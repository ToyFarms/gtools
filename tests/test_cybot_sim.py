"""CyBot runtime simulation -- ``gtools.core.growtopia.cybot``.

Every rule asserted here is a port of a verified client function (addresses in
``docs/cybot.md``): the command list build incl. mirror commands
(``cybotRebuildCommands`` 0x1403EB8B0), phase scheduling (``cybotScheduleFromClock``
0x1403EB1D0), the window-end tick (``cybotTick`` 0x1403EBF60), one-tile-per-window
movement (``cybotMove`` 0x1403EC090), shots (``cybotExecuteCommand`` 0x1403EA820),
melee + deadly projectiles (``cybotApplyMeleeDamage`` 0x1403EA370 /
``cybotProjectilesCheckKill`` 0x1403E9670). The clock is the client's ms clock
(``GameState+0x328``).
"""

import dataclasses

import pytest
from pyglm.glm import ivec2

from gtools.baked.items import (
    COMMAND_BASIC_SHOT_DOWN,
    COMMAND_BASIC_SHOT_LEFT,
    COMMAND_BASIC_SHOT_RIGHT,
    COMMAND_BASIC_SHOT_UP,
    COMMAND_MOVE_LEFT,
    COMMAND_MOVE_RIGHT,
    FLAMEBOT_LEVEL_1,
    MAIN_DOOR,
    SHOCKBOT_LEVEL_1,
    SHOOTERBOT_LEVEL_1,
    SPIKEBOT_LEVEL_1,
    SEARBOT_LEVEL_1,
)
from gtools.core.growtopia.cybot import (
    TILE,
    CyBotDirection,
    CyBotProjectile,
    CyBotWorld,
    command_direction,
)
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.packet import TankFlags
from gtools.core.growtopia.physics.controller import HITBOX, PlayerController
from gtools.core.growtopia.player import CharacterFlags
from gtools.core.growtopia.world import CyBotCommandData, CybotTile, Tile, World

MOVE_LEFT = COMMAND_MOVE_LEFT  # 5672, 500 ms, dx -1, mirror 5674
MOVE_RIGHT = COMMAND_MOVE_RIGHT
SHOT_LEFT = COMMAND_BASIC_SHOT_LEFT  # 5682, 2400 ms, dir 1, 0.16 px/ms, 800 ms life
SHOT_RIGHT = COMMAND_BASIC_SHOT_RIGHT
SHOT_UP = COMMAND_BASIC_SHOT_UP
SHOT_DOWN = COMMAND_BASIC_SHOT_DOWN

ROBOT_TX, ROBOT_TY = 5, 5
ROBOT_CENTER = (ROBOT_TX * TILE + TILE / 2, ROBOT_TY * TILE + TILE / 2)  # client tileToWorldCenter


class Clock:
    """Deterministic stand-in for the client's ms clock."""

    def __init__(self, ms: int = 0) -> None:
        self.ms = ms

    def __call__(self) -> float:
        return self.ms


def make_world(
    robot: int,
    commands: list[int],
    *,
    activated: int = 1,
    anchor_ms: int = 0,
    pos: tuple[int, int] = (ROBOT_TX, ROBOT_TY),
    extra_tiles: list[Tile] | None = None,
) -> tuple[World, Tile]:
    tile = Tile(fg_id=robot, pos=ivec2(*pos))
    tile.extra = CybotTile(
        commands=[CyBotCommandData(item_id=command, enabled=1) for command in commands],
        anchor_ms=anchor_ms,
        activated=activated,
    )
    world = World.from_tiles([tile, *(extra_tiles or [])])
    return world, tile


def make_sim(world: World, clock: Clock) -> tuple[CyBotWorld, "CyBot"]:
    sim = CyBotWorld(clock)
    sim.load(world)
    assert len(sim.robots) == 1
    return sim, sim.robots[0]


# -- command list build (cybotRebuildCommands) ---------------------------------------


