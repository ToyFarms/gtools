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
* all equal but hover still wrong -- the *presented pixels* are displaced
  relative to the reported client rect (observed docked). The report
  measures that displacement directly: every 0.5s it captures the screen
  region around the predicted crosshair position (client origin + io.MousePos,
  GDI BitBlt incl. layered windows) and locates the drawn crosshair markers,
  recording ``visual.disp_*`` = measured position - predicted position.

The F3 overlay also draws two crosshairs every frame: green at io.MousePos
(what ImGui thinks) and magenta at the win32 client cursor (ground truth).
F11 cycles the dock style A/B modes (``overlay.DOCK_STYLE_MODES``); each row
carries ``dock_mode`` so the displacement can be compared across modes.
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
_MEASURE_INTERVAL = 0.5
_MEASURE_HALF = 200  # capture region half-size around the predicted position

# the crosshair colors (drawn with alpha 0.9 over the ui -> near-opaque);
# magenta is rare in uis, so it is the primary marker, green the fallback
_IS_MAGENTA = lambda r, g, b: r >= 200 and g <= 120 and b >= 200  # noqa: E731
_IS_GREEN = lambda r, g, b: g >= 200 and r <= 120 and b <= 120  # noqa: E731


def _crosshair(draw_list: imgui.ImDrawList, x: float, y: float, col: int, r: float = _GLYPH) -> None:
    draw_list.add_line(ImVec2(x - r, y), ImVec2(x + r, y), col)
    draw_list.add_line(ImVec2(x, y - r), ImVec2(x, y + r), col)
    draw_list.add_circle(ImVec2(x, y), 3.0, col)


def _find_marker(data: bytes, w: int, h: int, test) -> tuple[float, float] | None:
    """Centroid of the pixels matching ``test(r, g, b)`` in a BGRA buffer."""
    sx = sy = n = 0
    for i in range(w * h):
        o = i * 4
        if test(data[o + 2], data[o + 1], data[o]):
            sx += i % w
            sy += i // w
            n += 1
    if n < 8:  # a stray pixel is noise; the crosshair is ~50px
        return None
    return (sx / n, sy / n)


