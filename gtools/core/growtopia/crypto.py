import ctypes
from datetime import datetime
import hashlib
import random
from gtools.core.dll_loader import DLL

crypto_lib = DLL("gtools/core/growtopia", "crypto")
if crypto_lib.supported:
    crypto_lib.proton_hash.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    crypto_lib.proton_hash.restype = ctypes.c_int32

    def proton_hash(data: bytes) -> int:
        data_size = len(data)
        return crypto_lib.proton_hash(data, data_size)

else:

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


class MersenneTwister:
    def __init__(self) -> None:
        self.mt = [0] * 624
        self.index = 625

    def seed(self, seed_value: int) -> None:
        self.mt[0] = seed_value
        self.index = 1

        for i in range(1, 624):
            self.mt[i] = (69069 * self.mt[i - 1]) & 0xFFFFFFFF

        self.index = 624

    def random(self, max_val: int) -> int:
        if max_val == 0:
            return 0

        if self.index >= 624:
            if self.index == 625:
                self.mt[0] = 4357
                self.index = 1
                for i in range(1, 624):
                    self.mt[i] = (69069 * self.mt[i - 1]) & 0xFFFFFFFF

            self._generate()

        y = self.mt[self.index]
        self.index += 1

        y ^= y >> 11
        y ^= (y << 7) & 0xFF3A58AD
        y ^= (y << 15) & 0xFFFFDF8C
        y ^= y >> 18

        return y % max_val

    def _generate(self) -> None:
        for i in range(624):
            y = (self.mt[i] & 0x80000000) + (self.mt[(i + 1) % 624] & 0x7FFFFFFF)
            self.mt[i] = self.mt[(i + 397) % 624] ^ (y >> 1)
            if y & 1:
                self.mt[i] ^= 0x9908B0DF

        self.index = 0


def generate_rid() -> str:
    now = datetime.now()
    month = now.month
    day = now.day
    year = now.year
    hour = now.hour
    second = now.second

    values = [0, 0, 0, 0]

    years_since_2014 = year - 2014
    temp1 = month + 12 * years_since_2014
    temp2 = day + 2 * temp1 + temp1
    temp3 = hour + 24 * temp2
    values[0] = second + 3600 * temp3

    r1 = random.randint(0, 0x7FFE) % 0x7FFF
    r2 = random.randint(0, 0x7FFE) % 0x7FFF
    r3 = random.randint(0, 0x7FFE) % 0x7FFF
    values[1] = (r2 * r1 + r3) & 0xFFFFFFFF

    r4 = random.randint(0, 0x7FFE) % 0x7FFF
    seed = (year + values[0] + r4) & 0xFFFFFFFF

    mt = MersenneTwister()
    mt.seed(seed)
    values[2] = mt.random(200000000)

    r5 = random.randint(0, 0x7FFE) % 0x7FFF
    r6 = random.randint(0, 0x7FFE) % 0x7FFF
    r7 = random.randint(0, 0x7FFE) % 0x7FFF
    values[3] = (r6 * r5 + r7) & 0xFFFFFFFF

    rid_parts = []
    for value in values:
        hex_str = format(value & 0xFFFFFFFF, "08X")
        rid_parts.append(hex_str)

    return "".join(rid_parts)


def extract_time_from_rid(rid: str) -> datetime:
    """NOTE: rid is reversible over the domain because of weird encoding:
    second e  [0, 3599]
    minute e  [0, 23]
    hour   e  [0, 2]
    month  e  [0, 11]
    year   >= 2014

    otherwise, there may be loss of information.
    but generally the year, month, hour, minute, second is pretty accurate
    """
    value0 = int(rid[:8], 16)

    second = value0 % 3600
    temp3 = value0 // 3600

    hour = temp3 % 24
    temp2 = temp3 // 24

    day = temp2 % 3
    temp1 = temp2 // 3

    month = temp1 % 12
    years_since_2014 = temp1 // 12

    year = 2014 + years_since_2014

    day += 1
    month += 1

    return datetime(year=year, month=month, day=day, hour=hour, second=second)


def md5(x: bytes) -> bytes:
    return hashlib.md5(x).hexdigest().upper().encode()


def sha256(x: bytes) -> bytes:
    return hashlib.sha256(x).hexdigest().lower().encode()


def generate_klv(protocol: bytes, version: bytes, rid: bytes) -> bytes:
    salts = [
        b"e9fc40ec08f9ea6393f59c65e37f750aacddf68490c4f92d0d2523a5bc02ea63",
        b"c85df9056ee603b849a93e1ebab5dd5f66e1fb8b2f4a8caef8d13b9f9e013fa4",
        b"3ca373dffbf463bb337e0fd768a2f395b8e417475438916506c721551f32038d",
        b"73eff5914c61a20a71ada81a6fc7780700fb1c0285659b4899bc172a24c14fc1",
    ]

    parts = [
        sha256(md5(sha256(protocol))) + salts[0],
        sha256(sha256(version)) + salts[1],
        sha256(md5(sha256(rid))) + salts[2],
        sha256(sha256(protocol) + salts[3]),
    ]

    return sha256(b"".join(parts))


# take this with a grain of salt, i just eyeballed this
def generate_klv_android(protocol: bytes, rid: bytes) -> bytes:
    salts = [
        b"f270bfe3092faf56e02b8740ed8a7390",
        b"c8f2bde4340c3c0fed4d550539489acc",
        b"cd439492ab5814c8665a720baabfbfb7",
        b"fba119844f893c112125f29cf858bedc",
    ]
    parts = [
        salts[0] + md5(md5(salts[0])),
        salts[1] + md5(md5(md5(md5(protocol)))),
        salts[2] + md5(md5(md5(rid))),
        salts[3],
    ]
    return md5(b"".join(parts))
