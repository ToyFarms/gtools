"""High-level facade: controller -> plan, with an oracle-checked result.

Typical use::

    pathfinder = SegmentedPathfinder(controller)
    result = pathfinder.plan_to_tile(42, 10)
    follower = PathFollower(controller, pathfinder, result.path)

Every public plan call refreshes the world snapshot and the live capability
profile, so re-planning after a ``SET_CHARACTER_STATE`` or a world edit is just
another call.

``validate=True`` replays the finished path through ``ControllerOracle`` (the
real controller) and downgrades the result to ``PARTIAL`` on any mismatch.  It
is off by default because that replay runs at ~10 k ticks/s -- 100 ms on a long
path -- and ``PathFollower`` already compares every live tick against the
recorded trace, which catches the same drift for free.  Use it in tests, in a
one-off tool, or whenever a caller drives the frames without a follower.
"""

from __future__ import annotations

import math
from typing import Any, Callable

from gtools.core.growtopia.physics.controller import TILE
from gtools.core.growtopia.physics.pathfinding.actions import ActionCatalog
from gtools.core.growtopia.physics.pathfinding.fastkernel import FastEvaluator
from gtools.core.growtopia.physics.pathfinding.oracle import ControllerOracle, motion_from_controller
from gtools.core.growtopia.physics.pathfinding.planner import (
    SearchTrace,
    SegmentedPlanner,
    tile_goal,
    tile_heuristic,
    tile_touch,
)
from gtools.core.growtopia.physics.pathfinding.profile import CapabilityProfile
from gtools.core.growtopia.physics.pathfinding.snapshot import WorldSnapshot
from gtools.core.growtopia.physics.pathfinding.types import MotionState, Path, PlanResult, PlanStatus