def _capture_bgra_win32(x: int, y: int, w: int, h: int) -> bytes | None:
    """GDI screen capture of (x, y, w, h); includes layered windows."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)

        class BMIH(ctypes.Structure):
            _fields_ = [
                ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32),
            ]

        class BMI(ctypes.Structure):
            _fields_ = [("bmiHeader", BMIH), ("bmiColors", ctypes.c_uint32 * 3)]

        hdc_screen = user32.GetDC(None)
        if not hdc_screen:
            return None
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
        gdi32.SelectObject(hdc_mem, hbmp)
        SRCCOPY, CAPTUREBLT = 0x00CC0020, 0x40000000
        ok = gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, x, y, SRCCOPY | CAPTUREBLT)
        bmi = BMI()
        bmi.bmiHeader.biSize = ctypes.sizeof(BMIH)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # top-down rows
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        buf = (ctypes.c_ubyte * (w * h * 4))()
        got = gdi32.GetDIBits(hdc_mem, hbmp, 0, h, buf, ctypes.byref(bmi), 0)  # DIB_RGB_COLORS
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_screen)
        if not ok or got != h:
            return None
        return bytes(buf)
    except Exception:
        logger.exception("screen capture failed")
        return None


class InputDebugRecorder:
    def __init__(
        self,
        *,
        window: Callable[[], object],
        overlay,
        last_cursor: Callable[[], tuple[float, float] | None],
        last_button: Callable[[], dict | None],
        report_path: Path,
        capture_region: Callable[[int, int, int, int], bytes | None] | None = None,
        measure_interval: float = _MEASURE_INTERVAL,
    ) -> None:
        self._window = window
        self._overlay = overlay
        self._last_cursor = last_cursor
        self._last_button = last_button
        self._report_path = report_path
        self._capture_region = capture_region or _capture_bgra_win32
        self._measure_interval = measure_interval
        self._last_measure = 0.0
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
            "dock_mode": getattr(overlay, "dock_style_mode", 0),
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

        self._measure_visual(row)
        return row

    def _measure_visual(self, row: dict) -> None:
        """Locate the drawn crosshair on screen and record its displacement
        from the predicted position (client origin + io.MousePos)."""
        now = time.time()
        if now - self._last_measure < self._measure_interval:
            return
        self._last_measure = now

        win32 = row.get("win32") or {}
        client_rect = win32.get("client_rect")
        if not client_rect:
            return
        px = client_rect[0] + row["io_mouse"][0]
        py = client_rect[1] + row["io_mouse"][1]

        half = _MEASURE_HALF
        rx, ry = int(px) - half, int(py) - half
        buf = self._capture_region(rx, ry, half * 2, half * 2)
        if buf is None:
            row["visual"] = {"error": "capture failed"}
            return

        def locate(test) -> list[float] | None:
            found = _find_marker(buf, half * 2, half * 2, test)
            return [rx + found[0], ry + found[1]] if found else None

        magenta = locate(_IS_MAGENTA)
        green = locate(_IS_GREEN)
        visual: dict = {"predicted": [px, py], "region": [rx, ry, half * 2, half * 2], "magenta": magenta, "green": green}
        for name in ("magenta", "green"):
            if visual[name]:
                visual[f"disp_{name}"] = [visual[name][0] - px, visual[name][1] - py]
        row["visual"] = visual

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

            out["foreground_gui"] = int(u32.GetForegroundWindow() or 0) == int(gui)
            out["style"] = u32.GetWindowLongW(wintypes.HWND(gui), GWL_STYLE)
            out["exstyle"] = u32.GetWindowLongW(wintypes.HWND(gui), GWL_EXSTYLE)

            game = self._overlay.game_hwnd() if self._overlay.docked else 0
            if game:
                game_outer = window_rect(game)
                if game_outer:
                    out["game_outer"] = [game_outer.x, game_outer.y, game_outer.w, game_outer.h]
                game_client = client_rect(game)
                if game_client:
                    out["game_client"] = [game_client.x, game_client.y, game_client.w, game_client.h]

            # dwm's "real" visible bounds -- differs from GetWindowRect when
            # the presented window is displaced from its logical rect
            try:
                dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

                class RECT2(ctypes.Structure):
                    _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                                ("r", ctypes.c_long), ("b", ctypes.c_long)]

                rect = RECT2()
                if dwmapi.DwmGetWindowAttribute(wintypes.HWND(gui), 9, ctypes.byref(rect), ctypes.sizeof(RECT2)) == 0:
                    out["dwm_bounds"] = [rect.l, rect.t, rect.r - rect.l, rect.b - rect.t]
            except Exception:
                pass

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
            f"input debug   docked={row['docked']} mode={row.get('dock_mode', 0)} hidden={row['hidden']}",
            f"green io.mouse_pos = ({mx:.1f}, {my:.1f})",
        ]
        if client:
            lines.append(f"magenta win32.client = ({client[0]}, {client[1]})  screen={win32.get('cursor_screen')}")
            delta = row.get("delta_io_win32")
            if delta:
                lines.append(f"delta io-win32 = ({delta[0]:.1f}, {delta[1]:.1f})")
        visual = row.get("visual") or {}
        if visual:
            if "error" in visual:
                lines.append(f"visual: {visual['error']}")
            else:
                for name, col in (("magenta", "magenta"), ("green", "green")):
                    if visual.get(name):
                        d = visual.get(f"disp_{name}", [0, 0])
                        lines.append(f"visual {col}: measured={visual[name][0]:.0f},{visual[name][1]:.0f}"
                                     f"  DISPLACEMENT=({d[0]:+.1f},{d[1]:+.1f})")
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
                    f"win32 outer = {win32.get('outer_rect')}  client = {win32.get('client_rect')}"
                    f"  dwm = {win32.get('dwm_bounds')}",
                    f"game outer = {win32.get('game_outer')}  client = {win32.get('game_client')}",
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
