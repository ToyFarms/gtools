import logging

from imgui_bundle import imgui
from gtools.gui.event import Event
from gtools.gui.panels.panel import Panel

logger = logging.getLogger("gui-proxy-panel")


class ProxyPanel(Panel):
    def __init__(self, outer_dockspace_id: int) -> None:
        super().__init__()
        self._outer_dockspace_id = outer_dockspace_id
        self._first_render = True

    def delete(self) -> None:
        pass

    def _render_body(self) -> None:
        imgui.text("proxy")

    def update(self, dt: float) -> None:
        pass

    def render(self) -> None:
        opened, self._open = self._imgui_begin()
        if opened:
            self._render_body()
        self._imgui_end()

    def handle_event(self, event: Event) -> bool:
        return False

    def _imgui_begin(self) -> tuple[bool, bool]:
        if self._first_render and self._outer_dockspace_id:
            imgui.set_next_window_dock_id(self._outer_dockspace_id)
            self._first_render = False
        x, y = imgui.begin("Proxy", self._open)
        return x, bool(y)

    def _imgui_end(self) -> None:
        imgui.end()
