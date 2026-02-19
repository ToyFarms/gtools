from abc import ABC, abstractmethod
from collections import defaultdict
import ctypes
from dataclasses import dataclass
import itertools
from sys import argv
from pathlib import Path
from typing import cast, Union
import queue

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


Event = Union[ScrollEvent, MouseButtonEvent, CursorMoveEvent, KeyEvent, ResizeEvent]


class InputRouter:
    def __init__(self, window) -> None:
        self._queue: queue.SimpleQueue[Event] = queue.SimpleQueue()
        self._window = window

        self._prev_resize = glfw.set_framebuffer_size_callback(window, self._on_resize)
        self._prev_scroll = glfw.set_scroll_callback(window, self._on_scroll)
        self._prev_mouse_btn = glfw.set_mouse_button_callback(window, self._on_mouse_btn)
        self._prev_cursor = glfw.set_cursor_pos_callback(window, self._on_cursor)
        self._prev_key = glfw.set_key_callback(window, self._on_key)

    def poll(self) -> list[Event]:
        events: list[Event] = []
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


class ShaderProgram:
    def __init__(self, vs_src: str, fs_src: str) -> None:
        self._id = self._link(vs_src, fs_src)

    @classmethod
    def from_file(cls, vs_file: str | Path, fs_file: str | Path | None = None) -> "ShaderProgram":
        if vs_file and fs_file:
            return cls(Path(vs_file).read_text(), Path(fs_file).read_text())
        name = Path(vs_file).with_suffix("").name
        base = Path(vs_file).parent
        return cls.from_file(base / f"{name}.vert", base / f"{name}.frag")

    def use(self) -> None:
        glUseProgram(self._id)

    def uniform_location(self, name: str) -> int:
        return glGetUniformLocation(self._id, name)

    def set_mat4(self, loc: int, m: npt.NDArray[np.float32]) -> None:
        glUniformMatrix4fv(loc, 1, GL_FALSE, m)

    def set_int(self, loc: int, v: int) -> None:
        glUniform1i(loc, v)

    @staticmethod
    def _compile(src: str, shader_type: int) -> int:
        shader = cast(int, glCreateShader(shader_type))
        glShaderSource(shader, src)
        glCompileShader(shader)
        if not glGetShaderiv(shader, GL_COMPILE_STATUS):
            raise RuntimeError(glGetShaderInfoLog(shader).decode(errors="ignore"))
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
            raise RuntimeError(glGetProgramInfoLog(prog).decode(errors="ignore"))
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
        glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices.tobytes(), usage)

        stride = sum(layout) * ctypes.sizeof(ctypes.c_float)
        offset = 0
        for loc, components in enumerate(layout):
            glEnableVertexAttribArray(loc)
            glVertexAttribPointer(loc, components, GL_FLOAT, GL_FALSE, stride, ctypes.c_void_p(offset * ctypes.sizeof(ctypes.c_float)))
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


@dataclass(slots=True)
class GLTex:
    key: str
    width: int
    height: int
    tex_id: int
    layer: int


