"""Differential fuzz: ``FastEvaluator`` vs the real ``PlayerController``.

The fast kernel is the performance mirror of ``PlayerController._simulate``; this
suite is the correctness gate described in ``docs/pathfinding-plan.md`` §8.5.  Both
paths are driven with the same inputs and compared field by field after **every**
tick.  Any divergence fails with the tick number and the field, so a regression is
localised immediately.

The scenarios cover every mechanic the controller implements: walking/jumping,
walls, ceilings, all three collision overrides, water/swim/floaties/vehicles,
wind, mud, ice, radial bounce, trampolines, steam launchers, climb grabs,
gravity wells, antigravity fields, snow/hay/mud jump reduction, and the separate
**deadly** (kill latch) and **damaging** (X knockback / Y -800 launch + slip)
classes.
"""

from __future__ import annotations

import random

import pytest
from pyglm.glm import ivec2

from gtools.baked.items import (
    CLIMBING_BOOTS,
    CLIMBING_WALL,
    DIRT,
    GRAVITY_WELL,
    HAY,
    HYPERTECH_ANTIGRAVITY_FIELD,
    ICE_CRUST_BLOCK,
    ICE_SKATES_OF_WINTER,
    JET_SKI,
    LEGENDARY_WINGS,
    MAIN_DOOR,
    MUSHROOM,
    PARASOL,
    PINBALL_BUMPER,
    SEA_MONSTER_FLOATIE,
    SLIPPERY_FLAG_POLE,
    SNOW_BLOCK,
    SNOWSHOES,
    STEAM_LAUNCHER,
    STEAM_VENT,
    WINTER_WIND,
)
from gtools.core.growtopia.physics.controller import HITBOX, PlayerController
from gtools.core.growtopia.physics.pathfinding.fastkernel import FastEvaluator
from gtools.core.growtopia.physics.pathfinding.profile import CapabilityProfile
from gtools.core.growtopia.physics.pathfinding.snapshot import WorldSnapshot
from gtools.core.growtopia.player import CharacterFlags, Clothing, Player
from gtools.core.growtopia.world import Tile, TileFlags, World

FLOOR_Y = 8
STAND_Y = FLOOR_Y * 32 - HITBOX[1]
SPAWN_TX = 4

LAVA = 4
ACID = 726
CACTUS = 330
DEATH_SPIKES = 162
STORM_CLOUD = 7202
MUD_PUDDLE = 8300
ONE_WAY_BLOCK = 3796
WOODEN_PLATFORM = 102
COSMIC_RAIN = 4530
TREASURE_CHEST = 596
EVIL_EYE = 1226

FIELDS = (
    "x",
    "y",
    "vx",
    "vy",
    "frac_x",
    "frac_y",
    "grounded",
    "sliding",
    "in_water",
    "water_float",
    "mud",
    "left_ground",
    "damage_slip",
    "climbing",
    "double_jumped",
    "killed",
    "facing_right",
)


def make_world(width=40, *, extras=(), floor_y=FLOOR_Y, door=True):
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, floor_y)) for x in range(width)]
    if door:
        tiles.append(Tile(fg_id=MAIN_DOOR, pos=ivec2(1, floor_y - 1)))
    tiles.extend(Tile(fg_id=item_id, pos=ivec2(x, y), flags=flags) for item_id, x, y, flags in extras)
    return World.from_tiles(tiles)


class Pair:
    """A live controller and its fast-kernel mirror, sharing one initial state."""

    def __init__(self, world, *, tx=SPAWN_TX, y=STAND_Y, clothing=None, flags=None):
        world.players[1] = Player(net_id=1, clothing=clothing or Clothing())
        self.world = world
        self.controller = PlayerController(world, net_id=1, send=None, auto_respawn=False)
        self.controller.spawn(tx * 32 + 6.0, y)
        if flags is not None:
            self.controller.state.flags = flags

        self.profile = CapabilityProfile.from_controller(self.controller)
        self.snapshot = WorldSnapshot(world)
        self.fast = FastEvaluator(self.snapshot, self.profile)
        self.motion = self.fast.state_from_controller(self.controller)
        self.ticks = 0

    def tick(self, direction=0, jump=False):
        self.controller.set_input(left=direction < 0, right=direction > 0, jump=jump)
        self.controller.step()
        self.fast.simulate_tick(self.motion, direction, jump)
        self.ticks += 1
        self.assert_equal()

    def run(self, program):
        for direction, jump, count in program:
            for _ in range(count):
                self.tick(direction, jump)

    def assert_equal(self):
        for name in FIELDS:
            live = getattr(self.controller, name)
            fast = getattr(self.motion, name)
            assert fast == live, f"tick {self.ticks}: {name} {fast!r} != {live!r}"
        assert self.motion.time_ms == self.controller.time_ms, f"tick {self.ticks}: time_ms"


