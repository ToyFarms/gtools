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

    def unproject(self, screen_x: float, screen_y: float, z_plane: float = 0.0) -> vec3:
        nx = (2.0 * screen_x) / self.width - 1.0
        ny = 1.0 - (2.0 * screen_y) / self.height

        inv_vp = glm.inverse(self.view_proj())

        near_vec4 = inv_vp * glm.vec4(nx, ny, -1.0, 1.0)
        far_vec4 = inv_vp * glm.vec4(nx, ny, 1.0, 1.0)

        near_world = vec3(near_vec4) / near_vec4.w  # pyright: ignore[reportAttributeAccessIssue]
        far_world = vec3(far_vec4) / far_vec4.w  # pyright: ignore[reportAttributeAccessIssue]

        ray_origin = near_world
        ray_dir = glm.normalize(far_world - near_world)

        if abs(ray_dir.z) < 1e-6:
            return near_world

        t = (z_plane - ray_origin.z) / ray_dir.z

        return ray_origin + ray_dir * t

    def fit_to_rect(self, x: float, y: float, w: float, h: float, z: float = 0.0, padding: float = 0.1) -> None:
        pw = w * (1.0 + padding * 2.0)
        ph = h * (1.0 + padding * 2.0)

        cx = x + w / 2.0
        cy = y + h / 2.0

        dist_y = ph / (2.0 * math.tan(self.fov / 2.0))

        aspect = self.width / max(self.height, 1)
        fov_x = 2.0 * math.atan(math.tan(self.fov / 2.0) * aspect)
        dist_x = pw / (2.0 * math.tan(fov_x / 2.0))

        dist = max(dist_x, dist_y)
        dist = max(100.0, min(dist, 40000.0))

        self.pos = vec3(cx, cy, z + dist)
        self.yaw = 0.0
        self.pitch = 0.0
