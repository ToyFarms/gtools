"""The overlay snap geometry (pure math, no win32)."""

from gtools.gui.overlay import Rect, anchor_rects, apply_snap, snap_anchor

AREA = Rect(0, 0, 1920, 1080)


def test_edge_strips_fill_their_edge():
    name, rect = snap_anchor(Rect(6, 400, 500, 400), AREA)
    assert name == "left"
    assert (rect.x, rect.y, rect.w, rect.h) == (0, 0, 960, 1080)

    name, rect = snap_anchor(Rect(400, 1070, 300, 8), AREA, margin=24)
    assert name == "bottom"
    assert (rect.x, rect.y, rect.w, rect.h) == (0, 540, 1920, 540)


def test_corners_keep_the_window_size():
    name, rect = snap_anchor(Rect(1500, 4, 410, 300), AREA)
    assert name == "top_right"
    assert (rect.w, rect.h) == (410, 300)
    assert (rect.x, rect.y) == (AREA.w - 410, 0)  # aligned inside the area


def test_corners_win_over_strips():
    # within margin of both the left and top edges -> the corner, not a strip
    name, _ = snap_anchor(Rect(8, 6, 400, 300), AREA)
    assert name == "top_left"


def test_free_floating_is_untouched():
    rect = Rect(700, 500, 400, 300)
    name, snapped = snap_anchor(rect, AREA)
    assert name == ""
    assert snapped == rect


def test_all_anchors_exist():
    assert set(anchor_rects(AREA)) == {
        "left", "right", "top", "bottom", "top_left", "top_right", "bottom_left", "bottom_right",
    }
