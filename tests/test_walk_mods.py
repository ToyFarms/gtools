"""Walk-over item mods: Tree Harvesting shoes (tractor) and the Chicken Plow.

Client evidence -- ``NetAvatar::tryPlaceSeedOrFertilizer`` (0x140506910), the per-tick
``tickAux`` callee (``docs/02_packet``, tile harvest / plant):

* Tree Harvesting shoes ``{898, 1830, 1966, 9650, 10504}``: a planted seed tile with
  its extra at the player position makes the client send the **FIST**
  ``TILE_CHANGE_REQUEST`` (value ``0x12``) -- the same request as a manual punch
  (0x140506F89); the server answers with the harvest broadcast.
* Chicken Plow / Doom Plow ``{5022, 5212}``, grounded and moving, with a seed selected
  (``isItemSeed``): an empty tile whose tile below has collision on
  (``IsTileBelowPlantable``) and that is not a door gets the **selected seed** placement
  request (0x140506B16); a tile that already holds a seed (extra present, no
  ``WAS_SPLICED``) gets the same request again -- the splice.
* The tap path (``HandleTouch``) validates seeds the same way: a seed on an empty tile
  without a plantable tile below aborts locally ("Can't plant a tree in the air!"), and
  a seed on an existing seed tile / ``BUNNY_EGG`` is the splice case.
"""

from pyglm.glm import ivec2

from gtools.baked.items import (
    BUNNY_EGG,
    CHICKEN_PLOW,
    DEAR_JOHN_TRACTOR,
    DIRT,
    DIRT_SEED,
    SIGN,
    SLIPPERY_FLAG_POLE,
)
from gtools.core.growtopia.packet import TankPacket, TankType
from gtools.core.growtopia.physics.controller import FIST_ID, HITBOX, PLOW_ITEMS, TREE_HARVESTING_ITEMS, PlayerController
from gtools.core.growtopia.player import Clothing, Player
from gtools.core.growtopia.world import SeedTile, SignTile, Tile, TileFlags, World

FLOOR_Y = 8
TREE_ROW = FLOOR_Y - 1
STAND_Y = FLOOR_Y * 32 - HITBOX[1]
SPAWN_TX = 10
TREE_TX = 14


def make_world(*, floor: bool = True, extra_tiles: tuple[Tile, ...] = ()) -> World:
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(24) if floor or x != TREE_TX]
    tiles.extend(extra_tiles)
    return World.from_tiles(tiles)


def planted(x: int, *, time_passed: int = 1, flags: TileFlags = TileFlags.NONE) -> Tile:
    """A planted seed: the seed foreground id plus its ``SeedTile`` extra.

    ``time_passed`` is the elapsed growth seconds; the Tree Harvesting gate needs more
    than the seed's ``unk5`` (0), so the default is one second of growth.
    """
    tile = Tile(fg_id=DIRT_SEED, pos=ivec2(x, TREE_ROW), flags=flags | TileFlags.HAS_EXTRA_DATA)
    tile.extra = SeedTile(time_passed=time_passed)
    return tile


def make_controller(world: World, *, shoes: int = 0, hand: int = DIRT_SEED, tx: int = SPAWN_TX, optimistic: bool = False) -> PlayerController:
    world.players[1] = Player(net_id=1, clothing=Clothing(shoes=shoes))
    world.set_local_player(1)
    return PlayerController(world, net_id=1, x=tx * 32 + 6.0, y=STAND_Y, hand_item=hand, optimistic=optimistic)


def record_requests(controller: PlayerController) -> list[TankPacket]:
    """Capture every packet the controller sends and return the tile-change requests."""
    packets: list[TankPacket] = []
    controller.send = packets.append
    controller.requests_log = packets  # type: ignore[attr-defined]

    return packets


def requests_of(controller: PlayerController) -> list[TankPacket]:
    return [p for p in getattr(controller, "requests_log", []) if p.type == TankType.TILE_CHANGE_REQUEST]


def spy_requests(controller: PlayerController) -> list[tuple[int, int, int, bool]]:
    """Capture ``(id, tx, ty, splice)`` for every request the controller emits."""
    calls: list[tuple[int, int, int, bool]] = []
    original = controller.request_change

    def spy(id: int, tx: int, ty: int, *, splice: bool = False, item_on_tree: int = 0) -> None:
        calls.append((id, tx, ty, splice))
        original(id, tx, ty, splice=splice, item_on_tree=item_on_tree)

    controller.request_change = spy  # type: ignore[method-assign]

    return calls


# -- Tree Harvesting (tractor) ----------------------------------------------------------


def test_tractor_harvests_the_seed_tile_under_the_avatar() -> None:
    world = make_world(extra_tiles=(planted(TREE_TX),))
    controller = make_controller(world, shoes=DEAR_JOHN_TRACTOR, tx=TREE_TX)
    record_requests(controller)

    controller.step()

    assert [(p.value, p.int_x, p.int_y) for p in requests_of(controller)] == [(FIST_ID, TREE_TX, TREE_ROW)]


def test_every_harvesting_shoe_harvests() -> None:
    for shoes in sorted(TREE_HARVESTING_ITEMS):
        world = make_world(extra_tiles=(planted(TREE_TX),))
        controller = make_controller(world, shoes=shoes, tx=TREE_TX)
        record_requests(controller)

        controller.step()

        assert [(p.value, p.int_x, p.int_y) for p in requests_of(controller)] == [(FIST_ID, TREE_TX, TREE_ROW)], shoes


def test_tractor_without_the_shoes_does_nothing() -> None:
    world = make_world(extra_tiles=(planted(TREE_TX),))
    controller = make_controller(world, tx=TREE_TX)
    record_requests(controller)

    controller.step()

    assert requests_of(controller) == []


