from abc import ABC, abstractmethod
from collections import defaultdict
import ctypes
from dataclasses import dataclass, field
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
from gtools.core.growtopia.world import Tile, World
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


class Uniform:
    def __init__(self, loc: int, prog: "ShaderProgram") -> None:
        self.loc = loc
        self.prog = prog

    def set_mat4(self, x: npt.NDArray[np.float32]) -> None:
        glUniformMatrix4fv(self.loc, 1, GL_FALSE, x)

    def set_int(self, x: int) -> None:
        glUniform1i(self.loc, x)


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

    def get_uniform(self, name: str) -> Uniform:
        id = glGetUniformLocation(self._id, name)
        return Uniform(loc=id, prog=self)

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

    def delete(self) -> None:
        glDeleteProgram(self._id)


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
    layer: int
    array: "TextureArray"

    @property
    def tex_id(self) -> int:
        return self.array.tex_id

    def __hash__(self) -> int:
        return hash(self.key)


class TextureArray:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.tex_id = int(glGenTextures(1))

        self._resident: list[GLTex] = []
        self._staging: list[GLTex] = []

        self._allocated_layers = 0

    def _allocate(self, total_layers: int) -> None:
        glBindTexture(GL_TEXTURE_2D_ARRAY, self.tex_id)

        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)

        glTexImage3D(
            GL_TEXTURE_2D_ARRAY,
            0,
            GL_RGBA8,
            self.width,
            self.height,
            total_layers,
            0,
            GL_RGBA,
            GL_UNSIGNED_BYTE,
            None,
        )

        self._allocated_layers = total_layers
        glBindTexture(GL_TEXTURE_2D_ARRAY, 0)

    def stage(self, key: str) -> GLTex:
        layer = len(self._resident) + len(self._staging)
        tex = GLTex(key, self.width, self.height, layer, self)
        self._staging.append(tex)
        return tex

    def flush(self) -> None:
        if not self._staging:
            return

        total_layers = len(self._resident) + len(self._staging)

        if total_layers != self._allocated_layers:
            self._allocate(total_layers)

        glBindTexture(GL_TEXTURE_2D_ARRAY, self.tex_id)

        for tex in self._staging:
            data = RTTex.from_file(tex.key)
            mip = data.get_mip(0)

            glTexSubImage3D(
                GL_TEXTURE_2D_ARRAY,
                0,
                0,
                0,
                tex.layer,
                self.width,
                self.height,
                1,
                GL_RGBA,
                GL_UNSIGNED_BYTE,
                mip.pixels,
            )

        self._resident.extend(self._staging)
        self._staging.clear()

        glBindTexture(GL_TEXTURE_2D_ARRAY, 0)

    def bind(self, unit: int = 0) -> None:
        glActiveTexture(int(GL_TEXTURE0) + unit)
        glBindTexture(GL_TEXTURE_2D_ARRAY, self.tex_id)

    def delete(self) -> None:
        glDeleteTextures(1, [self.tex_id])
        self._resident.clear()
        self._staging.clear()
        self._allocated_layers = 0


class GLTexManager:
    def __init__(self) -> None:
        self._textures: dict[str, GLTex] = {}
        self._arrays: dict[tuple[int, int], TextureArray] = {}

    def _get_or_create_array(self, width: int, height: int) -> TextureArray:
        key = (width, height)

        if key not in self._arrays:
            self._arrays[key] = TextureArray(width, height)

        return self._arrays[key]

    def push_texture(self, file: str | Path) -> GLTex:
        key = str(file)

        if key in self._textures:
            return self._textures[key]

        header = RTTex.header_from_file(key)

        array = self._get_or_create_array(header.width, header.height)

        tex = array.stage(key)
        self._textures[key] = tex

        return tex

    def flush(self) -> None:
        for array in self._arrays.values():
            array.flush()

    def bind(self, tex: GLTex, unit: int = 0) -> None:
        tex.array.bind(unit)

    def delete_texture(self, key: str) -> None:
        if key not in self._textures:
            return

        tex = self._textures.pop(key)
        array = tex.array

        array.delete()

        self._arrays.pop((array.width, array.height), None)

        keys_to_remove = [
            k for k, t in self._textures.items()
            if t.array is array
        ]

        for k in keys_to_remove:
            self._textures.pop(k)

    def delete_all(self) -> None:
        for array in self._arrays.values():
            array.delete()

        self._arrays.clear()
        self._textures.clear()

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

    def __init__(self, tex_mgr: GLTexManager | None = None) -> None:
        self._tex_mgr = tex_mgr if tex_mgr else GLTexManager()
        self._bg_meshes: dict[GLTex, Mesh] = {}
        self._fg_meshes: dict[GLTex, Mesh] = {}

    def load(self, world: World) -> None:
        self._build_meshes(world)
        self._tex_mgr.flush()

    def any(self) -> bool:
        return bool(self._bg_meshes) or bool(self._fg_meshes)

    def draw(self, tex: Uniform) -> None:
        for key, mesh in self._bg_meshes.items():
            self._tex_mgr.bind(key, unit=0)
            tex.set_int(0)
            mesh.draw()
        for key, mesh in self._fg_meshes.items():
            self._tex_mgr.bind(key, unit=0)
            tex.set_int(0)
            mesh.draw()

    def _build_meshes(self, world: World) -> None:
        bg_verts: defaultdict[GLTex, list[float]] = defaultdict(list)
        fg_verts: defaultdict[GLTex, list[float]] = defaultdict(list)
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

    def _tile_verts(self, tile: Tile, item_id: int, tex_index: int) -> tuple[GLTex, list[float]]:
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
        return (tex, [
            bx - p, by - p, u0, v0, tex.layer,
            bx + p, by - p, u1, v0, tex.layer,
            bx + p, by + p, u1, v1, tex.layer,
            bx - p, by - p, u0, v0, tex.layer,
            bx + p, by + p, u1, v1, tex.layer,
            bx - p, by + p, u0, v1, tex.layer,
        ])
        # fmt: on

    def delete(self) -> None:
        for mesh in self._bg_meshes.values():
            mesh.delete()
        for mesh in self._fg_meshes.values():
            mesh.delete()

        self._bg_meshes.clear()
        self._fg_meshes.clear()


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

    def delete(self) -> None:
        glDeleteFramebuffers(1, [self.fbo])
        glDeleteTextures(1, [self.color_tex])
        glDeleteRenderbuffers(1, [self.rbo])


