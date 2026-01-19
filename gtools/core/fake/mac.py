import secrets

BANNED_MAC_PREFIXES = {
    "00:05:69",  # VMware
    "00:0c:29",  # VMware
    "00:50:56",  # VMware
    "08:00:27",  # VirtualBox
    "00:15:5d",  # Microsoft Hyper-V
    "00:1c:42",  # Parallels
    "52:54:00",  # QEMU / KVM
    "00:16:3e",  # Xen
}


def _format_mac(mac_int: int) -> str:
    return ":".join(f"{(mac_int >> (8 * i)) & 0xFF:02x}" for i in reversed(range(6)))


def generate_random_mac(globally_administered: bool = True) -> str:
    for attempt in range(4096):
        mac_int = secrets.randbits(48)

        if mac_int == 0 or mac_int == (1 << 48) - 1:
            continue

        first_octet = (mac_int >> 40) & 0xFF
        first_octet &= 0b11111110

        if globally_administered:
            first_octet &= 0b11111101
        else:
            first_octet |= 0b00000010

        mac_int = (first_octet << 40) | (mac_int & ((1 << 40) - 1))
        prefix = ":".join(f"{(mac_int >> (8 * i)) & 0xFF:02x}" for i in reversed(range(6)))[:8]
        prefix = prefix.lower()
        prefix = ":".join(prefix.split(":")[:3])

        if prefix in BANNED_MAC_PREFIXES:
            continue

        return _format_mac(mac_int)

    raise RuntimeError("failed to generate mac for 4096 consecutive tries")

