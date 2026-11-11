"""Core data model for the segmented pathfinder.

Nothing in this module touches physics; it only describes motion states, input
programs, segments and plan results.  The authoritative motion state is the one
``PlayerController._simulate`` reads/writes; ``FastEvaluator`` and
``ControllerOracle`` both populate this dataclass so their results are directly
comparable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

# A frame is ``(direction, jump, ticks)``: hold ``direction`` (-1/0/+1) and
# ``jump`` for ``ticks`` fixed controller ticks.  ``jump`` edges trigger the
# controller's ``set_input`` jump action exactly like the live input layer.
InputFrame = tuple[int, bool, int]

# Structured stop predicates.  ``ActionCatalog`` tags its closures with these so
# the compiled backend can run them without crossing the Python boundary.
STOP_NONE = 0
STOP_WALK = 1
STOP_LANDING = 2


class SegmentKind(IntEnum):
    """The movement method a segment executes.

    Classification is based on the *observed* state delta, not on the action that
    was attempted, so a "jump" that lands in water becomes ``SWIM`` and a fall
    that hits a damaging tile and is launched upward becomes ``DAMAGE_LAUNCH``.
    """

    WALK = 0
    JUMP = 1
    JUMP_UP = 2
    JUMP_OVER = 3
    FALL = 4
    DROP_THROUGH = 5
    CLIMB = 6
    SWIM = 7
    SLOW_FALL = 8
    BOUNCE = 9
    BOUNCE_UP = 10
    WIND = 11
    WELL = 12
    DAMAGE_LAUNCH = 13
    DAMAGE_KNOCKBACK = 14


class Stance(IntEnum):
    GROUNDED = 0
    AIRBORNE = 1
    WATER = 2
    CLIMB = 3
    PLATFORM = 4


class PlanStatus(IntEnum):
    FOUND = 0
    PARTIAL = 1
    NO_PATH = 2
    NO_SAFE_ROUTE = 3
    BUDGET = 4
    KILLED = 5
    INVALID_GOAL = 6


@dataclass(slots=True)
class MotionState:
    """Every field ``PlayerController._simulate`` reads or writes for one avatar.

    ``permissions`` is the local ``CollisionPermissions`` copy (the mutable
    ``tile_cache`` lives there); ``flag_overrides`` models one-shot local tile
    mutations such as the steam launcher clearing ``IS_ON``.
    """

    x: float = 0.0
    y: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    frac_x: float = 0.0
    frac_y: float = 0.0

    time_ms: float = 0.0

    left: bool = False
    right: bool = False
    jump: bool = False
    jump_latch: bool = False

    facing_right: bool = True
    grounded: bool = False
    sliding: bool = False
    in_water: bool = False
    water_float: bool = False
    water_enter_ms: float = 0.0
    mud: bool = False
    left_ground: bool = False
    damage_slip: bool = False
    climbing: bool = False
    double_jumped: bool = False
    killed: bool = False

    permissions: Any = None  # CollisionPermissions (mutable tile_cache)
    flag_overrides: dict[int, int] = field(default_factory=dict)

    def clone(self) -> "MotionState":
        state = MotionState(
            x=self.x,
            y=self.y,
            vx=self.vx,
            vy=self.vy,
            frac_x=self.frac_x,
            frac_y=self.frac_y,
            time_ms=self.time_ms,
            left=self.left,
            right=self.right,
            jump=self.jump,
            jump_latch=self.jump_latch,
            facing_right=self.facing_right,
            grounded=self.grounded,
            sliding=self.sliding,
            in_water=self.in_water,
            water_float=self.water_float,
            water_enter_ms=self.water_enter_ms,
            mud=self.mud,
            left_ground=self.left_ground,
            damage_slip=self.damage_slip,
            climbing=self.climbing,
            double_jumped=self.double_jumped,
            killed=self.killed,
            permissions=_clone_permissions(self.permissions),
            flag_overrides=dict(self.flag_overrides),
        )

        return state

    def copy_from(self, other: "MotionState") -> None:
        for name in _MOTION_FIELDS:
            setattr(self, name, getattr(other, name))
        self.permissions = _clone_permissions(other.permissions)
        self.flag_overrides.clear()
        self.flag_overrides.update(other.flag_overrides)


_MOTION_FIELDS = tuple(MotionState.__dataclass_fields__)
_MOTION_FIELDS = tuple(name for name in _MOTION_FIELDS if name not in ("permissions", "flag_overrides"))


def _clone_permissions(permissions: Any) -> Any:
    if permissions is None:
        return None

    # CollisionPermissions is a slots dataclass; copy its fields explicitly so
    # the mutable set/list cannot be shared between simulated branches.
    clone = type(permissions)()
    for name in permissions.__dataclass_fields__:
        value = getattr(permissions, name)
        if isinstance(value, (set, list, dict)):
            value = value.copy()
        setattr(clone, name, value)

    return clone


@dataclass(slots=True)
class Outcome:
    """Result of evaluating one input program from a state."""

    state: MotionState
    ticks: int
    reason: str = "timeout"  # landed / water / climb / killed / timeout / goal
    damage_hits: int = 0
    bounced: bool = False
    launched: bool = False
    climbed: bool = False
    entered_water: bool = False
    used_wind: bool = False
    used_well: bool = False
    drop_through: bool = False
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    tick_trace: list[tuple[float, float, bool]] = field(default_factory=list)


@dataclass(slots=True)
class Segment:
    kind: SegmentKind
    frames: tuple[InputFrame, ...]
    start: MotionState
    end: MotionState
    ticks: int
    cost: float
    bbox: tuple[int, int, int, int]
    damage_hits: int = 0
    note: str = ""
    trace: list[tuple[float, float, bool]] = field(default_factory=list)

    @property
    def volatile(self) -> bool:
        return self.damage_hits > 0


@dataclass(slots=True)
class Path:
    segments: list[Segment] = field(default_factory=list)
    goal: tuple[int, int] = (-1, -1)
    partial: bool = False
    status: PlanStatus = PlanStatus.FOUND
    nodes_expanded: int = 0
    elapsed_ms: float = 0.0

    def __len__(self) -> int:
        return len(self.segments)

    def __iter__(self):
        return iter(self.segments)

    @property
    def total_ticks(self) -> int:
        return sum(segment.ticks for segment in self.segments)

    @property
    def total_cost(self) -> float:
        return sum(segment.cost for segment in self.segments)

    @property
    def damage_hits(self) -> int:
        return sum(segment.damage_hits for segment in self.segments)

    @property
    def start(self) -> MotionState | None:
        return self.segments[0].start if self.segments else None

    @property
    def end(self) -> MotionState | None:
        return self.segments[-1].end if self.segments else None

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        if not self.segments:
            return (0, 0, 0, 0)

        xs0, ys0, xs1, ys1 = self.segments[0].bbox
        for segment in self.segments[1:]:
            x0, y0, x1, y1 = segment.bbox
            xs0, ys0 = min(xs0, x0), min(ys0, y0)
            xs1, ys1 = max(xs1, x1), max(ys1, y1)

        return (xs0, ys0, xs1, ys1)

    def kinds(self) -> list[SegmentKind]:
        return [segment.kind for segment in self.segments]


@dataclass(slots=True)
class PlanResult:
    status: PlanStatus
    path: Path | None = None
    reason: str = ""
    nodes_expanded: int = 0
    elapsed_ms: float = 0.0
    profile_fingerprint: tuple = ()

    @property
    def ok(self) -> bool:
        """There is a route to follow -- possibly a *partial* one.

        A budget-exhausted plan still hands back the farthest progress it found
        (``BUDGET``), and the whole point of the segmented design is that the caller
        starts moving on it and re-plans from there.
        """
        return self.status in (PlanStatus.FOUND, PlanStatus.PARTIAL, PlanStatus.BUDGET) and bool(
            self.path is not None and self.path.segments
        )

    @property
    def complete(self) -> bool:
        """The route reaches the goal tile (as opposed to only making progress)."""
        return self.status is PlanStatus.FOUND and bool(self.path is not None and self.path.segments)

    @classmethod
    def failure(cls, status: PlanStatus, reason: str) -> "PlanResult":
        return cls(status=status, reason=reason)


def path_walk_frames(ticks: int = 14, settle: int = 24) -> tuple[InputFrame, ...]:
    """Convenience: one direction-agnostic walk program (dir filled in by caller)."""
    return ((0, False, ticks), (0, False, settle))
