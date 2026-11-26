"""PieMenu: overlay window, state machine, and the glue between all modules."""
from __future__ import annotations

import ctypes
import enum
import math
import time
import traceback
from contextlib import contextmanager
from typing import Any, Callable, List, Optional

import glfw
from imgui_bundle import imgui

try:
    from OpenGL import GL as gl
except ImportError as e:  # pragma: no cover
    raise ImportError("piemenu needs PyOpenGL:  pip install PyOpenGL") from e

from . import win32
from .intent import IntentConfig, IntentState, IntentTracker, Spring, ang_diff, clamp
from .items import Activation, MenuBuilder, Panel, PieItem, SubMenu, TextInput
from .render import (BACK, Painter, Theme, draw_backdrop, draw_ghost, draw_level, mix, u32)
from .triggers import Hold

TAU = math.tau
V2 = imgui.ImVec2


def _v(x) -> int:
    """imgui_bundle enum member -> int (safe for flag arithmetic)."""
    return int(getattr(x, "value", x))


def _c4(c, a: float = 1.0):
    return imgui.ImVec4(c[0] / 255, c[1] / 255, c[2] / 255, clamp(c[3] / 255 * a))


class State(enum.Enum):
    IDLE = 0      # nothing happening (overlay hidden unless panels are open)
    PENDING = 1   # trigger is down, waiting out `delay`
    ACTIVE = 2    # pie visible
    INPUT = 3     # a TextInput took over
    CLOSING = 4   # fade-out animation


class _Level:
    def __init__(self, node, origin, slots, angles, sector, radius, cfg):
        self.node, self.origin = node, origin
        self.slots, self.angles, self.sector, self.radius = slots, angles, sector, radius
        self.open = Spring(0.0, f=6.5, z=0.62)
        self.ghost = Spring(0.0, f=7.0, z=1.0)
        self.scales = [Spring(1.0, f=10.0, z=0.7) for _ in slots]
        self.hot = [Spring(0.0, f=12.0, z=1.0) for _ in slots]
        self.tracker = IntentTracker(cfg)
        self.entered: Optional[int] = None   # slot we descended through
        self.chosen: Optional[int] = None    # slot committed (flash while closing)