def test_flat_walk_jump_and_cut():
    pair = Pair(make_world())
    pair.run([(1, False, 30), (1, True, 4), (1, False, 40), (0, False, 20), (1, True, 40), (-1, False, 30), (-1, True, 2), (-1, False, 30)])
    assert pair.controller.x > SPAWN_TX * 32


def test_walls_and_ceiling():
    world = make_world(extras=[(DIRT, 12, y, TileFlags.NONE) for y in range(3, FLOOR_Y)])
    pair = Pair(world)
    pair.run([(1, False, 80), (0, True, 40), (1, True, 30)])

    ceiling = make_world(width=24, extras=[(DIRT, x, 3, TileFlags.NONE) for x in range(6, 12)])
    pair = Pair(ceiling, tx=7, y=5 * 32)
    pair.run([(0, True, 40), (1, True, 10), (1, False, 20)])


@pytest.mark.parametrize(
    ("item_id", "on", "spawn_tx", "spawn_y", "program"),
    [
        (WOODEN_PLATFORM, False, 4, 4 * 32, [(0, True, 40), (1, False, 40)]),
        (WOODEN_PLATFORM, False, 4, 3 * 32, [(1, False, 40), (0, True, 30)]),
        (ONE_WAY_BLOCK, False, 4, STAND_Y, [(1, False, 60)]),
        (ONE_WAY_BLOCK, True, 4, STAND_Y, [(1, False, 60)]),
        (COSMIC_RAIN, False, 4, 4 * 32, [(0, True, 40), (1, False, 40)]),
        (COSMIC_RAIN, False, 4, STAND_Y, [(0, False, 10), (1, False, 40)]),
        (TREASURE_CHEST, False, 4, STAND_Y, [(1, False, 40)]),
        (EVIL_EYE, False, 4, STAND_Y, [(1, False, 40)]),
        (EVIL_EYE, True, 4, STAND_Y, [(1, False, 40)]),
    ],
    ids=["platform-land", "platform-rise", "oneway-front", "oneway-back", "jumpdown-land", "jumpdown-fall", "collide-if-off", "collide-if-on-off", "collide-if-on-on"],
)
def test_collision_overrides(item_id, on, spawn_tx, spawn_y, program):
    flags = TileFlags.IS_ON if on else TileFlags.NONE
    extras = [(item_id, 4, FLOOR_Y - 1, flags)]
    if item_id in (WOODEN_PLATFORM, COSMIC_RAIN):
        extras = [(item_id, x, 5, flags) for x in range(3, 8)]
    pair = Pair(make_world(extras=extras), tx=spawn_tx, y=spawn_y)
    pair.run(program)


def test_water_swim_floatie_and_vehicle():
    pool = [(STEAM_VENT, x, row, TileFlags.IS_WET) for x in range(8, 14) for row in range(1, FLOOR_Y)]
    water = make_world(extras=pool)
    pair = Pair(water, tx=6, y=4 * 32)
    pair.run([(1, False, 30), (0, False, 20), (0, True, 30), (1, True, 10), (1, False, 40), (-1, True, 30), (-1, False, 30)])

    pair = Pair(make_world(extras=pool), tx=6, y=4 * 32, clothing=Clothing(neck=SEA_MONSTER_FLOATIE))
    pair.run([(1, False, 40), (0, True, 30), (0, False, 40)])

    pair = Pair(make_world(extras=pool), tx=6, y=4 * 32, clothing=Clothing(shoes=JET_SKI))
    pair.run([(1, False, 40), (0, True, 30), (1, False, 40)])


