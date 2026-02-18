import ctypes
from sys import argv
from pathlib import Path
import glfw
from OpenGL.GL import *  # pyright: ignore[reportWildcardImportFromLibrary]
import numpy as np
import numpy.typing as npt

from imgui_bundle import imgui
from imgui_bundle.python_backends.glfw_backend import GlfwRenderer
from pyglm.glm import vec2, mat4x4
from pyglm import glm

from gtools import setting
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.packet import NetPacket
from gtools.core.growtopia.rttex import RTTex
from gtools.core.growtopia.world import World
from gtools.core.wsl import windows_home

VERTEX_SHADER = """
#version 450 core

layout (location = 0) in vec2 in_pos;
layout (location = 1) in vec2 in_texCoord;
layout (location = 2) in float in_layer;

out vec2 texCoord;
flat out float layer;

uniform mat4 u_mvp;

void main() {
    gl_Position = u_mvp * vec4(in_pos, 0.0, 1.0);
    texCoord = in_texCoord;
    layer = in_layer;
}
"""

FRAGMENT_SHADER = """
#version 450 core

out vec4 out_fragColor;
in vec2 texCoord;
flat in float layer;
uniform sampler2DArray texArray;

void main() {
    out_fragColor = texture(texArray, vec3(texCoord, layer));
}
"""


def compile_shader(src: str, shader_type: int):
    shader = glCreateShader(shader_type)
    glShaderSource(shader, src)
    glCompileShader(shader)
    ok = glGetShaderiv(shader, GL_COMPILE_STATUS)
    if not ok:
        log = glGetShaderInfoLog(shader).decode(errors="ignore")
        raise RuntimeError(f"shader compile failed:\n{log}")
    return shader


def link_program(vs_src: str, fs_src: str):
    vs = compile_shader(vs_src, GL_VERTEX_SHADER)
    fs = compile_shader(fs_src, GL_FRAGMENT_SHADER)
    prog = glCreateProgram()
    glAttachShader(prog, vs)
    glAttachShader(prog, fs)
    glLinkProgram(prog)
    ok = glGetProgramiv(prog, GL_LINK_STATUS)
    if not ok:
        log = glGetProgramInfoLog(prog).decode(errors="ignore")
        raise RuntimeError(f"program link failed:\n{log}")

    glDetachShader(prog, vs)
    glDetachShader(prog, fs)
    glDeleteShader(vs)
    glDeleteShader(fs)
    return prog


class GLTexManager:
    FIXED_SIZE = 1024

    def __init__(self, max_layers: int = 64) -> None:
        self.max_layers = max_layers
        self._texture_id: int | None = None
        self._layer_map: dict[str, tuple[int, int, int]] = {}
        self._next_layer: int = 0
        self._texture_buffer = np.zeros((self.max_layers, self.FIXED_SIZE, self.FIXED_SIZE, 4), dtype=np.uint8)

    def _upload_to_layer(self, file: str) -> tuple[int, int, int]:
        if file in self._layer_map:
            return self._layer_map[file]

        rtex = RTTex.from_file(file)
        mip = rtex.get_mip(0)
        orig_h, orig_w = mip.pixels.shape[:2]

        layer = self._next_layer
        if orig_h > self.FIXED_SIZE or orig_w > self.FIXED_SIZE:
            raise RuntimeError(f"texture {file} is larger than FIXED_SIZE {self.FIXED_SIZE}")

        self._texture_buffer[layer, 0:orig_h, 0:orig_w, :] = mip.pixels
        self._next_layer += 1
        self._layer_map[file] = (self.FIXED_SIZE, self.FIXED_SIZE, layer)
        return self.FIXED_SIZE, self.FIXED_SIZE, layer

    def flush(self) -> None:
        used = self._next_layer
        if used == 0:
            raise RuntimeError("no layers to upload")

        trimmed = self._texture_buffer[:used]
        H = self.FIXED_SIZE
        W = self.FIXED_SIZE
        D = used
        print(f"writing {trimmed.nbytes / 1e6:.1f} MB for {used} layers (W={W} H={H} D={D})")

        if self._texture_id is None:
            self._texture_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D_ARRAY, self._texture_id)

        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)

        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)

        glTexImage3D(GL_TEXTURE_2D_ARRAY, 0, GL_RGBA8, W, H, D, 0, GL_RGBA, GL_UNSIGNED_BYTE, trimmed)
        glBindTexture(GL_TEXTURE_2D_ARRAY, 0)

    def get_layer(self, file: str | Path) -> tuple[int, int, int]:
        return self._upload_to_layer(str(file))

    def bind(self, location: int = 0):
        if self._texture_id is None:
            raise RuntimeError("texture array not initialized")
        glActiveTexture(int(GL_TEXTURE0) + location)
        glBindTexture(GL_TEXTURE_2D_ARRAY, self._texture_id)


