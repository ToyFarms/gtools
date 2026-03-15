import logging
from pathlib import Path
from sys import argv
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

from gtools import setting
from gtools.core import ndialog
from gtools.core.highres_sleep import nanosleep
from gtools.core.log import setup_logger
from gtools.core.wsl import windows_home
from gtools.gui.event import Event, EventRouter, KeyEvent, ResizeEvent
from gtools.gui.panels.panel import DockspacePanel, Panel
from gtools.gui.panels.proxy_interface import ProxyPanel
from gtools.gui.panels.world_viewer import WorldTab
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

        self.imgui_renderer = GlfwRenderer(self.window)
        self.event_router = EventRouter(self.window)

        self.dockspace = DockspacePanel()
        self.panels: list[Panel] = [self.dockspace, ProxyPanel(self.dockspace.node_id)]

        self._cmd = CommandPalette()
        self._cmd_builder = self._setup_cmd_palette()

        if world_path:
            logger.debug(f"app pre-loading world {world_path}")
            self.add_panel(WorldTab(self.dockspace.node_id, world_path))

        self.fps = 60
        self.prev = time.perf_counter()
        self.worlds: list[Path] = []

    def _setup_cmd_palette(self) -> PaletteBuilder:
        root = PaletteBuilder("Command palette")

        @root.cmd("Open World")
        def _() -> None:
            world = ndialog.open_file("Open World", history_path=setting.appdir / "ndialog.json")
            if isinstance(world, str):
                self.add_panel(WorldTab(self.dockspace.node_id, Path(world)))

        @root.submenu("Search World")
        def _(sub: PaletteBuilder) -> None:
            self.worlds = [x for x in (windows_home() / ".gtools/worlds").glob("*")]
            for world in self.worlds:

                @sub.cmd(world.name)
                def _(p=world) -> None:
                    self.add_panel(WorldTab(self.dockspace.node_id, p))

        return root

    def add_panel(self, panel: Panel) -> None:
        self.panels.append(panel)

    def remove_panel(self, panel: Panel) -> None:
        panel.delete()
        self.panels.remove(panel)

    def run(self) -> None:
        logger.info("starting App.run main loop")
        while not glfw.window_should_close(self.window):
            frame_start = time.perf_counter()

            now = time.perf_counter()
            dt = now - self.prev
            self.prev = now

            any_dirty = any(p.is_dirty for p in self.panels)
            if not any_dirty and not self._cmd.is_open:
                glfw.wait_events_timeout(0.1)
            else:
                glfw.poll_events()

            self.imgui_renderer.process_inputs()
            imgui.new_frame()

            for event in self.event_router.poll():
                self.process_events(event)

            glClearColor(0.1, 0.1, 0.1, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)  # pyright: ignore[reportOperatorIssue]

            to_remove: list[Panel] = []
            for panel in self.panels:
                if not panel.is_open:
                    to_remove.append(panel)

                panel.update(dt)
                panel.render()

            for panel in to_remove:
                self.remove_panel(panel)

            self._cmd.render()

            imgui.render()
            self.imgui_renderer.render(imgui.get_draw_data())
            glfw.swap_buffers(self.window)

            elapsed = time.perf_counter() - frame_start
            sleep_time = 1 / self.fps - elapsed - 0.002
            if sleep_time > 0:
                nanosleep(sleep_time * 1e9)

        self.shutdown()

    def process_events(self, e: Event) -> None:
        if isinstance(e, KeyEvent):
            if e.action == glfw.PRESS:
                if e.key == glfw.KEY_P and e.mods & glfw.MOD_CONTROL:
                    self._cmd.open(self._cmd_builder.build())
        elif isinstance(e, ResizeEvent):
            glViewport(0, 0, e.width, e.height)
            return

        for panel in reversed(self.panels):
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

        glEnable(GL_DEPTH_TEST);
        glDepthFunc(GL_LESS);
        glDepthMask(GL_TRUE);

    def shutdown(self) -> None:
        self.event_router.delete()
        logger.info("shutting down App")
        for panel in self.panels:
            panel.delete()

        self.imgui_renderer.shutdown()
        glfw.terminate()


def main() -> None:
    path: Path | None = None
    if len(argv) > 1:
        path = windows_home() / ".gtools/worlds" / argv[1]
    App(world_path=path).run()


if __name__ == "__main__":
    setup_logger(level=logging.DEBUG)
    main()
