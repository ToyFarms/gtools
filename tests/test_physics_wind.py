"""WIND tiles (Conveyor Block / Summer Breeze / Winter Wind / ...) physics.

Client evidence: ``NetAvatar::validatePhysics`` (0x1405051E0) reads the tile at the
collision-rect centre (``getTileAtPlayerPosition``), checks ``item_type == 60``
(WIND) and rebuilds the horizontal axis (0x14050587E) using ``kBounceClamp_100p0``
(100) and ``kBounceCrossZero_1000p0`` (1000) plus the speed cap; the push direction
is tile flag ``0x20`` (``TileFlags.FLIPPED_X``).

Item list (all ``ItemInfoType.WIND``): Summer Breeze 2864, Clover Fan 10704,
Conveyor Block 11192, Megawatt Bass Speaker 5518, Space Conveyor Block 11424,
Starship Turbo Fan 7018, Winter Wind 3232.
"""

from pyglm.glm import ivec2

from gtools.baked.items import CONVEYOR_BLOCK, DIRT, SUMMER_BREEZE, WINTER_WIND
from gtools.core.growtopia.physics.controller import HITBOX, WIND_OPPOSE_SPEED, PlayerController
from gtools.core.growtopia.world import Tile, TileFlags, World

FLOOR_Y = 8
STAND_Y = FLOOR_Y * 32 - HITBOX[1]
WIND_ROW = FLOOR_Y - 1


def make_world(item_id: int, flags: TileFlags = TileFlags.NONE) -> World:
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(24)]
    tiles += [Tile(fg_id=item_id, pos=ivec2(x, WIND_ROW), flags=flags) for x in range(4, 17)]
    return World.from_tiles(tiles)


def spawn(controller: PlayerController, world: World, tx: int = 10) -> PlayerController:
    world.set_local_player(1)

    return controller.spawn(tx * 32 + 6.0, STAND_Y)


def test_wind_pushes_right_to_the_speed_cap() -> None:
    world = make_world(SUMMER_BREEZE)
    controller = PlayerController(world)
    spawn(controller, world)
    controller.step()

    assert controller.vx == controller.state.max_velocity
    first_x = controller.x
    controller.step()
    assert controller.x > first_x


def test_winter_wind_is_the_same_item_type() -> None:
    world = make_world(WINTER_WIND)
    controller = PlayerController(world)
    spawn(controller, world)
    controller.step()

    assert controller.vx == controller.state.max_velocity


def test_flipped_wind_pushes_left() -> None:
    world = make_world(CONVEYOR_BLOCK, TileFlags.FLIPPED_X)
    controller = PlayerController(world)
    spawn(controller, world)
    controller.step()

    assert controller.vx == -controller.state.max_velocity
    first_x = controller.x
    controller.step()
    assert controller.x < first_x


def test_walking_against_the_wind_is_clamped_to_100() -> None:
    world = make_world(SUMMER_BREEZE)  # pushes right
    controller = PlayerController(world)
    spawn(controller, world)

    for _ in range(20):
        controller.set_input(left=True)
        controller.step()

    assert controller.vx == -WIND_OPPOSE_SPEED, "leftward motion caps at -100 on a rightward wind"


def test_flipped_wind_clamps_rightward_motion_to_100() -> None:
    world = make_world(SUMMER_BREEZE, TileFlags.FLIPPED_X)  # pushes left
    controller = PlayerController(world)
    spawn(controller, world)

    for _ in range(20):
        controller.set_input(right=True)
        controller.step()

    assert controller.vx == WIND_OPPOSE_SPEED, "rightward motion caps at +100 on a leftward wind"


def test_walking_with_the_wind_keeps_the_cap() -> None:
    world = make_world(SUMMER_BREEZE)
    controller = PlayerController(world)
    spawn(controller, world)

    for _ in range(10):
        controller.set_input(right=True)
        controller.step()

    assert controller.vx == controller.state.max_velocity


def test_plain_tiles_do_not_push() -> None:
    world = World.from_tiles([Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(24)])
    controller = PlayerController(world)
    spawn(controller, world)

    for _ in range(10):
        controller.step()

    assert controller.vx == 0.0
