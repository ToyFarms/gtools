import hashlib
from pathlib import Path
import platform
import click

from gtools.core.growtopia.crypto import generate_klv, generate_rid, proton_hash
from gtools.core.wsl import windows_home
from gtools.core.windows.adapter import get_computer_mac
from gtools.core.windows.guid import get_machine_guid
from gtools.core.windows.vsn import get_any_vsn


@click.command()
@click.argument("game_version", default="5.4")
@click.argument("protocol", default="225")
@click.argument("rid", default=None)
@click.argument("gt_path", default=windows_home() / "AppData/Local/Growtopia/growtopia.exe", type=Path)
def login_val(game_version: str, protocol: str, rid: str | None, gt_path: Path) -> None:
    if platform.system() != "Windows":
        print("\x1b[33mWARNING: running on something other than windows will result in different hardware id\x1b[0m")

    gt_buf = gt_path.read_bytes()

    rid_gen = rid is None
    if rid is None:
        print("using generated rid, values may be different")
        rid = generate_rid()

    print("? = not deterministic, depends on setting")
    print(f"f             = ?0")
    print(f"protocol      = {protocol}")
    print(f"game_version  = {game_version}")
    print(f"fz            = {len(gt_buf)}")
    print(f"cbits         = ?0")
    print(f"player_age    = ?25")
    print(f"GDPR          = ?2")
    print(f"FCMToken      = ?")
    print(f"category      = ?_-5100")
    print(f"totalPlaytime = 0")
    print(f"klv           = {generate_klv(protocol.encode(), game_version.encode(), rid.encode())}")
    print(f"hash2         = {proton_hash(get_computer_mac().encode() + b'RT')}")
    print(f"meta          = ?")
    print(f"fhash         = {proton_hash(b'tankIDName|tankIDPass|requestedName|f|protocol|game_version|fz|lmode|cbits|hash2|vid|aid|gid|meta|rid|platformID|deviceVersion|country|hash|mac|reconnect|1\nuser|token|doorID|ProductIdwk|fhash|')}")
    print(f"rid           = {'?' if rid_gen else ''}{rid}")
    print(f"platformID    = ?0,1,1")
    print(f"deviceVersion = ?0")
    print(f"country       = ?us")
    print(f"hash          = {proton_hash(get_any_vsn().encode() + b'RT')}")
    print(f"mac           = {get_computer_mac()}")
    print(f"wk            = {hashlib.md5(get_machine_guid()).hexdigest().upper()}")
    print(f"zf            = {proton_hash(gt_buf)}lmode|1")
    print(f"user          = ?")
    print(f"token         = ?")
    print(f"UUIDToken     = ?")
    print(f"doorID        = ?")
    print(f"aat           = ?")
