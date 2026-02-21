from dataclasses import dataclass
import math
import sys
from typing import Union
import queue
import logging

import glfw

logger = logging.getLogger("gui-input")


@dataclass(slots=True)
class FingerDragEvent:
    dx: float
    dy: float
    x: float  # centroid X
    y: float  # centroid Y


@dataclass(slots=True)
class FingerPinchEvent:
    scale: float
    x: float  # centroid X
    y: float  # centroid Y


@dataclass(slots=True)
class FingerRotateEvent:
    delta: float
    x: float  # centroid X
    y: float  # centroid Y


FingerEvent = Union[FingerDragEvent, FingerPinchEvent, FingerRotateEvent]

_MIN_DRAG_PX = 0.5
_MIN_SCALE_DIFF = 0.002
_MIN_ANGLE_RAD = 0.002


class _TouchPoint:
    __slots__ = ("id", "x", "y")

    def __init__(self, tid: int, x: float, y: float) -> None:
        self.id = tid
        self.x = x
        self.y = y


def _centroid(a: _TouchPoint, b: _TouchPoint) -> tuple[float, float]:
    return (a.x + b.x) * 0.5, (a.y + b.y) * 0.5


def _distance(a: _TouchPoint, b: _TouchPoint) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _angle(a: _TouchPoint, b: _TouchPoint) -> float:
    return math.atan2(b.y - a.y, b.x - a.x)


class _FingerRouterBase:
    def __init__(self, window, *, dead_zone_px: float = _MIN_DRAG_PX, dead_zone_scale: float = _MIN_SCALE_DIFF, dead_zone_angle: float = _MIN_ANGLE_RAD) -> None:
        self._window = window
        self._dz_px = dead_zone_px
        self._dz_scale = dead_zone_scale
        self._dz_angle = dead_zone_angle

        self._queue: queue.SimpleQueue[FingerEvent] = queue.SimpleQueue()

        self._points: dict[int, _TouchPoint] = {}

        self._prev_cx: float | None = None
        self._prev_cy: float | None = None
        self._prev_dist: float | None = None
        self._prev_angle: float | None = None

    def poll(self) -> list[FingerEvent]:
        events: list[FingerEvent] = []
        while not self._queue.empty():
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    def uninstall(self) -> None:
        pass

    def _reset_two_finger_state(self) -> None:
        self._prev_cx = None
        self._prev_cy = None
        self._prev_dist = None
        self._prev_angle = None

    def _emit_gestures(self) -> None:
        if len(self._points) != 2:
            return

        a, b = tuple(self._points.values())

        cx, cy = _centroid(a, b)
        dist = _distance(a, b)
        angle = _angle(a, b)

        if self._prev_cx is None:
            self._prev_cx = cx
            self._prev_cy = cy
            self._prev_dist = dist
            self._prev_angle = angle

            return

        assert self._prev_cy and self._prev_angle

        dx = cx - self._prev_cx
        dy = cy - self._prev_cy
        if math.hypot(dx, dy) >= self._dz_px:
            self._queue.put(FingerDragEvent(dx=dx, dy=dy, x=cx, y=cy))

        if self._prev_dist and self._prev_dist > 1e-6:
            scale = dist / self._prev_dist
            if abs(scale - 1.0) >= self._dz_scale:
                self._queue.put(FingerPinchEvent(scale=scale, x=cx, y=cy))

        delta = angle - self._prev_angle
        delta = (delta + math.pi) % (2 * math.pi) - math.pi
        if abs(delta) >= self._dz_angle:
            self._queue.put(FingerRotateEvent(delta=delta, x=cx, y=cy))

        self._prev_cx = cx
        self._prev_cy = cy
        self._prev_dist = dist
        self._prev_angle = angle


