"""Segmented A* over tile-scale perch nodes.

Nodes are ``(tile_x, feet_row, stance)``; every edge is a fully evaluated
movement ``Segment`` (the catalogue ran the physics), so the search never guesses
a trajectory.  ``g`` is the segment cost (ticks + explicit penalties + damage
hits), ``h`` is an admissible horizontal lower bound derived from the live
profile.

Deadly tiles are terminal: any action that latches ``killed`` is dropped before
it becomes an edge.  Damaging tiles are ordinary edges priced by their hits.
"""

from __future__ import annotations

import heapq
import itertools
import time
from dataclasses import dataclass
from typing import Callable

from gtools.core.growtopia.physics.controller import TILE
from gtools.core.growtopia.physics.pathfinding.actions import ActionCatalog, node_key
from gtools.core.growtopia.physics.pathfinding.profile import CapabilityProfile
from gtools.core.growtopia.physics.pathfinding.snapshot import WorldSnapshot
from gtools.core.growtopia.physics.pathfinding.types import (
    MotionState,
    Path,
    PlanResult,
    PlanStatus,
    Segment,
)

Goal = Callable[[MotionState], bool]
Heuristic = Callable[[MotionState], float]


@dataclass(slots=True)
class _Node:
    key: tuple
    state: MotionState
    g: float
    damage_hits: int
    # parent is the *node object*, never its key: a tile key buckets several
    # exact states, and replacing ``nodes[key]`` with a cheaper state would
    # otherwise break the exact start/end chain of already-expanded children
    parent: "_Node | None"
    segment: Segment | None
    depth: int = 0


