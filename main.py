import argparse
import logging
import multiprocessing as mp
import threading

from gtools.core.growtopia.packet import NetPacket
from gtools.core.utils.block_sigint import block_sigint
from gtools.core.utils.network import is_up, resolve_doh
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    DIRECTION_SERVER_TO_CLIENT,
    DIRECTION_UNSPECIFIED,
    INTEREST_TANK_PACKET,
    Interest,
    PendingPacket,
)
from gtools.proxy import login
from gtools.proxy.extension.broker import Broker
from gtools.proxy.extension.builtin.fast_drop import FastDropExtension
from gtools.proxy.extension.sdk import Extension
from gtools.proxy.proxy import Proxy
from thirdparty.enet.bindings import ENetPacketFlag


def run_proxy() -> None:
    server = login.setup_server()
    t = threading.Thread(target=lambda: server.serve_forever())
    t.start()
    Proxy().run()

    with block_sigint():
        server.shutdown()
        server.server_close()
        t.join()


def test_server() -> None:
    for host in ("www.growtopia1.com", "www.growtopia2.com"):
        print(f"checking for {host}")

        servers = resolve_doh(host)
        print(f"resolved ip: {servers}")

        should_break = False

        for server in servers:
            up = is_up(server)
            if up:
                should_break = True
            print(f"{server} status: {'ok' if up else 'unreachable'}")

        if should_break:
            break

        print("checking alternate host...")


def _run(e: type[Extension], *args) -> None:
    e(*args).start(block=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("-v", action="store_true")

    subparser = parser.add_subparsers(dest="cmd")

    subparser.add_parser("proxy")
    subparser.add_parser("ext_test")
    subparser.add_parser("test")

    args = parser.parse_args()

    class SimpleExtension(Extension):
        def __init__(self, name: str, priority: int) -> None:
            super().__init__(name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_BLOCK, direction=DIRECTION_UNSPECIFIED)])

        def process(self, event: PendingPacket) -> PendingPacket | None:
            p = NetPacket.deserialize(event.buf)
            p.tank.net_id = (p.tank.net_id * 31 + int(self._name.split(b"-")[-1].decode())) & 0xFFFFFFFF

            return self.forward(buf=p.serialize())

        def destroy(self) -> None:
            pass

    if args.v:
        logging.basicConfig(level=logging.DEBUG)

    if args.cmd == "test":
        test_server()
    elif args.cmd == "proxy":
        run_proxy()
    elif args.cmd == "ext_test":
        b = Broker()
        b.start()
        exts: list[mp.Process] = []

        p = mp.Process(target=_run, args=[FastDropExtension])
        p.start()
        exts.append(p)

        b.extension_len.wait_for(lambda x: x == len(exts), 5)

        buf = b"\x04\x00\x00\x00\x01\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xd4\x00\x00\x00\x02\x00\x02\x0f\x00\x00\x00OnDialogRequest\x01\x02\xb8\x00\x00\x00set_default_color|`o\nadd_label_with_icon|big|`wDrop Sign``|left|20|\nadd_textbox|How many to drop?|left|\nadd_text_input|count||3|5|\nembed_data|itemID|20\nend_dialog|drop_item|Cancel|OK|\n@"
        pkt = NetPacket.deserialize(buf)
        src = DIRECTION_SERVER_TO_CLIENT
        flags = ENetPacketFlag.NONE
        print(pkt)

        res = b.process_event(pkt, buf, src, flags)
        assert res

        processed, cancelled = res

        print(processed, f"cancelled={cancelled}")
        print(f"elapsed={int.from_bytes(processed.rtt_ns) / 1e6}us")
        print(processed.buf)

        for ext in exts:
            ext.terminate()
            ext.join()

        b.stop()
