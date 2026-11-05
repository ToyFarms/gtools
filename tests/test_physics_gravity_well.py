"""Gravity Well (6772) pull physics.

Client evidence:
* ``sub_140572FB0`` (0x140572FB0) tracks wells (item id ``0x1A74`` + tile flag
  ``IS_ON``) in a set on the particle manager (``+0x3668``);
* ``NetAvatar::tickAux`` (0x140503DAE) copies that set and calls
  ``findNearestInteractableTileDirection`` (0x140510FE0): the nearest well whose
  centre is inside a ``tile_range * 32`` box (the well's ``tile_range`` is 5) is
  selected and the returned pull is ``normalize(wellCentre - avatarCentre) * 60``
  with the falling (x3) and upward (y0/yx7) modifiers.
"""

from pyglm.glm import ivec2

from gtools.baked.items import DIRT, GRAVITY_WELL
from gtools.core.growtopia.physics.controller import HITBOX, PlayerController
from gtools.core.growtopia.world import Tile, TileFlags, World

FLOOR_Y = 8
STAND_Y = FLOOR_Y * 32 - HITBOX[1]
CENTRE_ROW = FLOOR_Y - 1


def make_world(wells=(), flags: TileFlags = TileFlags.IS_ON) -> World:
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(24)]
    tiles += [Tile(fg_id=GRAVITY_WELL, pos=ivec2(x, y), flags=flags) for x, y in wells]
    return World.from_tiles(tiles)


def spawn(controller: PlayerController, world: World, tx: int = 10) -> PlayerController:
    world.set_local_player(1)

    return controller.spawn(tx * 32 + 6.0, STAND_Y)


def test_active_well_pulls_toward_it() -> None:
    world = make_world([(14, CENTRE_ROW)])  # 4 tiles to the right, in range
    controller = PlayerController(world)
    spawn(controller, world)
    controller.step()  # settle: the first tick is airborne, so the x3 falling pull applies

    x0 = controller.x
    for _ in range(10):
        controller.step()

    # grounded: 60 px/s at dt = 1/60 -> exactly 1 px per tick toward the well
    assert controller.x == x0 + 10


def test_inactive_well_does_not_pull() -> None:
    world = make_world([(14, CENTRE_ROW)], flags=TileFlags.NONE)
    controller = PlayerController(world)
    spawn(controller, world)

    x0 = controller.x
    for _ in range(10):
        controller.step()

    assert controller.x == x0


def test_well_out_of_range_does_not_pull() -> None:
    world = make_world([(18, CENTRE_ROW)])  # 8 tiles away, outside the 5-tile range box
    controller = PlayerController(world)
    spawn(controller, world)

    x0 = controller.x
    for _ in range(10):
        controller.step()

    assert controller.x == x0


def test_nearest_well_wins() -> None:
    world = make_world([(5, CENTRE_ROW), (12, CENTRE_ROW)])  # left-far + right-close
    controller = PlayerController(world)
    spawn(controller, world)
    controller.step()  # settle

    x0 = controller.x
    for _ in range(10):
        controller.step()

    assert controller.x == x0 + 10, "must be pulled toward the closer well on the right"


def test_well_above_lifts_the_player() -> None:
    world = make_world([(10, CENTRE_ROW - 3)])  # straight above, in range
    controller = PlayerController(world)
    spawn(controller, world)

    y0 = controller.y
    for _ in range(10):
        controller.step()

    assert controller.y < y0, "a mostly-vertical upward pull is multiplied by 7"
