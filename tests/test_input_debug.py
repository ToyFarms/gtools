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
    )


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
    monkeypatch.setattr(
        rec,
        "_gather_win32",
        lambda: {"gui_hwnd": 0x1234, "cursor_screen": [110.0, 55.0], "cursor_client": [10.0, 5.0]},
    )
    ui.mouse_pos = (400.0, 300.0)
    imgui.new_frame()
    row = rec.sample_and_record()
    rec.render(row)  # must not raise
    rec.close()