def test_one_way_route_gets_mirror_commands_in_reverse() -> None:
    world, _ = make_world(SPIKEBOT_LEVEL_1, [MOVE_LEFT, MOVE_LEFT, MOVE_LEFT])
    sim, robot = make_sim(world, Clock())

    assert [cmd.duration_ms for cmd in robot.commands] == [500] * 6
    assert robot.cycle_duration_ms == 3000
    # primaries in order, then the mirrors (Move Right) in reverse
    assert [cmd.item_id for cmd in robot.commands] == [MOVE_LEFT] * 3 + [MOVE_RIGHT] * 3
    assert all(cmd.direction == CyBotDirection.NONE for cmd in robot.commands)


def test_balanced_and_shot_only_routes_get_no_mirrors() -> None:
    world, _ = make_world(SHOOTERBOT_LEVEL_1, [SHOT_LEFT, SHOT_RIGHT])
    sim, robot = make_sim(world, Clock())
    assert len(robot.commands) == 2
    assert robot.cycle_duration_ms == 4800

    world, _ = make_world(SPIKEBOT_LEVEL_1, [MOVE_LEFT, MOVE_RIGHT])
    sim, robot = make_sim(world, Clock())
    assert len(robot.commands) == 2  # sum of the offsets is zero -> no mirror pass


def test_command_direction_matches_the_shoot_bits() -> None:
    assert command_direction(int(item_database.get(SHOT_LEFT).flags2)) == CyBotDirection.LEFT
    assert command_direction(int(item_database.get(SHOT_RIGHT).flags2)) == CyBotDirection.RIGHT
    assert command_direction(int(item_database.get(SHOT_UP).flags2)) == CyBotDirection.UP
    assert command_direction(int(item_database.get(SHOT_DOWN).flags2)) == CyBotDirection.DOWN
    assert command_direction(int(item_database.get(MOVE_LEFT).flags2)) == CyBotDirection.NONE


def test_robot_without_commands_is_inert() -> None:
    world, _ = make_world(SHOOTERBOT_LEVEL_1, [])
    sim, robot = make_sim(world, Clock(1000))

    assert robot.cycle_duration_ms == 0
    assert robot.tick(2000) is None
    assert sim.projectiles == []


# -- scheduling (cybotScheduleFromClock) ---------------------------------------------


def test_schedule_picks_the_command_containing_the_phase() -> None:
    world, _ = make_world(SHOOTERBOT_LEVEL_1, [MOVE_LEFT, SHOT_LEFT], anchor_ms=1000)
    clock = Clock(1000 + 700)  # phase 700 -> inside the second command (500..2899)
    sim, robot = make_sim(world, clock)

    assert robot.index == 1
    assert robot.cmd_start_ms == 1500
    assert robot.cmd_end_ms == 1500 + 2400
    # the position is replayed from the tile centre through the earlier offsets
    assert (robot.x, robot.y) == (ROBOT_CENTER[0] - TILE, ROBOT_CENTER[1])
    assert (robot.target_x, robot.target_y) == (robot.x, robot.y)  # the shot command does not move


def test_schedule_wraps_past_whole_cycles() -> None:
    world, _ = make_world(SHOOTERBOT_LEVEL_1, [MOVE_LEFT], anchor_ms=0)
    sim, robot = make_sim(world, Clock(1500))  # cycle = 2 * 500 (mirror added)

    assert robot.cycle_duration_ms == 1000
    assert robot.index == 1
    assert robot.cmd_start_ms == 1500  # anchor + 1 * cycle + acc(0)


def test_schedule_clamps_a_future_anchor_to_now() -> None:
    world, _ = make_world(SHOOTERBOT_LEVEL_1, [MOVE_LEFT], anchor_ms=10_000)
    sim, robot = make_sim(world, Clock(1_000))

    assert robot.index == 0
    assert robot.cmd_start_ms == 1_000
    assert robot.cmd_end_ms == 1_500


# -- tick / movement (cybotTick + cybotMove) -----------------------------------------


