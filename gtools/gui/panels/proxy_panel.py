import logging
import threading
import time

from imgui_bundle import imgui
from imgui_bundle import imgui_toggle  # pyright: ignore[reportMissingModuleSource]
from gtools.gui.event import Event
from gtools.gui.panels.panel import Panel
from gtools.gui.lib.world_renderer import WorldRenderer
from gtools.proxy.http_proxy import ThreadedHTTPServer, setup_server
from gtools.proxy.proxy import Proxy
from humanfriendly import format_timespan

logger = logging.getLogger("gui-proxy-panel")


_SPLITTER_THICKNESS = 10.0
_SIDEBAR_MIN_W = 80.0
_SIDEBAR_MAX_RATIO = 0.8


class ProxyPanel(Panel):
    def __init__(self, outer_dockspace_id: int) -> None:
        super().__init__()
        self._outer_dockspace_id = outer_dockspace_id
        self._first_render = True

        self.http_server_enabled = False
        self.proxy_enabled = False

        self.server: ThreadedHTTPServer | None = None
        self.server_thread: threading.Thread | None = None
        self.proxy: Proxy | None = None

        self.server_last_packet_count = 0
        self.client_last_packet_count = 0

        self.world_renderer: WorldRenderer | None = None
        self._sidebar_w: float = 250.0

    def setup_http_server(self) -> None:
        self.server = setup_server()
        self.server_thread = threading.Thread(target=lambda: self.server and self.server.serve_forever())
        self.server_thread.start()

    def delete_http_server(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()

        if self.server_thread:
            self.server_thread.join(timeout=2.0)

    def setup_proxy(self) -> None:
        self.proxy = Proxy()
        self.proxy.start(block=False)

    def delete_proxy(self) -> None:
        if self.proxy:
            self.proxy.stop()

    def delete(self) -> None:
        self.delete_http_server()
        self.delete_proxy()

    def _render_splitter(self, origin_x: float, origin_y: float, h: float) -> None:
        imgui.set_cursor_screen_pos((origin_x + self._sidebar_w, origin_y))
        imgui.push_style_color(imgui.Col_.button, (0.25, 0.25, 0.25, 0.6))
        imgui.push_style_color(imgui.Col_.button_hovered, (0.45, 0.45, 0.45, 0.8))
        imgui.push_style_color(imgui.Col_.button_active, (0.60, 0.60, 0.60, 1.0))
        imgui.invisible_button("##splitter", (_SPLITTER_THICKNESS, h))
        imgui.pop_style_color(3)

        if imgui.is_item_activated():
            self._drag_start_mouse_x = imgui.get_io().mouse_pos.x
            self._drag_start_sidebar_w = self._sidebar_w

        if imgui.is_item_active():
            w_avail = imgui.get_content_region_avail().x + self._sidebar_w
            offset = imgui.get_io().mouse_pos.x - self._drag_start_mouse_x
            self._sidebar_w = max(
                _SIDEBAR_MIN_W,
                min(self._drag_start_sidebar_w + offset, w_avail * _SIDEBAR_MAX_RATIO),
            )

        if imgui.is_item_hovered() or imgui.is_item_active():
            imgui.set_mouse_cursor(imgui.MouseCursor_.resize_ew)

    def _render_body(self) -> None:
        if self.proxy:
            if not self.world_renderer and self.proxy.state.world:
                self.world_renderer = WorldRenderer(self.proxy.state.world)
            elif self.proxy.state.world and self.world_renderer and self.world_renderer._world.name != self.proxy.state.world.name:
                self.world_renderer.delete()
                self.world_renderer = WorldRenderer(self.proxy.state.world)


        changed, self.http_server_enabled = imgui_toggle.toggle("HTTP Server", self.http_server_enabled)
        if changed:
            if not self.http_server_enabled or (self.http_server_enabled and self.server):
                self.delete_http_server()

            if self.http_server_enabled:
                self.setup_http_server()

        imgui.same_line()

        changed, self.proxy_enabled = imgui_toggle.toggle("Proxy", self.proxy_enabled)
        if changed:
            if not self.proxy_enabled or (self.proxy_enabled and self.server):
                self.delete_proxy()

            if self.proxy_enabled:
                self.setup_proxy()

        origin_x, origin_y = imgui.get_cursor_screen_pos()
        avail_w, avail_h = imgui.get_content_region_avail()
        right_w = avail_w - self._sidebar_w - _SPLITTER_THICKNESS

        imgui.set_next_window_pos((origin_x, origin_y))
        imgui.set_next_window_size((self._sidebar_w, avail_h))
        imgui.begin(
            "##info",
            flags=(imgui.WindowFlags_.no_docking | imgui.WindowFlags_.no_move | imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.no_resize),
        )

        if self.proxy:
            state = self.proxy.state

            imgui.text(f"status={state.status.name}")

            imgui.text(f"server ping={state.telemetry.server_ping} pkt={self.proxy.from_server_packet}")
            imgui.same_line()
            c = max(0.2, min(1.0, (self.proxy.from_server_packet - self.server_last_packet_count) / 4))
            self.server_last_packet_count = self.proxy.from_server_packet
            imgui.text_colored((c, c, c, 1), "[*]")

            imgui.text(f"client ping={state.telemetry.client_ping} pkt={self.proxy.from_client_packet}")
            imgui.same_line()
            c = max(0.2, min(1.0, (self.proxy.from_client_packet - self.client_last_packet_count) / 4))
            self.client_last_packet_count = self.proxy.from_client_packet
            imgui.text_colored((c, c, c, 1), "[*]")

            imgui.text(f"uptime={format_timespan(state.me.time_since_login)}")
            imgui.text(f"in_world={format_timespan(state.me.time_in_world)}")

        imgui.end()
        self._render_splitter(origin_x, origin_y, avail_h)
        imgui.set_cursor_screen_pos((origin_x + self._sidebar_w + _SPLITTER_THICKNESS, origin_y))

        if self.world_renderer:
            imgui.begin_child(
                "##world",
                (right_w, avail_h),
                child_flags=imgui.ChildFlags_.none,
                window_flags=imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.no_scrollbar,
            )
            self.world_renderer.render()
            imgui.end_child()
        else:
            label = "waiting..."
            text_size = imgui.calc_text_size(label)
            imgui.set_cursor_screen_pos(
                (
                    origin_x + self._sidebar_w + _SPLITTER_THICKNESS + (right_w - text_size.x) * 0.5,
                    origin_y + (avail_h - text_size.y) * 0.5,
                )
            )
            imgui.text(label)

    def update(self, dt: float) -> None:
        pass

    def render(self) -> None:
        opened, self._open = self._imgui_begin()
        if opened:
            self._render_body()
        self._imgui_end()

    def handle_event(self, event: Event) -> bool:
        if self.world_renderer:
            return self.world_renderer.handle_event(event)

        return False

    def _imgui_begin(self) -> tuple[bool, bool]:
        if self._first_render and self._outer_dockspace_id:
            imgui.set_next_window_dock_id(self._outer_dockspace_id)
            self._first_render = False
        x, y = imgui.begin("Proxy", self._open)
        return x, bool(y)

    def _imgui_end(self) -> None:
        imgui.end()