def test_tractor_waits_for_the_seed_growth_clock() -> None:
    world = make_world(extra_tiles=(planted(TREE_TX, time_passed=0),))
    controller = make_controller(world, shoes=DEAR_JOHN_TRACTOR, tx=TREE_TX)
    record_requests(controller)

    controller.step()  # freshly planted: elapsed 0 is not above the seed's threshold

    assert requests_of(controller) == []

    for _ in range(61):  # the world clock crosses the first whole second
        controller.step()

    assert [(p.value, p.int_x, p.int_y) for p in requests_of(controller)][0] == (FIST_ID, TREE_TX, TREE_ROW)


def test_tractor_needs_a_seed_tile() -> None:
    sign = Tile(fg_id=SIGN, pos=ivec2(TREE_TX, TREE_ROW), flags=TileFlags.HAS_EXTRA_DATA)
    sign.extra = SignTile()
    world = make_world(extra_tiles=(sign,))
    controller = make_controller(world, shoes=DEAR_JOHN_TRACTOR, tx=TREE_TX)
    record_requests(controller)

    controller.step()

    assert requests_of(controller) == []


# -- Chicken Plow / Doom Plow -----------------------------------------------------------


def test_plow_plants_the_selected_seed() -> None:
    world = make_world()
    controller = make_controller(world, shoes=CHICKEN_PLOW, hand=DIRT_SEED)
    record_requests(controller)

    controller.set_input(right=True)
    controller.step()

    assert [(p.value, p.int_x, p.int_y) for p in requests_of(controller)] == [(DIRT_SEED, SPAWN_TX, TREE_ROW)]


def test_every_plow_plants() -> None:
    for shoes in sorted(PLOW_ITEMS):
        world = make_world()
        controller = make_controller(world, shoes=shoes, hand=DIRT_SEED)
        record_requests(controller)

        controller.set_input(right=True)
        controller.step()

        assert [(p.value, p.int_x, p.int_y) for p in requests_of(controller)] == [(DIRT_SEED, SPAWN_TX, TREE_ROW)], shoes


def test_plow_needs_a_seed_in_hand() -> None:
    world = make_world()
    controller = make_controller(world, shoes=CHICKEN_PLOW, hand=DIRT)
    record_requests(controller)

    controller.set_input(right=True)
    controller.step()

    assert requests_of(controller) == []


def test_plow_needs_movement() -> None:
    world = make_world()
    controller = make_controller(world, shoes=CHICKEN_PLOW, hand=DIRT_SEED)
    record_requests(controller)

    controller.step()  # settles, but vx stays 0 without input

    assert requests_of(controller) == []


def test_plow_splices_an_existing_seed() -> None:
    world = make_world(extra_tiles=(planted(TREE_TX),))
    controller = make_controller(world, shoes=CHICKEN_PLOW, hand=DIRT_SEED, tx=TREE_TX)
    calls = spy_requests(controller)

    controller.set_input(right=True)
    controller.step()

    assert calls == [(DIRT_SEED, TREE_TX, TREE_ROW, True)]


def test_plow_does_not_resplice_a_spliced_tree() -> None:
    world = make_world(extra_tiles=(planted(TREE_TX, flags=TileFlags.WAS_SPLICED),))
    controller = make_controller(world, shoes=CHICKEN_PLOW, hand=DIRT_SEED, tx=TREE_TX)
    calls = spy_requests(controller)

    controller.set_input(right=True)
    controller.step()

    assert calls == []


# -- the tap path's seed validation -----------------------------------------------------


def test_seed_tap_needs_a_plantable_tile_below() -> None:
    world = make_world(floor=False)  # the column under the target tile is a hole
    controller = make_controller(world, hand=DIRT_SEED)
    record_requests(controller)

    controller.touch_press(TREE_TX, TREE_ROW)

    assert requests_of(controller) == []


def test_seed_tap_plants_on_a_plantable_tile() -> None:
    world = make_world()
    controller = make_controller(world, hand=DIRT_SEED)
    record_requests(controller)

    controller.touch_press(TREE_TX, TREE_ROW)

    assert [(p.value, p.int_x, p.int_y) for p in requests_of(controller)] == [(DIRT_SEED, TREE_TX, TREE_ROW)]


def test_seed_tap_on_a_seed_tile_splices() -> None:
    world = make_world(extra_tiles=(planted(TREE_TX),))
    controller = make_controller(world, hand=DIRT_SEED)
    calls = spy_requests(controller)

    controller.touch_press(TREE_TX, TREE_ROW)

    assert calls == [(DIRT_SEED, TREE_TX, TREE_ROW, True)]


def test_seed_tap_on_a_bunny_egg_splices() -> None:
    egg = Tile(fg_id=BUNNY_EGG, pos=ivec2(TREE_TX, TREE_ROW))
    world = make_world(extra_tiles=(egg,))
    controller = make_controller(world, hand=DIRT_SEED)
    calls = spy_requests(controller)

    controller.touch_press(TREE_TX, TREE_ROW)

    assert calls == [(DIRT_SEED, TREE_TX, TREE_ROW, True)]


def test_collision_on_matches_the_plantable_rule() -> None:
    pole = Tile(fg_id=SLIPPERY_FLAG_POLE, pos=ivec2(4, TREE_ROW))
    world = make_world(extra_tiles=(pole,))
    controller = make_controller(world)

    assert controller._collision_on(4, FLOOR_Y) is True  # dirt under the target
    assert controller._collision_on(4, TREE_ROW) is False  # a non-collidable tile
    assert controller._collision_on(4, 0) is False  # empty air
