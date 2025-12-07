from enum import Enum, auto
import logging
from queue import Queue
import threading
import time
import traceback
from typing import Generator, NamedTuple, cast
from gtools.core.eventbus import listen
from gtools.core.growtopia.packet import NetPacket, NetType, TankType
from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.variant import Variant
from gtools.core.utils.block_sigint import block_sigint
from gtools.proxy.enet import PyENetEvent
from gtools.proxy.event import UpdateServerData
from gtools.proxy.proxy_client import ProxyClient
from gtools.proxy.proxy_server import ProxyServer
from gtools.proxy.setting import _setting
from thirdparty.enet.bindings import ENetEventType, ENetPacketFlag
from thirdparty.hexdump import hexdump


class From(Enum):
    SERVER = auto()
    CLIENT = auto()


class ProxyEvent(NamedTuple):
    inner: PyENetEvent
    src: From


class Proxy:
    logger = logging.getLogger("proxy")

    def __init__(self) -> None:
        self.proxy_server = ProxyServer(_setting.proxy_server, _setting.proxy_port)
        self.logger.info(
            f"proxy server listening on {_setting.proxy_server}:{_setting.proxy_port}"
        )
        self.proxy_client = ProxyClient()
        self.logger.debug("proxy client initialized")

        self.server_data: UpdateServerData | None = None
        self.redirecting: bool = False
        self.running = True

        self._event_queue: Queue[ProxyEvent | None] = Queue()
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._should_reconnect = threading.Event()

        listen(UpdateServerData)(lambda ch, ev: self._on_server_data(ch, ev))

    def _on_server_data(self, _channel: str, event: UpdateServerData) -> None:
        self.logger.info(f"server_data: {event.server}:{event.port}")
        self.running = True
        self.server_data = event

    def _dump_packet(self, data: bytes) -> None:
        if self.logger.level > logging.DEBUG:
            return

        dump = cast(Generator[str, None, None], hexdump(data, result="generator"))
        self.logger.debug(f"\t{'\n\t'.join(dump)}")
        self.logger.debug(f"\t{data}")

    def _handle_client_to_server(
        self,
        data: bytes,
        _pkt: NetPacket,
        flags: ENetPacketFlag,
    ) -> None:
        self.proxy_client.send(data, flags)

    def _handle_server_to_client(
        self,
        data: bytes,
        pkt: NetPacket,
        flags: ENetPacketFlag,
    ) -> None:
        if pkt.type == NetType.TANK_PACKET:
            if pkt.tank.type == TankType.CALL_FUNCTION:
                v = Variant.deserialize(pkt.tank.extended_data)
                fn = v.as_string[0]
                if fn == b"OnSendToServer":
                    port = v.as_int[1]
                    server_data = StrKV.deserialize(v.as_string[4])

                    self.server_data = UpdateServerData(
                        server=server_data[0, 0].decode(),
                        port=port,
                    )
                    self.logger.info(
                        f"redirecting to {self.server_data.server}:{self.server_data.port}"
                    )

                    server_data[0, 0] = _setting.proxy_server
                    v[1] = Variant.vint(_setting.proxy_port)
                    v[4] = Variant.vstr(server_data.serialize())

                    pkt.tank.extended_data = v.serialize()

                    self.redirecting = True
                    self.proxy_server.send(pkt.serialize(), flags)
                    self.proxy_client.disconnect()

                    return
                elif fn == b"OnSuperMainStartAcceptLogonHrdxs47254722215a":
                    self.redirecting = False

        self.proxy_server.send(data, flags)

    def _handle(
        self,
        data: bytes,
        src: From,
        flags: ENetPacketFlag,
    ) -> None:
        pkt = NetPacket.deserialize(data)
        self.logger.debug(f"{pkt!r}")
        if pkt.type == NetType.TANK_PACKET:
            if pkt.tank.type in (
                TankType.APP_CHECK_RESPONSE,
                TankType.APP_INTEGRITY_FAIL,
            ):
                self.logger.debug(f"blocked {pkt.tank} from {src}")
                return
            elif pkt.tank.type == TankType.DISCONNECT:
                src_ = self.proxy_client if src == "proxy_client" else self.proxy_server
                src_.disconnect_now()
        if pkt.type == NetType.GAME_MESSAGE:
            if pkt.game_message["action", 1] == b"quit":
                self.disconnect_all()
                self.running = False

                return

        if src == From.CLIENT:
            self._handle_client_to_server(data, pkt, flags)
        elif src == From.SERVER:
            self._handle_server_to_client(data, pkt, flags)

    def disconnect_all(self) -> None:
        self.proxy_client.disconnect()
        self.proxy_server.disconnect()

        if self.proxy_server.peer:
            self.logger.debug("waiting for proxy_server to disconnect...")
            while self.proxy_server.peer:
                self.proxy_server.poll()
        if self.proxy_client.peer:
            self.logger.debug("waiting for proxy_client to disconnect...")
            while self.proxy_client.peer:
                self.proxy_client.poll()

    def _worker(self) -> None:
        self.logger.debug("starting packet worker thread")
        while not self._stop_event.is_set():
            proxy_event = self._event_queue.get()
            if proxy_event is None:
                self._event_queue.task_done()
                continue

            event = proxy_event.inner

            if proxy_event.src == From.CLIENT:
                self.logger.debug("from gt client:")
            elif proxy_event.src == From.SERVER:
                self.logger.debug("from gt server:")
                if event.type == ENetEventType.DISCONNECT:
                    self._should_reconnect.set()

            self.logger.debug(f"\t{ENetEventType(event.type)!r}")
            if event.type == ENetEventType.RECEIVE and event.packet.data:
                self._dump_packet(event.packet.data)
                self._handle(
                    event.packet.data,
                    proxy_event.src,
                    event.packet.flags,
                )

            self._event_queue.task_done()

        self.logger.debug("packet worker thread exited")

    def run(self) -> None:
        self.logger.info("proxy running")
        if self._worker_thread is None:
            self._worker_thread = threading.Thread(target=self._worker)
            self._worker_thread.start()

        try:
            while True:
                if not self.server_data:
                    self.logger.info("waiting for server_data...")
                    while not self.server_data:
                        time.sleep(0.16)

                self.logger.info("waiting for growtopia to connect...")
                while not self.proxy_server.peer:
                    self.proxy_server.poll()
                    time.sleep(0.16)

                self.logger.info(
                    f"proxy_client connecting to {self.server_data.server}:{self.server_data.port}"
                )
                self.proxy_client.connect(
                    self.server_data.server, self.server_data.port
                )
                self.logger.info("connected! now polling for events")

                MAX_POLL_MS = 100

                while True:
                    start = time.perf_counter()
                    while (event := self.proxy_server.poll()) and (
                        (time.perf_counter() - start) * 1000.0 < MAX_POLL_MS
                    ):
                        self._event_queue.put(ProxyEvent(event, From.CLIENT))

                    start = time.perf_counter()
                    while (event := self.proxy_client.poll()) and (
                        (time.perf_counter() - start) * 1000.0 < MAX_POLL_MS
                    ):
                        self._event_queue.put(ProxyEvent(event, From.SERVER))

                    if self._should_reconnect.is_set():
                        self.disconnect_all()
                        self._should_reconnect.clear()
                        break

                with self._event_queue.mutex:
                    self._event_queue.queue.clear()
                    self._event_queue.unfinished_tasks = 0
                    self._event_queue.all_tasks_done.notify_all()

        except (InterruptedError, KeyboardInterrupt):
            pass
        except Exception as e:
            traceback.print_exc()
            self.logger.error(f"failed: {e}")
        finally:
            with block_sigint():
                self.proxy_server.disconnect_now()
                self.proxy_client.disconnect_now()

                self.proxy_server.destroy()
                self.proxy_client.destroy()

                self._stop_event.set()
                self._event_queue.put(None)
                self._worker_thread.join()