_DEBUG_COLLAPSED_W = 32.0
_DEBUG_EXPANDED_RATIO = 0.20


class WorldTab:
    _WORLD_TAB_COUNTER = itertools.count(1)

    def __init__(self, tex_mgr: GLTexManager, shader: ShaderProgram, mvp: Uniform, tex: Uniform, dockspace_id: int, path: Path) -> None:
        self._name = f"{path.stem}##{next(self._WORLD_TAB_COUNTER)}"
        self._shader = shader
        self._mvp = mvp
        self._tex = tex
        self._dockspace_id = dockspace_id

        self._camera = Camera2D(800, 600)
        self._fbo = Framebuffer(800, 600)
        self._renderer = WorldRenderer(tex_mgr)

        self._hovered = False
        self._drag: dict = {"active": False}
        self._image_origin: tuple[float, float] = (0.0, 0.0)

        self._open = True
        self._first_render = True

        pkt = NetPacket.deserialize(path.read_bytes())
        self._renderer.load(World.from_tank(pkt.tank))

    def delete(self) -> None:
        self._renderer.delete()
        self._fbo.delete()

    @property
    def is_open(self) -> bool:
        return bool(self._open)

    def render(self) -> None:
        if self._first_render and self._dockspace_id:
            imgui.set_next_window_dock_id(self._dockspace_id)
            self._first_render = False

        opened, self._open = imgui.begin(self._name, self._open)
        if opened:
            cw, ch = imgui.get_content_region_avail()
            cw, ch = int(cw), int(ch)
            if cw > 0 and ch > 0:
                self._fbo.resize(cw, ch)
                self._camera.resize(cw, ch)
                self._render_to_fbo()
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
            self._mvp.set_mat4(self._camera.proj_as_numpy())
            self._renderer.draw(self._tex)
        self._fbo.unbind()


class Panel(ABC):
    def __init__(self) -> None:
        self._debug_open = True

    @property
    def is_open(self) -> bool:
        return True

    def render(self) -> None:
        opened, should_stay = self._imgui_begin()
        if opened:
            self._render_body()
        self._imgui_end()
        self._on_close(should_stay)

    def handle_event(self, event: Event) -> bool:
        _ = event
        return False

    def render_debug(self) -> None:
        pass

    @abstractmethod
    def _imgui_begin(self) -> tuple[bool, bool]: ...

    @abstractmethod
    def _imgui_end(self) -> None: ...

    @abstractmethod
    def _render_content(self) -> None: ...

    @abstractmethod
    def delete(self) -> None: ...

    def _on_close(self, should_stay: bool) -> None:
        _ = should_stay
        pass

    def _render_body(self) -> None:
        avail_w, avail_h = imgui.get_content_region_avail()

        debug_w = _DEBUG_EXPANDED_RATIO * avail_w if self._debug_open else _DEBUG_COLLAPSED_W

        imgui.begin_child("##debug_panel", (debug_w, avail_h), child_flags=imgui.ChildFlags_.borders)

        toggle_label = "<" if self._debug_open else ">"
        if imgui.small_button(toggle_label):
            self._debug_open = not self._debug_open

        if self._debug_open:
            imgui.separator()
            self.render_debug()

        imgui.end_child()

        imgui.same_line()

        imgui.begin_child("##panel_content", (0.0, avail_h))
        self._render_content()
        imgui.end_child()


