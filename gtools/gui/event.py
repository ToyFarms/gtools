from dataclasses import dataclass
from enum import Enum, auto
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


Point = tuple[float, float]


class GestureLock(Enum):
    NONE = auto()
    PAN = auto()
    PINCH = auto()


class TouchManager(TouchRouter):
    def __init__(self, window, coherence_threshold: float = 0.015) -> None:
        super().__init__(window)
        self.install()
        self.active: dict[int, TouchContactEvent] = {}
        self.prev_positions: dict[int, Point] = {}

        self.coherence_threshold = coherence_threshold

        self._gesture_lock = GestureLock.NONE
        self._coherence = 0.0
        self._event_queue: queue.SimpleQueue[TouchEvent] = queue.SimpleQueue()

    def poll(self) -> list[TouchEvent]:
        for e in super().poll():
            if e.tip_active:
                if e.contact_id not in self.active:
                    self.on_touch_down(e)
                else:
                    self.active[e.contact_id] = e
            else:
                if e.contact_id in self.active:
                    self.on_touch_up(e)

        self._process_move()

        events: list[TouchEvent] = []
        while not self._event_queue.empty():
            try:
                events.append(self._event_queue.get_nowait())
            except queue.Empty:
                break
        return events

    def on_touch_down(self, ev: TouchContactEvent) -> None:
        self.active[ev.contact_id] = ev
        self.prev_positions[ev.contact_id] = (ev.x, ev.y)
        if len(self.active) == 2:
            self._coherence = 0.0
            self._gesture_lock = GestureLock.NONE

    def on_touch_up(self, ev: TouchContactEvent) -> None:
        self.active.pop(ev.contact_id, None)
        self.prev_positions.pop(ev.contact_id, None)
        if not self.active:
            self._gesture_lock = GestureLock.NONE
            self._coherence = 0.0

    def _process_move(self) -> None:
        if len(self.active) != 2:
            return

        ids = list(self.active.keys())
        if not all(i in self.prev_positions for i in ids):
            for i in ids:
                self.prev_positions[i] = (self.active[i].x, self.active[i].y)
            return

        (ax0, ay0), (bx0, by0) = (self.prev_positions[i] for i in ids)
        (ax1, ay1), (bx1, by1) = ((self.active[i].x, self.active[i].y) for i in ids)

        for i in ids:
            self.prev_positions[i] = (self.active[i].x, self.active[i].y)

        if self._gesture_lock is GestureLock.NONE:
            va = (ax1 - ax0, ay1 - ay0)
            vb = (bx1 - bx0, by1 - by0)
            mag_a = math.hypot(*va)
            mag_b = math.hypot(*vb)

            if mag_a > 1e-6 and mag_b > 1e-6:
                cos_angle = (va[0] * vb[0] + va[1] * vb[1]) / (mag_a * mag_b)
                self._coherence += cos_angle * (mag_a + mag_b)

            if self._coherence > self.coherence_threshold:
                self._gesture_lock = GestureLock.PAN
            elif self._coherence < -self.coherence_threshold:
                self._gesture_lock = GestureLock.PINCH
            else:
                return  # need more data

        if self._gesture_lock is GestureLock.PAN:
            dx = ((ax1 + bx1) - (ax0 + bx0)) * 0.5
            dy = ((ay1 + by1) - (ay0 + by0)) * 0.5

            self._event_queue.put(TouchEvent(dx=dx, dy=dy, scale_factor=1.0, d_angle=0.0))

        elif self._gesture_lock is GestureLock.PINCH:
            d0 = math.hypot(bx0 - ax0, by0 - ay0)
            d1 = math.hypot(bx1 - ax1, by1 - ay1)
            scale = d1 / d0 if d0 > 1e-6 else 1.0
            angle = math.atan2(by1 - ay1, bx1 - ax1) - math.atan2(by0 - ay0, bx0 - ax0)
            angle = (angle + math.pi) % (2 * math.pi) - math.pi

            self._event_queue.put(TouchEvent(dx=0.0, dy=0.0, scale_factor=scale, d_angle=angle))


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
