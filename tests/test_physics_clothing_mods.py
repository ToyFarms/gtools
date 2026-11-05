"""Special clothing interactions: Slippery, Skating and Wall Climbing.

Client evidence:
* Slippery / Skating live in the tile-below query ``sub_140505CB0``: slide is set
  when the tile below is slippery **or** the avatar wears the slide clothing
  (hat 7410 + shirt 7408, neck 8374, shirt 9078, shoes 10404), except with
  ``ICE_SKATES_OF_WINTER`` (5418, shoes) which forces the flag off;
* Wall Climbing lives in the wall-response branch of
  ``NetAvatar::handleTileInteraction`` (0x140501DF0): with ``vy >= 0`` and not
  grounded, a ``CLIMBING_WALL`` (3586) at the collision-rect centre grabs while
  the gear is worn (hand 3588/8042, shoes 3590/8018/9034/5440/7094, hair 5712),
  or an ``ADVENTURE_ROPE_PITON`` (4700) grabs when the Adventure Rope (1694) is
  in the avatar's five-slot touch cache.
"""

from pyglm.glm import ivec2

from gtools.baked.items import (
    ADVENTURE_ITEM_ROPE,
    ADVENTURE_ROPE_PITON,
    CLIMBING_PICKS,
    CLIMBING_WALL,
    DIRT,
    ICE_CRUST_BLOCK,
    ICE_SKATES_OF_WINTER,
    SLEDDING_PENGUIN,
    SLIPPERY_CHEMICAL_COAT,
)
from gtools.core.growtopia.physics.controller import HITBOX, PlayerController
from gtools.core.growtopia.player import Clothing, Player
from gtools.core.growtopia.world import Tile, TileFlags, World

FLOOR_Y = 8
STAND_Y = FLOOR_Y * 32 - HITBOX[1]
CENTRE_ROW = FLOOR_Y - 1


def set_clothing(world: World, **slots) -> None:
    world.players[1] = Player(net_id=1, clothing=Clothing(**slots))


def spawn(controller: PlayerController, world: World, tx: int = 10, y: float = STAND_Y) -> PlayerController:
    world.set_local_player(1)

    return controller.spawn(tx * 32 + 6.0, y)


def test_slippery_clothing_slides_on_plain_ground() -> None:
    world = World.from_tiles([Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(24)])
    set_clothing(world, shirt=SLIPPERY_CHEMICAL_COAT)
    controller = PlayerController(world)
    spawn(controller, world)
    controller.step()

    assert controller.sliding is True


def test_other_slippery_items() -> None:
    for slots in (
        {"hat": 7410, "shirt": 7408},  # Abominable Snowman Mask + Suit
        {"neck": 8374},  # Bob The Gross Blob
        {"shoes": SLEDDING_PENGUIN},
    ):
        world = World.from_tiles([Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(24)])
        set_clothing(world, **slots)
        controller = PlayerController(world)
        spawn(controller, world)
        controller.step()

        assert controller.sliding is True, f"{slots} must grant the Slippery mod"


def test_ice_skates_cancel_the_slide() -> None:
    # an ice floor slides normally...
    world = World.from_tiles([Tile(fg_id=ICE_CRUST_BLOCK, pos=ivec2(x, FLOOR_Y)) for x in range(24)])
    controller = PlayerController(world)
    spawn(controller, world)
    controller.step()
    assert controller.sliding is True

    # ...unless the Skating mod (ICE_SKATES_OF_WINTER) is worn
    world = World.from_tiles([Tile(fg_id=ICE_CRUST_BLOCK, pos=ivec2(x, FLOOR_Y)) for x in range(24)])
    set_clothing(world, shoes=ICE_SKATES_OF_WINTER)
    controller = PlayerController(world)
    spawn(controller, world)
    controller.step()
    assert controller.sliding is False


def make_climb_world(centre_item: int) -> World:
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(24)]
    tiles += [Tile(fg_id=DIRT, pos=ivec2(12, row)) for row in range(1, FLOOR_Y)]  # solid wall
    tiles += [Tile(fg_id=centre_item, pos=ivec2(11, row)) for row in range(1, FLOOR_Y)]  # climb column

    return World.from_tiles(tiles)


def test_climbing_wall_grabs_with_gear() -> None:
    world = make_climb_world(CLIMBING_WALL)
    set_clothing(world, hand=CLIMBING_PICKS)
    controller = PlayerController(world)
    spawn(controller, world, tx=11, y=4 * 32)

    for _ in range(40):
        controller.set_input(right=True)
        controller.step()
        if controller.grounded:
            break

    assert controller.grounded is True
    assert controller.vy == 0.0
    assert controller.y < STAND_Y - 16, "the grab freezes the avatar on the wall"


def test_climbing_wall_without_gear_does_not_grab() -> None:
    world = make_climb_world(CLIMBING_WALL)
    controller = PlayerController(world)
    spawn(controller, world, tx=11, y=4 * 32)

    for _ in range(120):
        controller.set_input(right=True)
        controller.step()

    assert controller.y == STAND_Y, "no gear -> falls to the floor"


def test_rope_piton_grabs_with_rope_in_cache() -> None:
    world = make_climb_world(ADVENTURE_ROPE_PITON)
    controller = PlayerController(world)
    spawn(controller, world, tx=11, y=4 * 32)
    controller.permissions.tile_cache = [ADVENTURE_ITEM_ROPE]

    for _ in range(40):
        controller.set_input(right=True)
        controller.step()
        if controller.grounded:
            break

    assert controller.grounded is True
    assert controller.y < STAND_Y - 16


def test_rope_piton_without_rope_does_not_grab() -> None:
    world = make_climb_world(ADVENTURE_ROPE_PITON)
    controller = PlayerController(world)
    spawn(controller, world, tx=11, y=4 * 32)
    controller.permissions.tile_cache = []

    for _ in range(120):
        controller.set_input(right=True)
        controller.step()

    assert controller.y == STAND_Y


def test_jumping_releases_the_climb_grip() -> None:
    world = make_climb_world(CLIMBING_WALL)
    set_clothing(world, hand=CLIMBING_PICKS)
    controller = PlayerController(world)
    spawn(controller, world, tx=11, y=4 * 32)

    for _ in range(40):
        controller.set_input(right=True)
        controller.step()
        if controller.grounded:
            break

    controller.set_input(jump=True)
    assert controller.vy == -450.0
