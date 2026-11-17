"""Blast simulation -- ``gtools.core.growtopia.blaster``.

Every rule is a port of a verified client function (``docs/blaster.md``):

* ``createNpcAndPushBack`` 0x1402B56F0 -- ``type``/``uid``/``param1..3`` mapping,
  per-uid slot reuse, the 106-entry cap, ``timer = 0`` and the spawn-tile gate
  (a BLASTER tile under the spawn point arms its 1000 ms timer and requests
  ``audio/flame_go.wav``);
* ``updateNPC`` 0x1402B7530 cases 8 / 15 -- timer-driven trail particle at the
  *pre-move* position, then ``pos += dir(param3) * (int)param2 * dt`` and
  **no** despawn condition;
* the kill test inside that same update: blast point inside the collision rect,
  avatar not dying (``state_2088 == 6``), a tile under the hitbox centre that is
  not an item of type ``DOOR``;
* ``npcHandleAction`` 0x1402B5A40 (DIE) and ``npcResetAction`` 0x1402B59E0
  (DELETE).
"""

import pytest
from pyglm.glm import ivec2, vec2

from gtools.baked.items import DIRT, HOWLER, MAIN_DOOR, TRICKSTER
from gtools.core.growtopia.blaster import (
    NPC_CAP,
    MAX_PARTICLES,
    TRAIL_PARTICLE,
    BlastWorld,
    _point_in_rect,
)
from gtools.core.growtopia.physics.controller import PlayerController
from gtools.core.growtopia.player import CharacterFlags
from gtools.core.growtopia.world import Npc, NpcType, Tile, World

TILE = 32
SPAWN = (5 * TILE + TILE / 2, 5 * TILE + TILE / 2)  # client tileToWorldCenter


class Clock:
    def __init__(self, ms: int = 0) -> None:
        self.ms = ms

    def __call__(self) -> float:
        return self.ms


def make_world(*tiles: Tile) -> World:
    # a far tile keeps the grid 20x20 so out-of-bounds maths has a boundary
    return World.from_tiles([*tiles, Tile(fg_id=DIRT, pos=ivec2(19, 19))])


def make_npc(
    *,
    npc_type: NpcType = NpcType.BLAST,
    uid: int = 7,
    x: float = SPAWN[0],
    y: float = SPAWN[1],
    speed: int = 100,
    angle: float = 0.0,
    param1: int = 0,
) -> Npc:
    return Npc(
        type=npc_type,
        id=uid,
        pos=vec2(x, y),
        target_pos=vec2(x, y),
        param1=param1,
        param2=speed,
        param3=angle,
    )


def make_player(world: World, x: float = 100.0, y: float = 100.0) -> PlayerController:
    world.set_local_player(1)
    controller = PlayerController(world, auto_respawn=False)
    controller.spawn(x, y)
    return controller


# -- registration (createNpcAndPushBack) ---------------------------------------------


def test_add_maps_the_npc_wire_fields() -> None:
    sim = BlastWorld(Clock(0))

    blast = sim.add(make_npc(uid=9, speed=480, angle=45.0, param1=3), now_ms=1000)

    assert blast is not None
    assert (blast.uid, blast.type) == (9, NpcType.BLAST)
    assert (blast.x, blast.y) == SPAWN
    assert blast.target_x == SPAWN[0] and blast.target_y == SPAWN[1]
    assert blast.param1 == 3
    assert blast.speed == 480  # param2
    assert blast.angle == 45.0  # param3
    assert blast.timer == 0.0


def test_add_ignores_every_other_npc_type() -> None:
    sim = BlastWorld(Clock(0))

    for npc_type in (NpcType.GHOST, NpcType.BEE_SWARM, NpcType.PINATA, NpcType.TRICKSTER + 100):
        assert sim.add(make_npc(npc_type=npc_type)) is None

    assert sim.blasts == []
    assert sim.add(make_npc(npc_type=NpcType.TRICKSTER)) is not None


def test_add_reuses_the_uid_slot() -> None:
    sim = BlastWorld(Clock(0))
    first = sim.add(make_npc(uid=7, x=100.0, y=100.0, speed=100, angle=0.0))
    assert first is not None
    first.timer = 0.4

    second = sim.add(make_npc(uid=7, x=200.0, y=200.0, speed=300, angle=180.0))

    assert second is first  # the client updates the existing entry in place
    assert len(sim.blasts) == 1
    assert (first.x, first.y) == (200.0, 200.0)
    assert (first.speed, first.angle) == (300, 180.0)
    assert first.timer == 0.0  # createNpcAndPushBack resets the particle timer


def test_add_caps_the_npc_vector() -> None:
    sim = BlastWorld(Clock(0))

    for uid in range(NPC_CAP):
        assert sim.add(make_npc(uid=uid)) is not None
    assert sim.add(make_npc(uid=NPC_CAP)) is None  # createNpcAndPushBack: >105 entries

    assert len(sim.blasts) == NPC_CAP


