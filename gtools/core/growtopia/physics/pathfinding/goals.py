"""Goal semantics: *standing in* a tile versus merely *touching* it.

The old goal was "the collision rect overlaps the tile (or rests on its top edge)".
That accepts a one-pixel graze of the tile's edge while still carrying full speed,
so a route "reached" a goal it then immediately left.

Two modes replace it:

``STAND``
    The avatar's **centre** is inside the tile *and* it stays there, with no input,
    for ``dwell_ticks`` consecutive ticks (default 12 = 0.2 s), ending on something it
    rests on (ground, a climb grip, or in water).  The planner checks the dwell with
    the exact kernel (``finish``), including a short braking burst, so momentum that
    would carry the avatar out of the tile is accounted for.  The dwell frames are
    appended to the route, so executing the route performs the stand.

``TOUCH``
    The rect overlaps the tile at any tick, no dwell.  Used when no avatar can rest
    in the tile -- a tile in mid-air, a ledge it can only fly past -- because a stand
    could never succeed and the old behaviour (reach it in passing) is the only
    meaningful one.

``resolve_goal`` picks the mode automatically from the world: a solid tile means
"stand on top of it"; a free tile is ``STAND`` when a probe finds a resting
configuration inside it, otherwise ``TOUCH``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from gtools.core.growtopia.physics.controller import TILE
from gtools.core.growtopia.physics.pathfinding.types import InputFrame, MotionState

DEFAULT_DWELL_TICKS = 12


class GoalMode(IntEnum):
    STAND = 0
    TOUCH = 1


@dataclass(frozen=True, slots=True)
class Goal:
    tx: int
    ty: int
    mode: GoalMode
    dwell_ticks: int
    width: float
    height: float
    requested: tuple[int, int] = (-1, -1)  # the tile the caller asked for
    margin: float = 0.0  # contact slack (1 px for a solid tile that can only be touched)

    # -- geometry ---------------------------------------------------------------

    @property
    def box(self) -> tuple[int, int, int, int]:
        return (self.tx, self.ty, self.tx, self.ty)

    def centre_inside(self, x: float, y: float) -> bool:
        cx, cy = x + self.width / 2.0, y + self.height / 2.0
        return self.tx * TILE <= cx < (self.tx + 1) * TILE and self.ty * TILE <= cy < (self.ty + 1) * TILE

    def overlaps(self, x: float, y: float) -> bool:
        m = self.margin
        return (
            x < (self.tx + 1) * TILE + m
            and x + self.width > self.tx * TILE - m
            and y < (self.ty + 1) * TILE + m
            and y + self.height > self.ty * TILE - m
        )

    def region(self, x: float, y: float) -> bool:
        """Positional membership test used while scanning a segment's trace."""
        return self.centre_inside(x, y) if self.mode is GoalMode.STAND else self.overlaps(x, y)

    # -- state tests ------------------------------------------------------------

    def reached(self, state: MotionState) -> bool:
        """Is ``state`` a finished arrival (the dwell itself is checked by ``finish``)?"""
        if state.killed:
            return False
        if self.mode is GoalMode.TOUCH:
            return self.overlaps(state.x, state.y)

        return self.centre_inside(state.x, state.y) and (state.grounded or state.climbing or state.in_water)

    def arrival_possible(self, state: MotionState) -> bool:
        """Cheap pre-filter for ``finish``: the state is in the goal region at rest-ish."""
        return self.reached(state)


@dataclass(slots=True)
class Finish:
    """A verified dwell: the frames to append and the state they end in."""

    frames: tuple[InputFrame, ...]
    end: MotionState
    ticks: int
    trace: list[tuple[float, float, bool]]


