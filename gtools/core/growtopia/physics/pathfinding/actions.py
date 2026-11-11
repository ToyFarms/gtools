"""Action catalogue: turn a ``MotionState`` into candidate movement segments.

The catalogue is deliberately small and analytic.  Each action is an input
program (``(direction, jump, ticks)`` frames) plus an optional stop predicate;
the program is executed by ``FastEvaluator`` and the resulting state delta is
**classified after the fact**.  That is why a "jump right" that lands in water
becomes ``SWIM`` and a fall that touches a damaging tile and is launched upward
becomes ``DAMAGE_LAUNCH`` -- segment kinds describe what happened, not what was
attempted.

Nothing here hard-codes a motion value: hold times, air times and search extents
are derived from the live ``CapabilityProfile``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from gtools.core.growtopia.physics.controller import TILE
from gtools.core.growtopia.physics.pathfinding.fastkernel import FastEvaluator
from gtools.core.growtopia.physics.pathfinding.profile import CapabilityProfile
from gtools.core.growtopia.physics.pathfinding.snapshot import WorldSnapshot
from gtools.core.growtopia.physics.pathfinding.types import (
    STOP_LANDING,
    STOP_WALK,
    InputFrame,
    MotionState,
    Outcome,
    Segment,
    SegmentKind,
)

StopPredicate = Callable[[MotionState, int], bool]


@dataclass(slots=True)
class Action:
    """One named input program plus its early-stop rule."""

    name: str
    frames: tuple[InputFrame, ...]
    stop: StopPredicate | None = None
    max_ticks: int | None = None
    penalty: float = 0.0


class ActionCatalog:
    """Generates and evaluates movement actions from a live state."""

    def __init__(
        self,
        evaluator: FastEvaluator,
        *,
        damage_penalty: float = 24.0,
        walk_tiles: int = 4,
        max_air_ticks: int | None = None,
    ) -> None:
        self.evaluator = evaluator
        self.profile = evaluator.profile
        self.snapshot: WorldSnapshot = evaluator.snapshot
        self.damage_penalty = float(damage_penalty)
        self.walk_tiles = max(1, int(walk_tiles))
        self.max_air_ticks = max_air_ticks
        self.killed_candidates = 0

    # -- tuning derived from the profile --------------------------------------

    @property
    def ticks_per_tile(self) -> float:
        speed = max(self.profile.max_velocity * self.profile.dt, 1e-9)
        return TILE / speed

    @property
    def walk_ticks(self) -> int:
        return int(math.ceil(self.ticks_per_tile * self.walk_tiles + 4))

    @property
    def air_ticks(self) -> int:
        if self.max_air_ticks is not None:
            return self.max_air_ticks

        return int(math.ceil(self.profile.jump_airtime_ticks * 2.0 + 30.0))

    @property
    def hold_ticks(self) -> int:
        return max(1, int(round(self.profile.jump_airtime_ticks)))

    @property
    def cut_ticks(self) -> int:
        return max(1, int(round(self.profile.jump_airtime_ticks * 0.3)))

    @property
    def paddle_ticks(self) -> int:
        return max(2, int(math.ceil(self.profile.jump_airtime_ticks * 0.5)) + 4)

    # -- candidate generation --------------------------------------------------

    def candidates(self, state: MotionState) -> list[Segment]:
        """All actions worth evaluating from ``state`` (killed states -> none)."""
        segments: list[Segment] = []
        for action in self.actions(state):
            segment = self.evaluate(state, action)
            if segment is not None:
                segments.append(segment)

        return segments

    def actions(self, state: MotionState) -> list[Action]:
        """The candidate actions for ``state``'s stance (no evaluation yet)."""
        if state.killed:
            return []

        actions: list[Action] = []
        self.killed_candidates = 0
        if state.climbing:
            actions.extend(self._climb_actions(state))
        elif state.in_water:
            actions.extend(self._water_actions(state))
        elif state.grounded:
            actions.extend(self._ground_actions(state))
        else:
            actions.extend(self._air_actions(state))

        unique: list[Action] = []
        seen: set[str] = set()
        for action in actions:
            if action.name in seen:
                continue
            seen.add(action.name)
            unique.append(action)

        return unique

    # -- action families -------------------------------------------------------

    def _release(self, state: MotionState, direction: int) -> tuple[InputFrame, ...]:
        """A release tick when the current state still holds jump."""
        return ((direction, False, 1),) if state.jump else ()

    def _ground_actions(self, state: MotionState) -> list[Action]:
        actions: list[Action] = []
        for direction in (-1, 0, 1):
            if direction:
                actions.append(Action(f"walk:{direction}", ((direction, False, self.walk_ticks),), self._walk_stop(direction)))
            for hold_name, hold in (("cut", self.cut_ticks), ("full", self.hold_ticks)):
                frames = self._release(state, direction) + ((direction, True, hold), (direction, False, self.air_ticks))
                actions.append(Action(f"jump:{hold_name}:{direction}", frames, self._landing_stop(hold), max_ticks=hold + self.air_ticks, penalty=1.0))
                if self.profile.has_double_jump:
                    frames = (
                        self._release(state, direction)
                        + ((direction, True, hold), (direction, False, max(2, self.cut_ticks)), (direction, True, hold), (direction, False, self.air_ticks))
                    )
                    actions.append(Action(f"jump2:{hold_name}:{direction}", frames, self._landing_stop(hold * 2 + 2), penalty=1.5))
        actions.append(Action("wait", ((0, False, 12),), None))
        return actions

    def _air_actions(self, state: MotionState) -> list[Action]:
        actions: list[Action] = []
        for direction in (-1, 0, 1):
            actions.append(Action(f"air:{direction}", ((direction, False, self.air_ticks),), self._landing_stop(0), penalty=0.25))
            if self.profile.slow_fall:
                frames = self._release(state, direction) + ((direction, True, self.air_ticks),)
                actions.append(Action(f"glide:{direction}", frames, self._landing_stop(0), penalty=0.5))
            if self.profile.has_double_jump and not state.double_jumped:
                frames = self._release(state, direction) + ((direction, True, self.hold_ticks), (direction, False, self.air_ticks))
                actions.append(Action(f"jump2_air:{direction}", frames, self._landing_stop(self.hold_ticks), penalty=1.5))
        return actions

    def _water_actions(self, state: MotionState) -> list[Action]:
        actions: list[Action] = []
        for direction in (-1, 0, 1):
            actions.append(Action(f"swim:{direction}", ((direction, False, self.air_ticks),), self._landing_stop(0)))
            frames = self._release(state, direction) + ((direction, True, 1), (direction, False, self.paddle_ticks))
            actions.append(Action(f"paddle:{direction}", frames, self._landing_stop(1), penalty=0.5))
        return actions

    def _climb_actions(self, state: MotionState) -> list[Action]:
        actions: list[Action] = [Action("hang", ((0, False, 8),), None)]
        for direction in (-1, 0, 1):
            frames = self._release(state, direction) + ((direction, True, self.cut_ticks), (direction, False, self.air_ticks))
            actions.append(Action(f"climb_jump:{direction}", frames, self._landing_stop(self.cut_ticks), penalty=1.0))
        return actions

    # -- stop rules ------------------------------------------------------------

    def _walk_stop(self, direction: int) -> StopPredicate:
        previous = [None]

        def stop(state: MotionState, ticks: int) -> bool:
            if state.killed or state.climbing or state.in_water:
                return True
            if ticks <= 1:
                previous[0] = state.x
                return False
            stuck = abs(state.x - (previous[0] or state.x)) < 0.5
            previous[0] = state.x
            return (not state.grounded) or stuck

        # the compiled backend runs this rule natively; keep the closure too
        stop._nb_stop = (STOP_WALK, 0)
        return stop

    def _landing_stop(self, after: int) -> StopPredicate:
        grounded_ticks = [0]

        def stop(state: MotionState, ticks: int) -> bool:
            if state.killed or state.climbing or state.in_water:
                return True
            if ticks <= after:
                grounded_ticks[0] = 0
                return False
            if state.grounded:
                # include one settle tick: hazard/bounce responses land *after*
                # the tick that grounds the avatar
                grounded_ticks[0] += 1
                return grounded_ticks[0] >= 2
            grounded_ticks[0] = 0
            return False

        stop._nb_stop = (STOP_LANDING, int(after))
        return stop

    # -- evaluation + classification ------------------------------------------

    def evaluate(self, state: MotionState, action: Action) -> Segment | None:
        origin = state.clone()
        start = state.clone()
        outcome = self.evaluator.simulate(
            start,
            action.frames,
            max_ticks=action.max_ticks,
            stop_when=action.stop,
            record_trace=True,
        )
        if outcome.state.killed or outcome.ticks == 0:
            if outcome.state.killed:
                self.killed_candidates += 1
            return None

        kind = self.classify(outcome, origin, action)
        cost = outcome.ticks + action.penalty + outcome.damage_hits * self.damage_penalty

        return Segment(
            kind=kind,
            frames=_truncate(action.frames, outcome.ticks),
            start=origin,
            end=outcome.state,
            ticks=outcome.ticks,
            cost=cost,
            bbox=outcome.bbox,
            damage_hits=outcome.damage_hits,
            note=action.name,
            trace=outcome.tick_trace,
        )

    def classify(self, outcome: Outcome, start: MotionState, action: Action) -> SegmentKind:
        end = outcome.state
        if outcome.climbed or end.climbing:
            return SegmentKind.CLIMB
        if outcome.bounced:
            return SegmentKind.BOUNCE
        if outcome.damage_hits and outcome.launched:
            return SegmentKind.DAMAGE_LAUNCH
        if outcome.launched:
            return SegmentKind.BOUNCE_UP
        if end.in_water:
            return SegmentKind.SWIM
        if outcome.used_well and not end.grounded:
            return SegmentKind.WELL
        if outcome.used_wind and abs(end.x - start.x) > 1.0:
            return SegmentKind.WIND
        if not end.grounded:
            return SegmentKind.SLOW_FALL if self.profile.slow_fall and end.vy > 0.0 and end.jump else SegmentKind.FALL
        if end.y < start.y - 0.5:
            return SegmentKind.JUMP_UP
        if end.y > start.y + 0.5:
            return SegmentKind.FALL
        if abs(end.x - start.x) > 0.5:
            return SegmentKind.JUMP_OVER if action.name.startswith(("jump", "paddle", "climb_jump")) else SegmentKind.WALK
        return SegmentKind.WALK


def _truncate(frames: tuple[InputFrame, ...], ticks: int) -> tuple[InputFrame, ...]:
    """Keep only the frames (and partial frame) the program actually executed."""
    kept: list[InputFrame] = []
    remaining = ticks
    for direction, jump, count in frames:
        if remaining <= 0:
            break
        take = min(int(count), remaining)
        if take > 0:
            kept.append((direction, jump, take))
            remaining -= take

    return tuple(kept)


def node_key(state: MotionState, height: float, *, tile: float = TILE) -> tuple[int, int, int]:
    """Tile-scale perch key: left column, feet row and a stance discriminator."""
    tx = math.floor(state.x / tile)
    feet = math.floor((state.y + height - 1e-4) / tile)
    return tx, feet, stance_of(state)


def stance_of(state: MotionState) -> int:
    if state.climbing:
        return 1
    if state.in_water:
        return 2
    if state.grounded:
        return 0
    return 3
