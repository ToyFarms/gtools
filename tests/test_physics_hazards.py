"""Deadly/damaging tile behaviour in ``gtools.core.growtopia.physics.controller``.

Mirrors the client's tile-interaction dispatchers (``NetAvatar::handleTileInteraction``
at ``0x140501DF0`` and ``vfunc_48`` at ``0x1405021D0``), ``killPlayer``
(``0x1405024E0``) and the two damaging responses (``0x1404FBFF0`` /
``0x1404FC0B0``).  See ``docs/netavatar-physics.md`` §12.
"""

import pytest
from pyglm.glm import ivec2

from gtools.baked.items import DIRT, MAIN_DOOR
from gtools.core.growtopia.packet import TankFlags
from gtools.core.growtopia.physics.controller import HITBOX, PlayerController
from gtools.core.growtopia.player import CharacterFlags
from gtools.core.growtopia.world import Tile, TileFlags, World

LAVA = 4
ACID = 726
CACTUS = 330  # POINTY
DEATH_SPIKES = 162  # DEADLY
MUSHROOM = 194  # TRAMPOLINE
PINBALL_BUMPER = 526  # BOUNCY
GRAVITY_WELL = 6772  # ItemInfoFlag2.TILE_DEADLY_IF_ON
STEAM_VENT = 3284  # STEAM_LAVA_IF_ON
STORM_CLOUD = 7202  # LIGHTNING_CLOUD
CHECKPOINT = 410

FLOOR_Y = 8
STAND_Y = FLOOR_Y * 32 - HITBOX[1]
SPAWN_TX = 8


def make_world(extras=(), *, door=True):
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(24)]
    if door:
        tiles.append(Tile(fg_id=MAIN_DOOR, pos=ivec2(1, FLOOR_Y - 1)))
    tiles.extend(Tile(fg_id=item_id, pos=ivec2(x, y), flags=flags) for item_id, x, y, flags in extras)
    return World.from_tiles(tiles)


def spawn(controller, world, tx, *, flags=None, y=STAND_Y):
    world.set_local_player(1)
    c = controller.spawn(tx * 32 + 6.0, y)
    if flags is not None:
        c.state.flags = flags
    return c


def walk_until(controller, sent, event, ticks=120):
    """Walk right, return the minimum ``vx`` seen, stop once ``event`` is in a frame."""
    min_vx = 0.0
    for _ in range(ticks):
        controller.set_input(right=True)
        controller.step()
        min_vx = min(min_vx, controller.vx)
        if any(int(p.flags) & int(event) for p in sent) or controller.killed:
            break
    return min_vx


@pytest.mark.parametrize(
    ("item_id", "tile_flags", "event"),
    [
        (LAVA, TileFlags.NONE, TankFlags.FIRE_DAMAGE),
        (ACID, TileFlags.NONE, TankFlags.ACID_DAMAGE),
        (CACTUS, TileFlags.NONE, TankFlags.DAMAGE),
        (STEAM_VENT, TileFlags.IS_ON, TankFlags.DAMAGE),
        (STORM_CLOUD, TileFlags.IS_ON, TankFlags.DAMAGE),
    ],
    ids=["lava", "acid", "cactus", "steam-vent", "storm-cloud"],
)
def test_x_probe_damages_and_knocks_back(item_id, tile_flags, event):
    world = make_world([(item_id, 10, FLOOR_Y - 1, tile_flags)])
    sent = []
    controller = PlayerController(world, send=sent.append)
    spawn(controller, world, SPAWN_TX)

    min_vx = walk_until(controller, sent, event)

    assert any(int(p.flags) & int(event) for p in sent)
    assert min_vx == -300.0  # inverted approach speed, clamped away from the tile


def test_x_probe_ignore_lava_falls_through_to_wall():
    world = make_world([(LAVA, 10, FLOOR_Y - 1, TileFlags.NONE)])
    sent = []
    controller = PlayerController(world, send=sent.append)
    c = spawn(controller, world, SPAWN_TX, flags=CharacterFlags.IGNORE_LAVA)

    for _ in range(60):
        controller.set_input(right=True)
        controller.step()

    assert not any(int(p.flags) & int(TankFlags.FIRE_DAMAGE) for p in sent)
    assert not c.on_fire
    assert c.vx == 0.0  # FULL-collision lava still gives the wall response
    assert c.x <= 10 * 32 - HITBOX[0] + 0.001


