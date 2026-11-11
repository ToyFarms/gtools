"""WorldSnapshot / TileGrid classification and invalidation."""

from __future__ import annotations

from pyglm.glm import ivec2

from gtools.baked.items import DIRT, ICE, MAIN_DOOR, MUD_PUDDLE, STEAM_VENT, WINTER_WIND
from gtools.core.growtopia.items_dat import ItemInfoCollisionType
from gtools.core.growtopia.physics.pathfinding.snapshot import (
    BOUNCE_RADIAL,
    BOUNCE_TRAMPOLINE,
    DAMAGE_FIRE,
    DAMAGE_GENERIC,
    DAMAGE_NONE,
    WorldSnapshot,
)
from gtools.core.growtopia.world import Tile, TileFlags, World

PLATFORM = 102  # JUMP_THROUGH
JUMP_DOWN = 4530  # COSMIC_RAIN
ONE_WAY = 3796
COLLIDE_IF_OFF = 596  # TREASURE_CHEST
COLLIDE_IF_ON = 1226  # EVIL_EYE
LAVA = 4
CACTUS = 330
DEATH_SPIKES = 162
PINBALL = 526
MUSHROOM = 194


def build():
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, 6)) for x in range(16)]
    tiles.append(Tile(fg_id=MAIN_DOOR, pos=ivec2(1, 5)))
    tiles += [
        Tile(fg_id=PLATFORM, pos=ivec2(2, 3)),
        Tile(fg_id=JUMP_DOWN, pos=ivec2(3, 3)),
        Tile(fg_id=ONE_WAY, pos=ivec2(4, 3)),
        Tile(fg_id=ONE_WAY, pos=ivec2(5, 3), flags=TileFlags.FLIPPED_X),
        Tile(fg_id=COLLIDE_IF_OFF, pos=ivec2(6, 3)),
        Tile(fg_id=COLLIDE_IF_OFF, pos=ivec2(7, 3), flags=TileFlags.IS_ON),
        Tile(fg_id=COLLIDE_IF_ON, pos=ivec2(8, 3)),
        Tile(fg_id=COLLIDE_IF_ON, pos=ivec2(9, 3), flags=TileFlags.IS_ON),
        Tile(fg_id=LAVA, pos=ivec2(10, 5)),
        Tile(fg_id=CACTUS, pos=ivec2(11, 5)),
        Tile(fg_id=DEATH_SPIKES, pos=ivec2(12, 5)),
        Tile(fg_id=PINBALL, pos=ivec2(13, 5)),
        Tile(fg_id=MUSHROOM, pos=ivec2(14, 5)),
        Tile(fg_id=WINTER_WIND, pos=ivec2(15, 5)),
        Tile(fg_id=WINTER_WIND, pos=ivec2(0, 5), flags=TileFlags.FLIPPED_X),
        Tile(fg_id=ICE, pos=ivec2(2, 5)),
        Tile(fg_id=MUD_PUDDLE, pos=ivec2(3, 5)),
        Tile(fg_id=STEAM_VENT, pos=ivec2(4, 5), flags=TileFlags.IS_WET),
    ]
    return World.from_tiles(tiles)


def test_classification():
    grid = WorldSnapshot(build()).grid

    def at(x, y):
        return grid.index(x, y)

    assert grid.collision[at(6, 3)] == ItemInfoCollisionType.COLLIDE_IF_OFF
    assert grid.collision[at(7, 3)] == ItemInfoCollisionType.NONE
    assert grid.collision[at(8, 3)] == ItemInfoCollisionType.NONE
    assert grid.collision[at(9, 3)] == ItemInfoCollisionType.COLLIDE_IF_ON

    assert grid.platform[at(2, 3)]
    assert grid.jump_down[at(3, 3)]
    assert grid.one_way[at(4, 3)] == 1
    assert grid.one_way[at(5, 3)] == -1
    assert grid.blocks[at(6, 3)] == 1
    assert grid.blocks[at(7, 3)] == 0
    assert grid.blocks[at(8, 3)] == 0
    assert grid.blocks[at(9, 3)] == 1

    assert grid.deadly[at(12, 5)] == 1
    assert grid.damage[at(10, 5)] == DAMAGE_FIRE
    assert grid.damage[at(11, 5)] == DAMAGE_GENERIC
    assert grid.damage[at(12, 5)] == DAMAGE_NONE
    assert grid.bouncy[at(13, 5)] == BOUNCE_RADIAL
    assert grid.bouncy[at(14, 5)] == BOUNCE_TRAMPOLINE
    assert grid.wind[at(15, 5)] == 1
    assert grid.wind[at(0, 5)] == -1
    assert grid.slippery[at(2, 5)] == 1
    assert grid.mud[at(3, 5)] == 1
    assert grid.wet[at(4, 5)] == 1


def test_incremental_sync_and_versions():
    world = build()
    snapshot = WorldSnapshot(world)
    idx = snapshot.grid.index(10, 5)
    before = snapshot.grid.version[idx]

    world.place_fg(world.get_tile(10, 5), DIRT)
    assert snapshot.sync_tile(world, 10, 5)
    assert snapshot.grid.version[idx] > before
    assert snapshot.grid.fg_id[idx] == DIRT
    assert snapshot.grid.damage[idx] == DAMAGE_NONE

    snapshot.invalidate_tile(10, 5)
    assert snapshot.grid.version[idx] > before + 1
    assert snapshot.max_version_in_bbox((9, 4, 11, 6)) >= snapshot.grid.version[idx]


def test_probe_world_isolates_tiles():
    world = build()
    snapshot = WorldSnapshot(world)
    probe = snapshot.probe_world()
    tile = probe.get_tile(2, 3)
    tile.flags |= TileFlags.IS_ON
    assert world.get_tile(2, 3).flags & TileFlags.IS_ON == 0
    assert snapshot.fresh_tile(snapshot.grid.index(2, 3)).flags & TileFlags.IS_ON == 0
