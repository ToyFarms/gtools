import ctypes
from dataclasses import dataclass
import logging
from types import GenericAlias

from thirdparty.enet.bindings import (
    ENetAddress,
    ENetEvent,
    ENetEventType,
    ENetPacket,
    ENetPacketFlag,
    ENetPeer,
    enet_address_set_host,
    enet_host_connect,
    enet_host_destroy,
    enet_host_service,
    enet_packet_create,
    enet_packet_destroy,
    enet_peer_disconnect,
    enet_peer_disconnect_now,
    enet_peer_send,
    enet_peer_timeout,
)


class POINTER[T](ctypes._Pointer):
    class _GenericAlias(GenericAlias):
        def __repr__(self) -> str:
            val = super().__repr__()
            ibra = val.find("[")
            idot = val.rfind(".", 0, ibra)
            return f"{val[:idot+1]}POINTER{val[ibra:]}"

    def __class_getitem__(cls, *args) -> _GenericAlias:
        ptrtype = ctypes.POINTER(*args)
        alias = POINTER._GenericAlias(ptrtype, *args)
        return alias


@dataclass
class PyENetPacket:
    data: bytes | None
    flags: ENetPacketFlag


@dataclass
class PyENetEvent:
    type: ENetEventType
    peer: POINTER[ENetPeer]
    packet: PyENetPacket

    @classmethod
    def new(cls, event: ENetEvent) -> "PyENetEvent":
        data: bytes | None = None
        flags = ENetPacketFlag(0)
        if event.type == ENetEventType.RECEIVE:
            packet = ctypes.cast(event.packet, ctypes.POINTER(ENetPacket)).contents
            data = ctypes.string_at(packet.data, packet.dataLength)
            flags = ENetPacketFlag(packet.flags)
            enet_packet_destroy(event.packet)

        return cls(
            type=ENetEventType(event.type),
            peer=event.peer,
            packet=(PyENetPacket(data=data, flags=flags)),
        )


class ENetPeerBase:
    host: ctypes.c_void_p
    addr: ENetAddress | None
    peer: POINTER[ENetPeer] | None
    logger = logging.getLogger("enet_peer")

    def connect(self, host: str, port: int) -> None:
        if self.peer:
            self.logger.warning(
                f"attempting to connect to {host}:{port}, but peer still connected"
            )
            return

        self.addr = ENetAddress(port=port)
        enet_address_set_host(ctypes.byref(self.addr), host.encode())

        self.peer = enet_host_connect(self.host, ctypes.byref(self.addr), 2, 0)
        enet_peer_timeout(self.peer, 0, 0, 60000)

    def disconnect(self) -> None:
        if not self.peer:
            return

        enet_peer_disconnect(self.peer, 0)
        self.peer = None

    def disconnect_now(self) -> None:
        if not self.peer:
            return

        enet_peer_disconnect_now(self.peer, 0)
        self.peer = None

    def send(
        self, data: bytes, flags: ENetPacketFlag = ENetPacketFlag.RELIABLE
    ) -> None:
        if not self.peer:
            return

        pkt = enet_packet_create(data, len(data), flags)
        enet_peer_send(self.peer, 0, pkt)

    def destroy(self) -> None:
        if not self.host:
            return

        enet_host_destroy(self.host)

    def poll(self) -> PyENetEvent | None:
        event = ENetEvent()
        if enet_host_service(self.host, ctypes.byref(event), 16) > 0:
            if event.type == ENetEventType.CONNECT:
                return PyENetEvent.new(event)
            elif event.type == ENetEventType.RECEIVE:
                return PyENetEvent.new(event)
            elif event.type == ENetEventType.DISCONNECT:
                return PyENetEvent.new(event)
