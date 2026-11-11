"""Numba-compiled backend for the fast kernel (the "super-optimised path").

``fastkernel.FastEvaluator`` is the readable reference: a tick-for-tick mirror of
``PlayerController._simulate`` that the differential fuzz suite proves against the
real controller.  It is, however, pure Python at ~0.1 M ticks/s.

This module is the *same* algorithm compiled with ``numba.njit`` over one flat
``int32`` grid matrix: no Python objects, no attribute lookups, no per-pixel
interpreter loop.  It is tick-identical to the reference -- the fuzz suite runs
both backends against the controller and against each other -- with one
deliberate simplification: permission-gated tiles are resolved at snapshot build
time (``_apply_gates``) instead of calling the controller's lock predicates per
query.  Only the adventure-key door stays dynamic, because it reads the avatar's
five-slot touched-tile cache.

Layout
------

* ``G``   -- ``(NFIELDS, width*height)`` int32 tile-fact matrix (``F_*`` rows);
* ``pf``  -- float64 profile scalars (``P_*`` slots);
* ``pb``  -- int64 profile flags/ids (``B_*`` slots);
* ``st``  -- float64 motion scalars (position/velocity/fractions/time);
* ``fl``  -- int64 motion flags (grounded/climbing/input/...);
* ``cache`` -- int32[5] touched-tile cache (client ``TileExistsAt`` slots);
* ``ov``  -- ``(idx, value)`` pairs recording the steam launcher's IS_ON clear.
"""

from __future__ import annotations

import math
import os
from typing import Any

import numpy as np
from numba import njit

from gtools.baked.items import (
    ADVENTURE_ITEM_KEY,
    ADVENTURE_ITEM_ROPE,
    ADVENTURE_ROPE_PITON,
    CLIMBING_WALL,
    HAY,
    HYPERTECH_ANTIGRAVITY_FIELD,
    LOCKED_ADVENTURE_DOOR,
    SLIPPERY_FLAG_POLE,
    SNOW_BLOCK,
    SNOWSHOES,
    STEAM_LAUNCHER,
)
from gtools.core.growtopia.items_dat import ItemInfoCollisionType
from gtools.core.growtopia.physics.pathfinding.snapshot import (
    BOUNCE_RADIAL,
    BOUNCE_TRAMPOLINE,
    BOUNCE_TRAMPOLINE_MOMENTUM,
    PermissionView,
)
from gtools.core.growtopia.physics.pathfinding.types import (
    STOP_LANDING,
    STOP_NONE,
    STOP_WALK,
    InputFrame,
    MotionState,
    Outcome,
)
from gtools.core.growtopia.world import TileFlags

# -- constants captured by the compiled kernel ---------------------------------

TILE = 32.0
EPS = 1e-6

_IS_ON = int(TileFlags.IS_ON)
_IS_WET = int(TileFlags.IS_WET)
_FLIPPED_X = int(TileFlags.FLIPPED_X)

_KIND_JUMP_THROUGH = int(ItemInfoCollisionType.JUMP_THROUGH)
_KIND_JUMP_DOWN = int(ItemInfoCollisionType.JUMP_DOWN)
_KIND_ONE_WAY = int(ItemInfoCollisionType.ONE_WAY)
_KIND_NONE = int(ItemInfoCollisionType.NONE)
_KIND_ADVENTURE = int(ItemInfoCollisionType.ADVENTURE)

# grid matrix rows
G_FG, G_FLAGS, G_COLL, G_BLOCKS, G_PLATFORM, G_JUMPDOWN, G_ONEWAY = range(7)
G_GATED, G_DEADLY, G_DEADLY_ON, G_DAMAGE, G_DAMAGE_ON = range(7, 12)
G_BOUNCY, G_WIND, G_WET, G_CLIMB, G_SLIPPERY, G_MUD, G_WELL = range(12, 19)
G_GATE_ON, G_GATE_OFF, G_GATE_DYN = 19, 20, 21
NFIELDS = 22

# profile scalar slots
P_DT, P_W, P_H = 0, 1, 2
P_VACC, P_JUMP_CUT, P_MAX_FALL = 3, 4, 5
P_WATER_VERT, P_SLOW_FALL_SCALE, P_ANTIGRAV_SCALE = 6, 7, 8
P_WF_ACCEL, P_WF_FALL_ACCEL, P_WF_MAX_FALL, P_WF_DURATION = 9, 10, 11, 12
P_MAXV, P_VWATER, P_HACC, P_MUD_SCALE, P_SLIDE_ACCEL = 13, 14, 15, 16, 17
P_WIND_OPPOSE = 18
P_WELL_PULL, P_WELL_FALL_UP, P_WELL_UP_UP = 19, 20, 21
P_JUMP, P_JUMP_REDUCED = 22, 23
P_SLIDE_WALL_BOUNCE, P_DMG_SLIP_WALL_BOUNCE = 24, 25
P_DMG_KNOCKBACK, P_DMG_LAUNCH, P_DMG_LAUNCH_NOG = 26, 27, 28
P_BOUNCY_SPEED, P_TRAMP_SPEED, P_TRAMP_MOMENTUM = 29, 30, 31
P_SIZE = 32

# profile / grid scalar slots
B_NOCLIP, B_IGNORE_SPIKES, B_IGNORE_LAVA = 0, 1, 2
B_ZOMBIE, B_SLOW_FALL, B_DOUBLE_JUMP = 3, 4, 5
B_FLOATIE, B_WATER_VEHICLE, B_WATER_FLOAT_PERM = 6, 7, 8
B_CLIMB_GEAR, B_SLIPPERY, B_SKATES = 9, 10, 11
B_SHOES, B_WELL_RANGE = 12, 13
B_GW, B_GH, B_WIND_COUNT, B_WELL_COUNT, B_HAZARD_COUNT, B_SURFACE_COUNT = 14, 15, 16, 17, 18, 19
B_SIZE = 24

# state scalar slots
S_X, S_Y, S_VX, S_VY, S_FX, S_FY, S_TMS, S_WEMS = range(8)
S_SIZE = 8

# state flag slots
FL_GROUNDED, FL_SLIDING, FL_IN_WATER, FL_WATER_FLOAT = 0, 1, 2, 3
FL_MUD, FL_LEFT_GROUND, FL_DAMAGE_SLIP, FL_CLIMBING = 4, 5, 6, 7
FL_DOUBLE_JUMPED, FL_KILLED, FL_LEFT, FL_RIGHT = 8, 9, 10, 11
FL_JUMP, FL_JUMP_LATCH, FL_FACING_RIGHT = 12, 13, 14
FL_SIZE = 16

# reason codes
REASON_TIMEOUT, REASON_KILLED, REASON_STOPPED = 0, 1, 2
REASON_CLIMB, REASON_WATER, REASON_LANDED = 3, 4, 5
_REASONS = ("timeout", "killed", "stopped", "climb", "water", "landed")


