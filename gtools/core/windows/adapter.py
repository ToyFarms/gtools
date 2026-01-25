import ctypes
from ctypes import wintypes
import struct
import socket


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

    result = iphlpapi.GetAdaptersAddresses(AF_INET, 0, None, ctypes.cast(buffer, ctypes.POINTER(IP_ADAPTER_ADDRESSES)), ctypes.byref(size))  # Family (IPv4)  # Flags  # Reserved

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
                info.ip_address_int = struct.unpack(">I", ip_bytes)[0]
                info.ip_address = socket.inet_ntoa(ip_bytes)

                if adapter.PhysicalAddressLength > 0:
                    mac_bytes = bytes(adapter.PhysicalAddress[:6])
                    info.mac_bytes = bytearray(mac_bytes)
                    info.mac_address = ":".join(f"{b:02x}" for b in mac_bytes)

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
