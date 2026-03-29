from abc import ABC
import logging

from imgui_bundle import imgui

logger = logging.getLogger("gui-panels")


class Panel(ABC):
    def __init__(self, dock_id: int = 0) -> None:
        self._open = True
        self._dock_id = dock_id

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
        return False

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
