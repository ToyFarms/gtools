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
import math
import time
from dataclasses import dataclass, field
from typing import Callable

from gtools.core.growtopia.physics.controller import TILE
from gtools.core.growtopia.physics.pathfinding.actions import ActionCatalog, node_key, truncate_frames
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
# Pixel-level distance to the goal, used only to break ties between states that
# the tile-scale heuristic cannot separate (``h`` is flat inside a tile).  It
# decides which node a *partial* (budget-exhausted) path ends at.
Progress = Callable[[MotionState], float]
# Positional form of the goal: ``touch(x, y)`` on the avatar's collision-rect
# origin.  A route is complete once the avatar *enters* the goal region, which is
# what lets a goal in mid-air (a tile above the floor, the face of a wall) be
# planned at all: segment endpoints only ever land on something.
Touch = Callable[[float, float], bool]


@dataclass(slots=True)
class SearchNodeRecord:
    """One search state, kept only when a ``SearchTrace`` is attached.

    ``expanded`` is False while the state is on the frontier (generated, not yet
    expanded), which is what an inspector wants to see: where the search *looked*
    versus where it still *plans to look*.
    """

    x: float
    y: float
    g: float
    h: float
    f: float
    weight: float
    depth: int
    pass_index: int
    tier: int  # 0 = cheap action tier, 1 = full action set
    expanded: bool = False
    goal: bool = False
    note: str = ""
    key: tuple = ()


@dataclass(slots=True)
class SearchPassRecord:
    """What one weighted-A* pass did."""

    weight: float
    full_actions: bool
    expansions: int = 0
    elapsed_ms: float = 0.0
    found: bool = False
    partial_h: float = math.inf
    exhausted: bool = False
    capped: bool = False


@dataclass(slots=True)
class SearchTrace:
    """A record of the last plan, for visualisation (opt-in, per planner).

    ``SegmentedPathfinder(record_search=True)`` attaches one and the demo draws
    it: every generated state, every expansion and every pass.  A benchmark or a
    game client leaves it off -- the allocation per successor is not free.
    """

    goal: tuple[int, int] = (-1, -1)
    start: tuple[float, float] = (0.0, 0.0)
    passes: list[SearchPassRecord] = field(default_factory=list)
    nodes: list[SearchNodeRecord] = field(default_factory=list)
    solved: bool = False
    status: PlanStatus = PlanStatus.NO_PATH
    expansions: int = 0
    elapsed_ms: float = 0.0

    def reset(self) -> None:
        self.passes.clear()
        self.nodes.clear()
        self.solved = False
        self.status = PlanStatus.NO_PATH
        self.expansions = 0
        self.elapsed_ms = 0.0

    @property
    def expanded(self) -> list[SearchNodeRecord]:
        return [record for record in self.nodes if record.expanded]

    @property
    def frontier(self) -> list[SearchNodeRecord]:
        return [record for record in self.nodes if not record.expanded]


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
    record: SearchNodeRecord | None = None


