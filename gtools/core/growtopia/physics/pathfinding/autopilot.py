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

from typing import Any

from gtools.core.growtopia.physics.pathfinding.follower import PathFollower
from gtools.core.growtopia.physics.pathfinding.pathfinder import SegmentedPathfinder
from gtools.core.growtopia.physics.pathfinding.types import PlanResult


class PathAutopilot:
    def __init__(
        self,
        controller: Any,
        pathfinder: SegmentedPathfinder | None = None,
        *,
        position_tolerance: float = 1.5,
        velocity_tolerance: float = 8.0,
        replan_limit: int = 8,
    ) -> None:
        self.controller = controller
        self.pathfinder = pathfinder if pathfinder is not None else SegmentedPathfinder(controller)
        self.position_tolerance = float(position_tolerance)
        self.velocity_tolerance = float(velocity_tolerance)
        self.replan_limit = int(replan_limit)

        self.result: PlanResult | None = None
        self.follower: PathFollower | None = None
        self.target: tuple[int, int] | None = None
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
        return self._start(self.pathfinder.plan_to_tile(int(tx), int(ty)), (int(tx), int(ty)))

    def plan_to_xy(self, x: float, y: float, *, tolerance: float = 8.0) -> PlanResult:
        return self._start(self.pathfinder.plan_to_xy(x, y, tolerance=tolerance), None)

    def _start(self, result: PlanResult, target: tuple[int, int] | None) -> PlanResult:
        self.cancel(None)
        self.result = result
        self.target = target
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
        )
        self._pending = False

        return result

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
