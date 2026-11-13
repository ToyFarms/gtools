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
    # "plain" runs ``frames`` as given; "edge" runs them and then *un-does the tick
    # that left the ground* (stop at the ledge, still grounded); "align" searches the
    # push duration that brings the avatar to rest at ``target_x``
    kind: str = "plain"
    target_x: float = 0.0
    direction: int = 0


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
        # planner-supplied callback: ``hints(state) -> list[int]`` of tile columns worth
        # lining up on from this (grounded) state -- the goal column, the column of a
        # hole in the ceiling... ``None`` disables aligned stops
        self.hints: Callable[[MotionState], list[int]] | None = None
        # planner-supplied callback: ``prefer(state) -> (-1,)|(1,)|(-1, 1)``, the horizontal
        # directions the guidance says are worth the *speculative* air variants (steer,
        # delayed double jump).  ``None`` means both.
        self.prefer: Callable[[MotionState], tuple[int, ...]] | None = None

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
    def run_ticks(self) -> int:
        """Upper bound of one ``run`` (24 tiles of walking)."""
        return int(math.ceil(self.ticks_per_tile * 24 + 8))

    @property
    def swim_ticks(self) -> int:
        """One swim step.  Water is slow, so steps are short: the search steers in them."""
        return 8

    @property
    def paddle_ticks(self) -> int:
        return max(2, int(math.ceil(self.profile.jump_airtime_ticks * 0.5)) + 4)

    @property
    def jump_ladder(self) -> tuple[tuple[str, int, float], ...]:
        """``(action suffix, jump-hold ticks, penalty)``, from a hop to a full jump.

        The jump is cut when the button is released (``JUMP_CUT_ACCEL``), so the
        arc height scales with the hold: a 1-tick hold peaks ~26 px above the
        ground and a 4-tick hold ~41 px, while ``cut`` and ``full`` peak ~88/101 px
        on the default profile.  The short holds are what lets a route cross a
        short gap under a low ceiling instead of walking the long way around it.

        Hops carry a smaller penalty than a full jump: the tie between "hop" and
        "walk the same distance" still breaks towards walking (a hop is no faster
        over flat ground), but a hop that genuinely saves ticks -- a gap -- wins.
        """
        ladder: list[tuple[str, int, float]] = []
        seen: set[int] = set()
        for name, hold, penalty in (
            ("hop", 1, 0.25),
            ("hop", 4, 0.25),
            ("cut", self.cut_ticks, 0.5),
            ("full", self.hold_ticks, 1.0),
        ):
            hold = max(1, int(hold))
            if hold in seen:
                continue
            seen.add(hold)
            ladder.append((f"{name}{hold}" if name == "hop" else name, hold, penalty))

        return tuple(ladder)

    # -- candidate generation --------------------------------------------------

    def candidates(self, state: MotionState, *, full: bool = True) -> list[Segment]:
        """All actions worth evaluating from ``state`` (killed states -> none)."""
        segments: list[Segment] = []
        for action in self.actions(state, full=full):
            segment = self.evaluate(state, action)
            if segment is not None:
                segments.append(segment)

        return segments

    def actions(self, state: MotionState, *, full: bool = True) -> list[Action]:
        """The candidate actions for ``state``'s stance (no evaluation yet).

        ``full=False`` selects the **cheap tier**: ground moves and the jump
        ladder, without the double-jump / glide / paddle / wait variants.  Those
        are the actions that cost the most physics per evaluation (a double jump
        averages ~90 simulated ticks), and the planner's first rough pass uses the
        cheap tier so it reaches a complete route quickly; the refinement passes
        then run the full set with the incumbent as an upper bound.
        """
        if state.killed:
            return []

        actions: list[Action] = []
        self.killed_candidates = 0
        if state.climbing:
            actions.extend(self._climb_actions(state, full))
        elif state.in_water:
            actions.extend(self._water_actions(state, full))
        elif state.grounded:
            actions.extend(self._ground_actions(state, full))
        else:
            actions.extend(self._air_actions(state, full))

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

    def _ground_actions(self, state: MotionState, full: bool = True) -> list[Action]:
        actions: list[Action] = []
        for direction in (-1, 0, 1):
            if direction:
                actions.append(Action(f"walk:{direction}", ((direction, False, self.walk_ticks),), self._walk_stop(direction)))
                # run to the end of the platform: one edge instead of a chain of 4-tile
                # walks (a 100-tile corridor used to be 25 expansions)
                actions.append(
                    Action(
                        f"run:{direction}",
                        ((direction, False, self.run_ticks),),
                        self._walk_stop(direction),
                        max_ticks=self.run_ticks,
                        kind="edge",
                        direction=direction,
                    )
                )
            for hold_name, hold, penalty in self.jump_ladder:
                frames = self._release(state, direction) + ((direction, True, hold), (direction, False, self.air_ticks))
                actions.append(
                    Action(f"jump:{hold_name}:{direction}", frames, self._landing_stop(hold), max_ticks=hold + self.air_ticks, penalty=penalty)
                )
                if full and direction:
                    # the launch alone: ends in the air so the *search* can steer the
                    # rest (release the direction early, double-jump the other way...)
                    actions.append(
                        Action(
                            f"launch:{hold_name}:{direction}",
                            self._release(state, direction) + ((direction, True, hold),),
                            None,
                            max_ticks=hold + (1 if state.jump else 0),
                            penalty=penalty,
                        )
                    )
                if full and direction == 0 and hold_name in ("cut", "full"):
                    actions.append(
                        Action(
                            f"launch:{hold_name}:0",
                            self._release(state, 0) + ((0, True, hold),),
                            None,
                            max_ticks=hold + (1 if state.jump else 0),
                            penalty=penalty,
                        )
                    )
                # a double jump only extends ``cut``/``full``: a double hop adds
                # little the single hops do not already cover, and it is the most
                # expensive action in the catalogue to simulate
                if full and self.profile.has_double_jump and hold_name in ("cut", "full"):
                    frames = (
                        self._release(state, direction)
                        + ((direction, True, hold), (direction, False, max(2, self.cut_ticks)), (direction, True, hold), (direction, False, self.air_ticks))
                    )
                    actions.append(Action(f"jump2:{hold_name}:{direction}", frames, self._landing_stop(hold * 2 + 2), penalty=1.5))
        if self.hints is not None:
            for column in self.hints(state):
                target = column * TILE + TILE / 2.0 - self.profile.width / 2.0
                delta = target - state.x
                if abs(delta) < 1.5:
                    continue
                direction = 1 if delta > 0 else -1
                actions.append(
                    Action(f"align:{column}", ((direction, False, 1),), None, kind="align", target_x=target, direction=direction)
                )
        if full:
            actions.append(Action("wait", ((0, False, 12),), None))
        return actions

    def _air_actions(self, state: MotionState, full: bool = True) -> list[Action]:
        actions: list[Action] = []
        sides = self.prefer(state) if self.prefer is not None else (-1, 1)
        for direction in (-1, 0, 1):
            actions.append(Action(f"air:{direction}", ((direction, False, self.air_ticks),), self._landing_stop(0), penalty=0.25))
            if full and direction and direction in sides:
                # push for a while, then let go: the avatar drifts to a stop instead
                # of carrying full speed onto a short platform
                for push in (4, 9, 16):
                    frames = self._release(state, direction) + ((direction, False, push), (0, False, self.air_ticks))
                    actions.append(Action(f"steer:{direction}:{push}", frames, self._landing_stop(0), penalty=0.3))
            if full and self.profile.slow_fall:
                frames = self._release(state, direction) + ((direction, True, self.air_ticks),)
                actions.append(Action(f"glide:{direction}", frames, self._landing_stop(0), penalty=0.5))
            if full and self.profile.has_double_jump and not state.double_jumped:
                frames = self._release(state, direction) + ((direction, True, self.hold_ticks), (direction, False, self.air_ticks))
                actions.append(Action(f"jump2_air:{direction}", frames, self._landing_stop(self.hold_ticks), penalty=1.5))
        if full and self.profile.has_double_jump and not state.double_jumped and state.vy < 0.0:
            # a *delayed* double jump (only while still rising: once falling, ``jump2_air`` covers it) whose horizontal intent differs from the first
            # jump's -- go up, then commit sideways (the human route under a low ceiling)
            hold = self.hold_ticks
            for lead in sides:
                for gap in (6, 16):
                    for d1, d2 in ((0, lead), (lead, lead), (lead, 0)):
                        frames = self._release(state, d1) + ((d1, False, gap), (d2, True, hold), (d2, False, self.air_ticks))
                        actions.append(
                            Action(f"dj:{d1}:{gap}:{d2}", frames, self._landing_stop(gap + hold), penalty=1.5)
                        )
            for gap in (6, 16):
                frames = self._release(state, 0) + ((0, False, gap), (0, True, hold), (0, False, self.air_ticks))
                actions.append(Action(f"dj:0:{gap}:0", frames, self._landing_stop(gap + hold), penalty=1.5))
        return actions

    def _water_actions(self, state: MotionState, full: bool = True) -> list[Action]:
        """Short swim *steps* (a few ticks), never terminal on ``in_water``.

        The old rule ended every water action on the first tick because it stopped
        whenever the avatar was in water -- so every swim edge was a one-tick segment
        that landed in its parent's search bucket and was discarded.  A step runs a
        fixed number of ticks and the search chains them, steering at every step.
        """
        actions: list[Action] = []
        k = self.swim_ticks
        for direction in (-1, 0, 1):
            actions.append(Action(f"swim:{direction}", ((direction, False, k),), None, max_ticks=k))
            actions.append(
                Action(
                    f"swimup:{direction}",
                    self._release(state, direction) + ((direction, True, k),),
                    None,
                    max_ticks=k + (1 if state.jump else 0),
                    penalty=0.25,
                )
            )
            if full:
                frames = self._release(state, direction) + ((direction, True, 1), (direction, False, self.paddle_ticks))
                actions.append(Action(f"paddle:{direction}", frames, None, max_ticks=1 + self.paddle_ticks + (1 if state.jump else 0), penalty=0.5))
                frames = self._release(state, direction) + ((direction, True, 24), (direction, False, 4))
                actions.append(Action(f"stroke:{direction}", frames, None, max_ticks=28 + (1 if state.jump else 0), penalty=0.5))
        return actions

    def _climb_actions(self, state: MotionState, full: bool = True) -> list[Action]:
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

    def evaluate(self, state: MotionState, action: Action, *, record_trace: bool = True) -> Segment | None:
        """Run ``action`` from ``state``; ``None`` when it kills, makes no progress or is invalid.

        ``record_trace=False`` skips the per-tick ``(x, y, grounded)`` list: the search
        only needs the end state, and the planner re-simulates the few segments it keeps.
        """
        origin = state  # nodes are never mutated: every run below works on a clone
        if action.kind == "align":
            resolved = self._resolve_align(origin, action)
            if resolved is None:
                return None
            action = resolved

        outcome = self.evaluator.simulate(
            state.clone(),
            action.frames,
            max_ticks=action.max_ticks,
            stop_when=action.stop,
            record_trace=record_trace,
        )
        if outcome.state.killed or outcome.ticks == 0:
            if outcome.state.killed:
                self.killed_candidates += 1
            return None

        if action.kind == "edge" and not outcome.state.grounded and not outcome.state.climbing and not outcome.state.in_water:
            # the run walked off the platform: stand on its very edge instead
            keep = outcome.ticks - 1
            if keep <= 0:
                return None
            outcome = self.evaluator.simulate(state.clone(), action.frames, max_ticks=keep, record_trace=record_trace)
            if outcome.state.killed or outcome.ticks == 0:
                return None

        kind = self.classify(outcome, origin, action)
        cost = outcome.ticks + action.penalty + outcome.damage_hits * self.damage_penalty

        return Segment(
            kind=kind,
            frames=truncate_frames(action.frames, outcome.ticks),
            start=origin,
            end=outcome.state,
            ticks=outcome.ticks,
            cost=cost,
            bbox=outcome.bbox,
            damage_hits=outcome.damage_hits,
            note=action.name,
            trace=outcome.tick_trace,
        )

    def _resolve_align(self, state: MotionState, action: Action) -> Action | None:
        """Find the push length that brings the avatar to rest on ``action.target_x``.

        The final x is monotone in the push length, so a bisection over it needs a handful
        of kernel runs.  The result is verified: it is only offered when the avatar ends
        within 3 px of the target, grounded, and not dead.
        """
        direction = action.direction
        distance = abs(action.target_x - state.x)
        speed = max(self.profile.max_velocity * self.profile.dt, 1e-9)
        hi = int(math.ceil(distance / speed)) + 24
        lo = 1
        settle = int(math.ceil(self.profile.max_velocity / max(self.profile.horizontal_accel * self.profile.dt, 1e-9))) + 6

        def run(push: int):
            frames = ((direction, False, push), (0, False, settle))
            outcome = self.evaluator.simulate(state.clone(), frames, stop_when=self._walk_stop(direction), max_ticks=push + settle)
            return frames, outcome

        best: tuple[float, tuple, Outcome] | None = None
        while lo <= hi:
            mid = (lo + hi) // 2
            frames, outcome = run(mid)
            end = outcome.state
            if end.killed or not end.grounded:
                hi = mid - 1
                continue
            error = (end.x - action.target_x) * direction
            if best is None or abs(error) < best[0]:
                best = (abs(error), frames, outcome)
            if error > 0:
                hi = mid - 1
            else:
                lo = mid + 1

        if best is None or best[0] > 3.0:
            return None

        _, frames, outcome = best
        return Action(
            action.name,
            truncate_frames(frames, outcome.ticks),
            None,
            max_ticks=outcome.ticks,
            penalty=0.0,
            kind="plain",
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
        if not end.grounded and end.vy < 0.0 and not end.in_water:
            return SegmentKind.JUMP
        if not end.grounded:
            return SegmentKind.SLOW_FALL if self.profile.slow_fall and end.vy > 0.0 and end.jump else SegmentKind.FALL
        if end.y < start.y - 0.5:
            return SegmentKind.JUMP_UP
        if end.y > start.y + 0.5:
            return SegmentKind.FALL
        if abs(end.x - start.x) > 0.5:
            return SegmentKind.JUMP_OVER if action.name.startswith(("jump", "paddle", "climb_jump")) else SegmentKind.WALK
        return SegmentKind.WALK


def truncate_frames(frames: tuple[InputFrame, ...], ticks: int) -> tuple[InputFrame, ...]:
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


def node_key(state: MotionState, height: float, *, tile: float = TILE) -> tuple:
    """Search bucket of a state.

    The first three entries stay ``(left tile column, feet row, stance)`` (the demo
    draws them); the rest refine the bucket so that *distinct* states are not merged.
    A bucket the size of a tile used to keep only the cheapest arrival, silently
    dropping the state that stood on a ledge's last pixel -- exactly the one a gap
    jump needs -- and every state with a different velocity or double-jump token.
    """
    tx = math.floor(state.x / tile)
    feet = math.floor((state.y + height - 1e-4) / tile)
    stance = stance_of(state)
    vcls = 0 if abs(state.vx) < 30.0 else (1 if state.vx > 0 else -1)
    if stance in (0, 1):  # grounded / climbing: x to 4 px, velocity class
        return (tx, feet, stance, int(state.x // 4), vcls, int(state.double_jumped), int(state.sliding))
    if stance == 2:  # water
        vy = 0 if abs(state.vy) < 30.0 else (1 if state.vy > 0 else -1)
        return (tx, feet, stance, int(state.x // 6), int(state.y // 6), vcls, vy, int(state.jump_latch), int(state.water_float))
    return (
        tx,
        feet,
        stance,
        int(state.x // 6),
        int(state.y // 6),
        int(state.vx // 80),
        int(state.vy // 80),
        int(state.jump_latch),
        int(state.double_jumped),
        int(state.left_ground),
    )


def stance_of(state: MotionState) -> int:
    if state.climbing:
        return 1
    if state.in_water:
        return 2
    if state.grounded:
        return 0
    return 3