if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as wt

    WM_TOUCH = 0x0240
    TOUCHEVENTF_MOVE = 0x0001
    TOUCHEVENTF_DOWN = 0x0002
    TOUCHEVENTF_UP = 0x0004
    GWLP_WNDPROC = -4

    _user32 = ctypes.WinDLL("user32", use_last_error=True)

    class _TOUCHINPUT(ctypes.Structure):
        _fields_ = [
            ("x", wt.LONG),
            ("y", wt.LONG),
            ("hSource", wt.HANDLE),
            ("dwID", wt.DWORD),
            ("dwFlags", wt.DWORD),
            ("dwMask", wt.DWORD),
            ("dwTime", wt.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
            ("cxContact", wt.DWORD),
            ("cyContact", wt.DWORD),
        ]

    _WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        wt.HWND,
        wt.UINT,
        wt.WPARAM,
        wt.LPARAM,
    )

    _GetTouchInputInfo = _user32.GetTouchInputInfo
    _GetTouchInputInfo.restype = wt.BOOL
    _GetTouchInputInfo.argtypes = [
        wt.HANDLE,
        wt.UINT,
        ctypes.POINTER(_TOUCHINPUT),
        ctypes.c_int,
    ]

    _CloseTouchInputHandle = _user32.CloseTouchInputHandle
    _CloseTouchInputHandle.restype = wt.BOOL
    _CloseTouchInputHandle.argtypes = [wt.HANDLE]

    _RegisterTouchWindow = _user32.RegisterTouchWindow
    _RegisterTouchWindow.restype = wt.BOOL
    _RegisterTouchWindow.argtypes = [wt.HWND, wt.ULONG]

    _SetWindowLongPtrW = _user32.SetWindowLongPtrW
    _SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]

    _CallWindowProcW = _user32.CallWindowProcW
    _CallWindowProcW.restype = ctypes.c_ssize_t
    _CallWindowProcW.argtypes = [
        ctypes.c_ssize_t,
        wt.HWND,
        wt.UINT,
        wt.WPARAM,
        wt.LPARAM,
    ]

    _ScreenToClient = _user32.ScreenToClient
    _ScreenToClient.restype = wt.BOOL
    _ScreenToClient.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]

    class _WindowsFingerRouter(_FingerRouterBase):
        def __init__(self, window, **kwargs) -> None:
            super().__init__(window, **kwargs)

            hwnd = glfw.get_win32_window(window)
            self._hwnd: int = hwnd

            if not _RegisterTouchWindow(hwnd, 0):
                raise OSError(f"RegisterTouchWindow failed: {ctypes.get_last_error()}")

            self._new_wndproc = _WNDPROC(self._wndproc)
            self._old_wndproc: int = _SetWindowLongPtrW(
                hwnd,
                GWLP_WNDPROC,
                ctypes.cast(self._new_wndproc, ctypes.c_void_p).value,
            )
            if self._old_wndproc == 0:
                raise OSError(f"SetWindowLongPtrW failed: {ctypes.get_last_error()}")

            logger.debug("FingerRouter installed on HWND %s", hex(hwnd))

        def uninstall(self) -> None:
            _SetWindowLongPtrW(self._hwnd, GWLP_WNDPROC, self._old_wndproc)
            logger.debug("FingerRouter uninstalled from HWND %s", hex(self._hwnd))

        def _wndproc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
            if msg == WM_TOUCH:
                self._handle_wm_touch(hwnd, wparam, lparam)
                return 0
            return _CallWindowProcW(self._old_wndproc, hwnd, msg, wparam, lparam)

        def _handle_wm_touch(self, hwnd: int, wparam: int, lparam: int) -> None:
            count = wparam & 0xFFFF
            inputs = (_TOUCHINPUT * count)()
            htouchinput = wt.HANDLE(lparam)

            if not _GetTouchInputInfo(
                htouchinput,
                count,
                inputs,
                ctypes.sizeof(_TOUCHINPUT),
            ):
                logger.warning("GetTouchInputInfo failed: %s", ctypes.get_last_error())
                return

            for i in range(count):
                ti = inputs[i]
                flags = ti.dwFlags
                tid = ti.dwID

                pt = wt.POINT(ti.x // 100, ti.y // 100)
                _ScreenToClient(hwnd, ctypes.byref(pt))
                cx, cy = float(pt.x), float(pt.y)

                if flags & TOUCHEVENTF_DOWN:
                    self._points[tid] = _TouchPoint(tid, cx, cy)
                    self._reset_two_finger_state()

                elif flags & TOUCHEVENTF_UP:
                    self._points.pop(tid, None)
                    self._reset_two_finger_state()

                elif flags & TOUCHEVENTF_MOVE:
                    if tid in self._points:
                        self._points[tid].x = cx
                        self._points[tid].y = cy

            if len(self._points) == 2:
                self._emit_gestures()

            _CloseTouchInputHandle(htouchinput)

    FingerRouter = _WindowsFingerRouter

elif sys.platform == "darwin":

    class _MacFingerRouter(_FingerRouterBase):
        def __init__(self, window, **kwargs) -> None:
            super().__init__(window, **kwargs)
            raise NotImplementedError("FingerRouter is not yet implemented on macOS")

    FingerRouter = _MacFingerRouter

else:

    class _LinuxFingerRouter(_FingerRouterBase):
        def __init__(self, window, **kwargs) -> None:
            super().__init__(window, **kwargs)
            raise NotImplementedError("FingerRouter is not yet implemented on linux")

    FingerRouter = _LinuxFingerRouter


@dataclass(slots=True)
class ScrollEvent:
    xoff: float
    yoff: float
    screen_x: float
    screen_y: float


@dataclass(slots=True)
class MouseButtonEvent:
    button: int
    action: int
    mods: int
    screen_x: float
    screen_y: float


@dataclass(slots=True)
class CursorMoveEvent:
    xpos: float
    ypos: float


@dataclass(slots=True)
class KeyEvent:
    key: int
    scancode: int
    action: int
    mods: int


@dataclass(slots=True)
class ResizeEvent:
    width: int
    height: int


Event = Union[ScrollEvent, MouseButtonEvent, CursorMoveEvent, KeyEvent, ResizeEvent, FingerDragEvent, FingerPinchEvent, FingerRotateEvent]


class EventRouter:
    def __init__(self, window) -> None:
        self._queue: queue.SimpleQueue[Event] = queue.SimpleQueue()
        self._window = window
        self._finger = FingerRouter(window)

        self._prev_resize = glfw.set_framebuffer_size_callback(window, self._on_resize)
        self._prev_scroll = glfw.set_scroll_callback(window, self._on_scroll)
        self._prev_mouse_btn = glfw.set_mouse_button_callback(window, self._on_mouse_btn)
        self._prev_cursor = glfw.set_cursor_pos_callback(window, self._on_cursor)
        self._prev_key = glfw.set_key_callback(window, self._on_key)

    def poll(self) -> list[Event]:
        events: list[Event] = []
        events.extend(self._finger.poll())
        while not self._queue.empty():
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    def _on_resize(self, win, w, h):
        if self._prev_resize:
            self._prev_resize(win, w, h)
        self._queue.put(ResizeEvent(w, h))

    def _on_scroll(self, win, xoff, yoff):
        if self._prev_scroll:
            self._prev_scroll(win, xoff, yoff)
        sx, sy = glfw.get_cursor_pos(win)
        self._queue.put(ScrollEvent(xoff, yoff, sx, sy))

    def _on_mouse_btn(self, win, button, action, mods):
        if self._prev_mouse_btn:
            self._prev_mouse_btn(win, button, action, mods)
        sx, sy = glfw.get_cursor_pos(win)
        self._queue.put(MouseButtonEvent(button, action, mods, sx, sy))

    def _on_cursor(self, win, xpos, ypos):
        if self._prev_cursor:
            self._prev_cursor(win, xpos, ypos)
        self._queue.put(CursorMoveEvent(xpos, ypos))

    def _on_key(self, win, key, scancode, action, mods):
        if self._prev_key:
            self._prev_key(win, key, scancode, action, mods)
        self._queue.put(KeyEvent(key, scancode, action, mods))
