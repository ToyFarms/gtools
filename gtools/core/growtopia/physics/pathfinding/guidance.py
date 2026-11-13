"""Topology-aware guidance for the segmented planner.

The planner's old heuristic was a horizontal/vertical *distance* bound.  On any
world whose route is not roughly a straight line (a switchback, a pit that has to
be walked around, a ceiling with a hole in it) that bound is a trap: every state
near the goal column looks "close", and the search spends its whole budget
wandering the wrong end of every corridor.

``GuidanceField`` replaces it with a cheap **tile-level distance-to-goal field**
computed by a reverse Dijkstra over an abstraction of the movement rules:

* horizontal moves between passable tiles;
* free fall through passable tiles that are not standable;
* *capped rise*: an avatar can climb at most ``rise_cap`` rows above the nearest
  tile it can stand on (the jump height; doubled with a double jump);
* water: free vertical and horizontal swimming through wet tiles;
* hazards: deadly tiles are walls; damaging tiles are walls in the *safe* model
  and priced in the *damage* model; tiles next to a hazard carry a small clearance
  cost so the guided route keeps its distance.

The abstraction ignores everything the real physics adds (arc shape, run-up,
bouncers, wind...).  That is deliberate: the field is only a *heuristic*.  It never
decides that something is impossible -- an unreachable cell simply falls back to a
large distance-based estimate -- and the exact segments produced by the kernel are
what the planner actually searches.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Any, Iterable

from gtools.core.growtopia.physics.controller import TILE

INF = math.inf

_IS_ON = 1 << 4  # replaced below with the real flag value


def _init_flag() -> int:
    from gtools.core.growtopia.world import TileFlags

    return int(TileFlags.IS_ON)


_IS_ON = _init_flag()


@dataclass(slots=True)
class Terrain:
    """Per-snapshot, per-hazard-model tile facts (independent of the goal)."""

    width: int
    height: int
    passable: bytearray
    standable: bytearray
    wet: bytearray
    air_height: list[int]  # rows above the nearest standable/wet tile in the column
    drift_ok: bytearray  # 1 = an airborne avatar can plausibly be here (near ground it left)
    exotic: bool  # the world has mechanics the abstraction ignores (bouncers, wind...)
    hazard: bytearray  # 1 = deadly, 2 = damaging (always filled, whatever the model)
    near: bytearray  # 1 = 8-neighbour of a hazard
    allow_damage: bool
    has_damage: bool
    rise_cap: int
    tick_h: float
    tick_water: float
    tick_fall: float
    tick_rise: float
    tick_swim_down: float
    tick_swim_up: float
    near_cost: float
    damage_cost: float

    def idx(self, x: int, y: int) -> int:
        return y * self.width + x

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height


def build_terrain(
    snapshot: Any,
    profile: Any,
    *,
    allow_damage: bool,
    blocks: Any = None,
    damage_cost: float = 60.0,
    near_cost: float = 4.0,
) -> Terrain:
    """Classify every tile for the guidance graph.

    ``blocks(idx)`` may override the snapshot's ``blocks`` column (used to resolve
    permission-gated tiles with the controller's own predicates).
    """
    grid = snapshot.grid
    w, h = int(grid.width), int(grid.height)
    n = w * h
    passable = bytearray(n)
    support = bytearray(n)
    wet = bytearray(n)
    hazard = bytearray(n)

    ignore_spikes = bool(profile.ignore_spikes)
    ignore_lava = bool(profile.ignore_lava)
    fg_id, flags = grid.fg_id, grid.flags
    for idx in range(n):
        if fg_id[idx] <= 0:
            passable[idx] = 1
            wet[idx] = 1 if grid.wet[idx] else 0
            continue

        on = bool(flags[idx] & _IS_ON)
        deadly = bool(grid.deadly[idx] or (grid.deadly_if_on[idx] and on)) and not ignore_spikes
        damaging = bool(grid.damage[idx] or (grid.damage_if_on[idx] and on)) and not ignore_lava
        if deadly:
            hazard[idx] = 1
        elif damaging:
            hazard[idx] = 2

        if grid.gated[idx] and blocks is not None:
            solid = bool(blocks(idx))
        else:
            solid = bool(grid.blocks[idx])
        plat = bool(grid.platform[idx])
        wet[idx] = 1 if grid.wet[idx] else 0
        passable[idx] = 0 if (solid or deadly) else 1
        if damaging and not allow_damage:
            passable[idx] = 0
        if (solid or plat) and not deadly and not (damaging and not allow_damage):
            support[idx] = 1

    standable = bytearray(n)
    for y in range(h - 1):
        base = y * w
        below = base + w
        for x in range(w):
            if passable[base + x] and support[below + x]:
                standable[base + x] = 1

    # rows above the nearest standable/wet tile in the column (INF-ish when none)
    big = 10_000
    air_height = [big] * n
    for x in range(w):
        previous = big
        for y in range(h - 1, -1, -1):
            idx = y * w + x
            if not passable[idx]:
                previous = big
                air_height[idx] = big
                continue
            if standable[idx] or wet[idx]:
                previous = 0
            else:
                previous = previous + 1 if previous < big else big
            air_height[idx] = previous

    # Airborne drift only exists near the ground the avatar left: a jump cannot cross
    # more than ~``reach`` empty tiles, so the middle of a wider gap is unreachable.
    # A cell can hold an airborne avatar when some standable tile within ``drift``
    # columns is no more than a jump height below it (or above it: a ledge it fell off).
    reach_tiles = profile.horizontal_jump_reach_px * (2.0 if profile.has_double_jump else 1.0) / TILE
    drift = max(2, int(reach_tiles / 2.0))
    top_row = [big] * w  # highest standable row per column
    for x in range(w):
        for y in range(h):
            if standable[y * w + x]:
                top_row[x] = y
                break
    window = [min(top_row[max(0, x - drift) : x + drift + 1]) for x in range(w)]
    rise_cap_cells = None
    drift_ok = bytearray(n)

    near = bytearray(n)
    for idx in range(n):
        if not hazard[idx]:
            continue
        y, x = divmod(idx, w)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    near[ny * w + nx] = 1

    dt = float(profile.dt)
    tick_h = TILE / max(profile.max_velocity * dt, 1e-9)
    tick_water = TILE / max(profile.velocity_in_water * dt, 1e-9)
    tick_fall = TILE / max(profile.max_fall * dt, 1e-9) + 0.5
    tick_rise = TILE / max(profile.jump_speed * dt, 1e-9) * 1.8
    water_fall = max(profile.max_fall * profile.water_vertical_scale * dt, 1e-9)
    tick_swim_down = TILE / water_fall
    tick_swim_up = TILE / max(profile.jump_speed * profile.jump_reduced_scale * dt * 0.7, 1e-9)

    height_px = profile.jump_height_px * (2.0 if profile.has_double_jump else 1.0)
    rise_cap = max(1, int(height_px / TILE + 1e-6)) if height_px > 0 else 1
    if profile.noclip:
        rise_cap = 10_000

    for y in range(h):
        base = y * w
        for x in range(w):
            if window[x] <= y + rise_cap:
                drift_ok[base + x] = 1

    exotic = bool(
        snapshot.grid.wind_count
        or snapshot.grid.well_count
        or any(snapshot.grid.bouncy)
        or any(snapshot.grid.climbable)
    )

    return Terrain(
        width=w,
        height=h,
        passable=passable,
        standable=standable,
        wet=wet,
        air_height=air_height,
        drift_ok=drift_ok,
        exotic=exotic,
        hazard=hazard,
        near=near,
        allow_damage=allow_damage,
        has_damage=hazard.count(2) > 0,
        rise_cap=rise_cap,
        tick_h=tick_h,
        tick_water=tick_water,
        tick_fall=tick_fall,
        tick_rise=tick_rise,
        tick_swim_down=tick_swim_down,
        tick_swim_up=tick_swim_up,
        near_cost=near_cost,
        damage_cost=damage_cost,
    )


class GuidanceField:
    """Distance (in ticks) from every tile to a goal tile set, over one ``Terrain``."""

    __slots__ = ("terrain", "dist", "goals")

    def __init__(self, terrain: Terrain, goals: Iterable[tuple[int, int]]) -> None:
        self.terrain = terrain
        self.goals = tuple(goals)
        self.dist = self._solve()

    # -- edge model -------------------------------------------------------------

    def _enter_cost(self, idx: int) -> float:
        t = self.terrain
        cost = 0.0
        if t.near[idx]:
            cost += t.near_cost
        if t.hazard[idx] == 2:
            cost += t.damage_cost
        return cost

    def _solve(self) -> list[float]:
        t = self.terrain
        w, h = t.width, t.height
        dist = [INF] * (w * h)
        heap: list[tuple[float, int]] = []
        for gx, gy in self.goals:
            if not t.inside(gx, gy):
                continue
            idx = gy * w + gx
            seeds = [idx]
            if not t.passable[idx]:
                # a solid goal tile: seed the passable tiles touching it
                seeds = []
                for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)):
                    nx, ny = gx + dx, gy + dy
                    if t.inside(nx, ny) and t.passable[ny * w + nx]:
                        seeds.append(ny * w + nx)
            for seed in seeds:
                if dist[seed] > 0.0:
                    dist[seed] = 0.0
                    heapq.heappush(heap, (0.0, seed))

        passable, standable, wet, air = t.passable, t.standable, t.wet, t.air_height
        drift_ok = t.drift_ok
        tick_h, tick_water = t.tick_h, t.tick_water
        while heap:
            d, v = heapq.heappop(heap)
            if d > dist[v]:
                continue
            vy, vx = divmod(v, w)
            enter = self._enter_cost(v)  # cost of *arriving* at v

            # horizontal predecessors
            for ux in (vx - 1, vx + 1):
                if 0 <= ux < w:
                    u = vy * w + ux
                    if passable[u] and (wet[v] or wet[u] or ((standable[u] or drift_ok[u]) and (standable[v] or drift_ok[v]))):
                        nd = d + (tick_water if wet[v] else tick_h) + enter
                        if nd < dist[u]:
                            dist[u] = nd
                            heapq.heappush(heap, (nd, u))

            # u above v: u falls into v (or swims down)
            if vy > 0:
                u = v - w
                if passable[u]:
                    if wet[u] and wet[v]:
                        nd = d + t.tick_swim_down + enter
                    elif not standable[u]:
                        nd = d + t.tick_fall + enter
                    else:
                        nd = INF
                    if nd < dist[u]:
                        dist[u] = nd
                        heapq.heappush(heap, (nd, u))

            # u below v: u rises into v
            if vy + 1 < h:
                u = v + w
                if passable[u]:
                    if wet[u] and wet[v]:
                        nd = d + t.tick_swim_up + enter
                    elif air[u] < t.rise_cap:
                        nd = d + t.tick_rise + enter
                    else:
                        nd = INF
                    if nd < dist[u]:
                        dist[u] = nd
                        heapq.heappush(heap, (nd, u))

        return dist

    # -- queries ----------------------------------------------------------------

    def at(self, tx: int, ty: int) -> float:
        t = self.terrain
        if 0 <= tx < t.width and 0 <= ty < t.height:
            return self.dist[ty * t.width + tx]
        return INF

    def reachable(self, tx: int, ty: int) -> bool:
        return self.at(tx, ty) < INF

    def vertical_move_columns(self, tx: int, ty: int, *, limit: int = 160) -> list[tuple[int, int, str]]:
        """Walk the guided route from ``(tx, ty)``; list ``(column, row, move)`` of
        the first vertical moves (``"rise"``/``"fall"``).  The planner uses these as
        *where to line up*: a hole in the ceiling can only be used from its column.
        """
        t = self.terrain
        w, h = t.width, t.height
        found: list[tuple[int, int, str]] = []
        x, y = tx, ty
        seen: set[int] = set()
        for _ in range(limit):
            u = y * w + x
            if u in seen or self.dist[u] <= 0.0 or self.dist[u] == INF:
                break
            seen.add(u)
            best = None
            best_val = INF
            for nx, ny, kind in ((x - 1, y, "h"), (x + 1, y, "h"), (x, y + 1, "fall"), (x, y - 1, "rise")):
                if not t.inside(nx, ny):
                    continue
                v = ny * w + nx
                if not t.passable[v]:
                    continue
                if kind == "h":
                    if not (t.wet[u] or t.wet[v] or ((t.standable[u] or t.drift_ok[u]) and (t.standable[v] or t.drift_ok[v]))):
                        continue
                if kind == "fall":
                    if not ((t.wet[u] and t.wet[v]) or not t.standable[u]):
                        continue
                elif kind == "rise":
                    if not ((t.wet[u] and t.wet[v]) or t.air_height[u] < t.rise_cap):
                        continue
                value = self.dist[v]
                if value < best_val:
                    best_val, best = value, (nx, ny, kind)
            if best is None or best_val >= self.dist[u]:
                break
            nx, ny, kind = best
            if kind != "h":
                found.append((x, y, "rise" if kind == "rise" else "fall"))
                if len(found) >= 3:
                    break
            x, y = nx, ny

        return found