def build_world(mgr: GLTexManager, world: World) -> npt.NDArray[np.float32]:
    vertices: list[float] = []

    for tile in world.tiles:
        if tile.bg_id != 0:
            bx = tile.pos.x * 32
            by = tile.pos.y * 32

            item = item_database.get(tile.bg_id)
            w, h, layer = mgr.get_layer(setting.asset_path / item.texture_file.decode())

            tex_pos, is_flipped = tile.tex_pos(tile.bg_id, tile.bg_tex_index)
            u0 = (tex_pos.x * 32) / w
            v0 = (tex_pos.y * 32) / h
            u1 = ((tex_pos.x + 1) * 32) / w
            v1 = ((tex_pos.y + 1) * 32) / h
            if is_flipped:
                u0, u1 = u1, u0

            vertices.extend([
                bx - 16, by - 16, u0, v0, layer,
                bx + 16, by - 16, u1, v0, layer,
                bx + 16, by + 16, u1, v1, layer,
                bx - 16, by - 16, u0, v0, layer,
                bx + 16, by + 16, u1, v1, layer,
                bx - 16, by + 16, u0, v1, layer,
            ])

        if tile.fg_id != 0:
            bx = tile.pos.x * 32
            by = tile.pos.y * 32

            item = item_database.get(tile.fg_id)
            w, h, layer = mgr.get_layer(setting.asset_path / item.texture_file.decode())

            tex_pos, is_flipped = tile.tex_pos(tile.fg_id, tile.fg_tex_index)
            u0 = (tex_pos.x * 32) / w
            v0 = (tex_pos.y * 32) / h
            u1 = ((tex_pos.x + 1) * 32) / w
            v1 = ((tex_pos.y + 1) * 32) / h
            if is_flipped:
                u0, u1 = u1, u0

            vertices.extend([
                bx - 16, by - 16, u0, v0, layer,
                bx + 16, by - 16, u1, v0, layer,
                bx + 16, by + 16, u1, v1, layer,
                bx - 16, by - 16, u0, v0, layer,
                bx + 16, by + 16, u1, v1, layer,
                bx - 16, by + 16, u0, v1, layer,
            ])


    return np.array(vertices, dtype=np.float32)

class Camera2D:
    def __init__(self, width: int, height: int) -> None:
        self.pos = vec2(0.0, 0.0)
        self.zoom = 1.0
        self.width = width
        self.height = height

        self.min_zoom = 0.05
        self.max_zoom = 10.0

    def proj(self) -> mat4x4:
        half_w = self.width / (2.0 * self.zoom)
        half_h = self.height / (2.0 * self.zoom)

        left = self.pos.x - half_w
        right = self.pos.x + half_w
        bottom = self.pos.y - half_h
        top = self.pos.y + half_h

        return glm.ortho(left, right, top, bottom, -1.0, 1.0)

    def screen_to_world(self, sx: float, sy: float) -> vec2:
        half_w = self.width / (2.0 * self.zoom)
        half_h = self.height / (2.0 * self.zoom)

        left = self.pos.x - half_w
        right = self.pos.x + half_w
        top = self.pos.y + half_h
        bottom = self.pos.y - half_h

        nx = sx / self.width
        ny = sy / self.height

        wx = left + nx * (right - left)
        wy = bottom + ny * (top - bottom)
        return vec2(wx, wy)

    def zoom_by(self, factor: float, screen_x: float, screen_y: float) -> None:
        before = self.screen_to_world(screen_x, screen_y)

        self.zoom *= factor
        self.zoom = max(self.min_zoom, min(self.zoom, self.max_zoom))

        after = self.screen_to_world(screen_x, screen_y)

        self.pos += before - after

    def pan_by(self, delta_world: glm.vec2) -> None:
        self.pos += delta_world

    def resize(self, width: int, height: int) -> None:
        self.width = width
        self.height = height


