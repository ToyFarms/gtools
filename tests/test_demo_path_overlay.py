"""Headless checks for the demo's pathfinding overlay.

The overlay draws into an ImGui window draw list, which works without an OpenGL
context (`imgui.create_context` + `new_frame`), so the whole overlay/menu can be
exercised in a test.  That matters because a wrong draw call is only ever a
runtime `TypeError` -- ``add_rect`` takes ``(p_min, p_max, col, rounding, flags,
thickness)``, and passing a thickness in the flags slot crashes the demo while
importing it does not.
"""

from __future__ import annotations

from collections import deque
from types import SimpleNamespace

import pytest
from imgui_bundle import imgui
from pyglm.glm import ivec2, vec2

from gtools.baked.items import DIRT, MAIN_DOOR
from gtools.core.growtopia.physics.controller import HITBOX, PlayerController
from gtools.core.growtopia.physics.demo import GPUPhysicsDemo, _input_edges, _segment_frames, _tier_color
from gtools.core.growtopia.physics.pathfinding import PathAutopilot, SegmentedPathfinder
from gtools.core.growtopia.world import Tile, World
from gtools.gui.camera import Camera2D

FLOOR_Y = 8
STAND_Y = FLOOR_Y * 32 - HITBOX[1]


@pytest.fixture(scope="module")
def ui():
    imgui.create_context()
    io = imgui.get_io()
    io.display_size = (1280.0, 720.0)
    io.delta_time = 1 / 60
    # no renderer backend in a test: tell ImGui the backend owns the textures, so
    # it does not insist on a built font atlas
    io.backend_flags |= imgui.BackendFlags_.renderer_has_textures

    yield imgui


def make_demo(gap=(10, 11)):
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(30) if x not in gap]
    tiles.append(Tile(fg_id=MAIN_DOOR, pos=ivec2(1, FLOOR_Y - 1)))
    world = World.from_tiles(tiles)
    world.set_local_player(1)
    controller = PlayerController(world, net_id=1, send=None, auto_respawn=False)
    controller.spawn(14.0, STAND_Y)
    for _ in range(8):
        controller.step()

    pathfinder = SegmentedPathfinder(controller, record_search=True)
    autopilot = PathAutopilot(controller, pathfinder)

    demo = GPUPhysicsDemo.__new__(GPUPhysicsDemo)  # no window: overlay code only
    camera = Camera2D(1280, 720)
    camera.zoom = 2.0
    camera.pos = vec2(320.0, 260.0)
    demo.world_renderer = SimpleNamespace(_camera=camera, _image_origin=(0.0, 0.0), mode_3d=False)
    demo.controller = controller
    demo.world = world
    demo.pathfinder = pathfinder
    demo.autopilot = autopilot
    demo.player = SimpleNamespace(clothing=None)
    demo.path_status = "idle"
    demo.show_path = True
    demo.show_path_labels = True
    demo.show_path_trail = True
    demo.show_path_inputs = True
    demo.show_search_nodes = True
    demo.show_search_frontier = True
    demo.show_search_detail = True
    demo._path_trail = deque(maxlen=900)
    demo._hover_search_node = None
    demo._recording_file = None
    demo._recording_path = None
    demo._recording_started_at = 0.0
    demo._recording_ticks = 0
    demo._recording_frames = 0
    demo._recording_events = []

    return demo, controller, pathfinder, autopilot


def test_segment_frames_expand_to_one_entry_per_tick():
    class FakeSegment:
        frames = ((1, True, 3), (0, False, 2), (-1, True, 1))

    assert _segment_frames(FakeSegment) == [(1, True), (1, True), (1, True), (0, False), (0, False), (-1, True)]
    assert _input_edges(_segment_frames(FakeSegment)) == [(0, 1, True), (3, 0, False), (5, -1, True)]


def test_tier_colours_are_distinct_per_action_tier():
    assert _tier_color(0) != _tier_color(1)


def test_jump_segment_is_drawn_as_its_arc_not_as_a_chord():
    """The requirement: a jump must curve, a fall must drop -- the trace, not a chord."""
    demo, _controller, pathfinder, _autopilot = make_demo()
    result = pathfinder.plan_to_tile(20, FLOOR_Y - 1)
    assert result.status.name == "FOUND"
    jump = max(result.path.segments, key=lambda segment: segment.ticks)
    points = demo._segment_polyline(jump)

    assert len(points) == len(jump.trace) >= 2
    # a chord would be a straight line: the real trajectory leaves it (the jump
    # bows up while the straight line between the ends does not)
    chord_mid = (points[0].y + points[-1].y) / 2.0
    actual_mid = points[len(points) // 2].y
    assert actual_mid < chord_mid - 5.0, "the drawn curve must bow above the chord"


def test_overlay_and_menu_draw_without_error(ui):
    demo, controller, pathfinder, autopilot = make_demo()
    autopilot.plan_to_tile(20, FLOOR_Y - 1)
    for _ in range(12):
        autopilot.advance()
        controller.step()
        demo._path_trail.append((controller.x + 10.0, controller.y + 15.0))

    for mouse in ((10.0, 10.0), (640.0, 400.0), (300.0, 300.0)):
        ui.new_frame()
        ui.get_io().mouse_pos = mouse
        ui.begin("host")
        demo.render_path_overlay()
        ui.end()
        ui.begin("Player")
        demo.render_menu()
        ui.end()
        ui.render()

    trace = pathfinder.search_trace
    assert trace is not None and trace.nodes, "search recording must be on for the demo"
    assert trace.passes, "every pass is recorded for the menu"
    assert len(trace.expanded) + len(trace.frontier) == len(trace.nodes)


def test_overlay_survives_an_empty_search_and_a_missing_path(ui):
    """Nothing planned yet: the overlay must not draw (or crash) on stale state."""
    demo, _controller, _pathfinder, _autopilot = make_demo()
    demo.pathfinder.search_trace.reset()
    demo.autopilot.path = None

    ui.new_frame()
    ui.begin("host")
    demo.render_path_overlay()
    ui.end()
    ui.render()
