from abc import ABC, abstractmethod
import logging

from imgui_bundle import imgui


logger = logging.getLogger("gui-panels")

_DEBUG_COLLAPSED_W = 32.0
_DEBUG_EXPANDED_RATIO = 0.20


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

    def handle_event(self, event) -> bool:
        _ = event
        return False

    def render_debug(self) -> None:
        pass

    @abstractmethod
    def _imgui_begin(self) -> tuple[bool, bool]:
        ...

    @abstractmethod
    def _imgui_end(self) -> None:
        ...

    @abstractmethod
    def _render_content(self) -> None:
        ...

    @abstractmethod
    def delete(self) -> None:
        ...

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
        logger.debug("initializing DockspacePanel")
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


