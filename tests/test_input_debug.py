"""Headless checks for the F3 input-geometry diagnostics (gui/input_debug).

The recorder samples the mouse-position chain (ImGui io <-> glfw <-> win32)
into a jsonl report. These tests exercise the pure parts -- row shape, the
io-vs-win32 delta, dedupe, and the report file -- with monkeypatched glfw
functions and a fake overlay; no window and no win32 needed.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from imgui_bundle import imgui

from gtools.gui import input_debug as input_debug_module
from gtools.gui.input_debug import InputDebugRecorder


@pytest.fixture(scope="module")
def ui():
    imgui.create_context()
    io = imgui.get_io()
    io.display_size = (800.0, 600.0)
    io.delta_time = 1 / 60
    # no renderer backend in a test: tell ImGui the backend owns the textures
    io.backend_flags |= imgui.BackendFlags_.renderer_has_textures
    yield io


@pytest.fixture(autouse=True)
def force_non_windows(monkeypatch):
    """The win32 probes must not run in tests (they are Windows-only)."""
    monkeypatch.setattr(input_debug_module.sys, "platform", "linux")


@pytest.fixture
def fake_glfw(monkeypatch):
    """Patch the glfw calls sample() makes; the cursor value is mutable."""
    state = {"cursor": (100.0, 50.0)}
    g = input_debug_module.glfw
    monkeypatch.setattr(g, "get_cursor_pos", lambda w: state["cursor"])
    monkeypatch.setattr(g, "get_window_size", lambda w: (800, 600))
    monkeypatch.setattr(g, "get_framebuffer_size", lambda w: (800, 600))
    monkeypatch.setattr(g, "get_window_pos", lambda w: (10, 20))
    monkeypatch.setattr(g, "get_window_content_scale", lambda w: (1.0, 1.0))
    monkeypatch.setattr(g, "get_window_attrib", lambda w, a: True)
    return state


class FakeOverlay:
    def __init__(self):
        self.docked = False
        self.state = SimpleNamespace(hidden=False)

    def gui_hwnd(self):
        return 0x1234

    def game_hwnd(self):
        return 0


def make_recorder(tmp_path, overlay, **providers) -> InputDebugRecorder:
    return InputDebugRecorder(
        window=lambda: object(),
        overlay=overlay,
        last_cursor=providers.get("last_cursor", lambda: None),
        last_button=providers.get("last_button", lambda: None),
        report_path=tmp_path / "report.jsonl",
        capture_region=providers.get("capture_region"),
        measure_interval=providers.get("measure_interval", 0.0),
    )


WIN32_FAKE = {
    "gui_hwnd": 0x1234,
    "cursor_screen": [466.0, 241.0],
    "cursor_client": [10.0, 5.0],
    "client_rect": [456, 236, 816, 639],
}


def paint(buf, w, x, y, bgra):
    o = (y * w + x) * 4
    buf[o : o + 4] = bytes(bgra)


def capture_with_blobs(w, h, *blobs):
    """Fake GDI capture: a BGRA buffer with (color, x, y) blobs painted in."""

    def capture(rx, ry, rw, rh):
        assert (rw, rh) == (w, h)
        buf = bytearray(w * h * 4)
        for (b, g, r, _a), x, y in blobs:
            for dx in range(4):
                for dy in range(4):
                    paint(buf, w, x + dx, y + dy, (b, g, r, 255))
        return bytes(buf)

    return capture


MAGENTA = (232, 48, 232, 255)  # b, g, r
GREEN = (46, 232, 46, 255)


def read_lines(tmp_path) -> list[dict]:
    text = (tmp_path / "report.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


def test_sample_row_shape(ui, fake_glfw, tmp_path):
    rec = make_recorder(tmp_path, FakeOverlay())
    row = rec.sample()
    assert row["glfw_cursor"] == [100.0, 50.0]
    assert row["glfw_win_size"] == [800, 600]
    assert row["glfw_win_pos"] == [10, 20]
    assert row["docked"] is False and row["hidden"] is False
    assert len(row["io_mouse"]) == 2
    # non-Windows test environment: no win32 section, no delta
    assert "win32" not in row and "delta_io_win32" not in row
    rec.close()


def test_report_header_written(ui, fake_glfw, tmp_path):
    rec = make_recorder(tmp_path, FakeOverlay())
    rec.close()
    lines = read_lines(tmp_path)
    assert len(lines) == 1
    header = lines[0]["header"]
    assert header["platform"] == "linux"
    assert header["imgui_bundle"]


def test_record_dedupes_identical_rows(ui, fake_glfw, tmp_path):
    rec = make_recorder(tmp_path, FakeOverlay())
    rec.sample_and_record()
    rec.sample_and_record()
    rec.close()
    lines = read_lines(tmp_path)
    assert len(lines) == 2  # header + one deduped row


def test_record_writes_changed_rows(ui, fake_glfw, tmp_path):
    rec = make_recorder(tmp_path, FakeOverlay())
    rec.sample_and_record()
    fake_glfw["cursor"] = (120.0, 60.0)
    rec.sample_and_record()
    rec.close()
    lines = read_lines(tmp_path)
    assert len(lines) == 3
    assert lines[2]["glfw_cursor"] == [120.0, 60.0]


def test_mark_is_not_deduped(ui, fake_glfw, tmp_path):
    rec = make_recorder(tmp_path, FakeOverlay())
    rec.sample_and_record()
    rec.mark("F3 on")
    rec.sample_and_record()  # identical, still deduped -- but the mark stays
    rec.close()
    lines = read_lines(tmp_path)
    assert any("mark" in line for line in lines)


def test_delta_io_win32_computed(ui, fake_glfw, tmp_path, monkeypatch):
    rec = make_recorder(tmp_path, FakeOverlay())
    monkeypatch.setattr(
        rec,
        "_gather_win32",
        lambda: {"gui_hwnd": 0x1234, "cursor_screen": [110.0, 55.0], "cursor_client": [10.0, 5.0]},
    )
    row = rec.sample_and_record()
    mx, my = row["io_mouse"]
    assert row["delta_io_win32"] == [mx - 10.0, my - 5.0]
    rec.close()
    lines = read_lines(tmp_path)
    assert lines[1]["win32"]["cursor_client"] == [10.0, 5.0]


def test_render_smoke(ui, fake_glfw, tmp_path, monkeypatch):
    """The crosshairs + text block draw without a GL context (draw-call
    signatures are only checked at runtime)."""
    rec = make_recorder(tmp_path, FakeOverlay())
    monkeypatch.setattr(rec, "_gather_win32", lambda: dict(WIN32_FAKE))
    ui.mouse_pos = (400.0, 300.0)
    imgui.new_frame()
    row = rec.sample_and_record()
    rec.render(row)  # must not raise
    rec.close()


def test_visual_measures_displacement(ui, fake_glfw, tmp_path, monkeypatch):
    """The screenshot probe locates the crosshair marker and reports its
    displacement from the predicted position (client origin + io.MousePos)."""
    # predicted = client origin + io.MousePos = (456+100, 236+50) = (556, 286)
    ui.mouse_pos = (100.0, 50.0)
    # region = predicted -+200 -> origin (356, 86); blob at local (205, 105)
    # -> measured at screen (561, 191) => displacement (+5, -95)
    capture = capture_with_blobs(400, 400, (MAGENTA, 205, 105))
    rec = make_recorder(tmp_path, FakeOverlay(), capture_region=capture)
    monkeypatch.setattr(rec, "_gather_win32", lambda: dict(WIN32_FAKE))
    row = rec.sample_and_record()
    rec.close()
    visual = row["visual"]
    assert visual["predicted"] == [556.0, 286.0]
    # 4x4 blob painted at local (205, 105): centroid at (206.5, 106.5)
    assert visual["magenta"] == [562.5, 192.5]
    assert visual["disp_magenta"] == [6.5, -93.5]
    assert visual["green"] is None


def test_visual_green_fallback(ui, fake_glfw, tmp_path, monkeypatch):
    ui.mouse_pos = (100.0, 50.0)
    capture = capture_with_blobs(400, 400, (GREEN, 207, 102))
    rec = make_recorder(tmp_path, FakeOverlay(), capture_region=capture)
    monkeypatch.setattr(rec, "_gather_win32", lambda: dict(WIN32_FAKE))
    row = rec.sample_and_record()
    rec.close()
    visual = row["visual"]
    assert visual["magenta"] is None
    assert visual["green"] == [564.5, 189.5]  # blob at (207, 102) -> centroid (208.5, 103.5)
    assert visual["disp_green"] == [8.5, -96.5]


def test_visual_no_marker(ui, fake_glfw, tmp_path, monkeypatch):
    ui.mouse_pos = (100.0, 50.0)
    rec = make_recorder(tmp_path, FakeOverlay(), capture_region=lambda *a: bytes(400 * 400 * 4))
    monkeypatch.setattr(rec, "_gather_win32", lambda: dict(WIN32_FAKE))
    row = rec.sample_and_record()
    rec.close()
    visual = row["visual"]
    assert visual["magenta"] is None and visual["green"] is None
    assert "disp_magenta" not in visual


def test_visual_throttled(ui, fake_glfw, tmp_path, monkeypatch):
    """With the default interval, a sample right after the previous one does
    not re-measure (no capture, no visual section)."""
    calls = []
    rec = make_recorder(
        tmp_path,
        FakeOverlay(),
        capture_region=lambda *a: calls.append(a) or bytes(400 * 400 * 4),
        measure_interval=100.0,
    )
    monkeypatch.setattr(rec, "_gather_win32", lambda: dict(WIN32_FAKE))
    ui.mouse_pos = (100.0, 50.0)
    row1 = rec.sample()
    assert "visual" in row1 and len(calls) == 1
    row2 = rec.sample()
    assert "visual" not in row2 and len(calls) == 1
    rec.close()


def test_visual_without_win32_is_skipped(ui, fake_glfw, tmp_path):
    rec = make_recorder(tmp_path, FakeOverlay(), capture_region=lambda *a: (_ for _ in ()).throw(AssertionError("must not capture")))
    row = rec.sample()
    assert "visual" not in row
    rec.close()


def test_dock_mode_in_rows(ui, fake_glfw, tmp_path):
    overlay = FakeOverlay()
    overlay.dock_style_mode = 2
    rec = make_recorder(tmp_path, overlay)
    row = rec.sample()
    assert row["dock_mode"] == 2
    rec.close()
