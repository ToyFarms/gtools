"""Clearance (the +-2 px fragility probe) and planner determinism."""

from __future__ import annotations

import pytest
from gtools.baked.items import DIRT
from gtools.core.growtopia.physics.controller import PlayerController
from gtools.core.growtopia.physics.pathfinding import SegmentedPathfinder
from gtools.core.growtopia.world import TileFlags

from tests.test_path_planner import DEATH_SPIKES, STAND_Y, make_world

GOAL = (20, 7)
MARGIN = 2.0


def pillar(height, x=12):
    return [(DEATH_SPIKES, x, 7 - k, TileFlags.NONE) for k in range(height)]


def planner_at(extras, x, *, fragile_penalty=25.0, max_expansions=3000, budget_ms=20000.0):
    world = make_world(extras=extras)
    world.set_local_player(1)
    controller = PlayerController(world, net_id=1, send=None, auto_respawn=False)
    controller.spawn(float(x), STAND_Y)
    for _ in range(8):
        controller.step()

    return SegmentedPathfinder(
        controller, fragile_penalty=fragile_penalty, max_expansions=max_expansions, time_budget_ms=budget_ms
    )


def plan(extras, x, **kwargs):
    pathfinder = planner_at(extras, x, **kwargs)
    result = pathfinder.plan_to_tile(*GOAL)
    assert result.ok, result.status

    return pathfinder, result


def fragile_segments(pathfinder, path):
    """Segments that die or take extra damage when replayed from +-2 px (independent of the planner)."""
    evaluator = pathfinder.catalog.evaluator
    bad = []
    for index, segment in enumerate(path.segments):
        for dx in (-MARGIN, MARGIN):
            probe = segment.start.clone()
            probe.x += dx
            outcome = evaluator.simulate(probe, segment.frames)
            if outcome.state.killed or outcome.damage_hits > segment.damage_hits:
                bad.append(index)
                break

    return bad


def signature(result):
    return (result.status, tuple(segment.note for segment in result.path.segments), round(result.path.total_cost, 3))


# -- the fragility probe ---------------------------------------------------------


def jump_from(pathfinder, x, name="jump:full:1"):
    catalog, planner = pathfinder.catalog, pathfinder.planner
    state = pathfinder.motion_state().clone()
    state.x, state.vx = float(x), 0.0
    action = next(a for a in catalog.actions(state, full=False) if a.name == name)

    return state, catalog.evaluate(state, action, record_trace=False), planner


def test_probe_agrees_with_an_independent_replay_at_every_start_pixel():
    pathfinder, _ = plan(pillar(2), 4 * 32 + 6)
    evaluator = pathfinder.catalog.evaluator
    flagged = unflagged = 0
    for x in range(250, 380):
        state, segment, planner = jump_from(pathfinder, x)
        if segment is None or segment.damage_hits or segment.end.killed:
            continue  # the jump itself is not viable from here
        penalty = planner._fragility(state, segment)
        replays_break = False
        for dx in (-MARGIN, MARGIN):
            probe = state.clone()
            probe.x += dx
            outcome = evaluator.simulate(probe, segment.frames)
            replays_break |= outcome.state.killed or outcome.damage_hits > segment.damage_hits
        assert (penalty > 0) == replays_break, f"x={x}"
        flagged += penalty > 0
        unflagged += penalty == 0
    assert flagged >= 2, "the scan must contain real edge cases"
    assert unflagged >= 20


def test_a_jump_that_clears_by_a_hair_is_flagged_and_a_roomy_one_is_not():
    pathfinder, _ = plan(pillar(3), 4 * 32 + 6)
    state, grazing, planner = jump_from(pathfinder, 294)
    assert grazing is not None and grazing.damage_hits == 0
    assert planner._fragility(state, grazing) == planner.fragile_penalty

    state, roomy, planner = jump_from(pathfinder, 298)
    assert roomy is not None and roomy.damage_hits == 0
    assert planner._fragility(state, roomy) == 0.0


