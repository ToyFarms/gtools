"""The docked placement math (pure; no win32)."""

from gtools.gui.overlay import Rect, docked_rect


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
