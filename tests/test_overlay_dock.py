"""The docked placement math (pure; no win32) + the presentation re-sync."""

from gtools.gui import overlay as overlay_module
from gtools.gui.overlay import OverlayController, Rect, docked_rect


def test_docked_pins_to_top_left_with_margin():
    rect = docked_rect(Rect(0, 0, 1366, 768), Rect(0, 0, 1000, 700), margin=8)
    assert (rect.x, rect.y) == (8, 8)
    assert (rect.w, rect.h) == (1000, 700)


def test_docked_clamps_into_the_game_area():
    rect = docked_rect(Rect(100, 50, 1280, 720), Rect(0, 0, 1600, 1000), margin=8)
    assert (rect.w, rect.h) == (1264, 704)


def test_small_game_window_still_fits():
    rect = docked_rect(Rect(0, 0, 640, 480), Rect(0, 0, 1600, 1000), margin=8)
    assert rect.w == 624 and rect.h == 464


def test_refresh_gl_surface_resizes_twice(monkeypatch):
    """The re-sync nudge must send a 1px-out resize and then restore the
    exact current size (two WM_SIZEs, same final geometry)."""
    calls = []

    class FakeUser32:
        def SetWindowPos(self, hwnd, after, x, y, w, h, flags):
            calls.append((w, h))
            return True

    monkeypatch.setattr(overlay_module.glfw, "get_window_size", lambda window: (816, 639))
    monkeypatch.setattr(overlay_module, "user32", FakeUser32())

    controller = OverlayController(gui_title="t")
    controller.set_glfw_window(object())  # any handle: glfw calls are patched
    controller.state.gui_hwnd = 0x50
    controller._refresh_gl_surface()

    assert calls == [(817, 639), (816, 639)]


def test_refresh_gl_surface_skipped_without_glfw_window(monkeypatch):
    class Boom:
        def __getattr__(self, name):
            raise AssertionError("must not be touched")

    monkeypatch.setattr(overlay_module, "user32", Boom())
    controller = OverlayController(gui_title="t")
    controller.state.gui_hwnd = 0x50
    controller._refresh_gl_surface()  # no glfw window: no-op, must not raise