def test_segments_far_from_any_hazard_are_not_probed():
    pathfinder, _ = plan(pillar(3), 4 * 32 + 6)
    planner = pathfinder.planner
    state = pathfinder.motion_state().clone()
    state.x, state.vx = 60.0, 0.0
    action = next(a for a in pathfinder.catalog.actions(state, full=False) if a.name == "walk:1")
    segment = pathfinder.catalog.evaluate(state, action, record_trace=False)
    assert segment is not None and segment.bbox[2] < 11 * 32
    # the probe is skipped by the hazard-index short-circuit, not by luck of the replay
    assert not planner.hazard_index.near(segment.bbox, 1)
    assert planner._fragility(state, segment) == 0.0


def test_penalty_is_off_when_set_to_zero():
    pathfinder, _ = plan(pillar(3), 4 * 32 + 6, fragile_penalty=0.0)
    state, grazing, planner = jump_from(pathfinder, 294)
    assert planner._fragility(state, grazing) == 0.0


# -- the planner prefers the roomier route ---------------------------------------


@pytest.mark.parametrize("height,x0", [(2, 236), (2, 238), (2, 249), (2, 359), (3, 241)])
def test_planner_takes_the_roomier_route_when_one_exists(height, x0):
    """Same world, same start: the cheap route grazes the pillar; pricing fragility finds one that does not."""
    free_pf, free = plan(pillar(height), x0, fragile_penalty=0.0)
    priced_pf, priced = plan(pillar(height), x0, fragile_penalty=25.0)

    assert len(fragile_segments(free_pf, free.path)) >= 1, "without the penalty the route grazes"
    assert fragile_segments(priced_pf, priced.path) == []
    assert priced.path.damage_hits == 0
    # the roomier route costs at most a little more time (often none)
    assert priced.path.total_ticks <= free.path.total_ticks + 10


def test_the_penalty_can_only_reduce_how_often_a_route_grazes():
    """Across a sweep of start pixels the priced route never grazes *more* often than the free one."""
    improved = 0
    for height in (2, 3):
        for x0 in range(236, 372, 5):
            try:
                free_pf, free = plan(pillar(height), x0, fragile_penalty=0.0)
                priced_pf, priced = plan(pillar(height), x0, fragile_penalty=25.0)
            except AssertionError:
                continue  # no route from this pixel at all
            before = len(fragile_segments(free_pf, free.path))
            after = len(fragile_segments(priced_pf, priced.path))
            assert after <= before, (height, x0)
            improved += after < before
    assert improved >= 1


def test_a_partial_improvement_is_still_an_improvement():
    free_pf, free = plan(pillar(3), 364, fragile_penalty=0.0)
    priced_pf, priced = plan(pillar(3), 364, fragile_penalty=25.0)
    assert len(fragile_segments(free_pf, free.path)) == 2
    assert len(fragile_segments(priced_pf, priced.path)) == 1


def test_penalty_is_paid_rather_than_failing_when_no_roomier_route_exists():
    free_pf, free = plan(pillar(2), 257, fragile_penalty=0.0)
    priced_pf, priced = plan(pillar(2), 257, fragile_penalty=25.0)
    assert [s.note for s in free.path.segments] == [s.note for s in priced.path.segments]
    assert priced.path.total_cost == pytest.approx(free.path.total_cost + 25.0)


def test_x_only_probe_does_not_price_vertical_slack():
    """Characterisation: a ~2 px gap under a low ceiling is x-independent, so it is not 'fragile'."""
    tunnel = [(DEATH_SPIKES, 12, 7, TileFlags.NONE)] + [(DIRT, x, 5, TileFlags.NONE) for x in (11, 12, 13)]
    free_pf, free = plan(tunnel, 4 * 32 + 6, fragile_penalty=0.0)
    priced_pf, priced = plan(tunnel, 4 * 32 + 6, fragile_penalty=25.0)
    assert priced.path.total_cost == pytest.approx(free.path.total_cost)
    assert fragile_segments(priced_pf, priced.path) == []