def test_add_arms_the_blaster_tile_and_requests_the_spawn_audio() -> None:
    blaster = Tile(fg_id=HOWLER, pos=ivec2(5, 5))
    world = make_world(blaster)
    sim = BlastWorld(Clock(0))

    sim.add(make_npc(x=SPAWN[0], y=SPAWN[1]), world, now_ms=4000)

    assert blaster.next_update_ms == 4000 + 1000
    assert sim.sounds == ["audio/flame_go.wav"]


def test_spawn_gate_ignores_non_blaster_tiles() -> None:
    dirt = Tile(fg_id=DIRT, pos=ivec2(5, 5))
    world = make_world(dirt)
    sim = BlastWorld(Clock(0))

    sim.add(make_npc(), world, now_ms=4000)

    assert dirt.next_update_ms == 0
    assert sim.sounds == []


def test_spawn_without_a_world_is_fine() -> None:
    sim = BlastWorld(Clock(0))
    assert sim.add(make_npc()) is not None
    assert sim.sounds == []


# -- motion + trail (updateNPC cases 8 / 15) -----------------------------------------


def test_motion_uses_the_integer_speed_and_the_degree_angle() -> None:
    clock = Clock(0)
    sim = BlastWorld(clock)
    blast = sim.add(make_npc(x=0.0, y=0.0, speed=120, angle=90.0))
    assert blast is not None

    sim.tick()  # first sample only primes the clock
    assert (blast.x, blast.y) == (0.0, 0.0)
    clock.ms = 500
    sim.tick()

    assert blast.x == pytest.approx(0.0, abs=1e-6)
    assert blast.y == pytest.approx(60.0)


def test_trail_particle_spawns_at_the_pre_move_position() -> None:
    clock = Clock(0)
    sim = BlastWorld(clock)
    blast = sim.add(make_npc(x=0.0, y=0.0, speed=100, angle=0.0))
    assert blast is not None
    sim.tick()

    clock.ms = 100
    sim.tick()

    assert blast.x == pytest.approx(10.0)  # moved after the particle was spawned
    assert len(sim.particles) == 1
    particle = sim.particles[0]
    assert particle.particle_id == TRAIL_PARTICLE[NpcType.BLAST] == 212
    assert (particle.x, particle.y) == (0.0, 0.0)
    assert particle.angle == 0.0


def test_a_long_frame_emits_a_single_particle() -> None:
    """``updateNPC`` uses ``if``, not ``while``: one particle per frame, timer kept."""

    clock = Clock(0)
    sim = BlastWorld(clock)
    blast = sim.add(make_npc(speed=0))
    assert blast is not None
    sim.tick()

    clock.ms = 300
    sim.tick()
    assert len(sim.particles) == 1
    assert blast.timer == pytest.approx(0.2)  # 0.3 - one 0.1 step

    clock.ms = 400
    sim.tick()
    assert len(sim.particles) == 2  # one more, not two
    assert blast.timer == pytest.approx(0.2)


def test_trickster_flies_with_particle_276() -> None:
    clock = Clock(0)
    sim = BlastWorld(clock)
    sim.add(make_npc(npc_type=NpcType.TRICKSTER, speed=0))
    sim.tick()
    clock.ms = 100
    sim.tick()

    assert [p.particle_id for p in sim.particles] == [276]


def test_blast_has_no_client_side_lifetime() -> None:
    clock = Clock(0)
    sim = BlastWorld(clock)
    blast = sim.add(make_npc(x=0.0, y=0.0, speed=100, angle=0.0))
    assert blast is not None
    sim.tick()

    clock.ms = 60_000
    sim.tick()

    assert sim.blasts == [blast]  # updateNPC never clears type 8/15
    assert blast.x == pytest.approx(6000.0)


def test_clock_is_injectable_for_replays() -> None:
    sim = BlastWorld(lambda: 1234.0)
    assert sim.now() == 1234
    assert sim.now(99) == 99


# -- particle pool -------------------------------------------------------------------


def test_trail_particles_age_and_expire() -> None:
    clock = Clock(0)
    sim = BlastWorld(clock)
    sim.add(make_npc())
    sim.despawn(7)  # 4 impact particles, no blast left to emit more
    assert len(sim.particles) == 4
    sim.tick()

    clock.ms = 100
    sim.tick()
    assert len(sim.particles) == 4
    assert all(p.age_ms == pytest.approx(100.0) for p in sim.particles)

    clock.ms = 500
    sim.tick()
    assert sim.particles == []  # 500 ms lifetime


def test_particle_pool_drops_the_oldest_past_the_engine_cap() -> None:
    sim = BlastWorld(Clock(0))

    for round_ in range(2):
        for uid in range(NPC_CAP):
            sim.add(make_npc(uid=uid))
        for uid in range(NPC_CAP):
            sim.despawn(uid)

    assert len(sim.particles) == MAX_PARTICLES


# -- DIE / DELETE --------------------------------------------------------------------


