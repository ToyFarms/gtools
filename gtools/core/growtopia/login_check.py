import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import logging
import re
from pathlib import Path
import threading
from typing import Any

from gtools.core.growtopia.crypto import generate_klv, proton_hash
from gtools.core.growtopia.strkv import StrKV
from gtools.core.wsl import is_running_wsl, windows_home
from gtools.setting import setting

VERSION_DB_PATH = setting.appdir / "login_checks.json"
logger = logging.getLogger("login_check")
_version_db_lock = threading.Lock()

REQUIRED_FIELDS = frozenset(
    {
        b"tankIDName",
        b"tankIDPass",
        b"requestedName",
        b"f",
        b"protocol",
        b"game_version",
        b"fz",
        b"cbits",
        b"player_age",
        b"GDPR",
        b"FCMToken",
        b"category",
        b"totalPlaytime",
        b"klv",
        b"hash2",
        b"meta",
        b"fhash",
        b"rid",
        b"platformID",
        b"deviceVersion",
        b"country",
        b"hash",
        b"mac",
        b"wk",
        b"zf",
        b"user",
        b"token",
        b"UUIDToken",
        b"doorID",
    }
)
OPTIONAL_FIELDS = frozenset({b"aat"})
EXPECTED_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS

FHASH_DATA = (
    b"tankIDName|tankIDPass|requestedName|f|protocol|game_version|fz|lmode|cbits|"
    b"hash2|vid|aid|gid|meta|rid|platformID|deviceVersion|country|hash|mac|"
    b"reconnect|1\nuser|token|doorID|ProductIdwk|fhash|"
)

