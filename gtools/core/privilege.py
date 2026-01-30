from dataclasses import dataclass
import os
import sys
import subprocess
import platform
from typing import Any
import uuid

ELEVATE_FLAG = "--__elevate_token="


@dataclass
class ElevationResult:
    success: bool
    proc_handle: Any | None = None


def is_elevated() -> bool:
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes

            try:
                return ctypes.windll.shell32.IsUserAnAdmin() != 0
            except Exception:
                return False
        else:
            return os.geteuid() == 0
    except Exception:
        return False


def elevate(wait_for_child: bool = False, timeout: float | None = None) -> bool:
    if is_elevated():
        return True

    system = platform.system()
    token = uuid.uuid4().hex

    try:
        if system == "Windows":
            result = _launch_elevated_windows(token)
        elif system == "Darwin":
            result = _launch_elevated_macos(token)
        elif system == "Linux":
            result = _launch_elevated_linux(token)
        else:
            return False

        if not result.success:
            return False

        child_handle = result.proc_handle

        if wait_for_child and child_handle is not None:
            _wait_for_process_handle(child_handle, timeout)
            return False
        elif wait_for_child and child_handle is None:
            return False
        else:
            return False

    except Exception:
        return False


def _launch_elevated_windows(token: str) -> ElevationResult:
    try:
        import ctypes
        from ctypes import wintypes

        SEE_MASK_NOCLOSEPROCESS = 0x00000040
        SW_SHOWNORMAL = 1

        class SHELLEXECUTEINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("fMask", wintypes.ULONG),
                ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR),
                ("lpFile", wintypes.LPCWSTR),
                ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR),
                ("nShow", wintypes.INT),
                ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", wintypes.LPVOID),
                ("lpClass", wintypes.LPCWSTR),
                ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD),
                ("hIcon", wintypes.HANDLE),
                ("hProcess", wintypes.HANDLE),
            ]

        exe = sys.executable
        params = " ".join([f'"{arg}"' for arg in sys.argv])
        params = f'{params} "{ELEVATE_FLAG}{token}"'

        ei = SHELLEXECUTEINFO()
        ei.cbSize = ctypes.sizeof(ei)
        ei.fMask = SEE_MASK_NOCLOSEPROCESS
        ei.hwnd = None
        ei.lpVerb = "runas"
        ei.lpFile = exe
        ei.lpParameters = params
        ei.lpDirectory = None
        ei.nShow = SW_SHOWNORMAL
        ei.hInstApp = None
        ei.hProcess = None

        ShellExecuteEx = ctypes.windll.shell32.ShellExecuteExW
        ret = ShellExecuteEx(ctypes.byref(ei))
        if not ret:
            return ElevationResult(False)

        hproc = ei.hProcess
        return ElevationResult(True, proc_handle=hproc)

    except Exception:
        return ElevationResult(False)


def _launch_elevated_macos(token: str) -> ElevationResult:
    try:
        script = os.path.abspath(sys.argv[0])
        args = sys.argv[1:]

        cmd = [sys.executable, script] + args
        cmd.append(f"{ELEVATE_FLAG}{token}")
        joined = " ".join([f'"{p}"' for p in cmd])
        applescript = f"do shell script {joined} with administrator privileges"

        popen = subprocess.Popen(["osascript", "-e", applescript], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return ElevationResult(True, proc_handle=popen)

    except Exception:
        return ElevationResult(False)


def _launch_elevated_linux(token: str) -> ElevationResult:
    try:
        script = os.path.abspath(sys.argv[0])
        args = [sys.executable, script] + sys.argv[1:]
        args.append(f"{ELEVATE_FLAG}{token}")

        elevation_commands = ["pkexec", "gksu", "kdesudo", "sudo"]

        for cmd in elevation_commands:
            if _command_exists(cmd):
                full_cmd = [cmd] + args
                try:
                    popen = subprocess.Popen(full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    return ElevationResult(True, proc_handle=popen)
                except Exception:
                    continue

        return ElevationResult(False)
    except Exception:
        return ElevationResult(False)


def _command_exists(command: str) -> bool:
    try:
        import shutil

        return shutil.which(command) is not None
    except Exception:
        try:
            subprocess.run(["which", command], capture_output=True, check=True)
            return True
        except Exception:
            return False


def _wait_for_process_handle(handle, timeout: float | None) -> bool:
    system = platform.system()
    if system == "Windows":
        try:
            import ctypes

            INFINITE = 0xFFFFFFFF
            WAIT_OBJECT_0 = 0x00000000
            ms = INFINITE if timeout is None else int(timeout * 1000)
            res = ctypes.windll.kernel32.WaitForSingleObject(handle, ms)
            ctypes.windll.kernel32.CloseHandle(handle)
            return res == WAIT_OBJECT_0
        except Exception:
            return False
    else:
        try:
            proc = handle
            if timeout is None:
                proc.wait()
                return True
            else:
                proc.wait(timeout=timeout)
                return True
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False


def launched_via_elevate() -> str | None:
    for arg in sys.argv:
        if arg.startswith(ELEVATE_FLAG):
            return arg[len(ELEVATE_FLAG) :]
    return


def is_elevated_child() -> bool:
    return is_elevated() and launched_via_elevate() is not None
