import ctypes
from ctypes import wintypes
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
ERROR_FILE_NOT_FOUND = 2
ERROR_PIPE_BUSY = 231
ERROR_BROKEN_PIPE = 109
ERROR_PIPE_NOT_CONNECTED = 233

_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

_kernel32 = None
if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    _kernel32.WaitNamedPipeW.restype = wintypes.BOOL
    _kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    _kernel32.WriteFile.restype = wintypes.BOOL
    _kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    _kernel32.ReadFile.restype = wintypes.BOOL
    _kernel32.PeekNamedPipe.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.PeekNamedPipe.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL


class PipeError(RuntimeError):
    """Base class for the pipe transport errors."""


class PipeUnavailable(PipeError):
    """The pipe server is not running or refused the connection."""


class PipeClosed(PipeError):
    """The connection was closed while a request was in flight."""


@dataclass(frozen=True)
class PipeEvent:
    name: str
    payload: str = ""

    @property
    def fields(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for part in self.payload.split(" "):
            key, separator, value = part.partition("=")
            if separator:
                result[key] = value

        return result


@dataclass(frozen=True)
class PipeResponse:
    kind: str
    text: str

    @property
    def ok(self) -> bool:
        return self.kind == "OK"

    @property
    def failed(self) -> bool:
        return self.kind == "ERR"


def _open_pipe(name: str, timeout: float) -> int:
    if _kernel32 is None:
        raise PipeUnavailable("named pipes are only available on windows")

    deadline = time.monotonic() + timeout
    while True:
        handle = _kernel32.CreateFileW(name, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, 0, None)
        if handle not in (None, 0, _INVALID_HANDLE_VALUE):
            return handle

        error = ctypes.get_last_error()
        if error == ERROR_PIPE_BUSY:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PipeUnavailable("the pipe is busy")
            _kernel32.WaitNamedPipeW(name, max(1, int(remaining * 1000)))
            continue

        if error == ERROR_FILE_NOT_FOUND:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PipeUnavailable("the pipe server is not running")
            time.sleep(min(0.02, remaining))
            continue

        raise PipeUnavailable(f"cannot open the pipe (windows error {error})")


class PipeClient:
    def __init__(self, name: str, connect_timeout: float = 2.0, io_timeout: float = 5.0) -> None:
        self.name = name
        self.connect_timeout = connect_timeout
        self.io_timeout = io_timeout

        self._handle: int | None = None
        self._responses: queue.Queue[PipeResponse | None] = queue.Queue()
        self._events: queue.Queue[PipeEvent] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._closing = threading.Event()
        self._disconnected = threading.Event()
        self._buffer = bytearray()

    def connect(self, timeout: float | None = None) -> None:
        if self._handle is not None:
            return
        self._handle = _open_pipe(self.name, self.connect_timeout if timeout is None else timeout)
        self._closing.clear()
        self._reader = threading.Thread(target=self._read_loop, name="pipe-reader", daemon=True)
        self._reader.start()

    def close(self) -> None:
        self._closing.set()
        self._disconnected.set()
        handle = self._handle
        self._handle = None
        if handle is not None and _kernel32 is not None:
            _kernel32.CloseHandle(handle)
        self._responses.put(None)

    @property
    def connected(self) -> bool:
        return self._handle is not None and not self._disconnected.is_set()

    def __enter__(self) -> "PipeClient":
        self.connect()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def send(self, text: str) -> None:
        assert _kernel32
        handle = self._handle
        if handle is None:
            raise PipeClosed("the pipe is not connected")

        payload = (text + "\n").encode("utf-8")
        buffer = ctypes.create_string_buffer(payload, len(payload))
        written = wintypes.DWORD(0)
        if not _kernel32.WriteFile(handle, buffer, len(payload), ctypes.byref(written), None):
            raise PipeError(f"cannot write to the pipe (windows error {ctypes.get_last_error()})")
        if written.value != len(payload):
            raise PipeError("short write to the pipe")

    def request(self, command: str, timeout: float | None = None) -> PipeResponse:
        timeout = self.io_timeout if timeout is None else timeout
        self.send(command)

        try:
            response = self._responses.get(timeout=timeout)
        except queue.Empty:
            raise PipeError(f"timed out waiting for the reply to {command!r}") from None

        if response is None:
            raise PipeClosed("the pipe was closed while waiting for a reply")
        return response

    def wait_event(self, timeout: float | None = None) -> PipeEvent | None:
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            return

    def _read_loop(self) -> None:
        assert _kernel32
        handle = self._handle
        if handle is None:
            return

        try:
            while not self._closing.is_set():
                available = wintypes.DWORD(0)
                if not _kernel32.PeekNamedPipe(handle, None, 0, None, ctypes.byref(available), None):
                    break
                if available.value == 0:
                    time.sleep(0.005)
                    continue

                buffer = ctypes.create_string_buffer(available.value)
                read = wintypes.DWORD(0)
                if not _kernel32.ReadFile(handle, buffer, available.value, ctypes.byref(read), None) or read.value == 0:
                    break

                self._buffer += buffer.raw[: read.value]
                while True:
                    index = self._buffer.find(b"\n")
                    if index < 0:
                        break
                    line = bytes(self._buffer[:index])
                    del self._buffer[: index + 1]
                    self._dispatch(line.decode("utf-8", "replace"))
        except Exception:
            logger.debug("the pipe reader stopped", exc_info=True)
        finally:
            self._disconnected.set()
            self._responses.put(None)

    def _dispatch(self, line: str) -> None:
        line = line.strip()
        if not line:
            return

        kind, _, text = line.partition(" ")
        if kind == "EVENT":
            name, _, payload = text.partition(" ")
            self._events.put(PipeEvent(name=name, payload=payload))
            return

        self._responses.put(PipeResponse(kind=kind, text=text))
