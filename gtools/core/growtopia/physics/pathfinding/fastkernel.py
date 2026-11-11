"""Exact, allocation-light tick kernel over a ``WorldSnapshot``.

This is the *fast evaluation path*, not the definition of physics.  It mirrors
``PlayerController._simulate`` in the same order, with the same float operations,
and the differential fuzz suite (``tests/test_path_fastkernel.py``) proves it
tick-for-tick against a real controller.

Performance shortcuts are exact:

* ``_move`` skips the per-pixel loop when the swept volume contains no blocking
  tile, applying the integer displacement directly (identical float result);
* tile facts come from flat arrays;
* one mutable ``MotionState`` is reused by the caller.

Deadly and damaging are handled as distinct classes:

* deadly -> ``_kill`` (terminal, simulation stops next tick);
* damaging -> X knockback / Y -800 launch + ``damage_slip`` (survivable, priced).
"""

from __future__ import annotations

import os

import math
from typing import Any, Callable

from gtools.baked.items import (
    ADVENTURE_ITEM_ROPE,
    ADVENTURE_ROPE_PITON,
    CLIMBING_WALL,
    HAY,
    HYPERTECH_ANTIGRAVITY_FIELD,
    SLIPPERY_FLAG_POLE,
    SNOW_BLOCK,
    SNOWSHOES,
    STEAM_LAUNCHER,
)
from gtools.core.growtopia.items_dat import ItemInfoCollisionType
from gtools.core.growtopia.physics.controller import _EPS, PlayerController, TILE
from gtools.core.growtopia.physics.pathfinding.profile import CapabilityProfile
from gtools.core.growtopia.physics.pathfinding.snapshot import (
    PermissionView,
    BOUNCE_RADIAL,
    BOUNCE_STEAM,
    BOUNCE_TRAMPOLINE,
    BOUNCE_TRAMPOLINE_MOMENTUM,
    DAMAGE_ACID,
    DAMAGE_FIRE,
    DAMAGE_GENERIC,
    DAMAGE_NONE,
    ProbeWorld,
    WorldSnapshot,
)
from gtools.core.growtopia.physics.pathfinding.types import InputFrame, MotionState, Outcome, _clone_permissions
from gtools.core.growtopia.world import TileFlags

# integer masks: ``int & IntFlag`` round-trips through ``__rand__`` and allocates
# a flag object per test, which dominated the per-tick profile
_IS_ON = int(TileFlags.IS_ON)
_IS_WET = int(TileFlags.IS_WET)
_FLIPPED_X = int(TileFlags.FLIPPED_X)


_PermissionView = PermissionView


