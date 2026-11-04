# Collision port backlog — `engine.py`

## Goal

Port the client's `ItemInfoCollisionType` handling into
`gtools/core/growtopia/physics/engine.py` completely and faithfully:
every type's movement rules (`canMoveXInto`/`canMoveYInto` + the candidate
collector) and interaction rules (`CanPassThroughTile`, including all door,
adventure, faction, guild and friend permissions), each backed by IDA evidence
and a unit test. Work happens on the `collision-port` branch with one commit
per step; the checklist below is the backlog.

Each item: **verify in IDA → port → unit test → tick the box → commit**.

> `/todo-add` is a user-side OpenCode plugin ("for you, not the agent"), so the
> backlog lives here instead. The engine's old `_is_solid` conflated the two
> client layers below; the fix is to split them.

## The verified client model

There are **two separate layers**, and the old engine mixed them up:

### 1. Movement layer (`NetAvatar::moveByPixels`, `0x140512080`)

Per whole-pixel steps. Before each step it collects candidate tiles with
`WorldView::collectStepTiles` (`0x1405617E0`) and asks
`NetAvatar::canMoveXInto` (`0x140512A40`) / `canMoveYInto` (`0x140512A80`).
A predicate returning 1 stops the step; the body rests exactly on the tile
edge.

`collectStepTiles(world, x, y, w, h, out, userID, dirX, dirY)`:
- gathers the rect tiles, then
- includes a tile when `CanPassThroughTile(tile, userID, world, 0) != 0`, or
- includes a `ONE_WAY` tile only when it is oriented **against** the movement
  direction (i.e. the tile that would block), and
- skips `JUMP_DOWN` on the X axis? (no: `a9 < 0 || collision != 7` — with
  `a9 = 0` on the X probe every tile passes that test).

`canMoveXInto` (`0x140512A40`):
| tile | result |
|---|---|
| `JUMP_THROUGH(2)`, `JUMP_DOWN(7)` | 0 — never blocks horizontally |
| `ONE_WAY(5)` | 0 when walking **with** the tile (`!FLIPPED_X` + right, or `FLIPPED_X` + left), else 1 (the collector already pre-filtered) |
| default (candidates only) | 1 |

`canMoveYInto` (`0x140512A80`):
| tile | moving **up** | moving **down** |
|---|---|---|
| `JUMP_THROUGH(2)` | 0 — pass | 1 only when `newBottom == tileTop + 1` (the landing pixel), else 0 |
| `JUMP_DOWN(7)` | 1 — cannot rise into it | 0 — can fall through |
| default (candidates only) | 1 | 1 |

So effectively:
- **NONE** tiles are never candidates (see below) → always pass.
- **ONE_WAY** blocks only the horizontal direction opposite to its facing; it is
  never collected for vertical movement (`dirX == 0` filter) → vertical pass.
- **JUMP_DOWN** blocks upward movement, passes downward.
- **JUMP_THROUGH** passes up/sideways, lands from above at the pixel edge.

### 2. Interaction layer (`CanPassThroughTile`, `0x140554C10`)

Called from `handleTileInteraction` (`0x140501DF0`, X) and `vfunc_48`
(`0x1405021D0`, Y) with `isBreakTap = 1` — this is the *wall response + climb*
gate, not movement. Returns 1 = "this tile blocks / demands interaction".
The docs §12.4 already describes it; the first check is `tile->isOn`
(`tile+0x12`), which the docs list as "never interacts" when clear.

