"""The ``World`` seed growth clock -- ``getSeedTimePassed`` / ``tree_ready``.

Client evidence:
* ``TileExtra+0x74`` (the wire ``time_passed`` of a seed tile) is the seed's **elapsed**
  growth seconds: world dumps show a mature Dirt Seed carrying
  ``time_passed == grow_time == 31`` (0x140557870 returns the slot unchanged --
  ``setSeedTimeCountdown`` 0x140557570 only ages extra types 27/38/46).
* The Tree Harvesting gate (``tryPlaceSeedOrFertilizer`` 0x140506F68) is
  ``item->unk5 < elapsed``, and ``SEND_TILE_TREE_STATE`` re-anchors the value with the
  packet's ``target_net_id`` (``setSeedPlacedTime`` 0x14055B310).
"""

from pyglm.glm import ivec2

from gtools.baked.items import DIRT, DIRT_SEED, SIGN
from gtools.core.growtopia.world import SeedTile, SignTile, Tile, TileFlags, World

DIRT_SEED_GROW_TIME = 31


def make_seed_world(*, time_passed: int = 0) -> tuple[World, Tile]:
    seed = Tile(fg_id=DIRT_SEED, pos=ivec2(2, 2), flags=TileFlags.HAS_EXTRA_DATA)
    seed.extra = SeedTile(time_passed=time_passed)
    world = World.from_tiles([Tile(fg_id=DIRT, pos=ivec2(x, 3)) for x in range(4)] + [seed])

    return world, seed


def test_seed_growth_time_reads_the_wire_value() -> None:
    world, seed = make_seed_world(time_passed=7)

    assert world.seed_growth_time(seed) == 7


def test_seed_growth_time_advances_with_the_world_clock() -> None:
    world, seed = make_seed_world(time_passed=7)

    world.advance_time(2500.0)  # 2 whole seconds; the ms remainder carries over
    assert world.seed_growth_time(seed) == 9
    assert seed.extra.time_passed == 9

    world.advance_time(600.0)  # 3.1 s of world time -> +3
    assert world.seed_growth_time(seed) == 10

    world.advance_time(500.0)  # 3.6 s -> still +3
    assert world.seed_growth_time(seed) == 10

    world.advance_time(500.0)  # 4.1 s -> +4
    assert world.seed_growth_time(seed) == 11


def test_seed_growth_time_caps_at_the_seed_grow_time() -> None:
    world, seed = make_seed_world(time_passed=DIRT_SEED_GROW_TIME - 1)

    world.advance_time(5000.0)
    assert world.seed_growth_time(seed) == DIRT_SEED_GROW_TIME

    world.advance_time(10_000.0)
    assert world.seed_growth_time(seed) == DIRT_SEED_GROW_TIME


def test_tree_ready_needs_elapsed_growth() -> None:
    world, seed = make_seed_world(time_passed=0)

    assert world.tree_ready(seed) is False

    world.advance_time(1000.0)

    assert world.tree_ready(seed) is True


def test_tree_ready_ignores_tiles_that_are_not_planted_seeds() -> None:
    sign = Tile(fg_id=SIGN, pos=ivec2(2, 2), flags=TileFlags.HAS_EXTRA_DATA)
    sign.extra = SignTile()
    plain = Tile(fg_id=DIRT, pos=ivec2(3, 2))
    world = World.from_tiles([sign, plain])

    assert world.tree_ready(sign) is False
    assert world.tree_ready(plain) is False
    assert world.seed_growth_time(plain) == 0


def test_update_tree_stores_the_packet_growth_time() -> None:
    world, seed = make_seed_world(time_passed=5)

    world.update_tree(seed, item_id=0, harvest=False, spawn_seed_flag=False, seedling_flag=True, time_passed=20)

    assert seed.extra.time_passed == 20
    assert seed.flags & TileFlags.IS_SEEDLING

    world.advance_time(1000.0)

    assert world.seed_growth_time(seed) == 21
