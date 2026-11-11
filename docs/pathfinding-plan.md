# Pathfinding for `PlayerController` — implementation plan

Branch: `feat/pathfinding` (created from `dev`).
Status: **plan — not implemented yet**.

This document is the contract for the pathfinding feature. It is written against the
current `PlayerController` (`gtools/core/growtopia/physics/controller.py`, ~2.4k lines)
and the client model in `docs/netavatar-physics.md` / `docs/collision-port-backlog.md`.

---

## 1. Goal

Give the local avatar a planner that, from the live world, produces a **segmented**
route to a target and keeps it valid while the world, the avatar's `CharacterState`
and its clothing/mods change. It must be fast enough to re-plan mid-walk and must never
assume physics the controller does not actually implement.

Requirements (from the request):

1. works and **re-evaluates** when the world/environment changes;
2. **super fast**, with a **separate, super-optimized evaluator**;
3. obeys the controller's physics with **no hard-coded motion values** — the live
   `CharacterState` (SET_CHARACTER_STATE) and clothing mods decide what is possible;
4. **no machine learning**, no training, no learned weights or data files;
5. **segmented** paths: `WALK`, `JUMP`, `FALL`, `CLIMB`, `SWIM`, `SLOW_FALL`,
   `BOUNCE`, `BOUNCE_UP`, `DROP_THROUGH`, `WIND`, … one segment per movement method.

Non-goals for the first pass: multiplayer/NPC pathfinding, door/world transitions,
combat, item collection routing, GUI drawing of the path.

---

## 2. What the controller already gives us

The planner is built **on top of** the existing simulation, not beside it:

- Coordinates: `x/y` = collision-rect top-left; hitbox `20×30`; `TILE = 32`.
- `step()` = one fixed `1/60 s` tick: `_check_tile_mod` → vertical integration →
  horizontal acceleration → wind → gravity-well pull → X/Y interaction probes →
  per-pixel horizontal/vertical movement → settle → world clamp, then walk mods,
  dropped-object collection, STATE send, auto-respawn.
- Collision has two layers: movement `_can_enter_x/_can_enter_y` and interaction
  `_interaction_blocked` / `_is_ground`, both driven by the same tile data.
- Runtime motion parameters live in `controller.state` (`CharacterState`):
  `max_velocity`, `horizontal_accel`, `vertical_accel`, `velocity_in_water`,
  `jump_strength`, `flags`.
- Clothing/mods change motion: slow fall, floatie, water vehicles, climb gear,
  slippery, skating, mud, hay/snow (jump reduction), wind, gravity wells.
- Tile state changes are broadcast as `WorldEvent.TILE_UPDATE(x, y)` by `World`
  (`world.place_fg/bg`, `tile_change`, `update_lock`, damage toggles, …), giving the
  follower a native invalidation signal.

Key consequence: **the only trustworthy "what can this avatar do?" oracle is the
controller itself**, so the plan uses it both as a measurement device and as the
last-word validator.

---

## 3. Design principles

1. **No duplicated physics as the source of truth.**
   The fast evaluator is a performance mirror of `_simulate`, never the definition.
   A differential fuzz suite must prove tick-for-tick equality with `PlayerController`
   before any planner code is trusted.
2. **Capabilities are measured, not assumed.**
   A `CapabilityProfile` is built from the live controller (`state`, `fixed_dt`,
   hitbox, mods) plus bounded probe runs of the real controller (jump height, jump
   distance, fall speed, climb reachability). No motion constant is written into the
   pathfinding package; the few controller constants that are genuinely fixed
   (`JUMP_SPEED`, `MAX_FALL`, the air-control constants) are **imported** from
   `controller.py` so there is a single source of truth.
3. **Search over actions, not pixels.**
   A* expands *movement segments* (walk-to-perch, jump-arc, fall, swim leg, …) whose
   outcomes are produced by the evaluator. This is the requested segmentation and it
   makes the search space tile-scale instead of pixel-scale.
4. **Everything cacheable is keyed by (profile fingerprint, tile versions).**
   A `CharacterState` change or a changed tile invalidates exactly the cached edges
   that depend on it; untouched edges are reused on re-plan.
5. **Bounded work.**
   Every plan call takes a node budget and a wall-clock budget; it returns the best
   partial path (with `partial=True`) instead of blocking.
