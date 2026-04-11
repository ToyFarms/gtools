import logging
import threading
from traceback import print_exc

from imgui_bundle import imgui
from imgui_bundle import imgui_toggle  # pyright: ignore[reportMissingModuleSource]
from gtools.core.format import format_timespan
from gtools.gui.event import Event
from gtools.gui.lib.toast import push_error
from gtools.gui.panels.panel import Panel
from gtools.gui.lib.world_renderer import WorldRenderer
from gtools.protogen.extension_pb2 import INTEREST_STATE_UPDATE, Interest
from gtools.proxy.extension.client.sdk import Extension
from gtools.proxy.http_proxy import ThreadedHTTPServer, setup_server
from gtools.proxy.proxy import Proxy

from gtools.proxy.state import Status

logger = logging.getLogger("gui-proxy-panel")


_SPLITTER_THICKNESS = 10.0
_SIDEBAR_MIN_W = 80.0
_SIDEBAR_MAX_RATIO = 0.8

_BLINK_DOT_RADIUS = 4.5
_BLINK_DOT_PAD = 8.0
_BLINK_DOT_RIGHT_MARGIN = 6.0
_BLINK_DECAY_RATE = 3.5


class GuiExtension(Extension):
    def __init__(self) -> None:
        super().__init__(name="GUI-EXTENSION", interest=[Interest(interest=INTEREST_STATE_UPDATE)])

    def destroy(self) -> None:
        pass


