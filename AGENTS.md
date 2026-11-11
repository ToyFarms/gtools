# AGENTS.md — working in `gtools`

Practical guide for agents working in this repository, with an emphasis on
reverse-engineering the Growtopia client (`Growtopia.exe.i64`) through the
`gt` IDA MCP tools.

## 1. What this repo is

`gtools` is a Python toolkit around Growtopia: packet/world parsing, a baked
item database, GUI tooling, and a local-player physics engine used by a demo.
It is **not** a full game client — the physics engine simulates one local
player, and **tests are the contract**.

| Path | Role |
|---|---|
| `gtools/core/growtopia/physics/controller.py` | `PlayerController` — the local player: physics port + outbound tile-change flow (the port target) |
| `gtools/core/growtopia/physics/demo.py` | interactive demo, not required by tests |
| `gtools/core/growtopia/world.py` | `World`, `Tile`, `TileFlags`, `TileExtra` subclasses (`LockTile`, `VipEntranceTile`, `FriendsEntranceTile`, `StormyCloudTile`, ...) |
| `gtools/core/growtopia/items_dat.py` | `ItemInfoType`, `ItemInfoCollisionType`, `item_database` |
| `gtools/core/growtopia/packet.py`, `player.py` | tank packets, `CharacterState`/`CharacterFlags`, `Clothing` |
| `gtools/baked/items.py` | generated item-id constants |
| `tests/test_physics_*.py` | pytest suites for physics (collision / vertical / hazards) |
| `docs/netavatar-physics.md` | the full reverse-engineering reference — ~95 % accurate, **not gospel** |
| `docs/netavatar_type.h` | explicit `NetAvatar` layout applied to the IDB |
| `docs/lock-permissions.md` | lock / build-permission model (client-verified vs `[server-side]`) |
| `docs/collision-port-backlog.md` | the two-layer collision model + the ported per-type checklist |
| `scripts/export_ida_pseudocode.py` | resumable all-function pseudocode exporter (retries, focus helper, size guard) |
| `scripts/decompile.py` | one-shot decompile wrapper (cold-start/focus/repair/stale-type auto-recovery) |
| `docs/ida-pseudocode-export.md` | root cause + usage/output for the pseudocode export |

## 2. Environment

- Always use the venv: `.venv/bin/python ...` — the system Python lacks the deps.
- Physics tests:
  `.venv/bin/python -m pytest tests/test_physics_collision.py tests/test_physics_vertical.py tests/test_physics_hazards.py -q`
  (the full suite is slow / times out; run targeted files).
- Item lookup:
  `.venv/bin/python -c "from gtools.core.growtopia.items_dat import item_database as db; i = db.get(4530); print(i.name, i.item_type.name, i.collision_type.name)"`
- Item data (`resources/items.dat`) is loaded through `gtools.setting.appdir`.
- The repo usually runs as **root** but belongs to `andra`; the local git
  identity is `ToyFarms <shafarrahman@gmail.com>` (already set).
- `opencode.json` is the local MCP config and `.opencode/` is agent state —
  **never commit either**.
- `/todo-add` is a user-side plugin and cannot be used by agents; keep
  checklists in repo files instead.
- The goal plugin has been seen truncating objectives to `F` (harness bug); if
  such a goal exists, ignore/leave it.

## 3. Reverse-engineering the client (IDA via the `gt` MCP tools)

The client is analysed in IDA (image base `0x140000000`) and driven through the
`gt` tool namespace. The loop:

1. **Find** — `lookup_funcs` (address or name, auto-detected), `list_funcs`
   (`{filter: "substring"}`), `xrefs_to`, `find` (string / immediate /
   data_ref / code_ref).
2. **Read** — `scripts/decompile.py` (robust wrapper, see below) or the raw
   `decompile`; `disasm` / `get_bytes` when it misbehaves.
3. **Cross-check the asm** for every branch you are porting — the decompiler
   is lossy around booleans, registers and float/int punning.