def test_command_effect_fires_at_the_end_of_its_window() -> None:
    world, _ = make_world(SHOOTERBOT_LEVEL_1, [SHOT_LEFT])
    sim, robot = make_sim(world, Clock(0))

    assert robot.cmd_end_ms == 2400
    sim.tick(1000)
    assert sim.projectiles == []  # still inside the window

    sim.tick(2401)
    assert len(sim.projectiles) == 1

    shot = sim.projectiles[0]
    assert (shot.x, shot.y) == ROBOT_CENTER
    assert (shot.dir_x, shot.dir_y) == (-1.0, 0.0)
    assert shot.speed == pytest.approx(0.16)
    assert shot.life_ms == 800
    assert shot.flip is True and shot.angle == 0.0
    assert shot.deadly is True  # ShooterBot carries ROBOT_SHOOT_DEADLY

    # wraps to the same (only) command
    assert robot.index == 0
    assert (robot.cmd_start_ms, robot.cmd_end_ms) == (2400, 4800)


def test_projectile_flies_at_016_px_per_ms_and_retires_after_its_lifetime() -> None:
    world, _ = make_world(SHOOTERBOT_LEVEL_1, [SHOT_LEFT])
    sim, _ = make_sim(world, Clock(0))
    sim.tick(2401)
    shot = sim.projectiles[0]

    sim.tick(2401 + 400)
    assert shot.x == pytest.approx(ROBOT_CENTER[0] - 64.0)  # 0.16 * 400
    assert shot.accrued_ms == 400

    # the retirement test runs on the *next* update after ``accrued >= life``
    # (client: `if (accrued < life) move` else retire)
    sim.tick(2401 + 800)
    assert shot.accrued_ms == 800 and len(sim.projectiles) == 1
    sim.tick(2401 + 801)
    assert sim.projectiles == []


def test_movement_lerps_one_tile_per_window() -> None:
    world, _ = make_world(SPIKEBOT_LEVEL_1, [MOVE_LEFT, MOVE_LEFT])
    sim, robot = make_sim(world, Clock(0))

    assert (robot.x, robot.y) == ROBOT_CENTER
    sim.tick(250)
    assert robot.x == pytest.approx(ROBOT_CENTER[0] - TILE / 2)
    assert robot.facing_left is True

    # `cybotMove` skips the frame where now == cmdEnd; the last frame inside the
    # window has covered essentially the whole tile and the remainder is picked
    # up by the first frame of the next window
    sim.tick(499)
    assert robot.x == pytest.approx(ROBOT_CENTER[0] - TILE, abs=0.1)
    assert robot.target_x == pytest.approx(ROBOT_CENTER[0] - TILE)

    sim.tick(500)  # equality: no advance, no movement (client branch)
    assert robot.index == 0

    # next command target is two tiles out (the offsets accumulate)
    sim.tick(501)
    assert robot.index == 1
    assert robot.target_x == pytest.approx(ROBOT_CENTER[0] - 2 * TILE, abs=0.1)
    assert robot.x == pytest.approx(ROBOT_CENTER[0] - TILE, abs=0.1)


def test_facing_flips_when_the_route_turns_around() -> None:
    world, _ = make_world(SPIKEBOT_LEVEL_1, [MOVE_RIGHT, MOVE_RIGHT])  # mirrors: 2x Move Left
    sim, robot = make_sim(world, Clock(0))
    assert [cmd.item_id for cmd in robot.commands] == [MOVE_RIGHT, MOVE_RIGHT, MOVE_LEFT, MOVE_LEFT]

    sim.tick(250)
    assert robot.facing_left is False  # moving right

    sim.tick(750)
    assert robot.facing_left is False  # second right leg

    sim.tick(1250)
    assert robot.index == 2 and robot.facing_left is True  # moving left again


def test_sprite_frames_and_flip_per_direction() -> None:
    # ShooterBot L1: base 0, idle 3, direction 6, projectile 2 (docs/cybot.md §2.2)
    world, _ = make_world(SHOOTERBOT_LEVEL_1, [SHOT_LEFT])
    sim, robot = make_sim(world, Clock(0))

    assert robot.sprite_frame(0) == 3  # left/right: base + idle
    assert robot.sprite_frame(400) == 4  # + elapsed/400 % 6
    assert robot.sprite_flip() is True  # left always mirrors

    world, _ = make_world(SHOOTERBOT_LEVEL_1, [MOVE_LEFT, MOVE_LEFT])
    sim, robot = make_sim(world, Clock(0))
    sim.tick(200)
    assert robot.sprite_frame(200) == 1  # idle: base + elapsed/200 % 3
    assert robot.sprite_frame(400) == 2
    assert robot.sprite_flip() is True  # idle uses the facing flag (walking left)


