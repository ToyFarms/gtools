import ctypes
import os
import sys
from ctypes.wintypes import COLORREF, HANDLE, HWND, BOOL, DWORD, LPWSTR, POINT
from typing import Callable, Iterable

if sys.platform != "win32":
    raise ImportError("piemenu is Windows only")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = BOOL
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = BOOL
user32.GetForegroundWindow.restype = HWND
user32.SetForegroundWindow.argtypes = [HWND]
user32.SetForegroundWindow.restype = BOOL
user32.BringWindowToTop.argtypes = [HWND]
user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(DWORD)]
user32.GetWindowThreadProcessId.restype = DWORD
user32.AttachThreadInput.argtypes = [DWORD, DWORD, BOOL]
user32.AttachThreadInput.restype = BOOL
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.SetFocus.argtypes = [HWND]
user32.SetFocus.restype = HWND
user32.SetActiveWindow.argtypes = [HWND]
user32.SetActiveWindow.restype = HWND
user32.IsWindow.argtypes = [HWND]
user32.IsWindow.restype = BOOL
user32.SetLayeredWindowAttributes.argtypes = [HWND, COLORREF, ctypes.c_ubyte, DWORD]
user32.GetLayeredWindowAttributes.argtypes = [HWND, ctypes.POINTER(COLORREF), ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(DWORD)]
user32.GetLayeredWindowAttributes.restype = BOOL
try:
    _get_long = user32.GetWindowLongPtrW
    _set_long = user32.SetWindowLongPtrW
except AttributeError:
    _get_long, _set_long = user32.GetWindowLongW, user32.SetWindowLongW

_get_long.argtypes = [HWND, ctypes.c_int]
_get_long.restype = ctypes.c_ssize_t
_set_long.argtypes = [HWND, ctypes.c_int, ctypes.c_ssize_t]
_set_long.restype = ctypes.c_ssize_t

kernel32.GetCurrentThreadId.restype = DWORD
kernel32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
kernel32.OpenProcess.restype = HANDLE
kernel32.CloseHandle.argtypes = [HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [HANDLE, DWORD, LPWSTR, ctypes.POINTER(DWORD)]
kernel32.QueryFullProcessImageNameW.restype = BOOL

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
LWA_ALPHA = 0x00000002
VK_LBUTTON, VK_RBUTTON, VK_MBUTTON, VK_ESCAPE = 0x01, 0x02, 0x04, 0x1B
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def cursor_pos() -> tuple[int, int]:
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def set_cursor_pos(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def mouse_buttons() -> tuple[bool, bool, bool]:
    l, r, m = key_down(VK_LBUTTON), key_down(VK_RBUTTON), key_down(VK_MBUTTON)
    return (r, l, m) if user32.GetSystemMetrics(23) else (l, r, m)  # SM_SWAPBUTTON


def modify_exstyle(hwnd: int, add: int = 0, remove: int = 0) -> None:
    cur = _get_long(hwnd, GWL_EXSTYLE)
    new = (cur | add) & ~remove
    if new != cur:
        _set_long(hwnd, GWL_EXSTYLE, new)


def set_click_through(hwnd: int, enabled: bool) -> None:
    key = COLORREF(0)
    alpha = ctypes.c_ubyte(0)
    flags = DWORD(0)
    ex = _get_long(hwnd, GWL_EXSTYLE)

    if ex & WS_EX_LAYERED:
        user32.GetLayeredWindowAttributes(hwnd, ctypes.byref(key), ctypes.byref(alpha), ctypes.byref(flags))

    if enabled:
        ex |= WS_EX_TRANSPARENT | WS_EX_LAYERED
    else:
        ex &= ~WS_EX_TRANSPARENT
        if ex & WS_EX_LAYERED and not (flags.value & LWA_ALPHA):
            ex &= ~WS_EX_LAYERED

    _set_long(hwnd, GWL_EXSTYLE, ex)
    if enabled:
        user32.SetLayeredWindowAttributes(hwnd, key, alpha, flags)


def foreground_hwnd() -> int:
    return int(user32.GetForegroundWindow() or 0)


def window_alive(hwnd: int) -> bool:
    return bool(hwnd) and bool(user32.IsWindow(hwnd))


def force_foreground(hwnd: int, focus: bool = False) -> bool:
    fg = foreground_hwnd()
    if fg == hwnd:
        if focus:
            user32.SetFocus(hwnd)
        return True
    cur = kernel32.GetCurrentThreadId()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(fg_tid and fg_tid != cur and user32.AttachThreadInput(cur, fg_tid, True))
    try:
        user32.BringWindowToTop(hwnd)
        ok = bool(user32.SetForegroundWindow(hwnd))
        if focus:
            user32.SetActiveWindow(hwnd)
            user32.SetFocus(hwnd)
        return ok and foreground_hwnd() == hwnd
    finally:
        if attached:
            user32.AttachThreadInput(cur, fg_tid, False)


def restore_foreground(hwnd: int) -> None:
    if window_alive(hwnd):
        force_foreground(hwnd)


def _process_name(pid: int) -> str:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""

    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(h)

    return ""


def foreground_process() -> tuple[int, str]:
    hwnd = foreground_hwnd()
    if not hwnd:
        return 0, ""

    pid = DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    return pid.value, _process_name(pid.value)


class FocusFilter:
    def __init__(self, processes: Iterable[str] | None = None, *, include_self: bool = True, predicate: Callable[[int, str], bool] | None = None) -> None:
        self.include_self = include_self
        self.predicate = predicate
        self.processes = self._norm(processes)

    @staticmethod
    def _norm(names: Iterable[str] | None):
        if names is None:
            return

        out = set()
        for n in names:
            n = os.path.basename(str(n)).lower().strip()
            out.add(n if "." in n else n + ".exe")

        return out

    def set_processes(self, names: Iterable[str] | None) -> None:
        self.processes = self._norm(names)

    def allows(self) -> bool:
        if self.processes is None and self.predicate is None:
            return True

        pid, exe = foreground_process()
        if not pid:
            return False

        if self.include_self and pid == os.getpid():
            return True

        if self.processes is None:
            return True if self.predicate is None else bool(self.predicate(pid, exe))

        if exe in self.processes:
            return True

        return bool(self.predicate and self.predicate(pid, exe))