4. **Annotate** the IDB as you verify: `rename` (`{batch: {func: [...]}}`),
   `set_comments`, `set_type`. Past sessions renamed/commented many POIs, so
   `lookup_funcs` by name often works; keep that habit.
5. **Implement + test** in `gtools`, then commit.

Tool calls go through the Code Mode `execute` tool, e.g.:

```js
const d = await tools.gt.decompile({addr: "0x140554c10"});
return d.pseudocode;
```

### Decompiling: `scripts/decompile.py` first

The raw MCP `decompile` is GUI automation (F5) and fails in known ways. The
wrapper applies every verified fix automatically inside a single run:

```sh
.venv/bin/python scripts/decompile.py 0x140554c10              # pseudocode to stdout
.venv/bin/python scripts/decompile.py handleSetCharacterState  # by name
.venv/bin/python scripts/decompile.py CanPassThroughTile --json
.venv/bin/python scripts/decompile.py 0x140512080 --out /tmp/opencode/move.c
```

- auto-detects the live MCP port (`.ida-mcp/instances/*.json`; `--url`
  overrides) and resolves names through `lookup_funcs`;
- retries cold-start "No pseudocode widget" misses, follows the server's
  offload URL (full output, never the 1 KB preview), and waits out
  giant-function stalls (`lookup_funcs` probe) instead of stacking timeouts;
- on `Decompiler action failed` runs the UIA focus helper once and retries —
  this briefly activates the IDA window (the verified cure); `--no-steal`
  skips when IDA is in the background, `--no-focus` disables it;
- on persistent "No pseudocode widget" undefine/redefines the function
  (stub-size guarded) and retries; `--no-fix` disables;
- on `->?` output re-applies the prototype (placeholder → real, **validated
  first**) and re-decompiles; prototypes with unnamed ordinal types (`#476`)
  are skipped without touching the IDB; `--no-fix` disables;
- refuses `sub_1402E5B40`-sized functions (> 0x80000 bytes) unless
  `--allow-large` is passed.

Only stdout carries pseudocode/JSON, notes go to stderr. Exit codes: 0 ok,
1 decompile failure, 2 setup/resolution error.

### IDA / MCP quirks (hard-won)

- **`No pseudocode widget for this function after decompilation` — verified
  root cause: the plugin only polls for ~2 s.** `decompile` drives IDA Free's
  GUI (F5 `hx:GenPseudo`, no Hex-Rays SDK) and polls for the pseudocode widget
  for 40 × 50 ms. IDA Free's GUI/cloud decompiler takes **~2.3–2.7 s for the
  first decompile after idle** (then ~0.4–0.6 s per function while warm), so
  the first call after idle fails and an **immediate retry succeeds in
  0.03–0.1 s** from the cache. A retry with a small backoff is enough; no
  human needed. Only extend the plugin poll (or poll across event-loop yields)
  if changing the plugin itself. After all retries fail, `No pseudocode
  widget` is often IDA's **"call analysis failed"** instead: the MCP can
  repair it with `undefine` + (`define_code` +) `define_func` so IDA
  re-analyses the function. `scripts/export_ida_pseudocode.py --repair-failed`
  automates both variants and rejects stubs smaller than 75 % of the original
  (so a failed repair is logged, never exported as truncated pseudocode).
- **`Decompiler action failed (hx:GenPseudo)` (returns in ~0.01 s) is a
  keyboard-focus problem.** F5 is context-sensitive; it only works when the
  disassembly view (`IDAView`) has keyboard focus. The plugin's
  `activate_widget("IDA View-A")` does not always restore it after it has
  closed a pseudocode tab, or when another dock (Local Types, Strings, the CLI
  line edit) is focused. Manual cure: click IDA and press `Tab`. Programmatic
  cure (Windows/WSL): UIA-select the `IDA View-A` tab item; helper
  `focus_ida_view()` in `scripts/export_ida_pseudocode.py` does exactly this.
  It is **foreground-aware**: when another application is active it exits 42
  (returns `"skipped"`) instead of activating IDA, so a running export never
  steals the foreground unless `--allow-focus-steal` is passed. The exporter
  calls it at most once per function and only for this error (not for
  cold-start widget misses, and not periodically; `--focus-every` is 0 by
  default). A single failed call is often self-curing on the next call, but
  repeated failures can leave IDA stuck.
