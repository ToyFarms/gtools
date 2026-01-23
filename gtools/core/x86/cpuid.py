import ctypes
import logging
from pathlib import Path
import platform

dir = Path("gtools/core/x86")
lib = None
logger = logging.getLogger("cpuid")

match platform.system():
    case "Windows":
        lib = ctypes.CDLL(dir / "cpuid.dll")
    case "Linux":
        lib = ctypes.CDLL(dir / "libcpuid.so")
    case _ as sys:
        logger.warning(f"cpuid instruction is not supported on {sys}")

if lib:
    lib.cpuid_checksum.restype = ctypes.c_int16


def cpuid_checksum() -> int:
    if not lib:
        logger.warning(f"cpuid instruction is not supported on {sys}")
        return 0

    return lib.cpuid_checksum()
