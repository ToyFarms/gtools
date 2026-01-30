from dataclasses import dataclass
import os
import shlex
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

        this_script = os.path.abspath(__file__)

        param_list = [this_script, sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:], f"{ELEVATE_FLAG}{token}"]

        params = subprocess.list2cmdline(param_list)

        ei = SHELLEXECUTEINFO()
        ei.cbSize = ctypes.sizeof(ei)
        ei.fMask = SEE_MASK_NOCLOSEPROCESS
        ei.hwnd = None
        ei.lpVerb = "runas"
        ei.lpFile = sys.executable
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
        this_script = os.path.abspath(__file__)
        param_list = [sys.executable, this_script, sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:], f"{ELEVATE_FLAG}{token}"]
        cmd = " ".join(shlex.quote(p) for p in param_list)
        applescript = f'do shell script "{cmd}" with administrator privileges'
        popen = subprocess.Popen(["osascript", "-e", applescript], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return ElevationResult(True, proc_handle=popen)
    except Exception:
        return ElevationResult(False)


def _launch_elevated_linux(token: str) -> ElevationResult:
    try:
        this_script = os.path.abspath(__file__)
        param_list = [sys.executable, this_script, sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:], f"{ELEVATE_FLAG}{token}"]

        elevation_commands = ["pkexec", "gksu", "kdesudo", "sudo"]

        for cmd in elevation_commands:
            if _command_exists(cmd):
                full_cmd = [cmd] + param_list
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


def is_elevated_child() -> bool:
    return is_elevated() and "ELEVATED" in os.environ and "ELEVATION_TOKEN" in os.environ


def _strip_elevate_flag(argv: list[str]) -> tuple[list[str], str | None]:
    token = None
    out = []
    for a in argv:
        if a.startswith(ELEVATE_FLAG) and token is None:
            token = a[len(ELEVATE_FLAG) :]
        else:
            out.append(a)
    return out, token


def _exec_elevated_target_windows(target_argv: list[str], extra_env: dict[str, str]) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    INFINITE = 0xFFFFFFFF
    WAIT_FAILED = 0xFFFFFFFF

    class STARTUPINFO(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    env = os.environ.copy()
    env.update(extra_env)
    env_block = "\0".join(f"{k}={v}" for k, v in env.items()) + "\0\0"
    env_block = ctypes.create_unicode_buffer(env_block)

    cmdline = subprocess.list2cmdline(target_argv)

    si = STARTUPINFO()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()

    ok = kernel32.CreateProcessW(
        None,
        ctypes.c_wchar_p(cmdline),
        None,
        None,
        False,
        CREATE_UNICODE_ENVIRONMENT,
        env_block,
        None,
        ctypes.byref(si),
        ctypes.byref(pi),
    )

    if not ok:
        raise RuntimeError("CreateProcessW failed")

    try:
        wait_rc = kernel32.WaitForSingleObject(pi.hProcess, INFINITE)
        if wait_rc == WAIT_FAILED:
            raise RuntimeError("WaitForSingleObject failed")

        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(pi.hProcess, ctypes.byref(exit_code)):
            raise RuntimeError("GetExitCodeProcess failed")

        if exit_code.value != 0:
            raise RuntimeError(f"child process exited with non-zero exit code {exit_code.value}")

    finally:
        kernel32.CloseHandle(pi.hThread)
        kernel32.CloseHandle(pi.hProcess)


def _exec_elevated_target_posix(target_argv: list[str], extra_env: dict[str, str]) -> None:
    env = os.environ.copy()
    env.update(extra_env)
    os.execvpe(target_argv[0], target_argv, env)


# NOTE: intermediary to pass argument as environment variable
if __name__ == "__main__":
    argv_no_token, token = _strip_elevate_flag(sys.argv)
    if token is None:
        print("Missing elevation token", file=sys.stderr)
        sys.exit(1)

    if len(argv_no_token) < 2:
        print("No target command supplied to elevated intermediary", file=sys.stderr)
        sys.exit(1)

    target_argv = argv_no_token[1:]

    injected_env = {
        "ELEVATED": "1",
        "ELEVATION_TOKEN": token,
    }

    system = platform.system()
    try:
        if system == "Windows":
            _exec_elevated_target_windows(target_argv, injected_env)
            sys.exit(0)
        else:
            _exec_elevated_target_posix(target_argv, injected_env)
    except Exception as e:
        print(f"Failed to launch elevated target: {e}", file=sys.stderr)
        sys.exit(1)