def test_wind_mud_ice_and_slow_fall():
    wind = make_world(extras=[(WINTER_WIND, x, FLOOR_Y - 1, TileFlags.NONE) for x in range(6, 14)])
    pair = Pair(wind)
    pair.run([(0, False, 20), (1, False, 40), (-1, False, 40), (0, False, 20)])

    flipped = make_world(extras=[(WINTER_WIND, x, FLOOR_Y - 1, TileFlags.FLIPPED_X) for x in range(6, 14)])
    pair = Pair(flipped)
    pair.run([(0, False, 20), (1, False, 40), (-1, False, 40)])

    mud = make_world(extras=[(MUD_PUDDLE, x, FLOOR_Y - 1, TileFlags.NONE) for x in range(6, 12)])
    pair = Pair(mud)
    pair.run([(1, False, 30), (0, True, 20), (1, True, 20), (0, False, 20)])

    ice = make_world(extras=[(ICE_CRUST_BLOCK, x, FLOOR_Y, TileFlags.NONE) for x in range(6, 14)])
    pair = Pair(ice)
    pair.run([(1, False, 30), (0, False, 30), (-1, False, 30)])

    pair = Pair(make_world(extras=[(ICE_CRUST_BLOCK, x, FLOOR_Y, TileFlags.NONE) for x in range(6, 14)]), clothing=Clothing(shoes=ICE_SKATES_OF_WINTER))
    pair.run([(1, False, 30), (0, False, 30)])

    for clothing in (Clothing(hand=PARASOL), Clothing(back=LEGENDARY_WINGS)):
        pair = Pair(make_world(), tx=4, y=3 * 32, clothing=clothing)
        pair.run([(0, True, 60), (1, True, 20), (0, False, 30)])


def test_bounce_trampoline_and_steam():
    for item_id in (PINBALL_BUMPER, MUSHROOM):
        for flags in (TileFlags.NONE, TileFlags.IS_ON):
            pair = Pair(make_world(extras=[(item_id, 4, FLOOR_Y - 1, flags)]), tx=4, y=4 * 32)
            pair.run([(0, False, 40), (1, False, 40), (0, True, 30)])

    pair = Pair(make_world(extras=[(STEAM_LAUNCHER, 4, FLOOR_Y - 1, TileFlags.IS_ON)]), tx=4, y=4 * 32)
    pair.run([(0, False, 40), (1, False, 30), (0, True, 20)])
    # the launch clears IS_ON in the live world; the fast kernel records an override
    idx = pair.snapshot.grid.index(4, FLOOR_Y - 1)
    assert idx in pair.motion.flag_overrides


def test_climb_grab():
    wall = make_world(extras=[(CLIMBING_WALL, 6, y, TileFlags.NONE) for y in range(2, FLOOR_Y)])
    pair = Pair(wall, tx=6, y=3 * 32, clothing=Clothing(shoes=CLIMBING_BOOTS))
    pair.run([(0, False, 40), (0, True, 2), (0, False, 20), (0, True, 30), (1, False, 30)])

    # without the gear the wall is solid and no grab happens
    pair = Pair(wall, tx=6, y=3 * 32)
    pair.run([(0, False, 40), (1, False, 30)])


def test_gravity_well_and_antigravity():
    for flags in (TileFlags.IS_ON, TileFlags.NONE):
        well = make_world(extras=[(GRAVITY_WELL, 8, FLOOR_Y - 3, flags)])
        pair = Pair(well, tx=5, y=3 * 32)
        pair.run([(0, False, 30), (1, False, 30), (0, True, 20), (0, False, 30)])

    antigrav = make_world(extras=[(HYPERTECH_ANTIGRAVITY_FIELD, 4, FLOOR_Y - 3, TileFlags.NONE)])
    pair = Pair(antigrav, tx=4, y=4 * 32)
    pair.run([(0, False, 30), (0, True, 30), (1, True, 30), (0, False, 40)])

    pole = make_world(extras=[(SLIPPERY_FLAG_POLE, 4, FLOOR_Y - 3, TileFlags.NONE)])
    pair = Pair(pole, tx=4, y=4 * 32)
    pair.run([(0, False, 30), (0, True, 30), (1, True, 20)])