Per-type pass conditions (return 0), `isBreakTap = 1`:
| type | pass when |
|---|---|
| `JUMP_THROUGH(2)`, `JUMP_DOWN(7)` | always (probe-only exclusion) |
| `ONE_WAY(5)` | always |
| `GATEWAY(3)` | `canDoorPassedThrough_1(...)` or tile `flags & 0x80` (open to public) |
| `VIP_DOOR(6)` | `canDoorPassedThrough(extra, userID, tile, 1)` |
| `FRIEND_ENTRANCE(13)` | `canFriendEntrancePassedThrough` (lock list / friends / world owner) |
| `ADVENTURE(8)` | `LOCKED_ADVENTURE_DOOR`: `ADVENTURE_ITEM_KEY (1696)` in the avatar tile cache; `ADVENTURE_BARRIER` / `IDOL_GATE` / `TOMB_GATE`: per `avatar+0x2E8[40/41/42]` event flags |
| `FACTION(10)` | team match / access list, public bit `0x80` |
| `GUILD(11)` | guild id `avatar+0x94` == `extra+0xF8` and rank `avatar+0xA0` >= `getGuildDoorRequiredRank(extra)` (from `extra+0x9` bits), or access list, or public |
| `CLOUD(12)` | `extra+0x13C+4 > 0` (storm-cloud countdown) |
| `COLLIDE_IF_OFF(4)` | `IS_ON` set |
| `COLLIDE_IF_ON(9)` | `IS_ON` clear |
| default (`FULL(1)`, `NONE(0)`) | never (returns 1) |

> `avatar+0x13C` is the local **user id**, not an item id: it is compared
> against lock `ownerId`/access lists (`canDoorPassedThrough`) — rename pending.

## Backlog

- [x] **NONE(0)** — movement: never a candidate → pass. Interaction: pass.
- [x] **FULL(1)** — movement: candidate → block on both axes. Interaction: block.
- [x] **JUMP_THROUGH(2)** — movement: X pass; Y: up pass, down lands at the
      pixel edge (`newBottom == tileTop + 1`). Interaction: pass (no wall push).
- [x] **GATEWAY(3)** — interaction: pass when `canDoorPassedThrough_1` (own
      lock extra → `parent_index` → world lock, access list / owner break-tap /
      guild / public) or the public bit (`flags & 0x80`) is set.
- [x] **COLLIDE_IF_OFF(4)** — solid iff `IS_ON` clear (both layers).
- [x] **ONE_WAY(5)** — movement: horizontal-only, blocks the direction opposite
      the facing (`FLIPPED_X`); vertical always passes. Interaction: pass.
      Fixed — it used to be modelled as a vertical platform.
- [x] **VIP_DOOR(6)** — `tile.extra` required (no extra → block);
      `canDoorPassedThrough(extra, userID, tile, 1)`: public bit, owner
      break-tap, guild-rank branch (protocol ≥ 36), access list.
- [x] **JUMP_DOWN(7)** — movement: block rising, pass falling; X pass.
      Interaction: pass; excluded from the ground query (`a7 == 1`).
- [x] **ADVENTURE(8)** — key gate via avatar tile cache (`TileExistsAt` scans
      five slots for `ADVENTURE_ITEM_KEY 1696`; the engine fills the cache from
      the interaction probes); `ADVENTURE_BARRIER(4706)` /
      `IDOL_GATE(4710)` / `TOMB_GATE(4744)` toggle on `+0x2E8[40/41/42]`
      (flag clear: open while `IS_ON`; flag set: open while `IS_ON` clear);
      other fg ids block.
- [x] **COLLIDE_IF_ON(9)** — solid iff `IS_ON` set (both layers).
- [x] **FACTION(10)** — `avatar+0x288` team vs `extra+0x80[0]` (the
      BALLOON_O_MATIC team byte), presence flag `avatar+0x294`, public bit,
      access list via `canDoorPassedThrough_1`.
- [x] **GUILD(11)** — `extra` required; guild id `extra+0xF8` + rank vs
      `getGuildDoorRequiredRank(extra)` (door bits `0xC0`→0, `0x80`→1,
      `0x40`→2, else 3), then `canDoorPassedThrough_1`, then public bit.
- [x] **CLOUD(12)** — storm cloud: solid while `extra->is_solid > 0`
      (`extra+0x140`), else pass; a cloud without an extra blocks (client
      falls to the default return). Damaging state (`LIGHTNING_CLOUD(126) &&
      IS_ON`) was already handled by `_damaging_event`.
- [x] **FRIEND_ENTRANCE(13)** — `canFriendEntrancePassedThrough`: the lock
      path with `isBreakTap = 0` (access list / public), then
      `placedTimestamp == 1`, then friend flag `+0x2DB0` + world owner
      (`World::getOwnerUserID`) or the owner's own user id.

## Port log

### Pass 1 — movement/interaction split + simple types (this commit)

