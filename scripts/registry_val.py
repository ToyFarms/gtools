import hashlib
import platform
import click
from gtools.core.growtopia.crypto import rolling_chksum, hex_rolling_shift, rolling_chksum2, rolling_shift, proton_hash
from gtools.core.windows.adapter import get_computer_mac
from gtools.core.windows.guid import get_machine_guid
from gtools.core.windows.vsn import get_any_vsn
from gtools.core.x86.cpuid import cpuid_checksum


@click.command()
def registry_val() -> None:
    if platform.system() != "Windows":
        print("\x1b[33mWARNING: running on something other than windows will result in different hardware id\x1b[0m")
    print("NOTE: if something differ, that means some hardware id has changed, you just need to force growtopia to regenerate it (by deleting the keys)")

    try:
        vsn = get_any_vsn()
    except Exception as e:
        print(f"failed to get vsn: {e}")
        vsn = input("input vsn (drive CDEFG, ex: DBA2CF12) > ")
    vsn_num = int(vsn, 16)
    vsn_hash = str(proton_hash(str(vsn_num).encode() + b"RT")).encode()

    print(f"{vsn=}")
    print(f"{vsn_hash=}")

    try:
        cpuid_leaf0 = cpuid_checksum()
    except Exception as e:
        print(f"failed to get cpuid: {e}")
        cpuid_leaf0 = int(input("input cpuid leaf0 (ex: 12758) > "))

    print(f"{cpuid_leaf0=}")

    try:
        machine_guid = get_machine_guid()
    except Exception as e:
        print(f"failed to get machine guid: {e}")
        machine_guid = input(r"input machine guid (ex: 6603fe66-9a80-4b75-9c12-5a70847a1173) > ").encode()

    print(f"{machine_guid=}")

    try:
        mac = get_computer_mac().encode()
    except Exception as e:
        print(f"failed to get mac: {e}")
        mac = input(r"input mac (ex: fa:ae:6c:ff:75:6d) > ").encode()
    print(f"{mac=}")

    key = cpuid_leaf0 + 1
    subkey = key >> 1

    v = rolling_shift(vsn_hash, 0xBE)
    vc = str(rolling_chksum(vsn_hash, 0x63BC)).encode()
    w = hex_rolling_shift(hashlib.md5(machine_guid).hexdigest().upper().encode())
    wc = str(rolling_chksum2(w, 0x63BC)).encode()

    vsn_hash_n = int(vsn_hash.decode())
    key2 = abs(int(vsn_hash_n / 3))
    subkey2 = abs(int(vsn_hash_n / 4))

    v2 = rolling_shift(mac, 0xBE)
    v2c = str(rolling_chksum(mac, 0x63BC)).encode()

    r = lambda x: " ".join([hex(y)[2:].rjust(2, "0") for y in x]) + " 00"

    print(rf"HKEY_CURRENT_USER\Software\Microsoft\{key}\{subkey} = {r(v)}")
    print(rf"HKEY_CURRENT_USER\Software\Microsoft\{key}\{subkey}c = {r(vc)}")
    print(rf"HKEY_CURRENT_USER\Software\Microsoft\{key}\{subkey}w = {r(w)}")
    print(rf"HKEY_CURRENT_USER\Software\Microsoft\{key}\{subkey}wc = {r(wc)}")
    print(rf"HKEY_CURRENT_USER\{key2}\{subkey2} = {r(v2)}")
    print(rf"HKEY_CURRENT_USER\{key2}\{subkey2}c = {r(v2c)}")
