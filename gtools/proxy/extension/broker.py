from bisect import insort
from collections import defaultdict
import logging
import threading
from typing import Iterator
import zmq

from gtools.protogen.extension_pb2 import Capability, CapabilityRequest, Packet
from gtools.protogen.growtopia_pb2 import Interest, InterestType


class Extension:
    def __init__(self, id: bytes, capability: list[Capability], interest: list[Interest]) -> None:
        self.id = id
        self.capability = capability
        self.interest = interest

    def is_interested(self) -> None:
        pass


class ExtensionManager:
    logger = logging.getLogger("extension_mgr")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._extensions: dict[bytes, Extension] = {}
        self._interest_map: defaultdict[InterestType, list[tuple[Extension, int]]] = defaultdict(list)

    def add_extension(self, extension: Extension) -> None:
        with self._lock:
            if extension.id in self._extensions:
                self.logger.warning(f"extension {extension.id} already exists, overwriting")
            self._extensions[extension.id] = extension
            for interest in extension.interest:
                ent = self._interest_map[interest.interest]
                insort(ent, (extension, interest.priority), key=lambda x: x[1])

    def remove_extension(self, id: bytes) -> None:
        with self._lock:
            if id not in self._extensions:
                self.logger.warning(f"extension {id} does not exists to be removed")
                return

            extension = self._extensions[id]
            for interest in extension.interest:
                ent = self._interest_map[interest.interest]
                ent.remove((extension, interest.priority))

            del self._extensions[id]

    def get_interested_extension(self, interest: InterestType) -> Iterator[Extension]:
        for extension, _ in self._interest_map[interest]:
            yield extension

    def get_extension(self, id: bytes) -> Extension:
        return self._extensions[id]


class Broker:
    logger = logging.getLogger("broker")

    def __init__(self, addr: str = "tcp://127.0.0.1:6712") -> None:
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.ROUTER)
        self.socket.bind(addr)

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        if self._thread is None:
            self._thread = threading.Thread(target=lambda: self._worker())
            self._thread.start()

        self.extension_mgr = ExtensionManager()

    def _recv(self) -> tuple[bytes, Packet]:
        extension, data = self.socket.recv_multipart()
        pkt = Packet()
        pkt.ParseFromString(data)

        self.logger.debug(f"recv {extension}: {pkt!r}")

        return extension, pkt

    def _send(self, extension: bytes, pkt: Packet) -> None:
        self.logger.debug(f"send {extension}: {pkt!r}")
        self.socket.send_multipart((extension, pkt.SerializeToString()))

    # @overload
    # def _broadcast(self, pkt: Packet) -> None: ...
    # @overload
    # def _broadcast(self, pkt: Callable[[bytes], None]) -> None: ...

    # def _broadcast(self, pkt: Packet | Callable[[bytes], None]) -> None:
    #     for extension in self.extension_mgr.keys():
    #         if isinstance(pkt, Packet):
    #             self._send(extension, pkt)
    #         else:
    #             pkt(extension)

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            id, pkt = self._recv()
            match pkt.type:
                case Packet.TYPE_HANDSHAKE:
                    self._send(id, Packet(type=Packet.TYPE_CAPABILITY_REQUEST, capability_request=CapabilityRequest()))
                case Packet.TYPE_CAPABILITY_RESPONSE:
                    self.extension_mgr.add_extension(
                        Extension(
                            id=id,
                            capability=list(pkt.capability_response.capability),
                            interest=list(pkt.capability_response.interest),
                        ),
                    )
                case Packet.TYPE_DISCONNECT:
                    self.extension_mgr.remove_extension(id)
