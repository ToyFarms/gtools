"""Segmented pathfinding for the local ``PlayerController``.

Public API::

    from gtools.core.growtopia.physics.pathfinding import (
        SegmentedPathfinder, PathFollower, Path, Segment, SegmentKind,
    )

    pathfinder = SegmentedPathfinder(controller)
    result = pathfinder.plan_to_tile(42, 10)
    if result.ok:
        follower = PathFollower(controller, pathfinder, result.path)
        while not follower.done:
            follower.step()

The design contract is ``docs/pathfinding-plan.md``; the durable reference is
``docs/pathfinding.md``.  The real controller is the authority -- ``FastEvaluator``
is its exact performance mirror and is gated by a differential fuzz suite.
"""

from gtools.core.growtopia.physics.pathfinding.actions import Action, ActionCatalog
from gtools.core.growtopia.physics.pathfinding.autopilot import PathAutopilot
from gtools.core.growtopia.physics.pathfinding.evaluator import PathEvaluator
from gtools.core.growtopia.physics.pathfinding.fastkernel import FastEvaluator
from gtools.core.growtopia.physics.pathfinding.follower import PathFollower
from gtools.core.growtopia.physics.pathfinding.oracle import ControllerOracle, motion_from_controller
from gtools.core.growtopia.physics.pathfinding.pathfinder import SegmentedPathfinder
from gtools.core.growtopia.physics.pathfinding.planner import SegmentedPlanner, tile_goal, tile_heuristic
from gtools.core.growtopia.physics.pathfinding.profile import CapabilityProfile
from gtools.core.growtopia.physics.pathfinding.snapshot import TileGrid, WorldSnapshot
from gtools.core.growtopia.physics.pathfinding.types import (
    InputFrame,
    MotionState,
    Outcome,
    Path,
    PlanResult,
    PlanStatus,
    Segment,
    SegmentKind,
    Stance,
)

__all__ = [
    "Action",
    "ActionCatalog",
    "CapabilityProfile",
    "ControllerOracle",
    "FastEvaluator",
    "InputFrame",
    "MotionState",
    "Outcome",
    "Path",
    "PathAutopilot",
    "PathEvaluator",
    "PathFollower",
    "PlanResult",
    "PlanStatus",
    "Segment",
    "SegmentKind",
    "SegmentedPathfinder",
    "SegmentedPlanner",
    "Stance",
    "TileGrid",
    "WorldSnapshot",
    "motion_from_controller",
    "tile_goal",
    "tile_heuristic",
]
