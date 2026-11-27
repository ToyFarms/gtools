import ctypes
import logging
from ctypes import wintypes
from dataclasses import dataclass

import glfw

logger = logging.getLogger("gui-overlay")

GWL_STYLE = -16
GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020

WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_LAYERED = 0x00080000
LWA_ALPHA = 0x00000002

FOCUSED_ALPHA = 235
UNFOCUSED_ALPHA = 170

ERROR_WINDOW_UNIQUE = 1400


user32 = None
kernel32 = None


def _user32():
    global user32, kernel32
    if user32 is None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return user32


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


def docked_rect(area: Rect, window: Rect, margin: int = 8) -> Rect:
    return Rect(
        area.x + margin,
        area.y + margin,
        min(window.w, area.w - margin * 2),
        min(window.h, area.h - margin * 2),
    )


def find_window_by_title(title: str) -> int:
    u32 = _user32()
    u32.FindWindowW.restype = wintypes.HWND
    u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    handle = u32.FindWindowW(None, title)
    return handle or 0


def find_game_window(pid: int, title: str = "Growtopia") -> int:
    u32 = _user32()
    result = []
    needle = title.lower()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def on_window(hwnd, _lparam):
        owner = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if not u32.IsWindowVisible(hwnd):
            return True
        buffer = ctypes.create_unicode_buffer(256)
        u32.GetWindowTextW(hwnd, buffer, 256)
        window_title = buffer.value.lower()
        if pid:
            if owner.value == pid and window_title:
                result.append(hwnd)
                return False
        elif needle in window_title:
            result.append(hwnd)
            return False
        return True

    u32.EnumWindows(on_window, 0)
    return result[0] if result else 0


def find_gui_window(title: str) -> int:
    u32 = _user32()
    current = wintypes.DWORD(kernel32.GetCurrentProcessId() if (kernel32 := ctypes.WinDLL("kernel32")) else 0)
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def on_window(hwnd, _lparam):
        owner = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == current.value:
            buffer = ctypes.create_unicode_buffer(256)
            u32.GetWindowTextW(hwnd, buffer, 256)
            if buffer.value == title:
                found.append(hwnd)
                return False
        return True

    u32.EnumWindows(on_window, 0)
    return found[0] if found else 0


def window_rect(hwnd: int) -> Rect | None:
    u32 = _user32()

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    rect = RECT()
    if not u32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return None
    return Rect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def client_rect(hwnd: int) -> Rect | None:
    u32 = _user32()

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    rect = RECT()
    if not u32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return None

    point = wintypes.POINT(0, 0)
    u32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(point))
    return Rect(point.x, point.y, rect.right, rect.bottom)


def set_owner(hwnd: int, owner: int) -> None:
    u32 = _user32()
    u32.SetWindowLongPtrW(wintypes.HWND(hwnd), GWLP_HWNDPARENT, wintypes.HWND(owner))


def move_window(hwnd: int, rect: Rect, activate: bool = False) -> None:
    u32 = _user32()
    u32.SetWindowPos(
        wintypes.HWND(hwnd),
        wintypes.HWND(0),
        rect.x,
        rect.y,
        rect.w,
        rect.h,
        0 if activate else SWP_NOACTIVATE,
    )


def set_above(hwnd: int, owner: int) -> None:
    u32 = _user32()
    u32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(owner), 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


@dataclass
class OverlayState:
    docked: bool = False
    hidden: bool = False
    game_hwnd: int = 0
    gui_hwnd: int = 0
    alpha: int = FOCUSED_ALPHA
    saved_placement: tuple[int, int, int, int] | None = None
    saved_style: int | None = None
    saved_exstyle: int | None = None