6. **Deadly and damaging are different classes, not one "hazard" bucket.**
   - **Deadly** (`ItemInfoType.DEADLY`, `DEADLY_IF_ON` while `IS_ON`, and the
     `TILE_DEADLY_IF_ON` flags2 bit while `IS_ON`) latches `PlayerController.killed`
     through `_kill`, which stops `_simulate` entirely and (with the default
     `auto_respawn`) teleports the avatar to the respawn. A route over an active
     deadly tile is therefore **unreachable, not expensive**: the planner never
     emits it. The only exception is the physics bypass the controller honours —
     `CharacterFlags.IGNORE_SPIKES` skips `_is_deadly` — and that is part of the
     capability profile, not a hard-coded assumption.
   - **Damaging** (`FIRE_DAMAGE`: lava / `ON_FIRE`; `ACID_DAMAGE`: acid;
     `DAMAGE`: pointy, `LIGHTNING_CLOUD` while on, `STEAM_LAVA_IF_ON` while on) is
     **not lethal in the engine**. It applies a one-shot event bit plus real
     kinematics: the X response inverts the horizontal velocity and clamps it to
     ≥ 300 px/s away from the tile; the Y response launches at −800 (or flips a
     rising velocity), clamps `vx` to ≥ 300 px/s in the facing direction and sets
     `damage_slip`. So a damaging tile can be **compromised (taken)**, and its
     launch can even be the *only* way to gain height. The planner models the
     exact trajectory and prices the hit with a configurable `damage_penalty`
     (plus an optional `max_damage_hits` budget), but a required damaging hit
     never by itself makes a route "no path". `IGNORE_LAVA` (which in this port
     gates the whole `_damaging_event` branch) is likewise a profile field.

---

## 4. Architecture

```
                    +-----------------------------+
                    |  PlayerController (live)    |
                    |  state / clothing / world   |
                    +--------------+--------------+
                                   |
             +---------------------+----------------------+
             |                                            |
    +--------v---------+                         +--------v---------+
    |  CapabilityProfile|                        |  WorldSnapshot    |
    |  (live + measured)|                        |  flat tile grid   |
    +--------+---------+                         +--------+---------+
             |                                            |
    +--------v--------------------------------------------v---------+
    |                     FastEvaluator                             |
    |  exact tick kernel over WorldSnapshot + CapabilityProfile     |
    |  (the super-optimized evaluation path)                        |
    +--------+--------------------------------------------+---------+
             |                                            |
    +--------v---------+                         +--------v---------+
    |   ActionCatalog  |                         |    Planner       |
    |  input programs  |<------------------------|  segmented A*    |
    +--------+---------+                         +--------+---------+
             |                                            |
    +--------v--------------------------------------------v---------+
    |                       ControllerOracle                        |
    |  real PlayerController on a ProbeWorld: segment synthesis +    |
    |  differential validation                                       |
    +--------+--------------------------------------------+---------+
             |                                            |
    +--------v---------+                         +--------v---------+
    |  PathFollower    |                         |  PathEvaluator    |
    |  replay + adapt  |                         |  fast path scoring |
    +------------------+                         +-------------------+
```

Flow for `plan_to(...)`:

1. `WorldSnapshot.sync()` (incremental; O(changed tiles)).
2. `CapabilityProfile.from_controller(...)`; if fingerprint changed → drop edge cache.
3. A* over perch nodes; for each candidate action ask `FastEvaluator.evaluate()`.
   Newly discovered, promising edges are optionally confirmed by the oracle.
4. Materialize a `Path` of `Segment`s (kind + input program + expected end state).
5. `PathFollower` replays it through the live controller; on deviation, dirty tile or
   profile change → incremental replan from the current live state.

---

## 5. Module layout

```
gtools/core/growtopia/physics/pathfinding/
    __init__.py       public API re-exports
    types.py          SegmentKind, InputFrame, InputProgram, Segment, Path, PlanResult
    profile.py        CapabilityProfile (+ fingerprint, measurement probes)
    snapshot.py       WorldSnapshot / TileGrid, ProbeWorld (snapshot-backed World)
    fastkernel.py     FastEvaluator — exact, allocation-light tick kernel
    evaluator.py      PathEvaluator — bulk cost/validity scoring with early exit
    actions.py        ActionCatalog — input programs + outcome classification
    oracle.py         ControllerOracle — real-controller micro-simulation
    planner.py        SegmentedPlanner — A*, edge cache, heuristic, budgets
    follower.py       PathFollower — replay, deviation detection, replanning
tests/
    test_path_snapshot.py
    test_path_profile.py
    test_path_fastkernel.py     differential fuzz (the correctness gate)
    test_path_segments.py       one test group per SegmentKind
    test_path_planner.py        scenario matrix
    test_path_follower.py       adaptation scenarios
    test_path_bench.py          opt-in performance smoke
scripts/
    bench_pathfinding.py
docs/
    pathfinding.md              durable design/evidence/API reference (after P1)
```

