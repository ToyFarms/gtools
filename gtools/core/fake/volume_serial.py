import random
import time


def generate_volume_serial() -> int:
    tm = time.localtime()
    date = ((tm.tm_year - 1980) << 9) | ((tm.tm_mon) << 5) | tm.tm_mday
    time_part = (tm.tm_hour << 11) | (tm.tm_min << 5) | (tm.tm_sec // 2)
    vsn = (date << 16) | time_part
    vsn ^= random.randint(0, 2**32 - 1)
    return vsn
