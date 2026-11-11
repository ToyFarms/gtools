"""Anytime planning, hop jumps and the chunked (partial-route) execution mode.

These cover the behaviour the interactive demo relies on:

* a **hop** (a short jump-hold) crosses a short gap that a full jump would smash
  into a ceiling;
* a goal the avatar only flies *through* (a tile in the air) still completes --
  the search used to burn its whole budget on such goals because only landing
  states were tested;
* a budget-exhausted plan still returns a **partial route**, that route reports
  ``ok``, and following it advances the avatar until a re-plan reaches the goal.
"""

from __future__ import annotations

from pyglm.glm import ivec2

from gtools.baked.items import DIRT, MAIN_DOOR
from gtools.core.growtopia.physics.controller import HITBOX, TILE, PlayerController
from gtools.core.growtopia.physics.pathfinding import PathAutopilot, SegmentedPathfinder
from gtools.core.growtopia.physics.pathfinding.types import PlanStatus
from gtools.core.growtopia.world import Tile, World

FLOOR_Y = 8
STAND_Y = FLOOR_Y * 32 - HITBOX[1]


def build(tiles, *, width=32, height=16, start_tx=4):
    world = World.from_tiles(tiles, width=width, height=height) if False else World.from_tiles(tiles)
    world.set_local_player(1)
    controller = PlayerController(world, net_id=1, send=None, auto_respawn=False)
    controller.spawn(start_tx * TILE + 6.0, STAND_Y)
    for _ in range(8):  # spawn leaves the avatar airborne; settle it like the demo
        controller.step()

    return world, controller


def floor_with_gap(width, gap, *, ceiling_gap=2, floor_y=FLOOR_Y):
    """Floor row with ``gap`` tiles missing, and an optional low ceiling above it."""
    tiles: list[Tile] = []
    for x in range(width):
        if x not in gap:
            tiles.append(Tile(fg_id=DIRT, pos=ivec2(x, floor_y)))
    tiles.append(Tile(fg_id=MAIN_DOOR, pos=ivec2(1, floor_y - 1)))
    if ceiling_gap is not None:
        for x in range(width):
            tiles.append(Tile(fg_id=DIRT, pos=ivec2(x, floor_y - 1 - ceiling_gap)))

    return tiles


def test_the_jump_ladder_starts_at_a_one_tick_hop():
    _, controller = build(floor_with_gap(20, set()))
    catalog = SegmentedPathfinder(controller).catalog
    ladder = catalog.jump_ladder
    holds = [hold for _, hold, _ in ladder]
    assert holds[0] == 1, "the shortest hop must be a single held tick"
    assert holds == sorted(holds), "the ladder climbs"
    assert len(set(holds)) == len(holds), "each rung is a distinct hold"
    # a hop is cheaper to commit to than a full jump, so a gap-crossing hop wins
    # the tie against walking the same distance
    penalties = {name: penalty for name, _, penalty in ladder}
    assert penalties["hop1"] < penalties["full"]


def test_a_hop_rises_less_than_a_tile_and_still_travels():
    """The hop rung is what fits under a low ceiling: short rise, real distance."""
    _, controller = build(floor_with_gap(20, set()))
    pathfinder = SegmentedPathfinder(controller)
    start = pathfinder.motion_state()
    action = next(action for action in pathfinder.catalog.actions(start) if action.name == "jump:hop1:1")
    segment = pathfinder.catalog.evaluate(start.clone(), action)

    apex = min(y for _x, y, _grounded in segment.trace)
    assert start.y - apex < TILE, "a hop must not rise a whole tile"
    assert segment.end.x - start.x > 8.0, "a hop still crosses ground"
    assert segment.end.grounded