`physics/` is currently a namespace package; `pathfinding/__init__.py` makes the new
subpackage a regular import target.

---

## 6. Public API (target)

```python
from gtools.core.growtopia.physics.pathfinding import (
    SegmentedPathfinder, PathFollower, Path, Segment, SegmentKind,
)

pathfinder = SegmentedPathfinder(controller)          # reads world/state/clothing
result = pathfinder.plan_to_tile(42, 10)              # PlanResult
if result.path is not None:
    follower = PathFollower(controller, pathfinder, result.path)
    while not follower.done:
        follower.step()                               # set_input + controller.step()

# alternatives
pathfinder.plan_to_xy(x, y, tolerance=8.0)
pathfinder.plan_to_predicate(lambda s: ...)
follower.tick_inputs()                                # inputs only, external stepping
pathfinder.invalidate_tile(tx, ty)                    # manual (un-broadcast) changes
```

`Path` exposes `segments`, `total_cost`, `total_ticks`, `tiles` (bbox) and
`__iter__`. `Segment` exposes `kind`, `inputs`, `start`, `end`, `ticks`,
`cost`, `tiles_touched`, `volatile`, `evidence`.

No controller API break: the feature is additive. A convenience
`PlayerController.path_to(...)` may be added in P6 if it stays a thin facade.

---

## 7. Data model

```python
class SegmentKind(IntEnum):
    WALK          # grounded horizontal travel (surface tags: normal/mud/ice/wind)
    JUMP          # launch from ground; variants JUMP_OVER / JUMP_UP / JUMP_ACROSS
    FALL          # leave a ledge / walk off, airborne descent
    DROP_THROUGH  # deliberate fall through JUMP_DOWN (Cosmic Rain etc.)
    CLIMB         # climb grab / hang / climb-jump chain
    SWIM          # water travel, incl. paddle jumps
    SLOW_FALL     # parasol/glide descent while jump is held
    BOUNCE        # radial bounce (BOUNCY tile)
    BOUNCE_UP     # trampoline / momentum trampoline / steam launcher
    WIND          # being carried by a WIND tile
    WELL          # gravity-well assisted travel (modifier segments)
```

`InputProgram` = compact list of `(left, right, jump, ticks)` frames, so a whole
segment can be replayed deterministically. A segment's `end` state is the exact state
observed when the program was evaluated; the follower compares live state against it
within tolerances.

`MotionState` (evaluator/oracle) covers every field `_simulate` reads and writes:
`x, y, vx, vy, frac_x, frac_y, grounded, sliding, in_water, water_float,
water_enter_ms, mud, left_ground, damage_slip, climbing, double_jumped, facing_right`.

---

## 8. Physics fidelity — the core of the plan

### 8.1 CapabilityProfile (no hard-coded values)

`CapabilityProfile.from_controller(controller)` captures:

- `dt = controller.fixed_dt`, `hitbox = (controller.width, controller.height)`;
- live `CharacterState` fields (`max_velocity`, `horizontal_accel`,
  `vertical_accel`, `velocity_in_water`, `flags`);
- mods derived from the controller's own helpers (`_slow_fall_flags`,
  `_is_floatie`, `_has_water_vehicle`, `_climb_gear`, `_slippery_clothing`,
  `_wearing_skates`, `controller.hand_item` is irrelevant to motion);
- imported controller constants (`JUMP_SPEED`, `JUMP_REDUCED_SCALE`,
  `JUMP_CUT_ACCEL`, `MAX_FALL`, `WATER_VERTICAL_SCALE`, `SLIDE_ACCEL_SCALE`,
  `MUD_SPEED_SCALE`, `BOUNCY_SPEED`, `TRAMPOLINE_*`, `DAMAGING_*`,
  `WIND_OPPOSE_SPEED`, `GRAVITY_WELL_*`) as *references*, never copies.

