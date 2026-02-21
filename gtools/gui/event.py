from dataclasses import dataclass
import math
from typing import Union
import queue
import logging

import glfw

from gtools.gui.touch.base import TouchContactEvent
from gtools.gui.touch.touch import TouchRouter

logger = logging.getLogger("gui-input")


@dataclass(slots=True)
class TouchEvent:
    dx: float
    dy: float
    scale_factor: float
    d_angle: float


class GestureState:
    NONE = 0
    POSSIBLE = 1
    ACTIVE = 2
    INERTIA = 3


Point = tuple[float, float]


class TouchManager(TouchRouter):
    def __init__(
        self,
        window,
        touch_slop: float = 0.01,
        smoothing_alpha: float = 0.15,
        scale_rot_alpha: float = 0.05,
        inertia_friction: float = 3.0,
        scale_dead_zone: float = 0.004,
        rot_dead_zone: float = 0.003,
    ) -> None:
        super().__init__(window)
        self.install()
        self.active: dict[int, TouchContactEvent] = {}
        self.start_positions: dict[int, Point] = {}
        self.start_centroid = (0.5, 0.5)
        self.start_time = None
        self.state = GestureState.NONE

        self.transform = (0.0, 0.0, 1.0, 0.0)
        self.smoothed = (0.0, 0.0, 1.0, 0.0)
        self.touch_slop = touch_slop
        self.alpha = smoothing_alpha
        self.scale_rot_alpha = scale_rot_alpha
        self.scale_dead_zone = scale_dead_zone
        self.rot_dead_zone = rot_dead_zone
        self.inertia_friction = inertia_friction

        self.last_vel = (0.0, 0.0, 0.0, 0.0)
        self.last_update_time = None
        self.smoothed_prev = (0.0, 0.0, 1.0, 0.0)

        self._event_queue: queue.SimpleQueue[TouchEvent] = queue.SimpleQueue()

    def _centroid(self, pts: list[Point]) -> Point:
        n = len(pts)
        if n == 0:
            return (0.5, 0.5)

        sx = sum(p[0] for p in pts)
        sy = sum(p[1] for p in pts)

        return (sx / n, sy / n)

    def _vecs_from_centroid(self, pts: list[Point], centroid: Point) -> list[Point]:
        return [(p[0] - centroid[0], p[1] - centroid[1]) for p in pts]

    def _similarity_transform(self, start_pts: list[Point], cur_pts: list[Point]) -> tuple[float, float, float, float]:
        n = len(start_pts)
        if n == 0:
            return (0.0, 0.0, 1.0, 0.0)

        start_cent = self._centroid(start_pts)
        cur_cent = self._centroid(cur_pts)

        if n == 1:
            tx = cur_cent[0] - start_cent[0]
            ty = cur_cent[1] - start_cent[1]
            return (tx, ty, 1.0, 0.0)

        sx = sxx = syy = sxy = syx = 0.0
        for (sx0, sy0), (cx0, cy0) in zip(start_pts, cur_pts):
            u1 = sx0 - start_cent[0]
            u2 = sy0 - start_cent[1]
            v1 = cx0 - cur_cent[0]
            v2 = cy0 - cur_cent[1]
            sxx += u1 * v1
            sxy += u1 * v2
            syx += u2 * v1
            syy += u2 * v2
            sx += u1 * u1 + u2 * u2

        if sx == 0:
            return (cur_cent[0] - start_cent[0], cur_cent[1] - start_cent[1], 1.0, 0.0)

        a = (sxx + syy) / sx
        b = (syx - sxy) / sx
        angle = math.atan2(b, a)
        num = sxx + syy
        denom = sx
        s = num / denom

        tx = cur_cent[0] - (s * (math.cos(angle) * start_cent[0] - math.sin(angle) * start_cent[1]))
        ty = cur_cent[1] - (s * (math.sin(angle) * start_cent[0] + math.cos(angle) * start_cent[1]))
        tx = cur_cent[0] - (s * (math.cos(angle) * start_cent[0] - math.sin(angle) * start_cent[1]))
        ty = cur_cent[1] - (s * (math.sin(angle) * start_cent[0] + math.cos(angle) * start_cent[1]))

        dx = cur_cent[0] - start_cent[0]
        dy = cur_cent[1] - start_cent[1]

        return (dx, dy, s, angle)

    def poll(self) -> list[TouchEvent]:
        for e in super().poll():
            if e.tip_active:
                if e.contact_id not in self.active:
                    self.on_touch_down(e)
                else:
                    self.active[e.contact_id] = e
                    self._process_move(e.timestamp)
            else:
                if e.contact_id in self.active:
                    self.on_touch_up(e)

        events: list[TouchEvent] = []
        while not self._event_queue.empty():
            try:
                events.append(self._event_queue.get_nowait())
            except queue.Empty:
                break

        return events

    def on_touch_down(self, ev: TouchContactEvent) -> None:
        if not self.active:
            self.transform = (0.0, 0.0, 1.0, 0.0)
            self.smoothed = (0.0, 0.0, 1.0, 0.0)
            self.smoothed_prev = (0.0, 0.0, 1.0, 0.0)
            self.last_vel = (0.0, 0.0, 0.0, 0.0)
            self.state = GestureState.NONE

        self.active[ev.contact_id] = ev
        self.start_positions[ev.contact_id] = (ev.x, ev.y)
        self.start_time = self.start_time or ev.timestamp
        self.state = GestureState.POSSIBLE
        self.last_update_time = ev.timestamp

    def on_touch_up(self, ev: TouchContactEvent) -> None:
        if ev.contact_id in self.active:
            del self.active[ev.contact_id]
        if ev.contact_id in self.start_positions:
            del self.start_positions[ev.contact_id]

        if not self.active:
            if self.state == GestureState.ACTIVE:
                self._start_inertia(ev.timestamp)
            else:
                self.state = GestureState.NONE

    def _process_move(self, now_ts: float) -> None:
        if len(self.active) != 2:
            return

        active_ids = list(self.active.keys())
        start_pts = [self.start_positions[i] for i in active_ids if i in self.start_positions]
        cur_pts = [(self.active[i].x, self.active[i].y) for i in active_ids]

        if len(start_pts) == 0:
            return

        dx, dy, s, angle = self._similarity_transform(start_pts, cur_pts)

        if self.state == GestureState.POSSIBLE:
            trans_mag = math.hypot(dx, dy)
            scale_dev = abs(s - 1.0)
            rot_dev = abs(angle)
            if trans_mag > self.touch_slop or scale_dev > 0.02 or rot_dev > (3.0 * math.pi / 180.0):
                self.state = GestureState.ACTIVE
                self.smoothed = (0.0, 0.0, 1.0, 0.0)
                self.last_update_time = now_ts
            else:
                return

        prev_tx, prev_ty, prev_s, prev_r = self.transform
        new_tx = dx
        new_ty = dy
        new_s = s
        new_r = angle

        dt = max(1e-6, now_ts - (self.last_update_time or now_ts))
        vx = (new_tx - prev_tx) / dt
        vy = (new_ty - prev_ty) / dt
        vs = (new_s - prev_s) / dt
        vr = (new_r - prev_r) / dt

        self.last_vel = (vx, vy, vs, vr)

        a_tr = self.alpha
        a_sr = self.scale_rot_alpha

        sm_tx = a_tr * new_tx + (1.0 - a_tr) * self.smoothed[0]
        sm_ty = a_tr * new_ty + (1.0 - a_tr) * self.smoothed[1]
        sm_s = a_sr * new_s + (1.0 - a_sr) * self.smoothed[2]
        sm_r = a_sr * new_r + (1.0 - a_sr) * self.smoothed[3]
        self.smoothed = (sm_tx, sm_ty, sm_s, sm_r)

        self.transform = (new_tx, new_ty, new_s, new_r)
        self.last_update_time = now_ts

        pd_tx, pd_ty, pd_s, pd_r = self.smoothed_prev
        delta_tx = sm_tx - pd_tx
        delta_ty = sm_ty - pd_ty
        raw_delta_s = sm_s / pd_s if pd_s != 0 else sm_s
        raw_delta_r = sm_r - pd_r
        self.smoothed_prev = self.smoothed

        delta_s = raw_delta_s if abs(raw_delta_s - 1.0) > self.scale_dead_zone else 1.0
        delta_r = raw_delta_r if abs(raw_delta_r) > self.rot_dead_zone else 0.0

        self._emit_transform(delta_tx, delta_ty, delta_s, delta_r)

    def _emit_transform(self, dx: float, dy: float, scale_factor: float, d_angle: float) -> None:
        self._event_queue.put(TouchEvent(dx=dx, dy=dy, scale_factor=scale_factor, d_angle=d_angle))

    def _start_inertia(self, now_ts: float) -> None:
        self.state = GestureState.INERTIA
        self.inertia_start_ts = now_ts
        self.inertia_v = self.last_vel

    def update_inertia(self, now_ts: float) -> None:
        if self.state != GestureState.INERTIA:
            return

        dt = now_ts - self.inertia_start_ts
        k = self.inertia_friction
        vx0, vy0, vs0, vr0 = self.inertia_v
        if k <= 0:
            return

        decay = lambda v0, t: v0 * (2.718281828 ** (-k * t))
        vxt = decay(vx0, dt)
        vyt = decay(vy0, dt)
        vst = decay(vs0, dt)
        vrt = decay(vr0, dt)

        def integrated_disp(v0, t):
            return (v0 / k) * (1.0 - 2.718281828 ** (-k * t))

        dx = integrated_disp(vx0, dt)
        dy = integrated_disp(vy0, dt)
        ds = 1.0 + integrated_disp(vs0, dt)
        dr = integrated_disp(vr0, dt)

        self._emit_transform(dx, dy, ds, dr)

        if abs(vxt) < 1e-3 and abs(vyt) < 1e-3 and abs(vst) < 1e-4 and abs(vrt) < (0.2 * math.pi / 180):
            self.state = GestureState.NONE


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


Event = Union[ScrollEvent, MouseButtonEvent, CursorMoveEvent, KeyEvent, ResizeEvent, TouchEvent]


class EventRouter:
    def __init__(self, window) -> None:
        self._queue: queue.SimpleQueue[Event] = queue.SimpleQueue()
        self._window = window
        self._touch = TouchManager(window)

        self._prev_resize = glfw.set_framebuffer_size_callback(window, self._on_resize)
        self._prev_scroll = glfw.set_scroll_callback(window, self._on_scroll)
        self._prev_mouse_btn = glfw.set_mouse_button_callback(window, self._on_mouse_btn)
        self._prev_cursor = glfw.set_cursor_pos_callback(window, self._on_cursor)
        self._prev_key = glfw.set_key_callback(window, self._on_key)

    def poll(self) -> list[Event]:
        events: list[Event] = []
        events.extend(self._touch.poll())
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

    def delete(self) -> None:
        self._touch.uninstall()
