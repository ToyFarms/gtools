"""The docked-overlay mouse fix.

Regression: when docked, the game window keeps the keyboard focus while the
gui window is hovered. Windows still delivers the cursor moves, but the stock
imgui_bundle GlfwRenderer gates its cursor callback on FOCUSED and feeds
(-1, -1) then -- a position ImGui accepts as valid (its invalid sentinel is
-FLT_MAX, i.e. < -256000), so hover/drags landed at the window's top-left.
"""

from gtools.gui import event as gui_event


class FakeIO:
    def __init__(self):
        self.events = []

    def add_mouse_pos_event(self, x, y):
        self.events.append((x, y))


class FakeRenderer:
    def __init__(self):
        self.io = FakeIO()


def test_callback_forwards_position_unfocused():
    """The docked case: the window is hovered while unfocused -- the real
    position must still reach io (the stock backend sends (-1, -1) here)."""
    renderer = FakeRenderer()
    callback = gui_event.real_mouse_pos_callback(renderer)
    callback(None, 12.5, 34.5)
    assert renderer.io.events == [(12.5, 34.5)]


def test_callback_forwards_every_move():
    renderer = FakeRenderer()
    callback = gui_event.real_mouse_pos_callback(renderer)
    callback(None, 100.0, 5.0)
    callback(None, 101.0, 6.0)
    assert renderer.io.events == [(100.0, 5.0), (101.0, 6.0)]


def test_callback_ignores_arguments_window_and_uses_given_coords():
    """EventRouter chains with (win, xpos, ypos); the callback must feed the
    event's own coordinates, not re-query anything."""
    renderer = FakeRenderer()
    callback = gui_event.real_mouse_pos_callback(renderer)
    callback("not-a-window", -5.5, -9.25)
    assert renderer.io.events == [(-5.5, -9.25)]


def test_feed_cursor_position_hovered(monkeypatch):
    """After a native SetWindowPos (dock/follow) no cursor callback fires:
    the per-frame feed must refresh io with the current cursor position."""
    io = FakeIO()
    window = object()
    monkeypatch.setattr(gui_event.glfw, "get_window_attrib", lambda w, a: True)
    monkeypatch.setattr(gui_event.glfw, "get_cursor_pos", lambda w: (12.5, 34.5))
    gui_event.feed_cursor_position(io, window)
    assert io.events == [(12.5, 34.5)]


def test_feed_cursor_position_not_hovered(monkeypatch):
    """The cursor is over the game while docked: leave io alone so the stale
    position does not register as mouse activity (idle mode stays idle)."""
    io = FakeIO()
    window = object()
    monkeypatch.setattr(gui_event.glfw, "get_window_attrib", lambda w, a: False)
    cursor_calls = []
    monkeypatch.setattr(gui_event.glfw, "get_cursor_pos", lambda w: cursor_calls.append(w))
    gui_event.feed_cursor_position(io, window)
    assert io.events == [] and not cursor_calls