class OverlayController:
    def __init__(self, gui_title: str, game_title: str = "Growtopia") -> None:
        self.gui_title = gui_title
        self.game_title = game_title
        self.state = OverlayState()
        self._glfw_window = None
        self._last_game_rect: Rect | None = None

    @property
    def docked(self) -> bool:
        return self.state.docked

    def gui_hwnd(self) -> int:
        if not self.state.gui_hwnd:
            self.state.gui_hwnd = find_gui_window(self.gui_title)
        return self.state.gui_hwnd

    def game_hwnd(self) -> int:
        return self.state.game_hwnd

    def find_game(self, pid: int | None = None) -> int:
        self.state.game_hwnd = find_game_window(pid or 0, self.game_title)
        return self.state.game_hwnd

    def dock(self, game_pid: int | None = None) -> bool:
        u32 = _user32()
        gui = self.gui_hwnd()
        if not gui:
            logger.warning("cannot find the gui window")
            return False

        game = self.find_game(game_pid)
        if not game:
            logger.warning("cannot find the growtopia window")
            return False

        game_area = client_rect(game)
        if game_area is None or game_area.w < 100 or game_area.h < 100:
            logger.warning("the growtopia window is too small to dock onto")
            return False

        gui_rect = window_rect(gui)
        if gui_rect is None:
            return False

        self.state.saved_placement = (gui_rect.x, gui_rect.y, gui_rect.w, gui_rect.h)
        self.state.saved_style = u32.GetWindowLongW(wintypes.HWND(gui), GWL_STYLE)
        self.state.saved_exstyle = u32.GetWindowLongW(wintypes.HWND(gui), GWL_EXSTYLE)

        set_owner(gui, game)

        u32.SetWindowLongW(wintypes.HWND(gui), GWL_STYLE, WS_POPUP | WS_VISIBLE)
        u32.SetWindowPos(wintypes.HWND(gui), None, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)

        exstyle = u32.GetWindowLongW(wintypes.HWND(gui), GWL_EXSTYLE) | WS_EX_LAYERED
        u32.SetWindowLongW(wintypes.HWND(gui), GWL_EXSTYLE, exstyle)
        u32.SetLayeredWindowAttributes(wintypes.HWND(gui), 0, FOCUSED_ALPHA, LWA_ALPHA)

        rect = docked_rect(game_area, gui_rect)
        u32.SetWindowPos(wintypes.HWND(gui), wintypes.HWND(game), rect.x, rect.y, rect.w, rect.h, SWP_FRAMECHANGED)
        self._refresh_gl_surface()
        self.state.docked = True
        self.state.hidden = False
        self._last_game_rect = game_area
        logger.info("docked to the growtopia window (top-left)")

        return True

    def _refresh_gl_surface(self) -> None:
        if self._glfw_window is None:
            return

        hwnd = self.state.gui_hwnd
        if not hwnd:
            return

        try:
            w, h = glfw.get_window_size(self._glfw_window)
        except Exception:
            return

        u32 = _user32()
        flags = SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE
        u32.SetWindowPos(wintypes.HWND(hwnd), None, 0, 0, w + 1, h, flags)
        u32.SetWindowPos(wintypes.HWND(hwnd), None, 0, 0, w, h, flags)

    def undock(self) -> None:
        if not self.state.docked:
            return
        u32 = _user32()
        gui = self.gui_hwnd()
        if gui:
            if self.state.saved_style is not None:
                u32.SetWindowLongW(wintypes.HWND(gui), GWL_STYLE, self.state.saved_style)
            exstyle = u32.GetWindowLongW(wintypes.HWND(gui), GWL_EXSTYLE) & ~WS_EX_LAYERED
            u32.SetWindowLongW(wintypes.HWND(gui), GWL_EXSTYLE, exstyle)
            u32.SetLayeredWindowAttributes(wintypes.HWND(gui), 0, 255, LWA_ALPHA)
            if self.state.saved_placement:
                x, y, w, h = self.state.saved_placement
                set_owner(gui, 0)
                move_window(gui, Rect(x, y, w, h), activate=True)
            else:
                set_owner(gui, 0)
            self._refresh_gl_surface()
        self.state.docked = False
        self._last_game_rect = None
        logger.info("undocked from the growtopia window")

    def hide(self) -> None:
        if self._glfw_window is not None:
            glfw.hide_window(self._glfw_window)

        self.state.hidden = True

    def show(self) -> None:
        if self._glfw_window is not None:
            glfw.show_window(self._glfw_window)
        self.state.hidden = False

    def toggle_hidden(self) -> None:
        if self.state.hidden:
            self.show()
        else:
            self.hide()

    def set_glfw_window(self, window) -> None:
        self._glfw_window = window

    def follow(self, game_pid: int | None = None) -> None:
        if not self.state.docked:
            return

        u32 = _user32()
        gui = self.gui_hwnd()
        if not gui:
            return

        game = self.state.game_hwnd or self.find_game(game_pid)
        if not game or not _user32().IsWindow(wintypes.HWND(game)):
            self.undock()
            return

        game_area = client_rect(game)
        if game_area is None:
            return

        if self._last_game_rect != game_area:
            self._last_game_rect = game_area
            gui_rect = window_rect(gui)
            if gui_rect is not None:
                target = docked_rect(game_area, gui_rect)
                if target != gui_rect:
                    move_window(gui, target)

            set_above(gui, game)

        focused = int(u32.GetForegroundWindow() or 0) == int(gui)
        target_alpha = FOCUSED_ALPHA if focused else UNFOCUSED_ALPHA
        if self.state.alpha != target_alpha:
            u32.SetLayeredWindowAttributes(wintypes.HWND(gui), 0, target_alpha, LWA_ALPHA)
            self.state.alpha = target_alpha
