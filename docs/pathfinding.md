# Segmented pathfinding — implementation reference

Branch `feat/pathfinding`. The contract (requirements, design decisions, acceptance
criteria) is [`docs/pathfinding-plan.md`](pathfinding-plan.md); this document is the
**durable reference** for what was built: the layers, the exactness gates, the API,
measured numbers and the known limits.

The guiding rule: **the live `PlayerController` is the only physics authority.**
Everything else (snapshot, profile, fast kernel, planner) exists to ask it *faster*,
never to replace it with hand-written motion constants.

---

## 1. Layers

```
World ──► WorldSnapshot ──► CapabilityProfile ──► FastEvaluator ──► ActionCatalog
  ▲          (flat grid,        (live CharacterState    (tick-exact       (frame
  │           per-tile ver)      + clothing + mods)      mirror)            programs)
  │                                                          │
  └── WorldEvent.TILE_UPDATE ◄── PathFollower ◄── SegmentedPlanner (A*) ◄─┘
```

| Module | Role |
|---|---|
| `types.py` | `MotionState`, `InputFrame`, `Segment`, `Path`, `PlanResult`, `SegmentKind`, `Stance` |
| `snapshot.py` | `WorldSnapshot` / `TileGrid`: flat per-tile arrays (fg, flags, collision, movement + hazard + mod flags), versions, `ProbeWorld` (world surface for the controller's own predicates), `PermissionView` |
| `profile.py` | `CapabilityProfile.from_controller`: the live `CharacterState` motion parameters, imported controller constants, clothing/mods booleans, permission clone, and a `fingerprint()` that invalidates caches when anything changes |
| `fastkernel.py` | `FastEvaluator`: a tick-for-tick Python mirror of `PlayerController._simulate`, plus `state_from_controller`, action-oriented probes and the shared stop predicates. This is the *reference* implementation |
| `numba_kernel.py` | `NumbaBackend`: the same algorithm compiled with `numba.njit` over one flat `int32` grid matrix. Selected automatically by `FastEvaluator` |
| `oracle.py` | `ControllerOracle`: replays frames on the real controller on a `ProbeWorld` (validation, ~10 k ticks/s) |
| `actions.py` | `ActionCatalog`: frame templates (`walk`, `jump`, `fall`, `drop`, `swim`, `climb`, `glide`, `bounce`, `launch`, `wind`, `well`) + observed-delta `SegmentKind` classification |
| `planner.py` | `SegmentedPlanner`: weighted A* over **segment endpoints** (not pixels), edge cache keyed by profile fingerprint + tile versions, node-object parent links |
| `pathfinder.py` | `SegmentedPathfinder`: the facade (`plan_to_tile`, `plan_to_xy`, `plan_to_predicate`, `plan_from_current`, `invalidate_tile`) |
| `follower.py` | `PathFollower`: replays the segment inputs on the real controller, detects deviation / world change / profile change, re-plans |
| `autopilot.py` | `PathAutopilot`: host-loop adapter (`plan_to_tile` / `advance` / `cancel`) for callers that already call `controller.step()`; used by the demo |
| `evaluator.py` | `PathEvaluator`: cheap static scoring of a finished path (cost, damage, clearance) |

### Why two kernels

`FastEvaluator` is readable and is the source of truth for *semantics*.
`NumbaBackend` is the "super-optimised path" requirement: the same branch structure
compiled once (cached on disk), with no Python objects in the hot loop.

They are kept interchangeable by construction:

- `FastEvaluator.simulate` / `.simulate_tick` delegate to the compiled backend when it
  is available, the state's static permissions match the profile, and the stop
  predicate is one of the structured rules (`ActionCatalog` tags its closures with
  `_nb_stop`). Anything else falls back to the Python implementation, so the API and
  the tests never depend on numba being installed.
- `PATHFINDING_NO_NUMBA=1` (environment) or `FastEvaluator(..., use_numba=False)`
  forces the reference path — the escape hatch for debugging a divergence.

### Grid data

One `(NFIELDS, width*height)` `int32` matrix (`G_*` rows): `fg_id`, `flags`,
`collision`, `blocks`, `platform`, `jump_down`, `one_way`, `gated`, `deadly`,
`deadly_if_on`, `damage`, `damage_if_on`, `bouncy`, `wind`, `wet`, `climbable`,
`slippery`, `mud`, `well_range`, plus three derived rows for permission gates. The
matrix is cached per `(snapshot id, snapshot epoch)` and the gate rows per profile
fingerprint, so re-planning on an unchanged world reuses it.

Permission-gated tiles (doors, gates, adventure/cloud/faction/guild tiles) cannot be
re-evaluated inside the compiled kernel — they need the controller's lock model and
the tile extras. They are resolved **once** into `G_GATE_ON` / `G_GATE_OFF` (the two
`IS_ON` states) with the controller's own `_blocks_like_client`, and one case stays
dynamic in the kernel: `LOCKED_ADVENTURE_DOOR` reads the avatar's five-slot
touched-tile cache (`G_GATE_DYN`). That is the only permission fact that changes
*within* one evaluation, because `_cache_touch` fills it as the avatar touches tiles.

Consequence: a gate whose resolution depends on something the snapshot does not
version — e.g. a `StormyCloudTile` extra's solid counter, or an access list mutated in
place — is seen at snapshot-build time. Bump the tile version (`WorldEvent.TILE_UPDATE`
does this) when such a tile changes.

The steam launcher clears `IS_ON` on landing; both kernels record that as a
`flag_overrides` entry on the motion state, so later ticks read the cleared flag
without mutating the snapshot.

---

## 2. Exactness gates

The planner is only as good as the kernel, so every physics change is gated by
differential tests rather than by inspection:

| Suite | What it pins |
|---|---|
| `tests/test_path_fastkernel.py` (27) | **Default backend vs the real controller**, field by field after *every* tick: walking/jumping/cut, walls/ceilings, all collision overrides, water/floatie/vehicle, wind/mud/ice/slow-fall, radial bounce, trampolines, steam, climb grabs, gravity wells, antigravity, snow/hay jump reduction, **deadly** (kill latch) vs **damaging** (X knockback, Y −800 launch + slip) |
| `tests/test_path_numba.py` (8) | **Compiled backend vs the Python reference**, same scenarios plus the whole `Outcome` (ticks, reason, bbox, event flags, tick trace), the touched-tile cache and the steam overrides |
| `tests/test_path_planner.py` (8) | route/no-route/budget cases, determinism, oracle validation, and a **segment-replay regression**: every segment replayed from its own start must reach its recorded end and consecutive segments must join |
| `tests/test_path_segments.py` (11) | per-kind synthesis: walk, jump-over, jump-up, fall, swim, climb, bounce, bounce-up, damage-launch, wind, well |
| `tests/test_path_snapshot.py` (3) / `test_path_profile.py` (3) | snapshot arrays + version accounting; profile fingerprint invalidation |
| `tests/test_path_follower.py` (5) | goal, wall added mid-route, teleport, `CharacterState` change, path scoring |

The deadliness model matters: a **deadly** tile latches `state.killed` and the
simulation stops (`PlanStatus.NO_SAFE_ROUTE` unless `IGNORE_SPIKES` disables it);
a **damaging** tile is traversable — it costs `damage_penalty`, may knock the avatar
sideways (clamped to ±`damaging_knockback_speed`) or launch it up
(`damaging_launch_speed`, `damage_slip`), and it can be required to reach a goal.
`IGNORE_LAVA` / `IGNORE_SPIKES` come from the live `CharacterState.flags`, not from a
constant.

---

## 3. API

```python
from gtools.core.growtopia.physics.pathfinding import SegmentedPathfinder, PathFollower

pathfinder = SegmentedPathfinder(controller)          # reads the live state
result = pathfinder.plan_to_tile(tx, ty)               # or plan_to_xy / plan_to_predicate
if result.ok:
    follower = PathFollower(controller, pathfinder, result.path)
    while not follower.done:                           # owns controller.step()
        follower.step()
else:
    print(result.status.name, result.reason)           # e.g. NO_SAFE_ROUTE

# external loops: feed the input, step the controller yourself, then observe
direction, jump, *_ = follower.tick_inputs() or (False, False)
controller.step()
follower.observe()
```

### Host loop that owns `step()` (`PathAutopilot`)

`tick_inputs`/`observe` split a tick in two, which is easy to misuse when the host
loop already steps the controller (the demo does). `PathAutopilot` collapses them
into one call per tick:

```python
from gtools.core.growtopia.physics.pathfinding import PathAutopilot

autopilot = PathAutopilot(controller)                  # or PathAutopilot(controller, pathfinder)
result = autopilot.plan_to_tile(tx, ty)                # result.path / autopilot.status
while autopilot.active:
    autopilot.advance()                                # may call set_input(...)
    controller.step()                                  # the physics engine
```

**The autopilot never writes avatar state.** Planning observes the controller
(`CapabilityProfile`, `motion_state`) and evaluates cloned `MotionState`s on a
`ProbeWorld`; execution writes only `set_input(left, right, jump)` — `step()`
produces the motion. `tests/test_path_follower.py` pins this with a proxy controller
that raises on any attribute write, covering the planner and the autopilot together.

`advance()` must be called at most once per `controller.step()` (it pairs the input
it wrote with the observation of the step it produced). `cancel()` clears the inputs
and leaves the avatar exactly where the physics left it. `progress`,
`current_kind`, `replans`, `path` and `status` are read-only views for a UI/overlay.

### Demo integration

`gtools/core/growtopia/physics/demo.py` wires it up:

| Action | Effect |
|---|---|
| **Ctrl+Left-Click** a tile (or right click → *Pathfind here*) | plans and starts following |
| any movement key (A/D/W/arrows/space) | cancels the autopilot and hands control back |
| right click → *Stop pathfinding*, or the menu button | cancels |
| menu → *Pathfinding* | target, status, segment breakdown, damage hits, live tick/replan counters, overlay toggles |

The overlay (2D view) draws one line per segment coloured by the *observed*
`SegmentKind` (green `WALK`, yellow/orange jumps, blue `FALL`, cyan `SWIM`,
magenta `CLIMB`, purple bounces, teal `WIND`, red `DAMAGE_*`), dims the part already
traversed, thickens the segment being executed, labels the kinds (`!` = the segment
takes damage hits), outlines the goal tile and traces the avatar's recent path.
Coordinates go through `Camera2D.world_to_screen` plus the renderer's
`_image_origin`, since the world is drawn into an FBO.

- `plan_*` returns `PlanResult(status, path, reason, nodes_expanded, elapsed_ms,
  profile_fingerprint)`; `status ∈ {FOUND, NO_SAFE_ROUTE, UNREACHABLE, PARTIAL, BUDGET}`.
- Goal semantics: the collision rect overlaps the target tile **or** stands on its top
  edge; `plan_to_xy` uses a centre-distance tolerance.
- `walk_tiles` splits long straight walks into segments (`SegmentKind.WALK`), so a
  route is a list of resumable movement chunks rather than one giant replay.
- Segment kinds are classified from the **observed** state delta, not the attempted
  action: a "jump" into water is `SWIM`, a damage launch is `DAMAGE_LAUNCH`.
- Adaptation: `PathFollower` compares per tick the controller state against the
  segment trace (`position_tolerance`, `velocity_tolerance`), the profile fingerprint
  and the tile versions of the segment's bbox; any mismatch re-plans
  (`replan_limit`, default 8). `World.subscribe(WorldEvent.TILE_UPDATE, ...)` feeds
  `invalidate_tile`, so a bridge disappearing under the path replans even when the
  avatar has not moved yet.

Knobs on `SegmentedPathfinder`: `damage_penalty`, `walk_tiles`, `max_expansions`
(4000), `time_budget_ms` (250), `max_damage_hits`, `max_segments` (64),
`heuristic_weight` (1.5, weighted A*), `validate` (**default off** — a full
`ControllerOracle` replay costs ~110 ms per 1100-tick path; the follower's per-tick
trace comparison catches drift for free, so enable it in CI or when debugging).

---

## 4. Measured performance

`PYTHONPATH=. .venv/bin/python scripts/bench_pathfinding.py` — one warm run on the
development machine (numba cache warm; per-run variance is a few percent):

| Benchmark | Result |
|---|---|
| walk action, compiled kernel | **~0.8 M ticks/s**, ~22 k evals/s, ~45 µs per 35-tick eval |
| walk action, Python mirror | ~0.13 M ticks/s, ~3.7 k evals/s |
| kernel speedup | **~5–6×** |
| flat corridor, 140 tiles wide, target tile 120 | **~16 ms** cold, **~2.7 ms** warm re-plan, 17 expansions |
| maze, 60 wide with four 3-high walls | **~22 ms**, 10 segments, 28 expansions |
| follower vs raw controller | **~13.3 k ticks/s vs ~21.7 k** (1.6× overhead — the per-tick capability-profile rebuild), no re-plan needed on a clean route |

For scale: the physics itself runs a 60 Hz tick, so 13 k ticks/s is ~220× real time
and the warm re-plan budget (250 ms) is ~15× the observed cost on these maps.

Cost notes:

- The first `FastEvaluator` in a *fresh* process pays numba's compile cost
  (~0.2–0.3 s, a few ms from the on-disk cache). `NumbaBackend` warms every kernel
  function in `__init__`, so that cost lands **outside** the planner's
  `time_budget_ms` and cannot turn a first plan into a spurious `BUDGET` result.
- Per-evaluation Python cost (encode/decode state, frame arrays, `Outcome`) is ~10 µs,
  so very short actions amortise the kernel speedup less than long ones.
- `_rebuild()` per plan re-syncs the snapshot and rebuilds the profile (~1–5 ms
  depending on world size); the compiled matrix is reused across re-plans while the
  epoch and fingerprint are unchanged.

---

## 5. Known limits / next steps

- **Gate resolution is snapshot-time** (§1): rare dynamic extras (storm-cloud solid
  counter, in-place access-list edits) need a version bump to be seen.
- The compiled kernel is a *transcription*, so any physics change must touch both
  kernels; the differential suites exist to make that safe, but review both diffs.
- `FastEvaluator` mirrors `_simulate`, not the whole `step()`: walk-over item mods
  (tractor/plows), STATE sending, auto-respawn and dropped-object collection are
  deliberately outside the search (the follower drives the real controller, so they
  still happen live).
- Weighted A* (`heuristic_weight=1.5`) is not cost-optimal by design: it cuts
  expansions ~9× on long corridors for ~0.4 % extra path length. Set it to `1.0` for
  optimal routes.
- `validate=False` by default (see §3); the planned oracle replay is opt-in.
- The demo overlay is 2D-only (`WorldRenderer.mode_3d` skips it) and the segment
  lines are straight start→end chords: the exact trajectory is in `Segment.trace`
  if a future overlay wants the per-tick polyline.
- Doors/world transitions, multiplayer avatars and item-collection routing are
  out of scope (see the plan's non-goals).

---

## 6. Reproducing the evidence

```sh
# the two correctness gates
.venv/bin/python -m pytest tests/test_path_fastkernel.py tests/test_path_numba.py -q

# planner / follower / snapshot / profile / segments
.venv/bin/python -m pytest tests/test_path_planner.py tests/test_path_follower.py \
    tests/test_path_snapshot.py tests/test_path_profile.py tests/test_path_segments.py -q

# the physics the kernel mirrors
.venv/bin/python -m pytest tests/test_physics_collision.py tests/test_physics_vertical.py \
    tests/test_physics_hazards.py -q

# numbers
PYTHONPATH=. .venv/bin/python scripts/bench_pathfinding.py          # table
PYTHONPATH=. .venv/bin/python scripts/bench_pathfinding.py --json   # machine-readable
```

Reference-kernel run (no numba): `PATHFINDING_NO_NUMBA=1 .venv/bin/python -m pytest
tests/test_path_fastkernel.py -q`.
