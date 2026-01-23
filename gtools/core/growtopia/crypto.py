def proton_hash(data: bytes) -> int:
    hash_val = 0x55555555

    for byte in data:
        hash_val = byte + ((hash_val & 0xFFFFFFFF) >> 27) + ((hash_val << 5) & 0xFFFFFFFF)
        hash_val &= 0xFFFFFFFF

    if hash_val & 0x80000000:
        hash_val -= 0x100000000

    return hash_val


def rolling_chksum(buf: bytes, shift: int) -> int:
    chksum = 0
    for i, b in enumerate(buf):
        shifted = (b + shift + i + 2) & 0xFF
        chksum = (chksum + shift + i + shifted) & 0xFFFFFFFF

    return chksum


def rolling_chksum2(buf: bytes, shift: int) -> int:
    chksum = 0
    for i, b in enumerate(buf):
        chksum = (chksum + shift + i + b) & 0xFFFFFFFF

    return chksum


def rolling_shift(buf: bytes, shift: int) -> bytes:
    return bytes([(b + shift + i) & 0xFF for i, b in enumerate(buf)])


def hex_rolling_shift(buf: bytes) -> bytes:
    arr = bytearray(len(buf))

    for i, b in enumerate(buf):
        shift = 0x9E if chr(b) in ("abcdef") else 0xBE
        arr[i] = (b + shift + i) & 0xFF

    return bytes(arr)

