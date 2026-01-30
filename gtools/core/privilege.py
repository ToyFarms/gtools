from dataclasses import dataclass
import os
import shlex
import sys
import subprocess
import platform
from typing import Any
import uuid
import logging
from logging.handlers import RotatingFileHandler

ELEVATE_FLAG = "--__elevate_token="


# --------------------------- Logging setup ---------------------------
TRACE_LEVEL_NUM = 5
logging.addLevelName(TRACE_LEVEL_NUM, "TRACE")


def _logger_trace(self, message, *args, **kws):
    if self.isEnabledFor(TRACE_LEVEL_NUM):
        self._log(TRACE_LEVEL_NUM, message, args, **kws)


logging.Logger.trace = _logger_trace


def _setup_logger(name: str = "elevate") -> logging.Logger:
    logger = logging.getLogger(name)
    if getattr(logger, "_setup_done", False):
        return logger

    # Allow control of level via environment variable
    level_name = os.environ.get("ELEVATE_LOG_LEVEL", "TRACE").upper()
    level = TRACE_LEVEL_NUM if level_name == "TRACE" else getattr(logging, level_name, logging.DEBUG)

    logger.setLevel(level)

    # Log file next to the script if possible, otherwise cwd
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        base_dir = os.getcwd()

    log_path = os.path.join(base_dir, "elevate_trace.log")

    fh = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setLevel(level)

    formatter = logging.Formatter("%(asctime)s %(levelname)-5s [%(name)s:%(lineno)d] %(message)s")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Also add a console handler when running interactively / for convenience if requested
    if os.environ.get("ELEVATE_LOG_TO_CONSOLE"):
        ch = logging.StreamHandler()
        ch.setLevel(level)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    logger._setup_done = True
    logger.debug("Logging initialized. path=%s level=%s", log_path, logging.getLevelName(level))
    return logger


logger = _setup_logger()


def _mask_token(token: str | None) -> str | None:
    if token is None:
        return None
    if len(token) <= 8:
        return "*" * len(token)
    return "*" * (len(token) - 8) + token[-8:]


@dataclass
class ElevationResult:
    success: bool
    proc_handle: Any | None = None


def is_elevated() -> bool:
    system = platform.system()
    logger.trace("is_elevated() called; system=%s", system)
    try:
        if system == "Windows":
            import ctypes

            try:
                res = ctypes.windll.shell32.IsUserAnAdmin() != 0
                logger.trace("Windows IsUserAnAdmin result=%s", res)
                return res
            except Exception:
                logger.exception("is_elevated: Windows check failed")
                return False
        else:
            try:
                euid = os.geteuid()
                res = euid == 0
                logger.trace("POSIX geteuid=%s elevated=%s", euid, res)
                return res
            except Exception:
                logger.exception("is_elevated: POSIX geteuid failed")
                return False
    except Exception:
        logger.exception("is_elevated: unexpected error")
        return False


def elevate(wait_for_child: bool = False, timeout: float | None = None) -> bool:
    logger.trace("elevate() called wait_for_child=%s timeout=%s", wait_for_child, timeout)
    if is_elevated():
        logger.debug("Already elevated")
        return True

    system = platform.system()
    token = uuid.uuid4().hex
    logger.debug("Generated elevation token=%s", _mask_token(token))

    try:
        if system == "Windows":
            result = _launch_elevated_windows(token)
        elif system == "Darwin":
            result = _launch_elevated_macos(token)
        elif system == "Linux":
            result = _launch_elevated_linux(token)
        else:
            logger.error("Unsupported platform: %s", system)
            return False

        logger.debug("Launch result success=%s proc_handle=%s", result.success, type(result.proc_handle))

        if not result.success:
            logger.warning("Failed to start elevated process")
            return False

        child_handle = result.proc_handle

        if wait_for_child and child_handle is not None:
            logger.debug("Waiting for elevated child to finish")
            ok = _wait_for_process_handle(child_handle, timeout)
            logger.debug("Child wait result=%s", ok)
            return ok
        elif wait_for_child and child_handle is None:
            logger.error("wait_for_child requested but no process handle available")
            return False
        else:
            # We launched successfully and not waiting.
            logger.debug("Elevated process launched successfully (not waiting)")
            return True

    except Exception:
        logger.exception("elevate: unexpected exception")
        return False


