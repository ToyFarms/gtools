import argparse
import logging
import multiprocessing as mp
import os
from pathlib import Path
from queue import Queue
import sys
import threading
import time
import traceback

from PIL import Image
import numpy as np
from pyglm.glm import ivec4, ivec2

from gtools import flags
from gtools.baked.items import COPPER_PLUMBING, STEAM_PIPE, STEAM_REVOLVER, STEAM_TUBES
from gtools.core.block_sigint import block_sigint
from gtools.core.color import color_tint, composite
from gtools.core.growtopia.items_dat import ItemFlag, ItemInfoTextureType, get_tex_stride, item_database
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket
from gtools.core.growtopia.rttex import RTTexManager
from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.world import World
from gtools.core.hosts import HostsFileManager
from gtools.core.log import setup_logger
from gtools.core.mixer import AudioMixer
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
from gtools.proxy.accountmgr import AccountManager
from gtools.proxy.http_proxy import setup_server as setup_http_proxy
from gtools.server.http_server import setup_server as setup_http_server
from gtools.proxy.extension.server.broker import Broker
from gtools.proxy.extension.client.sdk import Extension, register_thread
from gtools.proxy.proxy import Proxy
from gtools.server.server import Server
from thirdparty.enet.bindings import ENetPacketFlag
from gtools import setting
from gtools.setting import Setting
from extension.utils import UtilityExtension
from gtools.gui.app import App


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

    server = setup_http_proxy()
    t = threading.Thread(target=lambda: server.serve_forever())
    t.start()
    Proxy().start(block=True)

    with block_sigint():
        server.shutdown()
        server.server_close()
        t.join()


