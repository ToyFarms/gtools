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
from typing import Any, Callable

from gtools.core.growtopia.physics.controller import TILE
from gtools.core.growtopia.physics.pathfinding.actions import Action, ActionCatalog, node_key, truncate_frames
from gtools.core.growtopia.physics.pathfinding.profile import CapabilityProfile
from gtools.core.growtopia.physics.pathfinding.snapshot import WorldSnapshot
from gtools.core.growtopia.physics.pathfinding.types import (
    MotionState,
    Path,
    PlanResult,
    PlanStatus,
    Segment,
    SegmentKind,
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
    key: tuple = ()  # (tile column, feet row, stance, ...): the first three are what the overlay draws
    stage: str = ""  # "safe" or "damage": which hazard model this state was generated under


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
    stage: str = ""


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
class Target:
    """What the planner is searching *for*, with the guidance to get there.

    ``goal`` is the arrival test; ``finish`` (optional) verifies and returns a dwell
    that completes a *stand* goal; ``touch`` + ``touch_box`` let a route be cut off
    the tick it enters a touch-only region; ``heuristic(state, stage)`` is the
    estimate for the safe (0) or damage-tolerant (1) model; ``hints(state)`` lists the
    tile columns worth lining up on.
    """

    goal: Goal
    heuristic: Callable[[MotionState, int], float]
    progress: Progress | None = None
    touch: Touch | None = None
    touch_box: tuple[int, int, int, int] | None = None
    finish: Callable[[MotionState], Any] | None = None
    hints: Callable[[MotionState], list[int]] | None = None
    prefer: Callable[[MotionState], tuple[int, ...]] | None = None
    # does the safe guidance model connect the start to the goal?  When it does not,
    # the safe search only gets a short quota before the damage model is tried
    safe_feasible: bool = True
    # is there anything damaging in the world at all (otherwise stage 2 == stage 1)?
    damage_possible: bool = False
    # no guidance model connects start and goal *and* the world has no mechanic the
    # guidance ignores: the goal is unreachable, so only a brief probe is worthwhile
    hopeless: bool = False


class HazardIndex:
    """O(1) "is any deadly/damaging tile in this tile rect" (a summed-area table)."""

    def __init__(self, snapshot: WorldSnapshot) -> None:
        grid = snapshot.grid
        self.w, self.h = int(grid.width), int(grid.height)
        w, h = self.w, self.h
        prefix = [0] * ((w + 1) * (h + 1))
        deadly, deadly_on, damage, damage_on = grid.deadly, grid.deadly_if_on, grid.damage, grid.damage_if_on
        stride = w + 1
        for y in range(h):
            row = 0
            for x in range(w):
                idx = y * w + x
                if deadly[idx] or deadly_on[idx] or damage[idx] or damage_on[idx]:
                    row += 1
                prefix[(y + 1) * stride + x + 1] = prefix[y * stride + x + 1] + row
        self.prefix = prefix
        self.any = prefix[-1] > 0

    def near(self, bbox: tuple[int, int, int, int], margin: int = 1) -> bool:
        if not self.any:
            return False
        x0, y0, x1, y1 = bbox
        x0 = max(0, x0 - margin)
        y0 = max(0, y0 - margin)
        x1 = min(self.w - 1, x1 + margin)
        y1 = min(self.h - 1, y1 + margin)
        if x1 < x0 or y1 < y0:
            return False
        p, s = self.prefix, self.w + 1

        return (p[(y1 + 1) * s + x1 + 1] - p[y0 * s + x1 + 1] - p[(y1 + 1) * s + x0] + p[y0 * s + x0]) > 0


@dataclass(slots=True)
class _Node:
    key: tuple
    state: MotionState
    g: float
    damage_hits: int
    # parent is the *node object*, never its key: a bucket holds several exact
    # states, and replacing ``nodes[key]`` with a cheaper state would otherwise break
    # the exact start/end chain of already-expanded children
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


@dataclass(slots=True)
class _Stage:
    """The outcome of the anytime passes of one hazard model."""

    node: "_Node | None" = None
    partial: "_Node | None" = None
    partial_key: tuple[float, float] = (math.inf, math.inf)
    expansions: int = 0
    killed_seen: int = 0
    drained: bool = False
    weight: float = 1.0


STAGE_SAFE = 0
STAGE_DAMAGE = 1
_STAGE_NAMES = ("safe", "damage")


class SegmentedPlanner:
    """A* over movement segments with budgets, staged hazard policy and an edge cache.

    **Hazard policy.**  Damaging tiles are only considered when they are *necessary*:
    the first stage searches with damage forbidden; the damage-tolerant stage runs
    only if that space is exhausted without a route (or the guidance proves there is
    none).  Deadly tiles are never allowed.

    **Determinism.**  ``max_expansions`` is the budget; ``time_budget_ms`` is a
    wall-clock safety net.  While the expansion budget binds first the result does not
    depend on how fast the machine is.
    """

    def __init__(
        self,
        catalog: ActionCatalog,
        profile: CapabilityProfile,
        snapshot: WorldSnapshot,
        *,
        max_expansions: int = 5000,
        time_budget_ms: float = 1500.0,
        max_damage_hits: int | None = None,
        max_segments: int = 4096,
        edge_cache: dict | None = None,
        heuristic_weight: float = 1.5,
        trace: SearchTrace | None = None,
        hazard_index: HazardIndex | None = None,
        fragile_penalty: float = 25.0,
        fragile_margin_px: float = 2.0,
        damage_policy: str = "avoid",
        verify: bool = True,
    ) -> None:
        self.catalog = catalog
        self.profile = profile
        self.snapshot = snapshot
        self.max_expansions = int(max_expansions)
        self.time_budget_ms = float(time_budget_ms)
        self.max_damage_hits = max_damage_hits
        self.max_segments = int(max_segments)
        self.edge_cache = edge_cache if edge_cache is not None else {}
        self.trace = trace
        self.hazard_index = hazard_index
        self.fragile_penalty = float(fragile_penalty)
        self.fragile_margin_px = float(fragile_margin_px)
        self.damage_policy = damage_policy  # "avoid" | "allow" | "forbid"
        self.verify = bool(verify)
        self._tier = 1
        self._pass_index = 0
        self._stage = STAGE_SAFE
        self._fingerprint = profile.fingerprint()
        # share of the budget the rough (cheap-tier, inflated-weight) pass may use
        # before the full action set gets its turn
        self.first_pass_share = 0.35
        # a route within ``good_enough_ratio * guidance bound + good_enough_ticks`` is
        # accepted without a refinement pass.  The greedy first pass is sensitive to
        # the exact start pixel, so a loose band lets a 1 px shift pick a different
        # (and up to that much costlier) route: it is the planner's quality floor.
        self.good_enough_ratio = 1.03
        self.good_enough_ticks = 2.0
        # weighted A*: inflating ``h`` trades bounded suboptimality for far fewer
        # expansions.  1.0 restores plain A*.
        self.heuristic_weight = max(1.0, float(heuristic_weight))
        self.last_reason = ""

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
            state.jump_latch,
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
        """Decreasing heuristic weights: a rough route first, then refinements."""
        weights = [max(2.5, 1.7 * self.heuristic_weight)]
        for weight in (self.heuristic_weight, 1.0):
            if weight < weights[-1] - 1e-9:
                weights.append(float(weight))

        return tuple(weights)

    def _stages(self, target: Target) -> list[int]:
        if self.damage_policy == "forbid" or self.max_damage_hits == 0:
            return [STAGE_SAFE]
        if not target.damage_possible:
            return [STAGE_SAFE]
        if self.damage_policy == "allow":
            return [STAGE_DAMAGE]

        return [STAGE_SAFE, STAGE_DAMAGE]

    def plan(
        self,
        start: MotionState,
        goal: Any,
        heuristic: Heuristic,
        progress: Progress | None = None,
        *,
        touch: Touch | None = None,
        touch_box: tuple[int, int, int, int] | None = None,
        time_budget_ms: float | None = None,
        max_expansions: int | None = None,
    ) -> PlanResult:
        """Legacy entry point: a bare goal predicate + heuristic (no guidance, no dwell)."""
        target = Target(
            goal=goal,
            heuristic=lambda state, stage: heuristic(state),
            progress=progress,
            touch=touch,
            touch_box=touch_box,
            damage_possible=True,
        )

        return self.plan_target(start, target, time_budget_ms=time_budget_ms, max_expansions=max_expansions)

    def plan_target(
        self,
        start: MotionState,
        target: Target,
        *,
        time_budget_ms: float | None = None,
        max_expansions: int | None = None,
    ) -> PlanResult:
        """Anytime plan: the best complete route the budget allows, else a usable partial.

        ``max_expansions`` overrides the planner's expansion budget for this call only
        (an autopilot refine wants a small, *machine-independent* cap).
        """
        begun = time.perf_counter()
        budget = self.max_expansions if max_expansions is None else max(1, int(max_expansions))
        if start.killed:
            return PlanResult.failure(PlanStatus.KILLED, "start state is dead")

        budget_ms = self.time_budget_ms if time_budget_ms is None else float(time_budget_ms)
        deadline = begun + budget_ms / 1000.0
        trace = self.trace
        if trace is not None:
            trace.reset()
            trace.start = (start.x, start.y)

        stages = self._stages(target)
        expansions = 0
        killed_seen = 0
        found: _Stage | None = None
        found_stage = STAGE_SAFE
        last: _Stage | None = None
        last_stage = STAGE_SAFE

        for position, stage in enumerate(stages):
            remaining = max(0, budget - expansions)
            quota = remaining
            more_stages = position + 1 < len(stages)
            if target.hopeless:
                quota = min(remaining, 400)
            if stage == STAGE_SAFE and more_stages and not target.safe_feasible:
                # the guidance says there is no safe route: probe briefly, then go
                # straight to the damage-tolerant search with the rest of the budget
                quota = min(remaining, max(60, budget // 5))
            self._stage = stage
            # the stage's expansion ``quota`` bounds it; slicing the wall-clock too would
            # make the route depend on machine speed whenever the slice bound first
            outcome = self._anytime(start, target, stage, quota, deadline)
            expansions += outcome.expansions
            killed_seen += outcome.killed_seen
            last, last_stage = outcome, stage
            if outcome.node is not None:
                found, found_stage = outcome, stage
                break
            if not outcome.drained and not (stage == STAGE_SAFE and not target.safe_feasible):
                break  # the budget ran out: do not conclude anything about later stages
            if time.perf_counter() >= deadline:
                break

        if trace is not None:
            trace.expansions = expansions
            trace.elapsed_ms = (time.perf_counter() - begun) * 1000.0
            trace.solved = found is not None

        if found is not None and found.node is not None:
            result = self._result(found.node, PlanStatus.FOUND, expansions, begun, start)
            reasons = []
            if result.status is PlanStatus.FOUND:
                if found_stage == STAGE_DAMAGE and result.path is not None and result.path.damage_hits:
                    reasons.append(f"no safe route: {result.path.damage_hits} damaging hit(s) unavoidable")
                if reasons:
                    result.reason = "; ".join(reasons)
            if trace is not None:
                trace.status = result.status

            return result

        assert last is not None or not stages
        drained = bool(last is not None and last.drained) or target.hopeless
        partial = last.partial if last is not None else None
        if partial is not None and partial.segment is not None and not drained:
            result = self._result(partial, PlanStatus.BUDGET, expansions, begun, start)
            result.reason = "budget exhausted"
            if trace is not None:
                trace.status = PlanStatus.BUDGET

            return result

        status = PlanStatus.NO_SAFE_ROUTE if killed_seen else PlanStatus.NO_PATH
        failure = PlanResult.failure(status, "no route")
        failure.nodes_expanded = expansions
        failure.elapsed_ms = (time.perf_counter() - begun) * 1000.0
        failure.profile_fingerprint = self._fingerprint
        if trace is not None:
            trace.status = status

        return failure

    def _anytime(self, start: MotionState, target: Target, stage: int, quota: int, deadline: float) -> _Stage:
        """Decreasing-weight passes of one hazard model (cheap tier first)."""
        schedule = self.weight_schedule
        trace = self.trace
        used = 0
        killed_seen = 0
        out = _Stage()
        best: _Node | None = None
        best_cost = math.inf
        best_weight = schedule[0]
        root_h = target.heuristic(start, stage)
        begun = time.perf_counter()
        first_slice = min(deadline, begun + (deadline - begun) * self.first_pass_share)
        last: _Pass | None = None
        first_found_at = 0

        for index, weight in enumerate(schedule):
            now = time.perf_counter()
            if index and (now >= deadline or used >= quota):
                break

            pass_begun = now
            record = SearchPassRecord(weight=weight, full_actions=index > 0) if trace is not None else None
            if trace is not None:
                trace.passes.append(record)
            if index == 0:
                pass_quota = max(1, int((quota - used) * (self.first_pass_share if len(schedule) > 1 else 1.0)))
                pass_deadline = first_slice
            else:
                pass_quota = quota - used
                pass_deadline = deadline
                if best is not None:
                    # refining an existing route: bounded by the effort the route itself took
                    pass_quota = min(pass_quota, max(40, int(first_found_at * 0.8)))

            result = self._search(
                start,
                target,
                stage=stage,
                weight=weight,
                deadline=pass_deadline,
                incumbent=best_cost,
                expansion_budget=pass_quota,
                full_actions=index > 0,
            )
            last = result
            used += result.expansions
            killed_seen += result.killed_seen
            if result.partial is not None and result.partial_key < out.partial_key:
                out.partial, out.partial_key = result.partial, result.partial_key
            if record is not None:
                record.expansions = result.expansions
                record.elapsed_ms = (time.perf_counter() - pass_begun) * 1000.0
                record.found = result.node is not None
                record.partial_h = result.partial_key[0]
                record.exhausted = result.exhausted
                record.capped = result.capped
                record.stage = _STAGE_NAMES[stage]

            if result.node is not None:
                if result.node.g < best_cost - 1e-9:
                    if best is None:
                        first_found_at = used
                    best, best_cost, best_weight = result.node, result.node.g, weight
                    if best_cost <= root_h * self.good_enough_ratio + self.good_enough_ticks:
                        break  # within a few percent of the guidance bound: good enough
                    continue
                # an equal-cost route from a weighted pass only bounds the optimum to
                # within ``weight`` x: it proves nothing, so keep descending the
                # schedule.  Only the weight-1 pass is conclusive.
                if weight <= 1.0:
                    break
                continue
            if result.exhausted:
                continue  # this tier is fully explored -- the next pass sees more actions
            if time.perf_counter() >= deadline or used >= quota:
                break

        out.node = best
        out.weight = best_weight
        out.expansions = used
        out.killed_seen = killed_seen
        out.drained = bool(best is None and last is not None and last.exhausted and last.full_actions)

        return out

    def _search(
        self,
        start: MotionState,
        target: Target,
        *,
        stage: int,
        weight: float,
        deadline: float,
        incumbent: float,
        expansion_budget: int,
        full_actions: bool,
    ) -> _Pass:
        """One weighted-A* pass.  Stops on the first complete route."""
        allow_damage = stage == STAGE_DAMAGE
        heuristic = target.heuristic
        root_key = node_key(start, self.profile.height)
        root = _Node(root_key, start, 0.0, 0, None, None)
        nodes: dict[tuple, _Node] = {root_key: root}
        counter = itertools.count()
        root_h = heuristic(start, stage)
        heap: list[tuple[float, float, int, tuple]] = [(root_h * weight, 0.0, next(counter), root_key)]
        progress = target.progress
        pass_ = _Pass(
            partial=root,
            partial_key=(root_h, progress(start) if progress is not None else 0.0),
            full_actions=full_actions,
        )
        killed_seen = 0
        trace = self.trace
        self._pass_index = len(trace.passes) - 1 if trace is not None else 0
        self._tier = 1 if full_actions else 0
        self._stage = stage
        catalog = self.catalog
        catalog.hints = target.hints
        catalog.prefer = target.prefer
        height = self.profile.height

        while heap:
            f, g, _, key = heap[0]
            node = nodes.get(key)
            if node is None or g > node.g + 1e-9:
                heapq.heappop(heap)
                continue
            heapq.heappop(heap)

            if target.finish is None and target.goal(node.state):
                pass_.node = node
                pass_.killed_seen = killed_seen
                return pass_

            # ``g + h`` is a lower bound on the cost of any route through this node, so
            # an incumbent that is already better prunes it outright
            if node.g + heuristic(node.state, stage) >= incumbent - 1e-9:
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
            actions = catalog.actions(node.state, full=full_actions)
            killed_seen += catalog.killed_candidates
            for action in actions:
                deaths = catalog.killed_candidates
                segment = self._cached(node.state, action.name)
                if segment is None:
                    segment = catalog.evaluate(node.state, action, record_trace=False)
                    if segment is None:
                        killed_seen += catalog.killed_candidates - deaths
                        continue
                    self._store(node.state, action.name, segment)
                if segment.end.killed:
                    continue
                damage = node.damage_hits + segment.damage_hits
                if segment.damage_hits and not allow_damage:
                    continue
                if self.max_damage_hits is not None and damage > self.max_damage_hits:
                    continue

                end = segment.end
                # price the hazard margin only for a segment that could still matter:
                # one that cannot beat the cheapest known arrival at its bucket is dropped
                # before paying for the (two extra simulations of the) fragility check
                existing = nodes.get(node_key(end, height))
                if existing is not None and node.g + segment.cost >= existing.g - 1e-9 and target.touch is None and target.finish is None:
                    continue
                if not segment.fragile_checked:
                    segment.fragile_checked = True
                    segment.cost += self._fragility(node.state, segment)
                if end.grounded or end.in_water or end.climbing:
                    h = heuristic(end, stage)
                    key_ = (h, progress(end) if progress is not None else 0.0)
                    if key_ < pass_.partial_key:
                        pass_.partial_key, pass_.partial = key_, _Node(
                            node_key(end, height), end, node.g + segment.cost, damage, node, segment, node.depth + 1
                        )

                hit = self._goal_node(nodes, heap, counter, node, segment, damage, weight, target, stage)
                if hit is not None:
                    pass_.node = hit
                    pass_.killed_seen = killed_seen
                    return pass_

                self._link(nodes, heap, counter, node, segment, damage, weight, target, stage)

        pass_.exhausted = True
        pass_.killed_seen = killed_seen
        return pass_

    # -- goal handling -----------------------------------------------------------

    def _goal_node(
        self,
        nodes: dict[tuple, _Node],
        heap: list,
        counter,
        parent: _Node,
        segment: Segment,
        damage: int,
        weight: float,
        target: Target,
        stage: int,
    ) -> "_Node | None":
        """A goal node when ``segment`` completes the target, else ``None``.

        * touch-only goals are *entered* mid-action: the segment is cut off at the first
          tick whose rect touches the region;
        * stand goals need an arrival state in the tile *and* a verified dwell;
        * a plain predicate is tested on the end state.
        """
        height = self.profile.height
        if target.finish is not None:
            end = segment.end
            if not target.goal(end):
                return None
            finish = target.finish(end)
            if finish is None:
                return None
            arrival = self._offer(nodes, heap, counter, parent, segment, damage, weight, target, stage)
            dwell = Segment(
                kind=SegmentKind.WALK,
                frames=finish.frames,
                start=end.clone(),
                end=finish.end,
                ticks=finish.ticks,
                cost=float(finish.ticks),
                bbox=_trace_bbox(finish.trace, self.profile.width, self.profile.height, segment.bbox),
                damage_hits=0,
                note="stand",
                trace=finish.trace,
            )

            return _Node(node_key(finish.end, height), finish.end, arrival.g + dwell.cost, arrival.damage_hits, arrival, dwell, arrival.depth + 1)

        if target.touch is not None and _boxes_touch(segment.bbox, target.touch_box):
            trace = segment.trace or self._trace_of(segment)
            index = _first_touch(trace, target.touch)
            if index is not None:
                tick = index + 1
                truncated = segment if tick >= segment.ticks else self._truncate(segment, tick)
                if truncated is not None and not truncated.end.killed and not (truncated.damage_hits and stage == STAGE_SAFE):
                    return self._offer(nodes, heap, counter, parent, truncated, parent.damage_hits + truncated.damage_hits, weight, target, stage)

        if target.touch is None and target.goal(segment.end):
            return self._offer(nodes, heap, counter, parent, segment, damage, weight, target, stage)

        return None

    def _trace_of(self, segment: Segment) -> list[tuple[float, float, bool]]:
        outcome = self.catalog.evaluator.simulate(segment.start.clone(), segment.frames, record_trace=True)
        segment.trace = outcome.tick_trace

        return segment.trace

    def _fragility(self, start: MotionState, segment: Segment) -> float:
        """Extra cost for a segment that only just clears a hazard.

        A route that grazes a spike is correct only for the exact pixel the simulation
        started from.  When a segment passes within a tile of any hazard it is replayed
        from a couple of pixels either side; if either replay dies or takes more
        damage, it is fragile and priced accordingly, so the search prefers a
        comfortable alternative and only squeezes through when it has to.
        """
        index = self.hazard_index
        if index is None or not index.near(segment.bbox, 1):
            return 0.0

        evaluator = self.catalog.evaluator
        for dx in (-self.fragile_margin_px, self.fragile_margin_px):
            probe = start.clone()
            probe.x += dx
            outcome = evaluator.simulate(probe, segment.frames)
            if outcome.state.killed or outcome.damage_hits > segment.damage_hits:
                return self.fragile_penalty

        return 0.0

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
        target: Target,
        stage: int,
    ) -> _Node | None:
        """Offer ``segment`` as a successor of ``parent`` (cheapest state per key wins)."""
        child = self._make_child(parent, segment, damage)
        existing = nodes.get(child.key)
        if existing is not None and child.g >= existing.g - 1e-9:
            return None

        h = target.heuristic(segment.end, stage)
        trace = self.trace
        if trace is not None:
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
                stage=_STAGE_NAMES[self._stage],
            )
            trace.nodes.append(child.record)

        nodes[child.key] = child
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
        target: Target,
        stage: int,
    ) -> _Node:
        """``_link`` that always returns the node (a goal hit must not be dropped)."""
        child = self._link(nodes, heap, counter, parent, segment, damage, weight, target, stage)

        return child if child is not None else self._make_child(parent, segment, damage)

    def _truncate(self, segment: Segment, ticks: int) -> Segment | None:
        """``segment`` cut off at ``ticks`` (the tick that entered the goal region)."""
        if ticks <= 0:
            return None

        evaluator = self.catalog.evaluator
        outcome = evaluator.simulate(segment.start.clone(), segment.frames, max_ticks=ticks, record_trace=True)
        if outcome.state.killed:
            return None

        action = Action(segment.note, segment.frames)

        return Segment(
            kind=self.catalog.classify(outcome, segment.start, action),
            frames=truncate_frames(segment.frames, outcome.ticks),
            start=segment.start.clone(),
            end=outcome.state,
            ticks=outcome.ticks,
            cost=outcome.ticks + outcome.damage_hits * self.catalog.damage_penalty,
            bbox=outcome.bbox,
            damage_hits=outcome.damage_hits,
            note=segment.note,
            trace=outcome.tick_trace,
        )

    # -- result ----------------------------------------------------------------

    def _result(self, node: "_Node", status: PlanStatus, expanded: int, begun: float, start: MotionState) -> PlanResult:
        segments: list[Segment] = []
        cursor: "_Node | None" = node
        while cursor is not None:
            if cursor.segment is not None:
                segments.append(cursor.segment)
            cursor = cursor.parent
        segments.reverse()
        segments = self._finalize(segments)

        reason = "" if status is PlanStatus.FOUND else "budget exhausted" if status is PlanStatus.BUDGET else "no route"
        if self.verify and segments and not self._verified(segments, start):
            status = PlanStatus.PARTIAL
            reason = "verification mismatch"

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
            reason=reason,
            nodes_expanded=expanded,
            elapsed_ms=path.elapsed_ms,
            profile_fingerprint=self._fingerprint,
        )

    def _verified(self, segments: list[Segment], start: MotionState) -> bool:
        """Replay the whole route from the start with the kernel: it must end where the
        last segment says it does, alive."""
        frames = tuple(frame for segment in segments for frame in segment.frames)
        outcome = self.catalog.evaluator.simulate(start.clone(), frames)
        expected = segments[-1].end
        if outcome.state.killed:
            return False

        return abs(outcome.state.x - expected.x) <= 0.5 and abs(outcome.state.y - expected.y) <= 0.5

    def _finalize(self, segments: list[Segment]) -> list[Segment]:
        """Fill in traces, then merge the pieces the search composed back into the
        moves a person would name: launch+flight(+double jump) is one *jump*, a chain of
        swim steps one *swim*, consecutive walks one *walk*."""
        evaluator = self.catalog.evaluator
        for segment in segments:
            if not segment.trace:
                outcome = evaluator.simulate(segment.start.clone(), segment.frames, record_trace=True)
                segment.trace = outcome.tick_trace

        merged: list[Segment] = []
        index = 0
        while index < len(segments):
            group = [segments[index]]
            index += 1
            while index < len(segments) and len(group) < 48:
                last, following = group[-1], segments[index]
                end = last.end
                airborne = not (end.grounded or end.climbing or end.in_water)
                swim = end.in_water and last.start.in_water and following.start.in_water and following.end.in_water
                walk = (
                    last.kind is SegmentKind.WALK
                    and following.kind is SegmentKind.WALK
                    and last.note != "stand"
                    and following.note != "stand"
                    and end.x == following.start.x
                    and end.y == following.start.y
                )
                if not (airborne or swim or walk):
                    break
                group.append(following)
                index += 1
            merged.append(group[0] if len(group) == 1 else self._merge(group))

        return merged

    def _merge(self, group: list[Segment]) -> Segment:
        frames = tuple(frame for segment in group for frame in segment.frames)
        first, last = group[0], group[-1]
        outcome = self.catalog.evaluator.simulate(first.start.clone(), frames, record_trace=True)
        x0, y0, x1, y1 = first.bbox
        for segment in group[1:]:
            a0, b0, a1, b1 = segment.bbox
            x0, y0, x1, y1 = min(x0, a0), min(y0, b0), max(x1, a1), max(y1, b1)
        name = first.note if first.note == last.note else f"{first.note}+{last.note}"

        return Segment(
            kind=self.catalog.classify(outcome, first.start, Action(name, frames)),
            frames=frames,
            start=first.start,
            end=outcome.state,
            ticks=outcome.ticks,
            cost=sum(segment.cost for segment in group),
            bbox=(x0, y0, x1, y1),
            damage_hits=sum(segment.damage_hits for segment in group),
            note=name,
            trace=outcome.tick_trace,
        )


def _trace_bbox(trace: list[tuple[float, float, bool]], width: float, height: float, base: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = base
    for x, y, _g in trace:
        x0 = min(x0, math.floor(x / TILE))
        y0 = min(y0, math.floor(y / TILE))
        x1 = max(x1, math.floor((x + width - 1e-4) / TILE))
        y1 = max(y1, math.floor((y + height - 1e-4) / TILE))

    return (x0, y0, x1, y1)


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


def _tile_of(state: MotionState, height: float) -> tuple[int, int]:
    return int(state.x // TILE), int((state.y + height - 1e-4) // TILE)