- **Giant functions can freeze IDA for minutes.** Decompiling
  `sub_1402E5B40` (1 MB of code) kept IDA unresponsive with 4.4 GB RSS and had
  to be killed. Functions above ~16 KB are rare (15 of 22,298) but risky;
  skip them by default and attempt them one at a time only while watching
  IDA. `disasm` is the safe fallback for those. For all-function exports use
  `scripts/export_ida_pseudocode.py` (see `docs/ida-pseudocode-export.md`):
  it retries cold starts, fixes focus, skips >16 KB, and resumes per file.
- **Large tool outputs are offloaded by the MCP server.** Results over ~30 KB
  arrive truncated (`pseudocode` cut to ~1 KB) with `_output_truncated`,
  `_total_chars`, `_output_id`, `_download_url` and `_download_hint`. Fetch
  `_download_url` (Code Mode `fetch`, replacing `0.0.0.0` with `127.0.0.1`,
  or `curl`) to get the full JSON — a 37 KB function yielded
  `_total_chars: 200369`. Direct stateless `curl` calls to the MCP endpoint
  bypass the offload envelope and return the full payload inline.
- **Decompile one function at a time.** The tool is GUI automation; batched
  `decompile` calls have crashed IDA in past sessions. Sequential awaits
  inside one `execute` usually work, but call them one at a time when in
  doubt.
- `->?` in decompiled output means the function's cached type is stale. Fix
  with `set_type` to `void __fastcall NAME(void *this)` and back to the real
  signature (e.g. `void __fastcall NAME(NetAvatar *this)`), then re-decompile.
  This fixed `fillTankStatePacket`, `setJumpHeld`,
  `handleSetCharacterState` and `updateBlockStateFromPlayerInteraction` in
  earlier sessions. (Distinct from the widget error above, which is view
  state.) `scripts/decompile.py` does this automatically, but re-applies the
  captured signature as a no-op check first: unnamed ordinal prototypes
  (`#476 *ctx`) cannot be set through `set_type` at all, so they are skipped
  instead of leaving the function half-modified.
- **Persistent call-analysis failures can be a callee-prototype problem.**
  `sub_1400298D0` and `sub_140029920` refused to decompile even after
  undefine/redefine. The cause was `Log` (0x140029E50): IDA had inferred an
  8-named-arg variadic prototype
  (`AppContext *(CHAR *, BYTE *, int *, __int64, char, unsigned __int16, int, _BYTE *, ...)`),
  which broke call analysis in its callers. Setting it to
  `void __fastcall Log(const char *format, ...)` with `set_type` made both
  callers decompile instantly (and `Log` itself now shows a normal `va_list`).
  When a function resists repair, decompile its callees / inspect their
  prototypes (`export_funcs` format `prototypes`) before assuming the body is
  bad.
- **`disasm` is the reliable fallback** when `decompile` refuses. Entire
  branches were ported straight from the assembly
  (`getGuildDoorRequiredRank`, `canFriendEntrancePassedThrough`, `isLockTile`,
  `toggleLockedAndSetParentIndex`, `handleSendLock`). `offset` is in
  **instructions**, not bytes.
- `get_bytes` takes `regions: [{addr, size}]` — the key is `regions`.
- `find_bytes`: `??` is a single-byte wildcard; a single `?` is **not** a
  nibble wildcard (patterns silently match nothing). Displacements like `+0x12`
  can be encoded as disp8 (`C6 4? 12`) — search the actual encoding or
  `C6 ?? 12`.