def run_server() -> None:
    server = setup_http_server()
    t = threading.Thread(target=lambda: server.serve_forever())
    t.start()

    Server(setting.server.enet_host, setting.server.enet_port).start(block=True)

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
    global_parent = argparse.ArgumentParser(add_help=False)
    global_parent.add_argument("-v", "--verbose", default=argparse.SUPPRESS, action="store_true", help="verbose logging")

    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose logging")
    subparsers = parser.add_subparsers(dest="cmd", help="sub-command to run")

    for name, help_txt in [
        ("proxy", "run the proxy"),
        ("server", "run the server"),
        ("ext_test", "run extension test"),
        ("test", "run network checks"),
        ("stress", "run stress extension"),
        ("world_test", "test world parsing"),
        ("gui", "run gui"),
    ]:
        subparsers.add_parser(name, parents=[global_parent], help=help_txt)

    render = subparsers.add_parser("render", parents=[global_parent], help="render a world file")
    render.add_argument("world", help="path to world packet file")

    music = subparsers.add_parser("music", parents=[global_parent], help="simulate world music")
    music.add_argument("world", help="path to world packet file")

    sett = subparsers.add_parser("setting", parents=[global_parent], help="manipulate settings")
    sett_sub = sett.add_subparsers(dest="setting_op", help="setting operation")
    sett_sub.add_parser("list", parents=[global_parent], help="list settings")
    sett_get = sett_sub.add_parser("get", parents=[global_parent], help="get setting(s)")
    sett_get.add_argument("name", nargs="*", help="setting name(s)")
    sett_set = sett_sub.add_parser("set", parents=[global_parent], help="set a setting key")
    sett_set.add_argument("key", help="setting key")
    sett_set.add_argument("value", help="setting value")
    sett_reset = sett_sub.add_parser("reset", parents=[global_parent], help="reset settings")
    sett_reset.add_argument("name", nargs="*", help="setting name(s) to reset")

    host = subparsers.add_parser("host", parents=[global_parent], help="manage hosts file entries")
    host_sub = host.add_subparsers(dest="host_op", help="host operation")
    host_sub.add_parser("enable", parents=[global_parent], help="enable hosts")
    host_sub.add_parser("disable", parents=[global_parent], help="disable hosts")
    host_sub.add_parser("status", parents=[global_parent], help="show hosts status")
    host_sub.add_parser("ensure", parents=[global_parent], help="ensure hosts exist and are loopback")
    host_sub.add_parser("restore", parents=[global_parent], help="restore hosts from backup")

    acc = subparsers.add_parser("acc", parents=[global_parent], help="account management")
    acc_sub = acc.add_subparsers(dest="acc_op", help="account operation")

    name_parent = argparse.ArgumentParser(add_help=False)
    name_parent.add_argument("name", nargs="*", help="account name(s)")

    acc_sub.add_parser("list", parents=[global_parent], help="list accounts")
    acc_sub.add_parser("remove", parents=[global_parent, name_parent], help="remove account(s)")
    acc_sub.add_parser("get", parents=[global_parent, name_parent], help="get/create account(s)")
    acc_sub.add_parser("renew", parents=[global_parent, name_parent], help="renew account(s)")

    args = parser.parse_args()

    if args.cmd is None:
        parser.print_help()
        sys.exit(1)

    if args.cmd == "setting" and getattr(args, "setting_op", None) is None:
        sett.print_help()
        sys.exit(1)

    if args.cmd == "host" and getattr(args, "host_op", None) is None:
        host.print_help()
        sys.exit(1)

    if args.cmd == "acc" and getattr(args, "acc_op", None) is None:
        acc.print_help()
        sys.exit(1)

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

    level = logging.DEBUG if args.verbose else logging.INFO
    setup_logger(log_dir=setting.appdir / "logs", level=level)

    if args.cmd == "test":
        test_server()
    elif args.cmd == "proxy":
        run_proxy()
    elif args.cmd == "server":
        run_server()
    elif args.cmd == "gui":
        app = App().run()
    elif args.cmd == "acc":
        repr = lambda x: "".join([f"{x['name']} [v{x.get('_version', 0)}]:\n", "\n".join([f"    {k}={v}" for k, v in x["ident"].items()])])
        if args.acc_op == "list":
            for acc in AccountManager.get_all():
                print(repr(acc))
        elif args.acc_op == "remove":
            for name in args.name:
                try:
                    removed = AccountManager.remove(name.encode())
                    print(f"removed {repr(removed)}")
                except KeyError:
                    print(f"account {name} does not exists")
        elif args.acc_op == "get":
            for name in args.name:
                if not AccountManager.exists(name.encode()):
                    added = AccountManager.get(name.encode())
                    print(f"added {repr(added)}")
                else:
                    print(f"{repr(AccountManager.get(name.encode()))}")
        elif args.acc_op == "renew":
            for name in args.name:
                if not AccountManager.exists(name.encode()):
                    print(f"no account named {name}")
                    continue
                prev = AccountManager.get(name.encode())
                new = AccountManager.renew(name.encode())
                print(f"from {repr(prev)}\nto\n{repr(new)}")
    elif args.cmd == "setting":
        if args.setting_op == "list":
            for k, v in setting.to_dict().items():
                print(f"{k} = {v}")
        elif args.setting_op == "get":
            for f in args.name:
                print(f"{f} = {getattr(setting, f)}")
        elif args.setting_op == "set":
            if not hasattr(setting, args.key):
                print(f"setting does not have field: {args.key}")
                exit(1)
            setattr(setting, args.key, Setting.convert_field_value(args.key, args.value))
            print(f"set {args.key} to {args.value}")
            setting.save()
        elif args.setting_op == "reset":
            default = Setting()
            if not args.name:
                setting = default
            else:
                for f in args.name:
                    print(f"resetting field {f} ({getattr(setting, f)} -> {getattr(default, f)})")
                    setattr(setting, f, getattr(default, f))
            setting.save()
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
        logger = logging.getLogger("world")
        logger.setLevel(logging.CRITICAL)
        logging.getLogger("tank_packet").setLevel(logging.CRITICAL)
        for f in (setting.appdir / "worlds").glob("*"):
            try:
                pkt = NetPacket.deserialize(f.read_bytes())
                w = World.from_tank(pkt.tank)
            except:
                print(f"\x1b[31mparsing {f} failed\x1b[0m")
                traceback.print_exc()
                break
    elif args.cmd == "render":
        world = World.from_tank(Path(args.world).read_bytes())

        bg_layer = np.zeros((world.height * 32, world.width * 32, 4), dtype=np.uint8)
        fg_layer = np.zeros((world.height * 32, world.width * 32, 4), dtype=np.uint8)
        bg_shadow_layer = np.zeros((world.height * 32, world.width * 32, 4), dtype=np.uint8)
        fg_shadow_layer = np.zeros((world.height * 32, world.width * 32, 4), dtype=np.uint8)

        start = time.perf_counter()

        def place(tex: np.ndarray, id: int, pos: ivec2, is_bg: bool, no_shadow: bool = False) -> None:
            if id <= 0:
                return

            item = item_database.get(id)

            if id in (STEAM_PIPE, COPPER_PLUMBING):
                seed = item_database.get(id + 1)
                tex = color_tint(tex, np.array([seed.seed_overlay_color.r, seed.seed_overlay_color.g, seed.seed_overlay_color.b, 255]))

            base_layer = bg_layer if is_bg else fg_layer
            shadow_layer = bg_shadow_layer if is_bg else fg_shadow_layer

            dst = ivec4(pos.x * 32, pos.y * 32, 32, 32)
            alpha_mask = tex[:, :, 3] > 4
            dst_slice = base_layer[dst.y : dst.y + dst.z, dst.x : dst.x + dst.w, :]
            dst_slice[alpha_mask] = tex[:, :, : dst_slice.shape[2]][alpha_mask]

            if not no_shadow and item.flags & ItemFlag.NO_SHADOW == 0:
                dst = ivec4(pos.x * 32, pos.y * 32, 32, 32)
                alpha_mask = tex[:, :, 3] > 4
                dst_slice = shadow_layer[dst.y : dst.y + dst.z, dst.x : dst.x + dst.w, :]
                dst_slice[..., :3][alpha_mask] = 0
                dst_slice[..., 3][alpha_mask] = tex[..., 3][alpha_mask]

        mgr = RTTexManager()
        for i, tile in world.tiles.items():
            if i == world.garbage_start:
                break

            place(tile.get_bg_texture(mgr), tile.bg_id, tile.pos, is_bg=True)
            place(tile.get_fg_texture(mgr), tile.fg_id, tile.pos, is_bg=False)

            if item_database.get(tile.fg_id).is_steam():
                anchor = item_database.get(STEAM_TUBES)
                stride = get_tex_stride(ItemInfoTextureType.SMART_EDGE)
                off = ivec2(tile.fg_tex_index % max(stride, 1), tile.fg_tex_index // stride if stride else 0)
                tex_pos = (ivec2((anchor.tex_coord_x + 1), anchor.tex_coord_y) + off) * 32

                place(mgr.get(setting.gt_path / "game" / anchor.texture_file.decode(), tex_pos.x, tex_pos.y, 32, 32), tile.fg_id, tile.pos, is_bg=False, no_shadow=True)
            if tile.fg_id == STEAM_REVOLVER:
                tex_pos, _ = tile.tex_pos(tile.fg_id, 0)
                tex_pos = (tex_pos + ivec2(0, 1)) * 32

                place(
                    mgr.get(setting.gt_path / "game" / item_database.get(tile.fg_id).texture_file.decode(), tex_pos.x, tex_pos.y, 32, 32),
                    tile.fg_id,
                    tile.pos,
                    is_bg=False,
                    no_shadow=True,
                )

        bg = composite(bg_layer, bg_shadow_layer, dx=-2, dy=2)
        fg = composite(fg_layer, fg_shadow_layer, dx=-2, dy=2)
        img = composite(fg, bg)

        print(f"rendering took {time.perf_counter() - start:.3f}s")

        Image.fromarray(img).show()
        time.sleep(1)
    elif args.cmd == "music":
        world = World.from_tank(Path(args.world).read_bytes())
        mixer = AudioMixer()
        mixer.master_gain = 0.7
        sheet = world.get_sheet(mixer)

        prev = time.time()
        try:
            while True:
                now = time.time()
                dt = now - prev
                prev = now

                sheet.update(dt)
                time.sleep(1 / 60)
        except KeyboardInterrupt:
            pass
        finally:
            mixer.stop()

# TODO: fix ui (its so ugly!!)
# TODO: implement shadow in world viewer
# TODO: fix PortraitTile for the world START (prob bcs old world version)
# TODO: implement override callback for connect, disconnect, destroy for extension sdk
