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
    
    def verify_wndproc(self) -> bool:
        """Verify that our window procedure is still installed. Returns True if still installed."""
        return True  # Base implementation - override in platform-specific classes

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

    _GetWindowLongPtrW = _user32.GetWindowLongPtrW
    _GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]

    _CallWindowProcW = _user32.CallWindowProcW
    _CallWindowProcW.restype = ctypes.c_ssize_t
    _CallWindowProcW.argtypes = [
        ctypes.c_ssize_t,
        wt.HWND,
        wt.UINT,
        wt.WPARAM,
        wt.LPARAM,
    ]

    # Message hook functions
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _GetCurrentThreadId = _kernel32.GetCurrentThreadId
    _GetCurrentThreadId.restype = wt.DWORD
    _GetCurrentThreadId.argtypes = []

    WH_GETMESSAGE = 3
    _SetWindowsHookExW = _user32.SetWindowsHookExW
    _SetWindowsHookExW.restype = wt.HHOOK
    _SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wt.HINSTANCE, wt.DWORD]

    _UnhookWindowsHookEx = _user32.UnhookWindowsHookEx
    _UnhookWindowsHookEx.restype = wt.BOOL
    _UnhookWindowsHookEx.argtypes = [wt.HHOOK]

    _CallNextHookEx = _user32.CallNextHookEx
    _CallNextHookEx.restype = ctypes.c_ssize_t
    _CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]

    class _MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wt.HWND),
            ("message", wt.UINT),
            ("wParam", wt.WPARAM),
            ("lParam", wt.LPARAM),
            ("time", wt.DWORD),
            ("pt", wt.POINT),
        ]

    _HOOKPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        ctypes.c_int,
        wt.WPARAM,
        wt.LPARAM,
    )

    _ScreenToClient = _user32.ScreenToClient
    _ScreenToClient.restype = wt.BOOL
    _ScreenToClient.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]

    class _WindowsFingerRouter(_FingerRouterBase):
        def __init__(self, window, **kwargs) -> None:
            super().__init__(window, **kwargs)

            hwnd = glfw.get_win32_window(window)
            self._hwnd: int = hwnd
            logger.debug(f"Initializing FingerRouter for HWND {hex(hwnd)}")

            if not _RegisterTouchWindow(hwnd, 0):
                error = ctypes.get_last_error()
                logger.error(f"RegisterTouchWindow failed: {error}")
                raise OSError(f"RegisterTouchWindow failed: {error}")

            logger.debug("RegisterTouchWindow succeeded")

            # Try message hook approach first (intercepts before GLFW processes)
            self._hook = None
            self._hook_proc = None
            try:
                thread_id = _GetCurrentThreadId()
                self._hook_proc = _HOOKPROC(self._getmessage_hook)
                self._hook = _SetWindowsHookExW(
                    WH_GETMESSAGE,
                    self._hook_proc,
                    None,  # hMod - not needed for thread hooks
                    thread_id,
                )
                if self._hook:
                    logger.debug(f"Message hook installed for thread {thread_id}")
                else:
                    error = ctypes.get_last_error()
                    logger.warning(f"SetWindowsHookExW failed: {error}, falling back to window procedure")
            except Exception as e:
                logger.warning(f"Failed to install message hook: {e}, falling back to window procedure")

            # Also install window procedure as backup
            self._new_wndproc = _WNDPROC(self._wndproc)
            # Keep a reference to prevent garbage collection
            self._wndproc_ref = self._new_wndproc
            
            old_wndproc_value = _SetWindowLongPtrW(
                hwnd,
                GWLP_WNDPROC,
                ctypes.cast(self._new_wndproc, ctypes.c_void_p).value,
            )
            if old_wndproc_value == 0:
                error = ctypes.get_last_error()
                logger.error(f"SetWindowLongPtrW failed: {error}")
                raise OSError(f"SetWindowLongPtrW failed: {error}")

            self._old_wndproc: int = old_wndproc_value
            logger.debug(f"FingerRouter installed on HWND {hex(hwnd)}, old_wndproc={hex(old_wndproc_value)}")
            
            # Verify the window procedure was set correctly
            current_wndproc = _GetWindowLongPtrW(hwnd, GWLP_WNDPROC)
            expected_wndproc = ctypes.cast(self._new_wndproc, ctypes.c_void_p).value
            if current_wndproc != expected_wndproc:
                logger.warning(f"Window procedure verification failed! Current={hex(current_wndproc)}, Expected={hex(expected_wndproc)}")
            else:
                logger.debug(f"Window procedure verified: {hex(current_wndproc)}")
            
            # Test: verify window procedure is being called by checking periodically
            self._wndproc_call_count = 0

        def _getmessage_hook(self, nCode: int, wParam: int, lParam: int) -> int:
            """Message hook to intercept WM_TOUCH before GLFW processes it.
            
            For WH_GETMESSAGE hook:
            - nCode: HC_ACTION (0) means process the message
            - wParam: PM_REMOVE (1) or PM_NOREMOVE (0) 
            - lParam: Pointer to MSG structure
            """
            # HC_ACTION = 0 means we should process the message
            if nCode == 0 and lParam:
                try:
                    msg = ctypes.cast(lParam, ctypes.POINTER(_MSG)).contents
                    if msg.hwnd == self._hwnd and msg.message == WM_TOUCH:
                        logger.debug(f"WM_TOUCH intercepted via message hook: hwnd={hex(msg.hwnd)}, wparam={msg.wParam}, lparam={msg.lParam}")
                        print(f"WM_TOUCH intercepted via message hook: hwnd={hex(msg.hwnd)}, wparam={msg.wParam}, lparam={msg.lParam}")
                        # Process the touch message directly
                        self._handle_wm_touch(msg.hwnd, msg.wParam, msg.lParam)
                except Exception as e:
                    logger.warning(f"Error in message hook: {e}")
            # Always call next hook
            return _CallNextHookEx(self._hook, nCode, wParam, lParam)

        def verify_wndproc(self) -> bool:
            """Verify that our window procedure is still installed."""
            if not hasattr(self, '_new_wndproc'):
                return False
            current_wndproc = _GetWindowLongPtrW(self._hwnd, GWLP_WNDPROC)
            expected_wndproc = ctypes.cast(self._new_wndproc, ctypes.c_void_p).value
            if current_wndproc != expected_wndproc:
                logger.warning(f"Window procedure was overwritten! Current={hex(current_wndproc)}, Expected={hex(expected_wndproc)}")
                return False
            return True
        
        def uninstall(self) -> None:
            if self._hook:
                _UnhookWindowsHookEx(self._hook)
                self._hook = None
                logger.debug("Message hook uninstalled")
            _SetWindowLongPtrW(self._hwnd, GWLP_WNDPROC, self._old_wndproc)
            logger.debug("FingerRouter uninstalled from HWND %s", hex(self._hwnd))

        def _wndproc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
            # Track that window procedure is being called
            self._wndproc_call_count += 1
            if self._wndproc_call_count == 1:
                logger.debug(f"Window procedure called for the first time! msg={hex(msg)}")
                print(f"Window procedure called for the first time! msg={hex(msg)}")
            
            # Debug: log WM_TOUCH messages (0x0240)
            if msg == WM_TOUCH:
                logger.debug(f"WM_TOUCH received in _wndproc: hwnd={hex(hwnd)}, wparam={wparam}, lparam={lparam}")
                print(f"WM_TOUCH received in _wndproc: hwnd={hex(hwnd)}, wparam={wparam}, lparam={lparam}")
                self._handle_wm_touch(hwnd, wparam, lparam)
                return 0
            # Forward all other messages to the original window procedure
            # Note: We return the result from CallWindowProcW, which is what the original wndproc would return
            result = _CallWindowProcW(self._old_wndproc, hwnd, msg, wparam, lparam)
            return result

        def _handle_wm_touch(self, hwnd: int, wparam: int, lparam: int) -> None:
            logger.debug("_handle_wm_touch called")
            print("_handle_wm_touch called")  # User's debug print
            count = wparam & 0xFFFF
            logger.debug(f"Touch count: {count}")
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
