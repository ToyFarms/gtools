import ctypes
from sys import argv
from typing import cast
from pathlib import Path
import glfw
import moderngl as mgl
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
#version 450

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
#version 450

out vec4 out_fragColor;
in vec2 texCoord;
flat in float layer;
uniform sampler2DArray texArray;

void main() {
    out_fragColor = texture(texArray, vec3(texCoord, layer));
}
"""


class GLTexManager:
    FIXED_SIZE = 1024

    def __init__(self, ctx: mgl.Context, max_layers: int = 256) -> None:
        self.ctx = ctx
        self.max_layers = max_layers

        self._texture_array: mgl.TextureArray | None = None
        self._layer_map: dict[str, tuple[int, int, int]] = {}
        self._next_layer: int = 0

    def _ensure_array(self) -> None:
        if self._texture_array is not None:
            return

        if hasattr(self, "_texture_buffer"):
            return
        self._texture_buffer = np.zeros((self.max_layers, self.FIXED_SIZE, self.FIXED_SIZE, 4), dtype=np.uint8)

    def _upload_to_layer(self, file: str) -> tuple[int, int, int]:
        if file in self._layer_map:
            return self._layer_map[file]

        self._ensure_array()

        rtex = RTTex.from_file(file)
        mip = rtex.get_mip(0)
        pixels = mip.pixels
        orig_h, orig_w = pixels.shape[:2]

        layer = self._next_layer
        self._texture_buffer[layer, 0:orig_h, 0:orig_w] = pixels
        self._next_layer += 1
        self._layer_map[file] = (self.FIXED_SIZE, self.FIXED_SIZE, layer)
        return self.FIXED_SIZE, self.FIXED_SIZE, layer

    def flush(self) -> None:
        used = self._next_layer
        trimmed = np.ascontiguousarray(self._texture_buffer[:used])
        print(f"Writing {trimmed.nbytes / 1e6:.1f} MB for {used} layers")

        self._texture_array = self.ctx.texture_array(
            (self.FIXED_SIZE, self.FIXED_SIZE, used),
            components=4,
            dtype="u1",
        )
        self._texture_array.filter = (mgl.NEAREST, mgl.NEAREST)
        self._texture_array.write(trimmed.tobytes())

    def get_layer(self, file: str | Path) -> tuple[int, int, int]:
        return self._upload_to_layer(str(file))

    def bind(self, location: int = 0):
        if self._texture_array is None:
            raise RuntimeError("texture array not initialized")

        self._texture_array.use(location=location)


def build_world(mgr: GLTexManager, world: World) -> npt.NDArray[np.float32]:
    # 6 vertices * (x,y,u,v,layer)
    tile_comp = 30

    buf = np.zeros(tile_comp * world.width * world.height, dtype=np.float32)

    for tile in world.tiles:
        b = tile.index * tile_comp

        bx = tile.pos.x * 32
        by = tile.pos.y * 32

        item = item_database.get(tile.fg_id)
        w, h, layer = mgr.get_layer(setting.asset_path / item.texture_file.decode())

        u0 = (item.tex_coord_x * 32) / w
        v0 = (item.tex_coord_y * 32) / h
        u1 = ((item.tex_coord_x + 1) * 32) / w
        v1 = ((item.tex_coord_y + 1) * 32) / h

        vertices = np.array(
            [
                # x, y, u, v, layer
                bx - 16,
                by - 16,
                u0,
                v0,
                layer,
                bx + 16,
                by - 16,
                u1,
                v0,
                layer,
                bx + 16,
                by + 16,
                u1,
                v1,
                layer,
                bx - 16,
                by - 16,
                u0,
                v0,
                layer,
                bx + 16,
                by + 16,
                u1,
                v1,
                layer,
                bx - 16,
                by + 16,
                u0,
                v1,
                layer,
            ],
            dtype=np.float32,
        )

        buf[b : b + tile_comp] = vertices
    return buf


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

        return glm.ortho(left, right, bottom, top, -1.0, 1.0)

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
        wy = top - ny * (top - bottom)
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

    ctx = mgl.create_context()
    ctx.viewport = (0, 0, W, H)
    ctx.enable(mgl.BLEND)
    ctx.blend_func = mgl.SRC_ALPHA, mgl.ONE_MINUS_SRC_ALPHA

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
        if ctx:
            ctx.viewport = (0, 0, width, height)
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
            camera.pos.y = dragging["start_cam"].y + dy / camera.zoom

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

    prog = ctx.program(
        vertex_shader=VERTEX_SHADER,
        fragment_shader=FRAGMENT_SHADER,
    )

    mgr = GLTexManager(ctx)
    vertices = build_world(mgr, world)
    mgr.flush()

    vbo = ctx.buffer(vertices.tobytes())
    vao = ctx.vertex_array(prog, [(vbo, "2f 2f 1f", "in_pos", "in_texCoord", "in_layer")])

    while not glfw.window_should_close(window):
        glfw.poll_events()

        impl.process_inputs()
        imgui.new_frame()

        ctx.clear(0.1, 0.1, 0.1)

        m = camera.proj()
        ptr = glm.value_ptr(m)
        raw = ctypes.string_at(ptr, 16 * ctypes.sizeof(ctypes.c_float))
        cast(mgl.Uniform, prog["u_mvp"]).write(raw)

        mgr.bind(0)
        cast(mgl.Uniform, prog["texArray"]).value = 0
        vao.render()

        imgui.begin("Controls", True)
        imgui.text("Middle-click + drag to pan (world follows mouse).")
        imgui.text("Scroll to zoom centered on mouse.")
        imgui.text("Press R to reset camera.")
        imgui.separator()
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
