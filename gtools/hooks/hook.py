import ctypes
import logging
import os
import subprocess
import sys
import threading
import time
import traceback
from ctypes import wintypes
from pathlib import Path

from gtools.core.privilege import elevate, is_elevated
from gtools.hooks.control import HookControl
from gtools.core.pipe import PipeError
from gtools.proxy.event import UpdateClientVersion, UpdateServerData
from gtools.setting import setting

logger = logging.getLogger("hook")


HOOKS_DIR = Path(__file__).resolve().parent
HOOK_INJECTOR_DLL = HOOKS_DIR / "injector.dll"
HOOK_PAYLOAD = HOOKS_DIR / "hook.dll"
HOOK_AGENT_DLL = HOOKS_DIR / "agent.dll"
HOOK_STATUS = setting.appdir / "inject.status"

TARGET = b"Growtopia.exe"

AGENT_MUTEX = r"Global\gtools_hook_agent"


def agent_running() -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    SYNCHRONIZE = 0x00100000
    handle = kernel32.OpenMutexA(SYNCHRONIZE, False, AGENT_MUTEX.encode())
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def spawn_agent(timeout: float = 2.0) -> bool:
    """start the host process (rundll32 agent.dll,AgentMain) unless one is already running"""
    if agent_running():
        return True

    windir = os.environ.get("WINDIR", r"C:\Windows")
    rundll32 = Path(windir) / "System32" / "rundll32.exe"
    if not rundll32.exists():
        return False

    # the agent owns the pipe and hooks the game on its own, it must outlive
    # this process
    DETACHED_PROCESS = 0x00000008
    CREATE_NO_WINDOW = 0x08000000
    try:
        subprocess.Popen(
            [str(rundll32), f"{HOOK_AGENT_DLL.resolve()},AgentMain"],
            creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            close_fds=True,
        )
    except OSError:
        return False

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if agent_running():
            return True
        time.sleep(0.05)

    return agent_running()


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


def write_status(status: dict[str, str], path: Path = HOOK_STATUS) -> None:
    path.write_text("\n".join(f"{key}={value}" for key, value in status.items()) + "\n", encoding="utf-8")


def run_injector(status_path: Path = HOOK_STATUS) -> dict[str, str]:
    status = {
        "elevated": str(int(is_elevated())),
        "debug_privilege": "0",
        "debug_error": "0",
        "agent": "0",
        "rc": "-1",
        "error": "injector did not run",
    }

    try:
        if sys.maxsize <= 2**32:
            status["error"] = "injector must run under 64-bit Python"
        elif not HOOK_INJECTOR_DLL.exists():
            status["error"] = f"missing {HOOK_INJECTOR_DLL}"
        elif not HOOK_PAYLOAD.exists():
            status["error"] = f"missing {HOOK_PAYLOAD}"
        elif not HOOK_AGENT_DLL.exists():
            status["error"] = f"missing {HOOK_AGENT_DLL}"
        elif not is_elevated():
            status["error"] = "injector is not elevated"
        else:
            enabled, debug_error = enable_debug_privilege()
            status["debug_privilege"] = str(int(enabled))
            status["debug_error"] = str(debug_error)

            # the agent owns the pipe and it is the single injector: after the
            # UAC prompt its watch dog hooks the game roughly a second later,
            # injecting here in parallel would only fight over the pid lock
            status["agent"] = str(int(spawn_agent()))
            if not agent_running():
                status["error"] = "the rundll32 agent is not running"
                return status

            if target_running():
                ctl = _wait_hooks_installed(60.0)
                if ctl is not None:
                    ctl.close()
                    status["rc"] = "0"
                    status["error"] = "the agent watch dog injected the hook"
                    return status

            # fallback: the agent watch dog did not come through (missing or
            # broken injector exports); do it here the classic way, the lock
            # serializes with the watch dog if it happens to be mid inject
            injector = ctypes.CDLL(str(HOOK_INJECTOR_DLL))
            injector.inject.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            injector.inject.restype = ctypes.c_int
            injector.last_error.argtypes = []
            injector.last_error.restype = ctypes.c_char_p

            rc = injector.inject(TARGET, os.fsencode(str(HOOK_PAYLOAD)))
            status["rc"] = str(rc)
            status["error"] = (injector.last_error() or b"unknown error").decode("utf-8", "replace")
    except Exception:
        status["error"] = traceback.format_exc().replace("\n", " | ")
    finally:
        try:
            write_status(status, status_path)
        except Exception:
            pass

    return status


def read_inject_status() -> dict[str, str]:
    try:
        text = HOOK_STATUS.read_text(encoding="utf-8")
    except OSError:
        return {}

    status = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            status[key.strip()] = value

    return status


def hook_available() -> bool:
    return HOOK_INJECTOR_DLL.exists() and HOOK_PAYLOAD.exists() and HOOK_AGENT_DLL.exists()


def target_running() -> bool:
    if sys.platform != "win32":
        return False

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    TH32CS_SNAPPROCESS = 0x00000002
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return False

    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                if entry.szExeFile == TARGET.decode():
                    return True
                if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)

    return False


def _hooks_installed(ctl: HookControl) -> bool:
    """the agent serves the pipe even before the game is hooked, only a
    STATUS that reports installed hooks means the pipe belongs to a live hook"""
    try:
        pairs = ctl.status(0.5)
    except Exception:
        return False

    return any(value in ("ready", "patched") for key, value in pairs.items() if key.startswith("hook_"))


