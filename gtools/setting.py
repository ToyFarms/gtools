import atexit
import json
import logging
import threading
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from watchdog.events import DirModifiedEvent, FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from gtools.core.mixin import JsonMixin
from gtools.core.wsl import windows_home

logger = logging.getLogger("setting")

APPDIR = Path.home() / ".gtools"
APPDIR.mkdir(exist_ok=True)
SETTING_FILE = APPDIR / "setting.json"

_setting_lock = threading.RLock()
_setting = None
_observer = None


@dataclass
class ServerSetting(JsonMixin):
    # TODO: we should host this ourself
    login_url: str = field(default="login-gurotopia.vercel.app")
    server_data_host: str = field(default="0.0.0.0")
    server_data_port: int = field(default=443)
    enet_host: str = field(default="0.0.0.0")
    enet_port: int = field(default=18999)

@dataclass
class Setting(JsonMixin):
    server_data_url: str = field(default="www.growtopia1.com")
    proxy_server: str = field(default="127.0.0.1")
    proxy_port: int = field(default=16999)
    appdir: Path = field(default=Path(APPDIR))
    asset_path: Path = field(default=windows_home() / "AppData/Local/Growtopia")
    broker_addr: str = field(default="tcp://127.0.0.1:6712")
    spoof_hwident: bool = field(default=True)
    heartbeat_interval: float = field(default=1.0)
    heartbeat_threshold: float = field(default=5.0)
    panic_on_packet_error: bool = field(default=False)

    """
    growtopia real traffic always includes the so called "anomaly byte",
    which is a stray bytes at the end of every packet, the value is completely
    random (possibly out of bound memory read, or uninitialized memory)
    if this setting is on, it will compensate for that (and simulating too while at it)
    however, most 3rd party server (private server) usually doesnt have this kinda
    behavior so the packet will actually be parsed wrong.
    """
    anomaly_byte_compensation: bool = field(default=True)

    opengl_error_checking: bool = field(default=False)

    server: ServerSetting = field(default_factory=ServerSetting)

    def __getattribute__(self, name):
        with _setting_lock:
            return super().__getattribute__(name)

    def __setattr__(self, name, value):
        with _setting_lock:
            super().__setattr__(name, value)

    def save(self) -> None:
        logger.info(f"saved setting to {SETTING_FILE}")
        with _setting_lock:
            self.to_json_file(SETTING_FILE, 4)

    @staticmethod
    def load() -> "Setting":
        logger.info(f"loaded setting from {SETTING_FILE}")

        try:
            raw_keys = set(json.loads(SETTING_FILE.read_text()).keys())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"could not preload setting file for migration check: {e}")
            raw_keys = set()

        loaded = Setting.from_json_file(SETTING_FILE)

        missing_names = {f.name for f in fields(Setting)} - raw_keys
        if missing_names:
            logger.info(f"setting migrated, added {len(missing_names)} new field(s): " + ", ".join(sorted(missing_names)))
            loaded.save()

        return loaded


class _SettingFileHandler(FileSystemEventHandler):
    def on_modified(self, event: DirModifiedEvent | FileModifiedEvent) -> None:
        if not isinstance(event, FileModifiedEvent):
            return

        p = Path(event.src_path if isinstance(event.src_path, str) else event.src_path.decode())
        if p == SETTING_FILE:
            _reload()

    def on_created(self, event: DirModifiedEvent | FileModifiedEvent) -> None:
        if not isinstance(event, FileModifiedEvent):
            return

        p = Path(event.src_path if isinstance(event.src_path, str) else event.src_path.decode())
        if p == SETTING_FILE:
            _reload()


def _reload():
    global _setting
    with _setting_lock:
        try:
            old = _setting
            new = Setting.load()
            _setting = new
        except Exception:
            logger.exception("failed to reload setting, keeping previous")
            return

        if old is None:
            logger.info("setting loaded")
            return

        changes: list[tuple[str, Any, Any]] = []
        for f in fields(Setting):
            name = f.name
            old_val = getattr(old, name)
            new_val = getattr(new, name)
            if old_val != new_val:
                changes.append((name, old_val, new_val))

        if changes:
            logger.info(f"setting reloaded with {len(changes)} change(s):")
            for name, old_val, new_val in changes:
                logger.info(f"  {name}: {old_val} -> {new_val}")
        else:
            logger.info("setting reloaded (no changes)")


def _start_watchdog():
    handler = _SettingFileHandler()
    observer = Observer()
    observer.schedule(handler, str(SETTING_FILE.parent), recursive=False)
    observer.start()
    return observer


with _setting_lock:
    if SETTING_FILE.exists():
        _setting = Setting.load()
    else:
        _setting = Setting()
        _setting.save()

_observer = _start_watchdog()


@atexit.register
def _():
    if _observer:
        _observer.stop()
        _observer.join()


setting = _setting
