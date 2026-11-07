"""The ``World`` seed growth anchor -- ``seed_planted_at_ms`` / ``tree_ready``.

Client evidence:
* ``TileExtra+0x74`` (the wire ``time_passed`` of a seed tile) is the seed's **elapsed**
  growth seconds: world dumps show a mature Dirt Seed carrying
  ``time_passed == grow_time == 31``. ``getSeedTimePassed`` (0x140557870) returns that
  slot unchanged -- ``setSeedTimeCountdown`` (0x140557570) ages extra types 27/38/46
  only, never ``SEED_TILE`` (4).
* The Tree Harvesting gate (``tryPlaceSeedOrFertilizer`` 0x140506F68) is
  ``item->unk5 < elapsed``, and ``SEND_TILE_TREE_STATE`` re-anchors the value
  (``setSeedTimePassed`` 0x14055B310).

The engine turns the value into a planting timestamp once (``observed_ms``) and every
consumer derives from that -- no update loop, and the wire field is never mutated.
"""

from pyglm.glm import ivec2

from gtools.baked.items import DIRT, DIRT_SEED, SIGN
from gtools.core.growtopia.world import SeedTile, SignTile, Tile, TileFlags, World

DIRT_SEED_GROW_TIME = 31


class Clock:
    """Deterministic stand-in for ``World.clock`` (ms); assign it to the world."""

    def __init__(self, start_ms: float = 0.0) -> None:
        self.ms = start_ms

    def __call__(self) -> float:
        return self.ms


def make_seed_world(*, time_passed: int = 0, clock_ms: float = 0.0) -> tuple[World, Tile, Clock]:
    clock = Clock(clock_ms)
    seed = Tile(fg_id=DIRT_SEED, pos=ivec2(2, 2), flags=TileFlags.HAS_EXTRA_DATA)
    seed.extra = SeedTile(time_passed=time_passed)
    world = World.from_tiles([Tile(fg_id=DIRT, pos=ivec2(x, 3)) for x in range(4)] + [seed])
    world.clock = clock

    return world, seed, clock


def test_the_anchor_derives_the_planting_time_from_the_growth_value() -> None:
    world, seed, clock = make_seed_world(time_passed=7, clock_ms=50_000.0)

    assert world.seed_planted_at_ms(seed) == 43_000.0
    assert world.seed_growth_time(seed) == 7
    assert world.seed_time_left_ms(seed) == (DIRT_SEED_GROW_TIME - 7) * 1000.0


def test_growth_is_derived_without_touching_the_wire_field() -> None:
    world, seed, clock = make_seed_world(time_passed=7)

    assert world.seed_growth_time(seed) == 7

    # the elapsed time is derived from the planting anchor, so it keeps counting from the
    # moment the seed was planted -- not from the first time the value was queried
    clock.ms += 2500.0  # 9.5 s since planting
    assert world.seed_growth_time(seed) == 9

    clock.ms += 600.0  # 10.1 s
    assert world.seed_growth_time(seed) == 10

    clock.ms += 500.0  # 10.6 s
    assert world.seed_growth_time(seed) == 10

    assert seed.extra.time_passed == 7, "the wire value is never rewritten"


def test_seed_time_left_counts_down_and_reaches_zero() -> None:
    world, seed, clock = make_seed_world(time_passed=29)

    assert world.seed_time_left_ms(seed) == 2000.0

    clock.ms += 2000.0
    assert world.seed_time_left_ms(seed) == 0.0

    clock.ms += 60_000.0
    assert world.seed_time_left_ms(seed) < 0.0


def test_a_loaded_tile_is_anchored_at_first_sight() -> None:
    # a monotonic clock far from zero must not age a value the world just loaded
    world, seed, clock = make_seed_world(time_passed=7, clock_ms=1_234_567.0)

    assert world.seed_growth_time(seed) == 7
    assert seed.extra.observed_ms == 1_234_567.0

    clock.ms += 3000.0
    assert world.seed_growth_time(seed) == 10


def test_tree_ready_needs_elapsed_growth() -> None:
    world, seed, clock = make_seed_world(time_passed=0)

    assert world.tree_ready(seed) is False

    clock.ms += 1000.0

    assert world.tree_ready(seed) is True


def test_tree_ready_ignores_tiles_that_are_not_planted_seeds() -> None:
    sign = Tile(fg_id=SIGN, pos=ivec2(2, 2), flags=TileFlags.HAS_EXTRA_DATA)
    sign.extra = SignTile()
    plain = Tile(fg_id=DIRT, pos=ivec2(3, 2))
    world = World.from_tiles([sign, plain])

    assert world.tree_ready(sign) is False
    assert world.tree_ready(plain) is False
    assert world.seed_growth_time(plain) == 0
    assert world.seed_planted_at_ms(plain) is None
    assert world.seed_time_left_ms(plain) is None


def test_plant_starts_the_clock_and_update_tree_re_anchors_it() -> None:
    world, seed, clock = make_seed_world(clock_ms=1000.0)

    world.plant(seed, DIRT_SEED, item_on_tree=0, splice=False)
    assert seed.extra.time_passed == 0
    assert world.seed_time_left_ms(seed) == DIRT_SEED_GROW_TIME * 1000.0

    clock.ms += 5000.0
    world.update_tree(seed, item_id=0, harvest=False, spawn_seed_flag=False, seedling_flag=True, time_passed=20)

    assert seed.extra.time_passed == 20
    assert seed.flags & TileFlags.IS_SEEDLING
    assert world.seed_time_left_ms(seed) == (DIRT_SEED_GROW_TIME - 20) * 1000.0

    clock.ms += 1000.0
    assert world.seed_growth_time(seed) == 21
