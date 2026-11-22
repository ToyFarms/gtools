"""Overlay mode: dock the gui window onto the Growtopia window.

The gui window becomes *owned by* the game window (``GWLP_HWNDPARENT``), sits
inside its client area, follows it around, and snaps to anchors when dragged.
It stays a normal window: natively resizable, focused like any window -- click
the gui and inputs go there, click the game and the game is focused.

The game's HWND is found by pid (from the hook runtime) or by window title;
the gui's own HWND is found by its unique window title (the bundled glfw
bindings do not expose native handles).
"""

from __future__ import annotations

import ctypes
import logging
import threading
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

# docked look: translucent, dimmer while the game has the focus
FOCUSED_ALPHA = 235
UNFOCUSED_ALPHA = 170

ERROR_WINDOW_UNIQUE = 1400

# dock style A/B modes (F11 cycles) -- diagnostics for the displaced-content
# bug: the raw style swap and WS_EX_LAYERED on an OpenGL window are the two
# suspects for the presented pixels landing offset from the client rect.
DOCK_STYLE_MODES = (
    "native popup + layered",  # 0: current behaviour
    "native popup",            # 1: no WS_EX_LAYERED
    "glfw borderless",         # 2: glfw.set_window_attrib(DECORATED, False)
    "glfw borderless + layered",
)


user32 = None
kernel32 = None


def _user32():
    global user32, kernel32
    if user32 is None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    return user32


# ---------------------------------------------------------------------------
# pure geometry: the snap anchors (pytest-covered)


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


def docked_rect(area: Rect, window: Rect, margin: int = 8) -> Rect:
    """The docked placement: pinned to the top-left of the game's client
    area, clamped so the window fits inside it."""
    return Rect(
        area.x + margin,
        area.y + margin,
        min(window.w, area.w - margin * 2),
        min(window.h, area.h - margin * 2),
    )


# ---------------------------------------------------------------------------
# win32 helpers


def find_window_by_title(title: str) -> int:
    u32 = _user32()
    u32.FindWindowW.restype = wintypes.HWND
    u32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    handle = u32.FindWindowW(None, title)
    return handle or 0


def find_game_window(pid: int, title: str = "Growtopia") -> int:
    """The game's main window: by pid first (from the hook runtime), then by
    a case-insensitive substring of the window title."""
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
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    rect = RECT()
    if not u32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return None
    return Rect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)


def client_rect(hwnd: int) -> Rect | None:
    u32 = _user32()

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

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
    # HWND_TOP (0): above the owned game window, never topmost
    u32.SetWindowPos(
        wintypes.HWND(hwnd), wintypes.HWND(0),
        rect.x, rect.y, rect.w, rect.h,
        0 if activate else SWP_NOACTIVATE,
    )


def set_above(hwnd: int, owner: int) -> None:
    """Keep the gui window directly above its owner in the z order."""
    u32 = _user32()
    u32.SetWindowPos(wintypes.HWND(hwnd), wintypes.HWND(owner), 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)