def test_jump_reduction_surfaces():
    cases = [
        (HAY, Clothing()),
        (SNOW_BLOCK, Clothing()),
        (SNOW_BLOCK, Clothing(shoes=SNOWSHOES)),
    ]
    for item_id, clothing in cases:
        extras = [(item_id, 4, FLOOR_Y - 1, TileFlags.NONE)]
        pair = Pair(make_world(extras=extras), tx=4, clothing=clothing)
        pair.run([(0, True, 30), (0, False, 20), (1, True, 20)])
        assert pair.controller.y <= STAND_Y


@pytest.mark.parametrize(
    ("item_id", "tile_flags", "expected"),
    [
        (LAVA, TileFlags.NONE, "damage"),
        (ACID, TileFlags.NONE, "damage"),
        (CACTUS, TileFlags.NONE, "damage"),
        (STORM_CLOUD, TileFlags.IS_ON, "damage"),
        (STEAM_VENT, TileFlags.IS_ON, "damage"),
        (DEATH_SPIKES, TileFlags.NONE, "deadly"),
    ],
    ids=["lava", "acid", "cactus", "storm-cloud", "steam-vent", "death-spikes"],
)
def test_hazards(item_id, tile_flags, expected):
    extras = [(item_id, 8, FLOOR_Y - 1, tile_flags)]
    pair = Pair(make_world(extras=extras))
    pair.run([(1, False, 100), (0, False, 30), (0, True, 20)])
    if expected == "deadly":
        assert pair.controller.killed
        assert pair.motion.killed
    else:
        assert not pair.controller.killed
        assert not pair.motion.killed

    # IGNORE_LAVA / IGNORE_SPIKES bypasses are profile-driven, not assumptions
    if expected == "deadly":
        pair = Pair(make_world(extras=extras), flags=CharacterFlags.IGNORE_SPIKES)
        pair.run([(1, False, 80)])
        assert not pair.controller.killed
    else:
        pair = Pair(make_world(extras=extras), flags=CharacterFlags.IGNORE_LAVA)
        pair.run([(1, False, 60), (0, False, 20)])


def test_random_mixed_scenes():
    """Seeded fuzz over a mixed world and random input programs."""
    rng = random.Random(20241111)
    scenery = [
        (DIRT, 10, FLOOR_Y - 1, TileFlags.NONE),
        (DIRT, 16, FLOOR_Y - 2, TileFlags.NONE),
        (WOODEN_PLATFORM, 20, 5, TileFlags.NONE),
        (ONE_WAY_BLOCK, 14, FLOOR_Y - 1, TileFlags.NONE),
        (COSMIC_RAIN, 22, 5, TileFlags.NONE),
        (MUD_PUDDLE, 9, FLOOR_Y - 1, TileFlags.NONE),
        (ICE_CRUST_BLOCK, 24, FLOOR_Y, TileFlags.NONE),
        (WINTER_WIND, 26, FLOOR_Y - 1, TileFlags.NONE),
        (PINBALL_BUMPER, 28, FLOOR_Y - 1, TileFlags.NONE),
        (MUSHROOM, 30, FLOOR_Y - 1, TileFlags.NONE),
        (CACTUS, 18, FLOOR_Y - 1, TileFlags.NONE),
        (LAVA, 33, FLOOR_Y - 1, TileFlags.NONE),
        (GRAVITY_WELL, 12, 4, TileFlags.IS_ON),
        (EVIL_EYE, 35, FLOOR_Y - 1, TileFlags.IS_ON),
    ]
    clothing_options = [
        Clothing(),
        Clothing(hand=PARASOL),
        Clothing(back=LEGENDARY_WINGS),
        Clothing(shoes=JET_SKI),
        Clothing(shoes=CLIMBING_BOOTS),
        Clothing(neck=SEA_MONSTER_FLOATIE),
    ]
    flag_options = [CharacterFlags.NONE, CharacterFlags.DOUBLE_JUMP, CharacterFlags.IGNORE_LAVA, CharacterFlags.IGNORE_SPIKES, CharacterFlags.NOCLIP]

    for _ in range(12):
        world = make_world(width=38, extras=scenery)
        pair = Pair(
            world,
            tx=rng.randrange(2, 10),
            y=rng.randrange(2, 7) * 32,
            clothing=rng.choice(clothing_options),
            flags=rng.choice(flag_options),
        )
        for _ in range(6):
            pair.run([(rng.choice((-1, 0, 1)), rng.random() < 0.4, rng.randrange(5, 40))])