def _wait_hooks_installed(timeout: float) -> HookControl | None:
    """poll the agent pipe until a status reports installed hooks"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ctl = HookControl()
        try:
            if ctl.connect(0.25) and _hooks_installed(ctl):
                return ctl
        except Exception:
            pass
        finally:
            ctl.close()
        time.sleep(0.25)

    return None


def _ensure_hook_once() -> HookControl | None:
    if not hook_available():
        logger.info("hook unsupported")
        return None

    ctl = HookControl()
    if ctl.connect(0.25) and _hooks_installed(ctl):
        logger.info("attached to the running hook")
        return ctl
    ctl.close()

    if not target_running():
        return None

    # the agent watch dog hooks the game by itself roughly a second after the
    # game shows up; give it the chance before elevating again, otherwise the
    # first run after every restart pays a UAC prompt and a lock race
    if agent_running():
        fresh = _wait_hooks_installed(60.0)
        if fresh is not None:
            logger.info("the agent watch dog hooked the game")
            return fresh

    if not inject_hook():
        return None

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        fresh = HookControl()
        if fresh.connect(0.25) and _hooks_installed(fresh):
            return fresh
        fresh.close()
        time.sleep(0.05)

    logger.error("the hook was injected but its control pipe did not report installed hooks")

    return None


def ensure_hook(wait_forever: bool = True) -> HookControl | None:
    while True:
        hook_ctl = _ensure_hook_once()
        if hook_ctl is not None:
            return hook_ctl

        if not wait_forever:
            return

        if not target_running():
            time.sleep(0.5)
            continue

        time.sleep(1.0)


def _run_elevated_injector() -> bool:
    project_root = str(HOOKS_DIR.parent.parent)
    previous = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = project_root + (os.pathsep + previous if previous else "")
    try:
        return elevate(
            wait_for_child=True,
            timeout=150,
            argv=[sys.executable, "-m", "gtools.hooks.hook", str(HOOK_STATUS)],
        )
    finally:
        if previous is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = previous


def inject_hook() -> bool:
    try:
        HOOK_STATUS.unlink()
    except FileNotFoundError:
        pass

    if is_elevated():
        status = run_injector()
    else:
        if not _run_elevated_injector():
            logger.error("failed to start elevated injector (UAC cancelled or timed out)")
            return False
        status = read_inject_status()

    if not status:
        logger.error("injector did not write a status file")
        return False

    if status.get("elevated") != "1":
        logger.error("injector helper was not elevated, cannot open Growtopia")
        return False

    if status.get("debug_privilege") != "1":
        logger.warning(f"failed to enable SeDebugPrivilege (error {status.get('debug_error', '?')})")

    if status.get("agent") != "1":
        logger.error("failed to start the hook agent (rundll32)")

    if status.get("rc") == "-1":
        # the agent watch dog or a previous injector run got there first
        logger.info("the hook is already injected")
        return True

    if status.get("rc") != "0":
        logger.error(f"failed to inject hook (rc={status.get('rc', '?')}): {status.get('error', 'unknown error')}")
        return False

    logger.info("hook injected")
    return True


def apply_hook_settings(ctl: HookControl) -> None:
    values = {
        "proxy_host": setting.proxy_server,
        "proxy_port": str(setting.proxy_port),
        "start_delay_ms": str(setting.hook.start_delay_ms),
        "log_level": str(setting.hook.log_level),
        "allow_any_module": str(int(setting.hook.allow_any_module)),
        "stream_game_logs": str(int(setting.hook.stream_game_logs)),
    }
    for key, value in values.items():
        if not ctl.set(key, value):
            logger.warning(f"hook rejected setting {key}={value}")


def publish_hook_state(fields: dict[str, str]) -> None:
    version = fields.get("client_version", "")
    protocol = fields.get("client_protocol", "")
    server = fields.get("real_server", "")
    port = fields.get("real_port", "")

    if version and protocol:
        try:
            UpdateClientVersion(version=version, protocol=int(protocol)).send()
        except ValueError:
            logger.warning(f"hook returned invalid protocol: {protocol!r}")

    if server and port:
        try:
            port_number = int(port)
        except ValueError:
            logger.warning(f"hook returned invalid port: {port!r}")
        else:
            if port_number > 0:
                UpdateServerData(server=server, port=port_number).send()


def _reattach_hook(stop: threading.Event) -> HookControl | None:
    while not stop.is_set():
        fresh = ensure_hook(wait_forever=False)
        if fresh is not None:
            return fresh

        if not target_running():
            stop.wait(0.5)
            continue

        inject_hook()
        stop.wait(1.0)

    return


def listen_hook_events(ctl: HookControl, stop: threading.Event) -> None:
    current = ctl

    while not stop.is_set():
        try:
            event = current.wait_event(timeout=0.5)
        except Exception:
            logger.debug("failed to read a hook event", exc_info=True)
            continue

        if not current.connected:
            logger.warning("the hook control pipe was closed, waiting for the hook to return")
            current.close()

            fresh = _reattach_hook(stop)
            if fresh is None:
                return

            current = fresh
            try:
                apply_hook_settings(current)
                publish_hook_state(current.status())
            except PipeError:
                logger.exception("hook setup failed after reconnect")
                continue

            continue

        if event is None:
            continue

        if event.name == "state":
            publish_hook_state(event.fields)
        elif event.name == "log":
            logger.info("[game] %s", event.payload)


def inject_main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    status_path = Path(argv[0]) if argv else HOOK_STATUS
    status = run_injector(status_path)
    print(
        f"[hook injector] elevated={status['elevated']} debug={status['debug_privilege']} rc={status['rc']}: {status['error']}",
        flush=True,
    )
    return 0 if status["rc"] == "0" else 1


if __name__ == "__main__":
    sys.exit(inject_main())
