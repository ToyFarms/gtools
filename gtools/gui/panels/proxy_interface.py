import logging
import threading
import time

from imgui_bundle import imgui
from imgui_bundle import imgui_toggle  # pyright: ignore[reportMissingModuleSource]
from gtools.gui.event import Event
from gtools.gui.panels.panel import Panel
from gtools.proxy.http_proxy import ThreadedHTTPServer, setup_server
from gtools.proxy.proxy import Proxy
from humanfriendly import format_timespan

logger = logging.getLogger("gui-proxy-panel")


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

    def _render_body(self) -> None:
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

        if self.proxy:
            imgui.text(f"status={self.proxy.state.status.name}")

            imgui.text(f"server ping={self.proxy.state.telemetry.server_ping} pkt={self.proxy.from_server_packet}")
            imgui.same_line()
            c = max(0.2, min(1.0, (self.proxy.from_server_packet - self.server_last_packet_count) / 10))
            self.server_last_packet_count = self.proxy.from_server_packet
            imgui.text_colored((c, c, c, 1), "[*]")

            imgui.text(f"client ping={self.proxy.state.telemetry.client_ping} pkt={self.proxy.from_client_packet}")
            imgui.same_line()
            c = max(0.2, min(1.0, (self.proxy.from_client_packet - self.client_last_packet_count) / 10))
            self.client_last_packet_count = self.proxy.from_client_packet
            imgui.text_colored((c, c, c, 1), "[*]")

            now = time.time()
            if self.proxy.state.telemetry.logged_in_time != 0.0:
                imgui.text(f"uptime={format_timespan(now - self.proxy.state.telemetry.logged_in_time)} in_world time={format_timespan(now - self.proxy.state.telemetry.enter_world_time)}")
            else:
                imgui.text("uptime=0 in_world time=0")

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
