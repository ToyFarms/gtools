import ctypes
from sys import argv
from pathlib import Path
from typing import cast

import glfw
from OpenGL.GL import *  # pyright: ignore[reportWildcardImportFromLibrary]
import numpy as np
import numpy.typing as npt

from imgui_bundle import imgui
from imgui_bundle.python_backends.glfw_backend import GlfwRenderer
from pyglm.glm import vec2, mat4x4
from pyglm import glm

from gtools import setting
from gtools.core import ndialog
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.packet import NetPacket
from gtools.core.growtopia.rttex import RTTex
from gtools.core.growtopia.world import World
from gtools.core.wsl import windows_home


class ShaderProgram:
    def __init__(self, vs_src: str, fs_src: str) -> None:
        self._id = self._link(vs_src, fs_src)

    @classmethod
    def from_file(cls, vs_file: str | Path, fs_file: str | Path | None = None) -> "ShaderProgram":
        if vs_file and fs_file:
            return cls(Path(vs_file).read_text(), Path(fs_file).read_text())
        else:
            name = Path(vs_file).with_suffix("").name
            base = Path(vs_file).parent
            return cls.from_file(base / f"{name}.vert", base / f"{name}.frag")

    def use(self) -> None:
        glUseProgram(self._id)

    def uniform_location(self, name: str) -> int:
        return glGetUniformLocation(self._id, name)

    def set_mat4(self, location: int, matrix: npt.NDArray[np.float32]) -> None:
        glUniformMatrix4fv(location, 1, GL_FALSE, matrix)

    def set_int(self, location: int, value: int) -> None:
        glUniform1i(location, value)

    @staticmethod
    def _compile(src: str, shader_type: int) -> int:
        shader = cast(int, glCreateShader(shader_type))
        glShaderSource(shader, src)
        glCompileShader(shader)
        if not glGetShaderiv(shader, GL_COMPILE_STATUS):
            log = glGetShaderInfoLog(shader).decode(errors="ignore")
            raise RuntimeError(f"shader compile error:\n{log}")

        return shader

    @classmethod
    def _link(cls, vs_src: str, fs_src: str) -> int:
        vs = cls._compile(vs_src, GL_VERTEX_SHADER)
        fs = cls._compile(fs_src, GL_FRAGMENT_SHADER)

        prog = cast(int, glCreateProgram())
        glAttachShader(prog, vs)
        glAttachShader(prog, fs)
        glLinkProgram(prog)

        if not glGetProgramiv(prog, GL_LINK_STATUS):
            log = glGetProgramInfoLog(prog).decode(errors="ignore")
            raise RuntimeError(f"program link error:\n{log}")

        for s in (vs, fs):
            glDetachShader(prog, s)
            glDeleteShader(s)

        return prog


class Mesh:
    def __init__(self, vertices: npt.NDArray[np.float32], layout: list[int], usage: int = GL_STATIC_DRAW) -> None:
        self._vertex_count = vertices.size // sum(layout)
        self._vao = glGenVertexArrays(1)
        self._vbo = glGenBuffers(1)

        glBindVertexArray(self._vao)
        glBindBuffer(GL_ARRAY_BUFFER, self._vbo)

        data = vertices.tobytes()
        glBufferData(GL_ARRAY_BUFFER, len(data), data, usage)

        stride = sum(layout) * ctypes.sizeof(ctypes.c_float)
        offset = 0
        for loc, components in enumerate(layout):
            glEnableVertexAttribArray(loc)
            glVertexAttribPointer(
                loc,
                components,
                GL_FLOAT,
                GL_FALSE,
                stride,
                ctypes.c_void_p(offset * ctypes.sizeof(ctypes.c_float)),
            )
            offset += components

        glBindVertexArray(0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

    def draw(self, mode: int = GL_TRIANGLES) -> None:
        glBindVertexArray(self._vao)
        glDrawArrays(mode, 0, self._vertex_count)
        glBindVertexArray(0)

    def delete(self) -> None:
        glDeleteBuffers(1, [self._vbo])
        glDeleteVertexArrays(1, [self._vao])


class GLTexManager:
    FIXED_SIZE = 1024

    def __init__(self, max_layers: int = 256) -> None:
        self.max_layers = max_layers
        self._texture_id: int | None = None
        self._layer_map: dict[str, tuple[int, int, int]] = {}
        self._next_layer: int = 0
        self._buffer = np.zeros((max_layers, self.FIXED_SIZE, self.FIXED_SIZE, 4), dtype=np.uint8)

    def get_layer(self, file: str | Path) -> tuple[int, int, int]:
        key = str(file)
        if key in self._layer_map:
            return self._layer_map[key]

        rtex = RTTex.from_file(key)
        pixels = rtex.get_mip(0).pixels
        orig_h, orig_w = pixels.shape[:2]

        if orig_h > self.FIXED_SIZE or orig_w > self.FIXED_SIZE:
            raise RuntimeError(f"texture {key} ({orig_w}×{orig_h}) exceeds FIXED_SIZE {self.FIXED_SIZE}")

        layer = self._next_layer
        self._buffer[layer, :orig_h, :orig_w] = pixels
        self._next_layer += 1
        self._layer_map[key] = (self.FIXED_SIZE, self.FIXED_SIZE, layer)
        return self._layer_map[key]

    def flush(self) -> None:
        used = self._next_layer
        if used == 0:
            raise RuntimeError("no layers")

        W = H = self.FIXED_SIZE
        print(f"uploading {self._buffer[:used].nbytes / 1e6:.1f} MB " f"({used} layers, {W}×{H})")

        if self._texture_id is None:
            self._texture_id = glGenTextures(1)

        glBindTexture(GL_TEXTURE_2D_ARRAY, self._texture_id)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)

        glTexImage3D(GL_TEXTURE_2D_ARRAY, 0, GL_RGBA8, W, H, used, 0, GL_RGBA, GL_UNSIGNED_BYTE, self._buffer[:used])
        glBindTexture(GL_TEXTURE_2D_ARRAY, 0)

    def bind(self, unit: int = 0) -> None:
        if self._texture_id is None:
            raise RuntimeError("no texture id, did you call flush()?")

        glActiveTexture(int(GL_TEXTURE0) + unit)
        glBindTexture(GL_TEXTURE_2D_ARRAY, self._texture_id)