@dataclass(slots=True)
class _Pass:
    """One weighted-A* run: the route it completed and the best progress it made."""

    node: "_Node | None" = None
    partial: "_Node | None" = None
    partial_key: tuple[float, float] = (math.inf, math.inf)
    expansions: int = 0
    killed_seen: int = 0
    exhausted: bool = False
    capped: bool = False
    full_actions: bool = True


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
        trace: SearchTrace | None = None,
    ) -> None:
        self.catalog = catalog
        self.profile = profile
        self.snapshot = snapshot
        self.max_expansions = int(max_expansions)
        self.time_budget_ms = float(time_budget_ms)
        self.max_damage_hits = max_damage_hits
        self.max_segments = int(max_segments)
        self.edge_cache = edge_cache if edge_cache is not None else {}
        # opt-in search recording for the demo's node overlay
        self.trace = trace
        self._tier = 1
        self._pass_index = 0
        self._fingerprint = profile.fingerprint()
        # share of the budget the rough (cheap-tier, inflated-weight) pass may use
        # before the full action set gets its turn
        self.first_pass_share = 0.5
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

    @property
    def weight_schedule(self) -> tuple[float, ...]:
        """Decreasing heuristic weights: a rough route first, then refinements.

        ``heuristic_weight`` stays the "quality" weight; the first pass runs
        inflated (``max(3.0, 2 * heuristic_weight)``) so it is nearly greedy and
        completes after very few expansions, and the remaining budget is then spent
        lowering the weight towards 1.0 (plain admissible A*).  Refinement passes
        are pruned by the incumbent's cost, so they only look where an improvement
        is still possible.
        """
        weights = [max(3.0, 2.0 * self.heuristic_weight)]
        for weight in (self.heuristic_weight, 1.0):
            if weight < weights[-1] - 1e-9:
                weights.append(float(weight))

        return tuple(weights)

    def plan(
        self,
        start: MotionState,
        goal: Goal,
        heuristic: Heuristic,
        progress: Progress | None = None,
        *,
        touch: Touch | None = None,
        touch_box: tuple[int, int, int, int] | None = None,
        time_budget_ms: float | None = None,
    ) -> PlanResult:
        """Anytime plan: return the best complete route the budget allows.

        The contract is "never leave the caller without a route it can start
        moving on".  Passes run in order of decreasing heuristic weight and
        increasing action coverage:

        1. cheap action tier (no double jumps / glides / waits) at the inflated
           weight -- a few expansions produce a rough but complete route;
        2. the full action set at ``heuristic_weight`` and then at 1.0, each
           pruned by ``g + h < incumbent``, so they only improve on it.

        If no pass completes a route, the best *progress* node seen is returned as
        a partial path (``BUDGET``): the follower walks it and re-plans from the
        new state, which is what makes a long route advance in chunks instead of
        failing outright.
        """
        begun = time.perf_counter()
        if start.killed:
            return PlanResult.failure(PlanStatus.KILLED, "start state is dead")

        budget_ms = self.time_budget_ms if time_budget_ms is None else float(time_budget_ms)
        deadline = begun + budget_ms / 1000.0
        first_slice = min(deadline, begun + budget_ms * self.first_pass_share / 1000.0)
        schedule = self.weight_schedule
        trace = self.trace
        if trace is not None:
            trace.reset()
            trace.start = (start.x, start.y)
        expansions = 0
        killed_seen = 0
        best: _Node | None = None
        best_cost = math.inf
        best_weight = schedule[0]
        partial: _Node | None = None
        partial_key: tuple[float, float] = (math.inf, math.inf)
        last_pass: _Pass | None = None

        for index, weight in enumerate(schedule):
            if index and time.perf_counter() >= deadline:
                break

            pass_begun = time.perf_counter()
            pass_record = SearchPassRecord(weight=weight, full_actions=index > 0) if trace is not None else None
            if trace is not None:
                trace.passes.append(pass_record)

            outcome = self._search(
                start,
                goal,
                heuristic,
                progress=progress,
                touch=touch,
                touch_box=touch_box,
                weight=weight,
                # the rough pass gets a slice only: if it cannot finish, the full
                # action tier below still has budget to find a route the cheap tier
                # cannot express (double jumps, glides, waiting)
                deadline=first_slice if index == 0 else deadline,
                incumbent=best_cost,
                # the expansion cap is a budget for the *plan*, not per pass, so a
                # caller that wants "one expansion" still gets one
                expansion_budget=self.max_expansions - expansions,
                # the first, rough pass uses the cheap tier: those are the actions
                # that dominate the physics cost (a double jump is ~90 simulated
                # ticks per evaluation), and a route that needs them is still
                # found by the passes below
                full_actions=index > 0,
            )
            last_pass = outcome
            expansions += outcome.expansions
            killed_seen += outcome.killed_seen
            if outcome.partial is not None and outcome.partial_key < partial_key:
                partial, partial_key = outcome.partial, outcome.partial_key
            if pass_record is not None:
                pass_record.expansions = outcome.expansions
                pass_record.elapsed_ms = (time.perf_counter() - pass_begun) * 1000.0
                pass_record.found = outcome.node is not None
                pass_record.partial_h = outcome.partial_key[0]
                pass_record.exhausted = outcome.exhausted
                pass_record.capped = outcome.capped

            if outcome.node is not None:
                if outcome.node.g < best_cost - 1e-9:
                    best, best_cost, best_weight = outcome.node, outcome.node.g, weight
                    continue
                # a refinement found nothing better, and further passes are
                # bounded by the same incumbent: stop refining
                break

            if outcome.exhausted:
                # this tier is fully explored -- the next pass sees more actions
                continue

            if time.perf_counter() >= deadline:
                break

            # expansion cap with time to spare: the next weight may still get lucky
            continue

        if trace is not None:
            trace.expansions = expansions
            trace.elapsed_ms = (time.perf_counter() - begun) * 1000.0
            trace.solved = best is not None

        if best is not None:
            result = self._result(best, PlanStatus.FOUND, expansions, begun)
            result.reason = "" if best_weight >= self.heuristic_weight - 1e-9 else f"rough route (weight {best_weight:.1f})"
            if trace is not None:
                trace.status = PlanStatus.FOUND

            return result

        status = PlanStatus.NO_SAFE_ROUTE if killed_seen else PlanStatus.NO_PATH
        # "drained" means a pass that had the *full* action set explored everything
        # reachable; a cheap-tier pass running out is only a small space, not proof
        drained = last_pass is not None and last_pass.exhausted and last_pass.full_actions
        if partial is not None and partial.segment is not None and not drained:
            # partial progress towards the goal: the caller can start moving and
            # re-plan from there -- the "chunked" mode of long routes.  A search
            # that drained the whole space instead really has no route to offer.
            result = self._result(partial, PlanStatus.BUDGET, expansions, begun)
            result.reason = "budget exhausted"
            if trace is not None:
                trace.status = PlanStatus.BUDGET

            return result

        failure = PlanResult.failure(status, "no route")
        failure.nodes_expanded = expansions
        failure.elapsed_ms = (time.perf_counter() - begun) * 1000.0
        failure.profile_fingerprint = self._fingerprint
        if trace is not None:
            trace.status = status

        return failure

    def _search(
        self,
        start: MotionState,
        goal: Goal,
        heuristic: Heuristic,
        *,
        progress: Progress | None = None,
        touch: Touch | None = None,
        touch_box: tuple[int, int, int, int] | None = None,
        weight: float,
        deadline: float,
        incumbent: float,
        expansion_budget: int,
        full_actions: bool,
    ) -> _Pass:
        """One weighted-A* pass.  Stops on the first complete route."""
        root_key = node_key(start, self.profile.height)
        root = _Node(root_key, start, 0.0, 0, None, None)
        nodes: dict[tuple, _Node] = {root_key: root}
        counter = itertools.count()
        root_h = heuristic(start)
        # the root is the fallback partial, and it yields an empty path: only a
        # real successor (``partial_key`` strictly better) replaces it
        heap: list[tuple[float, float, int, tuple]] = [(root_h * weight, 0.0, next(counter), root_key)]
        pass_ = _Pass(
            partial=root,
            partial_key=(root_h, progress(start) if progress is not None else 0.0),
            full_actions=full_actions,
        )
        killed_seen = 0
        trace = self.trace
        self._pass_index = len(trace.passes) - 1 if trace is not None else 0
        self._tier = 1 if full_actions else 0

        while heap:
            f, g, _, key = heap[0]
            node = nodes.get(key)
            if node is None or g > node.g + 1e-9:
                heapq.heappop(heap)
                continue
            heapq.heappop(heap)

            if goal(node.state):
                pass_.node = node
                pass_.killed_seen = killed_seen
                return pass_

            # ``g + h`` is a lower bound on the cost of any route through this
            # node, so an incumbent that is already better prunes it outright
            if node.g + heuristic(node.state) >= incumbent - 1e-9:
                continue

            if pass_.expansions >= expansion_budget or time.perf_counter() >= deadline:
                pass_.capped = True
                pass_.killed_seen = killed_seen
                return pass_

            if node.depth >= self.max_segments:
                continue

            if node.record is not None:
                node.record.expanded = True

            pass_.expansions += 1
            actions = self.catalog.actions(node.state, full=full_actions)
            killed_seen += self.catalog.killed_candidates
            for action in actions:
                deaths = self.catalog.killed_candidates
                segment = self._cached(node.state, action.name)
                if segment is None:
                    segment = self.catalog.evaluate(node.state, action)
                    if segment is None:
                        killed_seen += self.catalog.killed_candidates - deaths
                        continue
                    self._store(node.state, action.name, segment)
                if segment.end.killed:
                    continue
                damage = node.damage_hits + segment.damage_hits
                if self.max_damage_hits is not None and damage > self.max_damage_hits:
                    continue

                # the best *partial* target is tracked from every realised move,
                # including the ones the key-level dominance rule drops below: a
                # budget-exhausted plan needs a place to walk to, not a search node
                h = heuristic(segment.end)
                key_ = (h, progress(segment.end) if progress is not None else 0.0)
                if key_ < pass_.partial_key:
                    pass_.partial_key, pass_.partial = key_, _Node(
                        node_key(segment.end, self.profile.height), segment.end, node.g + segment.cost, damage, node, segment, node.depth + 1
                    )

                # ... and the goal may be *entered* mid-action: a tile in the air,
                # the face of a wall or a ledge the avatar only flies past can never
                # satisfy a landing-state test, so the move is also offered cut off
                # at the first tick that touches the goal region
                if touch is not None and segment.trace and _boxes_touch(segment.bbox, touch_box):
                    index = _first_touch(segment.trace, touch)
                    # trace[i] is the state *after* tick i + 1
                    tick = None if index is None else index + 1
                    if tick is not None and tick < segment.ticks:
                        truncated = self._truncate(node.state, action, segment, tick)
                        if truncated is not None:
                            pass_.node = self._offer(
                                nodes, heap, counter, node, truncated, node.damage_hits + truncated.damage_hits, weight, heuristic
                            )
                            pass_.killed_seen = killed_seen
                            return pass_

                child = self._link(nodes, heap, counter, node, segment, damage, weight, heuristic)
                # the goal is tested on generation, not only on pop: the tile key
                # buckets several exact states, so a goal state can be dropped as
                # "dominated" by a cheaper state in the same tile and would never be
                # popped.  A* still refines this first hit through the later passes.
                if goal(segment.end):
                    pass_.node = child if child is not None else self._make_child(node, segment, damage)
                    pass_.killed_seen = killed_seen
                    return pass_

        pass_.exhausted = True
        pass_.killed_seen = killed_seen
        return pass_

    def _make_child(self, parent: _Node, segment: Segment, damage: int) -> _Node:
        return _Node(
            node_key(segment.end, self.profile.height),
            segment.end,
            parent.g + segment.cost,
            damage,
            parent,
            segment,
            parent.depth + 1,
        )

    def _link(
        self,
        nodes: dict[tuple, _Node],
        heap: list,
        counter,
        parent: _Node,
        segment: Segment,
        damage: int,
        weight: float,
        heuristic: Heuristic,
    ) -> _Node | None:
        """Offer ``segment`` as a successor of ``parent`` (cheapest state per key wins)."""
        child = self._make_child(parent, segment, damage)
        existing = nodes.get(child.key)
        if existing is not None and child.g >= existing.g - 1e-9:
            return None

        trace = self.trace
        if trace is not None:
            h = heuristic(segment.end)
            child.record = SearchNodeRecord(
                x=segment.end.x,
                y=segment.end.y,
                g=child.g,
                h=h,
                f=child.g + h * weight,
                weight=weight,
                depth=child.depth,
                pass_index=self._pass_index,
                tier=self._tier,
                note=segment.note,
                key=child.key,
            )
            trace.nodes.append(child.record)

        nodes[child.key] = child
        h = heuristic(segment.end)
        heapq.heappush(heap, (child.g + h * weight, child.g, next(counter), child.key))

        return child

    def _offer(
        self,
        nodes: dict[tuple, _Node],
        heap: list,
        counter,
        parent: _Node,
        segment: Segment,
        damage: int,
        weight: float,
        heuristic: Heuristic,
    ) -> _Node:
        """``_link`` that always returns the node (a goal hit must not be dropped)."""
        child = self._link(nodes, heap, counter, parent, segment, damage, weight, heuristic)

        return child if child is not None else self._make_child(parent, segment, damage)

    def _truncate(self, start: MotionState, action: Any, segment: Segment, ticks: int) -> Segment | None:
        """``segment`` cut off at ``ticks`` (the tick that entered the goal region).

        The frames are re-simulated with ``max_ticks`` instead of replayed from the
        trace so the end state carries the full motion state the follower compares
        against -- a trace entry only has position and groundedness.
        """
        if ticks <= 0:
            return None

        outcome = self.catalog.evaluator.simulate(start.clone(), action.frames, max_ticks=ticks, record_trace=True)
        if outcome.state.killed:
            return None

        return Segment(
            kind=self.catalog.classify(outcome, start, action),
            frames=truncate_frames(action.frames, ticks),
            start=start.clone(),
            end=outcome.state,
            ticks=outcome.ticks,
            cost=outcome.ticks + action.penalty + outcome.damage_hits * self.catalog.damage_penalty,
            bbox=outcome.bbox,
            damage_hits=outcome.damage_hits,
            note=action.name,
            trace=outcome.tick_trace,
        )

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


