"""Follower replay and adaptation: world/state/position changes mid-route."""

from __future__ import annotations

from pyglm.glm import ivec2

from gtools.baked.items import DIRT, MAIN_DOOR
from gtools.core.growtopia.physics.controller import HITBOX, PlayerController
from gtools.core.growtopia.physics.pathfinding import (
    PathAutopilot,
    PathEvaluator,
    PathFollower,
    SegmentedPathfinder,
)
from gtools.core.growtopia.physics.pathfinding.types import PlanStatus
from gtools.core.growtopia.world import Tile, World

DEATH_SPIKES = 162

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


class _InputOnlyController:
    """Read-through proxy that fails on any direct attribute write.

    The contract is: pathfinding *observes* the avatar and drives it only with
    ``set_input(left, right, jump)`` + ``step()``.  Every other mutation
    (``x``/``y``/``vx``/``vy``/``grounded``/``state``/...) must be rejected, so a
    plan can never "cheat" by writing the state it wants instead of simulating it.
    """

    def __init__(self, target):
        object.__setattr__(self, "_target", target)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_target"), name)

    def __setattr__(self, name, value):
        raise AssertionError(f"pathfinding wrote controller.{name} = {value!r} directly")


def test_planning_reads_but_never_modifies_the_live_controller():
    _, controller, pathfinder = setup(width=40)
    fields = ("x", "y", "vx", "vy", "frac_x", "frac_y", "time_ms", "tick", "grounded", "left", "right", "jump")
    before = tuple(getattr(controller, name) for name in fields)
    flags = controller.state.flags

    result = pathfinder.plan_to_tile(25, FLOOR_Y - 1)
    assert result.status == PlanStatus.FOUND

    assert tuple(getattr(controller, name) for name in fields) == before
    assert controller.state.flags == flags


def test_follower_drives_the_avatar_only_through_input_and_step():
    _, controller, pathfinder = setup(width=40)
    result = pathfinder.plan_to_tile(25, FLOOR_Y - 1)
    assert result.status == PlanStatus.FOUND

    # any direct write to the controller raises inside PathFollower
    proxy = _InputOnlyController(controller)
    follower = PathFollower(proxy, pathfinder, result.path)

    guard = 0
    while not follower.done and guard < 3000:
        follower.tick_inputs()
        controller.step()
        follower.observe()
        guard += 1
    follower.close()

    assert follower.done and not follower.failed, follower.reason
    assert pathfinder.goal_reached(pathfinder.motion_state())


def test_autopilot_host_loop_drives_only_through_input():
    """The demo's loop shape, headless: ``advance()`` then ``controller.step()``.

    Both the pathfinder and the autopilot are built on a proxy that raises on any
    attribute write, so this covers the whole stack the demo uses: planning reads
    the avatar, execution feeds ``set_input`` and the *physics engine* moves it.
    """
    _, controller, _ = setup(width=40)
    proxy = _InputOnlyController(controller)
    pathfinder = SegmentedPathfinder(proxy)
    autopilot = PathAutopilot(proxy, pathfinder)

    result = autopilot.plan_to_tile(25, FLOOR_Y - 1)
    assert result.status == PlanStatus.FOUND
    assert autopilot.active
    assert autopilot.path is result.path

    guard = 0
    while autopilot.active and guard < 3000:
        autopilot.advance()
        controller.step()
        guard += 1

    assert not autopilot.failed, autopilot.reason
    assert autopilot.status.startswith("goal reached")
    # the finished route stays available for an overlay
    assert autopilot.path is not None and len(autopilot.path.segments) == len(result.path.segments)
    assert pathfinder.goal_reached(pathfinder.motion_state())


def test_autopilot_cancel_resets_input_without_touching_the_avatar():
    _, controller, pathfinder = setup(width=40)
    autopilot = PathAutopilot(controller, pathfinder)
    autopilot.plan_to_tile(25, FLOOR_Y - 1)

    for _ in range(5):
        if autopilot.advance():
            controller.step()
    autopilot.advance()
    controller.step()

    before = (controller.x, controller.y, controller.vx, controller.vy)
    autopilot.cancel("stopped")

    assert not autopilot.active
    assert autopilot.status == "stopped"
    assert (controller.x, controller.y, controller.vx, controller.vy) == before
    assert not controller.left and not controller.right and not controller.jump


def test_autopilot_reports_an_unreachable_goal_without_starting():
    spikes = [(DEATH_SPIKES, 10, y, 0) for y in range(FLOOR_Y - 4, FLOOR_Y)]
    _, controller, pathfinder = setup(width=20, extras=spikes)
    autopilot = PathAutopilot(controller, pathfinder)

    result = autopilot.plan_to_tile(15, FLOOR_Y - 1)
    assert result.status == PlanStatus.NO_SAFE_ROUTE
    assert not autopilot.active
    assert autopilot.path is None
    assert autopilot.status.startswith("NO_SAFE_ROUTE")