def finish_stand(evaluator: Any, goal: Goal, state: MotionState) -> Finish | None:
    """Verify (with the kernel) that ``state`` can stand in ``goal`` for the dwell.

    Tries *idle*, then a short *brake* (push against the current velocity) followed by
    idle.  The first variant that keeps the centre inside the tile for the whole dwell,
    without dying or taking damage, wins.
    """
    n = max(1, int(goal.dwell_ticks))
    variants: list[tuple[InputFrame, ...]] = [((0, False, n),)]
    if abs(state.vx) > 8.0 and (state.grounded or state.in_water):
        against = -1 if state.vx > 0 else 1
        for brake in (3, 6, 9, 13, 18):
            variants.append(((against, False, brake), (0, False, n)))

    for frames in variants:
        probe = state.clone()
        # a held jump would re-fire on the idle frame: the dwell is hands-off
        outcome = evaluator.simulate(probe, frames, record_trace=True)
        if outcome.state.killed or outcome.damage_hits:
            continue
        trace = outcome.tick_trace
        dwell = trace[-n:] if len(trace) >= n else trace
        if len(dwell) < n:
            continue
        if not all(goal.centre_inside(x, y) for x, y, _g in dwell):
            continue
        end = outcome.state
        if not (end.grounded or end.climbing or end.in_water):
            continue

        return Finish(frames=frames, end=end, ticks=outcome.ticks, trace=trace)

    return None


def rest_possible(evaluator: Any, snapshot: Any, goal_tx: int, goal_ty: int, width: float, height: float, dwell: int) -> bool:
    """Can an avatar come to rest with its centre inside ``(goal_tx, goal_ty)``?

    Probes a few seeds (feet on the tile's bottom edge, a few x offsets; plus a
    mid-tile seed for water) and lets the kernel run the dwell with no input.
    """
    grid = snapshot.grid
    if not (0 <= goal_tx < grid.width and 0 <= goal_ty < grid.height):
        return False

    goal = Goal(goal_tx, goal_ty, GoalMode.STAND, dwell, width, height)
    seeds: list[tuple[float, float]] = []
    cx = goal_tx * TILE + TILE / 2.0 - width / 2.0
    for dx in (0.0, -6.0, 6.0):
        seeds.append((cx + dx, (goal_ty + 1) * TILE - height))
    seeds.append((cx, goal_ty * TILE + TILE / 2.0 - height / 2.0))

    for x, y in seeds:
        state = evaluator.initial_state()
        state.x, state.y = x, y
        outcome = evaluator.simulate(state, ((0, False, max(2, dwell)),), record_trace=True)
        if outcome.state.killed or outcome.damage_hits:
            continue
        trace = outcome.tick_trace
        if len(trace) < max(2, dwell):
            continue
        if not all(goal.centre_inside(tx, ty) for tx, ty, _g in trace[-max(1, dwell):]):
            continue
        end = outcome.state
        if end.grounded or end.climbing or end.in_water:
            return True

    return False


def resolve_goal(
    evaluator: Any,
    snapshot: Any,
    profile: Any,
    tx: int,
    ty: int,
    *,
    dwell_ticks: int | None = None,
    mode: str | GoalMode = "auto",
) -> Goal:
    """Decide how ``(tx, ty)`` should be reached (see the module docstring)."""
    dwell = DEFAULT_DWELL_TICKS if dwell_ticks is None else max(0, int(dwell_ticks))
    width, height = float(profile.width), float(profile.height)
    grid = snapshot.grid
    requested = (int(tx), int(ty))

    if isinstance(mode, str):
        mode = mode.lower()
        forced: GoalMode | None = {"stand": GoalMode.STAND, "touch": GoalMode.TOUCH}.get(mode)
    else:
        forced = mode

    def solid(x: int, y: int) -> bool:
        idx = grid.index(x, y)
        return idx is not None and grid.fg_id[idx] > 0 and bool(grid.blocks[idx] or grid.platform[idx] or grid.gated[idx])

    if forced is GoalMode.TOUCH:
        return Goal(tx, ty, GoalMode.TOUCH, 0, width, height, requested, 1.0 if solid(tx, ty) else 0.0)

    # a solid / platform tile: the sensible reading is "get on top of it"
    if solid(tx, ty) and not solid(tx, ty - 1):
        ty -= 1

    if dwell <= 0:
        return Goal(tx, ty, GoalMode.STAND if forced is GoalMode.STAND else GoalMode.TOUCH, 0, width, height, requested)

    if forced is GoalMode.STAND or rest_possible(evaluator, snapshot, tx, ty, width, height, dwell):
        return Goal(tx, ty, GoalMode.STAND, dwell, width, height, requested)

    return Goal(tx, ty, GoalMode.TOUCH, 0, width, height, requested, 1.0 if solid(tx, ty) else 0.0)
