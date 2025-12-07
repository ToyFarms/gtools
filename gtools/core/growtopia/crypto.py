def proton_hash(data: bytes, length: int | None = None) -> int:
    hash_val = 0x55555555

    if length is None:
        for byte in data:
            if byte == 0:
                break
            hash_val = (
                byte
                + ((hash_val & 0xFFFFFFFF) >> 27)
                + ((hash_val << 5) & 0xFFFFFFFFFFFFFFFF)
            )
            hash_val &= 0xFFFFFFFFFFFFFFFF
    else:
        for byte in data[:length]:
            hash_val = (
                byte
                + ((hash_val & 0xFFFFFFFF) >> 27)
                + ((hash_val << 5) & 0xFFFFFFFFFFFFFFFF)
            )
            hash_val &= 0xFFFFFFFFFFFFFFFF

    if hash_val & (1 << 63):
        return hash_val - (1 << 64)
    return hash_val