class SegmentedPathfinder:
    """Builds segmented paths for one live ``PlayerController``."""

    def __init__(
        self,
        controller: Any,
        *,
        damage_penalty: float = 24.0,
        walk_tiles: int = 4,
        max_expansions: int = 4000,
        time_budget_ms: float = 250.0,
        max_damage_hits: int | None = None,
        max_segments: int = 64,
        validate: bool = False,
        heuristic_weight: float = 1.5,
        record_search: bool = False,
    ) -> None:
        self.controller = controller
        self.snapshot = WorldSnapshot(controller.world)
        self.damage_penalty = float(damage_penalty)
        self.walk_tiles = int(walk_tiles)
        self.max_expansions = int(max_expansions)
        self.time_budget_ms = float(time_budget_ms)
        self.max_damage_hits = max_damage_hits
        self.max_segments = int(max_segments)
        self.validate = bool(validate)
        self.heuristic_weight = float(heuristic_weight)

        # opt-in: keep the last search (passes, generated + expanded states) so an
        # inspector can draw what the planner actually did
        self.search_trace: SearchTrace | None = SearchTrace() if record_search else None
        self._edge_cache: dict = {}
        self._fingerprint: tuple | None = None
        self._goal: Callable[[MotionState], bool] | None = None
        self._heuristic: Callable[[MotionState], float] | None = None
        self._progress: Callable[[MotionState], float] | None = None
        self._touch: Callable[[float, float], bool] | None = None
        self._touch_box: tuple[int, int, int, int] | None = None

        self._rebuild()

    # -- planning --------------------------------------------------------------

    def plan_to_tile(self, tx: int, ty: int, *, time_budget_ms: float | None = None) -> PlanResult:
        tx, ty = int(tx), int(ty)
        if self.search_trace is not None:
            self.search_trace.goal = (tx, ty)

        return self._plan(
            tile_goal(tx, ty, self.profile),
            tile_heuristic(self.profile, tx, ty),
            self._pixel_progress(tx * TILE + TILE / 2.0, ty * TILE + TILE / 2.0),
            touch=tile_touch(tx, ty, self.profile.width, self.profile.height),
            touch_box=(tx, ty, tx, ty),
            time_budget_ms=time_budget_ms,
        )

    def plan_to_xy(self, x: float, y: float, *, tolerance: float = 8.0, time_budget_ms: float | None = None) -> PlanResult:
        x, y, tolerance = float(x), float(y), float(tolerance)
        width, height = self.profile.width, self.profile.height

        def goal(state: MotionState) -> bool:
            cx, cy = state.x + width / 2.0, state.y + height / 2.0
            return math.hypot(cx - x, cy - y) <= tolerance

        ticks_per_tile = TILE / max(self.profile.max_velocity * self.profile.dt, 1e-9)

        def heuristic(state: MotionState) -> float:
            cx = state.x + width / 2.0
            return max(0.0, abs(cx - x) - tolerance) / TILE * ticks_per_tile

        def touch(px: float, py: float) -> bool:
            return math.hypot(px + width / 2.0 - x, py + height / 2.0 - y) <= tolerance

        return self._plan(goal, heuristic, self._pixel_progress(x, y), touch=touch, time_budget_ms=time_budget_ms)

    def plan_to_predicate(self, predicate: Callable[[MotionState], bool], *, heuristic: Callable[[MotionState], float] | None = None) -> PlanResult:
        return self._plan(predicate, heuristic or (lambda state: 0.0))

    def plan_from_current(self, *, time_budget_ms: float | None = None) -> PlanResult:
        if self._goal is None:
            return PlanResult.failure(PlanStatus.INVALID_GOAL, "no goal recorded")

        return self._plan(
            self._goal,
            self._heuristic or (lambda state: 0.0),
            self._progress,
            remember=False,
            touch=self._touch,
            touch_box=self._touch_box,
            time_budget_ms=time_budget_ms,
        )

    def _pixel_progress(self, x: float, y: float) -> Callable[[MotionState], float]:
        """Euclidean distance from the avatar's centre to ``(x, y)``.

        Only used to pick where a budget-exhausted *partial* path ends: the tile
        heuristic is flat inside a tile, so without this a partial route can end on
        the state it started from.
        """
        width, height = self.profile.width, self.profile.height

        def progress(state: MotionState) -> float:
            return math.hypot(state.x + width / 2.0 - x, state.y + height / 2.0 - y)

        return progress

    # -- state -----------------------------------------------------------------

    def motion_state(self) -> MotionState:
        return motion_from_controller(self.controller)

    def goal_reached(self, state: MotionState) -> bool:
        return self._goal is not None and bool(self._goal(state))

    def profile_now(self) -> CapabilityProfile:
        return CapabilityProfile.from_controller(self.controller)

    def invalidate_tile(self, tx: int, ty: int) -> None:
        self.snapshot.sync_tile(self.controller.world, int(tx), int(ty))

    # -- internals -------------------------------------------------------------

    def _rebuild(self) -> None:
        self.snapshot.sync(self.controller.world)
        self.profile = CapabilityProfile.from_controller(self.controller)
        fingerprint = self.profile.fingerprint()
        if fingerprint != self._fingerprint:
            self._edge_cache.clear()
            self._fingerprint = fingerprint

        self.evaluator = FastEvaluator(self.snapshot, self.profile)
        self.catalog = ActionCatalog(self.evaluator, damage_penalty=self.damage_penalty, walk_tiles=self.walk_tiles)
        self.planner = SegmentedPlanner(
            self.catalog,
            self.profile,
            self.snapshot,
            max_expansions=self.max_expansions,
            time_budget_ms=self.time_budget_ms,
            max_damage_hits=self.max_damage_hits,
            max_segments=self.max_segments,
            edge_cache=self._edge_cache,
            heuristic_weight=self.heuristic_weight,
            trace=self.search_trace,
        )

    def _plan(
        self,
        goal: Callable[[MotionState], bool],
        heuristic: Callable[[MotionState], float],
        progress: Callable[[MotionState], float] | None = None,
        *,
        remember: bool = True,
        touch: Callable[[float, float], bool] | None = None,
        touch_box: tuple[int, int, int, int] | None = None,
        time_budget_ms: float | None = None,
    ) -> PlanResult:
        self._rebuild()
        if remember:
            self._goal = goal
            self._heuristic = heuristic
            self._progress = progress
            self._touch = touch
            self._touch_box = touch_box

        start = self.motion_state()
        if goal(start):
            return PlanResult(
                status=PlanStatus.FOUND,
                path=Path(segments=[], goal=(int(start.x // TILE), int((start.y + self.profile.height - 1e-4) // TILE))),
                reason="already at the goal",
                profile_fingerprint=self._fingerprint or (),
            )

        result = self.planner.plan(
            start,
            goal,
            heuristic,
            progress,
            touch=touch,
            touch_box=touch_box,
            time_budget_ms=time_budget_ms,
        )
        if result.ok and self.validate and result.path is not None:
            self._oracle_check(result)

        return result

    def _oracle_check(self, result: PlanResult) -> None:
        path = result.path
        if path is None or not path.segments:
            return

        oracle = ControllerOracle.from_controller(self.controller, self.snapshot)
        frames = tuple(frame for segment in path.segments for frame in segment.frames)
        outcome = oracle.run(self.motion_state(), frames, max_ticks=path.total_ticks + 1)
        expected = path.end
        if expected is None:
            return

        if not _close(outcome.state, expected):
            result.status = PlanStatus.PARTIAL
            result.reason = "oracle validation mismatch"


def _close(actual: MotionState, expected: MotionState) -> bool:
    if abs(actual.x - expected.x) > 0.5 or abs(actual.y - expected.y) > 0.5:
        return False
    if abs(actual.vx - expected.vx) > 1.0 or abs(actual.vy - expected.vy) > 1.0:
        return False
    for name in ("grounded", "sliding", "in_water", "climbing"):
        if bool(getattr(actual, name)) != bool(getattr(expected, name)):
            return False
    return True
