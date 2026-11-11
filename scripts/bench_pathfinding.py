#!/usr/bin/env python3
"""Benchmark the segmented pathfinder: kernel, actions, plans, follower.

Run from the repository root:

    .venv/bin/python scripts/bench_pathfinding.py
    .venv/bin/python scripts/bench_pathfinding.py --quick
    .venv/bin/python scripts/bench_pathfinding.py --json

What is measured (all on synthetic worlds built in code, so numbers are
comparable between runs):

``kernel``     ticks/s and evals/s for one walk action, on the compiled backend
               and -- for reference -- the pure-Python mirror;
``plan``       wall time to a cold plan of a flat 100-tile corridor and to a
               warm re-plan (same world, second query), plus a 3-high wall maze;
``follower``   path-follower ticks/s vs the raw controller ticks/s (the
               overhead is the per-tick capability profile rebuild);
``quality``    segments / ticks / expansions of each planned route.

The first run in a fresh process pays numba's compile cost once (cached on
disk afterwards); the kernel benchmarks warm up before timing.  ``--json``
prints the same numbers as one object for CI or spreadsheets.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from pyglm.glm import ivec2

from gtools.baked.items import DIRT, MAIN_DOOR
from gtools.core.growtopia.physics.controller import HITBOX, PlayerController
from gtools.core.growtopia.physics.pathfinding import SegmentedPathfinder
from gtools.core.growtopia.physics.pathfinding.actions import ActionCatalog
from gtools.core.growtopia.physics.pathfinding.fastkernel import FastEvaluator
from gtools.core.growtopia.physics.pathfinding.follower import PathFollower
from gtools.core.growtopia.physics.pathfinding.profile import CapabilityProfile
from gtools.core.growtopia.physics.pathfinding.snapshot import WorldSnapshot
from gtools.core.growtopia.player import Clothing, Player
from gtools.core.growtopia.world import Tile, World

FLOOR_Y = 8
STAND_Y = FLOOR_Y * 32 - HITBOX[1]


@dataclass
class Report:
    kernel: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    follower: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)


def make_world(width: int, *, height: int = 12, walls: tuple[tuple[int, int, int], ...] = ()) -> World:
    """A flat dirt floor plus optional ``(tx, from_ty, to_ty)`` wall columns."""
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(width)]
    tiles.append(Tile(fg_id=MAIN_DOOR, pos=ivec2(1, FLOOR_Y - 1)))
    for tx, y0, y1 in walls:
        tiles.extend(Tile(fg_id=DIRT, pos=ivec2(tx, y)) for y in range(y0, y1))
    world = World.from_tiles(tiles)
    world.players[1] = Player(net_id=1, clothing=Clothing())
    return world


def spawn(world: World, tx: int = 4) -> PlayerController:
    controller = PlayerController(world, net_id=1, send=None, auto_respawn=False)
    controller.spawn(tx * 32 + 6.0, STAND_Y)
    for _ in range(3):
        controller.step()
    return controller


def bench_call(fn, repeats: int) -> tuple[float, float]:
    """Return ``(mean_ms, stdev_ms)`` of ``fn`` over ``repeats`` calls."""
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - started) * 1000.0)
    return statistics.mean(samples), (statistics.pstdev(samples) if len(samples) > 1 else 0.0)


def bench_kernel(report: Report, *, width: int = 120, repeats: int = 200) -> None:
    world = make_world(width)
    controller = spawn(world)
    profile = CapabilityProfile.from_controller(controller)
    snapshot = WorldSnapshot(world)

    for name, evaluator in (
        ("numba", FastEvaluator(snapshot, profile)),
        ("python", FastEvaluator(snapshot, profile, use_numba=False)),
    ):
        state = evaluator.state_from_controller(controller)
        actions = ActionCatalog(evaluator).actions(state)
        walk = next((action for action in actions if action.name == "walk:1"), actions[-1])
        frames = walk.frames

        def run() -> int:
            outcome = evaluator.simulate(state.clone(), frames)
            return outcome.ticks

        ticks = run()  # warm-up (compiles the kernel on the numba path)
        started = time.perf_counter()
        total_ticks = 0
        for _ in range(repeats):
            total_ticks += run()
        elapsed = time.perf_counter() - started
        report.kernel[name] = {
            "backend_available": evaluator._nb is not None if name == "numba" else True,
            "ticks_per_eval": ticks,
            "evals_per_s": round(repeats / elapsed, 1),
            "ticks_per_s": round(total_ticks / elapsed, 1),
            "us_per_eval": round(elapsed / repeats * 1e6, 1),
            "us_per_tick": round(elapsed / max(total_ticks, 1) * 1e6, 3),
        }

    if "numba" in report.kernel and report.kernel["numba"].get("backend_available"):
        speedup = report.kernel["numba"]["ticks_per_s"] / max(report.kernel["python"]["ticks_per_s"], 1e-9)
        report.kernel["speedup"] = round(speedup, 2)


def plan_once(world: World, tx: int, ty: int) -> tuple[SegmentedPathfinder, Any, float]:
    controller = spawn(world)
    pathfinder = SegmentedPathfinder(controller)
    started = time.perf_counter()
    result = pathfinder.plan_to_tile(tx, ty)
    return pathfinder, result, (time.perf_counter() - started) * 1000.0


def bench_plans(report: Report, *, quick: bool) -> None:
    corridor = make_world(140)
    _, result, cold_ms = plan_once(corridor, 120, FLOOR_Y - 1)
    report.plan["corridor_cold"] = {
        "status": result.status.name,
        "ms": round(cold_ms, 2),
        "segments": len(result.path.segments) if result.path else 0,
        "ticks": result.path.total_ticks if result.path else 0,
        "expanded": result.nodes_expanded,
    }

    pathfinder, first, _ = plan_once(corridor, 120, FLOOR_Y - 1)
    started = time.perf_counter()
    warm = pathfinder.plan_to_tile(121, FLOOR_Y - 1)
    warm_ms = (time.perf_counter() - started) * 1000.0
    report.plan["corridor_replan"] = {
        "status": warm.status.name,
        "ms": round(warm_ms, 2),
        "segments": len(warm.path.segments) if warm.path else 0,
        "ticks": warm.path.total_ticks if warm.path else 0,
        "expanded": warm.nodes_expanded,
    }

    if quick:
        return

    maze = make_world(60, walls=tuple((tx, FLOOR_Y - 3, FLOOR_Y) for tx in (12, 24, 36, 48)))
    _, result, maze_ms = plan_once(maze, 54, FLOOR_Y - 1)
    report.plan["maze"] = {
        "status": result.status.name,
        "ms": round(maze_ms, 2),
        "segments": len(result.path.segments) if result.path else 0,
        "ticks": result.path.total_ticks if result.path else 0,
        "expanded": result.nodes_expanded,
    }


def bench_follower(report: Report, *, width: int = 80, steps: int = 240) -> None:
    world = make_world(width)
    controller = spawn(world)
    pathfinder = SegmentedPathfinder(controller)
    result = pathfinder.plan_to_tile(width - 8, FLOOR_Y - 1)
    if not result.ok or result.path is None or not result.path.segments:
        report.follower = {"status": result.status.name, "error": "no path"}
        return

    follower = PathFollower(controller, pathfinder, result.path)
    started = time.perf_counter()
    follower_ticks = 0
    for _ in range(steps):
        follower.step()
        follower_ticks += 1
        if follower.done:
            break
    follower_ms = (time.perf_counter() - started) * 1000.0
    follower_ticks = max(follower_ticks, 1)

    raw = spawn(make_world(width))
    started = time.perf_counter()
    for _ in range(follower_ticks):
        raw.step()
    raw_ms = (time.perf_counter() - started) * 1000.0

    report.follower = {
        "status": "done" if follower.done else f"budget after {follower_ticks} ticks",
        "ticks": follower_ticks,
        "replans": follower.replans,
        "reason": follower.reason,
        "follower_ticks_per_s": round(follower_ticks / (follower_ms / 1000.0), 1),
        "controller_ticks_per_s": round(follower_ticks / (raw_ms / 1000.0), 1),
        "overhead_ratio": round((follower_ms / max(raw_ms, 1e-9)), 2),
    }
    if result.path:
        report.quality = {
            "segments": len(result.path.segments),
            "kinds": [kind.name for kind in result.path.kinds()][:12],
            "ticks": result.path.total_ticks,
            "cost": round(result.path.total_cost, 1),
            "damage_hits": result.path.damage_hits,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--quick", action="store_true", help="skip the maze scenario and the follower run")
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of a table")
    parser.add_argument("--repeats", type=int, default=200, help="walk-action repetitions per backend (default 200)")
    args = parser.parse_args(argv)

    if not os.environ.get("PATHFINDING_NO_NUMBA"):
        try:
            import numba  # noqa: F401
        except Exception:  # pragma: no cover - environment dependent
            print("note: numba is not installed; the kernel benchmarks use the Python mirror only", file=sys.stderr)

    report = Report()
    bench_kernel(report, repeats=args.repeats)
    bench_plans(report, quick=args.quick)
    if not args.quick:
        bench_follower(report)

    if args.json:
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
        return 0

    kernel = report.kernel
    for name in ("numba", "python"):
        if name not in kernel:
            continue
        row = kernel[name]
        print(
            f"kernel {name:<6} {row['ticks_per_s']:>12,.0f} ticks/s   "
            f"{row['evals_per_s']:>10,.0f} evals/s   "
            f"{row['us_per_eval']:>7.1f} us/eval   {row['ticks_per_eval']} ticks/eval"
        )
    if "speedup" in kernel:
        print(f"kernel speedup: {kernel['speedup']}x")

    for label, row in report.plan.items():
        print(
            f"plan {label:<16} {row['status']:<10} {row['ms']:>8.2f} ms   "
            f"{row['segments']:>3} segments   {row.get('ticks', 0):>5} ticks   {row['expanded']:>4} expanded"
        )
    if report.follower:
        row = report.follower
        if "error" in row:
            print(f"follower: {row['error']} ({row['status']})")
        else:
            print(
                f"follower {row['ticks']} ticks: {row['follower_ticks_per_s']:,.0f} ticks/s "
                f"(raw controller {row['controller_ticks_per_s']:,.0f}, {row['overhead_ratio']}x) "
                f"replans={row['replans']}"
            )
    if report.quality:
        print(f"quality: {report.quality['segments']} segments, {report.quality['kinds']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