class GLTexManager:
    def __init__(self) -> None:
        self._key_tex_id_map: dict[str, int] = {}
        self._gpu_tex: dict[int, GLTex] = {}
        self._tex_id = itertools.count()
        self._batch_process: dict[str, GLTex] = {}
        self._batch_buf: defaultdict[int, list[GLTex]] = defaultdict(list)

    def push_texture(self, file: str | Path) -> GLTex:
        key = str(file)
        if key in self._key_tex_id_map:
            id = self._key_tex_id_map[key]
            if id in self._gpu_tex:
                return self._gpu_tex[id]
        if key in self._batch_process:
            return self._batch_process[key]

        header = RTTex.header_from_file(key)

        if key not in self._key_tex_id_map:
            tex_id = int(glGenTextures(1))
            self._key_tex_id_map[key] = tex_id
        else:
            tex_id = self._key_tex_id_map[key]

        layer = len(self._batch_buf[tex_id])
        tex = GLTex(key, header.width, header.height, tex_id, layer)
        self._batch_buf[tex_id].append(tex)
        self._batch_process[key] = tex
        return tex

    def flush(self) -> None:
        for tex_id, textures in self._batch_buf.items():
            glBindTexture(GL_TEXTURE_2D_ARRAY, tex_id)
            glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
            glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            w, h = textures[0].width, textures[0].height
            glTexImage3D(GL_TEXTURE_2D_ARRAY, 0, GL_RGBA8, w, h, len(textures), 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
            for tex in textures:
                data = RTTex.from_file(tex.key)
                glTexSubImage3D(GL_TEXTURE_2D_ARRAY, 0, 0, 0, tex.layer, w, h, 1, GL_RGBA, GL_UNSIGNED_BYTE, data.get_mip(0).pixels)
                self._gpu_tex[tex_id] = tex
            glBindTexture(GL_TEXTURE_2D_ARRAY, 0)
        self._batch_process.clear()
        self._batch_buf.clear()

    def bind(self, id: int) -> int:
        glActiveTexture(int(GL_TEXTURE0) + id)
        glBindTexture(GL_TEXTURE_2D_ARRAY, id)
        return id

    def delete(self, id: int | None = None) -> None:
        if id is not None:
            glDeleteTextures(GL_TEXTURE_2D_ARRAY, [id])
            self._gpu_tex = {k: v for k, v in self._gpu_tex.items() if k != id}
        else:
            glBindTexture(GL_TEXTURE_2D_ARRAY, 0)
            glDeleteTextures(GL_TEXTURE_2D_ARRAY, list(self._gpu_tex.keys()))
            self._gpu_tex.clear()
            self._key_tex_id_map.clear()


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
        return glm.ortho(self.pos.x - hw, self.pos.x + hw, self.pos.y + hh, self.pos.y - hh, -1.0, 1.0)

    def proj_as_numpy(self) -> npt.NDArray[np.float32]:
        m = self.proj()
        ptr = glm.value_ptr(m)
        return np.frombuffer(ctypes.string_at(ptr, 16 * ctypes.sizeof(ctypes.c_float)), dtype=np.float32)

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


class WorldRenderer:
    LAYOUT = [2, 2, 1]
    TILE_PX = 32

    def __init__(self) -> None:
        self._tex_mgr = GLTexManager()
        self._bg_meshes: dict[int, Mesh] = {}
        self._fg_meshes: dict[int, Mesh] = {}

    def load(self, world: World) -> None:
        self._build_meshes(world)
        self._tex_mgr.flush()

    def any(self) -> bool:
        return bool(self._bg_meshes) or bool(self._fg_meshes)

    def draw(self, prog: ShaderProgram, u_tex: int) -> None:
        for key, mesh in self._bg_meshes.items():
            prog.set_int(u_tex, self._tex_mgr.bind(key))
            mesh.draw()
        for key, mesh in self._fg_meshes.items():
            prog.set_int(u_tex, self._tex_mgr.bind(key))
            mesh.draw()

    def _build_meshes(self, world: World) -> None:
        bg_verts: defaultdict[int, list[float]] = defaultdict(list)
        fg_verts: defaultdict[int, list[float]] = defaultdict(list)
        for tile in world.tiles:
            if tile.bg_id:
                tid, verts = self._tile_verts(tile, tile.bg_id, tile.bg_tex_index)
                bg_verts[tid].extend(verts)
            if tile.fg_id:
                tid, verts = self._tile_verts(tile, tile.fg_id, tile.fg_tex_index)
                fg_verts[tid].extend(verts)
        for key, verts in bg_verts.items():
            self._bg_meshes[key] = Mesh(np.array(verts, dtype=np.float32), self.LAYOUT)
        for key, verts in fg_verts.items():
            self._fg_meshes[key] = Mesh(np.array(verts, dtype=np.float32), self.LAYOUT)

    def _tile_verts(self, tile, item_id: int, tex_index: int) -> tuple[int, list[float]]:
        bx = tile.pos.x * self.TILE_PX
        by = tile.pos.y * self.TILE_PX
        item = item_database.get(item_id)
        tex = self._tex_mgr.push_texture(setting.asset_path / item.texture_file.decode())
        tex_pos, is_flipped = tile.tex_pos(item_id, tex_index)
        u0 = (tex_pos.x * self.TILE_PX) / tex.width
        v0 = (tex_pos.y * self.TILE_PX) / tex.height
        u1 = ((tex_pos.x + 1) * self.TILE_PX) / tex.width
        v1 = ((tex_pos.y + 1) * self.TILE_PX) / tex.height
        if is_flipped:
            u0, u1 = u1, u0
        p = self.TILE_PX / 2
        # fmt: off
        return (tex.tex_id, [
            bx - p, by - p, u0, v0, tex.layer,
            bx + p, by - p, u1, v0, tex.layer,
            bx + p, by + p, u1, v1, tex.layer,
            bx - p, by - p, u0, v0, tex.layer,
            bx + p, by + p, u1, v1, tex.layer,
            bx - p, by + p, u0, v1, tex.layer,
        ])
        # fmt: on


class Framebuffer:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.fbo = glGenFramebuffers(1)
        self.color_tex = glGenTextures(1)
        self.rbo = glGenRenderbuffers(1)
        self._create_attachments()

    def _create_attachments(self) -> None:
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glBindTexture(GL_TEXTURE_2D, self.color_tex)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, self.width, self.height, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, self.color_tex, 0)
        glBindRenderbuffer(GL_RENDERBUFFER, self.rbo)
        glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH24_STENCIL8, self.width, self.height)
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_RENDERBUFFER, self.rbo)
        if glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError("FBO not complete")
        glBindFramebuffer(GL_FRAMEBUFFER, 0)

    def resize(self, width: int, height: int) -> None:
        if width == self.width and height == self.height:
            return
        self.width = width
        self.height = height
        self._create_attachments()

    def bind(self) -> None:
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glViewport(0, 0, self.width, self.height)

    def unbind(self) -> None:
        glBindFramebuffer(GL_FRAMEBUFFER, 0)


