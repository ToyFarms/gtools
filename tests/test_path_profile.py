"""CapabilityProfile mirrors the live controller and invalidates on change."""

from __future__ import annotations

from pyglm.glm import ivec2

from gtools.baked.items import DIRT, MAIN_DOOR, PARASOL
from gtools.core.growtopia.physics.controller import HITBOX, PlayerController
from gtools.core.growtopia.physics.pathfinding.profile import CapabilityProfile
from gtools.core.growtopia.player import CharacterFlags, CharacterState, Clothing, Player
from gtools.core.growtopia.world import Tile, World

FLOOR_Y = 8


def make(clothing=None, state=None):
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(20)]
    tiles.append(Tile(fg_id=MAIN_DOOR, pos=ivec2(1, FLOOR_Y - 1)))
    world = World.from_tiles(tiles)
    world.players[1] = Player(net_id=1, clothing=clothing or Clothing())
    controller = PlayerController(world, net_id=1, send=None, auto_respawn=False, state=state)
    controller.spawn(4 * 32 + 6.0, FLOOR_Y * 32 - HITBOX[1])
    return controller, profile_of(controller)


def profile_of(controller):
    return CapabilityProfile.from_controller(controller)


def test_profile_mirrors_live_state():
    state = CharacterState(max_velocity=333.0, horizontal_accel=700.0, vertical_accel=800.0, velocity_in_water=99.0, jump_strength=1.0, flags=CharacterFlags.DOUBLE_JUMP)
    _, profile = make(state=state)
    assert profile.dt == 1.0 / 60.0
    assert profile.width == HITBOX[0] and profile.height == HITBOX[1]
    assert profile.max_velocity == 333.0
    assert profile.horizontal_accel == 700.0
    assert profile.vertical_accel == 800.0
    assert profile.velocity_in_water == 99.0
    assert profile.has_double_jump
    assert not profile.ignore_spikes and not profile.ignore_lava and not profile.noclip


def test_fingerprint_changes_with_state_and_clothing():
    controller, profile = make()
    base = profile.fingerprint()
    assert profile.fingerprint() == base

    controller.state.max_velocity = 400.0
    assert profile_of(controller).fingerprint() != base

    controller.state.max_velocity = 250.0
    controller.state.flags = CharacterFlags.IGNORE_SPIKES
    assert profile_of(controller).fingerprint() != base

    controller.state.flags = CharacterFlags.NONE
    assert profile_of(controller).fingerprint() == base

    controller.world.players[1].clothing = Clothing(hand=PARASOL)
    changed = profile_of(controller)
    assert changed.fingerprint() != base
    assert changed.slow_fall

    controller.permissions.user_id = 1234
    assert profile_of(controller).fingerprint() != changed.fingerprint()


def test_mods_and_derived_envelope():
    controller, profile = make(clothing=Clothing(hand=PARASOL))
    assert profile.slow_fall
    assert profile.jump_height_px > 0
    assert profile.jump_airtime_ticks > 0
    assert profile.horizontal_jump_reach_px > 0

    controller.state.vertical_accel = 0.0
    weightless = profile_of(controller)
    assert weightless.jump_airtime_ticks == 0.0
    assert weightless.jump_height_px == 0.0
