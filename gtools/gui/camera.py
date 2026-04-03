from pyglm.glm import vec2, mat4x4
from pyglm import glm
import numpy as np
import numpy.typing as npt
import ctypes


class Camera2D:
    def __init__(self, width: int, height: int, depth_range: int = 1) -> None:
        self.pos = vec2(0.0, 0.0)
        self.zoom = 1.0
        self.width = width
        self.height = height
        self.min_zoom = 0.05
        self.max_zoom = 10.0
        self.depth_range = depth_range

    def proj(self) -> mat4x4:
        hw = self.width / (2.0 * self.zoom)
        hh = self.height / (2.0 * self.zoom)
        return glm.ortho(self.pos.x - hw, self.pos.x + hw, self.pos.y + hh, self.pos.y - hh, -self.depth_range, self.depth_range)

    def proj_as_numpy(self) -> npt.NDArray[np.float32]:
        m = self.proj()
        ptr = glm.value_ptr(m)
        return np.frombuffer(ctypes.string_at(ptr, 16 * ctypes.sizeof(ctypes.c_float)), dtype=np.float32).reshape((4, 4), order="C")

    def screen_to_world(self, sx: float, sy: float) -> vec2:
        hw = self.width / (2.0 * self.zoom)
        hh = self.height / (2.0 * self.zoom)
        nx, ny = sx / self.width, sy / self.height
        return vec2((self.pos.x - hw) + nx * 2 * hw, (self.pos.y - hh) + ny * 2 * hh)

    def zoom_around(self, factor: float, screen_x: float, screen_y: float) -> None:
        before = self.screen_to_world(screen_x, screen_y)
        self.zoom = max(self.min_zoom, min(self.zoom * factor, self.max_zoom))
        after = self.screen_to_world(screen_x, screen_y)
        self.pos += before - after

    def pan_by_screen(self, dx: float, dy: float) -> None:
        self.pos.x -= dx / self.zoom
        self.pos.y -= dy / self.zoom

    def reset(self) -> None:
        self.pos = vec2(0.0, 0.0)
        self.zoom = 1.0

    def resize(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

    def get_bounds(self) -> tuple[float, float, float, float]:
        hw = self.width / (2.0 * self.zoom)
        hh = self.height / (2.0 * self.zoom)
        return self.pos.x - hw, self.pos.y - hh, hw * 2, hh * 2

    def is_visible(self, x: float, y: float, w: float, h: float) -> bool:
        bx, by, bw, bh = self.get_bounds()
        return not (x + w < bx or x > bx + bw or y + h < by or y > by + bh)

    def fit_to_rect(self, x: float, y: float, w: float, h: float, padding: float = 0.0) -> None:
        self.pos = vec2(x + w / 2.0, y + h / 2.0)
        padded_w = w + padding * 2.0
        padded_h = h + padding * 2.0
        zoom_x = self.width / padded_w if padded_w > 0 else self.max_zoom
        zoom_y = self.height / padded_h if padded_h > 0 else self.max_zoom
        self.zoom = max(self.min_zoom, min(min(zoom_x, zoom_y), self.max_zoom))
