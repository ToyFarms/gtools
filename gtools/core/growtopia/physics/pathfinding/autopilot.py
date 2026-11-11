"""Host-loop adapter: plan, follow and cancel for callers that own ``step()``.

``PathFollower`` splits a tick in two (``tick_inputs`` then ``observe``), which is
convenient when the follower owns the loop but easy to misuse when a host loop
already calls ``controller.step()``.  ``PathAutopilot`` collapses that into one
call per tick, so a host loop is just::

    autopilot = PathAutopilot(controller)
    autopilot.plan_to_tile(tx, ty)
    ...
    autopilot.advance()      # may set_input(); call at most once per step()
    controller.step()

The contract this class exists to enforce: the autopilot **never writes avatar
state**.  Planning only reads the controller (``CapabilityProfile`` /
``motion_state``) and evaluates cloned motion states on a probe world; execution
feeds only ``set_input(left, right, jump)`` and lets the host's ``step()`` -- the
physics engine -- produce the motion.  ``tests/test_path_follower.py`` pins this
with a proxy controller that raises on any attribute write.
"""

from __future__ import annotations

import math
from typing import Any

from gtools.core.growtopia.physics.pathfinding.follower import PathFollower
from gtools.core.growtopia.physics.pathfinding.pathfinder import SegmentedPathfinder
from gtools.core.growtopia.physics.pathfinding.types import MotionState, PlanResult

TILE = 32  # config import avoided: this module must not pull in the GUI stack


def _end_distance(state: MotionState, point: tuple[float, float], pathfinder: SegmentedPathfinder) -> float:
    width, height = pathfinder.profile.width, pathfinder.profile.height

    return math.hypot(state.x + width / 2.0 - point[0], state.y + height / 2.0 - point[1])