- `xrefs_to_field` returns nothing in this IDB. Sweep `find_bytes` over field
  displacements (e.g. `89 ?? F8 00 00 00` for writes to `+0xF8`) and group the
  hits with `lookup_funcs`.
- Structs: `search_structs` + `read_struct` give exact offsets and field names
  — prefer them over guessing from pseudocode. The applied `NetAvatar` type
  comes from `docs/netavatar_type.h`.
- `->?` in decompiled output means the function's cached type is stale; the
  `set_type` refresh above fixes it.
- Rename/comment freely; it persists in the IDB and makes later sessions
  faster.

### Decompiler traps already hit

- **Booleans are the most error-prone part.** Register maps (`edx`, `r8`),
  negated conditions and `int`/`float` punning (`*(float*)&tile->flags` in
  `moveByPixels`) all show up. Always cross-check the asm for the branch you
  are porting.
- IDB names can lie: `CanPassThroughTile` is **not** the movement predicate —
  it is the interaction/wall-response gate.
- `avatar+0x13C` is the **user id**, not an item id.
- `tile+0x12` is a separate `isOn` active byte; the collision type is
  `tile+0x14`.
- The `isBreakTap` argument flips platform handling in `CanPassThroughTile`
  (movement/ground use `0`, interaction probes use `1`).
- Field names in the IDB (`guildLockUnk2`, `placedTimestamp`, `gap80`, ...)
  are reverse-engineering guesses — verify the consumer code before trusting
  them.

## 4. Client reference (general)

### Structures

- Client `Tile` (0x90 bytes): `+0x04 fg`, `+0x06 bg`, `+0x08 flags (u16)`,
  `+0x0A tileX`, `+0x0B tileY`, `+0x0C index`, `+0x12 isOn`,
  `+0x14 collisionType`, `+0x18 bound_x/y/w/h`, `+0x28 extra`,
  `+0x4C nextUpdateMs`, `+0x5A hashOrUniqueID`, `+0x6C parent_index`.
  (`read_struct Tile` has the full layout.)
- Client `TileExtra` (344 bytes): `+0x08 type`, `+0x09` door-state byte
  (`0x40`/`0x80` bits), `+0x0C ownerId`, `+0x7C placedTimestamp`,
  `+0x80 gap80` (team byte for BALLOON_O_MATIC/FACTION), `+0x98/+0xA0`
  access-list begin/end, `+0xF8 guildLockUnk2`, `+0x140` storm-cloud solid
  counter.
- `NetAvatar` fields used by physics/permissions: `+0x13C` user id,
  `+0x94` guild id, `+0xA0` guild rank, `+0x288` team, `+0x294` has-team,
  `+0x2E8[40/41/42]` adventure event flags, `+0x2E0` five-slot tile cache
  (`TileExistsAt`), `+0x2DB0` friend state, `+0x1FB9` water-float,
  `+0x131` damage slip, `+0x140` coyote flag. Full layout:
  `docs/netavatar_type.h`.

### Collision model (verified)

There are two independent client layers:

- **Movement** — `NetAvatar::moveByPixels` (0x140512080) steps one pixel at a
  time; before each step `WorldView::collectStepTiles` (0x1405617E0) collects
  candidates (`CanPassThroughTile(tile, userID, world, 0) != 0`, plus
  direction-matched `ONE_WAY`), then `canMoveXInto` (0x140512A40) /
  `canMoveYInto` (0x140512A80) decide. `JUMP_THROUGH`/`JUMP_DOWN` never block
  X; vertically `JUMP_THROUGH` blocks only at the landing pixel and
  `JUMP_DOWN` blocks rising, passes falling; `ONE_WAY` blocks only against its
  facing.
- **Interaction** — `CanPassThroughTile` (0x140554C10) with `isBreakTap`
  (wall response + climb gate), and the ground query (`sub_140564570`, which
  skips `JUMP_DOWN`).