class Panel(ABC):
    @abstractmethod
    def render(self) -> None: ...

    def handle_event(self, event: Event) -> bool:
        _ = event
        return False

    @property
    def is_open(self) -> bool:
        return True


_SIDEBAR_W_RATIO = 0.20
_VIEWER_COUNTER = itertools.count(1)


class DockspacePanel(Panel):
    def __init__(self) -> None:
        self._node_id: int = 0

    @property
    def node_id(self) -> int:
        return self._node_id

    def render(self) -> None:
        display_w, display_h = imgui.get_io().display_size
        sidebar_w = int(display_w * _SIDEBAR_W_RATIO)
        right_w = display_w - sidebar_w

        imgui.set_next_window_pos((sidebar_w, 0))
        imgui.set_next_window_size((right_w, display_h))
        imgui.set_next_window_bg_alpha(0.0)

        imgui.begin(
            "##dockspace_host",
            None,
            imgui.WindowFlags_.no_title_bar
            | imgui.WindowFlags_.no_resize
            | imgui.WindowFlags_.no_move
            | imgui.WindowFlags_.no_collapse
            | imgui.WindowFlags_.no_saved_settings
            | imgui.WindowFlags_.no_bring_to_front_on_focus
            | imgui.WindowFlags_.no_nav_focus
            | imgui.WindowFlags_.no_docking,
        )

        self._node_id = imgui.dock_space(
            imgui.get_id("MainDockspace"),
            (0.0, 0.0),
            imgui.DockNodeFlags_.passthru_central_node,
        )

        imgui.end()


