import itertools
import logging
import math
from pathlib import Path
import time
from OpenGL.GL import GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, glClear, glClearColor

import glfw
from imgui_bundle import imgui, imgui_knobs  # pyright: ignore[reportMissingModuleSource]
from pyglm import glm
from pyglm.glm import mat4x4, vec3
import numpy as np

from gtools.core.growtopia.packet import NetPacket
from gtools.core.growtopia.world import Tile, World

from gtools.core.mixer import AudioMixer
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.object_renderer import ObjectRenderer
from gtools.gui.opengl import Framebuffer, Mesh, ShaderProgram
from gtools.gui.event import Event, ScrollEvent, MouseButtonEvent, CursorMoveEvent, KeyEvent, TouchEvent
from gtools.gui.panels.panel import Panel
from gtools.gui.lib.world_renderer import WorldRenderer

logger = logging.getLogger("gui-world-viewer")


class WorldTab(Panel):
    _UNIQUE = itertools.count()

    def __init__(self, dockspace_id: int, path: Path) -> None:
        super().__init__()

        pkt = NetPacket.deserialize(path.read_bytes())
        self._world = World.from_tank(pkt.tank)
        self._name = f"{self._world.name.decode()}##{next(WorldTab._UNIQUE)}"

        # TODO: need to cleanup shader globally
        self._dockspace_id = dockspace_id

        self._camera = Camera2D(800, 600)
        self._camera.fit_to_rect(0, 0, self._world.width * 32, self._world.height * 32)
        self._fbo = Framebuffer(800, 600)

        self._hovered = False
        self._drag: dict = {"active": False}
        self._image_origin: tuple[float, float] = (0.0, 0.0)
        self._cursor_pos: tuple[float, float] = (0.0, 0.0)
        self._last_touch_event = 0.0

        self._open = True
        self._first_render = True
        self._is_active = False

        self._mixer = AudioMixer()
        self._sheet = self._world.get_sheet(self._mixer)

        self._solid_shader = ShaderProgram.get("shaders/solid")
        self._solid_proj = self._solid_shader.get_uniform("u_proj")
        self._solid_model = self._solid_shader.get_uniform("u_model")
        # fmt: off
        playhead_vertices = np.array([
            -0.5, -0.5, 1.0, 1.0, 1.0, 0.2,
            0.5,  -0.5, 1.0, 1.0, 1.0, 0.2,
            0.5,  0.5,  1.0, 1.0, 1.0, 0.2,
            -0.5, 0.5,  1.0, 1.0, 1.0, 0.2,
        ], dtype=np.float32)
        # fmt: on
        self._playhead = Mesh(playhead_vertices, [2, 4], Mesh.RECT_INDICES)
        self._playing = True
        self._seek = 0

        # fmt: off
        hover_vertices = np.array([
            -0.5, -0.5, 1.0, 1.0, 1.0, 0.3,
            0.5,  -0.5, 1.0, 1.0, 1.0, 0.3,
            0.5,  0.5,  1.0, 1.0, 1.0, 0.3,
            -0.5, 0.5,  1.0, 1.0, 1.0, 0.3,
        ], dtype=np.float32)
        # fmt: on
        self._hover = Mesh(hover_vertices, [2, 4], Mesh.RECT_INDICES)
        self._hovered_tile: Tile | None = None

        self._mode_3d = False
        self._camera3d = Camera3D(800, 600)
        self._camera3d.fit_to_rect(self._world.width, self._world.height)
        self._layer_spread: float = 200.0

        # FPS movement key state
        self._keys_held: set[int] = set()

        self._world_renderer = WorldRenderer()
        self._world_renderer.load(self._world)
        self._object_renderer = ObjectRenderer()
        self._object_renderer.load(self._world)

    def delete(self) -> None:
        logger.info(f"deleting tab {self._name}")
        self._world_renderer.delete()
        self._object_renderer.delete()
        self._fbo.delete()
        self._mixer.stop()

    @property
    def is_open(self) -> bool:
        return bool(self._open)

    @property
    def is_active(self) -> bool:
        return self._is_active

    def update(self, dt: float) -> None:
        if self._playing:
            self._sheet.update(dt)

        if self._seek != 0:
            self._sheet.seek(self._seek)

        if self._mode_3d and self._is_active:
            fwd = 0.0
            rgt = 0.0
            vert = 0.0
            if glfw.KEY_W in self._keys_held:
                fwd += 1.0
            if glfw.KEY_S in self._keys_held:
                fwd -= 1.0
            if glfw.KEY_D in self._keys_held:
                rgt += 1.0
            if glfw.KEY_A in self._keys_held:
                rgt -= 1.0
            if glfw.KEY_LEFT_SHIFT in self._keys_held:
                vert -= 1.0
            if glfw.KEY_SPACE in self._keys_held:
                vert += 1.0

            boost = glfw.KEY_LEFT_CONTROL in self._keys_held or glfw.KEY_RIGHT_CONTROL in self._keys_held

            if fwd != 0.0 or rgt != 0.0 or vert != 0.0:
                self._camera3d.move(fwd, rgt, vert, dt, speed_mul=2 if boost else 1)

    def render(self) -> None:
        if self._first_render and self._dockspace_id:
            imgui.set_next_window_dock_id(self._dockspace_id)
            self._first_render = False

        opened, self._open = imgui.begin(self._name, self._open)
        self._is_active = imgui.is_window_focused(imgui.FocusedFlags_.child_windows)
        if opened:
            if self._hovered_tile:
                if self._hovered_tile.extra:
                    imgui.text(f"{self._hovered_tile.extra}")
                else:
                    imgui.text(f"-")
            else:
                imgui.text(f"-")

            _, self._sheet.bpm = imgui_knobs.knob("BPM", self._sheet.bpm, 20.0, 200.0, format="%.0f", size=24, variant=imgui_knobs.ImGuiKnobVariant_.wiper_only)

            imgui.same_line()
            _, self._playing = imgui.checkbox("Play Music", self._playing)

            FLAGS = [
                ("Render FG", WorldRenderer.Flags.RENDER_FG),
                ("Render BG", WorldRenderer.Flags.RENDER_BG),
            ]

            imgui.same_line()

            for i, (label, flag) in enumerate(FLAGS):
                if i != 0:
                    imgui.same_line()
                changed, is_set = imgui.checkbox(label, self._world_renderer.flags & flag != 0)
                if changed:
                    if is_set:
                        self._world_renderer.flags |= flag
                    else:
                        self._world_renderer.flags &= ~flag

            imgui.same_line()
            _, self._mode_3d = imgui.checkbox("3D", self._mode_3d)

            if self._mode_3d:
                imgui.same_line()
                imgui.set_next_item_width(120)
                _, self._layer_spread = imgui.slider_float("Layer Spread", self._layer_spread, 10.0, 1000.0)
                imgui.same_line()
                imgui.text(f"Speed: {self._camera3d.speed:.0f}")

            cw, ch = imgui.get_content_region_avail()
            cw, ch = int(cw), int(ch)
            if cw > 0 and ch > 0:
                self._fbo.resize(cw, ch)
                self._camera.resize(cw, ch)
                self._camera3d.resize(cw, ch)
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
        if isinstance(event, KeyEvent):
            if event.action == glfw.PRESS:
                if event.key == glfw.KEY_3:
                    self._mode_3d = not self._mode_3d
                if event.key == glfw.KEY_0:
                    self._world_renderer.flags |= WorldRenderer.Flags.RENDER_FG | WorldRenderer.Flags.RENDER_BG
                elif event.key == glfw.KEY_1:
                    self._world_renderer.flags ^= WorldRenderer.Flags.RENDER_FG
                elif event.key == glfw.KEY_2:
                    self._world_renderer.flags ^= WorldRenderer.Flags.RENDER_BG
                elif event.key == glfw.KEY_LEFT:
                    self._seek = -1
                elif event.key == glfw.KEY_RIGHT:
                    self._seek = 1
                elif event.key == glfw.KEY_COMMA:
                    self._sheet.seek(-1, play=True)
                elif event.key == glfw.KEY_PERIOD:
                    self._sheet.seek(1, play=True)
            elif event.action == glfw.RELEASE:
                if event.key == glfw.KEY_LEFT:
                    self._seek = 0
                elif event.key == glfw.KEY_RIGHT:
                    self._seek = 0

        if self._mode_3d:
            return self._handle_event_3d(event)
        return self._handle_event_2d(event)

    def _handle_event_3d(self, event: Event) -> bool:
        if isinstance(event, ScrollEvent):
            if self._hovered:
                self._camera3d.speed *= 1.1**event.yoff
                self._camera3d.speed = max(50.0, min(self._camera3d.speed, 10000.0))
                return True
        elif isinstance(event, MouseButtonEvent):
            if event.button == glfw.MOUSE_BUTTON_LEFT or event.button == glfw.MOUSE_BUTTON_RIGHT:
                if event.action == glfw.PRESS and self._hovered:
                    lx, ly = self._to_local(event.screen_x, event.screen_y)
                    self._drag = {
                        "active": True,
                        "last_screen": (lx, ly),
                    }
                    return True
                elif event.action == glfw.RELEASE and self._drag.get("active"):
                    self._drag["active"] = False
                    return True
        elif isinstance(event, CursorMoveEvent):
            self._cursor_pos = (event.xpos, event.ypos)
            if self._drag.get("active"):
                lx, ly = self._to_local(event.xpos, event.ypos)
                prev = self._drag["last_screen"]
                dx = lx - prev[0]
                dy = ly - prev[1]
                self._drag["last_screen"] = (lx, ly)
                self._camera3d.look(dx, dy)
                return True
        elif isinstance(event, KeyEvent):
            if self._is_active:
                if event.action == glfw.PRESS:
                    self._keys_held.add(event.key)
                    if event.key == glfw.KEY_R:
                        self._camera3d.fit_to_rect(self._world.width * 32, self._world.height * 32)
                        return True
                elif event.action == glfw.RELEASE:
                    self._keys_held.discard(event.key)
        elif isinstance(event, TouchEvent):
            if self._hovered:
                self._last_touch_event = time.monotonic()
                self._camera3d.look(event.dx, event.dy)
                return True
        return False

    def _handle_event_2d(self, event: Event) -> bool:
        if isinstance(event, ScrollEvent):
            if self._hovered and time.monotonic() - self._last_touch_event >= 0.5:
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
            if event.button == glfw.MOUSE_BUTTON_RIGHT:
                if event.action == glfw.PRESS:
                    self._playing = not self._playing
        elif isinstance(event, CursorMoveEvent):
            self._cursor_pos = (event.xpos, event.ypos)
            if self._drag.get("active"):
                lx, ly = self._to_local(event.xpos, event.ypos)
                dx = lx - self._drag["start_screen"][0]
                dy = ly - self._drag["start_screen"][1]
                self._camera.pos.x = self._drag["start_cam"].x - dx / self._camera.zoom
                self._camera.pos.y = self._drag["start_cam"].y - dy / self._camera.zoom
                return True
        elif isinstance(event, KeyEvent):
            if self._is_active:
                if event.action == glfw.PRESS:
                    if self._hovered and event.key == glfw.KEY_R:
                        self._camera.fit_to_rect(0, 0, self._world.width * 32, self._world.height * 32)
                        return True
                    elif event.key == glfw.KEY_SPACE:
                        self._playing = not self._playing
        elif isinstance(event, TouchEvent):
            if self._hovered:
                self._last_touch_event = time.monotonic()
                self._camera.pos.x -= event.dx / self._camera.zoom
                self._camera.pos.y -= event.dy / self._camera.zoom

                lx, ly = self._to_local(self._cursor_pos[0], self._cursor_pos[1])
                self._camera.zoom_around(event.scale_factor, lx, ly)

                return True
        return False

    def _to_local(self, sx: float, sy: float) -> tuple[float, float]:
        ox, oy = self._image_origin
        return sx - ox, sy - oy

    def _render_to_fbo(self) -> None:
        self._fbo.bind()

        glClearColor(0.08, 0.08, 0.08, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)  # pyright: ignore[reportOperatorIssue]

        if self._mode_3d:
            self._render_to_fbo_3d()
        else:
            self._render_to_fbo_2d()

        self._fbo.unbind()

    def _render_to_fbo_3d(self) -> None:
        self._world_renderer.draw_3d(self._camera3d, self._layer_spread)
        self._object_renderer.draw_3d(self._camera3d, self._layer_spread)

    def _render_to_fbo_2d(self) -> None:
        self._world_renderer.draw(self._camera)
        self._object_renderer.draw(self._camera)

        self._solid_shader.use()
        self._solid_proj.set_mat4x4(self._camera.proj_as_numpy())

        if self._sheet.any:
            model = mat4x4(1.0)
            playhead = self._sheet.playhead - 1
            width = 32.0
            height = 14.0 * 32.0
            model = glm.translate(
                model,
                vec3(
                    (playhead % self._world.width) * 32 - 16 + width / 2,
                    (playhead // self._world.width) * 14 * 32 - 16 + height / 2,
                    0.0,
                ),
            )
            model = glm.scale(model, vec3(width, height, 1.0))

            self._solid_model.set_mat4x4(glm.value_ptr(model))
            self._playhead.draw()

        local = self._to_local(self._cursor_pos[0], self._cursor_pos[1])
        world = self._camera.screen_to_world(local[0], local[1])

        tile_x = math.floor((world.x + 16) / 32)
        tile_y = math.floor((world.y + 16) / 32)
        if 0 < tile_x < self._world.width and 0 < tile_y < self._world.height:
            self._hovered_tile = self._world.get_tile(tile_x, tile_y)
        else:
            self._hovered_tile = None

        model = mat4x4(1.0)
        model = glm.translate(model, vec3(tile_x * 32, tile_y * 32, 0.0))
        model = glm.scale(model, vec3(32.0, 32.0, 1.0))
        self._solid_model.set_mat4x4(glm.value_ptr(model))

        self._hover.draw()
