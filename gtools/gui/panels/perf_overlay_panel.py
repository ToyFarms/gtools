from __future__ import annotations

import math
from collections.abc import Iterable

from imgui_bundle import ImVec2, imgui

import gtools.gui.lib.perf_stats as perf_stats
from gtools.gui.lib.perf_stats import PerfStats
from gtools.gui.panels.panel import Panel

_MS_60FPS = 1000.0 / 60
_MS_30FPS = 1000.0 / 30
_MS_10FPS = 1000.0 / 10

_GREEN = (0.2, 1.0, 0.2)
_YELLOW = (1.0, 0.85, 0.1)
_RED = (1.0, 0.15, 0.15)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _ms_to_color(ms: float, t_good: float = _MS_60FPS, t_warn: float = _MS_30FPS) -> tuple[float, float, float]:
    if ms <= t_good:
        return _GREEN
    if ms <= t_warn:
        t = (ms - t_good) / (t_warn - t_good)
        return (_lerp(_GREEN[0], _YELLOW[0], t), _lerp(_GREEN[1], _YELLOW[1], t), _lerp(_GREEN[2], _YELLOW[2], t))

    t_critical = t_warn * 1.5
    t = min((ms - t_warn) / (t_critical - t_warn), 1.0)
    return (_lerp(_YELLOW[0], _RED[0], t), _lerp(_YELLOW[1], _RED[1], t), _lerp(_YELLOW[2], _RED[2], t))


def _draw_time_graph(
    draw_list: imgui.ImDrawList,
    gx: float,
    gy: float,
    graph_w: float,
    graph_h: float,
    times_list: list[float],
    maxlen: int,
    label: str,
    t_good: float | None = None,
    t_warn: float | None = None,
) -> None:
    avg_val = sum(times_list) / len(times_list)
    max_val = max(times_list)

    draw_list.add_rect_filled(
        ImVec2(gx, gy),
        ImVec2(gx + graph_w, gy + graph_h),
        imgui.get_color_u32((0.0, 0.0, 0.0, 0.6)),
    )

    base_y_frac = 0.10
    px_per_ms = (graph_h * base_y_frac) / _MS_60FPS
    bar_w = graph_w / max(maxlen, 1)

    for i, t in enumerate(times_list):
        if t_good is not None and t_warn is not None:
            r, g, b = _ms_to_color(t, t_good, t_warn)
        else:
            r, g, b = _ms_to_color(t)

        bh = t * px_per_ms
        bx = gx + i * bar_w
        draw_list.add_rect_filled(
            ImVec2(bx, gy + graph_h - bh),
            ImVec2(bx + bar_w, gy + graph_h),
            imgui.get_color_u32((r, g, b, 0.9)),
        )

    if t_good is None:
        for ref_ms, ref_label in ((_MS_60FPS, "60fps"), (_MS_30FPS, "30fps"), (_MS_10FPS, "10fps")):
            ref_y = gy + graph_h - ref_ms * px_per_ms
            draw_list.add_line(
                ImVec2(gx, ref_y),
                ImVec2(gx + graph_w, ref_y),
                imgui.get_color_u32((1.0, 1.0, 1.0, 0.2)),
                thickness=1.0,
            )
            draw_list.add_text(
                ImVec2(gx + 3, ref_y - 13),
                imgui.get_color_u32((1.0, 1.0, 1.0, 0.4)),
                ref_label,
            )

    draw_list.add_text(
        ImVec2(gx + 4, gy + 4),
        imgui.get_color_u32((1.0, 1.0, 1.0, 0.85)),
        f"{label}  avg {avg_val:.2f}ms  max {max_val:.2f}ms",
    )
    draw_list.add_rect(
        ImVec2(gx, gy),
        ImVec2(gx + graph_w, gy + graph_h),
        imgui.get_color_u32((1.0, 1.0, 1.0, 0.15)),
    )


class PerfOverlayPanel(Panel):
    def __init__(self, stats: PerfStats) -> None:
        super().__init__(dock_id=0)
        self._stats = stats
        self._graph_height = 100.0

    @staticmethod
    def _non_empty(seq: Iterable[float]) -> bool:
        for _ in seq:
            return True
        return False

    def render(self) -> None:
        if not perf_stats.SHOW_DEBUG_OVERLAY:
            return

        vw, vh = imgui.get_io().display_size
        if vw <= 0 or vh <= 0:
            return

        imgui.set_next_window_pos(ImVec2(0, 0))
        imgui.set_next_window_size(ImVec2(vw, vh))

        imgui.begin(
            "##perf_overlay",
            flags=(
                imgui.WindowFlags_.no_decoration
                | imgui.WindowFlags_.no_background
                | imgui.WindowFlags_.no_inputs
                | imgui.WindowFlags_.no_nav
                | imgui.WindowFlags_.no_docking
                | imgui.WindowFlags_.no_focus_on_appearing
            ),
        )

        draw_list = imgui.get_window_draw_list()

        graph_specs: list[tuple[list[float], int, str]] = []
        for label, q in self._stats.stats.items():
            graph_specs.append((list(q), q.maxlen or 1, label))

        graph_specs = [x for x in graph_specs if x[0]]
        if not graph_specs:
            imgui.end()
            return

        graph_gap = 6
        graph_columns = 3
        num_rows = math.ceil(len(graph_specs) / graph_columns)
        graph_h = self._graph_height
        total_graphs_h = num_rows * graph_h + (num_rows - 1) * graph_gap

        graphs_x0 = 100
        graphs_y0 = vh - total_graphs_h - 20

        available_w = vw - graphs_x0 - 10
        graph_w = max(80.0, (available_w - graph_gap * 2.0) / graph_columns)

        for idx, (tlist, _maxlen, glabel) in enumerate(graph_specs):
            col = idx % graph_columns
            row = idx // graph_columns
            gx = graphs_x0 + col * (graph_w + graph_gap)
            gy = graphs_y0 + row * (graph_h + graph_gap)

            _draw_time_graph(draw_list, gx, gy, graph_w, graph_h, tlist, _maxlen, glabel, None, None)

            # Keep cursor stable; this dummy is only to avoid weird internal spacing.
            imgui.dummy(ImVec2(graph_w, graph_h))

        imgui.end()
