import itertools
import logging
from pathlib import Path
from OpenGL.GL import GL_COLOR_BUFFER_BIT, glClear, glClearColor

import glfw
from imgui_bundle import imgui
from pyglm import glm

from gtools import setting
from gtools.core import ndialog
from gtools.core.growtopia.packet import NetPacket
from gtools.core.growtopia.world import World

from gtools.gui.camera import Camera2D
from gtools.gui.opengl import Framebuffer, ShaderProgram, Uniform
from gtools.gui.event import Event, FingerDragEvent, FingerPinchEvent, ScrollEvent, MouseButtonEvent, CursorMoveEvent, KeyEvent
from gtools.gui.panels.panel import Panel
from gtools.gui.lib.world_renderer import WorldRenderer

logger = logging.getLogger("gui-world-viewer")


class WorldTab:
    _WORLD_TAB_COUNTER = itertools.count(1)

    def __init__(
        self,
        shader: ShaderProgram,
        mvp: Uniform,
        tex: Uniform,
        dockspace_id: int,
        path: Path,
    ) -> None:
        logger.info(f"creating WorldTab for {path}")
        self._name = f"{path.stem}##{next(self._WORLD_TAB_COUNTER)}"
        self._shader = shader
        self._mvp = mvp
        self._tex = tex
        self._dockspace_id = dockspace_id

        self._camera = Camera2D(800, 600)
        self._fbo = Framebuffer(800, 600)
        self._renderer = WorldRenderer()

        self._hovered = False
        self._drag: dict = {"active": False}
        self._image_origin: tuple[float, float] = (0.0, 0.0)

        self._open = True
        self._first_render = True

        pkt = NetPacket.deserialize(path.read_bytes())
        self._renderer.load(World.from_tank(pkt.tank))

    def delete(self) -> None:
        logger.info(f"deleting tab {self._name}")
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
            if event.action == glfw.PRESS:
                if self._hovered and event.key == glfw.KEY_R:
                    self._camera.reset()
                    return True
                if event.key == glfw.KEY_1:
                    self._renderer.flags |= WorldRenderer.Flags.RENDER_FG | WorldRenderer.Flags.RENDER_BG
                elif event.key == glfw.KEY_2:
                    self._renderer.flags ^= WorldRenderer.Flags.RENDER_FG
                elif event.key == glfw.KEY_3:
                    self._renderer.flags ^= WorldRenderer.Flags.RENDER_BG
        elif isinstance(event, FingerDragEvent):
            if self._hovered:
                self._camera.pos.x -= event.dx / self._camera.zoom
                self._camera.pos.y -= event.dy / self._camera.zoom
                return True
        elif isinstance(event, FingerPinchEvent):
            if self._hovered:
                lx, ly = self._to_local(event.x, event.y)
                self._camera.zoom_around(event.scale, lx, ly)
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
            self._mvp.set_mat4x4(self._camera.proj_as_numpy())
            self._renderer.draw(self._tex)
        self._fbo.unbind()


class WorldViewerPanel(Panel):
    def __init__(self, outer_dockspace_id: int) -> None:
        super().__init__()
        logger.debug(f"initializing WorldViewerPanel with outer_dockspace_id={outer_dockspace_id}")
        self._shader = ShaderProgram.from_file("shaders/world")
        self._mvp = self._shader.get_uniform("u_mvp")
        self._tex = self._shader.get_uniform("texArray")
        self._outer_dockspace_id = outer_dockspace_id

        self._inner_dockspace_id: int = 0
        self._inner_dockspace_key = "WorldViewerDock"
        self._tabs: list[WorldTab] = []

        self._open = True
        self._first_render = True

    @property
    def is_open(self) -> bool:
        return self._open

    def delete(self) -> None:
        logger.info("deleting WorldViewerPanel and its tabs")
        for tab in self._tabs:
            tab.delete()
        self._tabs = []
        self._shader.delete()

    def open_world(self, path: Path) -> None:
        logger.info(f"worldViewerPanel opening world: {path}")
        self._tabs.append(WorldTab(self._shader, self._mvp, self._tex, self._inner_dockspace_id, path))

    def render_debug(self) -> None:
        if imgui.button("Open World", (-1, 0)):
            world = ndialog.open_file("Open World", history_path=setting.appdir / "ndialog.json")
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
