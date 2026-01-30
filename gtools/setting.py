import atexit
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
SETTING_FILE = APPDIR / "setting.json"

_setting_lock = threading.RLock()
_setting = None
_observer = None


@dataclass
class Setting(JsonMixin):
    server_data_url: str = field(default="www.growtopia1.com")
    proxy_server: str = field(default="127.0.0.1")
    proxy_port: int = field(default=16999)
    appdir: Path = field(default=Path(APPDIR))
    asset_path: Path = field(default=windows_home() / "AppData/Local/Growtopia/game")
    broker_addr: str = field(default="tcp://127.0.0.1:6712")
    spoof_hwident: bool = field(default=True)
    heartbeat_interval: float = field(default=1.0)
    heartbeat_threshold: float = field(default=5.0)
    panic_on_packet_error: bool = field(default=False)

    def __getattribute__(self, name):
        with _setting_lock:
            return super().__getattribute__(name)

    def __setattr__(self, name, value):
        with _setting_lock:
            super().__setattr__(name, value)

    def save(self) -> None:
        logging.info(f"saved setting to {SETTING_FILE}")
        with _setting_lock:
            self.to_json_file(SETTING_FILE, 4)

    @staticmethod
    def load() -> "Setting":
        logging.info(f"loaded setting from {SETTING_FILE}")
        return Setting.from_json_file(SETTING_FILE)


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
        old = _setting
        new = Setting.load()
        _setting = new

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
            logger.info("setting reloaded with %d change(s):", len(changes))
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