# ---------------------------------------------------------------------------
# the controller


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
    """Docks the gui window onto the game window and follows it per frame."""

    def __init__(self, gui_title: str, game_title: str = "Growtopia") -> None:
        self.gui_title = gui_title
        self.game_title = game_title
        self.state = OverlayState()
        self._glfw_window = None
        self._last_game_rect: Rect | None = None
        self.dock_style_mode = 0
        self._used_glfw_decorated = False
        self._layered = False

    def set_dock_style_mode(self, mode: int) -> None:
        """Cycle the dock style A/B mode; re-docks when already docked."""
        self.dock_style_mode = mode % len(DOCK_STYLE_MODES)
        self._last_pid = getattr(self, "_last_pid", 0)
        if self.state.docked:
            self.undock()
            self.dock(self._last_pid or None)

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
        self._last_pid = game_pid or 0

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

        # own the window: above the game, minimized with it, no taskbar entry
        set_owner(gui, game)
        self._apply_dock_style(gui)

        rect = docked_rect(game_area, gui_rect)
        u32.SetWindowPos(wintypes.HWND(gui), wintypes.HWND(game), rect.x, rect.y, rect.w, rect.h, SWP_FRAMECHANGED)
        self._refresh_gl_surface()
        self.state.docked = True
        self.state.hidden = False
        self._last_game_rect = game_area
        logger.info("docked to the growtopia window (top-left)")
        return True

    def _apply_dock_style(self, gui: int) -> None:
        """Borderless + translucency, per the A/B dock style mode."""
        u32 = _user32()
        mode = self.dock_style_mode
        if mode in (2, 3) and self._glfw_window is not None:
            # let glfw own the style change so its wndproc and the present
            # path stay consistent with the geometry it reports
            glfw.set_window_attrib(self._glfw_window, glfw.DECORATED, False)
            self._used_glfw_decorated = True
        else:
            # borderless: the frame is gone, the toolbar's Undock button restores
            u32.SetWindowLongW(wintypes.HWND(gui), GWL_STYLE, WS_POPUP | WS_VISIBLE)
            # frame recalc as its own transition: applying the style and the
            # new geometry in one SetWindowPos leaves DWM presenting a stale
            # surface (displaced/blurry content) until the next frame change
            u32.SetWindowPos(wintypes.HWND(gui), None, 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
            self._used_glfw_decorated = False

        self._layered = mode in (0, 3)
        if self._layered:
            exstyle = u32.GetWindowLongW(wintypes.HWND(gui), GWL_EXSTYLE) | WS_EX_LAYERED
            u32.SetWindowLongW(wintypes.HWND(gui), GWL_EXSTYLE, exstyle)
            u32.SetLayeredWindowAttributes(wintypes.HWND(gui), 0, FOCUSED_ALPHA, LWA_ALPHA)

    def _refresh_gl_surface(self) -> None:
        """Force the presentation to re-sync with the final geometry.

        Measured (F3 report, docked): after the style swap + native
        SetWindowPos the DWM/GL surface can stay stale -- content displaced
        by tens of px or stretched (blurry, smaller, top clipped) -- until
        another style/geometry transition happens. A 1px resize cycle sends
        a real WM_SIZE, which re-creates the swapchain against the final
        client rect; no manual re-toggle needed."""
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
            if self._used_glfw_decorated and self._glfw_window is not None:
                glfw.set_window_attrib(self._glfw_window, glfw.DECORATED, True)
                self._used_glfw_decorated = False
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
        """Hide via glfw; the caller supplies its window through
        ``set_glfw_window`` at startup."""
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
        """Per-frame: keep the docked window inside the game's client area,
        hold the z order above the game, and drive the focus translucency."""
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
                # docked = pinned to the game's top-left: re-derive the
                # placement for the new rect, whatever direction it moved
                target = docked_rect(game_area, gui_rect)
                if target != gui_rect:
                    move_window(gui, target)
            set_above(gui, game)

        # translucency: dimmer while the game has the focus
        if self._layered:
            focused = int(u32.GetForegroundWindow() or 0) == int(gui)
            target_alpha = FOCUSED_ALPHA if focused else UNFOCUSED_ALPHA
            if self.state.alpha != target_alpha:
                u32.SetLayeredWindowAttributes(wintypes.HWND(gui), 0, target_alpha, LWA_ALPHA)
                self.state.alpha = target_alpha


def _raise_no_window():
    raise RuntimeError("no glfw window is current")


class HotkeyThread:
    """Global hotkeys via RegisterHotKey: they fire even while the game has
    focus. WM_HOTKEY sets thread-safe flags the frame loop consumes."""

    HOTKEY_SHOW_HIDE = 1
    HOTKEY_DOCK_UNDOCK = 2

    def __init__(self, show_hide_vk: int, dock_vk: int, mods: int = 0) -> None:
        self.show_hide_vk = show_hide_vk
        self.dock_vk = dock_vk
        self.mods = mods
        self.show_hide_requested = threading.Event()
        self.dock_requested = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="overlay-hotkeys", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        u32 = _user32()
        u32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        u32.RegisterHotKey.restype = wintypes.BOOL
        u32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        u32.GetMessageW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ok1 = u32.RegisterHotKey(None, self.HOTKEY_SHOW_HIDE, self.mods, self.show_hide_vk)
        err1 = kernel32.GetLastError()
        ok2 = u32.RegisterHotKey(None, self.HOTKEY_DOCK_UNDOCK, self.mods, self.dock_vk)
        err2 = kernel32.GetLastError()
        if not (ok1 and ok2):
            logger.warning(
                "global hotkeys unavailable: show=%s (err=%ld) dock=%s (err=%ld)",
                ok1, err1, ok2, err2,
            )

        class MSG(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                        ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                        ("time", wintypes.DWORD), ("pt", wintypes.POINT)]

        msg = MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                if msg.wParam == self.HOTKEY_SHOW_HIDE:
                    self.show_hide_requested.set()
                elif msg.wParam == self.HOTKEY_DOCK_UNDOCK:
                    self.dock_requested.set()

        u32.UnregisterHotKey(None, self.HOTKEY_SHOW_HIDE)
        u32.UnregisterHotKey(None, self.HOTKEY_DOCK_UNDOCK)
