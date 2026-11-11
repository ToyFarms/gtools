"""Live capability profile: what *this* avatar can do right now.

Nothing here is a motion constant of its own.  Every number is either

* read from the live ``CharacterState`` (SET_CHARACTER_STATE updates these),
* read from the controller's clothing/mod helpers, or
* imported from ``physics.controller`` where the client value is genuinely fixed
  (single source of truth, no copies).

The fingerprint is what invalidates cached edges when the server changes the
avatar's state or the player changes clothing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from gtools.core.growtopia.physics.controller import (
    ANTIGRAVITY_ACCEL_SCALE,
    BOUNCY_SPEED,
    DAMAGE_SLIP_WALL_BOUNCE,
    DAMAGING_KNOCKBACK_SPEED,
    DAMAGING_LAUNCH_NO_GRAVITY_SPEED,
    DAMAGING_LAUNCH_SPEED,
    GRAVITY_WELL_FALL_SPEEDUP,
    GRAVITY_WELL_PULL,
    GRAVITY_WELL_RANGE_TILES,
    GRAVITY_WELL_UP_SPEEDUP,
    JUMP_CUT_ACCEL,
    JUMP_REDUCED_SCALE,
    JUMP_SPEED,
    MAX_FALL,
    MUD_SPEED_SCALE,
    SLIDE_ACCEL_SCALE,
    SLIDE_WALL_BOUNCE,
    SLOW_FALL_ACCEL_SCALE,
    TRAMPOLINE_MOMENTUM_SPEED,
    TRAMPOLINE_SPEED,
    WATER_FLOAT_ACCEL,
    WATER_FLOAT_DURATION_MS,
    WATER_FLOAT_FALL_ACCEL,
    WATER_FLOAT_MAX_FALL,
    WATER_VERTICAL_SCALE,
    WIND_CROSS_ZERO,
    WIND_OPPOSE_SPEED,
)
from gtools.core.growtopia.physics.pathfinding.types import _clone_permissions
from gtools.core.growtopia.player import CharacterFlags

SLOW_FALL_NONE = 0
SLOW_FALL_PARASOL = 1
SLOW_FALL_GLIDE = 2


@dataclass(frozen=True, slots=True)
class CapabilityProfile:
    """Motion-relevant snapshot of one avatar at one instant."""

    dt: float
    width: float
    height: float

    max_velocity: float
    horizontal_accel: float
    vertical_accel: float
    velocity_in_water: float
    jump_strength: float
    flags: int

    shoes: int
    worn: frozenset[int]
    slow_fall: int
    floatie: bool
    water_vehicle: bool
    water_float_perm: bool
    climb_gear: bool
    slippery: bool
    skates: bool
    can_water_float: bool

    permissions: Any

    # client-fixed values, imported (never re-typed in the pathfinding package)
    jump_speed: float = JUMP_SPEED
    jump_cut_accel: float = JUMP_CUT_ACCEL
    jump_reduced_scale: float = JUMP_REDUCED_SCALE
    max_fall: float = MAX_FALL
    water_vertical_scale: float = WATER_VERTICAL_SCALE
    slow_fall_accel_scale: float = SLOW_FALL_ACCEL_SCALE
    antigravity_accel_scale: float = ANTIGRAVITY_ACCEL_SCALE
    water_float_accel: float = WATER_FLOAT_ACCEL
    water_float_fall_accel: float = WATER_FLOAT_FALL_ACCEL
    water_float_max_fall: float = WATER_FLOAT_MAX_FALL
    water_float_duration_ms: float = WATER_FLOAT_DURATION_MS
    mud_speed_scale: float = MUD_SPEED_SCALE
    slide_accel_scale: float = SLIDE_ACCEL_SCALE
    slide_wall_bounce: float = SLIDE_WALL_BOUNCE
    damage_slip_wall_bounce: float = DAMAGE_SLIP_WALL_BOUNCE
    bouncy_speed: float = BOUNCY_SPEED
    trampoline_speed: float = TRAMPOLINE_SPEED
    trampoline_momentum_speed: float = TRAMPOLINE_MOMENTUM_SPEED
    damaging_knockback_speed: float = DAMAGING_KNOCKBACK_SPEED
    damaging_launch_speed: float = DAMAGING_LAUNCH_SPEED
    damaging_launch_no_gravity_speed: float = DAMAGING_LAUNCH_NO_GRAVITY_SPEED
    wind_oppose_speed: float = WIND_OPPOSE_SPEED
    wind_cross_zero: float = WIND_CROSS_ZERO
    gravity_well_pull: float = GRAVITY_WELL_PULL
    gravity_well_fall_speedup: float = GRAVITY_WELL_FALL_SPEEDUP
    gravity_well_up_speedup: float = GRAVITY_WELL_UP_SPEEDUP
    gravity_well_range_tiles: int = GRAVITY_WELL_RANGE_TILES

    # -- convenience -----------------------------------------------------------

    @property
    def ignore_spikes(self) -> bool:
        return bool(self.flags & CharacterFlags.IGNORE_SPIKES)

    @property
    def ignore_lava(self) -> bool:
        # controller._touch gates the whole _damaging_event call on this flag
        return bool(self.flags & CharacterFlags.IGNORE_LAVA)

    @property
    def noclip(self) -> bool:
        return bool(self.flags & CharacterFlags.NOCLIP)

    @property
    def zombie(self) -> bool:
        return bool(self.flags & CharacterFlags.ZOMBIE)

    @property
    def has_double_jump(self) -> bool:
        return bool(self.flags & CharacterFlags.DOUBLE_JUMP)

    @property
    def horizontal_px_per_tick(self) -> float:
        return self.max_velocity * self.dt

    @property
    def water_px_per_tick(self) -> float:
        return self.velocity_in_water * self.dt

    @property
    def fall_px_per_tick(self) -> float:
        return self.max_fall * self.dt

    @property
    def jump_px_per_tick(self) -> float:
        return self.jump_speed * self.dt

    @property
    def jump_airtime_ticks(self) -> float:
        """Base full-jump airtime (launch to apex and back), in ticks."""
        if self.vertical_accel <= 0.0:
            return 0.0

        return 2.0 * self.jump_speed / self.vertical_accel / self.dt

    @property
    def jump_height_px(self) -> float:
        if self.vertical_accel <= 0.0:
            return 0.0

        return self.jump_speed * self.jump_speed / (2.0 * self.vertical_accel)

    @property
    def horizontal_jump_reach_px(self) -> float:
        """Rough flat-ground jump distance (used only to prune actions)."""
        return self.max_velocity * (self.jump_airtime_ticks * self.dt)

    # -- construction ----------------------------------------------------------

    @classmethod
    def from_controller(cls, controller: Any) -> "CapabilityProfile":
        state = controller.state
        clothing = controller._clothing()
        worn = controller._worn_items()
        slow = controller._slow_fall_flags()
        if slow is None:
            slow_fall = SLOW_FALL_NONE
        else:
            slow_fall = SLOW_FALL_PARASOL if slow[0] else SLOW_FALL_GLIDE

        return cls(
            dt=float(controller.fixed_dt),
            width=float(controller.width),
            height=float(controller.height),
            max_velocity=float(state.max_velocity),
            horizontal_accel=float(state.horizontal_accel),
            vertical_accel=float(state.vertical_accel),
            velocity_in_water=float(state.velocity_in_water),
            jump_strength=float(state.jump_strength),
            flags=int(state.flags),
            shoes=int(clothing.shoes) if clothing is not None else 0,
            worn=frozenset(worn),
            slow_fall=slow_fall,
            floatie=bool(controller._is_floatie()),
            water_vehicle=bool(controller._has_water_vehicle()),
            water_float_perm=bool(controller._has_water_float_perm()),
            climb_gear=bool(controller._climb_gear()),
            slippery=bool(controller._slippery_clothing()),
            skates=bool(controller._wearing_skates()),
            can_water_float=bool(controller._has_water_vehicle() or controller._has_water_float_perm()),
            permissions=_clone_permissions(controller.permissions),
        )

    # -- invalidation ----------------------------------------------------------

    def fingerprint(self) -> tuple:
        """Everything that can change motion; mutable per-run state is excluded."""
        perms = self.permissions
        return (
            round(self.dt, 9),
            round(self.width, 9),
            round(self.height, 9),
            round(self.max_velocity, 9),
            round(self.horizontal_accel, 9),
            round(self.vertical_accel, 9),
            round(self.velocity_in_water, 9),
            round(self.jump_strength, 9),
            self.flags,
            self.shoes,
            tuple(sorted(self.worn)),
            self.slow_fall,
            self.floatie,
            self.water_vehicle,
            self.water_float_perm,
            self.climb_gear,
            self.slippery,
            self.skates,
            self.can_water_float,
            perms.user_id,
            perms.guild_id,
            perms.guild_rank,
            perms.team,
            perms.has_team,
            perms.friend,
            perms.protocol_version,
            tuple(sorted(perms.adventure_flags)),
        )

    def same_motion(self, other: "CapabilityProfile") -> bool:
        return self.fingerprint() == other.fingerprint()


def movement_seconds(profile: CapabilityProfile, tiles: float) -> float:
    """Analytic lower bound (seconds) to cover ``tiles`` horizontally."""
    speed = max(profile.max_velocity, 1e-9)

    return tiles * 32.0 / speed


def jump_apex_seconds(profile: CapabilityProfile) -> float:
    if profile.vertical_accel <= 0.0:
        return math.inf

    return profile.jump_speed / profile.vertical_accel