def _launch_elevated_windows(token: str) -> ElevationResult:
    logger.trace("_launch_elevated_windows token=%s", _mask_token(token))
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

        logger.trace("Windows shell params=%s", params)

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
            logger.error("ShellExecuteEx failed")
            return ElevationResult(False)

        hproc = ei.hProcess
        logger.debug("ShellExecuteEx returned handle %s", hproc)
        return ElevationResult(True, proc_handle=hproc)

    except Exception:
        logger.exception("_launch_elevated_windows failed")
        return ElevationResult(False)


def _launch_elevated_macos(token: str) -> ElevationResult:
    logger.trace("_launch_elevated_macos token=%s", _mask_token(token))
    try:
        this_script = os.path.abspath(__file__)
        param_list = [sys.executable, this_script, sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:], f"{ELEVATE_FLAG}{token}"]
        cmd = " ".join(shlex.quote(p) for p in param_list)
        applescript = f'do shell script "{cmd}" with administrator privileges'
        logger.debug("osascript cmd=%s", cmd)
        popen = subprocess.Popen(["osascript", "-e", applescript], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.debug("osascript started pid=%s", getattr(popen, "pid", None))
        return ElevationResult(True, proc_handle=popen)
    except Exception:
        logger.exception("_launch_elevated_macos failed")
        return ElevationResult(False)


def _launch_elevated_linux(token: str) -> ElevationResult:
    logger.trace("_launch_elevated_linux token=%s", _mask_token(token))
    try:
        this_script = os.path.abspath(__file__)
        param_list = [sys.executable, this_script, sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:], f"{ELEVATE_FLAG}{token}"]

        elevation_commands = ["pkexec", "gksu", "kdesudo", "sudo"]

        for cmd in elevation_commands:
            logger.trace("Checking command exists: %s", cmd)
            if _command_exists(cmd):
                full_cmd = [cmd] + param_list
                logger.debug("Attempting elevate with: %s %s", cmd, param_list)
                try:
                    popen = subprocess.Popen(full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    logger.debug("Started %s pid=%s", cmd, getattr(popen, "pid", None))
                    return ElevationResult(True, proc_handle=popen)
                except Exception:
                    logger.exception("Failed to launch with %s", cmd)
                    continue

        logger.error("No elevation helper found")
        return ElevationResult(False)
    except Exception:
        logger.exception("_launch_elevated_linux failed")
        return ElevationResult(False)


def _command_exists(command: str) -> bool:
    logger.trace("_command_exists: %s", command)
    try:
        import shutil

        res = shutil.which(command) is not None
        logger.trace("shutil.which result for %s: %s", command, res)
        return res
    except Exception:
        logger.debug("shutil.which not available, falling back to 'which' subprocess for %s", command)
        try:
            subprocess.run(["which", command], capture_output=True, check=True)
            logger.trace("which returned success for %s", command)
            return True
        except Exception:
            logger.trace("which failed for %s", command)
            return False


def _wait_for_process_handle(handle, timeout: float | None) -> bool:
    system = platform.system()
    logger.trace("_wait_for_process_handle called system=%s timeout=%s", system, timeout)
    if system == "Windows":
        try:
            import ctypes

            INFINITE = 0xFFFFFFFF
            WAIT_OBJECT_0 = 0x00000000
            ms = INFINITE if timeout is None else int(timeout * 1000)
            logger.trace("Waiting (ms)=%s", ms)
            res = ctypes.windll.kernel32.WaitForSingleObject(handle, ms)
            ctypes.windll.kernel32.CloseHandle(handle)
            ok = res == WAIT_OBJECT_0
            logger.debug("Windows wait result=%s code=%s", ok, res)
            return ok
        except Exception:
            logger.exception("_wait_for_process_handle Windows failed")
            return False
    else:
        try:
            proc = handle
            logger.debug("Posix wait for proc pid=%s", getattr(proc, "pid", None))
            if timeout is None:
                proc.wait()
                logger.debug("Process finished")
                return True
            else:
                proc.wait(timeout=timeout)
                logger.debug("Process finished within timeout")
                return True
        except subprocess.TimeoutExpired:
            logger.warning("Timed out waiting for process")
            return False
        except Exception:
            logger.exception("_wait_for_process_handle POSIX failed")
            return False


def is_elevated_child() -> bool:
    res = is_elevated() and "ELEVATED" in os.environ and "ELEVATION_TOKEN" in os.environ
    logger.trace("is_elevated_child -> %s", res)
    return res


def _strip_elevate_flag(argv: list[str]) -> tuple[list[str], str | None]:
    token = None
    out = []
    logger.trace("_strip_elevate_flag argv=%s", argv)
    for a in argv:
        if a.startswith(ELEVATE_FLAG) and token is None:
            token = a[len(ELEVATE_FLAG) :]
            logger.trace("Found token (masked)=%s", _mask_token(token))
        else:
            out.append(a)
    logger.trace("_strip_elevate_flag returning argv=%s token=%s", out, _mask_token(token))
    return out, token


def _exec_elevated_target_windows(target_argv: list[str], extra_env: dict[str, str]) -> None:
    import ctypes
    from ctypes import wintypes

    logger.trace("_exec_elevated_target_windows target_argv=%s extra_env_keys=%s", target_argv, list(extra_env.keys()))

    kernel32 = ctypes.windll.kernel32
    CREATE_UNICODE_ENVIRONMENT = 0x00000400

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
        logger.error("CreateProcessW failed for cmd=%s", cmdline)
        raise RuntimeError("CreateProcessW failed")

    logger.debug("CreateProcessW succeeded pid=%s", pi.dwProcessId)
    kernel32.CloseHandle(pi.hThread)
    kernel32.CloseHandle(pi.hProcess)


def _exec_elevated_target_posix(target_argv: list[str], extra_env: dict[str, str]) -> None:
    logger.trace("_exec_elevated_target_posix argv=%s extra_env_keys=%s", target_argv, list(extra_env.keys()))
    env = os.environ.copy()
    env.update(extra_env)
    logger.debug("Exec'ing target argv[0]=%s", target_argv[0])
    os.execvpe(target_argv[0], target_argv, env)


# NOTE: intermediary to pass argument as environment variable
if __name__ == "__main__":
    logger.debug("__main__ entry argv=%s", sys.argv)
    argv_no_token, token = _strip_elevate_flag(sys.argv)
    if token is None:
        logger.error("Missing elevation token")
        print("Missing elevation token", file=sys.stderr)
        sys.exit(1)

    if len(argv_no_token) < 2:
        logger.error("No target command supplied to elevated intermediary")
        print("No target command supplied to elevated intermediary", file=sys.stderr)
        sys.exit(1)

    target_argv = argv_no_token[1:]

    injected_env = {
        "ELEVATED": "1",
        "ELEVATION_TOKEN": token,
    }

    system = platform.system()
    try:
        logger.debug("Launching elevated target system=%s target=%s", system, target_argv)
        if system == "Windows":
            _exec_elevated_target_windows(target_argv, injected_env)
            sys.exit(0)
        else:
            _exec_elevated_target_posix(target_argv, injected_env)
    except Exception as e:
        logger.exception("Failed to launch elevated target: %s", e)
        print(f"Failed to launch elevated target: {e}", file=sys.stderr)
        sys.exit(1)