Engine mirror: `_can_enter_x/_can_enter_y` (movement) vs
`_interaction_blocked`/`_is_ground` (interaction/ground), sharing
`_blocks_like_client`. The full per-type model + port log is in
`docs/collision-port-backlog.md`; `docs/netavatar-physics.md` §12.4/§12.5 have
the client branches.

### Lock / permission model

Doors resolve their governing lock as **own `LOCK_TILE` extra → `parent_index`
(area/salt lock) → world lock** (`canDoorPassedThrough_1`, 0x140555950); the
pass rules (public bit, owner break-tap, guild-rank branch, access list) live
in `canDoorPassedThrough` (0x140557A20). Area locks are linked by the server
through `handleSendLock` (0x140561A80) +
`toggleLockedAndSetParentIndex` (0x140556790). Details and the
server-authoritative caveats are in `docs/lock-permissions.md`.

### Known POIs

| Address | Symbol | Notes |
|---|---|---|
| `0x140554C10` | `CanPassThroughTile` | interaction gate, per-type switch |
| `0x140512A40` | `NetAvatar::canMoveXInto` | movement X predicate |
| `0x140512A80` | `NetAvatar::canMoveYInto` | movement Y predicate |
| `0x1405617E0` | `WorldView::collectStepTiles` | candidate collector |
| `0x140512080` | `NetAvatar::moveByPixels` | pixel mover |
| `0x140555950` | `canDoorPassedThrough_1` | own/parent/world-lock resolution |
| `0x140557A20` | `canDoorPassedThrough` | public/owner/guild/access-list |
| `0x1405587B0` | `canFriendEntrancePassedThrough` | friend entrance |
| `0x140551E30` | `getGuildDoorRequiredRank` | extra+9 bits → 0..3 |
| `0x14055E2E0` | `World::getOwnerUserID` | world owner uid, -1 if none |
| `0x140519D80` | `TileExistsAt` | scans five cached tile slots |
| `0x140512690` | `FindNearestInteractableTile` | interaction probes |
| `0x140501DF0` | `handleTileInteraction` | X probe dispatch |
| `0x1405021D0` | Y probe | landing + hazards |
| `0x140512630` | `getPlayerCollisionRect` | (left, top, right, bottom) |
| `0x140564570` | ground-tile query | skips `JUMP_DOWN` |
| `0x140505CB0` | tile-step query | slide/mud, clears `0x131`, sets `0x140` |
| `0x140510580` | `NetAvatar::integrateVerticalAxis` | vertical physics |
| `0x1404FE4A50` | `NetAvatar::onJump` | jump/swim launch |
| `0x140506430` | `TryPlaceSeedAtTile` | jump action conditions |
| `0x14050B9C0` | `handleSetCharacterState` | SET_CHARACTER_STATE deltas |
| `0x1404F5E30` | `sendTankState` | 200 ms send gate |
| `0x1404FBEB0` | `fillTankStatePacket` | frame builder |
| `0x140509C20` | `updateBlockStateFromPlayerInteraction` | water flag/float |
| `0x1405024E0` | `killPlayer` | deadly latch |
| `0x1404FBFF0` | `handleDamagingTileCollision` | X damaging |
| `0x1404FC0B0` | Y damaging response | + damage slip |
| `0x140561A80` | `handleSendLock` | SEND_LOCK relink |
| `0x140556790` | `toggleLockedAndSetParentIndex` | LOCKED flag + parent_index |
| `0x140555160` | `isLockTile` | extra type == `LOCK_TILE` |
| `0x140019D30` | init jump const | `X - Y*0.5 == -450` |

## 5. Controller conventions

- A `PlayerController` **is** the local avatar: no component registry, no world
  subsystem. `send` is the single packet sink (STATE + tile-change requests).
- `controller.x`/`controller.y` is the **collision-rect top-left** (the client
  stores the same, see `getPlayerCollisionRect`); hitbox `20×30`, `TILE = 32`.
