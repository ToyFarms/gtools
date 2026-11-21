"""Hook lifecycle: build the payload, inject, attach, stream events.

The hook descriptors and programs are authored in ``gtools/hooks/programs.py``
(via ``registry``); this module only moves them into place and keeps the
runtime (enable/state/data) in sync with the settings file.
"""

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

from gtools.core.eventbus import subscribe
from gtools.core.pipe import PipeError
from gtools.core.privilege import elevate_ex, is_elevated
from gtools.core.wsl import is_running_wsl
from gtools.hooks import programs, registry
from gtools.hooks.control import HookControl
from gtools.hooks.events import HookEventSink
from gtools.hooks.payload import Payload
from gtools.proxy.event import UpdateClientVersion, UpdateServerData
from gtools.setting import Setting, SettingChanged, setting

logger = logging.getLogger("hook")

HOOKS_DIR = Path(__file__).resolve().parent
HOOK_INJECTOR_DLL = HOOKS_DIR / "injector.dll"
HOOK_PAYLOAD_DLL = HOOKS_DIR / "hook.dll"
HOOK_AGENT_DLL = HOOKS_DIR / "agent.dll"
HOOK_PAYLOAD_FILE = HOOKS_DIR / "hook_payload.bin"
HOOK_STATUS = setting.appdir / "inject.status"

TARGET = b"Growtopia.exe"

AGENT_MUTEX = r"Global\gtools_hook_agent"

_SETTING_FIELDS_FORWARDED = frozenset({"hook", "proxy_server", "proxy_port"})
_pending_settings_push = threading.Event()


def payload_available() -> bool:
    return HOOK_PAYLOAD_FILE.exists()


def payload_target() -> bytes:
    """The target process named by the payload header (defaults to Growtopia)."""
    try:
        head = HOOK_PAYLOAD_FILE.read_bytes()[:64]
        name = head[32:64].split(b"\0")[0]
        return name if name else TARGET
    except OSError:
        return TARGET


def build_payload_file(source: Setting | None = None) -> Payload:
    """Serialize the registry (programs.py) into the install payload file."""
    current = source if source is not None else setting
    target = Path(current.gt_path).name or "Growtopia.exe"
    if not target.lower().endswith(".exe"):
        target += ".exe"  # gt_path may point at the install directory
    payload = registry.build_payload(
        start_delay_ms=0,  # the scan retry window handles unpacking; no boot delay
        allow_any_module=current.hook.allow_any_module,
        target_process=target,
    )
    blob = payload.pack()
    temporary = HOOK_PAYLOAD_FILE.with_suffix(".tmp")
    temporary.write_bytes(blob)
    os.replace(temporary, HOOK_PAYLOAD_FILE)
    logger.info(
        "hook payload written: %d hooks, %d bytes (crc 0x%08X)",
        len(payload.descriptors),
        len(blob),
        Payload.crc(blob),
    )
    return payload


def agent_running() -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    SYNCHRONIZE = 0x00100000
    handle = kernel32.OpenMutexA(SYNCHRONIZE, False, AGENT_MUTEX.encode())
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def spawn_agent(timeout: float = 2.0) -> bool:
    if agent_running():
        return True

    windir = os.environ.get("WINDIR", r"C:\Windows")
    rundll32 = Path(windir) / "System32" / "rundll32.exe"
    if not rundll32.exists():
        return False

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
    if not advapi32.OpenProcessToken(
        kernel32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token)
    ):
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