class PieMenu(MenuBuilder):
    """Pie-menu controller. Build the tree with .button/.submenu/.text_input/.panel,
    then call `menu.update()` once per frame from your main loop.

    processes=None            global trigger (works over any app)
    processes=["a.exe", ...]  only while one of these is the foreground process
    """

    def __init__(self, *, trigger=None, processes=None, include_self: bool = True,
                 focus_predicate: Optional[Callable[[int, str], bool]] = None,
                 main_window=None, scale: float = 1.0, theme: Optional[Theme] = None,
                 intent: Optional[IntentConfig] = None,
                 font_path: Optional[str] = r"C:\Windows\Fonts\segoeui.ttf",
                 glsl_version: str = "#version 330"):
        self._init_builder()
        self.trigger = trigger or Hold("ctrl")
        self.focus = win32.FocusFilter(processes, include_self=include_self,
                                       predicate=focus_predicate)
        self.theme = theme or Theme()
        self.intent = intent or IntentConfig()
        self.user_scale = scale
        self.enabled = True
        self.on_open: Optional[Callable[[], Any]] = None
        self.on_close: Optional[Callable[[bool], Any]] = None  # arg: cancelled?

        self._painter = Painter(self.theme)
        self._state = State.IDLE
        self._levels: List[_Level] = []
        self._panels: List[Panel] = []
        self._fade = Spring(0.0, f=8.0, z=1.0)
        self._st: Optional[IntentState] = None
        self._latched = False
        self._blocked = False
        self._press_pos = (0, 0)
        self._press_t = 0.0
        self._close_t = 0.0
        self._t_last = 0.0
        self._cursor = (0, 0)
        self._btn = self._prev_btn = (False, False, False)
        self._esc_edge = False
        self._prev_esc = False
        self._capture = False
        self._passthrough: Optional[bool] = None
        self._visible = False
        self._has_focus = False
        self._prev_fg = 0
        self._ox = self._oy = 0
        self._work = (0, 0, 1920, 1080)
        self._mon_key = None
        self._ui_scale = 1.0
        self._last_origin = (0, 0)
        self._last_radius = 120.0
        self._hover_key = None
        self._input_item: Optional[TextInput] = None
        self._input_origin = (0, 0)
        self._input_focus = False
        self._create_overlay(main_window, font_path, glsl_version)

    # ================================================================ setup ==
    def _create_overlay(self, main_window, font_path, glsl_version) -> None:
        main = main_window or glfw.get_current_context()
        if not main:
            raise RuntimeError("PieMenu needs your main GLFW window: pass main_window=... "
                               "or make its context current before constructing.")
        hints = [(glfw.VISIBLE, False, True), (glfw.DECORATED, False, True),
                 (glfw.FLOATING, True, False), (glfw.TRANSPARENT_FRAMEBUFFER, True, False),
                 (glfw.FOCUS_ON_SHOW, False, True), (glfw.RESIZABLE, False, True),
                 (glfw.AUTO_ICONIFY, False, True)]
        for h, v, _ in hints:
            glfw.window_hint(h, v)
        try:
            win = glfw.create_window(640, 480, "PieMenu overlay", None, main)
        finally:  # leave the app's hint state the way we found it
            for h, _, d in hints:
                glfw.window_hint(h, d)
        if not win:
            raise RuntimeError("Could not create the overlay window")
        self._win = win
        self._hwnd = int(glfw.get_win32_window(win))
        win32.modify_exstyle(self._hwnd, add=win32.WS_EX_NOACTIVATE | win32.WS_EX_TOOLWINDOW)
        glfw.set_key_callback(win, self._on_key)
        glfw.set_char_callback(win, self._on_char)
        glfw.set_scroll_callback(win, self._on_scroll)
        self._key_map = self._build_key_map()

        prev_win, prev_ctx = glfw.get_current_context(), imgui.get_current_context()
        glfw.make_context_current(win)
        glfw.swap_interval(0)  # the app's loop paces us; don't stall it on a 2nd vsync
        self._ctx = imgui.create_context()
        imgui.set_current_context(self._ctx)
        io = self._io = imgui.get_io()
        io.set_ini_filename("")
        io.set_log_filename("")
        imgui.style_colors_dark()
        ps = glfw.get_monitor_content_scale(glfw.get_primary_monitor())[0] * self.user_scale
        try:
            if not font_path:
                raise FileNotFoundError
            io.fonts.add_font_from_file_ttf(font_path, self.theme.font_size * ps)
        except Exception:
            io.fonts.add_font_default()
        st = imgui.get_style()
        st.scale_all_sizes(ps)
        st.window_rounding = self.theme.rounding * ps
        st.frame_rounding = 8.0 * ps
        imgui.backends.glfw_init_for_opengl(ctypes.cast(win, ctypes.c_void_p).value, False)
        imgui.backends.opengl3_init(glsl_version)
        glfw.make_context_current(prev_win)
        if prev_ctx is not None:
            imgui.set_current_context(prev_ctx)

    @staticmethod
    def _build_key_map():
        names = {"KEY_ENTER": "enter", "KEY_KP_ENTER": "keypad_enter", "KEY_ESCAPE": "escape",
                 "KEY_BACKSPACE": "backspace", "KEY_DELETE": "delete", "KEY_INSERT": "insert",
                 "KEY_LEFT": "left_arrow", "KEY_RIGHT": "right_arrow", "KEY_UP": "up_arrow",
                 "KEY_DOWN": "down_arrow", "KEY_HOME": "home", "KEY_END": "end",
                 "KEY_PAGE_UP": "page_up", "KEY_PAGE_DOWN": "page_down", "KEY_TAB": "tab",
                 "KEY_A": "a", "KEY_C": "c", "KEY_V": "v", "KEY_X": "x", "KEY_Y": "y",
                 "KEY_Z": "z", "KEY_LEFT_CONTROL": "left_ctrl", "KEY_RIGHT_CONTROL": "right_ctrl",
                 "KEY_LEFT_SHIFT": "left_shift", "KEY_RIGHT_SHIFT": "right_shift",
                 "KEY_LEFT_ALT": "left_alt", "KEY_RIGHT_ALT": "right_alt"}
        out = {}
        for gname, iname in names.items():
            g, i = getattr(glfw, gname, None), getattr(imgui.Key, iname, None)
            if g is not None and i is not None:
                out[g] = i
        return out

    # GLFW delivers these during the app's poll_events(); route them to *our* context.
    @contextmanager
    def _imgui_ctx(self):
        prev = imgui.get_current_context()
        imgui.set_current_context(self._ctx)
        try:
            yield
        finally:
            if prev is not None:
                imgui.set_current_context(prev)

    def _on_key(self, win, key, scancode, action, mods):
        k = self._key_map.get(key)
        if k is not None:
            with self._imgui_ctx():
                self._io.add_key_event(k, action != glfw.RELEASE)

    def _on_char(self, win, cp):
        with self._imgui_ctx():
            self._io.add_input_character(cp)

    def _on_scroll(self, win, dx, dy):
        with self._imgui_ctx():
            self._io.add_mouse_wheel_event(dx, dy)

    @contextmanager
    def _overlay(self):
        """Make the overlay's GL + ImGui contexts current, then restore the app's."""
        prev_win, prev_ctx = glfw.get_current_context(), imgui.get_current_context()
        glfw.make_context_current(self._win)
        imgui.set_current_context(self._ctx)
        try:
            yield
        finally:
            glfw.make_context_current(prev_win)
            if prev_ctx is not None:
                imgui.set_current_context(prev_ctx)

    def destroy(self) -> None:
        with self._overlay():
            imgui.backends.opengl3_shutdown()
            imgui.backends.glfw_shutdown()
            imgui.destroy_context(self._ctx)
        glfw.destroy_window(self._win)

    # ============================================================ public API ==
    @property
    def processes(self):
        return self.focus.processes

    @processes.setter
    def processes(self, names) -> None:
        self.focus.set_processes(names)

    @property
    def active(self) -> bool:
        """True while a pie, text field or panel is on screen."""
        return self._state in (State.ACTIVE, State.INPUT, State.CLOSING) or bool(self._panels)

    @property
    def busy(self) -> bool:
        """True when the menu wants per-frame updates (don't block in wait_events)."""
        return self._state is not State.IDLE or bool(self._panels)

    def open(self, at=None) -> None:
        """Open programmatically (latched: click to choose, Esc to cancel)."""
        if self._state is State.IDLE:
            self._open(at or win32.cursor_pos(), latched=True)

    def close(self) -> None:
        if self._state in (State.ACTIVE, State.INPUT):
            self._cancel()

    def show_panel(self, panel: Panel) -> Panel:
        panel.open, panel._placed, panel._fade = True, False, Spring(0.0, f=9.0, z=1.0)
        if self._state in (State.IDLE, State.PENDING):
            self._last_origin, self._last_radius = win32.cursor_pos(), 0.0
        self._panels.append(panel)
        return panel

    def close_panel(self, panel: Panel) -> None:
        panel.close()

    def update(self) -> None:
        """Call once per frame, anywhere in your loop (after swap_buffers is fine).

        Leaves your current GLFW/GL/ImGui contexts exactly as it found them.
        """
        if not self.enabled and self._state is State.IDLE and not self._panels:
            return
        now = time.perf_counter()
        dt = min(now - self._t_last, 0.05) if self._t_last else 1 / 60
        self._t_last = now
        try:
            self._cursor = win32.cursor_pos()
            if self.enabled:
                self._poll_trigger(now)
            need = self._state in (State.ACTIVE, State.INPUT, State.CLOSING) or bool(self._panels)
            if need:
                if not self._visible:
                    if self._mon_key is None or self._state is State.IDLE:
                        self._place_overlay(*self._cursor)
                    self._show_overlay()
                self._frame(dt)
            elif self._visible:
                self._hide_overlay()
        except Exception:
            self._emergency_reset()
            raise

    # ========================================================== state logic ==
    def _poll_trigger(self, now: float) -> None:
        down = self.trigger.is_down()
        st = self._state
        if st is State.IDLE:
            if not down:
                self._blocked = False
            elif not self._blocked:
                if not self.focus.allows():
                    self._blocked = True
                else:
                    self._press_pos, self._press_t = self._cursor, now
                    self._state = State.PENDING
        elif st is State.PENDING:
            if not down:
                self._state = State.IDLE
            elif self.trigger.interference():
                self._state, self._blocked = State.IDLE, True
            elif now - self._press_t >= self.trigger.delay:
                self._state = State.IDLE
                if not self._open(self._press_pos):
                    self._blocked = True

    def _emergency_reset(self) -> None:
        self._state, self._levels, self._input_item = State.IDLE, [], None
        try:
            self._set_passthrough(True)
            self._hide_overlay()
        except Exception:
            pass

    def _call(self, fn, *args) -> Any:
        """Run user code; a buggy callback must never wedge a fullscreen overlay."""
        if fn is None:
            return None
        try:
            return fn(*args)
        except Exception:
            traceback.print_exc()
            return None

    # ---- level construction -------------------------------------------------
    def _recenter(self, desired, R: float, cursor):
        """Clamp the pie inside the monitor's work area; warp the cursor by the same shift."""
        th, sc = self.theme, self._ui_scale
        x, y, w, h = self._work
        m = R + th.item_radius * sc * (1 + th.max_grow) + 8 * sc
        cx = clamp(desired[0], x + m, x + w - m) if x + m < x + w - m else x + w / 2
        cy = clamp(desired[1], y + m, y + h - m) if y + m < y + h - m else y + h / 2
        cx, cy = round(cx), round(cy)  # keep origin and (integer) cursor exactly aligned
        dx, dy = cx - desired[0], cy - desired[1]
        if abs(dx) >= 1 or abs(dy) >= 1:
            cursor = (cursor[0] + int(round(dx)), cursor[1] + int(round(dy)))
            win32.set_cursor_pos(*cursor)
        self._cursor = cursor
        return (cx, cy)

    def _make_level(self, node, desired, parent_origin=None) -> _Level:
        th, sc = self.theme, self._ui_scale
        items = [c for c in node.children if c.is_visible()]
        n = len(items)
        m = n if parent_origin is None else n + 1
        need = max(m, 1) * (2 * th.item_radius * 1.18 + 6) / TAU
        R = max(th.ring_radius, need) * sc
        origin = self._recenter(desired, R, self._cursor)
        if parent_origin is None:
            angles = [-math.pi / 2 + TAU * i / max(m, 1) for i in range(n)]
            slots: list = list(items)
        else:
            back = math.atan2(parent_origin[1] - origin[1], parent_origin[0] - origin[0])
            angles = [-math.pi / 2 + TAU * i / m for i in range(m)]
            back_slot = min(range(m), key=lambda i: ang_diff(angles[i], back))
            it = iter(items)
            slots = [BACK if i == back_slot else next(it) for i in range(m)]
        lv = _Level(node, origin, slots, angles, TAU / max(m, 2), R, self.intent)
        lv.tracker.reset(origin, self._cursor, grace=0.0 if parent_origin is None else 0.18)
        self._last_origin, self._last_radius = origin, R
        return lv

    def _open(self, pos, latched: bool = False) -> bool:
        if not any(c.is_visible() for c in self.children):
            return False
        self._place_overlay(*pos)
        self._cursor = win32.cursor_pos()
        lv = self._make_level(self, pos)
        self._levels, self._latched, self._st = [lv], latched, None
        self._state = State.ACTIVE
        self._fade.snap(0.0)
        self._prev_btn, self._prev_esc = win32.mouse_buttons(), win32.key_down(win32.VK_ESCAPE)
        self._hover_key = None
        self._call(self.on_open)
        return True

    def _push(self, item: SubMenu) -> None:
        parent = self._levels[-1]
        parent.entered = parent.slots.index(item)
        parent.chosen = None
        nxt = self._make_level(item, self._cursor, parent_origin=parent.origin)
        self._levels.append(nxt)
        self._st = None

    def _pop(self) -> None:
        if len(self._levels) <= 1:
            return
        self._levels.pop()
        lv = self._levels[-1]
        lv.entered = None
        lv.origin = self._recenter(self._cursor, lv.radius, self._cursor)
        lv.tracker.reset(lv.origin, self._cursor, grace=0.18)
        self._last_origin, self._last_radius = lv.origin, lv.radius
        self._st = None

    def _commit(self, st: IntentState, release: bool) -> None:
        lv = self._levels[-1]
        if st.index is None:
            if release or self._latched:
                self._cancel()
            return
        slot = lv.slots[st.index]
        if slot is BACK:
            self._pop()
            if release:
                self._latched = True
            return
        if not slot.is_enabled():
            if release:
                self._cancel()
            return
        if slot.is_branch:
            self._push(slot)
            if release:
                self._latched = True
            return
        res = self._call(slot.activate, self)
        if self._state is State.INPUT:
            return
        if res is Activation.KEEP:
            self._latched = True
            return
        self._begin_close(st.index, cancelled=False)

    def _cancel(self) -> None:
        if self._state is State.INPUT and self._input_item is not None:
            self._call(self._input_item.on_cancel)
            self._finish_input()
        else:
            self._begin_close(None, cancelled=True)

    def _begin_close(self, chosen: Optional[int], cancelled: bool) -> None:
        for l in self._levels:
            l.open.z = 1.0  # critically damped: no bounce on the way out
        if self._levels:
            self._levels[-1].chosen = chosen
        self._state, self._close_t, self._blocked = State.CLOSING, 0.0, True
        self._release_focus()
        self._call(self.on_close, cancelled)

    # ---- text input ---------------------------------------------------------
    def _begin_input(self, item: TextInput) -> None:
        self._input_item = item
        if not item.keep_text:
            item.text = ""
        self._input_origin = self._levels[-1].origin
        self._input_focus = True
        self._state = State.INPUT
        self._take_focus()

    def _finish_input(self) -> None:
        self._input_item = None
        self._begin_close(None, cancelled=False)

    # ============================================================ overlay win ==
    def _monitor_at(self, x: int, y: int):
        for m in glfw.get_monitors():
            mx, my = glfw.get_monitor_pos(m)
            mode = glfw.get_video_mode(m)
            if mx <= x < mx + mode.size.width and my <= y < my + mode.size.height:
                return m
        return glfw.get_primary_monitor()

    def _place_overlay(self, x: int, y: int) -> None:
        m = self._monitor_at(x, y)
        mx, my = glfw.get_monitor_pos(m)
        mode = glfw.get_video_mode(m)
        w, h = mode.size.width, mode.size.height
        key = (mx, my, w, h)
        if key != self._mon_key:
            if self._panels and self._mon_key is not None:  # panels live on one monitor
                for p in self._panels:
                    self._call(p.on_close)
                self._panels.clear()
            self._mon_key = key
            glfw.set_window_pos(self._win, mx, my)
            # 1px short of full height: a borderless window that exactly covers the
            # monitor gets "fullscreen-optimised" by Windows, which kills transparency.
            glfw.set_window_size(self._win, w, h - 1)
        self._ox, self._oy = mx, my
        self._work = tuple(glfw.get_monitor_workarea(m))
        self._ui_scale = glfw.get_monitor_content_scale(m)[0] * self.user_scale
        self._painter.scale = self._ui_scale

    def _show_overlay(self) -> None:
        self._frame(0.0)  # prime the transparent back buffer so the first present is clear
        glfw.show_window(self._win)
        self._visible = True

    def _hide_overlay(self) -> None:
        self._release_focus()
        self._set_passthrough(True)
        glfw.hide_window(self._win)
        self._visible = False

    def _set_passthrough(self, on: bool) -> None:
        if on == self._passthrough:
            return
        try:
            glfw.set_window_attrib(self._win, glfw.MOUSE_PASSTHROUGH, on)
        except Exception:  # GLFW < 3.4
            win32.set_click_through(self._hwnd, on)
        self._passthrough = on

    def _take_focus(self) -> None:
        """Give the overlay keyboard focus (needed for typing)."""
        if self._has_focus:
            return
        fg = win32.foreground_hwnd()
        self._prev_fg = 0 if fg == self._hwnd else fg
        win32.modify_exstyle(self._hwnd, remove=win32.WS_EX_NOACTIVATE)
        win32.force_foreground(self._hwnd)
        self._has_focus = True

    def _release_focus(self) -> None:
        if not self._has_focus:
            return
        self._has_focus = False
        win32.modify_exstyle(self._hwnd, add=win32.WS_EX_NOACTIVATE)
        if win32.foreground_hwnd() == self._hwnd:
            win32.restore_foreground(self._prev_fg)
        self._prev_fg = 0

    # =============================================================== frame ====
    def _frame(self, dt: float) -> None:
        with self._overlay():
            io = self._io
            fbw, fbh = glfw.get_framebuffer_size(self._win)
            gl.glViewport(0, 0, fbw, fbh)
            gl.glClearColor(0.0, 0.0, 0.0, 0.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
            imgui.backends.opengl3_new_frame()
            imgui.backends.glfw_new_frame()
            self._sample_input(io)
            imgui.new_frame()
            self._draw_ui(dt, io)
            imgui.render()
            imgui.backends.opengl3_render_draw_data(imgui.get_draw_data())
            glfw.swap_buffers(self._win)
            self._capture = bool(io.want_capture_mouse)
        self._set_passthrough(not (self._state is State.ACTIVE or self._capture))

    def _sample_input(self, io) -> None:
        self._btn = win32.mouse_buttons()
        self._edge = tuple(c and not p for c, p in zip(self._btn, self._prev_btn))
        self._prev_btn = self._btn
        esc = win32.key_down(win32.VK_ESCAPE)
        self._esc_edge, self._prev_esc = esc and not self._prev_esc, esc
        if self._state is State.ACTIVE:   # the pie owns the mouse; panels get nothing
            io.add_mouse_pos_event(-1e9, -1e9)
            for b in range(3):
                io.add_mouse_button_event(b, False)
        else:
            io.add_mouse_pos_event(self._cursor[0] - self._ox, self._cursor[1] - self._oy)
            for b in range(3):
                io.add_mouse_button_event(b, self._btn[b])
            if self._edge[0] and self._capture and not self._has_focus:
                self._take_focus()  # clicked a panel: it may contain a text field

    def _draw_ui(self, dt: float, io) -> None:
        th, P = self.theme, self._painter
        W, H = io.display_size.x, io.display_size.y
        dl = imgui.get_background_draw_list()
        off = (self._ox, self._oy)
        S = self._state

        if S is State.ACTIVE:
            self._tick_active(dt)
            S = self._state
        elif S is State.INPUT and (self._esc_edge or (self._edge[0] and not self._capture)):
            self._cancel()
            S = self._state

        self._fade.step({State.ACTIVE: 1.0, State.INPUT: 0.6}.get(S, 0.0), dt)
        fade = clamp(self._fade.x)
        draw_backdrop(dl, W, H, th, fade)

        n = len(self._levels)
        for i, lv in enumerate(self._levels):
            top = i == n - 1
            lv.open.step(1.0 if (top and S is State.ACTIVE) or (not top) else 0.0, dt)
            lv.ghost.step(0.0 if top else 1.0, dt)
            if top:
                self._step_springs(lv, self._st if S is State.ACTIVE else None, dt)
        for i, lv in enumerate(self._levels[:-1]):
            draw_ghost(dl, P, lv, off, self._levels[i + 1].origin, lv.ghost.x,
                       fade if S is State.ACTIVE else 0.0)
        if self._levels:
            draw_level(dl, P, self._levels[-1], off,
                       self._st if S is State.ACTIVE else None, fade if S is not State.INPUT else 0.0)
            if S is State.ACTIVE and self._latched:
                self._draw_hint(dl, W, H)

        if S is State.INPUT:
            self._draw_input(io, W, H)
        for p in list(self._panels):
            self._draw_panel(p, dt, W, H)

        if S is State.CLOSING:
            self._close_t += dt
            if self._close_t > 0.34:
                self._state, self._levels, self._st = State.IDLE, [], None

    def _draw_hint(self, dl, W, H) -> None:
        P, th = self._painter, self.theme
        P.text(dl, W / 2, H - 46 * self._ui_scale, "Click to choose  -  Esc to cancel",
               th.font_size * 0.9 * self._ui_scale, th.text_dim, 0.8 * clamp(self._fade.x))

    # ---- active pie ---------------------------------------------------------
    def _tick_active(self, dt: float) -> None:
        trig_down = self.trigger.is_down()
        if self._esc_edge or self._edge[1]:
            self._cancel()
            return
        lv = self._levels[-1]
        sc = self._ui_scale
        st = lv.tracker.update(self._cursor, dt, lv.angles, lv.sector, sc)
        self._st = st

        key = (id(lv), st.index)
        if key != self._hover_key:
            self._hover_key = key
            if st.index is not None and lv.slots[st.index] is not BACK:
                self._call(lv.slots[st.index].on_hover)

        # intent: push outward / dwell on a branch (or the back slot) to travel the tree
        if st.index is not None:
            slot = lv.slots[st.index]
            push = st.distance >= self.intent.push_ratio * lv.radius
            dwell = (st.dwell >= self.intent.dwell_time
                     and st.distance >= self.intent.dead_zone * 1.6 * sc)
            if push or dwell:
                if slot is BACK:
                    self._pop()
                    return
                if slot.is_branch and slot.is_enabled():
                    self._push(slot)
                    return

        if not self._latched and not trig_down:
            self._commit(st, release=True)
        elif self._edge[0]:
            self._commit(st, release=False)

    def _step_springs(self, lv: _Level, st: Optional[IntentState], dt: float) -> None:
        th = self.theme
        for i in range(len(lv.slots)):
            if st is not None:
                a = lv.angles[i]
                bx, by = lv.origin[0] + math.cos(a) * lv.radius, lv.origin[1] + math.sin(a) * lv.radius
                d = math.hypot(self._cursor[0] - bx, self._cursor[1] - by)
                p = clamp(1.0 - d / (1.25 * lv.radius))
                tgt = 1.0 + th.max_grow * p * p + (0.1 if i == st.index else 0.0)
                hot = 1.0 if i == st.index else 0.0
            else:
                tgt, hot = 1.0, 0.0
            if lv.chosen == i:
                tgt, hot = 1.35, 1.0
            lv.scales[i].step(tgt, dt)
            lv.hot[i].step(hot, dt)

    # ---- text field ---------------------------------------------------------
    def _draw_input(self, io, W: float, H: float) -> None:
        item, th, sc = self._input_item, self.theme, self._ui_scale
        if item is None:
            return
        w = item.width * sc
        ox = clamp(self._input_origin[0] - self._ox, w / 2 + 24 * sc, W - w / 2 - 24 * sc)
        oy = clamp(self._input_origin[1] - self._oy, 60 * sc, H - 60 * sc)
        imgui.set_next_window_pos(V2(ox, oy), _v(imgui.Cond_.always), V2(0.5, 0.5))
        fl = (_v(imgui.WindowFlags_.no_title_bar) | _v(imgui.WindowFlags_.no_resize)
              | _v(imgui.WindowFlags_.no_move) | _v(imgui.WindowFlags_.no_saved_settings)
              | _v(imgui.WindowFlags_.always_auto_resize) | _v(imgui.WindowFlags_.no_scrollbar))
        sv = [(imgui.StyleVar_.alpha, clamp(self._fade.x / 0.6)),
              (imgui.StyleVar_.window_rounding, 22 * sc), (imgui.StyleVar_.frame_rounding, 16 * sc),
              (imgui.StyleVar_.window_border_size, 1.0),
              (imgui.StyleVar_.window_padding, V2(18 * sc, 14 * sc)),
              (imgui.StyleVar_.frame_padding, V2(14 * sc, 10 * sc))]
        sc_ = [(imgui.Col_.window_bg, _c4(th.panel_bg)), (imgui.Col_.border, _c4(th.accent, 0.6)),
               (imgui.Col_.frame_bg, _c4(th.bubble_hot)), (imgui.Col_.text, _c4(th.text))]
        for k, val in sv:
            imgui.push_style_var(_v(k), val)
        for k, val in sc_:
            imgui.push_style_color(_v(k), val)
        imgui.begin("##pie_input", None, fl)
        imgui.text_colored(_c4(th.text_dim), item.label)
        imgui.set_next_item_width(w)
        if self._input_focus:
            imgui.set_keyboard_focus_here()
            self._input_focus = False
        submitted, text = imgui.input_text_with_hint(
            "##q", item.placeholder, item.text, _v(imgui.InputTextFlags_.enter_returns_true))
        imgui.end()
        imgui.pop_style_color(len(sc_))
        imgui.pop_style_var(len(sv))
        if text != item.text:
            item.text = text
            self._call(item.on_change, text)
        if submitted:
            self._call(item.on_submit, item.text)
            if item.close_on_submit:
                self._finish_input()

    # ---- panels -------------------------------------------------------------
    def _panel_pos(self, p: Panel, W: float, H: float):
        sc, th = self._ui_scale, self.theme
        w, h = p.size[0] * sc, p.size[1] * sc
        a = p.anchor
        if isinstance(a, tuple):
            x, y = a[0] - self._ox, a[1] - self._oy
        elif a == "center":
            x, y = (W - w) / 2, (H - h) / 2
        else:
            base = self._cursor if a == "cursor" else self._last_origin
            bx, by = base[0] - self._ox, base[1] - self._oy
            gap = (self._last_radius + th.item_radius * 1.5 * sc) if a == "origin" else 24 * sc
            x, y = bx + gap, by - h / 2
            if x + w > W - 12:
                x = bx - gap - w
        return clamp(x, 12, max(12, W - w - 12)), clamp(y, 12, max(12, H - h - 12))

    def _draw_panel(self, p: Panel, dt: float, W: float, H: float) -> None:
        th, sc = self.theme, self._ui_scale
        a = p._fade.step(1.0 if p.open else 0.0, dt)
        if not p._placed:
            x, y = self._panel_pos(p, W, H)
            imgui.set_next_window_pos(V2(x, y), _v(imgui.Cond_.always))
            p._placed = True
        imgui.set_next_window_size(V2(p.size[0] * sc, p.size[1] * sc), _v(imgui.Cond_.once))
        fl = _v(imgui.WindowFlags_.no_saved_settings) | _v(imgui.WindowFlags_.no_collapse)
        sv = [(imgui.StyleVar_.alpha, clamp(a)), (imgui.StyleVar_.window_rounding, th.rounding * sc),
              (imgui.StyleVar_.window_border_size, 1.0),
              (imgui.StyleVar_.window_padding, V2(14 * sc, 12 * sc))]
        cs = [(imgui.Col_.window_bg, _c4(th.panel_bg)), (imgui.Col_.title_bg, _c4(th.panel_bg)),
              (imgui.Col_.title_bg_active, _c4(mix(th.panel_bg, th.accent, 0.18))),
              (imgui.Col_.border, _c4(th.ring)), (imgui.Col_.header_hovered, _c4(th.accent, 0.35)),
              (imgui.Col_.header_active, _c4(th.accent, 0.5))]
        for k, val in sv:
            imgui.push_style_var(_v(k), val)
        for k, val in cs:
            imgui.push_style_color(_v(k), val)
        expanded, opened = imgui.begin(f"{p.title}###pie_panel_{p.id}",
                                       True if p.closable else None, fl)
        if expanded and p.draw:
            try:
                p.draw(p)
            except Exception:
                traceback.print_exc()
                p.open = False
        imgui.end()
        imgui.pop_style_color(len(cs))
        imgui.pop_style_var(len(sv))
        if p.closable and opened is False:
            p.open = False
        if not p.open and a < 0.03:
            self._panels.remove(p)
            self._call(p.on_close)
