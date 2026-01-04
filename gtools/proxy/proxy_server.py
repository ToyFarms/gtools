from gtools.proxy.enet import ENetPeerBase, PyENetEvent
from thirdparty.enet.bindings import (
    ENetAddress,
    ENetEventType,
    byref,
    enet_address_set_host,
    enet_host_compress_with_range_coder,
    enet_host_create,
    enet_host_use_crc32,
    enet_host_use_new_packet_for_server,
    enet_peer_timeout,
)


class ProxyServer(ENetPeerBase):
    def __init__(self, host: str, port: int) -> None:
        self.addr = ENetAddress(port=port)
        enet_address_set_host(byref(self.addr), host.encode())

        self.peer = None
        self.host = enet_host_create(byref(self.addr), 1, 2, 0, 0)
        if not self.host:
            raise RuntimeError("host is null")
        enet_host_compress_with_range_coder(self.host)
        enet_host_use_crc32(self.host)
        enet_host_use_new_packet_for_server(self.host)

    def poll(self) -> PyENetEvent | None:
        event = super().poll()
        if event:
            if event.type == ENetEventType.CONNECT:
                self.logger.debug("growtopia client connected")
                self.peer = event.peer
                enet_peer_timeout(self.peer, 0, 30000, 0)
            elif event.type == ENetEventType.RECEIVE:
                pass
            elif event.type == ENetEventType.DISCONNECT:
                self.logger.debug("growtopia client disconnected")
                self.peer = None

        return event
