import threading
import time
from thirdparty.enet.bindings import (
    ENetAddress,
    ENetEvent,
    ENetEventType,
    byref,
    enet_address_set_host,
    enet_host_compress_with_range_coder,
    enet_host_create,
    enet_host_service,
    enet_host_use_crc32,
    enet_host_use_new_packet_for_server,
)


class Server:
    def __init__(self, host: str, port: int) -> None:
        self.addr = ENetAddress(port=port)
        enet_address_set_host(byref(self.addr), host.encode())

        self.host = enet_host_create(byref(self.addr), 1, 2, 0, 0)
        if not self.host:
            raise RuntimeError("host is null")
        enet_host_compress_with_range_coder(self.host)
        enet_host_use_crc32(self.host)
        enet_host_use_new_packet_for_server(self.host)

        self._thread_id: threading.Thread | None = None

    def start(self, block: bool = False) -> None:
        if block:
            try:
                self._thread()
            except (InterruptedError, KeyboardInterrupt):
                pass
        else:
            self._thread_id = threading.Thread(target=self._thread)
            self._thread_id.start()

    def _thread(self) -> None:
        while True:
            event = ENetEvent()
            if enet_host_service(self.host, byref(event), 0) > 0:
                if event.type == ENetEventType.CONNECT:
                    print(event)
                elif event.type == ENetEventType.RECEIVE:
                    print(event)
                elif event.type == ENetEventType.DISCONNECT:
                    print(event)
            time.sleep(0.01)