def test_random_terrain_fuzz():
    rng = random.Random(7)
    palette = [
        DIRT,
        DIRT,
        DIRT,
        WOODEN_PLATFORM,
        ONE_WAY_BLOCK,
        COSMIC_RAIN,
        MUD_PUDDLE,
        ICE_CRUST_BLOCK,
        WINTER_WIND,
        PINBALL_BUMPER,
        MUSHROOM,
        CACTUS,
        LAVA,
        ACID,
        TREASURE_CHEST,
        EVIL_EYE,
        STEAM_VENT,
    ]
    clothing_options = [Clothing(), Clothing(hand=PARASOL), Clothing(shoes=JET_SKI), Clothing(neck=SEA_MONSTER_FLOATIE)]
    flag_options = [CharacterFlags.NONE, CharacterFlags.NONE, CharacterFlags.DOUBLE_JUMP, CharacterFlags.IGNORE_LAVA]

    for _ in range(10):
        width = rng.randrange(20, 34)
        tiles = [Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(width)]
        tiles.append(Tile(fg_id=MAIN_DOOR, pos=ivec2(1, FLOOR_Y - 1)))
        for _ in range(rng.randrange(8, 22)):
            tx = rng.randrange(2, width)
            ty = rng.randrange(2, FLOOR_Y)
            tiles.append(Tile(fg_id=rng.choice(palette), pos=ivec2(tx, ty), flags=TileFlags.IS_ON if rng.random() < 0.4 else TileFlags.NONE))
        world = World.from_tiles(tiles)
        pair = Pair(
            world,
            tx=rng.randrange(2, 6),
            y=rng.randrange(2, 7) * 32,
            clothing=rng.choice(clothing_options),
            flags=rng.choice(flag_options),
        )
        for _ in range(8):
            pair.run([(rng.choice((-1, 0, 1)), rng.random() < 0.45, rng.randrange(3, 30))])


def test_oracle_matches_fast_kernel():
    """The real controller on a ProbeWorld and the fast kernel agree exactly."""
    from gtools.core.growtopia.physics.pathfinding.oracle import ControllerOracle

    cases = [
        (make_world(extras=[(DIRT, 12, y, TileFlags.NONE) for y in range(3, FLOOR_Y)]), [(1, False, 30), (1, True, 30), (-1, False, 30)]),
        (make_world(extras=[(LAVA, 8, FLOOR_Y - 1, TileFlags.NONE)]), [(1, False, 60), (0, False, 20)]),
        (make_world(extras=[(DEATH_SPIKES, 8, FLOOR_Y - 1, TileFlags.NONE)]), [(1, False, 80)]),
    ]
    for world, program in cases:
        pair = Pair(world)
        oracle = ControllerOracle.from_controller(pair.controller, pair.snapshot)
        fast_state = pair.fast.state_from_controller(pair.controller)
        oracle_out = oracle.run(pair.fast.state_from_controller(pair.controller), program)
        fast_out = pair.fast.simulate(fast_state, program)
        assert oracle_out.ticks == fast_out.ticks
        assert oracle_out.damage_hits == fast_out.damage_hits
        assert oracle_out.reason == fast_out.reason
        for name in FIELDS:
            assert getattr(oracle_out.state, name) == getattr(fast_out.state, name), name


def test_kill_latch_is_terminal_for_both():
    pair = Pair(make_world(extras=[(DEATH_SPIKES, 6, FLOOR_Y - 1, TileFlags.NONE)]))
    pair.run([(1, False, 80)])
    assert pair.controller.killed and pair.motion.killed
    # the corpse does not integrate: both stop at the same place
    x, y = pair.controller.x, pair.controller.y
    pair.run([(1, False, 30)])
    assert pair.controller.x == x and pair.controller.y == y