class ProxyPanel(Panel):
    def __init__(self, dock_id: int) -> None:
        super().__init__(dock_id)
        self._is_docked = False
        self._first_render = True

        self.http_server_enabled = False
        self.proxy_enabled = False
        self.extension_enabled = False

        self.server: ThreadedHTTPServer | None = None
        self.server_thread: threading.Thread | None = None
        self.proxy: Proxy | None = None

        self.server_last_packet_count = 0
        self.client_last_packet_count = 0
        self._server_blink_t: float = 0.0
        self._client_blink_t: float = 0.0

        self.extension: GuiExtension | None = None

        self.world_renderer: WorldRenderer | None = None
        self.reload_next_world: bool = True
        self._sidebar_w: float = 250.0

    def setup_http_server(self) -> None:
        try:
            self.server = setup_server()
            self.server_thread = threading.Thread(target=lambda: self.server and self.server.serve_forever())
            self.server_thread.start()
        except Exception as e:
            push_error("HTTP Server", "failed starting http(s) server", f"{e}")
            print_exc()

    def delete_http_server(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

        if self.server_thread:
            self.server_thread.join(timeout=2.0)
            self.server_thread = None

    def setup_proxy(self) -> None:
        try:
            self.proxy = Proxy()
            self.proxy.start(block=False)
        except Exception as e:
            push_error("Proxy", "failed starting proxy", f"{e}")
            print_exc()

    def delete_proxy(self) -> None:
        if self.proxy:
            self.proxy.stop()
            self.proxy = None

    def setup_extension(self) -> None:
        try:
            self.extension = GuiExtension()
            self.extension.start()
        except Exception as e:
            push_error("Extension", "failed starting extension", f"{e}")
            print_exc()

    def delete_extension(self) -> None:
        if self.extension:
            self.extension.stop()
            self.extension = None

    def delete(self) -> None:
        self.delete_http_server()
        self.delete_proxy()
        self.delete_extension()

    def _label_value_row(self, label: str, value: str) -> None:
        avail_x = imgui.get_content_region_avail().x
        cursor_x = imgui.get_cursor_pos_x()
        value_w = imgui.calc_text_size(value).x

        imgui.text_unformatted(label)
        imgui.same_line()
        imgui.set_cursor_pos_x(cursor_x + max(0.0, avail_x - value_w))
        imgui.text_unformatted(value)

    def _render_packet_row(self, label: str, ping: int, pkt: int, blink_t: float) -> None:
        dl = imgui.get_window_draw_list()
        line_h = imgui.get_text_line_height()
        avail_x = imgui.get_content_region_avail().x
        cursor_x = imgui.get_cursor_pos_x()
        cursor_screen = imgui.get_cursor_screen_pos()

        dot_slot = _BLINK_DOT_RADIUS * 2.0 + _BLINK_DOT_PAD + _BLINK_DOT_RIGHT_MARGIN

        value = f"{ping}ms  {pkt:,}pkt"
        value_w = imgui.calc_text_size(value).x

        imgui.text_unformatted(label)

        imgui.same_line()
        imgui.set_cursor_pos_x(cursor_x + max(0.0, avail_x - dot_slot - value_w))
        imgui.text_unformatted(value)

        t = blink_t
        r = 0.15 + 0.60 * t
        g = 0.55 + 0.45 * t
        b = 0.15 + 0.30 * t
        dot_alpha = 0.35 + 0.65 * t

        dot_cx = cursor_screen.x + avail_x - _BLINK_DOT_RIGHT_MARGIN - _BLINK_DOT_RADIUS
        dot_cy = cursor_screen.y + line_h * 0.5

        fill_col = imgui.get_color_u32((r, g, b, dot_alpha))
        rim_col = imgui.get_color_u32((r * 1.3, g * 1.1, b, min(1.0, dot_alpha * 1.4)))

        dl.add_circle_filled((dot_cx, dot_cy), _BLINK_DOT_RADIUS, fill_col)
        dl.add_circle((dot_cx, dot_cy), _BLINK_DOT_RADIUS, rim_col, num_segments=0, thickness=1.2)

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
        state = self.proxy.state if self.proxy else self.extension.state if self.extension else None

        if state:
            if not state.world:
                self.reload_next_world = True

            if self.reload_next_world and state.world:
                if self.world_renderer:
                    self.world_renderer.delete()

                self.world_renderer = WorldRenderer(state.world)
                self.reload_next_world = False

        changed, self.http_server_enabled = imgui_toggle.toggle("HTTP Server", self.http_server_enabled)
        if changed:
            if not self.http_server_enabled or (self.http_server_enabled and self.server):
                self.delete_http_server()
            if self.http_server_enabled:
                self.setup_http_server()

        imgui.same_line()

        imgui.begin_disabled(self.extension_enabled)
        changed, self.proxy_enabled = imgui_toggle.toggle("Proxy", self.proxy_enabled)
        if changed:
            if not self.proxy_enabled or (self.proxy_enabled and self.server):
                self.delete_proxy()
            if self.proxy_enabled:
                self.setup_proxy()
        imgui.end_disabled()

        imgui.same_line()

        imgui.begin_disabled(self.proxy_enabled)
        changed, self.extension_enabled = imgui_toggle.toggle("Extension", self.extension_enabled)
        if changed:
            if not self.extension_enabled or (self.extension_enabled and self.extension):
                self.delete_extension()
            if self.extension_enabled:
                self.setup_extension()
        imgui.end_disabled()

        origin_x, origin_y = imgui.get_cursor_screen_pos()
        avail_w, avail_h = imgui.get_content_region_avail()
        right_w = avail_w - self._sidebar_w - _SPLITTER_THICKNESS

        imgui.set_next_window_pos((origin_x, origin_y))
        imgui.set_next_window_size((self._sidebar_w, avail_h))
        imgui.begin(
            "##info",
            flags=(imgui.WindowFlags_.no_docking | imgui.WindowFlags_.no_move | imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.no_resize),
        )

        if state:
            self._label_value_row("status", state.status.name)

            if state.status == Status.IN_WORLD and state.world:
                self._label_value_row("world", state.world.name.decode())

            imgui.spacing()

            if self.proxy:
                self._render_packet_row(
                    "server",
                    state.telemetry.server_ping,
                    self.proxy.from_server_packet,
                    self._server_blink_t,
                )
                self._render_packet_row(
                    "client",
                    state.telemetry.client_ping,
                    self.proxy.from_client_packet,
                    self._client_blink_t,
                )

                imgui.spacing()

            self._label_value_row("uptime", format_timespan(state.me.time_since_login))
            self._label_value_row("in world", format_timespan(state.me.time_in_world))

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

    @property
    def is_dirty(self) -> bool:
        if self.world_renderer:
            return self.world_renderer._dirty
        return False

    @is_dirty.setter
    def is_dirty(self, x: bool) -> None:
        if self.world_renderer:
            self.world_renderer._dirty = x

    def update(self, dt: float) -> None:
        if self.proxy:
            new_server = self.proxy.from_server_packet
            if new_server != self.server_last_packet_count:
                self._server_blink_t = 1.0
                self.server_last_packet_count = new_server

            new_client = self.proxy.from_client_packet
            if new_client != self.client_last_packet_count:
                self._client_blink_t = 1.0
                self.client_last_packet_count = new_client

        self._server_blink_t = max(0.0, self._server_blink_t - dt * _BLINK_DECAY_RATE)
        self._client_blink_t = max(0.0, self._client_blink_t - dt * _BLINK_DECAY_RATE)

        if self.world_renderer:
            self.world_renderer.update(dt)

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
        if not self._is_docked and self.dock_id:
            imgui.set_next_window_dock_id(self.dock_id)

        x, y = imgui.begin("Proxy", self._open)

        if not self._is_docked and imgui.is_window_docked():
            self._is_docked = True

        if self._first_render:
            self._first_render = False

        return x, bool(y)

    def _imgui_end(self) -> None:
        imgui.end()