def kill_stale_agents() -> int:
    """Terminate rundll32 processes hosting agent.dll.

    A leftover agent from an earlier session keeps serving the pipe; if it
    cannot write to the (elevated) game, every runtime push would be rejected.
    The elevated injector helper runs this before spawning its own agent.
    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
            ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
        ]

    class MODULEENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD), ("th32ModuleID", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD), ("GlblcntUsage", wintypes.DWORD),
            ("ProccntUsage", wintypes.DWORD), ("modBaseAddr", ctypes.POINTER(ctypes.c_ubyte)),
            ("modBaseSize", wintypes.DWORD), ("hModule", ctypes.c_void_p),
            ("szModule", ctypes.c_wchar * 256), ("szExePath", ctypes.c_wchar * 260),
        ]

    killed = 0
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snapshot in (0, wintypes.HANDLE(-1).value):
        return 0
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    pids = []
    if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
        while True:
            if entry.szExeFile.lower() == "rundll32.exe":
                pids.append(entry.th32ProcessID)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snapshot)

    for pid in pids:
        modules = kernel32.CreateToolhelp32Snapshot(0x8 | 0x10, pid)  # SNAPMODULE
        if modules in (0, wintypes.HANDLE(-1).value):
            continue
        module = MODULEENTRY32W()
        module.dwSize = ctypes.sizeof(module)
        hosts_agent = False
        if kernel32.Module32FirstW(modules, ctypes.byref(module)):
            while True:
                if module.szModule.lower() == "agent.dll":
                    hosts_agent = True
                    break
                if not kernel32.Module32NextW(modules, ctypes.byref(module)):
                    break
        kernel32.CloseHandle(modules)
        if not hosts_agent:
            continue
        process = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
        if process and kernel32.TerminateProcess(process, 0):
            killed += 1
            logger.info("terminated the stale hook agent (pid %d)", pid)
        if process:
            kernel32.CloseHandle(process)
    return killed


def run_injector(status_path: Path = HOOK_STATUS) -> dict[str, str]:
    status = {
        "elevated": str(int(is_elevated())),
        "debug_privilege": "0",
        "debug_error": "0",
        "agent": "0",
        "payload": "0",
        "rc": "-1",
        "error": "injector did not run",
    }

    try:
        if sys.maxsize <= 2**32:
            status["error"] = "injector must run under 64-bit Python"
        elif not HOOK_INJECTOR_DLL.exists():
            status["error"] = f"missing {HOOK_INJECTOR_DLL}"
        elif not HOOK_PAYLOAD_DLL.exists():
            status["error"] = f"missing {HOOK_PAYLOAD_DLL}"
        elif not HOOK_AGENT_DLL.exists():
            status["error"] = f"missing {HOOK_AGENT_DLL}"
        elif not payload_available():
            status["error"] = f"missing {HOOK_PAYLOAD_FILE} (call build_payload_file first)"
        elif not is_elevated():
            status["error"] = "injector is not elevated"
        else:
            status["payload"] = "1"
            enabled, debug_error = enable_debug_privilege()
            status["debug_privilege"] = str(int(enabled))
            status["debug_error"] = str(debug_error)

            kill_stale_agents()
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

            injector = ctypes.CDLL(str(HOOK_INJECTOR_DLL))
            injector.inject.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            injector.inject.restype = ctypes.c_int
            injector.last_error.argtypes = []
            injector.last_error.restype = ctypes.c_char_p

            rc = injector.inject(payload_target(), os.fsencode(str(HOOK_PAYLOAD_DLL)))
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
    return (
        HOOK_INJECTOR_DLL.exists()
        and HOOK_PAYLOAD_DLL.exists()
        and HOOK_AGENT_DLL.exists()
        and payload_available()
    )


def target_running() -> bool:
    if is_running_wsl():
        # growtopia runs on the windows side; the wsl proxy just attaches later
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
    try:
        pairs = ctl.status(0.5)
    except Exception:
        return False

    return any(value in ("ready", "patched") for key, value in pairs.items() if key.startswith("hook_"))


def _wait_hooks_installed(timeout: float) -> HookControl | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ctl = HookControl()
        try:
            connected = ctl.connect(0.25)
        except Exception:
            connected = False
        if connected and _hooks_installed(ctl):
            return ctl
        ctl.close()
        time.sleep(0.25)

    return


def _ensure_hook_once() -> HookControl | None:
    if not hook_available():
        logger.info("hook unsupported")
        return

    ctl = HookControl()
    if ctl.connect(0.25) and _hooks_installed(ctl):
        logger.info("attached to the running hook")
        return ctl
    ctl.close()

    if not target_running():
        return

    if agent_running():
        fresh = _wait_hooks_installed(60.0)
        if fresh is not None:
            logger.info("the agent watch dog hooked the game")
            return fresh

    if not inject_hook():
        return

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        fresh = HookControl()
        if fresh.connect(0.25) and _hooks_installed(fresh):
            return fresh
        fresh.close()
        time.sleep(0.05)

    logger.error("the hook was injected but its control pipe did not report installed hooks")

    return


def ensure_hook(wait_forever: bool = True) -> HookControl | None:
    if sys.platform != "win32":
        # the hook runtime is windows-only; the wsl proxy uses the hosts redirect
        return None
    while True:
        try:
            hook_ctl = _ensure_hook_once()
        except UacDeclined:
            logger.warning("elevation declined, continuing without the hook")
            raise
        if hook_ctl is not None:
            return hook_ctl

        if not wait_forever:
            return

        if not target_running():
            time.sleep(0.5)
            continue

        time.sleep(1.0)


class UacDeclined(Exception):
    """The user declined the elevation prompt; the hook setup cannot continue."""


def _run_elevated_injector() -> bool:
    project_root = str(HOOKS_DIR.parent.parent)
    previous = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = project_root + (os.pathsep + previous if previous else "")
    try:
        result = elevate_ex(
            wait_for_child=True,
            timeout=150,
            argv=[sys.executable, "-m", "gtools.hooks.hook", str(HOOK_STATUS)],
            windowless=True,  # pythonw: no console window for the elevated helper
        )
        if result.cancelled:
            raise UacDeclined()
        return result.success
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
        try:
            started = _run_elevated_injector()
        except UacDeclined:
            raise
        if not started:
            logger.error("failed to start elevated injector (timed out)")
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
        logger.info("the hook is already injected")
        return True

    if status.get("rc") != "0":
        logger.error(f"failed to inject hook (rc={status.get('rc', '?')}): {status.get('error', 'unknown error')}")
        return False

    logger.info("hook injected")
    return True


# ---------------------------------------------------------------------------
# runtime sync (settings -> hook state/data)
# ---------------------------------------------------------------------------


def apply_hook_settings(ctl: HookControl, source: Setting | None = None) -> None:
    """Map user settings onto the Python-owned hook state (no C knowledge).

    Binds ``ctl`` as the registry's live control first: this runs before the
    listener thread on startup, and the runtime methods (``set_data`` etc.)
    push through that connection.
    """
    registry.set_control(ctl)
    current = source if source is not None else setting

    def apply_once() -> list[str]:
        """Push every setting; returns the descriptions that were rejected."""
        rejected: list[str] = []
        hook_settings = current.hook

        def push(action, description: str) -> None:
            try:
                ok = action()
            except (PipeError, OSError):
                raise  # the caller handles a dropped pipe
            if not ok:
                detail = f": {ctl.last_reply}" if ctl.last_reply else ""
                logger.warning("the hook rejected %s%s", description, detail)
                rejected.append(description)

        response = registry.get("net/response")
        push(lambda: response.set_data(programs.response_data(current.proxy_server, current.proxy_port)),
             "net/response proxy data")

        frame = registry.get("render/frame")
        push(lambda: frame.set_state(0, int(hook_settings.low_power_fps)), "render/frame fps")
        push(lambda: frame.set_enabled(bool(hook_settings.low_power)), "render/frame enable")

        submit = registry.get("render/submit")
        push(lambda: submit.set_state(0, 1 if hook_settings.low_power_skip_draws else 0), "render/submit skip")
        push(lambda: submit.set_enabled(bool(hook_settings.low_power and hook_settings.low_power_skip_draws)),
             "render/submit enable")

        try:
            ctl.log_level(int(hook_settings.log_level))
        except PipeError:
            logger.debug("could not push the agent log level", exc_info=True)
        return rejected

    # the agent may still be swapping between hooked game instances at startup:
    # an "unknown key" rejection is transient, retry the whole push
    for attempt in range(10):
        rejected = apply_once()
        if not rejected:
            if attempt:
                logger.info("hook settings applied after %d retry(s)", attempt)
            return
        time.sleep(0.3)
    logger.warning("hook settings still rejected after %d retries", 9)


def forward_hook_state(fields: dict[str, str]) -> None:
    """Publish a captured client/server state to the proxy event bus."""
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


def _on_setting_changed(_channel: str, event: SettingChanged) -> None:
    forwarded = [name for name, _, _ in event.changes if name in _SETTING_FIELDS_FORWARDED]
    if not forwarded:
        return

    logger.info("setting change (%s) queued for the hook", ", ".join(forwarded))
    _pending_settings_push.set()


def _push_pending_settings(ctl: HookControl) -> None:
    if not _pending_settings_push.is_set() or not ctl.connected:
        return

    _pending_settings_push.clear()

    try:
        apply_hook_settings(ctl)
    except (PipeError, OSError):
        _pending_settings_push.set()
        logger.exception("failed to push reloaded settings to the hook, retrying after reconnect")
    else:
        logger.info("pushed reloaded setting to the hook")


def _reattach_hook(stop: threading.Event) -> HookControl | None:
    while not stop.is_set():
        try:
            fresh = ensure_hook(wait_forever=False)
        except UacDeclined:
            logger.warning("elevation declined during reconnect, the hook stays detached")
            return None
        if fresh is not None:
            return fresh

        if not target_running():
            stop.wait(0.5)
            continue

        try:
            inject_hook()
        except UacDeclined:
            logger.warning("elevation declined during reconnect, the hook stays detached")
            return None
        stop.wait(1.0)

    return


def listen_hook_events(ctl: HookControl, stop: threading.Event) -> None:
    current = ctl
    unsubscribe = subscribe(SettingChanged, _on_setting_changed)
    sink = HookEventSink(on_state=forward_hook_state)
    registry.set_control(current)

    try:
        while not stop.is_set():
            try:
                _push_pending_settings(current)
            except Exception:
                logger.exception("failed to push reloaded settings to the hook")
                _pending_settings_push.clear()

            try:
                event = current.wait_event(timeout=0.5)
                sink.process(event)
            except Exception:
                logger.debug("failed to read a hook event", exc_info=True)
                continue

            if not current.connected:
                logger.warning("the hook control pipe was closed, waiting for the hook to return")
                registry.set_control(None)
                current.close()

                fresh = _reattach_hook(stop)
                if fresh is None:
                    return

                current = fresh
                registry.set_control(current)
                try:
                    apply_hook_settings(current)
                except PipeError:
                    logger.exception("hook setup failed after reconnect")
                    continue

                continue
    finally:
        unsubscribe()
        _pending_settings_push.clear()
        registry.set_control(None)


def inject_main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    status_path = Path(argv[0]) if argv else HOOK_STATUS
    build_payload_file()
    status = run_injector(status_path)
    print(
        f"[hook injector] elevated={status['elevated']} debug={status['debug_privilege']} rc={status['rc']}: {status['error']}",
        flush=True,
    )
    return 0 if status["rc"] == "0" else 1


if __name__ == "__main__":
    sys.exit(inject_main())
