import logging
from pathlib import Path
from sys import argv
import time

import glfw
from OpenGL.GL import (
    GL_BLEND,
    GL_COLOR_BUFFER_BIT,
    GL_ONE_MINUS_SRC_ALPHA,
    GL_SRC_ALPHA,
    glBlendFunc,
    glClear,
    glClearColor,
    glEnable,
    glViewport,
)
from imgui_bundle import imgui
from imgui_bundle.python_backends.glfw_backend import GlfwRenderer

from gtools.core.highres_sleep import nanosleep
from gtools.core.log import setup_logger
from gtools.core.wsl import windows_home
from gtools.gui.event import Event, EventRouter, ResizeEvent
from gtools.gui.panels.panel import DockspacePanel, Panel
from gtools.gui.panels.world_viewer import WorldViewerPanel

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
        self.world_viewer = WorldViewerPanel(self.dockspace.node_id)
        self.panels: list[Panel] = [self.dockspace, self.world_viewer]

        if world_path:
            logger.debug(f"app pre-loading world {world_path}")
            self.world_viewer.open_world(world_path)

        self.fps = 60

    def run(self) -> None:
        logger.info("starting App.run main loop")
        frame_count = 0
        while not glfw.window_should_close(self.window):
            frame_start = time.perf_counter()

            glfw.poll_events()
            
            # Periodically verify window procedure is still installed
            frame_count += 1
            if frame_count % 300 == 0:  # Every 5 seconds at 60fps
                if not self.event_router._finger.verify_wndproc():
                    logger.warning("Window procedure was overwritten! Attempting to reinstall...")
                    # Note: Reinstallation would require recreating the FingerRouter
            
            self.imgui_renderer.process_inputs()
            imgui.new_frame()

            for event in self.event_router.poll():
                self.process_events(event)

            glClearColor(0.1, 0.1, 0.1, 1.0)
            glClear(GL_COLOR_BUFFER_BIT)

            for panel in self.panels:
                panel.render()

            imgui.render()
            self.imgui_renderer.render(imgui.get_draw_data())
            glfw.swap_buffers(self.window)

            elapsed = time.perf_counter() - frame_start
            sleep_time = 1 / self.fps - elapsed - 0.002
            if sleep_time > 0:
                nanosleep(sleep_time * 1e9)

        self.shutdown()

    def process_events(self, e: Event) -> None:
        if isinstance(e, ResizeEvent):
            glViewport(0, 0, e.width, e.height)
            return

        for panel in self.panels:
            if panel.handle_event(e):
                break

    def init_glfw(self, width: int, height: int) -> None:
        logger.debug(f"initializing GLFW with width={width}, height={height}")
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
