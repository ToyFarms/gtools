"""Autopilot refine safety: when a refine may run, what it may install, how it is budgeted."""

from __future__ import annotations

import dataclasses

from pyglm.glm import ivec2

from gtools.baked.items import DIRT, MAIN_DOOR
from gtools.core.growtopia.physics.controller import HITBOX, PlayerController
from gtools.core.growtopia.physics.pathfinding import PathAutopilot, SegmentedPathfinder
from gtools.core.growtopia.physics.pathfinding.types import PlanStatus
from gtools.core.growtopia.world import Tile, World

FLOOR_Y = 8
STAND_Y = FLOOR_Y * 32 - HITBOX[1]


def gap_world(width=30, gap=(10, 11)):
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(width) if x not in gap]
    tiles.append(Tile(fg_id=MAIN_DOOR, pos=ivec2(1, FLOOR_Y - 1)))
    world = World.from_tiles(tiles)
    world.set_local_player(1)
    controller = PlayerController(world, net_id=1, send=None, auto_respawn=False)
    controller.spawn(4 * 32 + 6.0, STAND_Y)
    for _ in range(8):
        controller.step()

    return controller


def started(**kwargs):
    controller = gap_world()
    pathfinder = SegmentedPathfinder(controller)
    autopilot = PathAutopilot(controller, pathfinder, refine=False, **kwargs)
    result = autopilot.plan_to_tile(16, FLOOR_Y - 1)
    assert result.ok, result.reason

    return controller, pathfinder, autopilot


def run_until(controller, autopilot, predicate, limit=1500):
    for _ in range(limit):
        if predicate(controller):
            return True
        if not autopilot.advance():
            return False
        controller.step()

    return False


def spy_on_planning(pathfinder):
    calls = []
    real = pathfinder.plan_from_current

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    pathfinder.plan_from_current = spy

    return calls


# -- refine_now only runs on a stable avatar -------------------------------------


def test_refine_now_never_plans_mid_air():
    controller, pathfinder, autopilot = started()
    calls = spy_on_planning(pathfinder)

    assert run_until(controller, autopilot, lambda c: not c.grounded and not c.in_water and not c.climbing), "the route should leave the ground"
    assert autopilot.refine_now() is False
    assert calls == [], "an airborne refine must not even plan"
    assert autopilot.refine_skip_reason == "airborne"
    assert autopilot.refines_skipped == 1


def test_refine_now_plans_once_the_avatar_rests():
    controller, pathfinder, autopilot = started()
    calls = spy_on_planning(pathfinder)

    assert controller.grounded
    autopilot.refine_now()
    assert len(calls) == 1
    assert autopilot.refine_skip_reason == ""


def test_an_airborne_tick_defers_the_refine_instead_of_burning_the_period():
    controller, pathfinder, autopilot = started()
    autopilot.refine = True
    autopilot.refine_every = 3
    stances = []
    real = pathfinder.plan_from_current

    def spy(**kwargs):
        stances.append(bool(controller.grounded or controller.in_water or controller.climbing))
        return real(**kwargs)

    pathfinder.plan_from_current = spy

    assert run_until(controller, autopilot, lambda c: not c.grounded)
    assert run_until(controller, autopilot, lambda c: c.grounded and autopilot.refines_skipped > 0, limit=600)
    # every plan that did run saw a resting avatar, and at least one refine was deferred
    assert stances and all(stances)
    assert autopilot.refines_skipped > 0
    # after the deferral the refine is retried on the next stable tick, not a period later
    before = len(stances)
    for _ in range(4):
        if not autopilot.advance():
            break
        controller.step()
    assert len(stances) > before


# -- _is_better never trades damage for ticks ---------------------------------


def candidate_with(path, *, damage, cost_scale=0.5, partial=False):
    segments = [dataclasses.replace(segment, cost=segment.cost * cost_scale, damage_hits=0) for segment in path.segments]
    segments[-1] = dataclasses.replace(segments[-1], damage_hits=damage)

    return dataclasses.replace(path, segments=segments, partial=partial)


def test_is_better_rejects_a_cheaper_route_with_more_damage_hits():
    _, _, autopilot = started()
    follower = autopilot.follower
    assert follower.remaining_damage_hits == 0

    cheaper_but_burning = candidate_with(follower.path, damage=1)
    assert cheaper_but_burning.total_cost < follower.remaining_cost - 1.0
    assert autopilot._is_better(cheaper_but_burning, follower) is False

    cheaper_and_safe = candidate_with(follower.path, damage=0)
    assert autopilot._is_better(cheaper_and_safe, follower) is True


def test_is_better_allows_equal_damage_and_counts_only_what_remains():
    _, _, autopilot = started()
    follower = autopilot.follower
    # the current route takes one hit later on: a candidate with one hit is no worse
    follower._segments[-1] = dataclasses.replace(follower._segments[-1], damage_hits=1)
    assert follower.remaining_damage_hits == 1
    assert autopilot._is_better(candidate_with(follower.path, damage=1), follower) is True
    assert autopilot._is_better(candidate_with(follower.path, damage=2), follower) is False


def test_remaining_damage_ignores_segments_already_behind_the_avatar():
    _, _, autopilot = started()
    follower = autopilot.follower
    follower._segments[0] = dataclasses.replace(follower._segments[0], damage_hits=2)
    assert follower.remaining_damage_hits >= 0
    before = follower.remaining_damage_hits
    follower._index = 1
    follower._tick = 0
    assert follower.remaining_damage_hits == before - 2


def test_damage_check_also_guards_partial_comparisons():
    _, _, autopilot = started()
    follower = autopilot.follower
    partial = candidate_with(follower.path, damage=1, partial=True)
    assert autopilot._is_better(partial, follower) is False


# -- the refine budget is counted in expansions ----------------------------------


def test_refine_passes_an_expansion_budget_to_the_planner():
    controller, pathfinder, autopilot = started(refine_budget_expansions=123)
    calls = spy_on_planning(pathfinder)
    autopilot.refine_now()
    assert calls and calls[0]["max_expansions"] == 123
    assert calls[0]["time_budget_ms"] == autopilot.refine_budget_ms


def test_the_expansion_cap_binds_before_a_huge_wall_clock():
    controller = gap_world()
    pathfinder = SegmentedPathfinder(controller, max_expansions=5000)
    pathfinder.plan_to_tile(16, FLOOR_Y - 1)
    free = pathfinder.plan_from_current(time_budget_ms=60_000.0)
    capped = pathfinder.plan_from_current(time_budget_ms=60_000.0, max_expansions=3)
    assert capped.nodes_expanded <= 3
    assert free.nodes_expanded >= capped.nodes_expanded
    assert capped.status in (PlanStatus.BUDGET, PlanStatus.FOUND, PlanStatus.PARTIAL)


def test_a_capped_refine_is_machine_independent():
    controller = gap_world()
    pathfinder = SegmentedPathfinder(controller)
    pathfinder.plan_to_tile(16, FLOOR_Y - 1)
    a = pathfinder.plan_from_current(time_budget_ms=60_000.0, max_expansions=40)
    b = pathfinder.plan_from_current(time_budget_ms=120_000.0, max_expansions=40)
    assert a.status == b.status
    assert a.nodes_expanded == b.nodes_expanded
    assert [s.note for s in a.path.segments] == [s.note for s in b.path.segments]