`engine.py`:
- Split the old `_is_solid` into `_interaction_blocked` (CanPassThroughTile with
  `isBreakTap = 1`, used by `_touch`'s wall response) and the movement predicates
  `_can_enter_x`/`_can_enter_y` (used by `_blocked_x`/`_blocked_y` per pixel).
- `_blocks_like_client` is the shared per-type switch; `_active_tile` feeds it.
- `_settle` now uses `_is_ground` (blocking tiles except `JUMP_DOWN`, matching
  the ground query's `a7 = 1`), so `ONE_WAY`/non-solid `CLOUD` are no longer
  standable.
- Permission types without engine-side context yet (`VIP_DOOR`,
  `FRIEND_ENTRANCE`, `ADVENTURE`, `FACTION`, `GUILD`) are explicit stubs that
  pass, so behaviour only changes when their backlog item lands.
- `GATEWAY` honours the public bit; `CLOUD` honours `StormyCloudTile.is_solid`.

Tests: `tests/test_physics_collision.py` (one-way orientation + vertical, jump
through landing, jump-down rising/falling, storm-cloud solidness).

### Pass 2 — lock permission layer + all door types (this commit)

`engine.py`:
- `CollisionPermissions` on `PhysicsComponent` (user id, guild id/rank,
  team/has-team, adventure event flags, five-slot touch cache, friend state,
  protocol version); `c` threaded through `_can_enter_x` / `_can_enter_y` /
  `_blocked_x` / `_blocked_y` / `_interaction_blocked` / `_blocks_like_client`
  / `_is_ground`.
- `_lock_passes` (`canDoorPassedThrough`, 0x140557A20) and `_lock_check`
  (`canDoorPassedThrough_1`, 0x140555950: own lock extra → `parent_index` →
  `World.get_world_lock()`).
- `_gateway_open` (public bit or lock), `_vip_door_open` (own extra only),
  `_friend_entrance_open`, `_adventure_open` (key tile cache + the 40/41/42
  event flags), `_faction_open` (team byte), `_guild_open` +
  `_guild_required_rank` (`getGuildDoorRequiredRank`, 0x140551E30).
- `_cache_touch` fills the `TileExistsAt` cache from both probes.
- CLOUD without an extra now blocks (the client falls through to its default
  return when `tile->extra` is null).

`world.py`:
- `LockTile.door_flags` (client +0x09) and `LockTile.guild_id` (client +0xF8
  → the trailing `unk1`), `VipEntranceTile.door_flags` (its `unk1`),
  `FriendsEntranceTile.access_uids` / `placed_timestamp` (runtime fields; the
  wire parse does not carry them in this build),
  `World.get_owner_user_id()` (`World::getOwnerUserID`, 0x14055E2E0).

Tests (`tests/test_physics_collision.py`): gateway public bit + world-lock and
parent-lock access resolution + owner break-tap; VIP extra-less/access/owner/
public; adventure key cache (manual + filled by touching the key) and the
barrier/idol/tomb toggles; faction team rules; guild rank/access/public/no-
extra rules; friend entrance owner/friend/access/`placedTimestamp` rules.

IDA verification for this pass: `CanPassThroughTile` 0x140554C10,
`canDoorPassedThrough` 0x140557A20, `canDoorPassedThrough_1` 0x140555950,
`TileExistsAt` 0x140519D80, `canFriendEntrancePassedThrough` 0x1405587B0,
`getGuildDoorRequiredRank` 0x140551E30, `determineTileExtraType` 0x140557B60
(faction team byte defaults, friends-entrance `placedTimestamp = 1`),
`World::getOwnerUserID` 0x14055E2E0 and the `TileExtra` struct offsets
(+0x09/+0x0C/+0x7C/+0x80/+0x98/+0xA0/+0xF8/+0x140).

## IDA housekeeping done for this port

- `0x140512A40` → `NetAvatar::canMoveXInto`
- `0x140512A80` → `NetAvatar::canMoveYInto`
- `0x1405617E0` → `WorldView::collectStepTiles`
- `0x1405587B0` → `canFriendEntrancePassedThrough`
- `0x140551E30` → `getGuildDoorRequiredRank`
- `NetAvatar::itemId_13C` → `userID` (lock checks compare it to user ids)
