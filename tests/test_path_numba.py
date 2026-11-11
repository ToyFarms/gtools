"""Cross-backend equality: the pure-Python reference vs the compiled kernel.

``FastEvaluator`` has two backends:

* the readable reference implementation in ``fastkernel.py`` (always available),
* ``numba_kernel.NumbaBackend``, the same algorithm compiled over flat arrays.

``tests/test_path_fastkernel.py`` proves the *default* backend equals the real
``PlayerController`` tick for tick.  This suite proves the two backends are
interchangeable: whenever the compiled kernel is touched, replay the same input
program on both and compare every motion field, the touched-tile cache, the
steam-launcher flag overrides and the whole ``Outcome`` (ticks, reason, bbox,
event flags, tick trace).

The scenarios cover walking/jumping, walls, water + floatie, radial bounce,
trampolines, steam launchers, climbing, wind, damaging tiles and a gravity well
-- i.e. every branch that has a hand-written compiled twin.
"""

from __future__ import annotations

import pytest
from pyglm.glm import ivec2

numba = pytest.importorskip("numba")

from gtools.baked.items import (
    CLIMBING_BOOTS,
    CLIMBING_WALL,
    DIRT,
    GRAVITY_WELL,
    MAIN_DOOR,
    MUSHROOM,
    PINBALL_BUMPER,
    SEA_MONSTER_FLOATIE,
    STEAM_LAUNCHER,
    STEAM_VENT,
    WINTER_WIND,
)
from gtools.core.growtopia.physics.controller import HITBOX, PlayerController
from gtools.core.growtopia.physics.pathfinding import numba_kernel
from gtools.core.growtopia.physics.pathfinding.fastkernel import FastEvaluator
from gtools.core.growtopia.physics.pathfinding.profile import CapabilityProfile
from gtools.core.growtopia.physics.pathfinding.snapshot import WorldSnapshot
from gtools.core.growtopia.player import Clothing, Player
from gtools.core.growtopia.world import Tile, TileFlags, World

FLOOR_Y = 8
STAND_Y = FLOOR_Y * 32 - HITBOX[1]
SPAWN_TX = 4

LAVA = 4
DEATH_SPIKES = 162

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


def make_world(width=40, *, extras=(), clothing=None):
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(width)]
    tiles.append(Tile(fg_id=MAIN_DOOR, pos=ivec2(1, FLOOR_Y - 1)))
    tiles.extend(Tile(fg_id=item_id, pos=ivec2(x, y), flags=flags) for item_id, x, y, flags in extras)
    world = World.from_tiles(tiles)
    world.players[1] = Player(net_id=1, clothing=clothing or Clothing())
    return world


class Rig:
    """One world, two evaluators, two identical motion states."""

    def __init__(self, world, *, tx=SPAWN_TX, y=STAND_Y, flags=None):
        self.controller = PlayerController(world, net_id=1, send=None, auto_respawn=False)
        self.controller.spawn(tx * 32 + 6.0, y)
        if flags is not None:
            self.controller.state.flags = flags

        self.profile = CapabilityProfile.from_controller(self.controller)
        self.snapshot = WorldSnapshot(world)
        self.reference = FastEvaluator(self.snapshot, self.profile, use_numba=False)
        # `default` is whatever the package ships with -- it must be the compiled path here
        self.default = FastEvaluator(self.snapshot, self.profile)
        assert self.default._nb is not None, "the compiled backend was not selected"

        self.a = self.reference.state_from_controller(self.controller)
        self.b = self.default.state_from_controller(self.controller)
        self.ticks = 0

    def tick(self, direction=0, jump=False):
        self.reference.simulate_tick(self.a, direction, jump)
        self.default.simulate_tick(self.b, direction, jump)
        self.ticks += 1
        self.assert_equal()

    def run(self, program):
        for direction, jump, count in program:
            for _ in range(count):
                self.tick(direction, jump)

    def assert_equal(self):
        for name in FIELDS:
            left = getattr(self.a, name)
            right = getattr(self.b, name)
            assert right == left, f"tick {self.ticks}: {name} {right!r} != {left!r} (numba vs python)"
        assert self.b.time_ms == self.a.time_ms, f"tick {self.ticks}: time_ms"
        assert self.b.flag_overrides == self.a.flag_overrides, f"tick {self.ticks}: flag_overrides"
        assert (
            self.b.permissions.tile_cache == self.a.permissions.tile_cache
        ), f"tick {self.ticks}: tile_cache {self.b.permissions.tile_cache} != {self.a.permissions.tile_cache}"


def test_flat_walk_jump_and_cut():
    rig = Rig(make_world())
    rig.run([(1, False, 40), (1, True, 4), (1, False, 40), (0, False, 20), (-1, True, 30), (-1, False, 30)])


def test_walls_and_ceiling():
    world = make_world(width=24, extras=[(DIRT, x, y, TileFlags.NONE) for x in range(6, 12) for y in range(3, FLOOR_Y)])
    rig = Rig(world)
    rig.run([(1, False, 60), (0, True, 40), (1, True, 30), (-1, False, 40)])


