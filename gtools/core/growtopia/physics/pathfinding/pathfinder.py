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
from gtools.core.growtopia.physics.pathfinding.goals import DEFAULT_DWELL_TICKS, Goal, GoalMode, finish_stand, resolve_goal
from gtools.core.growtopia.physics.pathfinding.guidance import GuidanceField, Terrain, build_terrain
from gtools.core.growtopia.physics.pathfinding.planner import (
    HazardIndex,
    SearchTrace,
    SegmentedPlanner,
    Target,
)
from gtools.core.growtopia.physics.pathfinding.profile import CapabilityProfile
from gtools.core.growtopia.physics.pathfinding.snapshot import WorldSnapshot
from gtools.core.growtopia.physics.pathfinding.types import MotionState, Path, PlanResult, PlanStatus


class SegmentedPathfinder:
    """Builds segmented paths for one live ``PlayerController``.

    Planning knobs
    --------------
    ``max_expansions`` / ``time_budget_ms``
        The search budget.  The expansion count is the primary limit (the result is
        then independent of machine speed); the wall-clock is a safety net.
    ``dwell_ticks``
        How long the avatar must *stand* in a goal tile (see :mod:`goals`).
    ``damage_policy``
        ``"avoid"`` (default): search with damaging tiles forbidden first and only
        accept damage when no safe route exists.  ``"allow"``: one search where damage
        is just a priced cost.  ``"forbid"``: never touch a damaging tile.
    ``damage_penalty``
        Cost (in ticks) of one damaging hit when damage is allowed.
    """

    def __init__(
        self,
        controller: Any,
        *,
        damage_penalty: float = 80.0,
        walk_tiles: int = 4,
        max_expansions: int = 5000,
        time_budget_ms: float = 1500.0,
        max_damage_hits: int | None = None,
        max_segments: int = 4096,
        validate: bool = False,
        heuristic_weight: float = 1.5,
        record_search: bool = False,
        dwell_ticks: int = DEFAULT_DWELL_TICKS,
        damage_policy: str = "avoid",
        fragile_penalty: float = 25.0,
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
        self.dwell_ticks = int(dwell_ticks)
        self.damage_policy = damage_policy
        self.fragile_penalty = float(fragile_penalty)

        # opt-in: keep the last search (passes, generated + expanded states) so an
        # inspector can draw what the planner actually did
        self.search_trace: SearchTrace | None = SearchTrace() if record_search else None
        self._edge_cache: dict = {}
        self._fingerprint: tuple | None = None
        self._epoch: int = -1
        self._terrains: dict[bool, Terrain] = {}
        self._fields: dict[tuple, GuidanceField] = {}
        self._hazards: HazardIndex | None = None
        self._request: tuple | None = None
        self._goal_spec: Goal | None = None
        self._goal_fn: Callable[[MotionState], bool] | None = None
        self.last_goal: Goal | None = None

        self._rebuild()

    # -- planning --------------------------------------------------------------

    def plan_to_tile(
        self,
        tx: int,
        ty: int,
        *,
        time_budget_ms: float | None = None,
        dwell_ticks: int | None = None,
        mode: str = "auto",
    ) -> PlanResult:
        """Plan to the tile ``(tx, ty)``.

        ``mode="auto"`` stands in the tile for ``dwell_ticks`` when an avatar can rest
        there (a solid tile means "on top of it") and merely touches it otherwise;
        ``"stand"`` / ``"touch"`` force one reading.
        """
        tx, ty = int(tx), int(ty)
        dwell = self.dwell_ticks if dwell_ticks is None else int(dwell_ticks)
        self._rebuild()
        goal = resolve_goal(self.evaluator, self.snapshot, self.profile, tx, ty, dwell_ticks=dwell, mode=mode)
        self.last_goal = goal
        if self.search_trace is not None:
            self.search_trace.goal = (goal.tx, goal.ty)

        return self._plan_goal(goal, time_budget_ms=time_budget_ms, remember=("tile", tx, ty, dwell, mode))

    def plan_to_xy(
        self,
        x: float,
        y: float,
        *,
        tolerance: float = 8.0,
        time_budget_ms: float | None = None,
        max_expansions: int | None = None,
    ) -> PlanResult:
        x, y, tolerance = float(x), float(y), float(tolerance)
        self._rebuild()
        width, height = self.profile.width, self.profile.height

        def reached(state: MotionState) -> bool:
            return math.hypot(state.x + width / 2.0 - x, state.y + height / 2.0 - y) <= tolerance

        def touch(px: float, py: float) -> bool:
            return math.hypot(px + width / 2.0 - x, py + height / 2.0 - y) <= tolerance

        tile = (int(x // TILE), int(y // TILE))
        target = self._guided_target(tile, reached, self._pixel_progress(x, y), touch=touch, goal_point=(x, y))
        self._remember(("xy", x, y, tolerance), reached)

        return self._run(target, reached, time_budget_ms, max_expansions)

    def plan_to_predicate(self, predicate: Callable[[MotionState], bool], *, heuristic: Callable[[MotionState], float] | None = None) -> PlanResult:
        self._rebuild()
        h = heuristic or (lambda state: 0.0)
        target = Target(goal=predicate, heuristic=lambda state, stage: h(state), damage_possible=True)
        self._remember(("predicate", predicate, heuristic), predicate)

        return self._run(target, predicate, None)

    def plan_from_current(self, *, time_budget_ms: float | None = None, max_expansions: int | None = None) -> PlanResult:
        request = self._request
        if request is None:
            return PlanResult.failure(PlanStatus.INVALID_GOAL, "no goal recorded")

        self._rebuild()
        kind = request[0]
        if kind == "tile" and self._goal_spec is not None:
            return self._plan_goal(self._goal_spec, time_budget_ms=time_budget_ms, remember=None, max_expansions=max_expansions)
        if kind == "xy":
            return self.plan_to_xy(request[1], request[2], tolerance=request[3], time_budget_ms=time_budget_ms, max_expansions=max_expansions)
        if kind == "predicate":
            h = request[2] or (lambda state: 0.0)
            target = Target(goal=request[1], heuristic=lambda state, stage: h(state), damage_possible=True)
            return self._run(target, request[1], time_budget_ms, max_expansions)

        return PlanResult.failure(PlanStatus.INVALID_GOAL, "no goal recorded")

    def _remember(self, request: tuple, goal_fn: Callable[[MotionState], bool]) -> None:
        self._request = request
        self._goal_fn = goal_fn

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
        return self._goal_fn is not None and bool(self._goal_fn(state))

    def profile_now(self) -> CapabilityProfile:
        return CapabilityProfile.from_controller(self.controller)

    def invalidate_tile(self, tx: int, ty: int) -> None:
        self.snapshot.sync_tile(self.controller.world, int(tx), int(ty))

    # -- internals -------------------------------------------------------------

    def _rebuild(self) -> None:
        self.snapshot.sync(self.controller.world)
        profile = CapabilityProfile.from_controller(self.controller)
        fingerprint = profile.fingerprint()
        stale = fingerprint != self._fingerprint or self.snapshot.epoch != self._epoch
        if fingerprint != self._fingerprint:
            self._edge_cache.clear()
        self.profile = profile

        if stale or not hasattr(self, "evaluator"):
            self._fingerprint = fingerprint
            self._epoch = self.snapshot.epoch
            self._terrains.clear()
            self._fields.clear()
            self._hazards = HazardIndex(self.snapshot)
            self.evaluator = FastEvaluator(self.snapshot, self.profile)
            self.catalog = ActionCatalog(self.evaluator, damage_penalty=self.damage_penalty, walk_tiles=self.walk_tiles)

        self.catalog.damage_penalty = self.damage_penalty
        self.catalog.walk_tiles = max(1, self.walk_tiles)
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
            hazard_index=self._hazards,
            fragile_penalty=self.fragile_penalty,
            damage_policy=self.damage_policy,
        )

    def _terrain(self, allow_damage: bool) -> Terrain:
        terrain = self._terrains.get(allow_damage)
        if terrain is None:
            evaluator = self.evaluator
            probe = evaluator.initial_state()

            def blocks(idx: int) -> bool:
                return bool(evaluator._blocks_like(probe, idx))

            terrain = build_terrain(
                self.snapshot, self.profile, allow_damage=allow_damage, blocks=blocks, damage_cost=self.damage_penalty
            )
            self._terrains[allow_damage] = terrain

        return terrain

    def _field(self, goals: tuple[tuple[int, int], ...], allow_damage: bool) -> GuidanceField:
        key = (goals, allow_damage)
        field = self._fields.get(key)
        if field is None:
            if len(self._fields) > 16:
                self._fields.clear()
            field = GuidanceField(self._terrain(allow_damage), goals)
            self._fields[key] = field

        return field

    def _guided_target(
        self,
        tile: tuple[int, int],
        reached: Callable[[MotionState], bool],
        progress: Callable[[MotionState], float],
        *,
        touch: Callable[[float, float], bool] | None = None,
        goal_point: tuple[float, float] | None = None,
        finish: Callable[[MotionState], Any] | None = None,
        hints_goal: Goal | None = None,
    ) -> Target:
        """A ``Target`` whose heuristic is the tile guidance field to ``tile``."""
        safe_terrain, damage_terrain = self._terrain(False), self._terrain(True)
        damage_possible = safe_terrain.has_damage
        goals = (tile,)
        safe = self._field(goals, False)
        fields = (safe, self._field(goals, True) if damage_possible else safe)
        width, height = self.profile.width, self.profile.height
        px_per_tick = max(self.profile.max_velocity * self.profile.dt, 1e-9)
        tick_h = TILE / px_per_tick
        gx = tile[0] * TILE + TILE / 2.0 if goal_point is None else goal_point[0]
        gy = tile[1] * TILE + TILE / 2.0 if goal_point is None else goal_point[1]

        def heuristic(state: MotionState, stage: int) -> float:
            cx = state.x + width / 2.0
            cy = state.y + height / 2.0
            d = fields[stage].at(int(cx // TILE), int(cy // TILE))
            if d == math.inf:
                # the abstraction cannot see a way (a bouncer, wind...): fall back to a
                # large, still distance-ordered estimate so the search keeps exploring
                return 600.0 + (abs(cx - gx) + abs(cy - gy)) / px_per_tick
            if d <= tick_h * 1.5:
                d += 0.5 * abs(cx - gx) / px_per_tick  # tie-break inside the goal's neighbourhood
            return d

        start_cell = None
        hint_cache: dict[tuple[int, int], list[int]] = {}
        hint_field = safe if safe.at(*self._cell_of(self.motion_state())) < math.inf else fields[1]

        side_cache: dict[tuple[int, int, bool], tuple[int, ...]] = {}

        def prefer(state: MotionState) -> tuple[int, ...]:
            # which way does the guidance say is *closer*?  Look one tile either side of
            # the avatar's cell; ties (or both unknown) keep both directions.
            cx, cy = self._cell_of(state)
            key = (cx, cy, state.grounded)
            cached = side_cache.get(key)
            if cached is not None:
                return cached
            field = hint_field
            left, right, here_d = field.at(cx - 1, cy), field.at(cx + 1, cy), field.at(cx, cy)
            if left == math.inf and right == math.inf:
                result = (-1, 1)
            elif right < left - 1.0:
                result = (1,)
            elif left < right - 1.0:
                result = (-1,)
            else:
                result = (-1, 1)
            side_cache[key] = result
            return result

        def hints(state: MotionState) -> list[int]:
            if not state.grounded or state.climbing:
                return []
            feet = int((state.y + height - 1e-4) // TILE)
            column = int((state.x + width / 2.0) // TILE)
            key = (column, feet)
            cached = hint_cache.get(key)
            if cached is not None:
                return cached
            columns: list[int] = []
            if hints_goal is not None and hints_goal.mode is GoalMode.STAND and feet == hints_goal.ty and hints_goal.tx != column:
                columns.append(hints_goal.tx)
            for col, row, _move in hint_field.vertical_move_columns(column, feet):
                if row == feet and col != column and col not in columns:
                    columns.append(col)
            hint_cache[key] = columns[:3]
            return hint_cache[key]

        here = self._cell_of(self.motion_state())
        feasible = safe.at(*here) < math.inf
        hopeless = not feasible and fields[1].at(*here) == math.inf and not safe_terrain.exotic

        return Target(
            goal=reached,
            heuristic=heuristic,
            progress=progress,
            touch=touch,
            touch_box=(tile[0], tile[1], tile[0], tile[1]) if touch is not None else None,
            finish=finish,
            hints=hints,
            prefer=prefer,
            safe_feasible=feasible,
            damage_possible=damage_possible,
            hopeless=hopeless,
        )

    def _cell_of(self, state: MotionState) -> tuple[int, int]:
        return int((state.x + self.profile.width / 2.0) // TILE), int((state.y + self.profile.height / 2.0) // TILE)

    def _plan_goal(
        self, goal: Goal, *, time_budget_ms: float | None, remember: tuple | None, max_expansions: int | None = None
    ) -> PlanResult:
        width, height = self.profile.width, self.profile.height
        evaluator = self.evaluator
        stand = goal.mode is GoalMode.STAND
        cx, cy = goal.tx * TILE + TILE / 2.0, goal.ty * TILE + TILE / 2.0

        def reached(state: MotionState) -> bool:
            return goal.reached(state)

        finish = (lambda state: finish_stand(evaluator, goal, state)) if stand and goal.dwell_ticks > 0 else None
        touch = None if stand else goal.region
        target = self._guided_target(
            (goal.tx, goal.ty),
            reached,
            self._pixel_progress(cx, cy),
            touch=touch,
            finish=finish,
            hints_goal=goal,
        )
        if remember is not None:
            self._remember(remember, reached)
            self._goal_spec = goal
        else:
            self._goal_fn = reached

        return self._run(target, reached, time_budget_ms, max_expansions)

    def _run(
        self,
        target: Target,
        reached: Callable[[MotionState], bool],
        time_budget_ms: float | None,
        max_expansions: int | None = None,
    ) -> PlanResult:
        start = self.motion_state()
        if reached(start) and (target.finish is None or target.finish(start) is not None):
            return PlanResult(
                status=PlanStatus.FOUND,
                path=Path(segments=[], goal=(int(start.x // TILE), int((start.y + self.profile.height - 1e-4) // TILE))),
                reason="already at the goal",
                profile_fingerprint=self._fingerprint or (),
            )

        result = self.planner.plan_target(start, target, time_budget_ms=time_budget_ms, max_expansions=max_expansions)
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
