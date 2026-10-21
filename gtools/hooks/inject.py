import ctypes
import os
import sys
import traceback
from ctypes import wintypes
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent
INJECTOR_DLL = HOOKS_DIR / "injector.dll"
PAYLOAD_DLL = HOOKS_DIR / "hook.dll"
HANDSHAKE = HOOKS_DIR / "gtdump_hook.handshake"
STATUS = HOOKS_DIR / "gtdump_hook.inject.status"

TARGET = b"Growtopia.exe"


class LUID(ctypes.Structure):
    _fields_ = [
        ("LowPart", wintypes.DWORD),
        ("HighPart", wintypes.LONG),
    ]


class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Luid", LUID),
        ("Attributes", wintypes.DWORD),
    ]


class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [
        ("PrivilegeCount", wintypes.DWORD),
        ("Privileges", LUID_AND_ATTRIBUTES * 1),
    ]


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def enable_debug_privilege() -> tuple[bool, int]:
    TOKEN_ADJUST_PRIVILEGES = 0x0020
    TOKEN_QUERY = 0x0008
    SE_PRIVILEGE_ENABLED = 0x0002

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.LookupPrivilegeValueW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.POINTER(LUID),
    ]
    advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL
    advapi32.AdjustTokenPrivileges.argtypes = [
        wintypes.HANDLE,
        wintypes.BOOL,
        ctypes.POINTER(TOKEN_PRIVILEGES),
        wintypes.DWORD,
        ctypes.POINTER(TOKEN_PRIVILEGES),
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.AdjustTokenPrivileges.restype = wintypes.BOOL

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token)):
        return False, ctypes.get_last_error()

    try:
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):
            return False, ctypes.get_last_error()

        privileges = TOKEN_PRIVILEGES()
        privileges.PrivilegeCount = 1
        privileges.Privileges[0].Luid = luid
        privileges.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED

        ctypes.set_last_error(0)
        ok = advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(privileges), 0, None, None)
        return bool(ok) and ctypes.get_last_error() == 0, ctypes.get_last_error()
    finally:
        kernel32.CloseHandle(token)


def write_status(status: dict[str, str]) -> None:
    STATUS.write_text("\n".join(f"{key}={value}" for key, value in status.items()) + "\n", encoding="utf-8")


def main() -> int:
    status = {
        "elevated": str(int(is_elevated())),
        "debug_privilege": "0",
        "debug_error": "0",
        "rc": "-1",
        "error": "injector did not run",
    }
    exit_code = 1

    try:
        if sys.maxsize <= 2**32:
            status["error"] = "injector must run under 64-bit Python"
        elif not INJECTOR_DLL.exists():
            status["error"] = f"missing {INJECTOR_DLL}"
        elif not PAYLOAD_DLL.exists():
            status["error"] = f"missing {PAYLOAD_DLL}"
        elif not is_elevated():
            status["error"] = "injector is not elevated"
        else:
            enabled, debug_error = enable_debug_privilege()
            status["debug_privilege"] = str(int(enabled))
            status["debug_error"] = str(debug_error)

            injector = ctypes.CDLL(str(INJECTOR_DLL))
            injector.inject.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
            injector.inject.restype = ctypes.c_int
            injector.last_error.argtypes = []
            injector.last_error.restype = ctypes.c_char_p

            rc = injector.inject(TARGET, os.fsencode(str(PAYLOAD_DLL)), os.fsencode(str(HANDSHAKE)))
            status["rc"] = str(rc)
            status["error"] = (injector.last_error() or b"unknown error").decode("utf-8", "replace")
            exit_code = 0 if rc == 0 else 1
    except Exception:
        status["error"] = traceback.format_exc().replace("\n", " | ")
    finally:
        try:
            write_status(status)
        except Exception:
            pass

    print(
        f"[hook injector] elevated={status['elevated']} debug={status['debug_privilege']} " f"rc={status['rc']}: {status['error']}",
        flush=True,
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
