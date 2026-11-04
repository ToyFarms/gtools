# Lock & build permissions — client model

> Side task from the collision port: confirm the Growtopia client's lock
> permission model in IDA and document it. The *server* is authoritative for
> placing/breaking; the client keeps the lock state locally and mirrors the
> same checks for doors (see `collision-port-backlog.md` and
> `netavatar-physics.md` §12.4). Verified client facts are marked
> **[verified]**; rules that only exist server-side are marked
> **[server-side]** and should be treated as unconfirmed client behaviour.

## 1. The lock hierarchy

A lock is a tile whose extra type is `LOCK_TILE` (`isLockTile`, 0x140555160:
`extra && extra->type == 3`). Locks come in two scopes:

| scope | items | coverage |
|---|---|---|
| **world lock** | `WORLD_LOCK(242)` and its variants | the whole world |
| **area locks** (salt locks) | `SMALL_LOCK(202)`, `BIG_LOCK(204)`, `HUGE_LOCK(206)` | only the tiles the server linked to them |
| **builder's lock** | `BUILDER_S_LOCK(4994)` | finer build/break control **[server-side flags]** |

### Linkage: the server sends the locked-tile list

**Verified** in `handleSendLock` (0x140561A80, the `SEND_LOCK` tank
handler):

1. the tank carries a lock tile (coordinates) and an array of locked tile
   indices (`[rbp+8]` count, extended-data u16 list);
2. `removeAllLockedTiles(worldview, lock_tile)` (0x140566000) clears the
   previous linkage of that lock;
3. for every index in the array the client calls
   `toggleLockedAndSetParentIndex(tile, lock_index)` (0x140556790), which
   sets `TileFlags.LOCKED` (bit 1 at tile+0x08), writes
   `tile->parent_index` (tile+0x6C) = lock tile index and refreshes the
   tile's `hashOrUniqueID` (tile+0x5A = fg + flags + `seedValue`).

So **an area lock owns tiles explicitly** — every covered tile points at the
lock tile through `parent_index`. The world lock, by contrast, is global:
the client stores its tile pointer at `World+0x138` and never marks every
tile.

### Resolution precedence: **specific lock first, world lock last**

`canDoorPassedThrough_1` (0x140555950) resolves the lock that governs a
tile:

```c
extra = tile->extra;
if ((!extra || extra->type != LOCK_TILE) && !tile->parent_index && !world->lock /*+0x138*/)
    return 1;                                   // nothing locks this tile
if (!extra || extra->type != LOCK_TILE) {
    idx = tile->parent_index;                   // the area lock that owns it
    if (!idx) idx = world_lock->index;          // else the world lock
    tile = world->tilesArray + 144 * idx;
}
return canDoorPassedThrough(tile->extra, userID, tile, /*isBreakTap=*/1);
```

**This is the confirmed precedence: own lock extra → `parent_index` area lock
→ world lock.** An area lock therefore *overrides* the world lock for the
tiles it covers (matching the in-game rule that a small/big/huge lock can be
more restrictive than the world lock). The engine mirrors it in
`PhysicsEngine._lock_check` (`gtools/core/growtopia/physics/engine.py`).

> Note: tiles linked by an area lock while standing on the world lock's
> access list still resolve to the **area lock** — being an admin on the
> world lock does not bypass a salt lock you are not on. (The client only
> ever resolves one lock.)

## 2. Who passes a locked door

`canDoorPassedThrough` (0x140557A20) — the same test the engine ports as
`_lock_passes`:

1. **public bit**: `tile->flags & 0x80` → pass for everyone;
2. **owner break-tap**: `isBreakTap && userID == extra->ownerId` → pass
   (the interaction/probe path uses break-tap = 1, so the owner can always
   punch their own door);
3. **guild branch** (`protocolVersion >= 36` and `extra->guildLockUnk2`
   != 0): if the avatar's guild (avatar+0x94) matches the lock's guild id
   (extra+0xF8), the door-state byte `extra+0x09` applies:
   - `0xC0` (`0x40|0x80`) → pass at any rank,
   - `0x80` → pass for rank 1–2,
   - `0x40` → pass for rank 2 only,
   - otherwise fall through;