class Camera2D:
    def __init__(self, width: int, height: int) -> None:
        self.pos = vec2(0.0, 0.0)
        self.zoom = 1.0
        self.width = width
        self.height = height
        self.min_zoom = 0.05
        self.max_zoom = 10.0

    def proj(self) -> mat4x4:
        hw = self.width / (2.0 * self.zoom)
        hh = self.height / (2.0 * self.zoom)
        return glm.ortho(
            self.pos.x - hw,
            self.pos.x + hw,
            self.pos.y + hh,
            self.pos.y - hh,
            -1.0,
            1.0,
        )

    def proj_as_numpy(self) -> npt.NDArray[np.float32]:
        m = self.proj()
        ptr = glm.value_ptr(m)
        return np.frombuffer(
            ctypes.string_at(ptr, 16 * ctypes.sizeof(ctypes.c_float)),
            dtype=np.float32,
        )

    def screen_to_world(self, sx: float, sy: float) -> vec2:
        hw = self.width / (2.0 * self.zoom)
        hh = self.height / (2.0 * self.zoom)
        nx, ny = sx / self.width, sy / self.height
        return vec2(
            (self.pos.x - hw) + nx * 2 * hw,
            (self.pos.y - hh) + ny * 2 * hh,
        )

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


class WorldRenderer:
    LAYOUT = [2, 2, 1]
    TILE_PX = 32
    HALF_PX = 16

    def __init__(self) -> None:
        self._tex_mgr = GLTexManager()
        self._mesh: Mesh | None = None

    def load(self, world: World) -> None:
        if self._mesh:
            self._mesh.delete()

        vertices = self._build_vertices(world)
        self._tex_mgr.flush()
        self._mesh = Mesh(vertices, self.LAYOUT)

    def bind_textures(self, unit: int = 0) -> None:
        self._tex_mgr.bind(unit)

    def draw(self) -> None:
        if self._mesh:
            self._mesh.draw()

    def _build_vertices(self, world: World) -> npt.NDArray[np.float32]:
        verts: list[float] = []
        for tile in world.tiles:
            if tile.bg_id:
                verts.extend(self._tile_verts(tile, tile.bg_id, tile.bg_tex_index))
            if tile.fg_id:
                verts.extend(self._tile_verts(tile, tile.fg_id, tile.fg_tex_index))
        return np.array(verts, dtype=np.float32)

    def _tile_verts(self, tile, item_id: int, tex_index: int) -> list[float]:
        bx = tile.pos.x * self.TILE_PX
        by = tile.pos.y * self.TILE_PX

        item = item_database.get(item_id)
        w, h, layer = self._tex_mgr.get_layer(setting.asset_path / item.texture_file.decode())

        tex_pos, is_flipped = tile.tex_pos(item_id, tex_index)
        u0 = (tex_pos.x * self.TILE_PX) / w
        v0 = (tex_pos.y * self.TILE_PX) / h
        u1 = ((tex_pos.x + 1) * self.TILE_PX) / w
        v1 = ((tex_pos.y + 1) * self.TILE_PX) / h
        if is_flipped:
            u0, u1 = u1, u0

        p = self.HALF_PX

        # fmt: off
        return [
            bx - p, by - p, u0, v0, layer,
            bx + p, by - p, u1, v0, layer,
            bx + p, by + p, u1, v1, layer,
            bx - p, by - p, u0, v0, layer,
            bx + p, by + p, u1, v1, layer,
            bx - p, by + p, u0, v1, layer,
        ]
        # fmt: on


