"""One segment kind per controller mechanic.

Each case builds a world that produces the movement method, evaluates the real
catalogue action, and asserts the *observed* classification rather than the
attempted action.
"""

from __future__ import annotations

from pyglm.glm import ivec2

from gtools.baked.items import (
    CLIMBING_BOOTS,
    CLIMBING_WALL,
    DIRT,
    GRAVITY_WELL,
    MAIN_DOOR,
    MUSHROOM,
    PINBALL_BUMPER,
    STEAM_VENT,
    WINTER_WIND,
)
from gtools.core.growtopia.physics.controller import HITBOX, PlayerController
from gtools.core.growtopia.physics.pathfinding.actions import Action, ActionCatalog
from gtools.core.growtopia.physics.pathfinding.fastkernel import FastEvaluator
from gtools.core.growtopia.physics.pathfinding.profile import CapabilityProfile
from gtools.core.growtopia.physics.pathfinding.snapshot import WorldSnapshot
from gtools.core.growtopia.physics.pathfinding.types import SegmentKind
from gtools.core.growtopia.player import Clothing, Player
from gtools.core.growtopia.world import Tile, TileFlags, World

FLOOR_Y = 8
LAVA = 4
STAND_Y = FLOOR_Y * 32 - HITBOX[1]


def make_world(extras=(), *, width=24, floor_y=FLOOR_Y):
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, floor_y)) for x in range(width)]
    tiles.append(Tile(fg_id=MAIN_DOOR, pos=ivec2(1, floor_y - 1)))
    tiles.extend(Tile(fg_id=item_id, pos=ivec2(x, y), flags=flags) for item_id, x, y, flags in extras)
    return World.from_tiles(tiles)


def setup(world, *, x, y, clothing=None, settle=0, flags=None):
    world.players[1] = Player(net_id=1, clothing=clothing or Clothing())
    controller = PlayerController(world, net_id=1, send=None, auto_respawn=False)
    controller.spawn(x, y)
    if flags is not None:
        controller.state.flags = flags
    for _ in range(settle):
        controller.step()

    profile = CapabilityProfile.from_controller(controller)
    snapshot = WorldSnapshot(world)
    evaluator = FastEvaluator(snapshot, profile)
    catalog = ActionCatalog(evaluator)
    state = evaluator.state_from_controller(controller)
    return controller, evaluator, catalog, state, snapshot


def find_action(catalog, state, name):
    return next(action for action in catalog.actions(state) if action.name == name)


def test_walk():
    controller, _, catalog, state, _ = setup(make_world(), x=4 * 32 + 6.0, y=STAND_Y, settle=3)
    segment = catalog.evaluate(state, find_action(catalog, state, "walk:1"))
    assert segment is not None
    assert segment.kind == SegmentKind.WALK
    assert segment.end.x > state.x


def test_jump_over():
    _, _, catalog, state, _ = setup(make_world(), x=4 * 32 + 6.0, y=STAND_Y, settle=3)
    segment = catalog.evaluate(state, find_action(catalog, state, "jump:cut:1"))
    assert segment is not None and segment.kind == SegmentKind.JUMP_OVER


def test_jump_up_onto_platform():
    extras = [(102, x, FLOOR_Y - 3, TileFlags.NONE) for x in range(3, 7)]  # Wooden Platform
    _, _, catalog, state, _ = setup(make_world(extras=extras), x=4 * 32 + 6.0, y=STAND_Y, settle=3)
    segment = catalog.evaluate(state, find_action(catalog, state, "jump:full:0"))
    assert segment is not None and segment.kind == SegmentKind.JUMP_UP
    assert segment.end.y < state.y


def test_fall():
    _, _, catalog, state, _ = setup(make_world(), x=4 * 32 + 6.0, y=2 * 32)
    segment = catalog.evaluate(state, find_action(catalog, state, "air:0"))
    assert segment is not None and segment.kind == SegmentKind.FALL
    assert segment.end.grounded


def test_swim():
    pool = [(STEAM_VENT, 6, row, TileFlags.IS_WET) for row in range(2, FLOOR_Y)]
    _, _, catalog, state, _ = setup(make_world(extras=pool), x=6 * 32 + 6.0, y=32.0)
    segment = catalog.evaluate(state, find_action(catalog, state, "air:0"))
    assert segment is not None and segment.kind == SegmentKind.SWIM
    assert segment.end.in_water


def test_climb():
    wall = [(CLIMBING_WALL, 6, row, TileFlags.NONE) for row in range(2, FLOOR_Y)]
    solid = [(DIRT, 7, row, TileFlags.NONE) for row in range(2, FLOOR_Y)]
    controller, _, catalog, state, _ = setup(
        make_world(extras=wall + solid),
        x=210.0,
        y=4 * 32,
        clothing=Clothing(shoes=CLIMBING_BOOTS),
    )
    segment = catalog.evaluate(state, find_action(catalog, state, "air:1"))
    assert segment is not None and segment.kind == SegmentKind.CLIMB
    assert segment.end.climbing


def test_bounce():
    _, _, catalog, state, _ = setup(make_world(extras=[(PINBALL_BUMPER, 4, FLOOR_Y - 1, TileFlags.NONE)]), x=4 * 32 + 6.0, y=3 * 32)
    segment = catalog.evaluate(state, find_action(catalog, state, "air:0"))
    assert segment is not None and segment.kind == SegmentKind.BOUNCE


def test_bounce_up():
    _, _, catalog, state, _ = setup(make_world(extras=[(MUSHROOM, 4, FLOOR_Y - 1, TileFlags.NONE)]), x=4 * 32 + 6.0, y=3 * 32)
    segment = catalog.evaluate(state, find_action(catalog, state, "air:0"))
    assert segment is not None and segment.kind == SegmentKind.BOUNCE_UP


def test_damage_launch():
    _, _, catalog, state, _ = setup(make_world(extras=[(LAVA, 4, FLOOR_Y - 1, TileFlags.NONE)]), x=4 * 32 + 6.0, y=2 * 32)
    segment = catalog.evaluate(state, find_action(catalog, state, "air:0"))
    assert segment is not None and segment.kind == SegmentKind.DAMAGE_LAUNCH
    assert segment.damage_hits > 0
    assert segment.volatile


def test_wind():
    extras = [(WINTER_WIND, x, FLOOR_Y - 1, TileFlags.NONE) for x in range(3, 7)]
    _, _, catalog, state, _ = setup(make_world(extras=extras), x=4 * 32 + 6.0, y=STAND_Y, settle=3)
    segment = catalog.evaluate(state, find_action(catalog, state, "wait"))
    assert segment is not None and segment.kind == SegmentKind.WIND
    assert segment.end.x > state.x


def test_well():
    _, evaluator, catalog, state, _ = setup(make_world(extras=[(GRAVITY_WELL, 8, 4, TileFlags.IS_ON)]), x=8 * 32 + 6.0, y=2 * 32)
    outcome = evaluator.simulate(state.clone(), ((0, False, 3),))
    assert outcome.used_well
    action = Action("well-probe", ((0, False, 3),))
    assert catalog.classify(outcome, state, action) == SegmentKind.WELL
