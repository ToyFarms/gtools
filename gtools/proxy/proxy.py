from enum import Enum, auto
import time
import traceback
from typing import Generator, Literal, NamedTuple, cast
from gtools.core.eventbus import listen
from gtools.core.growtopia.packet import NetPacket, NetType, TankType
from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.variant import Variant
from gtools.proxy.enet import PyENetEvent
from gtools.proxy.event import UpdateServerData
from gtools.proxy.proxy_client import ProxyClient
from gtools.proxy.proxy_server import ProxyServer
from gtools.proxy.setting import _setting
from thirdparty.enet.bindings import ENetEventType, ENetPacketFlag
from thirdparty.hexdump import hexdump


class From(Enum):
    Server = auto()
    Client = auto()


class ProxyEvent(NamedTuple):
    inner: PyENetEvent
    src: From


class Proxy:
    def __init__(self) -> None:
        self.proxy_server = ProxyServer(_setting.proxy_server, _setting.proxy_port)
        print(
            f"proxy server listening on {_setting.proxy_server}:{_setting.proxy_port}"
        )
        self.proxy_client = ProxyClient()
        print("proxy client initialized")

        self.server_data: UpdateServerData | None = None
        self.redirecting: bool = False
        self.running = True

        listen(UpdateServerData)(lambda ch, ev: self._on_server_data(ch, ev))

    def _on_server_data(self, _channel: str, event: UpdateServerData) -> None:
        print(f"server_data: {event.server}:{event.port}")
        self.running = True
        self.server_data = event

    def _dump_packet(self, data: bytes) -> None:
        dump = cast(Generator[str, None, None], hexdump(data, result="generator"))
        print(f"\t{'\n\t'.join(dump)}")
        print(f"\t{data}")

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
                    print(
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
        src: Literal["proxy_server", "proxy_client"],
        flags: ENetPacketFlag,
    ) -> None:
        pkt = NetPacket.deserialize(data)
        print(f"{pkt!r}")
        if pkt.type == NetType.TANK_PACKET:
            if pkt.tank.type in (
                TankType.APP_CHECK_RESPONSE,
                TankType.APP_INTEGRITY_FAIL,
            ):
                print(f"blocked {pkt.tank} from {src}")
                return
            elif pkt.tank.type == TankType.DISCONNECT:
                src_ = self.proxy_client if src == "proxy_client" else self.proxy_server
                src_.disconnect_now()
        if pkt.type == NetType.GAME_MESSAGE:
            if pkt.game_message["action", 1] == b"quit":
                self.proxy_client.disconnect()
                self.proxy_server.disconnect()

                print("waiting for proxy_server to disconnect...")
                while self.proxy_server.peer:
                    self.proxy_server.poll()
                print("waiting for proxy_client to disconnect...")
                while self.proxy_client.peer:
                    self.proxy_client.poll()

                self.running = False

                return

        if src == "proxy_server":
            self._handle_client_to_server(data, pkt, flags)
        elif src == "proxy_client":
            self._handle_server_to_client(data, pkt, flags)

    def run(self) -> None:
        print("proxy running")
        try:
            while True:
                # while not self.running:
                #     time.sleep(0.16)

                if not self.server_data:
                    print("waiting for server_data...")
                while not self.server_data:
                    time.sleep(0.16)

                print("waiting for growtopia to connect...")
                while not self.proxy_server.peer:
                    self.proxy_server.poll()
                    time.sleep(0.16)

                print(
                    f"proxy_client connecting to {self.server_data.server}:{self.server_data.port}"
                )
                self.proxy_client.connect(
                    self.server_data.server, self.server_data.port
                )
                print("connected! now polling for events")

                while True:
                    while pserver_event := self.proxy_server.poll():
                        print("from gt client:")
                        print(f"\t{ENetEventType(pserver_event.type)!r}")

                        if (
                            pserver_event.type == ENetEventType.RECEIVE
                            and pserver_event.packet.data
                        ):
                            self._dump_packet(pserver_event.packet.data)
                            self._handle(
                                pserver_event.packet.data,
                                "proxy_server",
                                pserver_event.packet.flags,
                            )

                    should_break = False

                    while pclient_event := self.proxy_client.poll():
                        print("from gt server:")
                        print(f"\t{ENetEventType(pclient_event.type)!r}")

                        if (
                            pclient_event.type == ENetEventType.RECEIVE
                            and pclient_event.packet.data
                        ):
                            self._dump_packet(pclient_event.packet.data)
                            self._handle(
                                pclient_event.packet.data,
                                "proxy_client",
                                pclient_event.packet.flags,
                            )

                        if pclient_event.type == ENetEventType.DISCONNECT:
                            should_break = True

                    if should_break:
                        break

        except (InterruptedError, KeyboardInterrupt):
            pass
        except Exception as e:
            traceback.print_exc()
            print(f"failed: {e}")
        finally:
            self.proxy_server.disconnect_now()
            self.proxy_client.disconnect_now()

            self.proxy_server.destroy()
            self.proxy_client.destroy()
