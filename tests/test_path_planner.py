"""Segmented planner scenarios: routes, hazards, budgets, determinism."""

from __future__ import annotations

from pyglm.glm import ivec2

from gtools.baked.items import DIRT, MAIN_DOOR
from gtools.core.growtopia.physics.controller import HITBOX, PlayerController
from gtools.core.growtopia.physics.pathfinding import SegmentedPathfinder
from gtools.core.growtopia.physics.pathfinding.types import PlanStatus, SegmentKind
from gtools.core.growtopia.world import Tile, TileFlags, World

FLOOR_Y = 8
STAND_Y = FLOOR_Y * 32 - HITBOX[1]
LAVA = 4
DEATH_SPIKES = 162


def make_world(extras=(), *, width=30, floor_y=FLOOR_Y, door=True):
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, floor_y)) for x in range(width)]
    if door:
        tiles.append(Tile(fg_id=MAIN_DOOR, pos=ivec2(1, floor_y - 1)))
    tiles.extend(Tile(fg_id=item_id, pos=ivec2(x, y), flags=flags) for item_id, x, y, flags in extras)
    return World.from_tiles(tiles)


def spawn(world, tx=4, *, y=STAND_Y):
    world.set_local_player(1)
    controller = PlayerController(world, net_id=1, send=None, auto_respawn=False)
    return controller.spawn(tx * 32 + 6.0, y)


def plan(world, tx, ty, start_tx=4, **kwargs):
    controller = spawn(world, start_tx)
    pathfinder = SegmentedPathfinder(controller, **kwargs)
    return controller, pathfinder, pathfinder.plan_to_tile(tx, ty)


def test_flat_path_is_found_and_oracle_validated():
    controller, pathfinder, result = plan(make_world(), 20, FLOOR_Y - 1, validate=True)
    assert result.status == PlanStatus.FOUND
    assert result.path is not None and result.path.segments
    assert result.path.total_ticks > 0
    assert result.path.damage_hits == 0
    # the oracle replay inside `_plan` must agree; no downgrade to PARTIAL
    assert result.reason == ""
    assert pathfinder.goal_reached(result.path.end)


def test_plan_is_deterministic():
    world = make_world()
    _, _, first = plan(world, 18, FLOOR_Y - 1)

    world = make_world()
    _, _, second = plan(world, 18, FLOOR_Y - 1)
    assert first.status == second.status == PlanStatus.FOUND
    assert first.path.kinds() == second.path.kinds()
    assert first.path.total_ticks == second.path.total_ticks


def test_wall_requires_a_jump():
    wall = [(DIRT, 10, y, TileFlags.NONE) for y in range(FLOOR_Y - 3, FLOOR_Y)]
    _, _, result = plan(make_world(extras=wall), 15, FLOOR_Y - 1)
    assert result.status == PlanStatus.FOUND
    assert any(kind in (SegmentKind.JUMP_OVER, SegmentKind.JUMP_UP) for kind in result.path.kinds())


def test_deadly_wall_has_no_safe_route():
    wall = [(DEATH_SPIKES, 10, y, TileFlags.NONE) for y in range(FLOOR_Y - 4, FLOOR_Y)]
    _, _, result = plan(make_world(extras=wall), 15, FLOOR_Y - 1)
    assert result.status == PlanStatus.NO_SAFE_ROUTE
    assert result.path is None
    assert result.nodes_expanded >= 1


def test_damaging_is_not_lethal_and_route_exists():
    extras = [(LAVA, 10, FLOOR_Y - 1, TileFlags.NONE)] + [(DIRT, x, FLOOR_Y - 2, TileFlags.NONE) for x in range(8, 13)]
    _, _, result = plan(make_world(extras=extras), 14, FLOOR_Y - 1)
    assert result.status == PlanStatus.FOUND
    assert result.path is not None


def test_expansion_budget_returns_partial():
    _, _, result = plan(make_world(width=80), 60, FLOOR_Y - 1, max_expansions=1)
    assert result.status == PlanStatus.BUDGET
    assert result.path is not None
    assert result.nodes_expanded <= 1


def test_time_budget_is_reported():
    _, _, result = plan(make_world(width=80), 60, FLOOR_Y - 1, time_budget_ms=1.0)
    assert result.status == PlanStatus.BUDGET
    assert result.elapsed_ms >= 0.0


def test_segments_replay_to_their_recorded_ends():
    """Regression: the parent chain must stay exact.

    A* once stored parents in a tile-keyed dict; when a second, *more exact*
    state landed on an already-expanded tile key, the child node's parent was
    swapped and replaying from the start diverged from the recorded segment
    ends (the oracle inside ``_plan`` caught it as ``PARTIAL``).  Parents are
    node objects now, so every segment must replay from its own start to
    exactly its recorded end, and consecutive segments must join.
    """

    controller, pathfinder, result = plan(make_world(width=40), 28, FLOOR_Y - 1)
    assert result.status == PlanStatus.FOUND
    path = result.path
    assert len(path.segments) >= 2

    evaluator = pathfinder.evaluator
    state = path.segments[0].start.clone()
    for index, segment in enumerate(path.segments):
        assert state.grounded == segment.start.grounded, f"segment {index}: start stance"
        assert (state.x, state.y) == (segment.start.x, segment.start.y), f"segment {index}: not contiguous"
        evaluator.simulate(state, segment.frames)
        assert (state.x, state.y) == (segment.end.x, segment.end.y), f"segment {index}: replay end"
        assert (state.vx, state.vy) == (segment.end.vx, segment.end.vy), f"segment {index}: replay velocity"

    assert pathfinder.goal_reached(state)
