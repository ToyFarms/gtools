import OpenGL
from gtools import setting
from gtools.gui.lib import perf_stats
from gtools.gui.lib.toast import ToastManager

OpenGL.ERROR_CHECKING = setting.opengl_error_checking

import logging
import math
from pathlib import Path
from sys import argv
import threading
import time

import glfw
from OpenGL.GL import (
    GL_BLEND,
    GL_COLOR_BUFFER_BIT,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_TEST,
    GL_LESS,
    GL_ONE,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_TRUE,
    glBlendFunc,
    glClear,
    glClearColor,
    glDepthFunc,
    glDepthMask,
    glEnable,
    glViewport,
)
from imgui_bundle import imgui
from imgui_bundle.python_backends.glfw_backend import GlfwRenderer
from pyglm.glm import ivec2, vec2

from gtools.baked.items import SIGN
from gtools.core import ndialog
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.world import SignTile, Tile, TileFlags, World
from gtools.core.highres_sleep import nanosleep
from gtools.core.log import setup_logger
from gtools.core.wsl import windows_home
from gtools.gui.event import Event, EventRouter, KeyEvent, ResizeEvent
from gtools.gui.opengl import ShaderProgram
from gtools.gui.texture import GLTexManager
from gtools.gui.panels.panel import DockspacePanel, Panel
from gtools.gui.panels.proxy_panel import ProxyPanel
from gtools.gui.panels.world_panel import WorldPanel
from gtools.gui.panels.perf_overlay_panel import PerfOverlayPanel
from gtools.gui.lib.perf_stats import PerfStats
from gtools.gui.widgets.command_palette import CommandPalette, PaletteBuilder

logger = logging.getLogger("gui")