def test_deadly_kills_once_and_auto_respawns_at_main_door():
    world = make_world([(DEATH_SPIKES, 10, FLOOR_Y - 1, TileFlags.NONE)])
    sent = []
    deaths = []
    controller = PlayerController(world, send=sent.append, on_death=lambda c, tx, ty: deaths.append((tx, ty)))
    c = spawn(controller, world, SPAWN_TX)

    for _ in range(40):
        controller.set_input(right=True)
        controller.step()
        if deaths:
            break

    assert deaths == [(10, 7)]
    assert any(int(p.flags) & int(TankFlags.GOT_KILLED) for p in sent)
    assert (c.x, c.y) == (38.0, STAND_Y)  # MAIN_DOOR respawn position for a 20x30 hitbox
    assert c.killed is False


def test_ignore_spikes_skips_the_kill_but_not_pointy_damage():
    world = make_world([(DEATH_SPIKES, 10, FLOOR_Y - 1, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, SPAWN_TX, flags=CharacterFlags.IGNORE_SPIKES)
    for _ in range(40):
        controller.set_input(right=True)
        controller.step()
    assert c.killed is False
    assert c.x <= 10 * 32 - HITBOX[0] + 0.001  # leans on the spike wall

    world = make_world([(CACTUS, 10, FLOOR_Y - 1, TileFlags.NONE)])
    sent = []
    controller = PlayerController(world, send=sent.append)
    spawn(controller, world, SPAWN_TX, flags=CharacterFlags.IGNORE_SPIKES)
    min_vx = walk_until(controller, sent, TankFlags.DAMAGE)
    assert any(int(p.flags) & int(TankFlags.DAMAGE) for p in sent)
    assert min_vx == -300.0


def test_tile_deadly_if_on_requires_the_is_on_flag():
    world = make_world([(GRAVITY_WELL, 10, FLOOR_Y - 1, TileFlags.IS_ON)])
    deaths = []
    controller = PlayerController(world, on_death=lambda c, tx, ty: deaths.append((tx, ty)))
    spawn(controller, world, SPAWN_TX)
    for _ in range(40):
        controller.set_input(right=True)
        controller.step()
        if deaths:
            break
    assert deaths == [(10, 7)]

    world = make_world([(GRAVITY_WELL, 10, FLOOR_Y - 1, TileFlags.NONE)])
    deaths = []
    controller = PlayerController(world, on_death=lambda c, tx, ty: deaths.append((tx, ty)))
    c = spawn(controller, world, SPAWN_TX)
    for _ in range(60):
        controller.set_input(right=True)
        controller.step()
    assert not deaths
    assert c.x > 11 * 32  # not solid when off, walks straight through


def test_y_probe_falling_launch_and_no_gravity_fallback():
    world = make_world([(LAVA, 10, FLOOR_Y - 1, TileFlags.NONE)])
    sent = []
    controller = PlayerController(world, send=sent.append)
    c = spawn(controller, world, 10, y=STAND_Y - 3 * 32)

    min_vy = 0.0
    for _ in range(60):
        controller.step()
        min_vy = min(min_vy, c.vy)
    assert min_vy == -800.0
    assert any(int(p.flags) & int(TankFlags.FIRE_DAMAGE) for p in sent)

    world = make_world([(LAVA, 10, FLOOR_Y - 1, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, 10)
    c.state.vertical_accel = 0.0
    for _ in range(90):
        controller.step()
        if c.vy == -50.0:
            break
    assert c.vy == -50.0


def test_y_probe_rising_contact_flips_and_sets_damage_slip():
    world = make_world([(ACID, 10, 5, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, 10)
    c.jump_latch = True  # suppress the jump cut so the rise reaches the tile
    c.vy = -400.0

    flip = None
    for _ in range(90):
        controller.step()
        if c.vy > 0.0:
            flip = c.vy
            break
    assert flip is not None and 0.0 < flip <= 400.0
    assert c.damage_slip is True


def test_damage_slip_is_frictionless_and_scales_input_until_landing():
    world = make_world([(LAVA, 10, FLOOR_Y - 1, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, 10, y=STAND_Y - 3 * 32)  # straight above the lava

    # fall onto the lava; inject the rightward incoming velocity just before contact
    # (holding the key for the whole fall would drift the avatar off the tile)
    for _ in range(60):
        if c.y + controller.height >= 210.0:
            c.vx = 250.0
        controller.step()
        if c.damage_slip:
            break
    assert c.damage_slip is True
    assert c.vx == 300.0  # same-direction clamp from the ~250 approach, not reversed

    # frictionless: with no input the above-cap speed is not damped at all
    for _ in range(3):
        controller.step()
        assert c.damage_slip is True
        assert c.vx == 300.0

    # the whole input magnitude is scaled by 0.15: pressing left moves vx by
    # 1200*0.15/60 = 3 px/s per tick instead of 20
    controller.set_input(left=True)
    controller.step()
    assert c.damage_slip is True
    assert abs(c.vx - 297.0) < 1e-9

    # touching the ground clears the state and restores the full acceleration step
    for _ in range(120):
        controller.step()
        if not c.damage_slip:
            break
    assert c.damage_slip is False
    before = c.vx
    controller.step()
    assert abs((before - c.vx) - 20.0) < 1e-9


def test_y_probe_steam_vent_launch():
    world = make_world([(STEAM_VENT, 10, FLOOR_Y - 1, TileFlags.IS_ON)])
    sent = []
    controller = PlayerController(world, send=sent.append)
    c = spawn(controller, world, 10, y=STAND_Y - 2 * 32)

    min_vy = 0.0
    for _ in range(80):
        controller.step()
        min_vy = min(min_vy, c.vy)
    assert min_vy == -800.0
    assert any(int(p.flags) & int(TankFlags.DAMAGE) for p in sent)


def test_trampoline_and_bouncy_still_work():
    world = make_world([(MUSHROOM, 10, FLOOR_Y - 1, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, 10, y=STAND_Y - 3 * 32)
    touched = False
    for _ in range(90):
        controller.step()
        if c.vy == -800.0:
            touched = True
            break
    assert touched

    world = make_world([(PINBALL_BUMPER, 10, FLOOR_Y - 1, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, 10, y=STAND_Y - 3 * 32)
    bounced = False
    for _ in range(90):
        controller.step()
        if c.vy < -100.0:
            bounced = True
            break
    assert bounced


def test_noclip_disables_tile_interaction():
    world = make_world([(DEATH_SPIKES, 10, FLOOR_Y - 1, TileFlags.NONE)])
    controller = PlayerController(world)
    c = spawn(controller, world, SPAWN_TX, flags=CharacterFlags.NOCLIP)
    for _ in range(60):
        controller.set_input(right=True)
        controller.step()
    assert c.killed is False


def test_killed_latch_freezes_the_corpse_without_auto_respawn():
    world = make_world([(DEATH_SPIKES, 10, FLOOR_Y - 1, TileFlags.NONE)])
    deaths = []
    controller = PlayerController(world, auto_respawn=False)
    controller.on_death = lambda c, tx, ty: deaths.append((tx, ty))
    c = spawn(controller, world, SPAWN_TX)

    for _ in range(40):
        controller.set_input(right=True)
        controller.step()
        if deaths:
            break

    frozen = (c.x, c.y, c.vx, c.vy)
    for _ in range(30):
        controller.step()
    assert c.killed is True
    assert (c.x, c.y, c.vx, c.vy) == frozen  # NetControllerLocal::Update skips the step


def test_checkpoint_moves_the_respawn_tile():
    world = make_world([(CHECKPOINT, 6, FLOOR_Y - 1, TileFlags.NONE)])
    controller = PlayerController(world)
    spawn(controller, world, 4)
    for _ in range(60):
        controller.set_input(right=True)
        controller.step()
        if world.respawn_tile is not None and world.respawn_tile.x == 6:
            break
    assert world.respawn_tile is not None and world.respawn_tile.x == 6
    pos = world.get_respawn_position(HITBOX)
    assert pos is not None and abs(pos[0] - 198.0) < 0.001  # tile 6 centred for a 20 px hitbox
