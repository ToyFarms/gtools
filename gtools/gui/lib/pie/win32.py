"""Thin ctypes layer over the Win32 calls the pie menu needs (Windows only)."""
from __future__ import annotations

import ctypes
import os
import sys
import time
from ctypes import wintypes
from typing import Callable, Iterable, Optional, Tuple

if sys.platform != "win32":  # pragma: no cover
    raise ImportError("piemenu is Windows-only")

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_H, _D, _B = wintypes.HWND, wintypes.DWORD, wintypes.BOOL

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = _B
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = _B
user32.GetForegroundWindow.restype = _H
user32.SetForegroundWindow.argtypes = [_H]
user32.SetForegroundWindow.restype = _B
user32.BringWindowToTop.argtypes = [_H]
user32.GetWindowThreadProcessId.argtypes = [_H, ctypes.POINTER(_D)]
user32.GetWindowThreadProcessId.restype = _D
user32.AttachThreadInput.argtypes = [_D, _D, _B]
user32.AttachThreadInput.restype = _B
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.SetFocus.argtypes = [_H]
user32.SetFocus.restype = _H
user32.SetActiveWindow.argtypes = [_H]
user32.SetActiveWindow.restype = _H
user32.IsWindow.argtypes = [_H]
user32.IsWindow.restype = _B
user32.SetLayeredWindowAttributes.argtypes = [_H, wintypes.COLORREF, ctypes.c_ubyte, _D]
user32.GetLayeredWindowAttributes.argtypes = [
    _H, ctypes.POINTER(wintypes.COLORREF), ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(_D)]
user32.GetLayeredWindowAttributes.restype = _B
try:
    _get_long = user32.GetWindowLongPtrW
    _set_long = user32.SetWindowLongPtrW
except AttributeError:  # 32-bit Python
    _get_long, _set_long = user32.GetWindowLongW, user32.SetWindowLongW
_get_long.argtypes = [_H, ctypes.c_int]
_get_long.restype = ctypes.c_ssize_t
_set_long.argtypes = [_H, ctypes.c_int, ctypes.c_ssize_t]
_set_long.restype = ctypes.c_ssize_t

kernel32.GetCurrentThreadId.restype = _D
kernel32.OpenProcess.argtypes = [_D, _B, _D]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, _D, wintypes.LPWSTR, ctypes.POINTER(_D)]
kernel32.QueryFullProcessImageNameW.restype = _B

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
LWA_ALPHA = 0x00000002
VK_LBUTTON, VK_RBUTTON, VK_MBUTTON, VK_ESCAPE = 0x01, 0x02, 0x04, 0x1B


# ----------------------------------------------------------------- input ---
def cursor_pos() -> Tuple[int, int]:
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def set_cursor_pos(x: int, y: int) -> None:
    user32.SetCursorPos(int(x), int(y))


def key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def mouse_buttons() -> Tuple[bool, bool, bool]:
    """(left, right, middle) as the user perceives them (honours swapped buttons)."""
    l, r, m = key_down(VK_LBUTTON), key_down(VK_RBUTTON), key_down(VK_MBUTTON)
    return (r, l, m) if user32.GetSystemMetrics(23) else (l, r, m)  # SM_SWAPBUTTON


# --------------------------------------------------------------- windows ---
def modify_exstyle(hwnd: int, add: int = 0, remove: int = 0) -> None:
    cur = _get_long(hwnd, GWL_EXSTYLE)
    new = (cur | add) & ~remove
    if new != cur:
        _set_long(hwnd, GWL_EXSTYLE, new)


def set_click_through(hwnd: int, enabled: bool) -> None:
    """Mouse passthrough for GLFW < 3.4 (which lacks GLFW_MOUSE_PASSTHROUGH).

    Mirrors GLFW 3.4's ``_glfwSetWindowMousePassthroughWin32`` exactly, including
    preserving existing layered-window attributes, so a transparent-framebuffer
    window keeps its DWM composition.
    """
    key = wintypes.COLORREF(0)
    alpha = ctypes.c_ubyte(0)
    flags = _D(0)
    ex = _get_long(hwnd, GWL_EXSTYLE)

    if ex & WS_EX_LAYERED:
        user32.GetLayeredWindowAttributes(
            hwnd, ctypes.byref(key), ctypes.byref(alpha), ctypes.byref(flags))

    if enabled:
        ex |= WS_EX_TRANSPARENT | WS_EX_LAYERED
    else:
        ex &= ~WS_EX_TRANSPARENT
        # Opacity also needs WS_EX_LAYERED, so keep it if alpha blending is set.
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
    """Bring `hwnd` to the foreground even if another process owns it.

    Windows normally refuses SetForegroundWindow from a background process;
    attaching to the foreground thread's input queue is the standard workaround.
    focus=True also makes `hwnd` the active/keyboard-focus window (use it for our own
    windows that need typing; never for restoring another app, whose focused child
    control would otherwise be replaced by its top-level frame).
    """
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
        if focus:  # must happen while the queues are still attached
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
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = _D(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(h)
    return ""


def foreground_process() -> Tuple[int, str]:
    """(pid, lowercase exe name) of the foreground window's process."""
    hwnd = foreground_hwnd()
    if not hwnd:
        return 0, ""
    pid = _D(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value, _process_name(pid.value)


class FocusFilter:
    """Decides whether the menu may open given the current foreground app.

    processes=None            -> global: always allowed.
    processes=["a.exe", ...]  -> only while one of those processes is in the foreground.
    include_self=True         -> this process always counts as a target.
    predicate(pid, exe)       -> optional extra rule, ORed with the list.
    """

    def __init__(self, processes: Optional[Iterable[str]] = None, *,
                 include_self: bool = True,
                 predicate: Optional[Callable[[int, str], bool]] = None):
        self.include_self = include_self
        self.predicate = predicate
        self.processes = self._norm(processes)

    @staticmethod
    def _norm(names: Optional[Iterable[str]]):
        if names is None:
            return None
        out = set()
        for n in names:
            n = os.path.basename(str(n)).lower().strip()
            out.add(n if "." in n else n + ".exe")
        return out

    def set_processes(self, names: Optional[Iterable[str]]) -> None:
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
