import argparse
import logging
import multiprocessing as mp
import os
from pathlib import Path
from queue import Queue
import sys
import threading
import time
from traceback import print_exc

from PIL import Image
import numpy as np
from pyglm.glm import ivec4

from gtools import flags
from gtools.core.block_sigint import block_sigint
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket
from gtools.core.growtopia.renderer.world_renderer import WorldRenderer
from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.world import World
from gtools.core.hosts import HostsFileManager
from gtools.core.log import setup_logger
from gtools.core.network import is_up, resolve_doh
from gtools.core.privilege import elevate, is_elevated, is_elevated_child
from gtools.core.wsl import is_running_wsl, windows_home
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    DIRECTION_SERVER_TO_CLIENT,
    DIRECTION_UNSPECIFIED,
    INTEREST_TANK_PACKET,
    Interest,
    PendingPacket,
)
from gtools.proxy.http_proxy import setup_server
from gtools.proxy.extension.broker import Broker
from gtools.proxy.extension.sdk import Extension, register_thread
from gtools.proxy.proxy import Proxy
from scripts.tileset import update_tile_connectivity
from thirdparty.enet.bindings import ENetPacketFlag
from gtools import setting
from extension.utils import UtilityExtension


def get_host_mgr() -> HostsFileManager:
    if is_running_wsl():
        return HostsFileManager("/mnt/c/Windows/System32/drivers/etc/hosts")
    else:
        return HostsFileManager()


hosts = ["www.growtopia1.com", "www.growtopia2.com"]


def ensure_enabled() -> None:
    m = get_host_mgr()
    if m.exists(hosts, include_disabled=True):
        m.enable(hosts)
        print(f"enabled {hosts}")
    else:
        for h in hosts:
            ent = m.get(h, include_disabled=True)
            if not ent:
                m.add("127.0.0.1", h, insert_after_hostname=hosts)
                print(f"added {h}")
                print(f"enabled {h}")
            elif ent.disabled:
                if len(ent.hostnames) > 1:
                    m.split_hostname(None, h, include_disabled=True)
                    print(f"split {ent}")
                    # m.enable(h)  # split makes it enabled by default
                    print(f"enabled {h}")
                else:
                    m.enable(h)
                    print(f"enabled {h}")


def ensure_disabled() -> None:
    m = get_host_mgr()
    if m.exists(hosts, include_disabled=True):
        m.disable(hosts)
        print(f"disabled {hosts}")
    else:
        for h in hosts:
            ent = m.get(h, include_disabled=True)
            if not ent:
                m.add("127.0.0.1", h, insert_after_hostname=hosts)
                print(f"added {h}")
                m.disable(h)
                print(f"disabled {h}")
            elif not ent.disabled:
                if len(ent.hostnames) > 1:
                    m.split_hostname(None, h)
                    print(f"split {ent}")
                    m.disable(h)
                    print(f"disabled {h}")
                else:
                    m.disable(h)
                    print(f"disabled {h}")


def check_hosts() -> None:
    m = get_host_mgr()

    ensure_enabled()  # also makes sure it exists
    replace_hostnames: list[str] = []

    if g := m.get("www.growtopia1.com"):
        if g.ip not in ("localhost", "127.0.0.1", "::1"):
            replace_hostnames.append("www.growtopia1.com")
            print(f"www.growtopia1.com hosts is not a loopback address ({g.ip})")
    if g := m.get("www.growtopia2.com"):
        if g.ip not in ("localhost", "127.0.0.1", "::1"):
            replace_hostnames.append("www.growtopia2.com")
            print(f"www.growtopia1.com hosts is not a loopback address ({g.ip})")

    if replace_hostnames:
        if not is_elevated():
            raise PermissionError()
        print("growtopia hosts found, but its not a loopback address")
        print("[1] do nothing")
        print(" 2  replace with a loopback address")
        print(" 3  change proxy target server to whats in the hosts file (replace)")
        match input("what do you want to do? "):
            case "2":
                if m.exists(replace_hostnames):
                    m.replace("127.0.0.1", replace_hostnames, keep_original=True)
                    print(f"changed {replace_hostnames} to 127.0.0.1")
                else:
                    for repl in replace_hostnames:
                        m.replace("127.0.0.1", repl, keep_original=True)
                        print(f"changed {repl} to 127.0.0.1")
            case "3":
                orig = None
                if m.exists(replace_hostnames):
                    orig = m.get(replace_hostnames[0])
                    m.replace("127.0.0.1", replace_hostnames, keep_original=True)
                    print(f"changed {replace_hostnames} to 127.0.0.1")
                else:
                    for repl in replace_hostnames:
                        if not orig:
                            orig = m.get(repl)
                        m.replace("127.0.0.1", repl, keep_original=True)
                        print(f"changed {repl} to 127.0.0.1")

                if orig:
                    setting.server_data_url = orig.ip
                    setting.save()  # no other way to transmit the information
                    print(f"changed proxy target server to {orig.ip}")


