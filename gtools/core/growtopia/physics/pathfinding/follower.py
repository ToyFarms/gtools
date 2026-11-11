"""Replay and adaptation: drive the live controller through a planned path.

The follower owns the per-tick loop.  It replays exactly the input frames the
planner evaluated, checks the live avatar against the recorded trajectory, and
re-plans from the **live** state when

* the capability fingerprint changes (``SET_CHARACTER_STATE`` / clothing),
* a tile inside a remaining segment's bounding box changes (``TILE_UPDATE``),
* the live trajectory deviates from the recorded one, or
* a segment finishes in a different state than the plan predicted.

Re-planning from the live state means server pushes (``OnSetPos``, knockback,
bounce) need no special cases.
"""

from __future__ import annotations

import math
from typing import Any

from gtools.core.growtopia.physics.pathfinding.profile import CapabilityProfile
from gtools.core.growtopia.physics.pathfinding.types import InputFrame, MotionState, Segment
from gtools.core.growtopia.world import WorldEvent


class PathFollower:
    def __init__(
        self,
        controller: Any,
        pathfinder: Any,
        path: Any,
        *,
        position_tolerance: float = 1.5,
        velocity_tolerance: float = 8.0,
        replan_limit: int = 8,
        replan_budget_ms: float | None = None,
    ) -> None:
        self.controller = controller
        self.pathfinder = pathfinder
        self.path = path
        self.position_tolerance = float(position_tolerance)
        self.velocity_tolerance = float(velocity_tolerance)
        self.replan_limit = int(replan_limit)
        # replans happen *while the avatar is moving*, so they are given a smaller
        # budget than an explicit plan; refinement makes up the quality afterwards
        self.replan_budget_ms = replan_budget_ms

        self.done = False
        self.failed = False
        self.reason = ""
        self.replans = 0

        self._segments: list[Segment] = []
        self._index = 0
        self._tick = 0
        self._inputs: list[tuple[int, bool]] = []
        self._versions: list[int] = []
        self._fingerprint: tuple = ()
        self._dirty = False

        self._world = getattr(controller, "world", None)
        self._subscribed = False
        if self._world is not None and hasattr(self._world, "subscribe"):
            self._world.subscribe(WorldEvent.TILE_UPDATE, single=self._on_tile_update)
            self._subscribed = True

        self._install(path)

    # -- public ----------------------------------------------------------------

    def close(self) -> None:
        if self._subscribed and hasattr(self._world, "unsubscribe"):
            self._world.unsubscribe(WorldEvent.TILE_UPDATE, single=self._on_tile_update)
            self._subscribed = False

    def invalidate_tile(self, tx: int, ty: int) -> None:
        """Manual invalidation for worlds mutated without a ``TILE_UPDATE``."""
        self.pathfinder.invalidate_tile(tx, ty)
        self._dirty = True

    @property
    def progress(self) -> tuple[int, int, int]:
        """``(segment index, tick inside it, segment count)`` -- for overlays/UI."""
        if self.done and self._index >= len(self._segments):
            return max(0, len(self._segments) - 1), self._tick, len(self._segments)

        return self._index, self._tick, len(self._segments)

    @property
    def current_kind(self):
        """The kind of the segment being executed (``None`` once finished)."""
        if self._index >= len(self._segments):
            return None

        return self._segments[self._index].kind

    @property
    def remaining_cost(self) -> float:
        """Cost of the rest of the route from where the avatar is now.

        Comparable with a fresh plan's ``path.total_cost`` (both are ticks plus
        penalties), used to decide whether a re-plan is worth installing.
        """
        total = 0.0
        for index in range(self._index, len(self._segments)):
            total += self._segments[index].cost
            if index == self._index:
                total -= min(self._tick, self._segments[index].ticks)

        return max(0.0, total)

    def improve(self, path: Any) -> bool:
        """Install ``path`` (planned from the live state) without losing the counters.

        Used by ``PathAutopilot`` refinement: the avatar keeps moving on the frames
        it was given, and the better route simply replaces the remaining ones.
        """
        if self.done or self.failed or path is None or not path.segments:
            return False

        self._install(path)
        self._dirty = False

        return True

    def step(self) -> bool:
        """Advance one controller tick.  Returns ``self.done``."""
        if self.done:
            return True

        if self._profile_changed():
            self._replan("capability profile changed")
            return self.done

        if self._dirty:
            self._dirty = False
            if self._versions_changed():
                self._replan("world changed under the path")
                return self.done

        if self._index >= len(self._segments):
            self._finish()
            return self.done

        if self._tick >= len(self._inputs):
            self._advance_segment()
            return self.done

        direction, jump = self._inputs[self._tick]
        self.controller.set_input(left=direction < 0, right=direction > 0, jump=jump)
        self.controller.step()
        self._tick += 1

        if self._deviated():
            self._replan("trajectory deviation")
        elif self._tick >= len(self._inputs):
            self._advance_segment()

        return self.done

    def tick_inputs(self) -> tuple[bool, bool, bool] | None:
        """Apply the next input without stepping (caller owns ``controller.step``)."""
        if self.done or self._index >= len(self._segments):
            self._finish()
            return None

        direction, jump = self._inputs[self._tick]
        self._tick += 1
        self.controller.set_input(left=direction < 0, right=direction > 0, jump=jump)
        return direction < 0, direction > 0, jump

    def observe(self) -> None:
        """Check a tick the caller stepped itself (after ``tick_inputs``)."""
        if self.done:
            return
        if self._profile_changed():
            self._replan("capability profile changed")
        elif self._deviated():
            self._replan("trajectory deviation")
        elif self._tick >= len(self._inputs):
            self._advance_segment()

    # -- internals -------------------------------------------------------------

    def _install(self, path: Any) -> None:
        self.path = path
        self._segments = list(path.segments)
        self._index = 0
        self._tick = 0
        self._inputs = []
        self._versions = [self.pathfinder.snapshot.max_version_in_bbox(segment.bbox) for segment in self._segments]
        self._fingerprint = self.pathfinder.profile.fingerprint()
        self._load_segment()

    def _load_segment(self) -> None:
        if self._index >= len(self._segments):
            self._inputs = []
            return

        self._tick = 0
        segment = self._segments[self._index]
        self._inputs = _expand_frames(segment.frames)

    def _on_tile_update(self, tx: int, ty: int) -> None:
        self.pathfinder.invalidate_tile(tx, ty)
        self._dirty = True

    def _profile_changed(self) -> bool:
        try:
            return CapabilityProfile.from_controller(self.controller).fingerprint() != self._fingerprint
        except Exception:
            return False

    def _versions_changed(self) -> bool:
        snapshot = self.pathfinder.snapshot
        for segment, version in zip(self._segments[self._index :], self._versions[self._index :]):
            if snapshot.max_version_in_bbox(segment.bbox) > version:
                return True
        return False

    def _deviated(self) -> bool:
        segment = self._segments[self._index]
        if self._tick - 1 >= len(segment.trace):
            return False
        x, y, grounded = segment.trace[self._tick - 1]
        if abs(self.controller.x - x) > self.position_tolerance or abs(self.controller.y - y) > self.position_tolerance:
            return True
        return bool(self.controller.grounded) != bool(grounded) and self._tick > 2

    def _advance_segment(self) -> None:
        segment = self._segments[self._index]
        if not _state_close(
            self.controller,
            segment.end,
            position=self.position_tolerance,
            velocity=self.velocity_tolerance,
        ):
            self._replan("segment ended in an unexpected state")
            return

        self._index += 1
        self._load_segment()
        if self._index >= len(self._segments):
            self._finish()

    def _finish(self) -> None:
        state = self.pathfinder.motion_state()
        if self.pathfinder.goal_reached(state):
            self.done = True
            self.failed = False
            self.reason = "goal reached"
        else:
            self._replan("path exhausted before the goal")

    def _replan(self, reason: str) -> None:
        if self.replans >= self.replan_limit:
            self.done = True
            self.failed = True
            self.reason = f"replan limit reached: {reason}"
            return

        self.replans += 1
        result = self.pathfinder.plan_from_current(time_budget_ms=self.replan_budget_ms)
        if not result.ok or result.path is None or not result.path.segments:
            self.done = True
            self.failed = True
            self.reason = f"{reason}: {result.reason or result.status.name}"
            return

        self._install(result.path)


# -- helpers -------------------------------------------------------------------


def _expand_frames(frames: tuple[InputFrame, ...]) -> list[tuple[int, bool]]:
    expanded: list[tuple[int, bool]] = []
    for direction, jump, count in frames:
        expanded.extend([(direction, jump)] * max(0, int(count)))
    return expanded


def _state_close(controller: Any, expected: MotionState, *, position: float, velocity: float) -> bool:
    if abs(controller.x - expected.x) > position or abs(controller.y - expected.y) > position:
        return False
    if abs(controller.vx - expected.vx) > max(velocity, abs(expected.vx) * 0.05):
        return False
    if abs(controller.vy - expected.vy) > max(velocity, abs(expected.vy) * 0.05):
        return False
    for name in ("grounded", "sliding", "in_water", "climbing"):
        if bool(getattr(controller, name)) != bool(getattr(expected, name)):
            return False
    return True


def _distance(controller: Any, expected: MotionState) -> float:
    return math.hypot(controller.x - expected.x, controller.y - expected.y)