class InputRouter:
    def __init__(self, window, camera: Camera2D) -> None:
        self._camera = camera
        self._drag: dict = {"active": False}

        self._prev_resize = glfw.set_framebuffer_size_callback(window, self._on_resize)
        self._prev_scroll = glfw.set_scroll_callback(window, self._on_scroll)
        self._prev_mouse_btn = glfw.set_mouse_button_callback(window, self._on_mouse_btn)
        self._prev_cursor = glfw.set_cursor_pos_callback(window, self._on_cursor)
        self._prev_key = glfw.set_key_callback(window, self._on_key)
        self._window = window

    def _on_resize(self, win, w: int, h: int) -> None:
        if self._prev_resize:
            self._prev_resize(win, w, h)

        glViewport(0, 0, w, h)
        self._camera.resize(w, h)

    def _on_scroll(self, win, xoff: float, yoff: float) -> None:
        if self._prev_scroll:
            self._prev_scroll(win, xoff, yoff)

        if imgui.get_io().want_capture_mouse:
            return

        sx, sy = glfw.get_cursor_pos(win)
        self._camera.zoom_around(1.1**yoff, sx, sy)

    def _on_mouse_btn(self, win, button: int, action: int, mods: int) -> None:
        if self._prev_mouse_btn:
            self._prev_mouse_btn(win, button, action, mods)
        if imgui.get_io().want_capture_mouse:
            return
        if button == glfw.MOUSE_BUTTON_LEFT:
            if action == glfw.PRESS:
                sx, sy = glfw.get_cursor_pos(win)
                self._drag = {
                    "active": True,
                    "start_screen": (sx, sy),
                    "start_cam": glm.vec2(self._camera.pos),
                }
            elif action == glfw.RELEASE:
                self._drag["active"] = False

    def _on_cursor(self, win, xpos: float, ypos: float) -> None:
        if self._prev_cursor:
            self._prev_cursor(win, xpos, ypos)

        if imgui.get_io().want_capture_mouse or not self._drag.get("active"):
            return

        dx = xpos - self._drag["start_screen"][0]
        dy = ypos - self._drag["start_screen"][1]
        cam = self._camera
        cam.pos.x = self._drag["start_cam"].x - dx / cam.zoom
        cam.pos.y = self._drag["start_cam"].y - dy / cam.zoom

    def _on_key(self, win, key: int, scancode: int, action: int, mods: int) -> None:
        if self._prev_key:
            self._prev_key(win, key, scancode, action, mods)
        if action == glfw.PRESS and key == glfw.KEY_R:
            self._camera.reset()


class App:
    def __init__(self, world_path: Path | None = None, width: int = 800, height: int = 600) -> None:
        self._init_glfw(width, height)
        self._camera = Camera2D(width, height)

        imgui.create_context()
        self._imgui = GlfwRenderer(self._window)
        self._input = InputRouter(self._window, self._camera)

        self._world_shader = ShaderProgram.from_file("shaders/world")
        self._u_mvp = self._world_shader.uniform_location("u_mvp")
        self._u_tex = self._world_shader.uniform_location("texArray")

        self._world_renderer = WorldRenderer()
        if world_path:
            pkt = NetPacket.deserialize(world_path.read_bytes())
            self._world_renderer.load(World.from_tank(pkt.tank))

    def run(self) -> None:
        while not glfw.window_should_close(self._window):
            glfw.poll_events()
            self._imgui.process_inputs()
            imgui.new_frame()

            self._render_viewport()
            self._render_gui()

            imgui.render()
            self._imgui.render(imgui.get_draw_data())
            glfw.swap_buffers(self._window)

        self._shutdown()

    def _render_viewport(self) -> None:
        glClearColor(0.1, 0.1, 0.1, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)

        if self._world_renderer._mesh:
            self._world_shader.use()
            self._world_shader.set_mat4(self._u_mvp, self._camera.proj_as_numpy())
            self._world_renderer.bind_textures(unit=0)
            self._world_shader.set_int(self._u_tex, 0)
        self._world_renderer.draw()

    def _render_gui(self) -> None:
        imgui.begin("debug", True)
        imgui.text(f"camera.pos = ({self._camera.pos.x:.1f}, {self._camera.pos.y:.1f})")
        imgui.text(f"zoom = {self._camera.zoom:.3f}")
        if imgui.button("Open World"):
            world = ndialog.open_file("Open World")
            if isinstance(world, str):
                pkt = NetPacket.deserialize(Path(world).read_bytes())
                self._world_renderer.load(World.from_tank(pkt.tank))
        imgui.end()

    def _init_glfw(self, width: int, height: int) -> None:
        if not glfw.init():
            raise RuntimeError("failed to initialise GLFW.")

        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 5)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)

        self._window = glfw.create_window(width, height, "gui", None, None)
        if not self._window:
            glfw.terminate()
            raise RuntimeError("failed to create GLFW window.")

        glfw.make_context_current(self._window)
        glfw.swap_interval(1)
        glViewport(0, 0, width, height)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    def _shutdown(self) -> None:
        self._imgui.shutdown()
        glfw.terminate()


def main() -> None:
    path = None
    if len(argv) > 1:
        path = windows_home() / ".gtools/worlds" / argv[1]
    App(world_path=path).run()


if __name__ == "__main__":
    main()