def test_sprite_flip_for_idle_follows_the_facing_flag() -> None:
    world, _ = make_world(SPIKEBOT_LEVEL_1, [MOVE_LEFT, MOVE_LEFT])
    sim, robot = make_sim(world, Clock(0))

    assert robot.sprite_flip() is False  # not moving yet
    sim.tick(250)
    assert robot.facing_left is True
    assert robot.sprite_flip() is True


def test_sprite_frames_for_up_and_down_use_their_own_windows() -> None:
    for command, expected in ((SHOT_UP, 9), (SHOT_DOWN, 15)):
        world, _ = make_world(SHOOTERBOT_LEVEL_1, [command])
        sim, robot = make_sim(world, Clock(0))
        assert robot.sprite_frame(0) == expected


# -- melee (cybotApplyMeleeDamage) ---------------------------------------------------


def spawn_player(world: World, *, flags: CharacterFlags | None = None) -> PlayerController:
    world.set_local_player(1)
    controller = PlayerController(world)
    # put the collision rect over the robot's melee box corner
    controller.spawn(ROBOT_CENTER[0] - HITBOX[0] / 2, ROBOT_CENTER[1] + 4)
    if flags is not None:
        controller.state.flags = flags
    return controller


def test_deadly_robot_kills_and_stops_the_scan() -> None:
    world, _ = make_world(SPIKEBOT_LEVEL_1, [])
    sim, _ = make_sim(world, Clock(0))
    player = spawn_player(world)

    hits = sim.apply_melee(player)
    assert [hit.kind for hit in hits] == ["kill"]
    assert player.killed is True and player.killed_pending is True


def test_unarmed_robot_never_hits() -> None:
    world, _ = make_world(SPIKEBOT_LEVEL_1, [], activated=0)
    sim, _ = make_sim(world, Clock(0))
    player = spawn_player(world)

    assert sim.apply_melee(player) == []
    assert player.killed is False


def test_ignore_spikes_and_main_door_skip_the_robot_damage() -> None:
    world, _ = make_world(SPIKEBOT_LEVEL_1, [])
    sim, _ = make_sim(world, Clock(0))
    player = spawn_player(world, flags=CharacterFlags.IGNORE_SPIKES)
    assert sim.apply_melee(player) == [] and player.killed is False

    # standing on a Main Door tile also skips robots: player on the door below the
    # robot, with a rect that still overlaps the 20x20 melee box
    door = Tile(fg_id=MAIN_DOOR, pos=ivec2(ROBOT_TX, ROBOT_TY + 1))
    world2, _ = make_world(SPIKEBOT_LEVEL_1, [], extra_tiles=[door])
    sim2, _ = make_sim(world2, Clock(0))
    world2.set_local_player(1)
    player2 = PlayerController(world2)
    player2.spawn(ROBOT_CENTER[0] - HITBOX[0] / 2, ROBOT_CENTER[1] + 10)

    assert (player2.x + player2.width / 2) // TILE == ROBOT_TX  # still over the robot column
    assert (player2.y + player2.height / 2) // TILE == ROBOT_TY + 1  # on the door tile
    assert sim2.apply_melee(player2) == [] and player2.killed is False


def test_pointy_robot_knocks_back_and_arms_the_damage_event() -> None:
    world, _ = make_world(SHOCKBOT_LEVEL_1, [])  # ROBOT_POINTY
    sim, _ = make_sim(world, Clock(0))
    player = spawn_player(world)

    player.vx = -10.0
    hits = sim.apply_melee(player)
    assert [hit.kind for hit in hits] == ["damage"]
    assert sim.robots[0].hit_axis in (0, 1)
    assert player.damaged is True
    # the X response inverts and clamps the horizontal speed away from the tile
    if sim.robots[0].hit_axis == 0:
        assert player.vx >= 300.0


def test_lava_robot_uses_the_fire_damage_event() -> None:
    world, _ = make_world(FLAMEBOT_LEVEL_1, [])  # ROBOT_LAVA
    sim, _ = make_sim(world, Clock(0))
    player = spawn_player(world)

    sim.apply_melee(player)
    assert player.on_fire is True
    assert player.damaged is False