def test_despawn_bursts_the_howler_impact_particles() -> None:
    sim = BlastWorld(Clock(0))
    sim.add(make_npc(uid=4, x=10.0, y=10.0))

    blast = sim.despawn(4, x=50.0, y=60.0)

    assert blast is not None and sim.blasts == []
    assert len(sim.particles) == 4
    for particle in sim.particles:
        assert particle.particle_id == 212
        assert (particle.x, particle.y) == (50.0, 60.0)  # the action position
        assert 0.0 <= particle.angle < 360.0
    assert sim.effects == []


def test_despawn_trickster_records_the_effect_ids() -> None:
    sim = BlastWorld(Clock(0))
    sim.add(make_npc(npc_type=NpcType.TRICKSTER, uid=4))

    assert sim.despawn(4) is not None

    assert sim.particles == []
    assert sim.effects == [178, 223]
    assert sim.despawn(4) is None


def test_delete_frees_the_slot_without_a_burst() -> None:
    sim = BlastWorld(Clock(0))
    sim.add(make_npc(uid=8))

    assert sim.delete(8) is True
    assert sim.blasts == [] and sim.particles == [] and sim.effects == []
    assert sim.delete(8) is False


# -- kill test (inside updateNPC) ----------------------------------------------------


def add_blast_in_player(player: PlayerController, sim: BlastWorld, *, npc_type: NpcType = NpcType.BLAST):
    x = player.x + player.width / 2
    y = player.y + player.height / 2
    return sim.add(make_npc(npc_type=npc_type, uid=1, x=x, y=y, speed=0))


def test_blast_point_inside_the_collision_rect_kills() -> None:
    world = make_world()
    sim = BlastWorld(Clock(0))
    player = make_player(world)
    add_blast_in_player(player, sim)

    hit = sim.check_kills(player)

    assert hit is not None
    assert player.killed is True and player.killed_pending is True


def test_blast_outside_the_rect_does_not_kill() -> None:
    world = make_world()
    sim = BlastWorld(Clock(0))
    player = make_player(world)
    sim.add(make_npc(uid=1, x=player.x + player.width + 1, y=player.y + 5, speed=0))

    assert sim.check_kills(player) is None
    assert player.killed is False


def test_a_dying_player_is_not_killed_twice() -> None:
    """``state_2088 == 6`` (the dying state) suppresses a repeat kill."""

    world = make_world()
    sim = BlastWorld(Clock(0))
    player = make_player(world)
    add_blast_in_player(player, sim)
    player._kill(0, 0)

    assert sim.check_kills(player) is None


def test_main_door_under_the_player_blocks_the_kill() -> None:
    # the player's hitbox centre sits on tile (3, 3)
    door = Tile(fg_id=MAIN_DOOR, pos=ivec2(3, 3))
    world = make_world(door)
    sim = BlastWorld(Clock(0))
    player = make_player(world)
    add_blast_in_player(player, sim)

    assert sim.check_kills(player) is None
    assert player.killed is False


def test_out_of_bounds_player_has_no_tile_and_survives() -> None:
    world = make_world()
    sim = BlastWorld(Clock(0))
    player = make_player(world, x=-100.0, y=100.0)
    add_blast_in_player(player, sim)

    assert sim.check_kills(player) is None


def test_kill_works_for_trickster_blasts_too() -> None:
    world = make_world()
    sim = BlastWorld(Clock(0))
    player = make_player(world)
    add_blast_in_player(player, sim, npc_type=NpcType.TRICKSTER)

    assert sim.check_kills(player) is not None


def test_the_blast_is_not_consumed_by_the_kill() -> None:
    world = make_world()
    sim = BlastWorld(Clock(0))
    player = make_player(world)
    add_blast_in_player(player, sim)

    sim.check_kills(player)

    assert len(sim.blasts) == 1  # the server removes it, not the kill test


def test_point_in_rect_accepts_an_inverted_rect() -> None:
    """``sub_14002F680`` tests both corner orderings."""

    assert _point_in_rect((200.0, 200.0, 100.0, 100.0), 150.0, 150.0) is True
    assert _point_in_rect((100.0, 100.0, 200.0, 200.0), 150.0, 150.0) is True
    assert _point_in_rect((100.0, 100.0, 200.0, 200.0), 250.0, 150.0) is False


# -- controller integration ----------------------------------------------------------


def test_controller_step_runs_the_kill_test() -> None:
    world = make_world()
    sim = BlastWorld(Clock(0))
    player = make_player(world)
    player.blasts = sim
    add_blast_in_player(player, sim)

    player.step()

    assert player.killed is True


def test_controller_without_blasts_is_untouched() -> None:
    world = make_world()
    sim = BlastWorld(Clock(0))
    player = make_player(world)
    add_blast_in_player(player, sim)

    player.step()

    assert player.killed is False


def test_noclip_avatar_is_still_hit() -> None:
    """The client checks blasts inside ``updateNPC``, not in the NOCLIP-gated
    probe pass (unlike cybot melee)."""

    world = make_world()
    sim = BlastWorld(Clock(0))
    player = make_player(world)
    player.state.flags = CharacterFlags.NOCLIP
    player.blasts = sim
    add_blast_in_player(player, sim)

    player.step()

    assert player.killed is True
