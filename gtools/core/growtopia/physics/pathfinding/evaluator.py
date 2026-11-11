"""Bulk path scoring on the fast kernel.

``PathEvaluator`` replays a candidate path (or a suffix) from a state with early
exit: the first segment that dies, the first state that reaches a goal, or a
wrong endpoint marks the path invalid.  It is used for tie-breaks and for cheap
"is the cached suffix still valid" checks that do not need a full A* run.
"""

from __future__ import annotations

from typing import Callable

from gtools.core.growtopia.physics.pathfinding.fastkernel import FastEvaluator
from gtools.core.growtopia.physics.pathfinding.types import MotionState, Path, Segment


class PathEvaluator:
    def __init__(self, evaluator: FastEvaluator) -> None:
        self.evaluator = evaluator

    def replay(
        self,
        path: Path,
        state: MotionState | None = None,
        *,
        stop_when: Callable[[MotionState], bool] | None = None,
    ) -> MotionState:
        """Replay ``path`` from ``state`` (or its recorded start) and return the end."""
        current = state.clone() if state is not None else path.start.clone()
        for segment in path.segments:
            outcome = self.evaluator.simulate(current, segment.frames, stop_when=lambda s, t: bool(stop_when and stop_when(s)))
            current = outcome.state
            if current.killed:
                return current
            if stop_when is not None and stop_when(current):
                return current

        return current

    def score(self, path: Path, state: MotionState | None = None) -> tuple[bool, float]:
        """``(valid, cost)`` -- valid when the replay matches the final segment end."""
        end = self.replay(path, state)
        if end.killed or path.end is None:
            return False, float("inf")

        expected = path.end
        if abs(end.x - expected.x) > 0.5 or abs(end.y - expected.y) > 0.5:
            return False, float("inf")

        return True, path.total_cost

    def suffix_valid(self, segments: list[Segment], state: MotionState) -> bool:
        current = state.clone()
        for segment in segments:
            outcome = self.evaluator.simulate(current, segment.frames)
            current = outcome.state
            if current.killed:
                return False
            if abs(current.x - segment.end.x) > 0.5 or abs(current.y - segment.end.y) > 0.5:
                return False

        return True
