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
from gtools.core.growtopia.physics.pathfinding.planner import SegmentedPlanner, tile_goal, tile_heuristic
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

        self._edge_cache: dict = {}
        self._fingerprint: tuple | None = None
        self._goal: Callable[[MotionState], bool] | None = None
        self._heuristic: Callable[[MotionState], float] | None = None

        self._rebuild()

    # -- planning --------------------------------------------------------------

    def plan_to_tile(self, tx: int, ty: int) -> PlanResult:
        return self._plan(tile_goal(int(tx), int(ty), self.profile), tile_heuristic(self.profile, int(tx), int(ty)))

    def plan_to_xy(self, x: float, y: float, *, tolerance: float = 8.0) -> PlanResult:
        x, y, tolerance = float(x), float(y), float(tolerance)
        width, height = self.profile.width, self.profile.height

        def goal(state: MotionState) -> bool:
            cx, cy = state.x + width / 2.0, state.y + height / 2.0
            return math.hypot(cx - x, cy - y) <= tolerance

        ticks_per_tile = TILE / max(self.profile.max_velocity * self.profile.dt, 1e-9)

        def heuristic(state: MotionState) -> float:
            cx = state.x + width / 2.0
            return max(0.0, abs(cx - x) - tolerance) / TILE * ticks_per_tile

        return self._plan(goal, heuristic)

    def plan_to_predicate(self, predicate: Callable[[MotionState], bool], *, heuristic: Callable[[MotionState], float] | None = None) -> PlanResult:
        return self._plan(predicate, heuristic or (lambda state: 0.0))

    def plan_from_current(self) -> PlanResult:
        if self._goal is None:
            return PlanResult.failure(PlanStatus.INVALID_GOAL, "no goal recorded")

        return self._plan(self._goal, self._heuristic or (lambda state: 0.0), remember=False)

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
        )

    def _plan(self, goal: Callable[[MotionState], bool], heuristic: Callable[[MotionState], float], *, remember: bool = True) -> PlanResult:
        self._rebuild()
        if remember:
            self._goal = goal
            self._heuristic = heuristic

        start = self.motion_state()
        if goal(start):
            return PlanResult(
                status=PlanStatus.FOUND,
                path=Path(segments=[], goal=(int(start.x // TILE), int((start.y + self.profile.height - 1e-4) // TILE))),
                reason="already at the goal",
                profile_fingerprint=self._fingerprint or (),
            )

        result = self.planner.plan(start, goal, heuristic)
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