class App:
    def __init__(self, world_path: Path | None = None, width: int = 800, height: int = 600) -> None:
        logger.info(f"initializing App with world_path={world_path}, width={width}, height={height}")
        self.init_glfw(width, height)

        imgui.create_context()
        io = imgui.get_io()
        io.config_windows_move_from_title_bar_only = True
        io.config_flags |= imgui.ConfigFlags_.docking_enable

        self.toast_mgr = ToastManager.get()

        self.imgui_renderer = GlfwRenderer(self.window)
        self.event_router = EventRouter(self.window)

        self.dockspace = DockspacePanel()
        self.perf_stats = PerfStats()
        self.panels: list[Panel] = [
            self.dockspace,
            ProxyPanel(self.dockspace.node_id),
            PerfOverlayPanel(self.perf_stats),
        ]

        self._panels_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._last_update_ms: float = 0.0

        self._cmd = CommandPalette()
        self._cmd_builder = self._setup_cmd_palette()

        if world_path:
            logger.debug(f"app pre-loading world {world_path}")
            self.add_panel(WorldPanel.load(world_path, self.dockspace.node_id))

        self.fps = 60
        self.update_fps = 60
        self.idle_fps = 10
        self.idle_transition = 5

        self.prev = time.perf_counter()
        self.last_dirty_time: float = time.perf_counter()
        self.worlds: list[Path] = []

        self._update_thread = threading.Thread(target=self._update_loop, name="update", daemon=True)
        self._update_thread.start()

    def _update_loop(self) -> None:
        logger.info("update thread started")
        prev = time.perf_counter()

        while not self._stop_event.is_set():
            loop_start = time.perf_counter()
            now = loop_start
            dt = now - prev
            prev = now

            with self._panels_lock:
                for panel in self.panels:
                    panel.update(dt)

            self.toast_mgr.update(dt)

            elapsed = time.perf_counter() - loop_start
            self._last_update_ms = elapsed * 1000.0

            sleep_time = 1 / self.update_fps - elapsed - 0.002
            if sleep_time > 0:
                nanosleep(sleep_time * 1e9)

        logger.info("update thread exiting")

    def _setup_cmd_palette(self) -> PaletteBuilder:
        root = PaletteBuilder("Command palette")

        @root.cmd("Open World")
        def _() -> None:
            world = ndialog.open_file("Open World", history_path=setting.appdir / "ndialog.json")
            if isinstance(world, str):
                self.add_panel(WorldPanel.load(Path(world), self.dockspace.node_id))

        @root.submenu("Search World")
        def _(sub: PaletteBuilder) -> None:
            self.worlds = [x for x in (setting.appdir / "worlds").glob("*")]
            for world in self.worlds:

                @sub.cmd(world.name)
                def _(p=world) -> None:
                    self.add_panel(WorldPanel.load(p, self.dockspace.node_id))

        @root.cmd("Debug World")
        def _() -> None:
            self._add_debug_world()

        return root

    def _add_debug_world(self) -> None:
        size = math.ceil(math.sqrt(item_database.item_count))
        w = World(name=b"Debug World", width=size, height=size)

        for item in item_database.items.values():
            x = item.id % w.width * 32
            y = item.id // w.width * 32
            w.tiles[item.id] = Tile(
                fg_id=SIGN,
                pos=ivec2(x / 32, y / 32),
                extra=SignTile(text=f"{item.name.decode()} ({item.id})".encode()),
                flags=TileFlags.PAINTED_RED | TileFlags.PAINTED_GREEN | TileFlags.PAINTED_BLUE,
            )

            w.create_dropped(item.id, vec2(x + 8, y + 8), 1, 0)

        w.fix()
        self.add_panel(WorldPanel(w, self.dockspace.node_id))

    def add_panel(self, panel: Panel) -> None:
        with self._panels_lock:
            if panel.dock_id == 0:
                panel.dock_id = self.dockspace.node_id
            self.panels.append(panel)

    def remove_panel(self, panel: Panel) -> None:
        with self._panels_lock:
            panel.delete()
            self.panels.remove(panel)

    def run(self) -> None:
        logger.info("starting App.run render loop")
        while not glfw.window_should_close(self.window):
            frame_start = time.perf_counter()

            with self._panels_lock:
                any_dirty = any(p.is_dirty for p in self.panels)

            if any_dirty:
                self.last_dirty_time = time.perf_counter()

            time_since_dirty = time.perf_counter() - self.last_dirty_time
            self.perf_stats.idle_timer = self.idle_transition - time_since_dirty
            idle = time_since_dirty > self.idle_transition

            event_start = time.perf_counter()
            if idle:
                glfw.wait_events_timeout(1.0 / self.idle_fps)
            else:
                glfw.poll_events()
            event_time_ms = (time.perf_counter() - event_start) * 1000.0

            self.imgui_renderer.process_inputs()
            imgui.new_frame()

            for event in self.event_router.poll():
                self.process_events(event)

            glClearColor(0.1, 0.1, 0.1, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)  # pyright: ignore[reportOperatorIssue]

            to_remove: list[Panel] = []
            panel_perf: dict[str, float] = {}

            panel_render_start = time.perf_counter()
            with self._panels_lock:
                for panel in self.panels:
                    if not panel.is_open:
                        to_remove.append(panel)

                    if panel.dock_id == 0:
                        panel.dock_id = self.dockspace.node_id

                    panel.render()
                    panel.get_perf(panel_perf)
            panel_render_ms = (time.perf_counter() - panel_render_start) * 1000.0

            for panel in to_remove:
                self.remove_panel(panel)

            if any_dirty:
                with self._panels_lock:
                    for panel in self.panels:
                        panel.is_dirty = False

            self._cmd.render()
            self.toast_mgr.render()

            imgui.render()

            drawlist_start = time.perf_counter()
            self.imgui_renderer.render(imgui.get_draw_data())
            drawlist_ms = (time.perf_counter() - drawlist_start) * 1000.0

            glfw.swap_buffers(self.window)

            elapsed = time.perf_counter() - frame_start
            frame_ms = elapsed * 1000.0

            self.perf_stats.record_frame(
                frame=frame_ms,
                events=event_time_ms,
                panel_update=self._last_update_ms,
                panel_render=panel_render_ms,
                drawlist=drawlist_ms,
                **panel_perf,
            )
            self.perf_stats.idle = idle

            target_fps = self.idle_fps if idle else self.fps
            sleep_time = 1 / target_fps - elapsed - 0.002
            if sleep_time > 0:
                nanosleep(sleep_time * 1e9)

        self.shutdown()

    def process_events(self, e: Event) -> None:
        if isinstance(e, KeyEvent):
            if e.action == glfw.PRESS:
                if e.key == glfw.KEY_P and e.mods & glfw.MOD_CONTROL:
                    self._cmd.open(self._cmd_builder.build())
                elif e.key == glfw.KEY_F3:
                    perf_stats.SHOW_DEBUG_OVERLAY = not perf_stats.SHOW_DEBUG_OVERLAY
        elif isinstance(e, ResizeEvent):
            glViewport(0, 0, e.width, e.height)
            return

        with self._panels_lock:
            panels_snapshot = list(self.panels)

        for panel in reversed(panels_snapshot):
            if panel.handle_event(e):
                break

    def init_glfw(self, width: int, height: int) -> None:
        logger.debug(f"initializing GLFW with width={width}, height={height}")
        if not glfw.init():
            raise RuntimeError("failed to initialise GLFW.")

        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 4)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 5)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        self.window = glfw.create_window(width, height, "gtools gui (ctrl+p command palette)", None, None)
        if not self.window:
            glfw.terminate()
            raise RuntimeError("failed to create GLFW window.")

        glfw.make_context_current(self.window)
        glfw.swap_interval(1)
        glViewport(0, 0, width, height)
        glEnable(GL_BLEND)
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)

        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)
        glDepthMask(GL_TRUE)

    def shutdown(self) -> None:
        logger.info("shutting down App")
        self._stop_event.set()
        self._update_thread.join(timeout=2.0)

        self.event_router.delete()
        with self._panels_lock:
            for panel in self.panels:
                panel.delete()

        GLTexManager().delete_all()
        ShaderProgram.delete_all()

        self.imgui_renderer.shutdown()
        glfw.terminate()


def main() -> None:
    path: Path | None = None
    if len(argv) > 1:
        path = setting.appdir / "worlds" / argv[1]
    App(world_path=path).run()


if __name__ == "__main__":
    setup_logger(level=logging.DEBUG)
    main()
