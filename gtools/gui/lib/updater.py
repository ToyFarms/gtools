import concurrent.futures
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto

import requests

logger = logging.getLogger("gui-updater")

_MASKED_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

_DEFAULT_SEGMENT_COUNT = 8
_CHUNK_SIZE = 64 * 1024
_MIN_SEGMENT_SIZE = 1 * 1024 * 1024
_HTTP_TIMEOUT = 15

_SILENT_INSTALL_FLAGS = ("/S", "/VERYSILENT /NORESTART", "/quiet")
_FLAG_REJECT_FAST_EXIT_S = 2.5

_GAME_PROCESS_NAME = "Growtopia.exe"
_GAME_WINDOW_TITLE = "Growtopia"

_CHILD_INSTALLER_TITLE_PATTERNS = (
    "microsoft visual c++",
    "visual c++ 20",
    "microsoft .net",
    "directx",
)
_UAC_TITLE_MARKER = "user account control"


class UpdateState(Enum):
    IDLE = auto()
    PREPARING = auto()
    DOWNLOADING = auto()
    DOWNLOADED = auto()
    KILLING_PROCESS = auto()
    INSTALLING = auto()
    DONE = auto()
    ERROR = auto()
    CANCELLED = auto()


@dataclass
class Segment:
    index: int
    start: int
    end: int  # inclusive
    downloaded: int = 0

    @property
    def size(self) -> int:
        return self.end - self.start + 1

    @property
    def done(self) -> bool:
        return self.downloaded >= self.size

    @property
    def progress(self) -> float:
        if self.size <= 0:
            return 1.0

        return min(1.0, self.downloaded / self.size)


@dataclass
class UpdaterState:
    state: UpdateState = UpdateState.IDLE
    segments: list[Segment] = field(default_factory=list)
    total_size: int = 0
    error: str | None = None
    installer_path: str | None = None
    used_silent_install: bool = False
    attempted_flag: str | None = None

    @property
    def downloaded_bytes(self) -> int:
        return sum(s.downloaded for s in self.segments)

    @property
    def progress(self) -> float:
        if self.total_size <= 0:
            return 0.0
        return min(1.0, self.downloaded_bytes / self.total_size)


