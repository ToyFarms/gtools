import argparse
import logging
import os
import signal
import threading
import time

from gtools.core.growtopia.packet import NetPacket
from gtools.core.utils.block_sigint import block_sigint
from gtools.core.utils.network import is_up, resolve_doh
from gtools.protogen.extension_pb2 import BLOCKING_MODE_BLOCK, DIRECTION_CLIENT_TO_SERVER, DIRECTION_SERVER_TO_CLIENT, DIRECTION_UNSPECIFIED, INTEREST_TANK_PACKET, Event, Forward, Interest, Packet
from gtools.proxy import login
from gtools.proxy.extension.broker import Broker
from gtools.proxy.extension.builtin.fast_drop import FastDropExtension
from gtools.proxy.extension.builtin.command import CommandExtension
from gtools.proxy.extension.sdk import Extension
from gtools.proxy.proxy import From, Proxy


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("-v", action="store_true")

    subparser = parser.add_subparsers(dest="cmd")
    subparser.add_parser("proxy")

    ext = subparser.add_parser("ext_test")

    args = parser.parse_args()

    class SimpleExtension(Extension):
        def __init__(self, name: str, priority: int) -> None:
            super().__init__(name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_BLOCK, direction=DIRECTION_UNSPECIFIED)])

        def process(self, event: Event) -> Packet | None:
            p = NetPacket.deserialize(event.buf)
            p.tank.net_id = (p.tank.net_id * 31 + int(self._name.split(b"-")[-1].decode())) & 0xFFFFFFFF

            return Packet(type=Packet.TYPE_FORWARD, forward=Forward(buf=p.serialize()))

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
        pids = []

        pid = os.fork()
        if pid == 0:
            e = FastDropExtension()
            e.start(block=True)
            exit(0)
        elif pid > 0:
            pids.append(pid)
        else:
            exit(1)

        pid = os.fork()
        if pid == 0:
            e = CommandExtension()
            e.start(block=True)
            exit(0)
        elif pid > 0:
            pids.append(pid)
        else:
            exit(1)

        time.sleep(0.5)

        buf = b'\x04\x00\x00\x00\x01\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xd4\x00\x00\x00\x02\x00\x02\x0f\x00\x00\x00OnDialogRequest\x01\x02\xb8\x00\x00\x00set_default_color|`o\nadd_label_with_icon|big|`wDrop Sign``|left|20|\nadd_textbox|How many to drop?|left|\nadd_text_input|count||3|5|\nembed_data|itemID|20\nend_dialog|drop_item|Cancel|OK|\n@'
        pkt = NetPacket.deserialize(buf)
        src = DIRECTION_SERVER_TO_CLIENT
        print(pkt)

        res = b.process_event(pkt, buf, src)

        if res:
            pkt = res[0]
            src = From.CLIENT if res[1] == DIRECTION_CLIENT_TO_SERVER else From.SERVER if res[1] == DIRECTION_SERVER_TO_CLIENT else src

        print(pkt, src)
        print(pkt.serialize())

        for pid in pids:
            os.kill(pid, signal.SIGINT)

        b.stop()