class FastEvaluator:
    """Mirror of the controller's per-tick simulation over a snapshot."""

    __slots__ = (
        "snapshot",
        "grid",
        "profile",
        "width",
        "height",
        "_gw",
        "_gh",
        "_dt",
        "_perm_world",
        "_perm_view",
        "_noclip",
        "_ignore_spikes",
        "_ignore_lava",
        "_zombie",
        "_slow_fall",
        "_double_jump",
        "_damage_hits",
        "_bounced",
        "_launched",
        "_climbed",
        "_entered_water",
        "_used_wind",
        "_used_well",
        "_killed",
        "_nb",
    )

    def __init__(self, snapshot: WorldSnapshot, profile: CapabilityProfile, *, use_numba: bool | None = None) -> None:
        self.snapshot = snapshot
        self.grid = snapshot.grid
        self.profile = profile
        self.width = float(profile.width)
        self.height = float(profile.height)
        self._gw = int(snapshot.grid.width)
        self._gh = int(snapshot.grid.height)
        self._dt = float(profile.dt)
        # hot boolean predicates: each property does an IntFlag bit test
        self._noclip = bool(profile.noclip)
        self._ignore_spikes = bool(profile.ignore_spikes)
        self._ignore_lava = bool(profile.ignore_lava)
        self._zombie = bool(profile.zombie)
        self._slow_fall = bool(profile.slow_fall)
        self._double_jump = bool(profile.has_double_jump)
        self._perm_world = snapshot.probe_world()
        self._perm_view = _PermissionView(self._perm_world, profile.permissions)
        self._nb = _make_backend(snapshot, profile, use_numba)
        self._reset_events()

    # -- state construction -----------------------------------------------------

    def initial_state(self) -> MotionState:
        state = MotionState(permissions=_clone_permissions(self.profile.permissions))
        return state

    def state_from_controller(self, controller: Any) -> MotionState:
        state = MotionState(
            x=float(controller.x),
            y=float(controller.y),
            vx=float(controller.vx),
            vy=float(controller.vy),
            frac_x=float(controller.frac_x),
            frac_y=float(controller.frac_y),
            time_ms=float(controller.time_ms),
            left=bool(controller.left),
            right=bool(controller.right),
            jump=bool(controller.jump),
            jump_latch=bool(controller.jump_latch),
            facing_right=bool(controller.facing_right),
            grounded=bool(controller.grounded),
            sliding=bool(controller.sliding),
            in_water=bool(controller.in_water),
            water_float=bool(controller.water_float),
            water_enter_ms=float(controller.water_enter_ms),
            mud=bool(controller.mud),
            left_ground=bool(controller.left_ground),
            damage_slip=bool(controller.damage_slip),
            climbing=bool(controller.climbing),
            double_jumped=bool(controller.double_jumped),
            killed=bool(controller.killed),
            permissions=_clone_permissions(controller.permissions),
        )

        return state

    # -- driving ----------------------------------------------------------------

    def apply_input(self, state: MotionState, direction: int, jump: bool) -> None:
        state.left = direction < 0
        state.right = direction > 0
        if jump != state.jump:
            state.jump_latch = jump
            if jump:
                self._jump(state)
        state.jump = jump

    def simulate(
        self,
        state: MotionState,
        frames: tuple[InputFrame, ...] | list[InputFrame],
        *,
        max_ticks: int | None = None,
        stop_when: Callable[[MotionState, int], bool] | None = None,
        record_trace: bool = False,
    ) -> Outcome:
        """Run ``frames`` on ``state`` (mutating it) and return the outcome."""
        backend = self._nb
        if backend is not None and backend.can_run(state, stop_when):
            return backend.simulate(
                state,
                frames,
                max_ticks=max_ticks,
                stop_when=stop_when,
                record_trace=record_trace,
            )

        self._reset_events()
        if state.permissions is None:
            state.permissions = _clone_permissions(self.profile.permissions)
        self._perm_view.permissions = state.permissions

        ticks = 0
        trace: list[tuple[float, float, bool]] = []
        min_tx, min_ty, max_tx, max_ty = self._bbox(state)
        start_x, start_y = state.x, state.y
        reason = "timeout"
        killed_at_start = state.killed

        for direction, jump, count in frames:
            for _ in range(max(0, int(count))):
                if state.killed:
                    reason = "killed"
                    break
                # mirror PlayerController.step(): time advances before _simulate
                state.time_ms += self._dt * 1000.0
                self.apply_input(state, direction, jump)
                self._simulate(state)
                ticks += 1
                tx0, ty0, tx1, ty1 = self._bbox(state)
                min_tx, min_ty = min(min_tx, tx0), min(min_ty, ty0)
                max_tx, max_ty = max(max_tx, tx1), max(max_ty, ty1)
                if record_trace:
                    trace.append((state.x, state.y, state.grounded))
                if stop_when is not None and stop_when(state, ticks):
                    reason = "stopped"
                    break
                if max_ticks is not None and ticks >= max_ticks:
                    reason = "timeout"
                    break
            else:
                continue
            break

        if not state.killed:
            if state.climbing:
                reason = "climb"
            elif state.in_water:
                reason = "water"
            elif state.grounded:
                reason = "landed"

        if state.killed and not killed_at_start:
            reason = "killed"

        return Outcome(
            state=state,
            ticks=ticks,
            reason=reason,
            damage_hits=self._damage_hits,
            bounced=self._bounced,
            launched=self._launched,
            climbed=self._climbed,
            entered_water=self._entered_water,
            used_wind=self._used_wind,
            used_well=self._used_well,
            bbox=(min_tx, min_ty, max_tx, max_ty),
            tick_trace=trace,
        )

    def simulate_tick(self, state: MotionState, direction: int, jump: bool) -> None:
        """One tick (no bookkeeping) -- used by differential tests."""
        backend = self._nb
        if backend is not None and backend.can_run(state, None):
            backend.simulate_tick(state, direction, jump)
            return

        state.time_ms += self._dt * 1000.0
        self.apply_input(state, direction, jump)
        self._simulate(state)

    def _reset_events(self) -> None:
        self._damage_hits = 0
        self._bounced = False
        self._launched = False
        self._climbed = False
        self._entered_water = False
        self._used_wind = False
        self._used_well = False
        self._killed = False

    # -- tile queries -----------------------------------------------------------

    def _idx(self, x: int, y: int) -> int | None:
        # inlined ``TileGrid.index``: this is the single hottest call in the kernel
        if 0 <= x < self._gw and 0 <= y < self._gh:
            return y * self._gw + x

        return None

    def _fg(self, idx: int | None) -> int:
        return self.grid.fg_id[idx] if idx is not None else 0

    def _flags(self, state: MotionState, idx: int) -> int:
        return self.grid.flags_at(idx, state.flag_overrides)

    def _tile(self, state: MotionState, idx: int):
        return self.snapshot.tile(idx, state.flag_overrides)

    def _blocks_like(self, state: MotionState, idx: int) -> bool:
        if self.grid.gated[idx]:
            self._perm_view.permissions = state.permissions
            return bool(self._perm_view._blocks_like_client(self._tile(state, idx), ItemInfoCollisionType(self.grid.collision[idx])))

        return bool(self.grid.blocks[idx])

    def _can_enter_x(self, state: MotionState, tx: int, ty: int, direction: int) -> bool:
        idx = self._idx(tx, ty)
        if idx is None or self.grid.fg_id[idx] <= 0:
            return True

        kind = self.grid.collision[idx]
        if kind in (ItemInfoCollisionType.JUMP_THROUGH, ItemInfoCollisionType.JUMP_DOWN):
            return True
        if kind == ItemInfoCollisionType.ONE_WAY:
            flipped = bool(self._flags(state, idx) & _FLIPPED_X)
            return (flipped and direction < 0) or (not flipped and direction > 0)

        return not self._blocks_like(state, idx)

    def _can_enter_y(self, state: MotionState, tx: int, ty: int, y: float, direction: int) -> bool:
        idx = self._idx(tx, ty)
        if idx is None or self.grid.fg_id[idx] <= 0:
            return True

        kind = self.grid.collision[idx]
        if kind == ItemInfoCollisionType.JUMP_THROUGH:
            if direction > 0 and math.floor(y + self.height) == ty * int(TILE) + 1:
                return False
            return True
        if kind == ItemInfoCollisionType.JUMP_DOWN:
            return direction > 0
        if kind == ItemInfoCollisionType.ONE_WAY:
            return True

        return not self._blocks_like(state, idx)

    def _interaction_blocked(self, state: MotionState, idx: int) -> bool:
        if self.grid.fg_id[idx] <= 0:
            return False
        kind = self.grid.collision[idx]
        if kind in (ItemInfoCollisionType.JUMP_THROUGH, ItemInfoCollisionType.JUMP_DOWN, ItemInfoCollisionType.ONE_WAY):
            return False

        return self._blocks_like(state, idx)

    def _is_ground(self, state: MotionState, tx: int, ty: int) -> bool:
        idx = self._idx(tx, ty)
        if idx is None or self.grid.fg_id[idx] <= 0:
            return False
        kind = self.grid.collision[idx]
        if kind == ItemInfoCollisionType.JUMP_DOWN:
            return False
        if self.grid.gated[idx]:
            return self._blocks_like(state, idx)

        return bool(self.grid.blocks[idx] or self.grid.platform[idx])

    def _is_deadly(self, state: MotionState, idx: int) -> bool:
        if self.grid.deadly[idx]:
            return True
        if self.grid.deadly_if_on[idx] and self._flags(state, idx) & _IS_ON:
            return True

        return False

    def _damaging_event(self, state: MotionState, idx: int) -> int:
        damage = self.grid.damage[idx]
        if damage:
            return damage
        if self.grid.damage_if_on[idx] and self._flags(state, idx) & _IS_ON:
            return self.grid.damage_if_on[idx]

        return DAMAGE_NONE

    # -- simulation -------------------------------------------------------------

    def _simulate(self, state: MotionState) -> None:
        if state.killed:
            return

        dt = self._dt
        self._check_tile_mod(state)

        centre = self._centre_idx(state)

        # vertical -- integrateVerticalAxis
        if state.grounded:
            state.vy = min(state.vy, 0.0)
        else:
            accel = self.profile.vertical_accel
            max_fall = self.profile.max_fall
            if accel > 0.0:
                if state.vy < 0.0 and not state.jump_latch:
                    accel += self.profile.jump_cut_accel
                elif state.damage_slip:
                    accel += self.profile.jump_cut_accel * 0.85
                if state.vy > 0.0 and state.jump_latch and not state.in_water and not self._zombie:
                    if self._slow_fall:
                        accel *= self.profile.slow_fall_accel_scale
                if centre is not None and self.grid.fg_id[centre] == HYPERTECH_ANTIGRAVITY_FIELD:
                    accel *= self.profile.antigravity_accel_scale
            if state.in_water:
                accel *= self.profile.water_vertical_scale
                max_fall = self.profile.max_fall * self.profile.water_vertical_scale
                if state.water_float:
                    accel = 0.0
                    max_fall = 0.0
                if self.profile.floatie:
                    accel = self.profile.water_float_accel
                    if state.vy > 0.0:
                        accel = self.profile.water_float_fall_accel
                        state.vy = min(state.vy, self.profile.water_float_max_fall)
            elif centre is not None and self.grid.fg_id[centre] == SLIPPERY_FLAG_POLE:
                accel *= self.profile.water_vertical_scale
                max_fall = self.profile.max_fall * self.profile.water_vertical_scale
            state.vy = min(state.vy + dt * accel, max_fall)
            if accel < 0.0:
                state.vy = max(state.vy, -max_fall)

        # horizontal -- validatePhysics
        direction = int(state.right) - int(state.left)
        if direction:
            state.facing_right = direction > 0
        elif state.vx:
            state.facing_right = state.vx > 0.0
        cap = self.profile.velocity_in_water if state.in_water else self.profile.max_velocity
        if state.mud:
            cap *= self.profile.mud_speed_scale
        step_v = self.profile.horizontal_accel * dt
        if state.sliding and state.vy <= 0.0:
            step_v *= self.profile.slide_accel_scale
        if state.damage_slip:
            step_v *= self.profile.slide_accel_scale
        if state.sliding or state.damage_slip:
            if direction > 0 and state.vx < cap:
                state.vx = min(state.vx + step_v, cap)
            elif direction < 0 and state.vx > -cap:
                state.vx = max(state.vx - step_v, -cap)
        else:
            state.vx = _approach(state.vx, direction * cap, step_v)

        self._apply_wind(state, cap)

        pull_x, pull_y = self._gravity_well_pull(state)
        step_x = max(-TILE, min(TILE, (state.vx + pull_x) * dt))
        step_y = max(-TILE, min(TILE, (state.vy + pull_y) * dt))
        self._touch(state, step_x, step_y)
        self._move(state, (state.vx + pull_x) * dt, 0)
        self._move(state, (state.vy + pull_y) * dt, 1)
        self._settle(state)

        state.x = max(0.0, min(self.grid.width * TILE - self.width, state.x))
        state.y = max(0.0, min(self.grid.height * TILE - self.height, state.y))

    # -- jump -------------------------------------------------------------------

    def _jump(self, state: MotionState) -> None:
        below = self._below_idx(state)
        centre = self._centre_idx(state)
        below_fg = self._fg(below)
        centre_fg = self._fg(centre)

        antigrav = below_fg == HYPERTECH_ANTIGRAVITY_FIELD or centre_fg == HYPERTECH_ANTIGRAVITY_FIELD
        pole = below_fg == SLIPPERY_FLAG_POLE or centre_fg == SLIPPERY_FLAG_POLE
        double_jump = self._double_jump and not state.double_jumped
        can_swim = state.in_water and (state.vy > 0.0 or state.water_float)
        can_jump = state.grounded or state.left_ground or double_jump or self.profile.noclip or antigrav or pole or can_swim

        state.left_ground = False
        if not can_jump:
            return

        state.climbing = False
        was_grounded = state.grounded
        snow_locked = below_fg == SNOW_BLOCK and self.profile.shoes != SNOWSHOES
        reduced = state.in_water or state.mud or pole or below_fg == HAY or snow_locked
        state.vy = -self.profile.jump_speed * (self.profile.jump_reduced_scale if reduced else 1.0)

        if not was_grounded:
            state.double_jumped = True
        if antigrav or pole:
            state.double_jumped = False

    # -- tile mods --------------------------------------------------------------

    def _check_tile_mod(self, state: MotionState) -> None:
        centre = self._centre_idx(state)
        if state.climbing and self._climb_surface_idx(state) is None:
            state.climbing = False
        was_water = state.in_water
        state.in_water = bool(centre is not None and self._flags(state, centre) & _IS_WET)

        slippery = False
        mud = False
        if self.grid.surface_count:
            row = math.floor((state.y + self.height) / TILE)
            for tx in _columns(state.x + 2.0, state.x + self.width - 2.0):
                idx = self._idx(tx, row)
                if idx is None or self.grid.fg_id[idx] <= 0:
                    continue
                if self.grid.slippery[idx]:
                    slippery = True
                if self.grid.mud[idx]:
                    mud = True
        if not self.profile.skates and (self.profile.slippery or slippery):
            state.sliding = True
        elif state.grounded:
            state.sliding = False
        state.mud = mud

        self._update_water_state(state, was_water)

    def _update_water_state(self, state: MotionState, was_water: bool) -> None:
        if state.in_water and not was_water:
            state.water_enter_ms = state.time_ms
            self._entered_water = True
            if self.profile.water_vehicle:
                state.water_float = True
        if not state.in_water:
            state.water_float = False
        elif state.time_ms - state.water_enter_ms > self.profile.water_float_duration_ms and not self.profile.water_float_perm:
            state.water_float = False

    def _apply_wind(self, state: MotionState, cap: float) -> None:
        if not self.grid.wind_count:
            return
        centre = self._centre_idx(state)
        if centre is None or self.grid.fg_id[centre] <= 0:
            return
        wind = self.grid.wind[centre]
        if wind == 0:
            return

        self._used_wind = True
        if wind < 0:  # flipped -> push left
            if state.vx > self.profile.wind_oppose_speed:
                state.vx = self.profile.wind_oppose_speed
            elif state.vx <= 0.0:
                state.vx = -cap
        else:
            if state.vx < -self.profile.wind_oppose_speed:
                state.vx = -self.profile.wind_oppose_speed
            elif state.vx >= 0.0:
                state.vx = cap

    def _gravity_well_pull(self, state: MotionState) -> tuple[float, float]:
        if not self.grid.well_count:
            return (0.0, 0.0)
        centre_x = state.x + self.width / 2.0
        centre_y = state.y + self.height / 2.0
        span = self.profile.gravity_well_range_tiles
        base_tx = int(centre_x // TILE)
        base_ty = int(centre_y // TILE)

        best_delta: tuple[float, float] | None = None
        best_dist2 = math.inf
        for tx in range(base_tx - span, base_tx + span + 1):
            for ty in range(base_ty - span, base_ty + span + 1):
                idx = self._idx(tx, ty)
                if idx is None or self.grid.fg_id[idx] <= 0 or self.grid.well_range[idx] <= 0:
                    continue
                if not (self._flags(state, idx) & _IS_ON):
                    continue

                reach = float(self.grid.well_range[idx])
                dx = tx * TILE + TILE / 2.0 - centre_x
                dy = ty * TILE + TILE / 2.0 - centre_y
                if reach <= abs(dx) or reach <= abs(dy):
                    continue

                dist2 = dx * dx + dy * dy
                if dist2 < best_dist2:
                    best_dist2, best_delta = dist2, (dx, dy)

        if best_delta is None:
            return (0.0, 0.0)

        dx, dy = best_delta
        dist = math.hypot(dx, dy)
        if dist == 0.0:
            return (0.0, 0.0)

        pull_x = dx / dist * self.profile.gravity_well_pull
        pull_y = dy / dist * self.profile.gravity_well_pull
        if state.vy > 0.0:
            pull_x *= self.profile.gravity_well_fall_speedup
        if pull_y < 0.0 and (abs(dx) > abs(dy) or abs(dx) > 16.0):
            pull_y = 0.0
        if pull_y < 0.0 and abs(pull_y) > abs(pull_x):
            pull_y *= self.profile.gravity_well_up_speedup

        self._used_well = True
        return (pull_x, pull_y)

    # -- probes -----------------------------------------------------------------

    def _touch(self, state: MotionState, step_x: float, step_y: float) -> None:
        if self._noclip:
            return

        if self.grid.hazard_count:
            ignore_spikes = self._ignore_spikes
            ignore_lava = self._ignore_lava
        else:
            # no deadly/damaging tile anywhere in the world: skip both probes
            ignore_spikes = ignore_lava = True
        w, h = self.width, self.height
        grid = self.grid
        fg_id = grid.fg_id
        bouncy = grid.bouncy

        left = state.x + step_x
        right = left + w
        ty0 = math.floor((state.y + _EPS) / TILE)
        ty1 = math.floor((state.y + h - _EPS) / TILE)
        stop = False
        for tx in range(math.floor((left + _EPS) / TILE), math.floor((right - _EPS) / TILE) + 1):
            if stop:
                break
            for ty in range(ty0, ty1 + 1):
                idx = self._idx(tx, ty)
                if idx is None or fg_id[idx] <= 0:
                    continue
                self._cache_touch(state, idx)
                if not ignore_spikes and self._is_deadly(state, idx):
                    self._kill(state)
                    continue

                hazard = DAMAGE_NONE if ignore_lava else self._damaging_event(state, idx)
                if hazard != DAMAGE_NONE:
                    self._damaging_x(state, hazard)
                    stop = True
                    break
                if bouncy[idx] == BOUNCE_RADIAL:
                    self._bounce(state, tx, ty)
                    stop = True
                    break
                if self._interaction_blocked(state, idx):
                    if state.damage_slip:
                        state.vx *= self.profile.damage_slip_wall_bounce
                    else:
                        state.vx = state.vx * self.profile.slide_wall_bounce if state.sliding else 0.0
                    if self._try_climb(state):
                        return

        probe = 1.0 if (step_y == 0.0 and state.grounded) else step_y
        top = state.y + probe
        bottom = top + h
        tx0 = math.floor((state.x + _EPS) / TILE)
        tx1 = math.floor((state.x + w - _EPS) / TILE)
        ty0 = math.floor((top + _EPS) / TILE)
        ty1 = math.floor((bottom - _EPS) / TILE)
        stop = False
        for tx in range(tx0, tx1 + 1):
            if stop:
                break
            for ty in range(ty0, ty1 + 1):
                idx = self._idx(tx, ty)
                if idx is None or fg_id[idx] <= 0:
                    continue
                self._cache_touch(state, idx)
                if not ignore_spikes and self._is_deadly(state, idx):
                    self._kill(state)
                    continue

                hazard = DAMAGE_NONE if ignore_lava else self._damaging_event(state, idx)
                if hazard != DAMAGE_NONE:
                    self._damaging_y(state, hazard)
                    stop = True
                    break
                if bouncy[idx] == BOUNCE_RADIAL:
                    self._bounce(state, tx, ty)
                    stop = True
                    break

                launch = self._landing_launch(state, tx, ty, idx)
                if launch is not None:
                    state.vy = launch
                    state.grounded = False
                    stop = True
                    break

    def _kill(self, state: MotionState) -> None:
        if state.killed:
            return

        state.killed = True
        self._killed = True

    def _apply_damage(self, state: MotionState, event: int) -> None:
        self._damage_hits += 1

    def _damaging_x(self, state: MotionState, event: int) -> None:
        self._apply_damage(state, event)
        state.vx = -state.vx
        if not state.damage_slip:
            if state.vx < 0.0:
                state.vx = min(-self.profile.damaging_knockback_speed, state.vx)
            else:
                state.vx = max(self.profile.damaging_knockback_speed, state.vx)

    def _damaging_y(self, state: MotionState, event: int) -> None:
        if self.profile.vertical_accel <= 0.0:
            state.vy = self.profile.damaging_launch_no_gravity_speed
        elif state.vy < 0.0:
            state.vy = -state.vy
        else:
            state.vy = self.profile.damaging_launch_speed

        state.grounded = False
        self._apply_damage(state, event)
        self._launched = True

        if state.vx == 0.0:
            state.vx = -1.0 if not state.facing_right else 1.0
        if state.vx < 0.0:
            state.vx = min(-self.profile.damaging_knockback_speed, state.vx)
        else:
            state.vx = max(self.profile.damaging_knockback_speed, state.vx)

        state.damage_slip = True

    def _bounce(self, state: MotionState, tx: int, ty: int) -> None:
        angle = math.atan2(
            state.y + self.height / 2 - (ty * TILE + TILE / 2),
            state.x + self.width / 2 - (tx * TILE + TILE / 2),
        )
        state.vx = math.cos(angle) * self.profile.bouncy_speed
        state.vy = math.sin(angle) * self.profile.bouncy_speed
        state.grounded = False
        state.jump_latch = False
        state.sliding = True
        self._bounced = True

    def _landing_launch(self, state: MotionState, tx: int, ty: int, idx: int) -> float | None:
        bouncy = self.grid.bouncy[idx]
        steam = self.grid.fg_id[idx] == STEAM_LAUNCHER and self._flags(state, idx) & _IS_ON
        if bouncy not in (BOUNCE_TRAMPOLINE, BOUNCE_TRAMPOLINE_MOMENTUM) and not steam:
            return None
        accel = self.profile.vertical_accel
        if state.in_water:
            accel *= self.profile.water_vertical_scale
        if accel <= 0.0 or state.vy < 0.0:
            return None
        if ty * TILE < state.y + self.height - _EPS:
            return None

        self._launched = True
        if bouncy == BOUNCE_TRAMPOLINE_MOMENTUM:
            return self.profile.trampoline_momentum_speed

        if steam:
            # the client clears IS_ON and sends the activate request; the request
            # has no motion effect, the flag clear does
            state.flag_overrides[idx] = self._flags(state, idx) & ~_IS_ON

        return self.profile.trampoline_speed

    def _try_climb(self, state: MotionState) -> bool:
        if state.climbing or state.vy < 0.0 or state.grounded:
            return False
        if self._climb_surface_idx(state) is None:
            return False

        state.climbing = True
        state.vx = state.vy = 0.0
        state.grounded = True
        self._climbed = True

        return True

    def _climb_surface_idx(self, state: MotionState) -> int | None:
        centre = self._centre_idx(state)
        if centre is None:
            return None
        fg = self.grid.fg_id[centre]
        if fg <= 0:
            return None
        if fg == CLIMBING_WALL:
            return centre if self.profile.climb_gear else None
        if fg == ADVENTURE_ROPE_PITON:
            cache = state.permissions.tile_cache if state.permissions is not None else ()
            return centre if ADVENTURE_ITEM_ROPE in cache else None

        return None

    # -- movement ---------------------------------------------------------------

    def _move(self, state: MotionState, delta: float, axis: int) -> None:
        total = delta + (state.frac_x if axis == 0 else state.frac_y)
        steps = math.floor(total + 0.5)
        if axis == 0:
            state.frac_x = total - steps
        else:
            state.frac_y = total - steps
        if steps == 0:
            return

        if self._swept_clear(state, steps, axis):
            # no tile in the swept volume can block: the per-pixel loop would
            # stop at nothing, so apply the integer displacement at once
            if axis == 0:
                state.x += steps
            else:
                state.y += steps
            return

        direction = 1 if steps > 0 else -1
        for _ in range(abs(steps)):
            if axis == 0:
                new_x = state.x + direction
                if self._blocked_x(state, new_x, state.y, direction):
                    return
                state.x = new_x
            else:
                new_y = state.y + direction
                if self._blocked_y(state, state.x, new_y, direction):
                    return
                state.y = new_y

    def _swept_clear(self, state: MotionState, steps: int, axis: int) -> bool:
        """True when the swept tile rect contains no non-empty tile.

        Conservative by construction: any non-empty tile (even a passable one)
        forces the exact per-pixel path, so the shortcut can never change a
        result -- it only skips iterations that cannot block.
        """
        grid = self.grid
        fg = grid.fg_id
        gw = self._gw
        gh = self._gh
        x = state.x
        y = state.y
        if axis == 0:
            target = x + steps
            lo = x if x < target else target
            hi = (target if target > x else x) + self.width
            tx0 = int(math.floor((lo + _EPS) / TILE))
            tx1 = int(math.floor((hi - _EPS) / TILE))
            ty0 = int(math.floor((y + _EPS) / TILE))
            ty1 = int(math.floor((y + self.height - _EPS) / TILE))
        else:
            target = y + steps
            lo = y if y < target else target
            hi = target if target > y else y
            ty0 = int(math.floor((lo + _EPS) / TILE))
            ty1 = int(math.floor((hi + self.height - _EPS) / TILE))
            tx0 = int(math.floor((x + _EPS) / TILE))
            tx1 = int(math.floor((x + self.width - _EPS) / TILE))

        if tx0 < 0:
            tx0 = 0
        if ty0 < 0:
            ty0 = 0
        if tx1 >= gw:
            tx1 = gw - 1
        if ty1 >= gh:
            ty1 = gh - 1
        for ty in range(ty0, ty1 + 1):
            base = ty * gw
            for tx in range(tx0, tx1 + 1):
                if fg[base + tx] > 0:
                    return False

        return True

    def _blocked_x(self, state: MotionState, x: float, y: float, direction: int) -> bool:
        edge = x + self.width if direction > 0 else x
        tx = math.floor((edge - direction * _EPS) / TILE)
        for ty in range(math.floor((y + _EPS) / TILE), math.floor((y + self.height - _EPS) / TILE) + 1):
            if not self._can_enter_x(state, tx, ty, direction):
                return True

        return False

    def _blocked_y(self, state: MotionState, x: float, y: float, direction: int) -> bool:
        edge = y + self.height if direction > 0 else y
        ty = math.floor((edge - direction * _EPS) / TILE)
        for tx in range(math.floor((x + _EPS) / TILE), math.floor((x + self.width - _EPS) / TILE) + 1):
            if not self._can_enter_y(state, tx, ty, y, direction):
                return True

        return False

    def _settle(self, state: MotionState) -> None:
        if state.climbing:
            state.grounded = True
            state.vy = 0.0
            return

        feet = state.y + self.height
        row = math.floor((feet + 0.5) / TILE)
        support = any(self._is_ground(state, tx, row) for tx in _columns(state.x + 2.0, state.x + self.width - 2.0))
        if support and abs(feet - row * TILE) <= 0.5 and state.vy >= 0.0:
            state.y = row * TILE - self.height
            state.vy = 0.0
            state.grounded = True
            state.double_jumped = False
            state.damage_slip = False
        else:
            if state.grounded:
                state.left_ground = True
            state.grounded = False

    # -- helpers ----------------------------------------------------------------

    def _centre_idx(self, state: MotionState) -> int | None:
        tx = math.floor((state.x + self.width / 2.0) / TILE)
        ty = math.floor((state.y + self.height / 2.0) / TILE)
        return self._idx(tx, ty)

    def _below_idx(self, state: MotionState) -> int | None:
        row = math.floor((state.y + self.height) / TILE)
        for tx in _columns(state.x + 2.0, state.x + self.width - 2.0):
            idx = self._idx(tx, row)
            if idx is not None and self.grid.fg_id[idx] > 0:
                return idx

        return None

    def _cache_touch(self, state: MotionState, idx: int) -> None:
        fg = self.grid.fg_id[idx]
        if fg <= 0 or state.permissions is None:
            return

        cache = state.permissions.tile_cache
        if fg in cache:
            cache.remove(fg)
        cache.append(fg)
        del cache[:-5]

    def _bbox(self, state: MotionState) -> tuple[int, int, int, int]:
        tx0 = math.floor(state.x / TILE)
        ty0 = math.floor(state.y / TILE)
        tx1 = math.floor((state.x + self.width - _EPS) / TILE)
        ty1 = math.floor((state.y + self.height - _EPS) / TILE)
        return (tx0, ty0, tx1, ty1)


def _make_backend(snapshot: WorldSnapshot, profile: CapabilityProfile, use_numba: bool | None) -> Any:
    """Build the compiled backend when numba is importable (and allowed).

    Set ``PATHFINDING_NO_NUMBA=1`` to force the pure-Python reference kernel
    (useful when debugging a divergence or in an environment without llvmlite).
    """
    if use_numba is False or os.environ.get("PATHFINDING_NO_NUMBA"):
        return None
    try:
        from gtools.core.growtopia.physics.pathfinding import numba_kernel
    except Exception:
        return None
    try:
        return numba_kernel.NumbaBackend(snapshot, profile)
    except Exception:
        return None


def _approach(value: float, target: float, step: float) -> float:
    return min(value + step, target) if value < target else max(value - step, target)


def _columns(left: float, right: float) -> range:
    return range(math.floor(left / TILE), math.floor(right / TILE) + 1)