class Updater:
    def __init__(self, dest_dir: str | None = None) -> None:
        self._dest_dir = dest_dir or os.path.join(os.path.expanduser("~"), "Downloads")
        self._lock = threading.Lock()
        self.state = UpdaterState()
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._worker_thread: threading.Thread | None = None
        self._cancel = threading.Event()

    def start(self, url: str, version: str, segment_count: int = _DEFAULT_SEGMENT_COUNT) -> None:
        if self.state.state in (
            UpdateState.PREPARING,
            UpdateState.DOWNLOADING,
            UpdateState.KILLING_PROCESS,
            UpdateState.INSTALLING,
        ):
            return

        self._cancel.clear()
        with self._lock:
            self.state = UpdaterState(state=UpdateState.PREPARING)

        self._worker_thread = threading.Thread(target=self._run, args=(url, version, segment_count), daemon=True, name="updater")
        self._worker_thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def _run(self, url: str, version: str, segment_count: int) -> None:
        try:
            self._download(url, version, segment_count)
            if self._cancel.is_set():
                self._set_state(UpdateState.CANCELLED)
                return

            self._kill_game_process()
            if self._cancel.is_set():
                self._set_state(UpdateState.CANCELLED)
                return

            self._run_installer()
            self._set_state(UpdateState.DONE)
        except Exception as e:
            logger.exception("update failed")
            with self._lock:
                self.state.state = UpdateState.ERROR
                self.state.error = str(e)

    def _set_state(self, state: UpdateState) -> None:
        with self._lock:
            self.state.state = state

    def _download(self, url: str, version: str, segment_count: int) -> None:
        headers = {"User-Agent": _MASKED_USER_AGENT}

        with requests.get(url, headers=headers, stream=True, timeout=_HTTP_TIMEOUT) as resp:
            resp.raise_for_status()
            total_size = int(resp.headers.get("Content-Length", 0))
            accepts_ranges = resp.headers.get("Accept-Ranges", "").lower() == "bytes"

        os.makedirs(self._dest_dir, exist_ok=True)
        dest_path = os.path.join(self._dest_dir, f"growtopia_update_{version}.exe")

        if total_size <= 0 or not accepts_ranges:
            segments = [Segment(index=0, start=0, end=max(total_size - 1, 0))]
        else:
            count = max(1, min(segment_count, max(1, total_size // _MIN_SEGMENT_SIZE)))
            segments = _split_segments(total_size, count)

        with self._lock:
            self.state.state = UpdateState.DOWNLOADING
            self.state.segments = segments
            self.state.total_size = total_size

        with open(dest_path, "wb") as f:
            if total_size > 0:
                f.truncate(total_size)

        ranged = len(segments) > 1
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=len(segments))
        try:
            futures = [self._executor.submit(self._download_segment, url, headers, dest_path, seg, ranged) for seg in segments]
            for fut in concurrent.futures.as_completed(futures):
                if self._cancel.is_set():
                    break
                fut.result()
        finally:
            self._executor.shutdown(wait=False, cancel_futures=True)

        if self._cancel.is_set():
            return

        with self._lock:
            self.state.state = UpdateState.DOWNLOADED
            self.state.installer_path = dest_path

    def _download_segment(self, url: str, headers: dict[str, str], dest_path: str, seg: Segment, ranged: bool) -> None:
        req_headers = dict(headers)
        if ranged:
            req_headers["Range"] = f"bytes={seg.start}-{seg.end}"

        with requests.get(url, headers=req_headers, stream=True, timeout=_HTTP_TIMEOUT) as resp:
            resp.raise_for_status()
            with open(dest_path, "r+b") as f:
                f.seek(seg.start)
                for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                    if self._cancel.is_set():
                        return
                    if not chunk:
                        continue
                    f.write(chunk)
                    with self._lock:
                        seg.downloaded += len(chunk)

    def _kill_game_process(self) -> None:
        self._set_state(UpdateState.KILLING_PROCESS)

        pids = _find_pids_by_window_title(_GAME_WINDOW_TITLE, exact=True)
        pids |= _find_pids_by_image_name(_GAME_PROCESS_NAME)

        if not pids:
            logger.info("no running Growtopia window/process found, nothing to kill")
        for pid in pids:
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10)
            except FileNotFoundError:
                logger.warning("taskkill not available on this platform, skipping process kill")
                break
            except Exception:
                logger.exception("failed to kill pid %s", pid)

        time.sleep(1.0)

    def _run_installer(self) -> None:
        with self._lock:
            self.state.state = UpdateState.INSTALLING
            path = self.state.installer_path

        if not path:
            raise RuntimeError("no installer path to run")

        stop_watcher = threading.Event()
        watcher_thread = threading.Thread(target=_watch_and_dismiss_child_installers, args=(stop_watcher,), daemon=True, name="updater-child-watch")
        watcher_thread.start()

        try:
            for flag_str in _SILENT_INSTALL_FLAGS:
                args = [path, *flag_str.split()]
                with self._lock:
                    self.state.attempted_flag = flag_str

                try:
                    proc = subprocess.Popen(args)
                except Exception:
                    logger.debug("failed to launch installer with %s", flag_str, exc_info=True)
                    continue

                try:
                    returncode = proc.wait(timeout=_FLAG_REJECT_FAST_EXIT_S)
                except subprocess.TimeoutExpired:
                    returncode = proc.wait()

                if returncode == 0:
                    with self._lock:
                        self.state.used_silent_install = True
                    return

                logger.debug("installer exited %s with flag %r, trying next", returncode, flag_str)

            logger.info("no silent install flag succeeded, launching installer normally")
            with self._lock:
                self.state.attempted_flag = None

            subprocess.Popen([path]).wait()
        finally:
            stop_watcher.set()
            watcher_thread.join(timeout=2.0)


def _split_segments(total_size: int, count: int) -> list[Segment]:
    base = total_size // count
    segments: list[Segment] = []
    start = 0
    for i in range(count):
        end = start + base - 1 if i < count - 1 else total_size - 1
        segments.append(Segment(index=i, start=start, end=end))
        start = end + 1

    return segments


def _enum_visible_windows() -> list[tuple[int, str]]:
    if sys.platform != "win32":
        return []

    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[tuple[int, str]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value:
            found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(_callback, 0)
    return found


def _pid_for_window(hwnd: int) -> int | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value or None


def _find_pids_by_window_title(title: str, exact: bool = True) -> set[int]:
    pids: set[int] = set()
    for hwnd, window_title in _enum_visible_windows():
        matched = window_title == title if exact else title.lower() in window_title.lower()
        if not matched:
            continue
        pid = _pid_for_window(hwnd)
        if pid:
            pids.add(pid)

    return pids


def _find_pids_by_image_name(image_name: str) -> set[int]:
    if sys.platform != "win32":
        return set()

    pids: set[int] = set()
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image_name}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        logger.debug("tasklist lookup failed", exc_info=True)
        return pids

    for line in result.stdout.splitlines():
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) >= 2 and parts[0].lower() == image_name.lower() and parts[1].isdigit():
            pids.add(int(parts[1]))
    return pids


def _watch_and_dismiss_child_installers(stop_event: threading.Event) -> None:
    if sys.platform != "win32":
        return

    import ctypes

    user32 = ctypes.windll.user32
    handled: set[int] = set()

    while not stop_event.is_set():
        for hwnd, title in _enum_visible_windows():
            title_lower = title.lower()
            if _UAC_TITLE_MARKER in title_lower:
                continue
            if hwnd in handled:
                continue
            if not any(pattern in title_lower for pattern in _CHILD_INSTALLER_TITLE_PATTERNS):
                continue

            logger.info("auto-confirming bundled prerequisite installer window: %r", title)
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.15)
            user32.keybd_event(0x0D, 0, 0, 0)
            user32.keybd_event(0x0D, 0, 2, 0)
            handled.add(hwnd)

        stop_event.wait(0.75)
