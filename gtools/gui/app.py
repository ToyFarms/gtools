import OpenGL
from gtools import setting
from gtools.gui.lib import perf_stats
from gtools.gui.lib.pie import Hold, PieMenu
from gtools.gui.lib.toast import ToastManager, push_debug, push_error
from gtools.gui.panels.midi_workspace import MidiWorkspace

OpenGL.ERROR_CHECKING = setting.opengl_error_checking

from collections import deque
import logging
import math
from pathlib import Path
from sys import argv
import threading
import time
from typing import Any, Callable

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
from imgui_bundle import ImVec2, ImVec4, imgui
from imgui_bundle.python_backends.glfw_backend import GlfwRenderer
from pyglm.glm import ivec2, vec2

from gtools.baked.items import SIGN
from gtools.core import ndialog
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.world import SignTile, Tile, TileFlags, World
from gtools.core.highres_sleep import nanosleep
from gtools.core.log import setup_logger
from gtools.gui.event import Event, EventRouter, KeyEvent, ResizeEvent
from gtools.gui.opengl import ShaderProgram
from gtools.gui.texture import GLTexManager
from gtools.gui.overlay import OverlayController
from gtools.gui.panels.panel import DockspacePanel, Panel
from gtools.gui.panels.proxy_panel import ProxyPanel
from gtools.gui.panels.hook_panel import HookPanel
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
            HookPanel(self.dockspace.node_id),
            PerfOverlayPanel(self.perf_stats),
        ]

        self.overlay = OverlayController(gui_title="gtools gui (ctrl+p command palette)")
        self.overlay.set_glfw_window(self.window)

        self._panels_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._last_update_ms: float = 0.0

        self.pie = self._create_pie_menu()
        self._pie_actions: deque[Callable[[], None]] = deque()
        self._pie_trigger_down = False

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

            trigger_down = self.pie is not None and self.pie.enabled and self.pie.trigger.is_down()
            if trigger_down != self._pie_trigger_down:
                glfw.post_empty_event()

            self._pie_trigger_down = trigger_down

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
            self._open_world_dialog()

        @root.submenu("Search World")
        def _(sub: PaletteBuilder) -> None:
            self.worlds = self._world_paths()
            for world in self.worlds:

                @sub.cmd(world.name)
                def _(p=world) -> None:
                    self._open_world(p)

        @root.cmd("Debug World")
        def _() -> None:
            self._add_debug_world()

        @root.cmd("Midi Workspace")
        def _() -> None:
            self.add_panel(MidiWorkspace(self.dockspace.node_id))

        @root.cmd("Pie Menu", keybind="hold Ctrl", description="radial command menu")
        def _() -> None:
            if self.pie is not None:
                self.pie.open()

        @root.cmd(lambda: "Dev Mode: Turn Off" if Panel.dev_mode else "Dev Mode: Turn On")
        def _() -> None:
            Panel.dev_mode = not Panel.dev_mode

        return root

    def _create_pie_menu(self) -> PieMenu:
        menu = PieMenu(trigger=Hold("ctrl"), processes=["Growtopia.exe"], main_window=self.window)
        self._build_pie_menu(menu)

        return menu

    def _pie_action(self, action: Callable[[], None]) -> None:
        self._pie_actions.append(action)

    def _flush_pie_actions(self) -> None:
        while self._pie_actions:
            action = self._pie_actions.popleft()
            try:
                action()
            except Exception:
                logger.exception("pie action failed")

    def _build_pie_menu(self, menu: Any) -> None:
        from gtools.gui.lib.pie import Panel as PiePanel

        menu.button("Open World", lambda: self._pie_action(self._open_world_dialog), icon="O")

        worlds = menu.submenu("Worlds", icon="W")
        worlds.button("Open World...", lambda: self._pie_action(self._open_world_dialog), icon="+")

        recent: list[str] | None = None

        def refresh_worlds() -> None:
            nonlocal recent
            paths = self._world_paths()[:10]
            names = [p.name for p in paths]
            if names == recent:
                return
            recent = names
            del worlds.children[1:]
            for path in paths:
                worlds.button(path.name, lambda p=path: self._pie_action(lambda: self._open_world(p)))
            worlds.button("Debug World", lambda: self._pie_action(self._add_debug_world), icon="*")

        worlds.on_hover = refresh_worlds
        refresh_worlds()

        search: dict[str, Any] = {"query": "", "panel": None}

        def search_rows() -> list[str]:
            q = search["query"].lower()
            return [p.name for p in self._world_paths() if q in p.name.lower()][:14]

        def on_search_change(text: str) -> None:
            search["query"] = text
            panel = search["panel"]
            if text and (panel is None or not panel.open):
                search["panel"] = menu.show_panel(
                    PiePanel.list("Worlds", search_rows, on_pick=lambda name: self._pie_action(lambda: self._open_world_by_name(name)), size=(320, 320))
                )
            elif not text and panel is not None:
                panel.close()

        def on_search_submit(text: str) -> None:
            rows = search_rows()
            if rows:
                name = rows[0]
                self._pie_action(lambda: self._open_world_by_name(name))
            if search["panel"] is not None:
                search["panel"].close()

        menu.text_input("Search", on_submit=on_search_submit, on_change=on_search_change, placeholder="Search worlds...")

        panels = menu.submenu("Panels", icon="P")
        panels.button("Proxy", lambda: self._pie_action(lambda: self.add_panel(ProxyPanel(self.dockspace.node_id))), icon="X")
        panels.button("Hook", lambda: self._pie_action(lambda: self.add_panel(HookPanel(self.dockspace.node_id))), icon="K")
        panels.button("Midi Workspace", lambda: self._pie_action(lambda: self.add_panel(MidiWorkspace(self.dockspace.node_id))), icon="M")

        menu.button("Toggle Dev Mode", lambda: self._pie_action(self._toggle_dev_mode), icon="!")
        menu.button("Dock Overlay", lambda: self._pie_action(self._toggle_dock), icon="D")
        menu.button("Hide GUI", lambda: self._pie_action(self.overlay.toggle_hidden), icon="H")

    def _world_paths(self) -> list[Path]:
        try:
            return sorted((p for p in (setting.appdir / "worlds").glob("*") if p.is_file()), key=lambda p: p.name.lower())
        except OSError:
            return []

    def _open_world_dialog(self) -> None:
        world = ndialog.open_file("Open World", history_path=setting.appdir / "ndialog.json")
        if isinstance(world, str):
            self._open_world(Path(world))

    def _open_world(self, path: Path) -> None:
        self.add_panel(WorldPanel.load(path, self.dockspace.node_id))

    def _open_world_by_name(self, name: str) -> None:
        self._open_world(setting.appdir / "worlds" / name)

    def _toggle_dev_mode(self) -> None:
        Panel.dev_mode = not Panel.dev_mode

    def _render_menu_bar(self) -> None:
        if not imgui.begin_main_menu_bar():
            return

        if imgui.begin_menu("View"):

            if self.pie is not None:
                if imgui.menu_item("Pie Menu", "hold Ctrl", False)[0]:
                    self.pie.open()
                imgui.separator()

            if imgui.menu_item("Midi Workspace", "", False)[0]:
                self.add_panel(MidiWorkspace(self.dockspace.node_id))

            if imgui.menu_item("Proxy", "", False)[0]:
                self.add_panel(ProxyPanel(self.dockspace.node_id))

            if imgui.menu_item("Hook", "", False)[0]:
                self.add_panel(HookPanel(self.dockspace.node_id))

            imgui.separator()

            if imgui.menu_item("Open World", "", False)[0]:
                self._open_world_dialog()

            if imgui.begin_menu("Open Recent World"):
                self.worlds = self._world_paths()
                if self.worlds:
                    for p in self.worlds:
                        if imgui.menu_item(p.name, "", False)[0]:
                            self._open_world(p)
                else:
                    imgui.begin_disabled()
                    imgui.menu_item("(none)", "", False)
                    imgui.end_disabled()
                imgui.end_menu()

            if imgui.menu_item("Debug World", "", False)[0]:
                self._add_debug_world()

            imgui.separator()

            label = "Dev Mode: Turn Off" if Panel.dev_mode else "Dev Mode: Turn On"
            if imgui.menu_item(label, "", False)[0]:
                self._toggle_dev_mode()

            imgui.end_menu()

        imgui.end_main_menu_bar()

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

    def _toggle_dock(self) -> None:
        if self.overlay.docked:
            self.overlay.undock()
            return

        game_pid = 0
        for panel in self.panels:
            if isinstance(panel, HookPanel) and panel._model.snapshot.connected:
                game_pid = panel._model.snapshot.pid
                break

        if not self.overlay.dock(game_pid or None):
            push_error("Overlay", "cannot find the Growtopia window", "launch the game first")

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

            pie_busy = self.pie is not None and self.pie.busy
            with self._panels_lock:
                any_dirty = any(p.is_dirty for p in self.panels) or self._cmd.is_dirty() or self.toast_mgr.is_dirty() or pie_busy

            if Panel.panels_to_add:
                while Panel.panels_to_add:
                    panel = Panel.panels_to_add.pop()
                    self.add_panel(panel(self.dockspace.node_id))
                    any_dirty = True

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

            io = imgui.get_io()
            _md = io.mouse_delta
            imgui_active = (
                _md.x != 0.0 or _md.y != 0.0 or any(io.mouse_down) or io.mouse_wheel != 0.0 or io.want_capture_keyboard or imgui.is_any_item_hovered() or imgui.is_any_item_active()
            )
            if imgui_active:
                self.last_dirty_time = time.perf_counter()

            for event in self.event_router.poll():
                self.process_events(event)

            glClearColor(0.1, 0.1, 0.1, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)  # pyright: ignore[reportOperatorIssue]

            to_remove: list[Panel] = []
            panel_perf: dict[str, float] = {}

            self._render_menu_bar()

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
                self._cmd.clear_dirty()
                self.toast_mgr.clear_dirty()

            self._cmd.render()
            self.toast_mgr.render()

            if Panel.dev_mode:
                drawlist = imgui.get_foreground_draw_list()
                drawlist.add_text(ImVec2(0, 0), imgui.get_color_u32(ImVec4(0.8, 0.8, 0.1, 1.0)), "DEV MODE")

            imgui.render()

            drawlist_start = time.perf_counter()
            self.imgui_renderer.render(imgui.get_draw_data())
            drawlist_ms = (time.perf_counter() - drawlist_start) * 1000.0

            glfw.swap_buffers(self.window)

            if self.pie is not None:
                self.pie.update()
                self._flush_pie_actions()

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

            pie_busy = self.pie is not None and self.pie.busy
            self.perf_stats.idle = idle and not pie_busy

            target_fps = self.idle_fps if idle and not pie_busy else self.fps
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

            if Panel.dev_mode and e.key == glfw.KEY_F12:
                push_debug("TEST", "SUBTITLE", "DESCRIPTION")
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

        if self.pie is not None:
            try:
                self.pie.destroy()
            except Exception:
                logger.exception("failed to destroy the pie menu")
            self.pie = None

        glfw.make_context_current(self.window)
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