class DockspacePanel(Panel):
    def __init__(self) -> None:
        super().__init__()
        self._node_id: int = 0

    def delete(self) -> None:
        pass

    @property
    def node_id(self) -> int:
        return self._node_id

    def _imgui_begin(self) -> tuple[bool, bool]:
        display_w, display_h = imgui.get_io().display_size

        imgui.set_next_window_pos((0, 0))
        imgui.set_next_window_size((display_w, display_h))
        imgui.set_next_window_bg_alpha(0.0)

        opened = imgui.begin(
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
        return bool(opened), True

    def _imgui_end(self) -> None:
        imgui.end()

    def _render_content(self) -> None:
        self._node_id = imgui.dock_space(
            imgui.get_id("MainDockspace"),
            (0.0, 0.0),
            imgui.DockNodeFlags_.passthru_central_node,
        )

    def _render_body(self) -> None:
        self._render_content()


class WorldViewerPanel(Panel):
    def __init__(self, outer_dockspace_id: int) -> None:
        super().__init__()
        self._shader = ShaderProgram.from_file("shaders/world")
        self._mvp = self._shader.get_uniform("u_mvp")
        self._tex = self._shader.get_uniform("texArray")
        self._tex_mgr = GLTexManager()
        self._outer_dockspace_id = outer_dockspace_id

        self._inner_dockspace_id: int = 0
        self._inner_dockspace_key = f"WorldViewerDock"
        self._tabs: list[WorldTab] = []

        self._open = True
        self._first_render = True

    @property
    def is_open(self) -> bool:
        return self._open

    def delete(self) -> None:
        for tab in self._tabs:
            tab.delete()
        self._tabs = []
        self._tex_mgr.delete_all()
        self._shader.delete()

    def open_world(self, path: Path) -> None:
        self._tabs.append(WorldTab(self._tex_mgr, self._shader, self._mvp, self._tex, self._inner_dockspace_id, path))

    def render_debug(self) -> None:
        if imgui.button("Open World", (-1, 0)):
            world = ndialog.open_file("Open World")
            if isinstance(world, str):
                self.open_world(Path(world))

    def render(self) -> None:
        opened, should_stay = self._imgui_begin()
        if opened:
            self._render_body()
        self._imgui_end()
        self._on_close(should_stay)

        self._prune_closed_tabs()
        for tab in self._tabs:
            tab.render()

    def handle_event(self, event: Event) -> bool:
        for tab in self._tabs:
            if tab.handle_event(event):
                return True
        return False

    def _imgui_begin(self) -> tuple[bool, bool]:
        if self._first_render and self._outer_dockspace_id:
            imgui.set_next_window_dock_id(self._outer_dockspace_id)
            self._first_render = False
        x, y = imgui.begin("World Viewer", self._open)
        return x, bool(y)

    def _imgui_end(self) -> None:
        imgui.end()

    def _on_close(self, should_stay: bool) -> None:
        self._open = should_stay

    def _render_content(self) -> None:
        self._inner_dockspace_id = imgui.dock_space(
            imgui.get_id(self._inner_dockspace_key),
            (0.0, 0.0),
            imgui.DockNodeFlags_.passthru_central_node,
        )

    def _prune_closed_tabs(self) -> None:
        alive = []
        for tab in self._tabs:
            if tab.is_open:
                alive.append(tab)
            else:
                tab.delete()
        self._tabs = alive


class App:
    def __init__(self, world_path: Path | None = None, width: int = 800, height: int = 600) -> None:
        self.init_glfw(width, height)

        imgui.create_context()
        io = imgui.get_io()
        io.config_windows_move_from_title_bar_only = True
        io.config_flags |= imgui.ConfigFlags_.docking_enable

        self.imgui_renderer = GlfwRenderer(self.window)
        self.input = InputRouter(self.window)

        self.dockspace = DockspacePanel()
        self.world_viewer = WorldViewerPanel(self.dockspace.node_id)
        self.panels: list[Panel] = [self.dockspace, self.world_viewer]

        if world_path:
            self.world_viewer.open_world(world_path)

    def run(self) -> None:
        while not glfw.window_should_close(self.window):
            glfw.poll_events()
            self.imgui_renderer.process_inputs()
            imgui.new_frame()

            self.process_events(self.input.poll())

            glClearColor(0.1, 0.1, 0.1, 1.0)
            glClear(GL_COLOR_BUFFER_BIT)

            for panel in self.panels:
                panel.render()

            imgui.render()
            self.imgui_renderer.render(imgui.get_draw_data())
            glfw.swap_buffers(self.window)

        self.shutdown()

    def process_events(self, events: list[Event]) -> None:
        for e in events:
            if isinstance(e, ResizeEvent):
                glViewport(0, 0, e.width, e.height)
                continue

            for panel in self.panels:
                if panel.handle_event(e):
                    break

    def init_glfw(self, width: int, height: int) -> None:
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

    def shutdown(self) -> None:
        for panel in self.panels:
            panel.delete()

        self.imgui_renderer.shutdown()
        glfw.terminate()


def main() -> None:
    path = None
    if len(argv) > 1:
        path = windows_home() / ".gtools/worlds" / argv[1]
    App(world_path=path).run()


if __name__ == "__main__":
    main()