- `vy > 0` = falling; `CharacterState` axis triplets are the packet constants.
- `_simulate` order: `_check_tile_mod` → vertical → horizontal → `_touch`
  (probes) → `_move` (pixel steps) → `_settle`.
- `step()` order: `_flush_changes` (tile-change queue) → `_simulate` →
  `_send_state` → `_auto_respawn`.
- Collision helpers: `_active_tile`, `_can_enter_x/_can_enter_y`,
  `_blocked_x/_blocked_y`, `_interaction_blocked`, `_blocks_like_client`,
  `_is_ground`; permission logic: `_lock_passes`, `_lock_check`, the per-type
  `_*_open` helpers and `PlayerController.permissions`
  (`CollisionPermissions`).
- Special tiles / clothing: `_apply_wind` (WIND push tiles),
  `_gravity_well_pull` (Gravity Well), `_try_climb` + `climbing` (Wall Climbing
  gear via `Player.clothing`), `_slippery_clothing` / `_wearing_skates`
  (Slippery / Skating). Evidence and the mods classification: see
  `docs/netavatar-physics.md` §13 and `docs/02_packet` for the wire flags.
- Walk-over item mods: `_walk_item_mods` (called from `step()`) ports
  `NetAvatar::tryPlaceSeedOrFertilizer` (0x140506910) — the Tree Harvesting shoes
  (898/1830/1966/9650/10504) send the FIST request for a planted seed tile, the
  Chicken/Doom Plow (5022/5212) plant the selected seed (the splice re-request on
  an already-planted tile). A seed is *validated* on the tap path (`HandleTouch`:
  `IsTileBelowPlantable`, else "Can't plant a tree in the air!") but uses the
  same `TILE_CHANGE_REQUEST` as a block — evidence: `docs/02_packet` ("tile
  harvest / plant").
- Seed growth: `World` derives everything from one anchor — `SeedTile.time_passed`
  is the wire *elapsed* growth seconds and `SeedTile.observed_ms` is when the world
  received it, so `World.seed_planted_at_ms = observed_ms - time_passed * 1000`.
  Consumers derive: `seed_growth_time` (elapsed now; `getSeedTimePassed`
  0x140557870), `seed_time_left_ms` (≤ 0 once grown) and `tree_ready` (the Tree
  Harvesting gate, `item->unk5 < elapsed`). `World.clock` (monotonic ms, the
  client's `getTick`) is only read by those queries — nothing ages the field and no
  update loop or controller driver is involved.
- Tile changes: `touch_press`/`touch_hold`/`touch_release` model the client
  `HandleTouch` pipeline — per-tile de-dup (the Fist's `item_type` 0 repeats,
  items do not), 150 px reach, the 11 s hold timeout, `PUNCH_REPEAT_MS` for the
  punch-animation gate. `request_change`/`request_punch`/`request_place` send the
  position-stamped `TILE_CHANGE_REQUEST` immediately and arm the chained STATE
  bits (`PUNCH|TILE_CHANGE` / `PLACE|TILE_CHANGE`); `request_tile_activate` sends
  the steam-launcher `TILE_ACTIVATE_REQUEST` (type 7), while the per-tick
  `_collect_dropped_items` sends `ITEM_ACTIVATE_OBJECT_REQUEST` (type 11) for a
  walked-over dropped object (`request_collect_object`). Those are three
  different client senders. Client evidence: `docs/tile-change-request.md`.
- Server position sets: `handle_set_pos(x, y)` models `NetAvatar::onSetPos`
  (0x140501290, the `OnSetPos` call variant): it teleports and re-arms the
  one-shot `reset_visual_state` latch, so the next STATE frame carries
  `RESET_VISUAL_STATE`. The proxy state layer maps `Call(OnSetPos, (x, y))` to
  the self `STATE_PLAYER_UPDATE` (net_id 0).
- `World.from_tiles()` does **not** set `Tile.index` for explicitly supplied
  tiles (only `World.fill()` assigns indices). Compute indices with
  `World.index_tile(pos)` when resolving `parent_index`-style links.
- Item constants come from `gtools.baked.items`
  (`from gtools.baked.items import DIRT, MAIN_DOOR`).
- Tests build small worlds, `spawn()` a controller, and drive
  `set_input(...)` + `step()` loops, asserting on the returned controller's
  `x` / `y` / `grounded`.

### Pathfinding (`gtools/core/growtopia/physics/pathfinding/`)

- Contract: `docs/pathfinding-plan.md`; durable reference: `docs/pathfinding.md`.
- The controller is the physics authority. `FastEvaluator` is a tick-exact mirror
  of `_simulate`; `NumbaBackend` is the same algorithm compiled with `numba.njit`
  over one flat `int32` grid matrix, selected automatically by `FastEvaluator`.
- **Any physics change must be mirrored in both kernels.** The gates:
  `tests/test_path_fastkernel.py` (kernel vs the real controller, per tick) and
  `tests/test_path_numba.py` (compiled vs Python kernel, per tick + `Outcome`).
- `PATHFINDING_NO_NUMBA=1` (or `FastEvaluator(..., use_numba=False)`) forces the
  Python reference path. The compiled backend warms every kernel function in
  `NumbaBackend.__init__` so JIT compile time never lands inside the planner's
  `time_budget_ms`.
- Gated tiles (doors/gates/adventure/cloud/faction/guild) are resolved **once** per
  snapshot + profile fingerprint with the controller's own predicates; only the
  `LOCKED_ADVENTURE_DOOR` stays dynamic (avatar touched-tile cache). A dynamic
  extra that the snapshot does not version needs a `TILE_UPDATE` to be seen.
- Usage: `SegmentedPathfinder(controller).plan_to_tile(tx, ty)` →
  `PathFollower(controller, pathfinder, path)`; the follower owns the
  `set_input` + `step` loop (`tick_inputs`/`observe` when an outer loop steps).
- Host loops that already call `controller.step()` use `PathAutopilot`
  (`autopilot.advance()` then `step()`, `cancel()`, `progress`). Pathfinding
  **never writes avatar state**: planning reads the controller / cloned motion
  states, execution only calls `set_input(left, right, jump)` — pinned by the
  write-rejecting proxy controller in `tests/test_path_follower.py`.
- Demo: Ctrl+Left-Click (or right click → *Pathfind here*) plans and follows;
  the *Pathfinding* menu shows status and toggles the segment overlay
  (per-kind colours, traversed part dimmed, current segment thick, goal outlined,
  avatar trail). Overlay is 2D-only.
- Bench: `PYTHONPATH=. .venv/bin/python scripts/bench_pathfinding.py [--quick|--json]`.

## 6. Snippets

```sh
# physics tests
.venv/bin/python -m pytest tests/test_physics_collision.py tests/test_physics_vertical.py tests/test_physics_hazards.py -q

# item lookup
.venv/bin/python -c "from gtools.core.growtopia.items_dat import item_database as db; i=db.get(4530); print(i.name, i.item_type.name, i.collision_type.name)"
```

```python
# generic collision harness used by the tests
from gtools.core.growtopia.physics.controller import PlayerController
from gtools.core.growtopia.world import World, Tile, TileFlags
# build World.from_tiles([...]) with a floor, controller = PlayerController(world),
# c = controller.spawn(x, y); controller.set_input(right=True); controller.step()
# loop; assert c.x / c.y / c.grounded
```

## 7. Documentation conventions

- `docs/netavatar-physics.md` is the durable RE reference: update it when you
  verify or correct client behaviour, and keep unverified claims marked as
  such.
- Domain checklists (e.g. `docs/collision-port-backlog.md`) track what is
  ported; tick boxes and append a port log with the IDA evidence per pass.
- Mark rules that cannot be confirmed client-side (server-authoritative) as
  `[server-side]` — see `docs/lock-permissions.md`.