def run_proxy() -> None:
    try:
        check_hosts()
        if is_elevated_child():
            print("waiting 1s to sync up")
            time.sleep(1)
            exit(0)
    except PermissionError:
        elevate(wait_for_child=True)

    server = setup_server()
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
    _ = item_database.items()  # trigger cache
    parser = argparse.ArgumentParser()

    parser.add_argument("-v", action="store_true")

    subparser = parser.add_subparsers(dest="cmd")

    subparser.add_parser("proxy")
    subparser.add_parser("ext_test")
    subparser.add_parser("test")
    subparser.add_parser("stress")
    subparser.add_parser("world_test")

    render = subparser.add_parser("render")
    render.add_argument("world")

    host = subparser.add_parser("host")
    host_sub = host.add_subparsers(dest="host_op")
    host_sub.add_parser("enable")
    host_sub.add_parser("disable")
    host_sub.add_parser("status")
    host_sub.add_parser("ensure")
    host_sub.add_parser("restore")

    args = parser.parse_args()

    class SimpleExtension(Extension):
        def __init__(self, name: str, priority: int) -> None:
            super().__init__(name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_BLOCK, direction=DIRECTION_UNSPECIFIED)])

        def process(self, event: PendingPacket) -> PendingPacket | None:
            p = NetPacket.deserialize(event.buf)
            p.tank.net_id = (p.tank.net_id * 31 + int(self._name.split(b"-")[-1].decode())) & 0x7FFFFFFF
            event.buf = p.serialize()

            return self.forward(event)

        def destroy(self) -> None:
            pass

    level = logging.DEBUG if args.v else logging.INFO
    setup_logger(log_dir=setting.appdir / "logs", level=level)

    if args.cmd == "test":
        test_server()
    elif args.cmd == "proxy":
        run_proxy()
    elif args.cmd == "host":
        m = get_host_mgr()
        if args.host_op in ("enable", "disable"):
            bak_path = m.backup()
            print(f"backed up {m.hosts_path} to {bak_path}")
            if elevate():
                if args.host_op == "enable":
                    ensure_enabled()
                elif args.host_op == "disable":
                    ensure_disabled()
        elif args.host_op == "status":
            for x in ("www.growtopia1.com", "www.growtopia2.com"):
                ent = m.get(x, include_disabled=True)
                print(f"{x}: {'None' if not ent else f'{ent.ip} (disabled)' if ent.disabled else f'{ent.ip} (enabled)'}")
        elif args.host_op == "ensure":
            check_hosts()
        elif args.host_op == "restore":
            if elevate():
                bak = m.restore()
                print(f"successfully restored from {bak}")
                exit(0)
    elif args.cmd == "ext_test":
        b = Broker()
        b.start()
        exts: list[mp.Process] = []

        p = mp.Process(target=_run, args=[UtilityExtension])
        p.start()
        exts.append(p)

        b.extension_len.wait_until(lambda x: x == len(exts), 5)

        buf = b"\x04\x00\x00\x00\x01\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xd4\x00\x00\x00\x02\x00\x02\x0f\x00\x00\x00OnDialogRequest\x01\x02\xb8\x00\x00\x00set_default_color|`o\nadd_label_with_icon|big|`wDrop Sign``|left|20|\nadd_textbox|How many to drop?|left|\nadd_text_input|count||3|5|\nembed_data|itemID|20\nend_dialog|drop_item|Cancel|OK|\n@"
        pkt = PreparedPacket(
            NetPacket.deserialize(buf),
            DIRECTION_SERVER_TO_CLIENT,
            ENetPacketFlag.NONE,
        )
        print(pkt)

        res = b.process_event(pkt)
        assert res

        processed, cancelled = res

        print(processed, f"cancelled={cancelled}")
        print(f"elapsed={processed._rtt_ns / 1e6}us")
        print(processed.buf)

        for ext in exts:
            ext.terminate()
            ext.join()

        b.stop()
    elif args.cmd == "stress":
        if not flags.BENCHMARK:
            os.environ["BENCHMARK"] = "1"
            os.execvpe(sys.executable, [sys.executable] + sys.argv, os.environ)

        class Stress(Extension):
            def __init__(self) -> None:
                super().__init__(name="stress", interest=[Interest(interest=INTEREST_TANK_PACKET, priority=0, blocking_mode=BLOCKING_MODE_BLOCK, direction=DIRECTION_UNSPECIFIED)])

            @register_thread
            def thread_spam(self) -> None:
                p = PreparedPacket(packet=NetPacket(type=NetType.GAME_MESSAGE, data=StrKV([[b"test", b"1"]])), direction=DIRECTION_SERVER_TO_CLIENT, flags=ENetPacketFlag.RELIABLE)
                while True:
                    self.push(p)

            def process(self, _event: PendingPacket) -> PendingPacket | None:
                pass

            def destroy(self) -> None:
                pass

        q = Queue()
        b = Broker(q)
        b.start()

        p = mp.Process(target=_run, args=[Stress])
        p.start()

        try:
            while True:
                q.get()
        except (KeyboardInterrupt, InterruptedError):
            pass

        p.terminate()
        p.join()
        b.stop()
    elif args.cmd == "world_test":
        for f in (windows_home() / ".gtools/world").glob("*"):
            try:
                World.from_tank(f.read_bytes())
            except:
                print(f"parsing {f} failed")
    elif args.cmd == "render":
        renderer = WorldRenderer()
        world = World.from_tank(Path(args.world).read_bytes())

        img = np.zeros((world.height * 32, world.width * 32, 4), dtype=np.uint8)
        start = time.perf_counter()
        try:
            for tile in world.tiles:
                update_tile_connectivity(world, tile)
        except Exception as e:
            print_exc()

        for i, tile in enumerate(world.tiles):
            if i == world.garbage_start:
                break
            try:
                for cmd in renderer.get_render_cmd(tile):
                    for dst in cmd.dst:
                        dst = ivec4(dst)
                        alpha_mask = cmd.buffer[:, :, 3] > 4
                        dst_slice = img[dst.y : dst.y + dst.z, dst.x : dst.x + dst.w, :]
                        dst_slice[alpha_mask] = cmd.buffer[:, :, : dst_slice.shape[2]][alpha_mask]
            except:
                break
        print(f"rendering took {time.perf_counter() - start:.3f}s")

        Image.fromarray(img).show()
