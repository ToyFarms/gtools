import ctypes
import hashlib
import platform
import click
import winreg
import socket
import struct
from ctypes import wintypes
from gtools.core.growtopia.crypto import rolling_chksum, hex_rolling_shift, rolling_chksum2, rolling_shift, proton_hash
from gtools.core.x86.cpuid import cpuid_checksum


def get_vsn(drive: str) -> str | None:
    volume_serial_number = ctypes.c_uint32()
    max_component_length = ctypes.c_uint32()
    file_system_flags = ctypes.c_uint32()

    res = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(drive),
        None,
        0,
        ctypes.byref(volume_serial_number),
        ctypes.byref(max_component_length),
        ctypes.byref(file_system_flags),
        None,
        0,
    )
    if res == 0:
        return
    return f"{volume_serial_number.value:08X}"


def get_any_vsn() -> str:
    for drive in "CDEFG":
        if vsn := get_vsn(f"{drive}:\\"):
            return vsn

    return ""

AF_INET = 2
GAA_FLAG_SKIP_ANYCAST = 0x0002
GAA_FLAG_SKIP_MULTICAST = 0x0004
GAA_FLAG_SKIP_FRIENDLY_NAME = 0x0020

class SOCKADDR(ctypes.Structure):
    _fields_ = [
        ("sa_family", ctypes.c_ushort),
        ("sa_data", ctypes.c_byte * 14),
    ]

class SOCKET_ADDRESS(ctypes.Structure):
    _fields_ = [
        ("lpSockaddr", ctypes.POINTER(SOCKADDR)),
        ("iSockaddrLength", ctypes.c_int),
    ]

class IP_ADAPTER_UNICAST_ADDRESS(ctypes.Structure):
    pass

IP_ADAPTER_UNICAST_ADDRESS._fields_ = [
    ("Length", wintypes.ULONG),
    ("Flags", wintypes.DWORD),
    ("Next", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS)),
    ("Address", SOCKET_ADDRESS),
    ("PrefixOrigin", ctypes.c_int),
    ("SuffixOrigin", ctypes.c_int),
    ("DadState", ctypes.c_int),
    ("ValidLifetime", wintypes.ULONG),
    ("PreferredLifetime", wintypes.ULONG),
    ("LeaseLifetime", wintypes.ULONG),
    ("OnLinkPrefixLength", ctypes.c_ubyte),
]

class IP_ADAPTER_DNS_SERVER_ADDRESS(ctypes.Structure):
    pass

IP_ADAPTER_DNS_SERVER_ADDRESS._fields_ = [
    ("Length", wintypes.ULONG),
    ("Reserved", wintypes.DWORD),
    ("Next", ctypes.POINTER(IP_ADAPTER_DNS_SERVER_ADDRESS)),
    ("Address", SOCKET_ADDRESS),
]

class IP_ADAPTER_ADDRESSES(ctypes.Structure):
    pass

IP_ADAPTER_ADDRESSES._fields_ = [
    ("Length", wintypes.ULONG),
    ("IfIndex", wintypes.DWORD),
    ("Next", ctypes.POINTER(IP_ADAPTER_ADDRESSES)),
    ("AdapterName", ctypes.c_char_p),
    ("FirstUnicastAddress", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS)),
    ("FirstAnycastAddress", ctypes.c_void_p),
    ("FirstMulticastAddress", ctypes.c_void_p),
    ("FirstDnsServerAddress", ctypes.POINTER(IP_ADAPTER_DNS_SERVER_ADDRESS)),
    ("DnsSuffix", ctypes.c_wchar_p),
    ("Description", ctypes.c_wchar_p),
    ("FriendlyName", ctypes.c_wchar_p),
    ("PhysicalAddress", ctypes.c_ubyte * 8),
    ("PhysicalAddressLength", wintypes.DWORD),
    ("Flags", wintypes.DWORD),
    ("Mtu", wintypes.DWORD),
    ("IfType", wintypes.DWORD),
    ("OperStatus", ctypes.c_int),
]


class AdapterInfo:
    def __init__(self):
        self.friendly_name = ""
        self.description = ""
        self.ip_address = ""
        self.ip_address_int = 0
        self.mac_address = "WINNONE"
        self.mac_bytes = bytearray(6)
        self.dns_server = ""


def get_adapters() -> list[AdapterInfo]:
    iphlpapi = ctypes.windll.iphlpapi

    size = wintypes.ULONG(0x4000)
    buffer = ctypes.create_string_buffer(size.value)

    result = iphlpapi.GetAdaptersAddresses(
        AF_INET,  # Family (IPv4)
        0,        # Flags
        None,     # Reserved
        ctypes.cast(buffer, ctypes.POINTER(IP_ADAPTER_ADDRESSES)),
        ctypes.byref(size)
    )

    if result != 0:
        return []

    adapter_count = 0
    current = ctypes.cast(buffer, ctypes.POINTER(IP_ADAPTER_ADDRESSES))

    while current:
        if current.contents.FirstUnicastAddress:
            unicast = current.contents.FirstUnicastAddress
            while unicast:
                if unicast.contents.Address.lpSockaddr.contents.sa_family == AF_INET:
                    adapter_count += 1
                    break
                unicast = unicast.contents.Next
        current = current.contents.Next

    adapters = []
    current = ctypes.cast(buffer, ctypes.POINTER(IP_ADAPTER_ADDRESSES))

    while current:
        adapter = current.contents
        unicast = adapter.FirstUnicastAddress
        while unicast:
            if unicast.contents.Address.lpSockaddr.contents.sa_family == AF_INET:
                info = AdapterInfo()
                sockaddr = unicast.contents.Address.lpSockaddr.contents
                ip_bytes = bytes((b & 0xFF) for b in sockaddr.sa_data[2:6])
                info.ip_address_int = struct.unpack('>I', ip_bytes)[0]
                info.ip_address = socket.inet_ntoa(ip_bytes)

                if adapter.PhysicalAddressLength > 0:
                    mac_bytes = bytes(adapter.PhysicalAddress[:6])
                    info.mac_bytes = bytearray(mac_bytes)
                    info.mac_address = ':'.join(f'{b:02x}' for b in mac_bytes)

                dns = adapter.FirstDnsServerAddress
                while dns:
                    dns_sockaddr = dns.contents.Address.lpSockaddr.contents

                    if dns_sockaddr.sa_family == AF_INET:
                        dns_ip_bytes = bytes((b & 0xFF) for b in dns_sockaddr.sa_data[2:6])
                        info.dns_server = socket.inet_ntoa(dns_ip_bytes)
                        break

                    dns = dns.contents.Next

                if adapter.FriendlyName:
                    info.friendly_name = adapter.FriendlyName

                if adapter.Description:
                    info.description = adapter.Description

                adapters.append(info)
                break
            unicast = unicast.contents.Next
        current = adapter.Next

    return adapters


def get_primary_adapter(adapters: list[AdapterInfo]) -> AdapterInfo | None:
    if not adapters:
        return None

    for adapter in adapters:
        if adapter.dns_server:
            return adapter

    return None


def get_computer_mac() -> str:
    adapters = get_adapters()
    primary = get_primary_adapter(adapters)

    return primary.mac_address if primary else "WINNONE"


def get_machine_guid() -> bytes:
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ) as key:
        machine_guid, _ = winreg.QueryValueEx(key, r"MachineGuid")
        return machine_guid.encode()


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
