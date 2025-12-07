from gtools.proxy.enet import ENetPeerBase, PyENetEvent
from thirdparty.enet.bindings import (
    ENetEventType,
    enet_host_compress_with_range_coder,
    enet_host_create,
    enet_host_use_crc32,
    enet_host_use_new_packet,
)


class ProxyClient(ENetPeerBase):
    def __init__(self) -> None:
        self.addr = None
        self.peer = None
        self.host = enet_host_create(None, 1, 2, 0, 0)
        if not self.host:
            raise RuntimeError("host is null")
        enet_host_compress_with_range_coder(self.host)
        enet_host_use_crc32(self.host)
        enet_host_use_new_packet(self.host)

    def poll(self) -> PyENetEvent | None:
        event = super().poll()
        if event:
            if event.type == ENetEventType.CONNECT:
                self.logger.debug("connected to growtopia server")
            elif event.type == ENetEventType.RECEIVE:
                pass
            elif event.type == ENetEventType.DISCONNECT:
                self.logger.debug("disconnected from growtopia server")
                self.peer = None

        return event