# -- determinism -------------------------------------------------------------------

WORLDS = {
    "flat": [],
    "wall": [(DIRT, 10, y, TileFlags.NONE) for y in range(5, 8)],
    "pillar2": pillar(2),
    "pillar3": pillar(3),
}
START = 4 * 32 + 6


@pytest.mark.parametrize("name", WORLDS)
def test_route_does_not_depend_on_the_time_budget(name):
    reference = signature(plan(WORLDS[name], START, budget_ms=3000.0)[1])
    for budget in (20_000.0, 60_000.0):
        assert signature(plan(WORLDS[name], START, budget_ms=budget)[1]) == reference


@pytest.mark.parametrize("name", WORLDS)
def test_route_is_machine_independent_under_an_expansion_cap(name):
    """When the expansion budget binds, the wall-clock must not change the outcome."""
    a = plan_capped(WORLDS[name], 25, 5_000.0)
    b = plan_capped(WORLDS[name], 25, 120_000.0)
    assert a == b


def plan_capped(extras, cap, budget_ms):
    pathfinder = planner_at(extras, START, max_expansions=cap, budget_ms=budget_ms)
    result = pathfinder.plan_to_tile(*GOAL)

    return (
        result.status,
        result.nodes_expanded,
        tuple(segment.note for segment in result.path.segments) if result.path else None,
    )


@pytest.mark.parametrize("name", WORLDS)
def test_repeating_a_query_in_one_process_gives_the_same_route(name):
    first = signature(plan(WORLDS[name], START)[1])
    for other in WORLDS:  # plan other worlds in between: no state may leak across pathfinders
        plan(WORLDS[other], START + 8)
    assert signature(plan(WORLDS[name], START)[1]) == first


KNOWN_PRUNING_MISS = pytest.mark.xfail(
    strict=True,
    reason="known: the guidance estimate is far above the true cost (192 vs 140 at the root) and prunes "
    "the best route from some start pixels, so a 1 px shift can cost ~16% more",
)


@pytest.mark.parametrize(
    "name,dx",
    [(name, dx) if (name, dx) != ("wall", -1) else pytest.param(name, dx, marks=KNOWN_PRUNING_MISS) for name in WORLDS for dx in (-1, 1)],
)
def test_one_pixel_of_start_x_does_not_change_the_route_class(name, dx):
    base = plan(WORLDS[name], START)[1]
    moved = plan(WORLDS[name], START + dx)[1]
    assert moved.path.goal == base.path.goal
    assert moved.path.damage_hits == base.path.damage_hits == 0
    assert moved.path.total_cost <= base.path.total_cost + max(2.0, 0.015 * base.path.total_cost)
    if name in ("flat", "wall"):  # unique optimum: the segment list must be identical
        assert [s.note for s in moved.path.segments] == [s.note for s in base.path.segments]


class _SlowClock:
    """``time`` stand-in whose ``perf_counter`` advances on every call: a machine ``step`` s slower per check."""

    def __init__(self, step):
        self.now = 1000.0
        self.step = step

    def perf_counter(self):
        self.now += self.step

        return self.now


@pytest.mark.parametrize("name", WORLDS)
def test_a_slow_machine_finds_the_same_route(name, monkeypatch):
    """Every wall-clock check is made to cost 30 ms; the expansion budget alone must decide the route."""
    import gtools.core.growtopia.physics.pathfinding.planner as planner_module

    reference = signature(plan(WORLDS[name], START, budget_ms=60_000.0)[1])
    monkeypatch.setattr(planner_module, "time", _SlowClock(0.03))
    slow = signature(plan(WORLDS[name], START, budget_ms=60_000.0)[1])
    assert slow == reference