class PathAutopilot:
    def __init__(
        self,
        controller: Any,
        pathfinder: SegmentedPathfinder | None = None,
        *,
        position_tolerance: float = 1.5,
        velocity_tolerance: float = 8.0,
        replan_limit: int = 8,
        replan_budget_ms: float | None = 60.0,
        refine: bool = True,
        refine_every: int = 40,
        refine_budget_ms: float = 40.0,
    ) -> None:
        self.controller = controller
        self.pathfinder = pathfinder if pathfinder is not None else SegmentedPathfinder(controller)
        self.position_tolerance = float(position_tolerance)
        self.velocity_tolerance = float(velocity_tolerance)
        self.replan_limit = int(replan_limit)
        self.replan_budget_ms = replan_budget_ms
        # continuous refinement: while the avatar walks, the remaining route is
        # re-planned from the live state every ``refine_every`` ticks and swapped in
        # when it is cheaper.  This is what turns a rough or chunked route into a
        # good one without ever making the caller wait for a full search.
        self.refine = bool(refine)
        self.refine_every = max(1, int(refine_every))
        self.refine_budget_ms = float(refine_budget_ms)
        self.refines = 0
        self._countdown = self.refine_every

        self.result: PlanResult | None = None
        self.follower: PathFollower | None = None
        self.target: tuple[int, int] | None = None
        self.goal_point: tuple[float, float] | None = None
        self.path: Any = None
        self.status = "idle"
        self.failed = False
        self.reason = ""
        self._pending = False

    # -- state -----------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self.follower is not None

    @property
    def progress(self) -> tuple[int, int, int]:
        """``(segment index, tick inside it, segment count)`` -- for overlays/UI."""
        if self.follower is None:
            return 0, 0, 0

        return self.follower.progress

    @property
    def current_kind(self):
        return self.follower.current_kind if self.follower is not None else None

    @property
    def replans(self) -> int:
        return self.follower.replans if self.follower is not None else 0

    # -- planning --------------------------------------------------------------

    def plan_to_tile(self, tx: int, ty: int) -> PlanResult:
        tx, ty = int(tx), int(ty)

        return self._start(self.pathfinder.plan_to_tile(tx, ty), (tx, ty))

    def plan_to_xy(self, x: float, y: float, *, tolerance: float = 8.0) -> PlanResult:
        x, y = float(x), float(y)

        return self._start(self.pathfinder.plan_to_xy(x, y, tolerance=tolerance), None, goal_point=(x, y))

    def _start(self, result: PlanResult, target: tuple[int, int] | None, *, goal_point: tuple[float, float] | None = None) -> PlanResult:
        self.cancel(None)
        self.result = result
        self.target = target
        self.goal_point = goal_point if goal_point is not None else (target[0] * TILE + TILE / 2.0, target[1] * TILE + TILE / 2.0) if target else None
        self.failed = False
        self.reason = ""

        path = result.path if result.ok else None
        if path is None or not path.segments:
            self.path = None
            self.reason = result.reason or result.status.name
            self.status = f"{result.status.name}: {self.reason}"

            return result

        self.path = path
        self.status = result.status.name
        self.follower = PathFollower(
            self.controller,
            self.pathfinder,
            path,
            position_tolerance=self.position_tolerance,
            velocity_tolerance=self.velocity_tolerance,
            replan_limit=self.replan_limit,
            replan_budget_ms=self.replan_budget_ms,
        )
        self._pending = False
        self._countdown = self.refine_every

        return result

    def refine_now(self) -> bool:
        """Try to replace the remaining route with a cheaper fresh plan.

        Returns ``True`` when a better route was installed.  The new path is planned
        from the **live** state, so it already accounts for everything that happened
        (server pushes, knockback, drifting off the recorded trace).
        """
        follower = self.follower
        if follower is None or follower.done or follower.failed:
            return False

        result = self.pathfinder.plan_from_current(time_budget_ms=self.refine_budget_ms)
        if not result.ok or result.path is None or not result.path.segments:
            return False

        if not self._is_better(result.path, follower):
            return False
        if not follower.improve(result.path):
            return False

        self.refines += 1
        self.path = follower.path
        self.status = result.status.name

        return True

    def _is_better(self, candidate: Any, follower: PathFollower) -> bool:
        """Should ``candidate`` (planned from the live state) replace the rest of the route?

        Complete beats partial; between two complete routes the cheaper one wins;
        between two partial ones the one that reaches closer to the goal wins.  A
        partial route is *not* compared by cost -- its cost is only the cost of the
        chunk it covers, so it is always "cheaper" than a route that finishes the job.
        """
        current = follower.path
        candidate_complete = not candidate.partial
        current_complete = not current.partial
        if candidate_complete != current_complete:
            return candidate_complete
        if candidate_complete:
            return candidate.total_cost < follower.remaining_cost - 1.0

        point = self.goal_point
        if point is None or candidate.end is None or current.end is None:
            return False

        return _end_distance(candidate.end, point, self.pathfinder) < _end_distance(current.end, point, self.pathfinder) - 1.0

    # -- execution -------------------------------------------------------------

    def advance(self) -> bool:
        """Prepare one tick.  Returns ``True`` when the host should ``step()``.

        Call at most once per ``controller.step()``: the flag below pairs the
        input written now with the observation of the step it produced.
        """
        follower = self.follower
        if follower is None:
            return False

        if self._pending:
            self._pending = False
            follower.observe()
            self.path = follower.path
            if follower.done:
                self._finish()

                return False

            if self.refine:
                self._countdown -= 1
                if self._countdown <= 0:
                    self._countdown = self.refine_every
                    self.refine_now()

        if follower.done:
            self._finish()

            return False

        if follower.tick_inputs() is None:
            if follower.done:
                self._finish()

            return False

        self._pending = True

        return True

    def cancel(self, reason: str | None = "cancelled") -> None:
        """Stop following and reset the inputs.  Avatar state is left untouched."""
        follower = self.follower
        if follower is None:
            return

        follower.close()
        self.follower = None
        self._pending = False
        self.controller.set_input(left=False, right=False, jump=False)
        if reason is not None:
            self.status = reason
            self.reason = reason

    def _finish(self) -> None:
        follower = self.follower
        if follower is None:
            return

        self.path = follower.path
        self.failed = follower.failed
        if follower.failed:
            self.reason = follower.reason
            self.status = f"failed: {follower.reason}"
        else:
            self.reason = follower.reason
            self.status = f"goal reached ({follower.replans} replans)"

        self.cancel(None)
