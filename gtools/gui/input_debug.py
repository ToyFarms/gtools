"""Input-geometry diagnostics for the docked-overlay mouse bug.

While the F3 debug overlay is on (``perf_stats.SHOW_DEBUG_OVERLAY``), every
frame samples the full mouse-position chain and appends rows that differ from
the previous one to ``~/.gtools/input_debug_report.jsonl``:

    ImGui io.MousePos   <- GlfwRenderer cursor callback / process_inputs
                        <- glfw.get_cursor_pos()            (client px)
                        <- win32 GetCursorPos+ScreenToClient (ground truth)

plus the window geometry both sides report, so the report can discriminate
between the failure modes:

* ``io_mouse`` != ``glfw_cursor``/``win32.cursor_client`` -- the input chain
  feeds ImGui something other than the real client position;
* ``win32.cursor_client`` != where the user sees the cursor -- the window's
  client origin is not where the style/DPI math thinks it is;
* all equal but hover still wrong -- the rendered UI is displaced relative to
  the window (viewport / layout mismatch: compare io_display vs glfw sizes).

The F3 overlay also draws two crosshairs every frame: green at io.MousePos
(what ImGui thinks) and magenta at the win32 client cursor (ground truth).
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path

import glfw
import imgui_bundle
from imgui_bundle import ImVec2, imgui

logger = logging.getLogger("gui-input-debug")

MAX_ROWS = 5000

_GLYPH = 12.0  # crosshair arm length


def _crosshair(draw_list: imgui.ImDrawList, x: float, y: float, col: int, r: float = _GLYPH) -> None:
    draw_list.add_line(ImVec2(x - r, y), ImVec2(x + r, y), col)
    draw_list.add_line(ImVec2(x, y - r), ImVec2(x, y + r), col)
    draw_list.add_circle(ImVec2(x, y), 3.0, col)


class InputDebugRecorder:
    def __init__(
        self,
        *,
        window: Callable[[], object],
        overlay,
        last_cursor: Callable[[], tuple[float, float] | None],
        last_button: Callable[[], dict | None],
        report_path: Path,
    ) -> None:
        self._window = window
        self._overlay = overlay
        self._last_cursor = last_cursor
        self._last_button = last_button
        self._report_path = report_path
        self._file = None
        self._rows = 0
        self._last_key: str | None = None
        self._reset_report()

    # -- report file -------------------------------------------------------

    def _reset_report(self) -> None:
        try:
            self._report_path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self._report_path.open("w", encoding="utf-8")
            header = {
                "header": {
                    "t": round(time.time(), 3),
                    "platform": sys.platform,
                    "python": sys.version.split()[0],
                    "argv": sys.argv,
                    "glfw": glfw.get_version_string().decode(),
                    "imgui_bundle": imgui_bundle.__version__,
                }
            }
            self._file.write(json.dumps(header) + "\n")
            self._file.flush()
        except OSError:
            logger.exception("cannot open the input debug report %s", self._report_path)
            self._file = None

    def mark(self, text: str) -> None:
        """Write an action marker row (not deduped), e.g. F3 toggles."""
        if self._file is None:
            return
        self._file.write(json.dumps({"mark": text, "t": round(time.time(), 3)}) + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    # -- sampling ----------------------------------------------------------

    def sample(self) -> dict:
        io = imgui.get_io()
        window = self._window()
        overlay = self._overlay

        row: dict = {
            "t": round(time.time(), 3),
            "docked": bool(overlay.docked),
            "hidden": bool(overlay.state.hidden),
            "io_mouse": [io.mouse_pos.x, io.mouse_pos.y],
            "io_display": [io.display_size.x, io.display_size.y],
            "io_fb_scale": [io.display_framebuffer_scale.x, io.display_framebuffer_scale.y],
            "io_mouse_down": [bool(x) for x in io.mouse_down],
            "io_capture_mouse": bool(io.want_capture_mouse),
            "glfw_cursor": list(glfw.get_cursor_pos(window)),
            "glfw_last_callback": list(self._last_cursor() or ()),
            "glfw_win_size": list(glfw.get_window_size(window)),
            "glfw_fb_size": list(glfw.get_framebuffer_size(window)),
            "glfw_win_pos": list(glfw.get_window_pos(window)),
            "glfw_content_scale": list(glfw.get_window_content_scale(window)),
            "glfw_focused": bool(glfw.get_window_attrib(window, glfw.FOCUSED)),
            "glfw_hovered": bool(glfw.get_window_attrib(window, glfw.HOVERED)),
        }

        last_button = self._last_button()
        if last_button:
            row["last_button"] = last_button

        win32 = self._gather_win32()
        if win32 is not None:
            row["win32"] = win32
            client = win32.get("cursor_client")
            if client:
                row["delta_io_win32"] = [row["io_mouse"][0] - client[0], row["io_mouse"][1] - client[1]]

        return row

    def _gather_win32(self) -> dict | None:
        """Ground truth from win32 -- Windows only, never raises."""
        if sys.platform != "win32":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            from gtools.gui.overlay import GWL_EXSTYLE, GWL_STYLE, _user32, client_rect, window_rect

            u32 = _user32()
            gui = self._overlay.gui_hwnd()
            out: dict = {"gui_hwnd": gui}
            if not gui:
                return out

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint32),
                    ("rcMonitor", RECT),
                    ("rcWork", RECT),
                    ("dwFlags", ctypes.c_uint32),
                ]

            pt = wintypes.POINT(0, 0)
            u32.GetCursorPos(ctypes.byref(pt))
            client_pt = wintypes.POINT(pt.x, pt.y)
            u32.ScreenToClient(wintypes.HWND(gui), ctypes.byref(client_pt))
            out["cursor_screen"] = [pt.x, pt.y]
            out["cursor_client"] = [client_pt.x, client_pt.y]

            outer = window_rect(gui)
            if outer:
                out["outer_rect"] = [outer.x, outer.y, outer.w, outer.h]
            client = client_rect(gui)
            if client:
                out["client_rect"] = [client.x, client.y, client.w, client.h]

            out["foreground_gui"] = bool(u32.GetForegroundWindow() == wintypes.HWND(gui))
            out["style"] = u32.GetWindowLongW(wintypes.HWND(gui), GWL_STYLE)
            out["exstyle"] = u32.GetWindowLongW(wintypes.HWND(gui), GWL_EXSTYLE)

            if hasattr(u32, "GetDpiForWindow"):
                u32.GetDpiForWindow.argtypes = [wintypes.HWND]
                u32.GetDpiForWindow.restype = ctypes.c_uint32
                out["dpi_gui"] = u32.GetDpiForWindow(wintypes.HWND(gui))
                game = self._overlay.game_hwnd()
                if game:
                    out["dpi_game"] = u32.GetDpiForWindow(wintypes.HWND(game))

            monitor = u32.MonitorFromWindow(wintypes.HWND(gui), 2)  # MONITOR_DEFAULTTONEAREST
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if u32.GetMonitorInfoW(wintypes.HANDLE(monitor), ctypes.byref(info)):
                rc = info.rcMonitor
                out["monitor_rect"] = [rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top]

            return out
        except Exception as exc:  # diagnostics must never break the app
            return {"error": repr(exc)}

    # -- report + render ---------------------------------------------------

    def record(self, row: dict) -> None:
        if self._file is None or self._rows >= MAX_ROWS:
            return
        key = json.dumps({k: v for k, v in row.items() if k != "t"}, sort_keys=True, default=str)
        if key == self._last_key:
            return
        self._last_key = key
        self._rows += 1
        self._file.write(json.dumps(row, default=str) + "\n")
        if self._rows >= MAX_ROWS:
            self._file.write(json.dumps({"note": f"row cap {MAX_ROWS} reached, sampling stopped"}) + "\n")
        self._file.flush()

    def sample_and_record(self) -> dict:
        row = self.sample()
        self.record(row)
        return row

    def render(self, row: dict) -> None:
        draw_list = imgui.get_foreground_draw_list()
        green = imgui.get_color_u32((0.2, 1.0, 0.2, 0.9))
        magenta = imgui.get_color_u32((1.0, 0.2, 1.0, 0.9))
        white = imgui.get_color_u32((1.0, 1.0, 1.0, 0.85))
        dim = imgui.get_color_u32((0.0, 0.0, 0.0, 0.6))

        io_mouse = row["io_mouse"]
        _crosshair(draw_list, io_mouse[0], io_mouse[1], green)

        win32 = row.get("win32") or {}
        client = win32.get("cursor_client")
        if client:
            _crosshair(draw_list, client[0], client[1], magenta)

        mx, my = io_mouse
        lines = [
            f"input debug   docked={row['docked']} hidden={row['hidden']}",
            f"green io.mouse_pos = ({mx:.1f}, {my:.1f})",
        ]
        if client:
            lines.append(f"magenta win32.client = ({client[0]}, {client[1]})  screen={win32.get('cursor_screen')}")
            delta = row.get("delta_io_win32")
            if delta:
                lines.append(f"delta io-win32 = ({delta[0]:.1f}, {delta[1]:.1f})")
        lines += [
            f"glfw.cursor = {row['glfw_cursor']}  last_cb={row['glfw_last_callback']}",
            f"io.display = ({row['io_display'][0]:.0f}, {row['io_display'][1]:.0f})"
            f"  fb_scale=({row['io_fb_scale'][0]:.2f}, {row['io_fb_scale'][1]:.2f})"
            f"  capture_mouse={row['io_capture_mouse']}",
            f"glfw.win = {row['glfw_win_size']}  fb = {row['glfw_fb_size']}  pos = {row['glfw_win_pos']}"
            f"  content_scale = {row['glfw_content_scale']}",
            f"focused={row['glfw_focused']} hovered={row['glfw_hovered']}",
        ]
        if win32:
            if "error" in win32:
                lines.append(f"win32 error: {win32['error']}")
            else:
                lines += [
                    f"win32 outer = {win32.get('outer_rect')}  client = {win32.get('client_rect')}",
                    f"style={win32.get('style')} exstyle={win32.get('exstyle')} fg_gui={win32.get('foreground_gui')}"
                    f" dpi_gui={win32.get('dpi_gui')} dpi_game={win32.get('dpi_game')}",
                    f"monitor = {win32.get('monitor_rect')}",
                ]

        x, y = 8.0, imgui.get_frame_height() + 6.0
        line_h = imgui.get_text_line_height()
        pad = 4.0
        w = max(imgui.calc_text_size(line).x for line in lines) + pad * 2
        h = len(lines) * line_h + pad * 2
        draw_list.add_rect_filled(ImVec2(x, y), ImVec2(x + w, y + h), dim)
        for i, line in enumerate(lines):
            draw_list.add_text(ImVec2(x + pad, y + pad + i * line_h), white, line)
