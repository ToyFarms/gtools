"""Follower replay and adaptation: world/state/position changes mid-route."""

from __future__ import annotations

from pyglm.glm import ivec2

from gtools.baked.items import DIRT, MAIN_DOOR
from gtools.core.growtopia.physics.controller import HITBOX, PlayerController
from gtools.core.growtopia.physics.pathfinding import PathEvaluator, PathFollower, SegmentedPathfinder
from gtools.core.growtopia.physics.pathfinding.types import PlanStatus
from gtools.core.growtopia.world import Tile, World

FLOOR_Y = 8
STAND_Y = FLOOR_Y * 32 - HITBOX[1]


def make_world(width=30, extras=()):
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(width)]
    tiles.append(Tile(fg_id=MAIN_DOOR, pos=ivec2(1, FLOOR_Y - 1)))
    tiles.extend(Tile(fg_id=item_id, pos=ivec2(x, y), flags=flags) for item_id, x, y, flags in extras)
    return World.from_tiles(tiles)


def setup(width=30, extras=(), start_tx=4):
    world = make_world(width, extras)
    world.set_local_player(1)
    controller = PlayerController(world, net_id=1, send=None, auto_respawn=False)
    controller.spawn(start_tx * 32 + 6.0, STAND_Y)
    pathfinder = SegmentedPathfinder(controller)
    return world, controller, pathfinder


def drive(follower, limit=2000):
    ticks = 0
    while not follower.done and ticks < limit:
        follower.step()
        ticks += 1
    follower.close()
    return ticks


def test_follower_reaches_a_flat_goal():
    _, controller, pathfinder = setup()
    result = pathfinder.plan_to_tile(20, FLOOR_Y - 1)
    assert result.status == PlanStatus.FOUND

    follower = PathFollower(controller, pathfinder, result.path)
    ticks = drive(follower)
    assert follower.done and not follower.failed, follower.reason
    assert follower.replans == 0
    assert pathfinder.goal_reached(pathfinder.motion_state())
    assert ticks == result.path.total_ticks


def test_wall_added_mid_route_triggers_replan():
    world, controller, pathfinder = setup(width=40)
    result = pathfinder.plan_to_tile(25, FLOOR_Y - 1)
    follower = PathFollower(controller, pathfinder, result.path)

    for _ in range(20):
        follower.step()
        if follower.done:
            break

    if not follower.done:
        for y in range(FLOOR_Y - 3, FLOOR_Y):
            tile = world.get_tile(18, y)
            world.place_fg(tile, DIRT)

    drive(follower)
    assert follower.done and not follower.failed, follower.reason
    assert follower.replans >= 1
    assert pathfinder.goal_reached(pathfinder.motion_state())


def test_teleport_mid_route_triggers_replan():
    _, controller, pathfinder = setup(width=40)
    result = pathfinder.plan_to_tile(25, FLOOR_Y - 1)
    follower = PathFollower(controller, pathfinder, result.path)

    for _ in range(30):
        follower.step()

    controller.handle_set_pos(6 * 32 + 6.0, STAND_Y)
    drive(follower)
    assert follower.done and not follower.failed, follower.reason
    assert follower.replans >= 1
    assert pathfinder.goal_reached(pathfinder.motion_state())


def test_character_state_change_triggers_replan():
    _, controller, pathfinder = setup(width=40)
    result = pathfinder.plan_to_tile(25, FLOOR_Y - 1)
    follower = PathFollower(controller, pathfinder, result.path)

    for _ in range(15):
        follower.step()

    controller.state.max_velocity = 500.0
    drive(follower)
    assert follower.done and not follower.failed, follower.reason
    assert follower.replans >= 1
    assert pathfinder.goal_reached(pathfinder.motion_state())


def test_path_evaluator_scores_a_valid_path():
    _, controller, pathfinder = setup()
    result = pathfinder.plan_to_tile(15, FLOOR_Y - 1)
    evaluator = PathEvaluator(pathfinder.evaluator)
    valid, cost = evaluator.score(result.path, pathfinder.motion_state())
    assert valid
    assert cost == result.path.total_cost
