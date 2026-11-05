"""Vertical-axis behaviour in ``gtools.core.growtopia.physics.controller``.

Mirrors ``NetAvatar::integrateVerticalAxis`` (0x140510580), ``NetAvatar::onJump``
(0x1404FE4A50) and ``TryPlaceSeedAtTile`` (0x140506430): the slow-fall clothing,
the water gravity/floaties/swim, the water-vehicle float state and the reduced
jump surfaces.  See ``docs/netavatar-physics.md`` §5.2 / §6.
"""

from pyglm.glm import ivec2

from gtools.baked.items import (
    DIRT,
    GOLDEN_JET_SKI,
    HAY,
    HYPERTECH_ANTIGRAVITY_FIELD,
    JET_SKI,
    LEGENDARY_WINGS,
    MAIN_DOOR,
    PARASOL,
    SEA_MONSTER_FLOATIE,
    SLIPPERY_FLAG_POLE,
    SNOWSHOES,
    SNOW_BLOCK,
    STEAM_VENT,
    SURFBOARD,
)
from gtools.core.growtopia.physics.controller import HITBOX, JUMP_SPEED, MAX_FALL, WATER_VERTICAL_SCALE, PlayerController
from gtools.core.growtopia.player import Clothing, Player
from gtools.core.growtopia.world import Tile, TileFlags, World

MUD_PUDDLE = 8300  # ItemInfoType.MUD
FLOOR_Y = 8
STAND_Y = FLOOR_Y * 32 - HITBOX[1]


def make_world(extras=()):
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(24)]
    tiles.append(Tile(fg_id=MAIN_DOOR, pos=ivec2(1, FLOOR_Y - 1)))
    for item_id, x, y, flags in extras:
        tiles.append(Tile(fg_id=item_id, pos=ivec2(x, y), flags=flags))
    return World.from_tiles(tiles)


def make_pool_world():
    # a non-solid IS_WET column to swim in
    return make_world([(STEAM_VENT, 10, row, TileFlags.IS_WET) for row in range(1, FLOOR_Y)])


def set_clothing(world, net_id=1, **slots):
    world.players[net_id] = Player(net_id=net_id, clothing=Clothing(**slots))


def spawn(controller, world, tx, *, y=STAND_Y):
    world.set_local_player(1)
    return controller.spawn(tx * 32 + 6.0, y)


def test_slow_fall_requires_the_item_and_held_jump():
    # control: no item
    world = make_world()
    controller = PlayerController(world)
    c = spawn(controller, world, 4, y=3 * 32)
    for _ in range(20):
        controller.step()
    assert not c.parasol and not c.glide
    fast = c.vy

    for slots, attr in ((({"hand": PARASOL}), "parasol"), (({"back": LEGENDARY_WINGS}), "glide")):
        world = make_world()
        set_clothing(world, **slots)
        controller = PlayerController(world)
        c = spawn(controller, world, 4, y=3 * 32)
        controller.set_input(jump=True)  # held; no launch while airborne without a token
        for _ in range(20):
            controller.step()
        assert getattr(c, attr) is True
        assert c.vy < fast * 0.75  # 0.3x gravity instead of 1x

    # releasing the button (or leaving the air) turns the state off
    controller.set_input(jump=False)
    controller.step()
    assert not c.parasol and not c.glide


def test_water_swim_launch_is_270():
    world = make_pool_world()
    controller = PlayerController(world)
    c = spawn(controller, world, 10, y=4 * 32)
    controller.step()
    assert c.in_water

    controller.set_input(jump=True)
    assert c.vy == -JUMP_SPEED * 0.6  # -270, the reduced water launch


def test_water_vehicle_suppresses_gravity():
    world = make_pool_world()
    set_clothing(world, shoes=JET_SKI)
    controller = PlayerController(world)
    c = spawn(controller, world, 10, y=4 * 32)
    assert c.water_float is True

    for _ in range(30):
        controller.step()
    assert c.water_float is True
    assert c.vy == 0.0  # neither sinking nor floating while the state is active


def test_water_float_expires_after_3s_without_a_permanent_vehicle():
    world = make_pool_world()
    set_clothing(world, shoes=SURFBOARD)  # grants the 3 s window only
    controller = PlayerController(world)
    c = spawn(controller, world, 10, y=4 * 32)
    assert c.water_float is True

    c.water_enter_ms = controller.time_ms - 3001.0
    controller.step()
    assert c.water_float is False

    world = make_pool_world()
    set_clothing(world, shoes=GOLDEN_JET_SKI)  # permanent while in water
    controller = PlayerController(world)
    c = spawn(controller, world, 10, y=4 * 32)
    c.water_enter_ms = controller.time_ms - 30_000.0
    controller.step()
    assert c.water_float is True


def test_floatie_floats_to_the_surface():
    world = make_pool_world()
    set_clothing(world, neck=SEA_MONSTER_FLOATIE)
    controller = PlayerController(world)
    c = spawn(controller, world, 10, y=3 * 32)

    for _ in range(30):
        controller.step()
    assert c.in_water
    assert c.vy < 0.0  # pulled upward instead of sinking
    assert c.vy >= -MAX_FALL * 0.3  # the water upward clamp


def test_reduced_jump_surfaces():
    def first_jump_vy(extras=(), **clothing):
        world = make_world(extras)
        set_clothing(world, **clothing)
        controller = PlayerController(world)
        c = spawn(controller, world, 10)
        controller.step()  # settle on the surface
        controller.set_input(jump=True)

        return c.vy

    assert first_jump_vy() == -JUMP_SPEED
    assert first_jump_vy([(HAY, 10, FLOOR_Y, TileFlags.NONE)]) == -JUMP_SPEED * 0.6
    assert first_jump_vy([(SNOW_BLOCK, 10, FLOOR_Y, TileFlags.NONE)]) == -JUMP_SPEED * 0.6
    assert first_jump_vy([(SNOW_BLOCK, 10, FLOOR_Y, TileFlags.NONE)], shoes=SNOWSHOES) == -JUMP_SPEED
    assert first_jump_vy([(MUD_PUDDLE, 10, FLOOR_Y, TileFlags.NONE)]) == -JUMP_SPEED * 0.6


def test_antigravity_field_scales_gravity():
    world = make_world([(HYPERTECH_ANTIGRAVITY_FIELD, 10, 4, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, 10, y=4 * 32)
    for _ in range(10):
        controller.step()
    slow = c.vy

    world = make_world()
    controller = PlayerController(world)
    c = spawn(controller, world, 10, y=4 * 32)
    for _ in range(10):
        controller.step()
    assert slow < c.vy * 0.6  # 0.375x gravity


def test_water_and_pole_share_the_120_terminal_speed():
    world = make_pool_world()
    controller = PlayerController(world)
    c = spawn(controller, world, 10, y=4 * 32)
    c.vy = 500.0
    controller.step()
    assert c.vy <= MAX_FALL * WATER_VERTICAL_SCALE

    world = make_world([(SLIPPERY_FLAG_POLE, 10, 4, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, 10, y=4 * 32)
    c.vy = 500.0
    controller.step()
    assert c.vy <= MAX_FALL * WATER_VERTICAL_SCALE


def test_mud_scales_the_horizontal_cap():
    world = make_world([(MUD_PUDDLE, x, FLOOR_Y, TileFlags.NONE) for x in range(6, 24)])
    controller = PlayerController(world)
    c = spawn(controller, world, 10)
    controller.step()
    assert c.mud is True

    for _ in range(60):
        controller.set_input(right=True)
        controller.step()
    assert c.vx <= 250.0 * 0.6 + 1e-9