def main():
    if not glfw.init():
        raise RuntimeError("failed to initialize GLFW")

    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 5)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)

    W, H = 800, 600
    window = glfw.create_window(W, H, "gui", None, None)
    if not window:
        glfw.terminate()
        raise RuntimeError("failed to create GLFW window")

    glfw.make_context_current(window)
    glfw.swap_interval(1)

    glViewport(0, 0, W, H)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    imgui.create_context()
    impl = GlfwRenderer(window)

    camera = Camera2D(W, H)

    prev_framebuffer_cb = None
    prev_scroll_cb = None
    prev_mouse_btn_cb = None
    prev_cursor_cb = None
    prev_key_cb = None

    dragging = {"active": False, "start_world": None, "start_cam": None}

    def imgui_wants_mouse():
        return imgui.get_io().want_capture_mouse

    def on_resize(_window, width: int, height: int) -> None:
        if prev_framebuffer_cb:
            prev_framebuffer_cb(_window, width, height)
        glViewport(0, 0, width, height)
        if camera:
            camera.resize(width, height)

    def on_scroll(window, xoffset, yoffset):
        if prev_scroll_cb:
            prev_scroll_cb(window, xoffset, yoffset)

        if imgui_wants_mouse():
            return

        factor = 1.1**yoffset
        sx, sy = glfw.get_cursor_pos(window)
        camera.zoom_by(factor, sx, sy)

    def on_mouse_btn(window, button, action, mods):
        if prev_mouse_btn_cb:
            prev_mouse_btn_cb(window, button, action, mods)

        if imgui_wants_mouse():
            return

        if button == glfw.MOUSE_BUTTON_LEFT:
            if action == glfw.PRESS:
                sx, sy = glfw.get_cursor_pos(window)
                dragging["active"] = True
                dragging["start_screen"] = (sx, sy)
                dragging["start_cam"] = glm.vec2(camera.pos)
            elif action == glfw.RELEASE:
                dragging["active"] = False

    def on_cursor_pos(window, xpos, ypos):
        if prev_cursor_cb:
            prev_cursor_cb(window, xpos, ypos)

        if imgui_wants_mouse():
            return

        if dragging["active"]:
            dx = xpos - dragging["start_screen"][0]
            dy = ypos - dragging["start_screen"][1]

            camera.pos.x = dragging["start_cam"].x - dx / camera.zoom
            camera.pos.y = dragging["start_cam"].y - dy / camera.zoom

    def on_key(window, key, scancode, action, mods):
        if prev_key_cb:
            prev_key_cb(window, key, scancode, action, mods)

        if action == glfw.PRESS:
            if key == glfw.KEY_R:
                camera.pos = vec2(0.0, 0.0)
                camera.zoom = 1.0

    prev_framebuffer_cb = glfw.set_framebuffer_size_callback(window, on_resize)
    prev_scroll_cb = glfw.set_scroll_callback(window, on_scroll)
    prev_mouse_btn_cb = glfw.set_mouse_button_callback(window, on_mouse_btn)
    prev_cursor_cb = glfw.set_cursor_pos_callback(window, on_cursor_pos)
    prev_key_cb = glfw.set_key_callback(window, on_key)

    f = windows_home() / ".gtools/worlds" / argv[1]
    pkt = NetPacket.deserialize(f.read_bytes())
    world = World.from_tank(pkt.tank)

    prog = link_program(VERTEX_SHADER, FRAGMENT_SHADER)

    u_mvp_loc = glGetUniformLocation(prog, "u_mvp")
    tex_loc = glGetUniformLocation(prog, "texArray")

    mgr = GLTexManager()
    vertices = build_world(mgr, world)
    mgr.flush()

    vao = glGenVertexArrays(1)
    glBindVertexArray(vao)

    vbo = glGenBuffers(1)
    glBindBuffer(GL_ARRAY_BUFFER, vbo)
    vbo_bytes = vertices.tobytes()
    glBufferData(GL_ARRAY_BUFFER, len(vbo_bytes), vbo_bytes, GL_STATIC_DRAW)

    stride = 5 * ctypes.sizeof(ctypes.c_float)
    # in_pos location 0
    glEnableVertexAttribArray(0)
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(0))
    # in_texCoord location 1
    glEnableVertexAttribArray(1)
    glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(2 * ctypes.sizeof(ctypes.c_float)))
    # in_layer location 2
    glEnableVertexAttribArray(2)
    glVertexAttribPointer(2, 1, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(4 * ctypes.sizeof(ctypes.c_float)))

    glBindVertexArray(0)
    glBindBuffer(GL_ARRAY_BUFFER, 0)

    vertex_count = vertices.size // 5

    while not glfw.window_should_close(window):
        glfw.poll_events()

        impl.process_inputs()
        imgui.new_frame()

        glClearColor(0.1, 0.1, 0.1, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)

        glUseProgram(prog)

        m = camera.proj()
        ptr = glm.value_ptr(m)

        mat = np.frombuffer(ctypes.string_at(ptr, 16 * ctypes.sizeof(ctypes.c_float)), dtype=np.float32)
        glUniformMatrix4fv(u_mvp_loc, 1, GL_FALSE, mat)

        mgr.bind(0)
        glUniform1i(tex_loc, 0)

        glBindVertexArray(vao)
        glDrawArrays(GL_TRIANGLES, 0, vertex_count)
        glBindVertexArray(0)

        imgui.begin("Debug", True)
        imgui.text(f"camera.pos = ({camera.pos.x:.1f}, {camera.pos.y:.1f})")
        imgui.text(f"zoom = {camera.zoom:.3f}")
        imgui.end()

        imgui.render()
        impl.render(imgui.get_draw_data())

        glfw.swap_buffers(window)

    impl.shutdown()
    glfw.terminate()


if __name__ == "__main__":
    main()