Additionally, `profile.measure(controller)` runs short oracle probes (one jump on
flat ground, one fall from a fixed height, one water jump, one climb attempt) to
derive the practical envelope: `max_jump_height_px`, `max_jump_airtime_ticks`,
`max_horizontal_jump_px`, `max_fall_speed`, `climb_available`, `slow_fall_available`.
The planner's heuristics use the measured envelope, so a server-side
`SET_CHARACTER_STATE` change re-measures instead of trusting stale numbers.

`fingerprint()` hashes every field that can change motion. The follower compares the
live fingerprint every tick; a change triggers re-planning and edge-cache eviction.

### 8.2 WorldSnapshot / TileGrid

One pass over `world.tiles` builds flat, index-addressed arrays
(`index = y * width + x`):

- `fg_id`, `flags`, `parent_index`, plus per-tile derived bytes:
  `collision` (state-aware: COLLIDE_IF_ON/OFF resolved with `IS_ON`),
  `solid`, `platform` (JUMP_THROUGH), `jump_down`, `one_way_dir`, `wet`,
  `climbable`, `deadly` (state-aware `DEADLY` / `DEADLY_IF_ON` / `TILE_DEADLY_IF_ON`),
  `damage_event` (`NONE` / `FIRE` / `ACID` / `GENERIC`, state-aware for the `IS_ON`
  variants), `bouncy_kind` (BOUNCY / TRAMPOLINE / TRAMPOLINE_MOMENTUM /
  steam-on), `wind_dir`, `slippery`, `mud`, `gravity_well`.
  Deadly and damaging are separate columns **by design**: deadly tiles are route
  blockers, damaging tiles are traversable-with-cost and may launch the avatar.
- **Door/lock permissions are not pre-baked.** A tile whose passability depends on
  `CollisionPermissions` (GATEWAY, VIP_DOOR, FRIEND_ENTRANCE, ADVENTURE, FACTION,
  GUILD, CLOUD) is marked `permission_gated`; the fast kernel calls the controller's
  existing predicates (`_blocks_like_client` semantics) for those few tiles. This
  avoids re-implementing `canDoorPassedThrough` while keeping the hot path free of
  permission work.
- Per-tile `version` counter; `dirty(x, y)` increments versions of changed tiles and
  records a world epoch. `WorldEvent.TILE_UPDATE` drives it; manual changes can call
  `invalidate_tile`.
- `ProbeWorld` implements the minimal `World` surface the oracle controller touches
  (`width/height`, `get_tile`, `players`, `dropped`, `clock`, `index_tile`,
  `get_world_lock`, `is_local_player`, `update_local_respawn`,
  `get_respawn_position`, `tree_ready`), backed by the snapshot, so the oracle can
  run a real `PlayerController` without copying a `World` dict.

### 8.3 FastEvaluator (the separate super-optimized evaluator)

- Mirrors `_simulate` **exactly**, in the same order and with the same float
  operations, for one tick given an `InputFrame`.
- Replaces per-pixel `_blocked_x/_blocked_y` loops with a **swept-AABB check**:
  if no blocking tile can be touched anywhere in the step volume, apply the integer
  displacement directly (`x += steps`, `y += steps`), which is bit-identical to the
  pixel loop; otherwise fall back to the pixel loop. Same for `_settle`.
- Reuses a single mutable `MotionState`; no per-tick allocation; local variable
  caching; flat grid indexing; optional numpy only for snapshot preprocessing.
- `evaluate(state, program) -> Outcome` runs a program with early exits
  (grounded-and-idle, dead, water state settled) and returns
  `(end_state, ticks, end_reason, path_bbox)`.
- `PathEvaluator.score(path, state)` replays a whole candidate path with early exit
  and returns cost/validity; used for tie-breaks and for cheap segment reuse checks.

### 8.4 ControllerOracle (authoritative)

Runs a **real** `PlayerController` on a `ProbeWorld` + copied avatar fields. Used for:

- measuring the capability envelope;
- synthesizing each segment's exact input program and end state;
- validating finished plans end-to-end;
- the differential fuzz suite.

The oracle never defines behavior; it only measures. The fast evaluator is the fast
copy that must agree.

### 8.5 Correctness gate — differential fuzz

