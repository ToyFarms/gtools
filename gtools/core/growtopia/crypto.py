def proton_hash(data: bytes) -> int:
    hash_val = 0x55555555

    for byte in data:
        if byte == 0:
            break
        hash_val = byte + ((hash_val & 0xFFFFFFFF) >> 27) + ((hash_val << 5) & 0xFFFFFFFF)
        hash_val &= 0xFFFFFFFF

    if hash_val & 0x80000000:
        hash_val -= 0x100000000

    return hash_val