_INT_RE = re.compile(rb"^-?\d+$")
_VERSION_RE = re.compile(rb"^\d+\.\d+(?:\.\d+)*$")
_FCM_RE = re.compile(rb"^[A-Za-z0-9_.:=+/~-]{1,4096}$")
_RID_RE = re.compile(rb"^[0-9A-F]{32}$")
_UUID_RE = re.compile(rb"^(?:[0-9A-Fa-f]{32}|-?\d+)?$")
_DOOR_RE = re.compile(rb"^(?:0|[A-Za-z0-9]{1,16})?$")
_MAC_RE = re.compile(rb"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
_HEX32_RE = re.compile(rb"^[0-9A-F]{32}$")
_HEX64_RE = re.compile(rb"^[0-9a-f]{64}$")
_ZF_RE = re.compile(rb"^(-?\d+)lmode\|(-?\d+)$")


def _get(pkt: StrKV, key: bytes) -> bytes | None:
    cell = pkt.get(key, 1)
    return None if cell is None else bytes(cell)


def _int(value: bytes | None) -> int | None:
    if value is None or not _INT_RE.fullmatch(value):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _local_mac() -> str | None:
    try:
        from gtools.core.windows.adapter import get_computer_mac

        return get_computer_mac()
    except Exception:
        return None


def _local_machine_guid() -> bytes | None:
    try:
        from gtools.core.windows.guid import get_machine_guid

        guid = get_machine_guid()
        return guid or None
    except Exception:
        return None


def _local_vsn() -> str | None:
    try:
        from gtools.core.windows.vsn import get_any_vsn

        return get_any_vsn()
    except Exception:
        return None


def validate(pkt: StrKV, gt_path: Path | None = None) -> list[str]:
    errors: list[str] = []

    def fail(field: str, message: str) -> None:
        errors.append(f"{field}: {message}")

    keys = [row[0] for row in pkt._data if row and row[0]]
    present = set(keys)

    for missing in sorted(REQUIRED_FIELDS - present):
        fail(missing.decode("ascii", "backslashreplace"), "missing field")

    for added in sorted(present - EXPECTED_FIELDS):
        fail(added.decode("ascii", "backslashreplace"), "unexpected field")

    seen: set[bytes] = set()
    for key in keys:
        if key in seen:
            fail(key.decode("ascii", "backslashreplace"), "duplicate field")
        seen.add(key)

    try:
        gt_bytes: bytes | None = setting.gt_path.read_bytes()
    except OSError as e:
        gt_bytes = None
        fail("growtopia.exe", f"cannot read {setting.gt_path}: {e}")

    local_mac = _local_mac()
    local_guid = _local_machine_guid()
    local_vsn = _local_vsn()

    swear_filter = _get(pkt, b"f")
    if swear_filter is None:
        fail("f", "missing value")
    elif swear_filter not in (b"0", b"1"):
        fail("f", "expected 0 or 1")

    protocol = _get(pkt, b"protocol")
    protocol_n = _int(protocol)
    if protocol_n is None:
        fail("protocol", "expected a positive integer")
    elif not 0 < protocol_n <= 0x7FFFFFFF:
        fail("protocol", "out of range")

    game_version = _get(pkt, b"game_version")
    if game_version is None:
        fail("game_version", "missing value")
    elif not _VERSION_RE.fullmatch(game_version):
        fail("game_version", "expected a dotted version such as 5.4 or 5.39")

    player_age = _get(pkt, b"player_age")
    player_age_n = _int(player_age)
    if player_age_n is None:
        fail("player_age", "expected an integer")
    elif not 0 <= player_age_n <= 150:
        fail("player_age", "out of range")

    gdpr = _get(pkt, b"GDPR")
    gdpr_n = _int(gdpr)
    if gdpr_n not in (1, 2, 3):
        fail("GDPR", "expected 1 (adult), 2 (child non-US), or 3 (child US)")

    fcm_token = _get(pkt, b"FCMToken")
    if fcm_token is None:
        fail("FCMToken", "missing value")
    elif fcm_token and not _FCM_RE.fullmatch(fcm_token):
        fail("FCMToken", "expected an empty value or a Firebase token")

    fz = _get(pkt, b"fz")
    fz_n = _int(fz)
    if fz_n is None:
        fail("fz", "expected an integer")
    elif fz_n <= 0:
        fail("fz", "expected a positive file size")
    elif gt_bytes is not None and fz_n != len(gt_bytes):
        fail("fz", f"expected {len(gt_bytes)} (size of growtopia.exe)")

    zf = _get(pkt, b"zf")
    if zf is None:
        fail("zf", "missing value")
    else:
        match = _ZF_RE.fullmatch(zf)
        if match is None:
            fail("zf", "expected <proton_hash>lmode|<mode>")
        else:
            zf_hash = int(match.group(1))
            lmode = int(match.group(2))
            if lmode < 0:
                fail("zf", "lmode must be non-negative")
            if gt_bytes is not None and zf_hash != proton_hash(gt_bytes):
                fail("zf", f"expected {proton_hash(gt_bytes)}lmode|{lmode}")

    klv = _get(pkt, b"klv")
    if klv is None:
        fail("klv", "missing value")
    elif not _HEX64_RE.fullmatch(klv):
        fail("klv", "expected 64 lowercase hexadecimal characters")
    elif protocol is not None and game_version is not None:
        rid_for_klv = _get(pkt, b"rid")
        if rid_for_klv is not None:
            try:
                expected_klv = generate_klv(protocol, game_version, rid_for_klv)
            except Exception as e:
                fail("klv", f"could not compute: {e}")
            else:
                if klv != expected_klv:
                    fail("klv", f"expected {expected_klv.decode()}")

    fhash = _get(pkt, b"fhash")
    fhash_n = _int(fhash)
    if fhash_n is None:
        fail("fhash", "expected an integer")
    else:
        expected_fhash = proton_hash(FHASH_DATA)
        if fhash_n != expected_fhash:
            fail("fhash", f"expected {expected_fhash}")

    hash2 = _get(pkt, b"hash2")
    hash2_n = _int(hash2)
    if hash2_n is None:
        fail("hash2", "expected an integer")
    elif local_mac is not None:
        mac_for_hash = b"" if local_mac.upper() == "WINNONE" else local_mac.encode()
        expected_hash2 = proton_hash(mac_for_hash + b"RT")
        if hash2_n != expected_hash2:
            fail("hash2", f"expected {expected_hash2}")

    volume_hash = _get(pkt, b"hash")
    volume_hash_n = _int(volume_hash)
    if volume_hash_n is None:
        fail("hash", "expected an integer")
    elif local_vsn is not None:
        expected_hashes = {proton_hash(b"RT")}
        if local_vsn:
            try:
                expected_hashes.add(proton_hash(str(int(local_vsn, 16)).encode() + b"RT"))
            except ValueError:
                pass
            expected_hashes.add(proton_hash(local_vsn.encode() + b"RT"))

        if volume_hash_n not in expected_hashes:
            fail("hash", f"expected one of {sorted(expected_hashes)}")

    mac = _get(pkt, b"mac")
    if mac is None:
        fail("mac", "missing value")
    elif mac != b"WINNONE" and not _MAC_RE.fullmatch(mac):
        fail("mac", "expected a MAC address or WINNONE")
    elif local_mac is not None and mac.decode("ascii", "replace").lower() != local_mac.lower():
        fail("mac", f"expected {local_mac}")

    wk = _get(pkt, b"wk")
    if wk is None:
        fail("wk", "missing value")
    elif not _HEX32_RE.fullmatch(wk):
        fail("wk", "expected 32 uppercase hexadecimal characters")
    elif local_guid is not None:
        expected_wk = hashlib.md5(local_guid).hexdigest().upper().encode()
        if wk != expected_wk:
            fail("wk", f"expected {expected_wk.decode()}")

    rid = _get(pkt, b"rid")
    if rid is None:
        fail("rid", "missing value")
    elif not _RID_RE.fullmatch(rid):
        fail("rid", "expected 32 uppercase hexadecimal characters")

    user = _get(pkt, b"user")
    if _int(user) is None:
        fail("user", "expected an integer")

    token = _get(pkt, b"token")
    if _int(token) is None:
        fail("token", "expected an integer")

    uuid_token = _get(pkt, b"UUIDToken")
    if uuid_token is None:
        fail("UUIDToken", "missing value")
    elif not _UUID_RE.fullmatch(uuid_token):
        fail("UUIDToken", "expected 32 hexadecimal characters, an integer, or empty")

    door_id = _get(pkt, b"doorID")
    if door_id is None:
        fail("doorID", "missing value")
    elif not _DOOR_RE.fullmatch(door_id):
        fail("doorID", "expected 0, empty, or a door ID")

    aat = _get(pkt, b"aat")
    if aat is not None and _int(aat) is None:
        fail("aat", "expected an integer")

    meta = _get(pkt, b"meta")
    if meta is None:
        fail("meta", "missing value")
    elif not meta or len(meta) % 4 or not re.fullmatch(rb"[A-Za-z0-9+/]*={0,2}", meta):
        fail("meta", "expected padded base64")
    else:
        try:
            decoded_meta = base64.b64decode(meta, validate=True)
        except (binascii.Error, ValueError):
            fail("meta", "expected padded base64")
        else:
            if len(decoded_meta) != 32:
                fail("meta", "expected 32 decoded bytes")

    return errors


def version_key(version: str, protocol: int | bytes) -> str:
    if isinstance(protocol, bytes):
        protocol = int(protocol)
    return f"{version}|{protocol}"


def _read_versions() -> dict[str, Any]:
    try:
        data = json.loads(VERSION_DB_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"could not read login version database {VERSION_DB_PATH}: {e}")
        return {}

    if not isinstance(data, dict):
        logger.warning(f"login version database {VERSION_DB_PATH} must contain a JSON object")
        return {}

    return data


def is_version_known(version: str, protocol: int | bytes) -> bool:
    with _version_db_lock:
        return version_key(version, protocol) in _read_versions()


def mark_version_known(version: str, protocol: int | bytes) -> bool:
    key = version_key(version, protocol)
    with _version_db_lock:
        data = _read_versions()
        data[key] = {
            "version": version,
            "protocol": int(protocol),
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

        tmp_path = VERSION_DB_PATH.with_name(VERSION_DB_PATH.name + ".tmp")
        try:
            tmp_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            tmp_path.replace(VERSION_DB_PATH)
        except OSError as e:
            logger.warning(f"could not write login version database {VERSION_DB_PATH}: {e}")
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    logger.info(f"remembered validated login version {key}")
    return True