class WorldViewerPanel(Panel):
    def __init__(
        self,
        shader: ShaderProgram,
        u_mvp: int,
        u_tex: int,
        dockspace_node_id: int,
        world_path: Path | None = None,
    ) -> None:
        n = next(_VIEWER_COUNTER)
        self._title = f"World Viewer {n}"
        self._shader = shader
        self._u_mvp = u_mvp
        self._u_tex = u_tex
        self._dockspace_node_id = dockspace_node_id

        self._camera = Camera2D(800, 600)
        self._fbo = Framebuffer(800, 600)
        self._renderer = WorldRenderer()

        self._hovered = False
        self._drag: dict = {"active": False}
        self._image_origin: tuple[float, float] = (0.0, 0.0)

        self._open = True
        self._first_render = True

        if world_path:
            self.load_world(world_path)

    def load_world(self, path: Path) -> None:
        pkt = NetPacket.deserialize(path.read_bytes())
        self._renderer.load(World.from_tank(pkt.tank))

    @property
    def is_open(self) -> bool:
        return bool(self._open)

    def render(self) -> None:
        self._render_to_fbo()
        self._render_window()

    def handle_event(self, event: Event) -> bool:
        if isinstance(event, ScrollEvent):
            if self._hovered:
                lx, ly = self._to_local(event.screen_x, event.screen_y)
                self._camera.zoom_around(1.1**event.yoff, lx, ly)
                return True

        elif isinstance(event, MouseButtonEvent):
            if event.button == glfw.MOUSE_BUTTON_LEFT:
                if event.action == glfw.PRESS and self._hovered:
                    lx, ly = self._to_local(event.screen_x, event.screen_y)
                    self._drag = {
                        "active": True,
                        "start_screen": (lx, ly),
                        "start_cam": glm.vec2(self._camera.pos),
                    }
                    return True
                elif event.action == glfw.RELEASE and self._drag.get("active"):
                    self._drag["active"] = False
                    return True

        elif isinstance(event, CursorMoveEvent):
            if self._drag.get("active"):
                lx, ly = self._to_local(event.xpos, event.ypos)
                dx = lx - self._drag["start_screen"][0]
                dy = ly - self._drag["start_screen"][1]
                self._camera.pos.x = self._drag["start_cam"].x - dx / self._camera.zoom
                self._camera.pos.y = self._drag["start_cam"].y - dy / self._camera.zoom
                return True

        elif isinstance(event, KeyEvent):
            if self._hovered and event.action == glfw.PRESS and event.key == glfw.KEY_R:
                self._camera.reset()
                return True

        return False

    def _to_local(self, sx: float, sy: float) -> tuple[float, float]:
        ox, oy = self._image_origin
        return sx - ox, sy - oy

    def _render_to_fbo(self) -> None:
        self._fbo.bind()
        glClearColor(0.08, 0.08, 0.08, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)
        if self._renderer.any():
            self._shader.use()
            self._shader.set_mat4(self._u_mvp, self._camera.proj_as_numpy())
            self._renderer.draw(self._shader, self._u_tex)
        self._fbo.unbind()

    def _render_window(self) -> None:
        if self._first_render and self._dockspace_node_id:
            imgui.set_next_window_dock_id(self._dockspace_node_id)
            self._first_render = False

        _, self._open = imgui.begin(self._title, self._open)

        cw, ch = imgui.get_content_region_avail()
        cw, ch = int(cw), int(ch)

        if cw > 0 and ch > 0:
            self._fbo.resize(cw, ch)
            self._camera.resize(cw, ch)

            imgui.image(
                imgui.ImTextureRef(self._fbo.color_tex),
                (cw, ch),
                uv0=(0, 1),
                uv1=(1, 0),
            )
            self._hovered = imgui.is_item_hovered()
            rect_min = imgui.get_item_rect_min()
            self._image_origin = (rect_min.x, rect_min.y)

        imgui.end()