def test_water_floatie_and_vehicle():
    pool = [(STEAM_VENT, x, row, TileFlags.IS_WET) for x in range(8, 14) for row in range(1, FLOOR_Y)]
    Rig(make_world(extras=pool)).run([(1, False, 30), (0, True, 30), (-1, True, 20), (1, False, 40)])
    Rig(make_world(extras=pool, clothing=Clothing(neck=SEA_MONSTER_FLOATIE))).run(
        [(1, False, 40), (0, True, 30), (1, False, 30)]
    )


def test_bounce_and_steam():
    for item_id in (PINBALL_BUMPER, MUSHROOM):
        for flags in (TileFlags.NONE, TileFlags.IS_ON):
            rig = Rig(make_world(extras=[(item_id, 4, FLOOR_Y - 1, flags)]), tx=4, y=4 * 32)
            rig.run([(0, False, 30), (1, False, 30), (0, True, 30)])

    rig = Rig(make_world(extras=[(STEAM_LAUNCHER, 4, FLOOR_Y - 1, TileFlags.IS_ON)]), tx=4, y=4 * 32)
    rig.run([(0, False, 40), (1, False, 30), (0, True, 20)])
    idx = rig.snapshot.grid.index(4, FLOOR_Y - 1)
    assert idx in rig.b.flag_overrides and idx in rig.a.flag_overrides


def test_climb_and_wind():
    wall = make_world(
        extras=[(CLIMBING_WALL, 6, y, TileFlags.NONE) for y in range(2, FLOOR_Y)],
        clothing=Clothing(shoes=CLIMBING_BOOTS),
    )
    Rig(wall, tx=6, y=3 * 32).run(
        [(0, False, 40), (0, True, 2), (0, False, 20), (0, True, 30), (1, False, 30)]
    )

    wind = make_world(extras=[(WINTER_WIND, x, FLOOR_Y - 1, TileFlags.NONE) for x in range(6, 14)])
    Rig(wind).run([(0, False, 20), (1, False, 40), (-1, False, 40)])


def test_damaging_and_gravity_well():
    lava = make_world(extras=[(LAVA, 8, FLOOR_Y - 1, TileFlags.NONE)])
    Rig(lava).run([(1, False, 60), (1, True, 20), (-1, False, 40)])

    spikes = make_world(extras=[(DEATH_SPIKES, 8, FLOOR_Y - 1, TileFlags.NONE)])
    Rig(spikes).run([(1, False, 40), (0, False, 20)])

    well = make_world(extras=[(GRAVITY_WELL, 10, FLOOR_Y - 1, TileFlags.IS_ON)])
    Rig(well).run([(1, False, 40), (0, True, 30), (-1, False, 40)])


def test_simulate_outcome_matches():
    """``simulate`` -- not just per-tick replay -- must agree, including the trace."""
    from gtools.core.growtopia.physics.pathfinding.actions import ActionCatalog

    rig = Rig(make_world())
    program = ((1, False, 30), (1, True, 6), (1, False, 25), (0, True, 20), (0, False, 15))

    reference_state = rig.a.clone()
    compiled_state = rig.b.clone()
    expected = rig.reference.simulate(reference_state, program, record_trace=True)
    actual = rig.default.simulate(compiled_state, program, record_trace=True)

    assert actual.ticks == expected.ticks
    assert actual.reason == expected.reason
    assert actual.bbox == expected.bbox
    assert (actual.bounced, actual.launched, actual.climbed) == (expected.bounced, expected.launched, expected.climbed)
    assert (actual.entered_water, actual.used_wind, actual.used_well) == (
        expected.entered_water,
        expected.used_wind,
        expected.used_well,
    )
    assert actual.damage_hits == expected.damage_hits
    assert actual.tick_trace == expected.tick_trace
    for name in FIELDS:
        assert getattr(compiled_state, name) == getattr(reference_state, name), name

    fresh = Rig(make_world())
    # spawn() leaves the avatar airborne; a few ticks settle it so ``walk:*`` exists
    for _ in range(4):
        fresh.tick(0, False)
    catalog = ActionCatalog(fresh.default)
    actions = {action.name: action for action in catalog.actions(fresh.b)}
    walk = actions.get("walk:1") or actions["air:1"]
    expected = fresh.reference.simulate(fresh.a.clone(), walk.frames, stop_when=walk.stop)
    actual = fresh.default.simulate(fresh.b.clone(), walk.frames, stop_when=walk.stop)
    assert (actual.ticks, actual.reason) == (expected.ticks, expected.reason)


def test_matrix_cache_is_reused_per_snapshot():
    """Re-planning must not rebuild the compiled matrices every call."""
    rig = Rig(make_world())
    matrix = rig.default._nb.G
    second = FastEvaluator(rig.snapshot, rig.profile)
    assert second._nb.G is matrix
