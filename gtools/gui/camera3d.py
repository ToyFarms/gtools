import math
import ctypes

from pyglm.glm import vec3, mat4x4
from pyglm import glm
import numpy as np
import numpy.typing as npt


class Camera3D:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

        self.fov = math.radians(45.0)
        self.near = 1.0
        self.far = 50000.0

        self.pos = vec3(0.0, 0.0, 0.0)
        self.speed = 500.0

        self.yaw = 0.0
        self.pitch = -0.6

        self.min_pitch = -math.pi / 2.0 + 0.05
        self.max_pitch = math.pi / 2.0 - 0.05

    def forward(self) -> vec3:
        return vec3(
            -math.cos(self.pitch) * math.sin(self.yaw),
            -math.sin(self.pitch),
            -math.cos(self.pitch) * math.cos(self.yaw),
        )

    def flat_forward(self) -> vec3:
        return vec3(-math.sin(self.yaw), 0.0, -math.cos(self.yaw))

    def right(self) -> vec3:
        return vec3(
            math.cos(self.yaw),
            0.0,
            -math.sin(self.yaw),
        )

    def up(self) -> vec3:
        return vec3(0.0, -1.0, 0.0)

    def view_proj(self) -> mat4x4:
        aspect = self.width / max(self.height, 1)
        proj = glm.perspective(self.fov, aspect, self.near, self.far)
        proj[1][1] *= -1.0

        eye = self.pos
        target = self.pos + self.forward()

        view = glm.lookAt(eye, target, vec3(0, 1, 0))

        return proj * view

    def view_proj_as_numpy(self) -> npt.NDArray[np.float32]:
        m = self.view_proj()
        ptr = glm.value_ptr(m)
        return np.frombuffer(
            ctypes.string_at(ptr, 16 * ctypes.sizeof(ctypes.c_float)),
            dtype=np.float32,
        ).reshape((4, 4), order="C")

    def look(self, dx: float, dy: float, sensitivity: float = 0.003) -> None:
        self.yaw -= dx * sensitivity
        self.pitch -= dy * sensitivity
        self.pitch = max(self.min_pitch, min(self.pitch, self.max_pitch))

    def move(self, forward: float, right: float, up: float, dt: float, speed_mul: float = 1) -> None:
        velocity = self.speed * speed_mul * dt
        self.pos += self.flat_forward() * (forward * velocity)
        self.pos += self.right() * (right * velocity)
        self.pos += self.up() * (up * velocity)

    def resize(self, width: int, height: int) -> None:
        self.width = width
        self.height = height

    def fit_to_rect(self, world_width: int, world_height: int) -> None:
        cx = world_width / 2.0
        cy = world_height / 2.0
        self.pos = vec3(cx, cy, 1500.0)
        self.yaw = 0.0
        self.pitch = -0.6