class SegmentedPlanner:
    """A* over movement segments with budgets and an edge cache."""

    def __init__(
        self,
        catalog: ActionCatalog,
        profile: CapabilityProfile,
        snapshot: WorldSnapshot,
        *,
        max_expansions: int = 4000,
        time_budget_ms: float = 250.0,
        max_damage_hits: int | None = None,
        max_segments: int = 64,
        edge_cache: dict | None = None,
        heuristic_weight: float = 1.5,
    ) -> None:
        self.catalog = catalog
        self.profile = profile
        self.snapshot = snapshot
        self.max_expansions = int(max_expansions)
        self.time_budget_ms = float(time_budget_ms)
        self.max_damage_hits = max_damage_hits
        self.max_segments = int(max_segments)
        self.edge_cache = edge_cache if edge_cache is not None else {}
        self._fingerprint = profile.fingerprint()
        # weighted A*: inflating ``h`` trades bounded suboptimality for a much
        # smaller expansion count (a 150-tile corridor: 196 -> 22 nodes for a
        # +0.4 % path length).  1.0 restores plain admissible A*.
        self.heuristic_weight = max(1.0, float(heuristic_weight))

    # -- cache -----------------------------------------------------------------

    def _cache_key(self, state: MotionState, action_name: str) -> tuple:
        return (
            state.x,
            state.y,
            state.vx,
            state.vy,
            state.frac_x,
            state.frac_y,
            state.grounded,
            state.sliding,
            state.in_water,
            state.water_float,
            state.mud,
            state.left_ground,
            state.damage_slip,
            state.climbing,
            state.double_jumped,
            state.jump,
            action_name,
        )

    def _cached(self, state: MotionState, action_name: str) -> Segment | None:
        entry = self.edge_cache.get(self._cache_key(state, action_name))
        if entry is None:
            return None
        segment, version = entry
        if self.snapshot.max_version_in_bbox(segment.bbox) > version:
            return None
        return segment

    def _store(self, state: MotionState, action_name: str, segment: Segment) -> None:
        version = self.snapshot.max_version_in_bbox(segment.bbox)
        self.edge_cache[self._cache_key(state, action_name)] = (segment, version)

    # -- search ----------------------------------------------------------------

    def plan(self, start: MotionState, goal: Goal, heuristic: Heuristic) -> PlanResult:
        begun = time.perf_counter()
        if start.killed:
            return PlanResult.failure(PlanStatus.KILLED, "start state is dead")

        root_key = node_key(start, self.profile.height)
        root = _Node(root_key, start, 0.0, 0, None, None)
        nodes: dict[tuple, _Node] = {root_key: root}
        counter = itertools.count()
        weight = self.heuristic_weight
        heap: list[tuple[float, float, int, tuple]] = [(heuristic(start) * weight, 0.0, next(counter), root_key)]
        expanded = 0
        closest = root
        closest_h = heuristic(start)
        killed_seen = 0

        while heap:
            f, g, _, key = heap[0]
            node = nodes.get(key)
            if node is None or g > node.g + 1e-9:
                heapq.heappop(heap)
                continue
            heapq.heappop(heap)

            if goal(node.state):
                return self._result(node, PlanStatus.FOUND, expanded, begun)

            if expanded >= self.max_expansions or (time.perf_counter() - begun) * 1000.0 > self.time_budget_ms:
                status = PlanStatus.BUDGET
                return self._result(closest, status, expanded, begun)

            if node.depth >= self.max_segments:
                continue

            expanded += 1
            actions = self.catalog.actions(node.state)
            killed_seen += self.catalog.killed_candidates
            for action in actions:
                segment = self._cached(node.state, action.name)
                if segment is None:
                    segment = self.catalog.evaluate(node.state, action)
                    if segment is None:
                        killed_seen += self.catalog.killed_candidates
                        continue
                    self._store(node.state, action.name, segment)
                if segment.end.killed:
                    continue
                damage = node.damage_hits + segment.damage_hits
                if self.max_damage_hits is not None and damage > self.max_damage_hits:
                    continue

                child_key = node_key(segment.end, self.profile.height)
                child_g = node.g + segment.cost
                existing = nodes.get(child_key)
                if existing is not None and child_g >= existing.g - 1e-9:
                    continue

                child = _Node(child_key, segment.end, child_g, damage, node, segment, node.depth + 1)
                nodes[child_key] = child
                h = heuristic(segment.end)
                heapq.heappush(heap, (child_g + h * weight, child_g, next(counter), child_key))
                if h < closest_h:
                    closest_h, closest = h, child

        status = PlanStatus.NO_SAFE_ROUTE if killed_seen else PlanStatus.NO_PATH
        failure = PlanResult.failure(status, "no route")
        failure.nodes_expanded = expanded
        failure.elapsed_ms = (time.perf_counter() - begun) * 1000.0
        failure.profile_fingerprint = self._fingerprint
        return failure

    # -- result ----------------------------------------------------------------

    def _result(self, node: "_Node", status: PlanStatus, expanded: int, begun: float) -> PlanResult:
        segments: list[Segment] = []
        cursor: "_Node | None" = node
        while cursor is not None:
            if cursor.segment is not None:
                segments.append(cursor.segment)
            cursor = cursor.parent
        segments.reverse()
        segments = self._merge_walks(segments)

        path = Path(
            segments=segments,
            partial=status is not PlanStatus.FOUND,
            status=status,
            nodes_expanded=expanded,
            elapsed_ms=(time.perf_counter() - begun) * 1000.0,
        )
        if segments:
            path.goal = _tile_of(segments[-1].end, self.profile.height)

        return PlanResult(
            status=status,
            path=path,
            reason="" if status is PlanStatus.FOUND else "budget exhausted" if status is PlanStatus.BUDGET else "no route",
            nodes_expanded=expanded,
            elapsed_ms=path.elapsed_ms,
            profile_fingerprint=self._fingerprint,
        )

    @staticmethod
    def _merge_walks(segments: list[Segment]) -> list[Segment]:
        if not segments:
            return segments
        merged: list[Segment] = [segments[0]]
        for segment in segments[1:]:
            previous = merged[-1]
            if (
                previous.kind == segment.kind
                and segment.kind.name == "WALK"
                and previous.end.x == segment.start.x
                and previous.end.y == segment.start.y
            ):
                previous.frames = previous.frames + segment.frames
                previous.end = segment.end
                previous.ticks += segment.ticks
                previous.cost += segment.cost
                previous.damage_hits += segment.damage_hits
                previous.trace = previous.trace + segment.trace
                x0, y0, x1, y1 = previous.bbox
                a0, b0, a1, b1 = segment.bbox
                previous.bbox = (min(x0, a0), min(y0, b0), max(x1, a1), max(y1, b1))
                previous.note = "walk"
            else:
                merged.append(segment)
        return merged


def tile_goal(tx: int, ty: int, profile: CapabilityProfile) -> Goal:
    """Success when the collision rect overlaps the target tile."""

    def goal(state: MotionState) -> bool:
        return _overlaps_tile(state, tx, ty, profile.width, profile.height)

    return goal


def tile_heuristic(profile: CapabilityProfile, tx: int, ty: int) -> Heuristic:
    """Admissible lower bound: horizontal tiles to cover / max speed."""
    ticks_per_tile = TILE / max(profile.max_velocity * profile.dt, 1e-9)

    def heuristic(state: MotionState) -> float:
        x0 = int(state.x // TILE)
        x1 = int((state.x + profile.width - 1e-4) // TILE)
        dx = max(0, tx - x1, x0 - tx)
        return dx * ticks_per_tile

    return heuristic


def _overlaps_tile(state: MotionState, tx: int, ty: int, width: float, height: float) -> bool:
    """Collision rect overlaps the tile, or stands on its top edge (floor blocks)."""
    horizontal = state.x < (tx + 1) * TILE and state.x + width > tx * TILE
    vertical = state.y < (ty + 1) * TILE and state.y + height >= ty * TILE
    return horizontal and vertical


def _tile_of(state: MotionState, height: float) -> tuple[int, int]:
    return int(state.x // TILE), int((state.y + height - 1e-4) // TILE)