# -- compiled helpers ----------------------------------------------------------


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True, inline="always")
def _idx_nb(x, y, gw, gh):
    if 0 <= x < gw and 0 <= y < gh:
        return y * gw + x
    return -1


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True, inline="always")
def _flags_nb(G, ov_idx, ov_val, ov_len, idx):
    for i in range(ov_len[0]):
        if ov_idx[i] == idx:
            return ov_val[i]
    return G[G_FLAGS, idx]


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True, inline="always")
def _blocks_like_nb(G, idx, cache, cache_len, ov_idx, ov_val, ov_len):
    if G[G_GATED, idx]:
        if G[G_GATE_DYN, idx]:
            for i in range(cache_len):
                if cache[i] == ADVENTURE_ITEM_KEY:
                    return False
            return True
        if _flags_nb(G, ov_idx, ov_val, ov_len, idx) & _IS_ON:
            return bool(G[G_GATE_ON, idx])
        return bool(G[G_GATE_OFF, idx])
    return bool(G[G_BLOCKS, idx])


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True, inline="always")
def _can_enter_x_nb(G, idx, direction, cache, cache_len, ov_idx, ov_val, ov_len):
    if idx < 0 or G[G_FG, idx] <= 0:
        return True
    kind = G[G_COLL, idx]
    if kind == _KIND_JUMP_THROUGH or kind == _KIND_JUMP_DOWN:
        return True
    if kind == _KIND_ONE_WAY:
        flipped = bool(_flags_nb(G, ov_idx, ov_val, ov_len, idx) & _FLIPPED_X)
        return (flipped and direction < 0) or ((not flipped) and direction > 0)
    return not _blocks_like_nb(G, idx, cache, cache_len, ov_idx, ov_val, ov_len)


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True, inline="always")
def _can_enter_y_nb(G, idx, ty, y, direction, h, cache, cache_len, ov_idx, ov_val, ov_len):
    if idx < 0 or G[G_FG, idx] <= 0:
        return True
    kind = G[G_COLL, idx]
    if kind == _KIND_JUMP_THROUGH:
        if direction > 0 and math.floor(y + h) == ty * 32 + 1:
            return False
        return True
    if kind == _KIND_JUMP_DOWN:
        return direction > 0
    if kind == _KIND_ONE_WAY:
        return True
    return not _blocks_like_nb(G, idx, cache, cache_len, ov_idx, ov_val, ov_len)


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True, inline="always")
def _interaction_blocked_nb(G, idx, cache, cache_len, ov_idx, ov_val, ov_len):
    if G[G_FG, idx] <= 0:
        return False
    kind = G[G_COLL, idx]
    if kind == _KIND_JUMP_THROUGH or kind == _KIND_JUMP_DOWN or kind == _KIND_ONE_WAY:
        return False
    return _blocks_like_nb(G, idx, cache, cache_len, ov_idx, ov_val, ov_len)


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True, inline="always")
def _is_ground_nb(G, idx, cache, cache_len, ov_idx, ov_val, ov_len):
    if idx < 0 or G[G_FG, idx] <= 0:
        return False
    if G[G_COLL, idx] == _KIND_JUMP_DOWN:
        return False
    if G[G_GATED, idx]:
        return _blocks_like_nb(G, idx, cache, cache_len, ov_idx, ov_val, ov_len)
    return bool(G[G_BLOCKS, idx] or G[G_PLATFORM, idx])


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True, inline="always")
def _is_deadly_nb(G, idx, ov_idx, ov_val, ov_len):
    if G[G_DEADLY, idx]:
        return True
    if G[G_DEADLY_ON, idx] and (_flags_nb(G, ov_idx, ov_val, ov_len, idx) & _IS_ON):
        return True
    return False


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True, inline="always")
def _damaging_event_nb(G, idx, ov_idx, ov_val, ov_len):
    value = G[G_DAMAGE, idx]
    if value:
        return value
    if G[G_DAMAGE_ON, idx] and (_flags_nb(G, ov_idx, ov_val, ov_len, idx) & _IS_ON):
        return G[G_DAMAGE_ON, idx]
    return 0


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True, inline="always")
def _approach_nb(value, target, step):
    if value < target:
        return min(value + step, target)
    return max(value - step, target)


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True, inline="always")
def _centre_idx_nb(x, y, w, h, gw, gh):
    return _idx_nb(int(math.floor((x + w / 2.0) / TILE)), int(math.floor((y + h / 2.0) / TILE)), gw, gh)


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True, inline="always")
def _below_idx_nb(G, x, y, w, h, gw, gh):
    row = int(math.floor((y + h) / TILE))
    tx0 = int(math.floor((x + 2.0) / TILE))
    tx1 = int(math.floor((x + w - 2.0) / TILE))
    for tx in range(tx0, tx1 + 1):
        idx = _idx_nb(tx, row, gw, gh)
        if idx >= 0 and G[G_FG, idx] > 0:
            return idx
    return -1


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def _climb_surface_idx_nb(G, x, y, w, h, gw, gh, cache, cache_len, climb_gear):
    centre = _centre_idx_nb(x, y, w, h, gw, gh)
    if centre < 0:
        return -1
    value = G[G_FG, centre]
    if value <= 0:
        return -1
    if value == CLIMBING_WALL:
        return centre if climb_gear else -1
    if value == ADVENTURE_ROPE_PITON:
        for i in range(cache_len):
            if cache[i] == ADVENTURE_ITEM_ROPE:
                return centre
    return -1


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True, inline="always")
def _cache_touch_nb(G, idx, cache, cache_len):
    value = G[G_FG, idx]
    if value <= 0:
        return cache_len
    for i in range(cache_len):
        if cache[i] == value:
            for j in range(i, cache_len - 1):
                cache[j] = cache[j + 1]
            cache[cache_len - 1] = value
            return cache_len
    if cache_len < 5:
        cache[cache_len] = value
        return cache_len + 1
    for j in range(4):
        cache[j] = cache[j + 1]
    cache[4] = value
    return 5


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def _jump_nb(G, st, fl, pf, pb, cache, cache_len):
    below = _below_idx_nb(G, st[S_X], st[S_Y], pf[P_W], pf[P_H], pb[B_GW], pb[B_GH])
    centre = _centre_idx_nb(st[S_X], st[S_Y], pf[P_W], pf[P_H], pb[B_GW], pb[B_GH])
    below_fg = G[G_FG, below] if below >= 0 else 0
    centre_fg = G[G_FG, centre] if centre >= 0 else 0

    antigrav = below_fg == HYPERTECH_ANTIGRAVITY_FIELD or centre_fg == HYPERTECH_ANTIGRAVITY_FIELD
    pole = below_fg == SLIPPERY_FLAG_POLE or centre_fg == SLIPPERY_FLAG_POLE
    double_jump = pb[B_DOUBLE_JUMP] != 0 and fl[FL_DOUBLE_JUMPED] == 0
    can_swim = fl[FL_IN_WATER] != 0 and (st[S_VY] > 0.0 or fl[FL_WATER_FLOAT] != 0)
    can_jump = (
        fl[FL_GROUNDED] != 0
        or fl[FL_LEFT_GROUND] != 0
        or double_jump
        or pb[B_NOCLIP] != 0
        or antigrav
        or pole
        or can_swim
    )

    fl[FL_LEFT_GROUND] = 0
    if not can_jump:
        return

    fl[FL_CLIMBING] = 0
    was_grounded = fl[FL_GROUNDED] != 0
    snow_locked = below_fg == SNOW_BLOCK and pb[B_SHOES] != SNOWSHOES
    reduced = fl[FL_IN_WATER] != 0 or fl[FL_MUD] != 0 or pole or below_fg == HAY or snow_locked
    scale = pf[P_JUMP_REDUCED] if reduced else 1.0
    st[S_VY] = -pf[P_JUMP] * scale

    if not was_grounded:
        fl[FL_DOUBLE_JUMPED] = 1
    if antigrav or pole:
        fl[FL_DOUBLE_JUMPED] = 0


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def _apply_input_nb(G, st, fl, pf, pb, direction, jump, cache, cache_len):
    fl[FL_LEFT] = 1 if direction < 0 else 0
    fl[FL_RIGHT] = 1 if direction > 0 else 0
    if jump != (fl[FL_JUMP] != 0):
        fl[FL_JUMP_LATCH] = 1 if jump else 0
        if jump:
            _jump_nb(G, st, fl, pf, pb, cache, cache_len)
    fl[FL_JUMP] = 1 if jump else 0


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def _check_tile_mod_nb(G, st, fl, pf, pb, cache, cache_len, ov_idx, ov_val, ov_len):
    w, h = pf[P_W], pf[P_H]
    gw, gh = pb[B_GW], pb[B_GH]

    if fl[FL_CLIMBING] != 0:
        if _climb_surface_idx_nb(G, st[S_X], st[S_Y], w, h, gw, gh, cache, cache_len, pb[B_CLIMB_GEAR] != 0) < 0:
            fl[FL_CLIMBING] = 0

    centre = _centre_idx_nb(st[S_X], st[S_Y], w, h, gw, gh)
    was_water = fl[FL_IN_WATER] != 0
    wet = False
    if centre >= 0:
        wet = bool(_flags_nb(G, ov_idx, ov_val, ov_len, centre) & _IS_WET)
    fl[FL_IN_WATER] = 1 if wet else 0

    slippery = False
    mud = False
    if pb[B_SURFACE_COUNT] > 0:
        row = int(math.floor((st[S_Y] + h) / TILE))
        tx0 = int(math.floor((st[S_X] + 2.0) / TILE))
        tx1 = int(math.floor((st[S_X] + w - 2.0) / TILE))
        for tx in range(tx0, tx1 + 1):
            idx = _idx_nb(tx, row, gw, gh)
            if idx < 0 or G[G_FG, idx] <= 0:
                continue
            if G[G_SLIPPERY, idx]:
                slippery = True
            if G[G_MUD, idx]:
                mud = True

    if pb[B_SKATES] == 0 and (pb[B_SLIPPERY] != 0 or slippery):
        fl[FL_SLIDING] = 1
    elif fl[FL_GROUNDED] != 0:
        fl[FL_SLIDING] = 0
    fl[FL_MUD] = 1 if mud else 0

    if fl[FL_IN_WATER] != 0 and not was_water:
        st[S_WEMS] = st[S_TMS]
        if pb[B_WATER_VEHICLE] != 0:
            fl[FL_WATER_FLOAT] = 1
    if fl[FL_IN_WATER] == 0:
        fl[FL_WATER_FLOAT] = 0
    elif st[S_TMS] - st[S_WEMS] > pf[P_WF_DURATION] and pb[B_WATER_FLOAT_PERM] == 0:
        fl[FL_WATER_FLOAT] = 0
    return cache_len


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def _apply_wind_nb(G, st, pf, pb, centre, cap, ov_idx, ov_val, ov_len):
    if pb[B_WIND_COUNT] == 0:
        return False
    if centre < 0 or G[G_FG, centre] <= 0:
        return False
    wind = G[G_WIND, centre]
    if wind == 0:
        return False
    if wind < 0:
        if st[S_VX] > pf[P_WIND_OPPOSE]:
            st[S_VX] = pf[P_WIND_OPPOSE]
        elif st[S_VX] <= 0.0:
            st[S_VX] = -cap
    else:
        if st[S_VX] < -pf[P_WIND_OPPOSE]:
            st[S_VX] = -pf[P_WIND_OPPOSE]
        elif st[S_VX] >= 0.0:
            st[S_VX] = cap
    return True


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def _gravity_well_pull_nb(G, st, pf, pb, pull, ov_idx, ov_val, ov_len):
    pull[0] = 0.0
    pull[1] = 0.0
    if pb[B_WELL_COUNT] == 0:
        return False

    w, h = pf[P_W], pf[P_H]
    gw, gh = pb[B_GW], pb[B_GH]
    centre_x = st[S_X] + w / 2.0
    centre_y = st[S_Y] + h / 2.0
    span = pb[B_WELL_RANGE]
    base_tx = int(centre_x // TILE)
    base_ty = int(centre_y // TILE)

    best_dx = 0.0
    best_dy = 0.0
    best_dist2 = math.inf
    found = False
    for tx in range(base_tx - span, base_tx + span + 1):
        for ty in range(base_ty - span, base_ty + span + 1):
            idx = _idx_nb(tx, ty, gw, gh)
            if idx < 0 or G[G_FG, idx] <= 0 or G[G_WELL, idx] <= 0:
                continue
            if not (_flags_nb(G, ov_idx, ov_val, ov_len, idx) & _IS_ON):
                continue
            reach = float(G[G_WELL, idx])
            dx = tx * TILE + TILE / 2.0 - centre_x
            dy = ty * TILE + TILE / 2.0 - centre_y
            if reach <= abs(dx) or reach <= abs(dy):
                continue
            dist2 = dx * dx + dy * dy
            if dist2 < best_dist2:
                best_dist2 = dist2
                best_dx = dx
                best_dy = dy
                found = True

    if not found:
        return False

    dist = math.sqrt(best_dx * best_dx + best_dy * best_dy)
    if dist == 0.0:
        return False
    pull_x = best_dx / dist * pf[P_WELL_PULL]
    pull_y = best_dy / dist * pf[P_WELL_PULL]
    if st[S_VY] > 0.0:
        pull_x *= pf[P_WELL_FALL_UP]
    if pull_y < 0.0 and (abs(best_dx) > abs(best_dy) or abs(best_dx) > 16.0):
        pull_y = 0.0
    if pull_y < 0.0 and abs(pull_y) > abs(pull_x):
        pull_y *= pf[P_WELL_UP_UP]

    pull[0] = pull_x
    pull[1] = pull_y
    return True


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def _bounce_nb(G, st, fl, pf, tx, ty):
    angle = math.atan2(
        st[S_Y] + pf[P_H] / 2.0 - (ty * TILE + TILE / 2.0),
        st[S_X] + pf[P_W] / 2.0 - (tx * TILE + TILE / 2.0),
    )
    st[S_VX] = math.cos(angle) * pf[P_BOUNCY_SPEED]
    st[S_VY] = math.sin(angle) * pf[P_BOUNCY_SPEED]
    fl[FL_GROUNDED] = 0
    fl[FL_JUMP_LATCH] = 0
    fl[FL_SLIDING] = 1


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def _landing_launch_nb(G, st, fl, pf, tx, ty, idx, ov_idx, ov_val, ov_len):
    bouncy = G[G_BOUNCY, idx]
    steam = G[G_FG, idx] == STEAM_LAUNCHER and (_flags_nb(G, ov_idx, ov_val, ov_len, idx) & _IS_ON)
    if bouncy != BOUNCE_TRAMPOLINE and bouncy != BOUNCE_TRAMPOLINE_MOMENTUM and not steam:
        return math.nan
    accel = pf[P_VACC]
    if fl[FL_IN_WATER] != 0:
        accel *= pf[P_WATER_VERT]
    if accel <= 0.0 or st[S_VY] < 0.0:
        return math.nan
    if ty * TILE < st[S_Y] + pf[P_H] - EPS:
        return math.nan

    if steam:
        value = _flags_nb(G, ov_idx, ov_val, ov_len, idx) & ~_IS_ON
        placed = False
        for i in range(ov_len[0]):
            if ov_idx[i] == idx:
                ov_val[i] = value
                placed = True
        if not placed and ov_len[0] < 16:
            ov_idx[ov_len[0]] = idx
            ov_val[ov_len[0]] = value
            ov_len[0] += 1

    if bouncy == BOUNCE_TRAMPOLINE_MOMENTUM:
        return pf[P_TRAMP_MOMENTUM]
    return pf[P_TRAMP_SPEED]


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def _try_climb_nb(G, st, fl, pf, pb, cache, cache_len):
    if fl[FL_CLIMBING] != 0 or st[S_VY] < 0.0 or fl[FL_GROUNDED] != 0:
        return False
    if _climb_surface_idx_nb(
        G, st[S_X], st[S_Y], pf[P_W], pf[P_H], pb[B_GW], pb[B_GH], cache, cache_len, pb[B_CLIMB_GEAR] != 0
    ) < 0:
        return False
    fl[FL_CLIMBING] = 1
    st[S_VX] = 0.0
    st[S_VY] = 0.0
    fl[FL_GROUNDED] = 1
    return True


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def _damage_x_nb(st, fl, pf):
    st[S_VX] = -st[S_VX]
    if fl[FL_DAMAGE_SLIP] == 0:
        if st[S_VX] < 0.0:
            st[S_VX] = min(-pf[P_DMG_KNOCKBACK], st[S_VX])
        else:
            st[S_VX] = max(pf[P_DMG_KNOCKBACK], st[S_VX])


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def _damage_y_nb(st, fl, pf):
    if pf[P_VACC] <= 0.0:
        st[S_VY] = pf[P_DMG_LAUNCH_NOG]
    elif st[S_VY] < 0.0:
        st[S_VY] = -st[S_VY]
    else:
        st[S_VY] = pf[P_DMG_LAUNCH]
    fl[FL_GROUNDED] = 0
    if st[S_VX] == 0.0:
        st[S_VX] = 1.0 if fl[FL_FACING_RIGHT] != 0 else -1.0
    if st[S_VX] < 0.0:
        st[S_VX] = min(-pf[P_DMG_KNOCKBACK], st[S_VX])
    else:
        st[S_VX] = max(pf[P_DMG_KNOCKBACK], st[S_VX])
    fl[FL_DAMAGE_SLIP] = 1


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def _touch_nb(G, st, fl, pf, pb, cache, cache_len, ov_idx, ov_val, ov_len, step_x, step_y, state):
    w, h = pf[P_W], pf[P_H]
    gw, gh = pb[B_GW], pb[B_GH]
    if pb[B_NOCLIP] != 0:
        return cache_len

    if pb[B_HAZARD_COUNT] > 0:
        ignore_spikes = pb[B_IGNORE_SPIKES] != 0
        ignore_lava = pb[B_IGNORE_LAVA] != 0
    else:
        ignore_spikes = True
        ignore_lava = True

    left = st[S_X] + step_x
    right = left + w
    ty0 = int(math.floor((st[S_Y] + EPS) / TILE))
    ty1 = int(math.floor((st[S_Y] + h - EPS) / TILE))
    tx_start = int(math.floor((left + EPS) / TILE))
    tx_end = int(math.floor((right - EPS) / TILE))
    stop = False
    for tx in range(tx_start, tx_end + 1):
        if stop:
            break
        for ty in range(ty0, ty1 + 1):
            idx = _idx_nb(tx, ty, gw, gh)
            if idx < 0 or G[G_FG, idx] <= 0:
                continue
            cache_len = _cache_touch_nb(G, idx, cache, cache_len)
            if not ignore_spikes and _is_deadly_nb(G, idx, ov_idx, ov_val, ov_len):
                if fl[FL_KILLED] == 0:
                    fl[FL_KILLED] = 1
                continue

            hazard = 0 if ignore_lava else _damaging_event_nb(G, idx, ov_idx, ov_val, ov_len)
            if hazard != 0:
                _damage_x_nb(st, fl, pf)
                state[0] += 1
                stop = True
                break
            if G[G_BOUNCY, idx] == BOUNCE_RADIAL:
                _bounce_nb(G, st, fl, pf, tx, ty)
                state[1] = 1
                stop = True
                break
            if _interaction_blocked_nb(G, idx, cache, cache_len, ov_idx, ov_val, ov_len):
                if fl[FL_DAMAGE_SLIP] != 0:
                    st[S_VX] *= pf[P_DMG_SLIP_WALL_BOUNCE]
                elif fl[FL_SLIDING] != 0:
                    st[S_VX] = st[S_VX] * pf[P_SLIDE_WALL_BOUNCE]
                else:
                    st[S_VX] = 0.0
                if _try_climb_nb(G, st, fl, pf, pb, cache, cache_len):
                    return cache_len

    probe = 1.0 if (step_y == 0.0 and fl[FL_GROUNDED] != 0) else step_y
    top = st[S_Y] + probe
    bottom = top + h
    tx0 = int(math.floor((st[S_X] + EPS) / TILE))
    tx1 = int(math.floor((st[S_X] + w - EPS) / TILE))
    ty0 = int(math.floor((top + EPS) / TILE))
    ty1 = int(math.floor((bottom - EPS) / TILE))
    stop = False
    for tx in range(tx0, tx1 + 1):
        if stop:
            break
        for ty in range(ty0, ty1 + 1):
            idx = _idx_nb(tx, ty, gw, gh)
            if idx < 0 or G[G_FG, idx] <= 0:
                continue
            cache_len = _cache_touch_nb(G, idx, cache, cache_len)
            if not ignore_spikes and _is_deadly_nb(G, idx, ov_idx, ov_val, ov_len):
                if fl[FL_KILLED] == 0:
                    fl[FL_KILLED] = 1
                continue

            hazard = 0 if ignore_lava else _damaging_event_nb(G, idx, ov_idx, ov_val, ov_len)
            if hazard != 0:
                _damage_y_nb(st, fl, pf)
                state[0] += 1
                state[2] = 1
                stop = True
                break
            if G[G_BOUNCY, idx] == BOUNCE_RADIAL:
                _bounce_nb(G, st, fl, pf, tx, ty)
                state[1] = 1
                stop = True
                break

            launch = _landing_launch_nb(G, st, fl, pf, tx, ty, idx, ov_idx, ov_val, ov_len)
            if not math.isnan(launch):
                st[S_VY] = launch
                fl[FL_GROUNDED] = 0
                state[2] = 1
                stop = True
                break

    return cache_len


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def _move_nb(G, st, fl, pf, pb, cache, cache_len, ov_idx, ov_val, ov_len, delta, axis):
    w, h = pf[P_W], pf[P_H]
    gw, gh = pb[B_GW], pb[B_GH]
    if axis == 0:
        total = delta + st[S_FX]
    else:
        total = delta + st[S_FY]
    steps = int(math.floor(total + 0.5))
    if axis == 0:
        st[S_FX] = total - steps
    else:
        st[S_FY] = total - steps

    direction = 1 if steps > 0 else -1
    for _ in range(abs(steps)):
        if axis == 0:
            new_x = st[S_X] + direction
            edge = new_x + w if direction > 0 else new_x
            tx = int(math.floor((edge - direction * EPS) / TILE))
            rows0 = int(math.floor((st[S_Y] + EPS) / TILE))
            rows1 = int(math.floor((st[S_Y] + h - EPS) / TILE))
            blocked = False
            for ty in range(rows0, rows1 + 1):
                if not _can_enter_x_nb(G, _idx_nb(tx, ty, gw, gh), direction, cache, cache_len, ov_idx, ov_val, ov_len):
                    blocked = True
            if blocked:
                return
            st[S_X] = new_x
        else:
            new_y = st[S_Y] + direction
            edge = new_y + h if direction > 0 else new_y
            ty = int(math.floor((edge - direction * EPS) / TILE))
            cols0 = int(math.floor((st[S_X] + EPS) / TILE))
            cols1 = int(math.floor((st[S_X] + w - EPS) / TILE))
            blocked = False
            for tx in range(cols0, cols1 + 1):
                if not _can_enter_y_nb(G, _idx_nb(tx, ty, gw, gh), ty, new_y, direction, h,
                                       cache, cache_len, ov_idx, ov_val, ov_len):
                    blocked = True
            if blocked:
                return
            st[S_Y] = new_y


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def _settle_nb(G, st, fl, pf, pb, cache, cache_len, ov_idx, ov_val, ov_len):
    w, h = pf[P_W], pf[P_H]
    gw, gh = pb[B_GW], pb[B_GH]
    if fl[FL_CLIMBING] != 0:
        fl[FL_GROUNDED] = 1
        st[S_VY] = 0.0
        return

    feet = st[S_Y] + h
    row = int(math.floor((feet + 0.5) / TILE))
    support = False
    tx0 = int(math.floor((st[S_X] + 2.0) / TILE))
    tx1 = int(math.floor((st[S_X] + w - 2.0) / TILE))
    for tx in range(tx0, tx1 + 1):
        if _is_ground_nb(G, _idx_nb(tx, row, gw, gh), cache, cache_len, ov_idx, ov_val, ov_len):
            support = True
    if support and abs(feet - row * TILE) <= 0.5 and st[S_VY] >= 0.0:
        st[S_Y] = row * TILE - h
        st[S_VY] = 0.0
        fl[FL_GROUNDED] = 1
        fl[FL_DOUBLE_JUMPED] = 0
        fl[FL_DAMAGE_SLIP] = 0
    else:
        if fl[FL_GROUNDED] != 0:
            fl[FL_LEFT_GROUND] = 1
        fl[FL_GROUNDED] = 0


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def _simulate_tick_nb(G, st, fl, pf, pb, cache, cache_len, ov_idx, ov_val, ov_len, event, pull):
    """One tick; returns ``(cache_len, used_wind, used_well)``."""
    if fl[FL_KILLED] != 0:
        return cache_len, False, False

    dt = pf[P_DT]
    gw, gh = pb[B_GW], pb[B_GH]
    w, h = pf[P_W], pf[P_H]

    cache_len = _check_tile_mod_nb(G, st, fl, pf, pb, cache, cache_len, ov_idx, ov_val, ov_len)
    centre = _centre_idx_nb(st[S_X], st[S_Y], w, h, gw, gh)

    if fl[FL_GROUNDED] != 0:
        st[S_VY] = min(st[S_VY], 0.0)
    else:
        accel = pf[P_VACC]
        max_fall = pf[P_MAX_FALL]
        if accel > 0.0:
            if st[S_VY] < 0.0 and fl[FL_JUMP_LATCH] == 0:
                accel += pf[P_JUMP_CUT]
            elif fl[FL_DAMAGE_SLIP] != 0:
                accel += pf[P_JUMP_CUT] * 0.85
            if st[S_VY] > 0.0 and fl[FL_JUMP_LATCH] != 0 and fl[FL_IN_WATER] == 0 and pb[B_ZOMBIE] == 0:
                if pb[B_SLOW_FALL] != 0:
                    accel *= pf[P_SLOW_FALL_SCALE]
            if centre >= 0 and G[G_FG, centre] == HYPERTECH_ANTIGRAVITY_FIELD:
                accel *= pf[P_ANTIGRAV_SCALE]
        if fl[FL_IN_WATER] != 0:
            accel *= pf[P_WATER_VERT]
            max_fall = pf[P_MAX_FALL] * pf[P_WATER_VERT]
            if fl[FL_WATER_FLOAT] != 0:
                accel = 0.0
                max_fall = 0.0
            if pb[B_FLOATIE] != 0:
                accel = pf[P_WF_ACCEL]
                if st[S_VY] > 0.0:
                    accel = pf[P_WF_FALL_ACCEL]
                    st[S_VY] = min(st[S_VY], pf[P_WF_MAX_FALL])
        elif centre >= 0 and G[G_FG, centre] == SLIPPERY_FLAG_POLE:
            accel *= pf[P_WATER_VERT]
            max_fall = pf[P_MAX_FALL] * pf[P_WATER_VERT]
        st[S_VY] = min(st[S_VY] + dt * accel, max_fall)
        if accel < 0.0:
            st[S_VY] = max(st[S_VY], -max_fall)

    direction = (1 if fl[FL_RIGHT] != 0 else 0) - (1 if fl[FL_LEFT] != 0 else 0)
    if direction != 0:
        fl[FL_FACING_RIGHT] = 1 if direction > 0 else 0
    elif st[S_VX] != 0.0:
        fl[FL_FACING_RIGHT] = 1 if st[S_VX] > 0.0 else 0

    if fl[FL_IN_WATER] != 0:
        cap = pf[P_VWATER]
    else:
        cap = pf[P_MAXV]
    if fl[FL_MUD] != 0:
        cap *= pf[P_MUD_SCALE]
    step_v = pf[P_HACC] * dt
    if fl[FL_SLIDING] != 0 and st[S_VY] <= 0.0:
        step_v *= pf[P_SLIDE_ACCEL]
    if fl[FL_DAMAGE_SLIP] != 0:
        step_v *= pf[P_SLIDE_ACCEL]
    if fl[FL_SLIDING] != 0 or fl[FL_DAMAGE_SLIP] != 0:
        if direction > 0 and st[S_VX] < cap:
            st[S_VX] = min(st[S_VX] + step_v, cap)
        elif direction < 0 and st[S_VX] > -cap:
            st[S_VX] = max(st[S_VX] - step_v, -cap)
    else:
        st[S_VX] = _approach_nb(st[S_VX], direction * cap, step_v)

    used_wind = _apply_wind_nb(G, st, pf, pb, centre, cap, ov_idx, ov_val, ov_len)

    used_well = _gravity_well_pull_nb(G, st, pf, pb, pull, ov_idx, ov_val, ov_len)
    step_x = max(-TILE, min(TILE, (st[S_VX] + pull[0]) * dt))
    step_y = max(-TILE, min(TILE, (st[S_VY] + pull[1]) * dt))
    cache_len = _touch_nb(G, st, fl, pf, pb, cache, cache_len, ov_idx, ov_val, ov_len, step_x, step_y, event)
    _move_nb(G, st, fl, pf, pb, cache, cache_len, ov_idx, ov_val, ov_len, (st[S_VX] + pull[0]) * dt, 0)
    _move_nb(G, st, fl, pf, pb, cache, cache_len, ov_idx, ov_val, ov_len, (st[S_VY] + pull[1]) * dt, 1)
    _settle_nb(G, st, fl, pf, pb, cache, cache_len, ov_idx, ov_val, ov_len)

    st[S_X] = max(0.0, min(gw * TILE - w, st[S_X]))
    st[S_Y] = max(0.0, min(gh * TILE - h, st[S_Y]))
    return cache_len, used_wind, used_well


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def simulate_nb(
    G,
    pf,
    pb,
    st,
    fl,
    cache,
    cache_len,
    ov_idx,
    ov_val,
    ov_len,
    f_dir,
    f_jump,
    f_cnt,
    nframes,
    max_ticks,
    stop_kind,
    stop_after,
    trace,
):
    w, h = pf[P_W], pf[P_H]
    gw, gh = pb[B_GW], pb[B_GH]

    ticks = 0
    damage_hits = 0
    bounced = False
    launched = False
    climbed = False
    entered_water = False
    used_wind = False
    used_well = False
    trace_len = 0

    min_tx = int(math.floor(st[S_X] / TILE))
    min_ty = int(math.floor(st[S_Y] / TILE))
    max_tx = int(math.floor((st[S_X] + w - EPS) / TILE))
    max_ty = int(math.floor((st[S_Y] + h - EPS) / TILE))
    killed_at_start = fl[FL_KILLED] != 0
    reason = REASON_TIMEOUT

    event = np.zeros(3)
    pull = np.zeros(2)
    previous_x = 0.0
    grounded_ticks = 0

    for fi in range(nframes):
        direction = f_dir[fi]
        jump = f_jump[fi] != 0
        count = f_cnt[fi]
        broke = False
        for _ in range(max(0, count)):
            if fl[FL_KILLED] != 0:
                reason = REASON_KILLED
                broke = True
                break

            st[S_TMS] += pf[P_DT] * 1000.0
            before_climb = fl[FL_CLIMBING] != 0
            before_water = fl[FL_IN_WATER] != 0
            _apply_input_nb(G, st, fl, pf, pb, direction, jump, cache, cache_len)

            event[0] = 0.0
            event[1] = 0.0
            event[2] = 0.0
            cache_len, wind_hit, well_hit = _simulate_tick_nb(
                G, st, fl, pf, pb, cache, cache_len, ov_idx, ov_val, ov_len, event, pull
            )
            damage_hits += int(event[0])
            if event[1] != 0.0:
                bounced = True
            if event[2] != 0.0:
                launched = True
            if wind_hit:
                used_wind = True
            if well_hit:
                used_well = True
            if not before_climb and fl[FL_CLIMBING] != 0:
                climbed = True
            if not before_water and fl[FL_IN_WATER] != 0:
                entered_water = True
            ticks += 1

            tx0 = int(math.floor(st[S_X] / TILE))
            ty0 = int(math.floor(st[S_Y] / TILE))
            tx1 = int(math.floor((st[S_X] + w - EPS) / TILE))
            ty1 = int(math.floor((st[S_Y] + h - EPS) / TILE))
            if tx0 < min_tx:
                min_tx = tx0
            if ty0 < min_ty:
                min_ty = ty0
            if tx1 > max_tx:
                max_tx = tx1
            if ty1 > max_ty:
                max_ty = ty1

            if trace_len < trace.shape[0]:
                trace[trace_len, 0] = st[S_X]
                trace[trace_len, 1] = st[S_Y]
                trace[trace_len, 2] = 1.0 if fl[FL_GROUNDED] != 0 else 0.0
                trace_len += 1

            stopped = False
            if stop_kind == STOP_WALK:
                if fl[FL_KILLED] != 0 or fl[FL_CLIMBING] != 0 or fl[FL_IN_WATER] != 0:
                    stopped = True
                elif ticks <= 1:
                    previous_x = st[S_X]
                else:
                    stuck = abs(st[S_X] - previous_x) < 0.5
                    previous_x = st[S_X]
                    stopped = (fl[FL_GROUNDED] == 0) or stuck
            elif stop_kind == STOP_LANDING:
                if fl[FL_KILLED] != 0 or fl[FL_CLIMBING] != 0 or fl[FL_IN_WATER] != 0:
                    stopped = True
                elif ticks <= stop_after:
                    grounded_ticks = 0
                elif fl[FL_GROUNDED] != 0:
                    grounded_ticks += 1
                    stopped = grounded_ticks >= 2
                else:
                    grounded_ticks = 0

            if stopped:
                reason = REASON_STOPPED
                broke = True
                break
            if max_ticks >= 0 and ticks >= max_ticks:
                reason = REASON_TIMEOUT
                broke = True
                break
        if broke:
            break

    if fl[FL_KILLED] == 0:
        if fl[FL_CLIMBING] != 0:
            reason = REASON_CLIMB
        elif fl[FL_IN_WATER] != 0:
            reason = REASON_WATER
        elif fl[FL_GROUNDED] != 0:
            reason = REASON_LANDED
    if fl[FL_KILLED] != 0 and not killed_at_start:
        reason = REASON_KILLED

    return (
        ticks,
        reason,
        damage_hits,
        bounced,
        launched,
        climbed,
        entered_water,
        used_wind,
        used_well,
        min_tx,
        min_ty,
        max_tx,
        max_ty,
        trace_len,
        cache_len,
    )


@njit(cache=True, fastmath=False, boundscheck=False, nogil=True)
def simulate_tick_nb(G, pf, pb, st, fl, cache, cache_len, ov_idx, ov_val, ov_len, direction, jump):
    event = np.zeros(3)
    pull = np.zeros(2)
    st[S_TMS] += pf[P_DT] * 1000.0
    _apply_input_nb(G, st, fl, pf, pb, direction, jump, cache, cache_len)
    cache_len, _, _ = _simulate_tick_nb(G, st, fl, pf, pb, cache, cache_len, ov_idx, ov_val, ov_len, event, pull)
    return cache_len, int(event[0]), event[1] != 0.0, event[2] != 0.0


# -- Python side: array building, gating, state bridging ------------------------


class _MatrixCache:
    """One-entry cache so a re-plan reuses the compiled matrices."""

    key: tuple | None = None
    holder: Any = None
    matrix: np.ndarray | None = None
    gate_key: tuple | None = None


_CACHE = _MatrixCache()


def _grid_matrix(snapshot: Any) -> np.ndarray:
    key = (id(snapshot), snapshot.epoch)
    if _CACHE.key == key and _CACHE.matrix is not None:
        return _CACHE.matrix

    grid = snapshot.grid
    n = grid.width * grid.height
    G = np.zeros((NFIELDS, n), dtype=np.int32)
    G[G_FG] = grid.fg_id
    G[G_FLAGS] = grid.flags
    G[G_COLL] = grid.collision
    G[G_BLOCKS] = grid.blocks
    G[G_PLATFORM] = grid.platform
    G[G_JUMPDOWN] = grid.jump_down
    G[G_ONEWAY] = grid.one_way
    G[G_GATED] = grid.gated
    G[G_DEADLY] = grid.deadly
    G[G_DEADLY_ON] = grid.deadly_if_on
    G[G_DAMAGE] = grid.damage
    G[G_DAMAGE_ON] = grid.damage_if_on
    G[G_BOUNCY] = grid.bouncy
    G[G_WIND] = grid.wind
    G[G_WET] = grid.wet
    G[G_CLIMB] = grid.climbable
    G[G_SLIPPERY] = grid.slippery
    G[G_MUD] = grid.mud
    G[G_WELL] = grid.well_range

    _CACHE.key = key
    _CACHE.holder = snapshot  # keep alive so ``id()`` is never recycled
    _CACHE.matrix = G
    _CACHE.gate_key = None
    return G


def _apply_gates(G: np.ndarray, snapshot: Any, profile: Any) -> None:
    """Resolve permission-gated tiles once per (snapshot, profile).

    The controller's own predicates do the work; only the two ``IS_ON`` states are
    pre-evaluated, and the adventure-key door stays dynamic because it reads the
    avatar's touched-tile cache.
    """
    fingerprint = profile.fingerprint()
    if _CACHE.gate_key == fingerprint:
        return

    grid = snapshot.grid
    n = grid.width * grid.height
    G[G_GATE_ON, :] = 0
    G[G_GATE_OFF, :] = 0
    G[G_GATE_DYN, :] = 0

    view = PermissionView(snapshot.probe_world(), profile.permissions)
    for idx in range(n):
        if not grid.gated[idx]:
            continue
        kind = ItemInfoCollisionType(int(grid.collision[idx]))
        if kind == ItemInfoCollisionType.ADVENTURE and int(grid.fg_id[idx]) == LOCKED_ADVENTURE_DOOR:
            G[G_GATE_DYN, idx] = 1
            continue

        tile = snapshot.fresh_tile(idx)
        tile.flags = TileFlags(int(tile.flags) | _IS_ON)
        G[G_GATE_ON, idx] = 1 if view._blocks_like_client(tile, kind) else 0
        tile.flags = TileFlags(int(tile.flags) & ~_IS_ON)
        G[G_GATE_OFF, idx] = 1 if view._blocks_like_client(tile, kind) else 0

    _CACHE.gate_key = fingerprint


def _static_permissions_match(state: MotionState, profile: Any) -> bool:
    perms = state.permissions
    if perms is None:
        return False
    ref = profile.permissions
    return (
        perms.user_id == ref.user_id
        and perms.guild_id == ref.guild_id
        and perms.guild_rank == ref.guild_rank
        and perms.team == ref.team
        and perms.has_team == ref.has_team
        and perms.friend == ref.friend
        and perms.protocol_version == ref.protocol_version
        and perms.adventure_flags == ref.adventure_flags
    )


def stop_descriptor(stop: Any) -> tuple[int, int] | None:
    """Map an ``ActionCatalog`` stop predicate to ``(kind, after)``."""
    if stop is None:
        return (STOP_NONE, 0)
    return getattr(stop, "_nb_stop", None)


class NumbaBackend:
    """Compiled implementation of ``FastEvaluator.simulate``."""

    __slots__ = (
        "snapshot",
        "profile",
        "G",
        "pf",
        "pb",
        "_st",
        "_fl",
        "_cache",
        "_ov_idx",
        "_ov_val",
        "_ov_len",
    )

    def __init__(self, snapshot: Any, profile: Any) -> None:
        self.snapshot = snapshot
        self.profile = profile
        self.G = _grid_matrix(snapshot)
        _apply_gates(self.G, snapshot, profile)

        grid = snapshot.grid
        self.pf = np.array(
            [
                profile.dt,
                profile.width,
                profile.height,
                profile.vertical_accel,
                profile.jump_cut_accel,
                profile.max_fall,
                profile.water_vertical_scale,
                profile.slow_fall_accel_scale,
                profile.antigravity_accel_scale,
                profile.water_float_accel,
                profile.water_float_fall_accel,
                profile.water_float_max_fall,
                profile.water_float_duration_ms,
                profile.max_velocity,
                profile.velocity_in_water,
                profile.horizontal_accel,
                profile.mud_speed_scale,
                profile.slide_accel_scale,
                profile.wind_oppose_speed,
                profile.gravity_well_pull,
                profile.gravity_well_fall_speedup,
                profile.gravity_well_up_speedup,
                profile.jump_speed,
                profile.jump_reduced_scale,
                profile.slide_wall_bounce,
                profile.damage_slip_wall_bounce,
                profile.damaging_knockback_speed,
                profile.damaging_launch_speed,
                profile.damaging_launch_no_gravity_speed,
                profile.bouncy_speed,
                profile.trampoline_speed,
                profile.trampoline_momentum_speed,
            ],
            dtype=np.float64,
        )
        self.pb = np.array(
            [
                1 if profile.noclip else 0,
                1 if profile.ignore_spikes else 0,
                1 if profile.ignore_lava else 0,
                1 if profile.zombie else 0,
                1 if profile.slow_fall else 0,
                1 if profile.has_double_jump else 0,
                1 if profile.floatie else 0,
                1 if profile.water_vehicle else 0,
                1 if profile.water_float_perm else 0,
                1 if profile.climb_gear else 0,
                1 if profile.slippery else 0,
                1 if profile.skates else 0,
                int(profile.shoes),
                int(profile.gravity_well_range_tiles),
                int(grid.width),
                int(grid.height),
                int(grid.wind_count),
                int(grid.well_count),
                int(grid.hazard_count),
                int(grid.surface_count),
            ],
            dtype=np.int64,
        )
        self._st = np.zeros(S_SIZE, dtype=np.float64)
        self._fl = np.zeros(FL_SIZE, dtype=np.int64)
        self._cache = np.zeros(5, dtype=np.int32)
        self._ov_idx = np.zeros(16, dtype=np.int32)
        self._ov_val = np.zeros(16, dtype=np.int32)
        self._ov_len = np.zeros(1, dtype=np.int64)
        self._warm_up()

    def _warm_up(self) -> None:
        """Compile every kernel function once, *outside* any caller's budget.

        The first ``simulate`` of a fresh process pays numba's compile cost
        (~0.2-0.3 s, or a few ms from the on-disk cache).  Left lazy, that cost
        lands inside the planner's ``time_budget_ms`` and turns the first plan
        into a spurious ``BUDGET`` result, so it is paid here instead.
        """
        self._st[:] = 0.0
        self._fl[:] = 0
        self._ov_len[0] = 0
        simulate_nb(
            self.G,
            self.pf,
            self.pb,
            self._st,
            self._fl,
            self._cache,
            0,
            self._ov_idx,
            self._ov_val,
            self._ov_len,
            np.zeros(2, dtype=np.int32),
            np.ones(2, dtype=np.int32),
            np.ones(2, dtype=np.int32),
            2,
            -1,
            STOP_NONE,
            0,
            np.empty((0, 3), dtype=np.float64),
        )
        simulate_tick_nb(
            self.G,
            self.pf,
            self.pb,
            self._st,
            self._fl,
            self._cache,
            0,
            self._ov_idx,
            self._ov_val,
            self._ov_len,
            0,
            False,
        )

    # -- state bridging --------------------------------------------------------

    def can_run(self, state: MotionState, stop: Any) -> bool:
        return stop_descriptor(stop) is not None and _static_permissions_match(state, self.profile)

    def _encode_state(self, state: MotionState) -> tuple[int, int]:
        st = self._st
        fl = self._fl
        st[S_X] = state.x
        st[S_Y] = state.y
        st[S_VX] = state.vx
        st[S_VY] = state.vy
        st[S_FX] = state.frac_x
        st[S_FY] = state.frac_y
        st[S_TMS] = state.time_ms
        st[S_WEMS] = state.water_enter_ms
        fl[FL_GROUNDED] = 1 if state.grounded else 0
        fl[FL_SLIDING] = 1 if state.sliding else 0
        fl[FL_IN_WATER] = 1 if state.in_water else 0
        fl[FL_WATER_FLOAT] = 1 if state.water_float else 0
        fl[FL_MUD] = 1 if state.mud else 0
        fl[FL_LEFT_GROUND] = 1 if state.left_ground else 0
        fl[FL_DAMAGE_SLIP] = 1 if state.damage_slip else 0
        fl[FL_CLIMBING] = 1 if state.climbing else 0
        fl[FL_DOUBLE_JUMPED] = 1 if state.double_jumped else 0
        fl[FL_KILLED] = 1 if state.killed else 0
        fl[FL_LEFT] = 1 if state.left else 0
        fl[FL_RIGHT] = 1 if state.right else 0
        fl[FL_JUMP] = 1 if state.jump else 0
        fl[FL_JUMP_LATCH] = 1 if state.jump_latch else 0
        fl[FL_FACING_RIGHT] = 1 if state.facing_right else 0

        tile_cache = state.permissions.tile_cache if state.permissions is not None else []
        cache_len = min(5, len(tile_cache))
        for i in range(cache_len):
            self._cache[i] = int(tile_cache[i])

        overrides = state.flag_overrides or {}
        ov_len = min(16, len(overrides))
        for i, (idx, value) in enumerate(overrides.items()):
            if i >= 16:
                break
            self._ov_idx[i] = int(idx)
            self._ov_val[i] = int(value)
        self._ov_len[0] = ov_len
        return ov_len, cache_len

    def _decode_state(self, state: MotionState, cache_len: int) -> None:
        st = self._st
        fl = self._fl
        state.x = float(st[S_X])
        state.y = float(st[S_Y])
        state.vx = float(st[S_VX])
        state.vy = float(st[S_VY])
        state.frac_x = float(st[S_FX])
        state.frac_y = float(st[S_FY])
        state.time_ms = float(st[S_TMS])
        state.water_enter_ms = float(st[S_WEMS])
        state.grounded = bool(fl[FL_GROUNDED])
        state.sliding = bool(fl[FL_SLIDING])
        state.in_water = bool(fl[FL_IN_WATER])
        state.water_float = bool(fl[FL_WATER_FLOAT])
        state.mud = bool(fl[FL_MUD])
        state.left_ground = bool(fl[FL_LEFT_GROUND])
        state.damage_slip = bool(fl[FL_DAMAGE_SLIP])
        state.climbing = bool(fl[FL_CLIMBING])
        state.double_jumped = bool(fl[FL_DOUBLE_JUMPED])
        state.killed = bool(fl[FL_KILLED])
        state.left = bool(fl[FL_LEFT])
        state.right = bool(fl[FL_RIGHT])
        state.jump = bool(fl[FL_JUMP])
        state.jump_latch = bool(fl[FL_JUMP_LATCH])
        state.facing_right = bool(fl[FL_FACING_RIGHT])

        if state.permissions is not None:
            state.permissions.tile_cache[:] = [int(self._cache[i]) for i in range(cache_len)]

        if state.flag_overrides is None:
            state.flag_overrides = {}
        state.flag_overrides.clear()
        for i in range(int(self._ov_len[0])):
            state.flag_overrides[int(self._ov_idx[i])] = int(self._ov_val[i])

    # -- public ----------------------------------------------------------------

    def simulate(
        self,
        state: MotionState,
        frames: tuple[InputFrame, ...] | list[InputFrame],
        *,
        max_ticks: int | None = None,
        stop_when: Any = None,
        record_trace: bool = False,
    ) -> Outcome:
        kind, after = stop_descriptor(stop_when) or (STOP_NONE, 0)
        ov_len, cache_len = self._encode_state(state)

        nframes = len(frames)
        dirs = np.empty(nframes, dtype=np.int32)
        jumps = np.empty(nframes, dtype=np.int32)
        counts = np.empty(nframes, dtype=np.int32)
        total = 0
        for i, (direction, jump, count) in enumerate(frames):
            dirs[i] = int(direction)
            jumps[i] = 1 if jump else 0
            counts[i] = max(0, int(count))
            total += int(counts[i])
        if record_trace:
            trace = np.empty((total + 1, 3), dtype=np.float64)
        else:
            trace = np.empty((0, 3), dtype=np.float64)

        result = simulate_nb(
            self.G,
            self.pf,
            self.pb,
            self._st,
            self._fl,
            self._cache,
            cache_len,
            self._ov_idx,
            self._ov_val,
            self._ov_len,
            dirs,
            jumps,
            counts,
            nframes,
            -1 if max_ticks is None else int(max_ticks),
            int(kind),
            int(after),
            trace,
        )
        (
            ticks,
            reason_code,
            damage_hits,
            bounced,
            launched,
            climbed,
            entered_water,
            used_wind,
            used_well,
            min_tx,
            min_ty,
            max_tx,
            max_ty,
            trace_len,
            cache_len,
        ) = result

        self._decode_state(state, int(cache_len))
        trace_list = (
            [(float(trace[i, 0]), float(trace[i, 1]), bool(trace[i, 2])) for i in range(int(trace_len))]
            if record_trace
            else []
        )

        return Outcome(
            state=state,
            ticks=int(ticks),
            reason=_REASONS[int(reason_code)],
            damage_hits=int(damage_hits),
            bounced=bool(bounced),
            launched=bool(launched),
            climbed=bool(climbed),
            entered_water=bool(entered_water),
            used_wind=bool(used_wind),
            used_well=bool(used_well),
            bbox=(int(min_tx), int(min_ty), int(max_tx), int(max_ty)),
            tick_trace=trace_list,
        )

    def simulate_tick(self, state: MotionState, direction: int, jump: bool) -> None:
        ov_len, cache_len = self._encode_state(state)
        cache_len, _, _, _ = simulate_tick_nb(
            self.G,
            self.pf,
            self.pb,
            self._st,
            self._fl,
            self._cache,
            cache_len,
            self._ov_idx,
            self._ov_val,
            self._ov_len,
            int(direction),
            jump,
        )
        self._decode_state(state, int(cache_len))


def available() -> bool:
    try:
        import numba  # noqa: F401
    except Exception:
        return False
    return True