4. **access list**: `userID in extra->arrayBegin..arrayEnd` → pass.

The engine exposes these as `LockTile.door_flags` (+0x09) and
`LockTile.guild_id` (+0xF8 → the trailing `unk1`), and
`LockTile.access_uids`.

`extra->minimumLevel` (serialized after the access list) is the "minimum
level" lock setting; the client stores it but the door checks above do not
read it **[verified for doors]**. Whether the *edit* path enforces it is
**[server-side]** in this build.

## 3. Entrances override everything they can

Collision entrances carry their own extra and often a public bit:

- GATEWAY doors (`GATEWAY(3)`): pass when `canDoorPassedThrough_1` says so
  **or** `flags & 0x80` (open-to-public);
- VIP doors (`VIP_DOOR(6)`, `VipEntranceTile`): own lock extra only, same
  `canDoorPassedThrough` rules;
- Friends entrances (`FRIEND_ENTRANCE(13)`): `canFriendEntrancePassedThrough`
  (0x1405587B0) — the lock path with `isBreakTap = 0`, then
  `placedTimestamp == 1`, then the avatar's friend state (+0x2DB0) with a
  valid `World::getOwnerUserID` (0x14055E2E0, world lock extra+0x0C) or the
  world owner's own user id;
- Faction doors (`FACTION(10)`): public → team byte must match; otherwise
  `canDoorPassedThrough_1` **and** team match;
- Guild doors (`GUILD(11)`): guild id/rank, or the access list, or public.

All of these are ported and tested in `tests/test_physics_collision.py`.

## 4. Build / break rights

The client stores everything the server sends and mirrors lock resolution,
but **the actual build/break authorization is server-authoritative**
**[server-side]** — the client only knows:

- the resolved lock and its owner/access list (verified above);
- the builder's-lock extra (a `LOCK_TILE` variant) whose flags the server
  interprets as build-only / break-only / both **[server-side, flags bits not
  confirmed in this build]**;
- item-level restrictions such as vending machines being owner-only
  **[server-side, hard-coded]**.

Practical summary for the engine: edit rights should be modelled as the same
lock resolution (`own → parent_index → world lock`) + the same
owner/access/guild/public checks, with the server-only bits (minimum level,
builder flags, item restrictions) left to the server side. The collision
engine only needs the pass-through half, which is fully ported.

## 5. Client POIs referenced

| Address | Symbol |
|---|---|
| `0x140555160` | `isLockTile` (extra type == `LOCK_TILE`) |
| `0x140556790` | `toggleLockedAndSetParentIndex` (LOCKED flag + parent_index + hash) |
| `0x140561A80` | `handleSendLock` (SEND_LOCK tank: relink the lock's tile list) |
| `0x140566000` | `removeAllLockedTiles` (clear a lock's previous linkage) |
| `0x140555950` | `canDoorPassedThrough_1` (own → parent → world lock resolution) |
| `0x140557A20` | `canDoorPassedThrough` (public / owner / guild / access list) |
| `0x14055E2E0` | `World::getOwnerUserID` (world lock extra+0x0C, -1 when unlocked) |
| `0x1405587B0` | `canFriendEntrancePassedThrough` |
| `0x140551E30` | `getGuildDoorRequiredRank` (`0xC0`→0, `0x80`→1, `0x40`→2, else 3) |

Tile layout (IDB `Tile`, 0x90 bytes): `+0x08 flags`, `+0x0C index`,
`+0x12 isOn`, `+0x14 collisionType`, `+0x28 extra`, `+0x5A hash`,
`+0x6C parent_index`.
TileExtra layout: `+0x08 type`, `+0x09 doorState/flags`,
`+0x0C ownerId`, `+0x7C placedTimestamp`, `+0x80 gap80` (team byte for
BALLOON_O_MATIC), `+0x98/+0xA0` access-list begin/end,
`+0xF8 guildLockUnk2`.
