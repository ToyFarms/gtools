import logging
from pathlib import Path
import subprocess
import sys
import threading
import time

from gtools.core.privilege import elevate
from gtools.hooks.control import HookControl
from gtools.hooks.inject import is_elevated
from gtools.proxy.event import UpdateClientVersion, UpdateServerData
from gtools.setting import setting

logger = logging.getLogger("hook")


HOOKS_DIR = Path(__file__).resolve().parent
HOOK_INJECTOR = HOOKS_DIR / "inject.py"
HOOK_PAYLOAD = HOOKS_DIR / "hook.dll"
HOOK_STATUS = HOOKS_DIR / "inject.status"
HOOK_CONFIG = HOOKS_DIR / "hook.cfg"


def hook_available() -> bool:
    return (HOOKS_DIR / "injector.dll").exists() and HOOK_PAYLOAD.exists() and HOOK_INJECTOR.exists()


def ensure_hook_config() -> None:
    lines = HOOK_CONFIG.read_text(encoding="utf-8").splitlines() if HOOK_CONFIG.exists() else []
    managed = {
        "proxy_host",
        "proxy_port",
        "handshake_file",
        "handshake",
        "log_file",
        "out_of_process",
        "server_ip",
        "server_port",
        "notify_url",
        "notify_format",
        "server_type",
        "loginurl",
        "nop_request",
        "verbose",
    }
    lines = [line for line in lines if line.split("=", 1)[0].strip() not in managed]
    lines += [
        f"proxy_host = {setting.proxy_server}",
        f"proxy_port = {setting.proxy_port}",
    ]
    HOOK_CONFIG.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def inject_hook() -> bool:
    ensure_hook_config()

    try:
        HOOK_STATUS.unlink()
    except FileNotFoundError:
        pass

    argv = [sys.executable, str(HOOK_INJECTOR)]

    if is_elevated():
        result = subprocess.run(argv, check=False)
        if result.returncode != 0 and not HOOK_STATUS.exists():
            logger.error(f"injector helper exited with code {result.returncode}")
            return False
    elif not elevate(wait_for_child=True, timeout=90, argv=argv):
        logger.error("failed to start elevated injector (UAC cancelled or timed out)")
        return False

    status = read_inject_status()
    if not status:
        logger.error("injector helper did not write a status file")
        return False

    if status.get("elevated") != "1":
        logger.error("injector helper was not elevated, cannot open Growtopia")
        return False

    if status.get("debug_privilege") != "1":
        logger.warning(f"failed to enable SeDebugPrivilege (error {status.get('debug_error', '?')})")

    if status.get("rc") != "0":
        logger.error(f"failed to inject hook (rc={status.get('rc', '?')}): {status.get('error', 'unknown error')}")
        return False

    logger.info("hook injected")
    return True


def ensure_hook() -> HookControl | None:
    ctl = HookControl()
    if ctl.connect(0.25):
        logger.info("attached to existing hook DLL")
        ensure_hook_config()
        return ctl

    if not hook_available():
        logger.info("hook unsupported")
        return None

    if not inject_hook():
        return None

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if ctl.connect(0.25):
            logger.info("hook control connected")
            return ctl

        time.sleep(0.05)

    logger.error("hook was injected but its control pipe did not appear")

    return


def apply_hook_settings(ctl: HookControl) -> None:
    values = {
        "proxy_host": setting.proxy_server,
        "proxy_port": str(setting.proxy_port),
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


def listen_hook_events(ctl: HookControl, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            event = ctl.wait_event(timeout=0.5)
        except Exception:
            logger.debug("failed to read a hook event", exc_info=True)
            continue

        if not ctl.connected:
            logger.warning("the hook control pipe was closed")
            return

        if event is None:
            continue

        if event.name == "state":
            publish_hook_state(event.fields)
        elif event.name == "log":
            logger.info("[game] %s", event.payload)