class DebugPanel(Panel):
    def __init__(
        self,
        get_active_viewer,
        on_open_world,
    ) -> None:
        self._get_active_viewer = get_active_viewer
        self._on_open_world = on_open_world

    def render(self) -> None:
        display_w, display_h = imgui.get_io().display_size
        sidebar_w = int(display_w * _SIDEBAR_W_RATIO)

        imgui.set_next_window_pos((0, 0))
        imgui.set_next_window_size((sidebar_w, display_h))
        imgui.begin(
            "debug",
            True,
            imgui.WindowFlags_.no_title_bar
            | imgui.WindowFlags_.no_resize
            | imgui.WindowFlags_.no_move
            | imgui.WindowFlags_.no_collapse
            | imgui.WindowFlags_.no_saved_settings
            | imgui.WindowFlags_.no_docking,
        )

        viewer = self._get_active_viewer()
        if viewer:
            cam = viewer._camera
            imgui.text_wrapped(f"camera  ({cam.pos.x:.1f}, {cam.pos.y:.1f})")
            imgui.text_wrapped(f"zoom    {cam.zoom:.3f}")
        else:
            imgui.text_disabled("no world open")

        imgui.separator()

        if imgui.button("Open World", (-1, 0)):
            self._on_open_world(None)

        imgui.end()


class App:
    def __init__(self, world_path: Path | None = None, width: int = 800, height: int = 600) -> None:
        self._init_glfw(width, height)

        imgui.create_context()
        io = imgui.get_io()
        io.config_windows_move_from_title_bar_only = True
        io.config_flags |= imgui.ConfigFlags_.docking_enable

        self.imgui_renderer = GlfwRenderer(self.window)
        self.input = InputRouter(self.window)

        self._world_shader = ShaderProgram.from_file("shaders/world")
        self._u_mvp = self._world_shader.uniform_location("u_mvp")
        self._u_tex = self._world_shader.uniform_location("texArray")

        self._dockspace = DockspacePanel()
        self._viewers: list[WorldViewerPanel] = []
        self._panels: list[Panel] = [
            self._dockspace,
            DebugPanel(self._active_viewer, self._open_world_dialog),
        ]

        if world_path:
            self._add_viewer(world_path)

    def run(self) -> None:
        while not glfw.window_should_close(self.window):
            glfw.poll_events()
            self.imgui_renderer.process_inputs()
            imgui.new_frame()

            self._process_events(self.input.poll())
            self._prune_closed_viewers()

            glClearColor(0.1, 0.1, 0.1, 1.0)
            glClear(GL_COLOR_BUFFER_BIT)

            for panel in self._panels:
                panel.render()

            imgui.render()
            self.imgui_renderer.render(imgui.get_draw_data())
            glfw.swap_buffers(self.window)

        self._shutdown()

    def _process_events(self, events: list[Event]) -> None:
        for e in events:
            if isinstance(e, ResizeEvent):
                glViewport(0, 0, e.width, e.height)
                continue

            for panel in self._panels:
                if panel.handle_event(e):
                    break

    def _prune_closed_viewers(self) -> None:
        closed = [v for v in self._viewers if not v.is_open]
        for v in closed:
            self._viewers.remove(v)
            self._panels.remove(v)

    def _active_viewer(self) -> WorldViewerPanel | None:
        return self._viewers[-1] if self._viewers else None

    def _add_viewer(self, path: Path) -> WorldViewerPanel:
        viewer = WorldViewerPanel(
            self._world_shader,
            self._u_mvp,
            self._u_tex,
            self._dockspace.node_id,
            world_path=path,
        )
        self._viewers.append(viewer)
        self._panels.append(viewer)
        return viewer

    def _open_world_dialog(self, _: None) -> None:
        world = ndialog.open_file("Open World")
        if isinstance(world, str):
            self._add_viewer(Path(world))

    def _init_glfw(self, width: int, height: int) -> None:
        if not glfw.init():
            raise RuntimeError("failed to initialise GLFW.")

        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 5)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        self.window = glfw.create_window(width, height, "gui", None, None)
        if not self.window:
            glfw.terminate()
            raise RuntimeError("failed to create GLFW window.")

        glfw.make_context_current(self.window)
        glfw.swap_interval(1)
        glViewport(0, 0, width, height)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    def _shutdown(self) -> None:
        self.imgui_renderer.shutdown()
        glfw.terminate()


def main() -> None:
    path = None
    if len(argv) > 1:
        path = windows_home() / ".gtools/worlds" / argv[1]
    App(world_path=path).run()


if __name__ == "__main__":
    main()
