import ctypes
import logging
import platform

from gtools.core.dll_loader import DLL

lib = DLL("gtools/core/x86", "cpuid")
logger = logging.getLogger("cpuid")

if lib.supported:
    lib.cpuid_checksum.restype = ctypes.c_int16

    def cpuid_checksum() -> int:
        return lib.cpuid_checksum()

else:
    logger.warning(f"cpuid instruction is not supported on {platform.system()}")

    def cpuid_checksum() -> int:
        return 0
