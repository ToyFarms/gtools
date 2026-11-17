# Blasters (Howler / Trickster) — client mechanics reference

> Client facts are marked **[verified]** when read from the binary (asm or
> pseudocode, with the address) and **[data]** when they come from `items.dat` /
> world dumps. Not-yet-decoded points are **[unknown]**; things the client cannot
> decide are `[server-side]`. The engine implementation (simulation, controller
> hook, renderer, demo) is tracked in §10.

Sources:

- `Growtopia.exe.i64` via the pre-exported corpus `export/ida_pseudocode/`
  (addresses below are the exported symbols; image base `0x140000000`).
- `items.dat` v27 (16 580 items) through `gtools.core.growtopia.items_dat`.
- 631 world files under `/mnt/c/Users/andra/.gtools/worlds` (**57 blaster tiles
  in 21 files**: 41 Trickster, 16 Howler).
- Particle sheets `GameData/game/particles.rttex`, `game/particles2.rttex`.

Recon artifacts (raw dumps, byte-by-byte decodes, re-runnable scripts):
`/tmp/opencode/blaster-recon/` (`data.md`, `client.md`).

---

## 1. Executive summary

| Question | Answer |
|---|---|
| What are the items? | `ItemInfoType.BLASTER = 93`: **Howler** (4344) and **Trickster** (8020). Both are non-solid decorations (`collision_type NONE`, `tile_range 0`), `frame_interval_ms = 400`. **[data]** |
| Does the item carry a payload? | **No.** `flags2 == 0`, `cybot is None`, and the tile extra is wire-empty; the speed comes from the tank packet, *not* from `frame_interval_ms` (that is the tile's sprite animation rate). **[data]** |
| What is the tile extra? | `BLASTER_TILE = 0x34`, **one byte on the wire** (the type byte). All 57 corpus tiles are byte-exact with an empty payload; a 6-byte payload layout exists in `TileExtra::Parse` behind an unreachable `someFlag` gate (§3). **[verified + data]** |
| Who fires? | **Nobody on the client.** There is no blaster sender anywhere in the binary; the server spawns the blast as an **NPC** and the client simulates it. `[server-side]` **[verified: no send path]** |
| What is a blast? | An NPC entity: type **8 = `NpcType.BLAST`** (Howler), **15 = `NpcType.TRICKSTER`**. It is *not* a tile entity and has no item id. **[verified]** |
| Motion | `timer += dt`; every `0.1 s` one trail particle at the pre-move point; then `pos += (cos, sin)(param3°) * (int)param2 * dt`. **No tile collision, no despawn, no lifetime.** **[verified]** |
| Who ends it? | Only the server: event 7 (DIE, impact burst) or event 1 (DELETE, silent). **[verified]** |
| What kills the player? | The blast *point* inside `getPlayerCollisionRect`, avatar not dying, and a tile under the hitbox centre that exists and is not item type `DOOR` (13) → `killPlayer`. Nothing else. **[verified]** |
| Rendering | `renderNpc` draws **nothing** for types 8/15: the projectile is visible only as particles. 212 → `game/particles.rttex` cell (0, 2); 276 → `game/particles2.rttex` cell (8, 14); 16 px cells, scale 1.0. **[verified]** |

---

## 2. Item data

**[data]** (items.dat v27):

| id | name | `item_type` | collision | `frame_interval_ms` | `flags2` | `cybot` |
|---|---|---|---|---|---|---|
| 4344 | Howler | BLASTER (93) | `NONE` | 400 | 0 | `None` |
| 8020 | Trickster | BLASTER (93) | `NONE` | 400 | 0 | `None` |

Consequences for the port:

- There is **nothing to decode** from items.dat for blasters — unlike ROBOT /
  COMMAND items, whose 60-byte `cybot_related` field the client reads. An earlier
  `ItemInfoBlasterSpec` idea (blast speed from `frame_interval_ms`) was wrong and
  has been removed: `frame_interval_ms` is the tile sprite's frame rate, consumed
  by the ordinary tile animation code, and the blast speed is the tank packet's
  `int_y` (§5).
- The items are **decorations** (`NONE` collision), so the player walks through
  the tile; the blast is a separate NPC.

---

## 3. The tile extra — `BLASTER_TILE` (`0x34`)

### 3.1 Live wire format: one byte

`TileExtra::Parse` (0x1405588F0) dispatches `case 0x34` into a blaster branch that
reads `state u8`, `tile_type u8`, `interval_ms u32` — but only on the
`someFlag == 0` path. Every reachable parse path (world `SEND_MAP_DATA` and tile
updates) passes `someFlag = 1`, so the client consumes **only the type byte**.
**[verified]**

Corpus proof **[data]** (`/tmp/opencode/blaster-recon/data.md`):

- 631 world files scanned, 21 contain blasters, **57 extras, all exactly one byte
  (`0x34`)**, no exception.
- `World.serialize()` round-trips byte-exact for the 1-byte layout; forcing the
  6-byte layout desyncs every one of the 21 files (first garbage tile in the first
  tens/hundreds of tiles).
- Completeness sweep: no blaster-flagged tile carries any other extra class.

Worked example — five consecutive Trickster tiles in `FIND`, starting at tile
`(p=1702)`:

```
54 1f | 00 00 | 0f 07 | 43 00 | 0f 07 | 34
fg    | bg    | parent| flags | lock  | extra
```

`fg = 0x1f54 = 8020`, `parent = lock = 1807`, `flags = 0x0043`
(`HAS_EXTRA_DATA | LOCKED | 0x40`), then the single `0x34` extra byte and the next
tile header immediately after it.

### 3.2 gtools model

`world.BlasterTile` is a field-less extra (only `_extra_raw = b"\x34"`); see
`tests/test_blaster_data.py` for the byte-exact regression.

---

## 4. The NPC wire — how a blast arrives

`ProcessTankUpdatePacket` (0x140405470) routes `TANK_NPC` (type 34) into
`handleNPC` (0x1403F3DF0). **[verified]**

Tank fields used by the NPC path:

| off | field | NPC meaning |
|---|---|---|
| +0x01 | `object_type` | NPC **type** (8 / 15 for blasters) |
| +0x02 | `jump_count` | NPC **uid** |
| +0x03 | `animation_type` | NPC **event** (0…9) |
| +0x18/+0x1C | `vector_x/y` | `pos` |
| +0x20/+0x24 | `vector_x2/y2` | `target_pos` |
| +0x28 | `particle_rotation` | `param3` — **heading, degrees** |
| +0x2C | `int_x` | `param1` (unused by 8/15) |
| +0x30 | `int_y` | `param2` — **flight speed, px/s** |
| +0x34/+0x38 | `extended_len` / extended data | event 0 only: `count u8` + `count` × 30-byte entries |

Events (0 FULL_STATE, 1 DELETE, 2 ADD, 3 MOVE, 4 SUCKED, 5 BURP, 6 TELEPORT,
7 DIE, 9 OUCH) all funnel through `npc` (0x1402B6260) with the same argument
order; 8/10/11 fall into `default: return`. For blasters only **2, 7 and 1**
matter. **[verified]**

### 4.1 The 30-byte full-state entry (`npcDeserialize` 0x1402B73D0)

```
u8 type | u8 uid | f32 pos.x | f32 pos.y | f32 target.x | f32 target.y
        | i32 param1 | i32 param2 | f32 param3          = 30 bytes
```

`npcDeserializeAndPushBack` (0x1402B7490) first reads a `u8` count, then calls
`npcDeserialize` that many times. (The in-memory `NPC` struct is 44 bytes —
`renderAllNpc` 0x1402B7110 and `npcResetAction` 0x1402B59E0 stride by 44 — which is
a different number and easy to confuse.) **[verified]**

`gtools.world.Npc.deserialize` implements the 30-byte entry; pinned by
`tests/test_blaster_data.py`.

---

## 5. Spawn — `createNpcAndPushBack` (0x1402B56F0), tank event 2

Field writes **[verified]**:

```c
npc->type            = tank.object_type;         // 8 = Howler blast, 15 = Trickster
npc->uid             = tank.jump_count;
npc->position        = (vector_x, vector_y);
npc->targetPosition  = (vector_x2, vector_y2);   // unused by 8/15
npc->param1          = tank.int_x;               // unused by 8/15
npc->param2          = tank.int_y;               // speed (int! truncated in the update)
npc->param3          = tank.particle_rotation;   // heading in degrees
npc->timer           = 0.0;
```

Slot handling: a linear scan reuses the entry whose `uid` matches (so a re-sent
uid **updates in place and resets `timer`**) or the first empty slot; if none and
the vector already holds more than **105** entries the spawn is dropped (cap ≈ 106
NPCs of *any* type). Nothing here is blaster-specific. **[verified]**

### 5.1 Spawn-tile gate (types 8 / 15 only)

Both blaster cases look up the tile at the **spawn point**
(`getTileAtPosition`: `(int)(x/32), (int)(y/32)`) and, when its item type is
`BLASTER` (93), run the shared tail **[verified]**:

```c
setTileNextUpdate(tile, 1000);          // tile->nextUpdateMs = getTick() + 1000
playAudio(gs, tileToWorldCenter(tile), "audio/flame_go.wav");
```

i.e. the *tile* under the spawn flashes its firing animation and plays the launch
sound. If the spawn point is not over a blaster tile, the blast still exists — it
is just silent. `setTileNextUpdate` (0x140556710) writes the **absolute** tick
`now + 1000` (client `Tile+0x4C`, not serialized); gtools models it as
`Tile.next_update_ms` (blast spawn only — no consumer yet).

No ADD-time projectile sprite is created for 8/15.

---

## 6. Per-frame update — `updateNPC` (0x1402B7530), cases 8 / 15

Verbatim structure (identical for both types; only the particle id differs)
**[verified]**:

```c
timer += dt;
if (timer >= 0.1) {                       // one particle per frame, not a while
    spawnParticle(pm + 248, <212|276>, position.x, position.y, param3, 0, 0, 0);
    timer -= 0.1;
}
speed = (float)(int)param2;               // int truncation is real
rad   = param3 * PI / 180.0;
position.x += cos(rad) * dt * speed;
position.y += sin(rad) * dt * speed;
// 8/15 are not in the action vector -> no npcMoveTowardsTarget, no collision
```

Notes:

- The particle is spawned **before** the position advances, i.e. at the
  pre-move point (`gtools` captures `pre_x/pre_y` for exactly this reason).
- `+y` is **down** in client world pixels: `param3 = 0` → right, `90` → down,
  `-90`/`270` → up, `180` → left.
- `timer >= 0.1` is a single `if`: a 350 ms frame emits **one** particle and
  leaves `timer = 0.25`.
- There is **no** tile collision, no out-of-bounds test, no lifetime and no
  despawn: a blast flies forever until the server deletes it. (The type-3
  `HOMING_PROJECTILE` drags its own trail along; 8/15 never do — their trail
  stays where it was spawned.)
- Types 8/15 take `default` in `sub_1402B6040` (events 3/6/9), so MOVE / TELEPORT
  only retarget and reposition.

### 6.1 The kill test (inside the same update)

```c
if (!localPlayer) return;
if (!pointInRect(getPlayerCollisionRect(player), npc->position)) return;   // sub_14002F680
if ((avatar+0x179 || avatar+0x17A) && (charFlags & NOCLIP)) return;        // build override
if (avatar->state_2088 == 6) return;                                       // already dying
tile = tileAt(playerRectCentre);
if (!tile) return;
if (item[tile->fg].item_type != DOOR) killPlayer(player, 0);
```

**[verified]**

- `pointInRect` (`sub_14002F680`) accepts **either** rect ordering (an inverted
  rect still matches) — the same quirk `cybotApplyMeleeDamage` has.
- `getPlayerCollisionRect` is `(left, top, right, bottom)` = `(x, y, x+w, y+h)`;
  the point is the blast's **centre**.
- The tile is the one under the **hitbox centre**; gtools `World.fill()` /
  `fix()` materialise every in-bounds tile, so "no tile" means out of bounds.
- `item_type != DOOR (13)` — the Main Door exemption is the *item type*, not the
  specific item, and it is the same rule the cybot melee gate uses
  (`docs/cybot.md` §7).
- `killPlayer(player, 0)` sets the dying state and sends the plain
  `action|respawn_spike` (no tile arguments).
- The test runs in `updateNPC`, **not** in the interaction probe pass, so a
  NOCLIP avatar is still hit unless the build-override bytes are set — different
  from cybot melee, which is skipped for NOCLIP.
- The blast is **not** consumed by a hit; it keeps going until the server ends it.

---

## 7. End of life

| tank event | function | effect for 8 / 15 |
|---|---|---|
| 7 DIE | `npcHandleAction` 0x1402B5A40 | type 8: **4 × particle 212** at `randFloat(0, 360)` around the (updated) position; type 15: **effect entries 178 + 223**; then `npc->type = 0` (removed). **[verified]** |
| 1 DELETE | `npcResetAction` 0x1402B59E0 | clears the entry, **no** particles, no sound. **[verified]** |

Type 15's burst goes through `maybeSpawnParticleEffect` (0x1403E6920), which uses
the separate 32-slot *effect* pool and the 3402-line per-id parameter table, not
the trail registry — so 178/223 are effect ids, not sprite cells. gtools records
them in `BlastWorld.effects` and does not draw them.

---

## 8. Particles and rendering

`renderNpc` (0x1402B6950) switches on the NPC type; 8/15 hit `default`, then fail
the action-vector membership test ({1, 12, 4, 6, 7, 11}) and return **without
drawing anything**. There is no projectile sprite, sheet or animation.
**[verified]**

The visible blast is entirely particles **[verified]**:

| particle | role | sheet | cell (x, y) | cell px | scale |
|---|---|---|---|---|---|
| 212 | Howler trail (+ DIE burst) | `game/particles.rttex` | (0, 2) | 16 | 1.0 |
| 276 | Trickster trail | `game/particles2.rttex` | (8, 14) | 16 | 1.0 |

- Both are initialised by the same `sub_1402C8F00` case: `+32 (scale) = 1.0`,
  `+44 = 0.5`. The draw path (`sub_1402CD860` case 212 / case 276) passes the
  record's angle as the sprite rotation, so the trail is oriented along the
  heading.
- The 16 px cell size comes from `sub_1402CD700` (the surface/frame helper forces
  16 for these particle surfaces), not from a per-id table.
- `+44 = 0.5` is the only lifetime-ish record field; for particle 197 the same
  field is 2.0–3.0 s, so **500 ms is [inferred]**, not read from a `despawn`
  branch.

---

## 9. Open questions / server-side

- **Fire cadence, blast speed/heading and blast lifetime**: the client never
  chooses any of them. Howler/Trickster `frame_interval_ms = 400` is the *tile
  sprite* animation, not a fire rate. `[server-side]`
- **The blaster's owner / tile link**: the blast NPC carries no tile id, owner or
  item reference; nothing in `updateNPC`/`npcHandleAction` looks at the tile
  again. Which lock owner a blast "belongs to" (and whether it can be blocked) is
  not client-visible. `[server-side]`
- `avatar+0x179/+0x17A` (the build-override pair) are not modelled in gtools, so
  the `override && NOCLIP` immunity can never trigger — the same deviation
  `CyBotWorld` documents.
- Particle 212/276 **pixel content** was not inspected; only the sheet/cell and
  the scale were verified.

---

## 10. gtools status (implemented)

| Piece | Where | Notes |
|---|---|---|
| Simulation | `gtools/core/growtopia/blaster.py` — `Blast`, `BlastParticle`, `BlastWorld` | `add` (= ADD), `delete` (= DELETE), `despawn` (= DIE), `tick` (trail + motion + ageing), `check_kills` (the §6.1 gate), `particle_sprites` |
| Controller hook | `PlayerController.blasts`, run at the end of `_simulate` | the client runs the kill test inside `updateNPC`, not the probe pass, so this hook is independent of NOCLIP |
| Renderer | `gtools/gui/lib/blaster_renderer.py` — `BlasterRenderer` | two sheet passes, instanced quads rotated to the heading; `particle_instances()` is the headless conversion |
| Shaders | `shaders/blaster.vert`, `blaster3d.vert`, `blaster.frag` | instance attribs: worldPos, frameUV, angle |
| World renderer | `WorldRenderer.blasts`, `update()`, `delete()`, "Blasters" render order | depth `layer.BLAST = -71.45` |
| Demo | `GPUPhysicsDemo._spawn_blast` + the *Blaster* menu section | the demo has no server, so the buttons emit the same NPC ADD (`BLAST_DEMO_SPEED = 400 px/s`, a viewer default, **not** client data) |
| Tests | `tests/test_blaster_data.py`, `test_blaster_sim.py`, `test_blaster_renderer.py` | wire format, motion/trail, cap/reuse, kill gates, renderer math |

Deliberate deviations: the build-override immunity (§9), and the trail list is
bounded by an engine constant (`MAX_PARTICLES = 512`, oldest dropped) where the
client's dynamic pool overwrites its lowest-priority record. That bound is an
engine choice, not client data.

---

## 11. Evidence index

| Address | Symbol | Used for |
|---|---|---|
| `0x140405470` | `ProcessTankUpdatePacket` | `TANK_NPC` → `handleNPC` |
| `0x1403F3DF0` | `handleNPC` | event switch, tank field map |
| `0x1402B6260` | `npc` | per-event vector mutation |
| `0x1402B56F0` | `createNpcAndPushBack` | ADD fields, uid reuse, 106 cap, spawn gate + sound |
| `0x1402B73D0` | `npcDeserialize` | 30-byte entry |
| `0x1402B7490` | `npcDeserializeAndPushBack` | count-prefixed full state |
| `0x1402B7530` | `updateNPC` | cases 8/15: trail, motion, kill test |
| `0x1402B5A40` | `npcHandleAction` | DIE bursts (4×212 / 178+223) |
| `0x1402B59E0` | `npcResetAction` | DELETE |
| `0x1402B6040` | `sub_1402B6040` | MOVE / TELEPORT / OUCH (no 8/15 branch) |
| `0x1402B6950` | `renderNpc` | no sprite for 8/15 |
| `0x1402B7110` | `renderAllNpc` | 44-byte in-memory stride |
| `0x14002F680` | `sub_14002F680` | point-in-rect with either ordering |
| `0x140512630` | `getPlayerCollisionRect` | kill rect |
| `0x1404FB8F0` | `getTileAtPlayerPosition` | hitbox-centre tile |
| `0x14053C300` | `isItemDoor` | item type `DOOR` (13) exemption |
| `0x140556710` | `setTileNextUpdate` | `Tile+0x4C = now + ms` |
| `0x1405588F0` | `TileExtra::Parse` | `0x34` branch + the `someFlag` gate |
| `0x1402C8F00` | particle init | 212/276 scale 1.0, `+44 = 0.5` |
| `0x1402CD860` | particle draw | cell (0,2) / (8,14) |
| `0x1402CD700` | particle surface/frame helper | 16 px cells |
| `0x1403E6920` | `maybeSpawnParticleEffect` | effect pool (178 / 223) |