`tests/test_path_fastkernel.py` runs randomized scenes (floors, walls, platforms,
one-way, jump-down, water pools, wind, mud/ice, bouncy, trampolines, wells, climb
columns, doors) × random start states × random input programs, stepping both the real
controller and the fast kernel. Assertions: identical `x, y, vx, vy, grounded,
sliding, in_water, water_float, climbing, damage_slip, mud` at **every tick**
(exact floats, or ≤ 1e-9 where an operation order is provably equivalent).
No planner work is accepted until this suite is green.

---

## 9. Segmented search

### 9.1 Nodes

Perch node = `(tile_x, tile_y, stance)` where stance is a small enum
(`GROUNDED`, `AIRBORNE`, `WATER`, `CLIMB`, `PLATFORM`) plus the exact canonical
`(x, y, vx, vy)` that the action generator starts from. Canonical grounded stances
use the collision-rect centre of a tile (`x = tx*32 + 6`, feet on `ty*32`), matching
the existing test harness.

### 9.2 Action catalogue

Each action is a template + parameter search bounded by the profile envelope:

| Action | Parameter space | Produces |
|---|---|---|
| `walk_*` | direction, target column / stop condition | `WALK` |
| `jump_*` | direction, jump-hold ticks (cut), launch offset | `JUMP`, `JUMP_UP`, `JUMP_OVER` |
| `drop` | direction, step-off vs deliberate | `FALL` / `DROP_THROUGH` |
| `swim_*` | direction, paddle cadence | `SWIM` |
| `climb_*` | grab direction, jump-regrab chain | `CLIMB` |
| `glide_*` | direction, jump held | `SLOW_FALL` |
| `bounce_*` | none (radial) | `BOUNCE` |
| `launch_*` | none (landing) | `BOUNCE_UP` |
| `damage_launch_*` | direction, approach height | `DAMAGE_LAUNCH` (Y damaging response's −800 launch) |
| `wind_*` | direction / release timing | `WIND` |
| `well_*` | direction into the pull | `WELL` |

Endpoint classification is based on the **observed** state delta, not on the action
that was tried: e.g. a "jump right" that leaves the ground and lands 3 tiles right and
1 up becomes `JUMP_UP`; a jump that ends in water becomes `SWIM`; a fall that hits a
damaging row and is launched upward becomes `DAMAGE_LAUNCH`. That keeps segment kinds
descriptive rather than aspirational.

Damaging tiles are ordinary search space: the evaluator already reproduces the
knockback/launch exactly, so actions are allowed to cross them. The cost function adds
`damage_penalty` per damaging contact (and `max_damage_hits` can cap the total if a
caller wants a "no more than N hits" route). Lethal tiles are excluded before search
unless the profile says the controller's `IGNORE_SPIKES` / `IGNORE_LAVA` flags disable
them.

### 9.3 A*

- Priority queue keyed `(f = g + h, h, node)`; deterministic tie-break.
- `g` = ticks (time) + small action penalties (jump, hazard exposure) + risk flags.
  **Deadly** tiles (and `ON_FIRE`/lava/acid only when they kill — they do not) are
  never expanded: they latch `killed`, so the node is terminal and discarded.
  **Damaging** tiles are expanded; each damaging contact adds `damage_penalty`
  (default: several ticks) and increments `damage_hits`, bounded by
  `max_damage_hits` when set. This is what lets the planner "compromise" and take a
  hit — or deliberately ride a damaging tile's −800 launch — when it is the only or
  clearly shortest route, while still preferring a safe detour when one exists.
- `h` = admissible lower bound in ticks from a cached distance field: 8/4-connected
  Dijkstra over free tiles with weight `tile_size / (max_horizontal_speed * dt)`, or a
  simpler Chebyshev bound; both derived from the profile.
- Budgets: `max_expansions`, `time_budget_ms`, `max_path_segments`; on exhaustion
  return the best partial route (`PlanResult.partial = True`).
- Edge cache: `dict[(fingerprint, node, action_id)] -> Outcome`; each cached edge also
  stores the max tile version it touched, so validity is O(1) when popped.

### 9.4 Segment materialization

The winning node chain is converted into `Segment`s by re-running each action's input
program on the oracle (or reusing the fast outcome when confirmed by the oracle for
that profile fingerprint). Segments are merged where the method is identical and
continuous (e.g. consecutive `WALK`), then the whole path is replayed once in the
oracle from the live state; any mismatch aborts the plan rather than handing the
follower a lie.

---

## 10. Adaptation (re-evaluation)

`PathFollower` owns the live loop:

1. **Per tick**, compare the live `CapabilityProfile.fingerprint()` and the max tile
   version over the current segment's bbox with the values captured at plan time.
2. **Deviation check**: live `(x, y, vx, vy, grounded, in_water, climbing)` vs the
   segment's recorded trajectory. Tolerances: position 1.5 px, velocity 5 %, state
   booleans exact; two consecutive violations or a teleport-sized jump → re-plan.
3. **Timeout check**: a segment that exceeds its expected tick count by > 30 % →
   re-plan.
4. **World events**: subscribe to `WorldEvent.TILE_UPDATE`; increment the world epoch
   and mark the region. Segments whose bbox intersects a changed tile are invalid.
   Also expose `invalidate_tile()` for silently mutated worlds (tests, tools).
5. **Re-plan incrementally**: keep the prefix already executed; find the first
   invalid segment; plan from its start (or from the live state if the deviation is
   in the current segment) to the goal; splice. Cached edges make this cheap.
6. **Abort conditions**: death (`controller.killed`), goal unreachable with zero
   partial progress, budget exhausted with no progress; report a `PlanResult` reason.

Because the follower re-plans from the *live* state, any unmodelled server push
(`handle_set_pos`, knockback, bounce) is handled by the same mechanism without special
cases.

---

## 11. Performance plan

- Snapshot build: one O(tiles) pass; incremental O(changed tiles). Tests use small
  worlds; a 200×200 world is the benchmark target.
- Fast kernel: no allocation in the tick loop, flat arrays, swept-AABB shortcut.
  Target: **≥ 200k simulated ticks/s** on the reference scene (≈ 5 µs/tick).
- Planner: edge cache + bounded action templates. Target on a 100×60 mixed scene:
  **≤ 20 ms cold**, **≤ 5 ms warm** for a ~150-tile path; hard cap enforced by
  `time_budget_ms` (default 100 ms) with partial results.
- Re-plan: **≤ 5 ms** typical after a one-tile change (suffix reuse + cache).
- `scripts/bench_pathfinding.py` prints cold/warm/re-plan timings and tick throughput;
  `tests/test_path_bench.py` is opt-in (`-m bench`) so CI is not timing-flaky.

No neural nets, no training, no learned heuristics. All costs are analytic and
derived from the measured profile.

---

## 12. Test matrix

| Area | Tests |
|---|---|
| Snapshot | build/incremental sync, collision classification for every `ItemInfoCollisionType`, state-aware COLLIDE_IF_ON/OFF, wet/climb/hazard/bounce/wind/mud flags, version/epoch invalidation |
| Profile | fields mirror live `CharacterState`; fingerprint changes on state/clothing/flag change; measured envelope within controller truth; no motion literal outside `profile`/imports |
| Fast kernel | differential fuzz vs real controller (the gate), per-mechanic corpora: flat walk + stop, jump cut, ceiling, one-way, jump-through landing pixel, jump-down, water/floatie, wind, well, slide/mud, bounce, trampoline/steam, climb grab, **deadly kill latch, X damaging knockback, Y damaging −800 launch + damage_slip** |
| Segments | each `SegmentKind` synthesized and replayed through the oracle to the recorded end state, including `DAMAGE_LAUNCH` |
| Planner | flat walk, wall jump, gap jump, ledge drop, shaft fall, platform drop-through, pool swim, climb column, slow-fall descent, bounce route, trampoline route, wind conveyor, well assist, locked door blocked, **safe detour preferred over damaging route; mandatory damaging hit still returns a path; deadly route returns NO_SAFE_ROUTE**, no-path |
| Adaptation | bridge removed mid-walk, wall added, tile IS_ON toggled, `SET_CHARACTER_STATE` velocity/gravity change, clothing change (parasol/climb), knockback, teleport; verify replan and eventual arrival |
| Budgets | expansion cap, time cap, partial path, determinism (same scene → same path) |
| Perf | cold/warm/re-plan thresholds (opt-in), tick throughput |

Existing suites must stay green:
`.venv/bin/python -m pytest tests/test_physics_collision.py tests/test_physics_vertical.py tests/test_physics_hazards.py tests/test_player_controller.py -q`
plus the wind/gravity-well/clothing/walk-mod suites.

---

## 13. Phases and acceptance criteria

### P0 — evidence & skeleton (no behavior)
- Confirm segments against the controller: climb reachability (grab requires an
  interactive neighbour while the centre tile is climbable), swim ascent, platform
  landing, bounce/launch launch conditions. Record findings in `docs/pathfinding.md`.
- Add the package skeleton + `types.py` + API docstrings.
- **Accept:** import works; design doc lists every segment kind with the controller
  method that produces it.

### P1 — snapshot + probe world
- `snapshot.py` with `WorldSnapshot`, `TileGrid`, `ProbeWorld`, incremental sync and
  tile versions; `WorldEvent.TILE_UPDATE` wiring.
- **Accept:** snapshot tests green; a probe controller steps identically to a live
  controller on the same small world for 100 ticks.

### P2 — profile + fast kernel (correctness gate)
- `profile.py`, `fastkernel.py`; differential fuzz includes the **deadly kill latch**
  and both **damaging** responses (X knockback, Y −800 launch + `damage_slip`).
- **Accept:** fuzz corpus green with exact per-tick equality; benchmark shows
  ≥ 200k ticks/s on the reference scene.

### P3 — action catalogue + segment synthesis
- `actions.py`, `oracle.py`; per-kind segment builders and classifiers.
- **Accept:** every segment kind has a test that synthesizes it and replays it through
  the oracle to the recorded endpoint.

### P4 — segmented A* planner
- `planner.py` with node model, heuristic, budgets, edge cache.
- **Accept:** scenario matrix green; benchmark meets cold/warm targets; deterministic.

### P5 — follower + adaptation
- `follower.py` with fingerprint/version checks, deviation detection, incremental
  replan, `WorldEvent` subscription.
- **Accept:** adaptation scenarios green (world change mid-path, state change,
  teleport/knockback); re-plan target met.

### P6 — integration + docs
- `pathfinding/__init__.py` exports; optional demo “pathfind to cursor” hook;
  `docs/pathfinding.md` (design, evidence, API, port log); AGENTS.md section.
- **Accept:** demo can walk to a clicked tile; docs explain the model and known gaps.

### P7 — hardening
- Fuzz long-running mixed scenes, budgets, memory (edge cache cap/LRU), review pass.
- **Accept:** full targeted suite green; no unbounded cache growth; documented limits.

---

## 14. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Fast kernel silently drifts from controller | differential fuzz is a merge gate; oracle re-validates the final path |
| Climb mechanic is narrower than the name suggests (grab-only in the port) | measure reachability; generate climb edges only when the oracle proves them; document the limitation |
| Non-holonomic states (ice slide, wind, well) break “walk to tile” assumptions | stance includes velocity; actions are validated by simulation, not geometry |
| Permission-gated doors need live permissions | pre-mark such tiles and call the controller predicates; fingerprint permissions too |
| World mutations without `TILE_UPDATE` | per-tile version check + explicit `invalidate_tile`; follower re-checks bbox versions |
| Deadly/damaging conflated | separate `deadly` and `damage_event` columns; deadly = kill-latch terminal node, damaging = traversable + trajectory + `damage_penalty`; both covered by the fuzz gate |
| Path explosion in open worlds | tile-scale perch nodes + action templates + budgets + partial results |
| Timing thresholds flaky in CI | benchmarks opt-in; unit tests assert counts/budgets, not wall-clock |
| `CharacterState` changes mid-route | profile fingerprint per tick → full motion-edge invalidation and re-plan |
| Server position snaps | follower detects base-state jumps and re-plans from the live state |

---

## 15. Decisions to confirm before implementation

Defaults chosen (change if you prefer):

1. **Hazards:** **deadly** tiles are always route blockers (unless the live
   `CharacterFlags.IGNORE_SPIKES` disables them); **damaging** tiles are allowed and
   priced (`damage_penalty`, optional `max_damage_hits`) because the engine has no HP
   and the hit is a kinematic knockback/launch. The planner prefers a safe detour but
   returns a damaging route when it is the only or clearly shortest option.
2. **Follower ownership:** `PathFollower.step()` drives `controller.set_input(...)` +
   `controller.step()`; `tick_inputs()` is provided for callers that own the loop.
3. **Goal semantics:** success = collision rect overlaps the target tile column;
   `plan_to_xy` adds a tolerance; `plan_to_predicate` for custom goals.
4. **Re-plan trigger:** any profile/world/position deviation re-plans; there is no
   silent "push through" mode.
