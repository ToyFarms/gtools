from abc import ABC
from collections import deque
import logging
from typing import Callable, ClassVar

from imgui_bundle import imgui

logger = logging.getLogger("gui-panels")

"""template

from imgui_bundle import imgui
from gtools.gui.event import Event
from gtools.gui.panels.panel import Panel


class FOO(Panel):
    def __init__(self, dock_id: int) -> None:
        super().__init__(dock_id)
        self._is_docked = False
        self._first_render = True

    def _render_body(self) -> None:
        pass

    @property
    def is_dirty(self) -> bool:
        return True

    @is_dirty.setter
    def is_dirty(self, x: bool) -> None:
        pass

    def update(self, dt: float) -> None:
        pass

    def render(self) -> None:
        if not self._is_docked and self.dock_id:
            imgui.set_next_window_dock_id(self.dock_id)

        opened, self._open = imgui.begin("FOO", self._open)
        if not self._is_docked and imgui.is_window_docked():
            self._is_docked = True

        if self._first_render:
            self._first_render = False

        if opened:
            self._render_body()
        imgui.end()

    def handle_event(self, event: Event) -> bool:
        return False

    def delete(self) -> None:
        pass
"""


class Panel(ABC):
    dev_mode: ClassVar[bool] = False
    panels_to_add: ClassVar[deque[Callable[[int], "Panel"]]] = deque()

    def __init__(self, dock_id: int = 0) -> None:
        self._open = True
        self._dock_id = dock_id
        self._dirty = False

    @staticmethod
    def add_panel(panel: Callable[[int], "Panel"]) -> None:
        Panel.panels_to_add.append(panel)

    @property
    def dock_id(self) -> int:
        return self._dock_id

    @dock_id.setter
    def dock_id(self, value: int) -> None:
        self._dock_id = value

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    @is_dirty.setter
    def is_dirty(self, x: bool) -> None:
        self._dirty = x

    def handle_event(self, event) -> bool:
        _ = event
        return False

    def render(self) -> None:
        pass

    def update(self, dt: float) -> None:
        pass

    def get_perf(self, out: dict[str, float]) -> None:
        pass

    def delete(self) -> None: ...


class DockspacePanel(Panel):
    def __init__(self) -> None:
        super().__init__()
        logger.debug("initializing DockspacePanel")
        self._node_id: int = 0

    @property
    def node_id(self) -> int:
        return self._node_id

    def render(self) -> tuple[bool, bool]:
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
        self._node_id = imgui.dock_space(
            imgui.get_id("MainDockspace"),
            (0.0, 0.0),
            imgui.DockNodeFlags_.passthru_central_node,
        )
        imgui.end()

        return bool(opened), True