def test_melee_cooldown_gate_blocks_repeat_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    robot_item = item_database.get(SEARBOT_LEVEL_1)  # ROBOT_LAVA, cooldown 0 stock
    patched = dataclasses.replace(robot_item, cybot=dataclasses.replace(robot_item.cybot, melee_cooldown_ms=500))
    monkeypatch.setitem(item_database.items, SEARBOT_LEVEL_1, patched)

    world, _ = make_world(SEARBOT_LEVEL_1, [])
    sim, _ = make_sim(world, Clock(1000))
    player = spawn_player(world)

    assert [hit.kind for hit in sim.apply_melee(player)] == ["damage"]
    assert sim.next_hit_ms == 1500
    assert sim.apply_melee(player) == []  # inside the cooldown -> the scan stops

    sim.clock.ms = 1600
    assert [hit.kind for hit in sim.apply_melee(player)] == ["damage"]


# -- projectiles (cybotProjectilesCheckKill) -----------------------------------------


def add_projectile(sim: CyBotWorld, *, x: float, y: float, deadly: bool) -> CyBotProjectile:
    shot = CyBotProjectile(
        base_frame=21,
        frame_count=2,
        angle=0.0,
        x=x,
        y=y,
        origin_x=x,
        origin_y=y,
        flip=False,
        armed=True,
        life_ms=800,
        speed=0.16,
        dir_x=1.0,
        dir_y=0.0,
        deadly=deadly,
    )
    sim.projectiles.append(shot)
    return shot


def test_deadly_projectile_overlap_kills() -> None:
    world, _ = make_world(SHOOTERBOT_LEVEL_1, [])
    sim, _ = make_sim(world, Clock(0))
    player = spawn_player(world)

    add_projectile(sim, x=player.x + 5, y=player.y + 5, deadly=True)
    assert sim.check_kills(player) is not None
    assert player.killed is True


def test_non_deadly_projectile_and_misses_do_nothing() -> None:
    world, _ = make_world(SHOOTERBOT_LEVEL_1, [])
    sim, _ = make_sim(world, Clock(0))
    player = spawn_player(world)

    add_projectile(sim, x=player.x + 5, y=player.y + 5, deadly=False)
    add_projectile(sim, x=player.x + 500, y=player.y + 5, deadly=True)
    assert sim.check_kills(player) is None
    assert player.killed is False


# -- registration / refresh ----------------------------------------------------------


def test_sync_tile_registers_refreshes_and_removes() -> None:
    world, tile = make_world(SPIKEBOT_LEVEL_1, [], pos=(2, 2))
    blank = Tile(fg_id=0, pos=ivec2(2, 2))
    world = World.from_tiles([Tile(fg_id=2, pos=ivec2(2, 2))])
    sim = CyBotWorld(Clock(0))
    sim.load(world)
    assert sim.robots == []

    target = world.get_tile(2, 2)
    assert target is not None
    target.fg_id = SPIKEBOT_LEVEL_1
    target.extra = CybotTile(commands=[CyBotCommandData(item_id=MOVE_LEFT, enabled=1)], anchor_ms=0, activated=1)
    sim.sync_tile(world, 2, 2)
    assert len(sim.robots) == 1
    robot = sim.robots[0]

    # a program change rebuilds in place
    target.extra = CybotTile(commands=[CyBotCommandData(item_id=SHOT_LEFT, enabled=1)], anchor_ms=0, activated=1)
    sim.sync_tile(world, 2, 2)
    assert sim.robots[0] is robot
    assert [cmd.item_id for cmd in robot.commands] == [SHOT_LEFT]

    # breaking the tile removes it
    target.fg_id = 0
    target.extra = None
    sim.sync_tile(world, 2, 2)
    assert sim.robots == []


def test_controller_probe_pass_runs_the_robots() -> None:
    world, _ = make_world(SPIKEBOT_LEVEL_1, [])
    sim, _ = make_sim(world, Clock(0))
    player = spawn_player(world)

    # without the hook the probe pass ignores robots
    player.step()
    assert player.killed is False

    player.cybots = sim
    player.step()
    assert player.killed is True