def tile_touch(tx: int, ty: int, width: float, height: float) -> Touch:
    """The positional form of :func:`tile_goal`: does the rect at ``(x, y)`` touch it?"""

    def touch(x: float, y: float) -> bool:
        return x < (tx + 1) * TILE and x + width > tx * TILE and y < (ty + 1) * TILE and y + height >= ty * TILE

    return touch


def _boxes_touch(bbox: tuple[int, int, int, int], box: tuple[int, int, int, int] | None) -> bool:
    """Cheap pre-filter: can a segment whose tile bbox is ``bbox`` reach ``box``?"""
    if box is None:
        return True
    x0, y0, x1, y1 = bbox
    bx0, by0, bx1, by1 = box

    return x0 <= bx1 and x1 >= bx0 and y0 <= by1 and y1 >= by0


def _first_touch(trace: list[tuple[float, float, bool]], touch: Touch) -> int | None:
    """Index of the first traced tick that touches the goal region (``None`` if never)."""
    for index, (x, y, _grounded) in enumerate(trace):
        if touch(x, y):
            return index

    return None


def tile_heuristic(profile: CapabilityProfile, tx: int, ty: int) -> Heuristic:
    """Admissible lower bound on the ticks needed to reach the goal tile.

    Two terms, because a horizontal-only bound is *flat inside a goal column*: on
    a parkour world the search then has no reason to prefer the goal's row over
    any other and spends its budget wandering up and down the column.

    * horizontal: tiles to cover / max speed;
    * vertical: rows to cover / the fastest possible climb, which is the jump
      speed itself (a tile of height can never take less than ``32 / jump_speed``
      ticks, in either direction -- falling only adds time).

    The goal test accepts the collision rect overlapping the tile *or* standing on
    its top edge, so the feet may legitimately finish one row off; the vertical
    term keeps that row free.
    """
    ticks_per_tile = TILE / max(profile.max_velocity * profile.dt, 1e-9)
    ticks_per_row = TILE / max(profile.jump_speed * profile.dt, 1e-9)

    def heuristic(state: MotionState) -> float:
        x0 = int(state.x // TILE)
        x1 = int((state.x + profile.width - 1e-4) // TILE)
        dx = max(0, tx - x1, x0 - tx)
        feet = int((state.y + profile.height - 1e-4) // TILE)
        dy = max(0, abs(ty - feet) - 1)

        return dx * ticks_per_tile + dy * ticks_per_row

    return heuristic


def _overlaps_tile(state: MotionState, tx: int, ty: int, width: float, height: float) -> bool:
    """Collision rect overlaps the tile, or stands on its top edge (floor blocks)."""
    horizontal = state.x < (tx + 1) * TILE and state.x + width > tx * TILE
    vertical = state.y < (ty + 1) * TILE and state.y + height >= ty * TILE
    return horizontal and vertical


def _tile_of(state: MotionState, height: float) -> tuple[int, int]:
    return int(state.x // TILE), int((state.y + height - 1e-4) // TILE)