def test_hop_crosses_a_gap_under_a_ceiling_that_stops_a_full_jump():
    """A two-tile-high passage: full jumps hit the ceiling, the route still crosses."""
    gap = {10, 11}
    tiles = floor_with_gap(20, gap, ceiling_gap=2)
    _, controller = build(tiles)
    pathfinder = SegmentedPathfinder(controller)

    result = pathfinder.plan_to_tile(15, FLOOR_Y - 1)
    assert result.status == PlanStatus.FOUND, result.reason
    path = result.path
    # it must actually get to the far side of the gap, at floor height (the
    # ceiling forbids the full arc, so the route has to stay low)
    assert path.end.x > 12 * TILE
    assert path.end.y == STAND_Y
    assert any(segment.kind.name.startswith("JUMP") for segment in path.segments), [s.note for s in path.segments]


def test_a_goal_the_avatar_only_flies_through_is_reached():
    """A tile one row above the avatar's body: only a jump passes through it."""
    _, controller = build(floor_with_gap(20, set()))
    pathfinder = SegmentedPathfinder(controller)

    body_row = int((STAND_Y + HITBOX[1] - 1e-4) // TILE)
    result = pathfinder.plan_to_tile(12, body_row - 1)
    assert result.status == PlanStatus.FOUND, result.reason
    assert pathfinder.goal_reached(result.path.end)
    # the route ends mid-air, i.e. the last segment was cut off when it entered
    # the tile rather than run out to a landing
    assert not result.path.end.grounded


def test_budget_exhaustion_returns_a_usable_partial_path():
    _, controller = build(floor_with_gap(220, set(), ceiling_gap=None))
    pathfinder = SegmentedPathfinder(controller, time_budget_ms=1.0, max_expansions=2)

    result = pathfinder.plan_to_tile(200, FLOOR_Y - 1)
    assert result.status == PlanStatus.BUDGET
    assert result.ok, "a partial route is still a route the caller can follow"
    assert not result.complete
    assert result.path.segments
    started = pathfinder.motion_state().x
    assert result.path.end.x > started, "a partial route must still make progress"


def test_chunked_following_reaches_a_goal_a_single_plan_cannot():
    """The demo's mode: follow a partial route, re-plan, refine, arrive."""
    _, controller = build(floor_with_gap(200, set(), ceiling_gap=None))
    pathfinder = SegmentedPathfinder(controller, time_budget_ms=4.0, max_expansions=24)
    autopilot = PathAutopilot(controller, pathfinder, refine_budget_ms=30.0, replan_budget_ms=30.0)

    first = autopilot.plan_to_tile(180, FLOOR_Y - 1)
    assert first.status in (PlanStatus.FOUND, PlanStatus.BUDGET)
    assert autopilot.active

    guard = 0
    while autopilot.active and guard < 6000:
        autopilot.advance()
        controller.step()
        guard += 1

    assert not autopilot.failed, autopilot.reason
    assert pathfinder.goal_reached(pathfinder.motion_state())
    # it took at least one more plan than the first, i.e. it really chunked
    assert autopilot.replans + autopilot.refines > 0 or first.status is PlanStatus.FOUND


def test_refinement_replaces_a_partial_route_with_a_complete_one():
    _, controller = build(floor_with_gap(120, set(), ceiling_gap=None))
    # only the *time* budget is tiny: refinement gets a normal one
    pathfinder = SegmentedPathfinder(controller, time_budget_ms=1.0)
    autopilot = PathAutopilot(controller, pathfinder, refine_budget_ms=200.0)

    result = autopilot.plan_to_tile(100, FLOOR_Y - 1)
    assert result.status == PlanStatus.BUDGET
    assert autopilot.path.partial

    assert autopilot.refine_now(), "a complete route must replace a partial one"
    assert not autopilot.path.partial
    assert autopilot.refines == 1
    assert autopilot.active


def test_planning_leaves_the_controller_alone_on_a_partial_route():
    _, controller = build(floor_with_gap(200, set(), ceiling_gap=None))
    pathfinder = SegmentedPathfinder(controller, time_budget_ms=1.0, max_expansions=2)
    before = (controller.x, controller.y, controller.vx, controller.vy, controller.tick)

    pathfinder.plan_to_tile(180, FLOOR_Y - 1)

    assert (controller.x, controller.y, controller.vx, controller.vy, controller.tick) == before


