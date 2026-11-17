# CyBots (ROBOT / COMMAND tiles) — client mechanics reference

> Client facts are marked **[verified]** when read from the binary (asm or
> pseudocode, with the address) and **[data]** when they come from `items.dat` /
> world dumps. Not-yet-decoded points are **[unknown]**; things the client cannot
> decide are `[server-side]`. The engine implementation (items, simulation,
> controller hook, world renderer) is tracked in §10.

Sources:

- `Growtopia.exe.i64` via the `gt` MCP tools + `export/ida_pseudocode/`
  (addresses below were renamed in the IDB during this analysis — §12 mapping).
- `items.dat` v27 (16580 items) through `gtools.core.growtopia.items_dat`.
- 631 world files under `/mnt/c/Users/andra/.gtools/worlds` (39 CYBOT tiles in
  12 files); worked example: `WOLFWORLD8`.
- Sprite sheet `GameData/game/npc1.rttex` (1024×1024, 32×32 frames) via
  `out/npc1.png`.

Recon artifacts (raw dumps, byte-by-byte decodes, re-runnable scripts):
`/tmp/opencode/cybot-recon/` (`items.md/json`, `world.md/json`,
`client-decode.md`).

---

## 1. Executive summary

| Question | Answer |
|---|---|
| What are the items? | `ItemInfoType.ROBOT = 113` (20 stock: Shock/Spike/Shooter/Flame/SearBot, each L1–L4) and `COMMAND = 114` (17 stock: Move Left/Right/Up/Down, Pause, Basic/Improved/Long Shot × 4 directions). |
| Where does the command program live? | In the **tile extra** (`CY_BOT_TILE`, type `0x3F`) as an ordered list of command item ids (each ~15 B on the wire). **[verified]** |
| What is `cybot_related`? | A 60-byte (15×u32) item-data field, read by the client as `item+0x78` (right after `flags2`). For **COMMAND** items it is `[mirror command id, shot speed, shot lifetime, move dx, move dy, 6 muzzle offsets, cooldown, 3 unused]`. For **ROBOT** items it is sprite/animation data + muzzle offsets + melee cooldown. **[verified] + [data]** |
| Who runs the robot? | The client, per frame, from a `CyBot` object (0x90 B) in a vector at `WorldView+0x35E8`. It walks the command list on a timer cycle, lerps its own position and fires purely cosmetic projectiles; only **deadly** projectiles and **melee** contact hurt the local player. **[verified]** |
| Networking | None for the simulation: no c→s packet sender exists anywhere in the cybot call graph. The server only ships the tile extra + the `activated` flag and (presumably) decides which robots exist. **[verified: no sender] / [server-side: placement + program edits]** |
| Timing | One clock: `GameState+0x328`, a **millisecond** server-synced timestamp. Per-command duration = the command item's `frame_interval_ms` (`item+0x10C`): **500 ms** move/pause, **2400 ms** shots, 100 ms on robot items. **[verified] + [data]** |
| Movement | 1 tile (32 px) per command window, position lerped toward the target; purely visual, no collision. **[verified]** |
| Shots | Spawned at the **end** of a shot command: speed `cybot_related[1]/100` px/ms (stock: 0.16), lifetime `cybot_related[2]` ms (stock 800/1600/2400 = 4/8/12 tiles), never collide with tiles; `ROBOT_SHOOT_DEADLY` robots' projectiles kill the player on overlap. **[verified]** |
| Melee | Armed robots (tile extra `+0x7C > 0`) with `ROBOT_DEADLY`/`ROBOT_LAVA`/`ROBOT_POINTY` damage or knock the player back through a 20×20 box test, with a per-world cooldown gate. **[verified]** |

---

## 2. Item data

### 2.1 Robot families and flags

`ItemInfoFlag2` (items.dat `flags2`, client `item+0x74`) carries the robot's
capabilities **[data + verified read site]**:

| bit | name | meaning in the robot code |
|---|---|---|
| `0x001` | `ROBOT_DEADLY` | melee contact kills the local player |
| `0x002` | `ROBOT_SHOOT_LEFT` | command direction = left (1) |
| `0x004` | `ROBOT_SHOOT_RIGHT` | command direction = right (2) |
| `0x008` | `ROBOT_SHOOT_DOWN` | command direction = down (4) |
| `0x010` | `ROBOT_SHOOT_UP` | command direction = up (3) |
| `0x020` | `ROBOT_CAN_SHOOT` | no explicit consumer found; shooting is gated by the command's direction bits |
| `0x040` | `ROBOT_LAVA` | melee burns (lava response) |
| `0x080` | `ROBOT_POINTY` | melee knocks back (spike response) |
| `0x100` | `ROBOT_SHOOT_DEADLY` | this robot's projectiles kill the player |

Stock robots **[data]** (all 20 items have `tile_range = vault_capacity =
grow_time = 0`, `frame_interval_ms = 100`):

| family | ids (L1→L4) | flags2 | notes |
|---|---|---|---|
| ShockBot | 5668, 5792, 5794, 5796 | `0x0080` | `ROBOT_POINTY` |
| SpikeBot | 5670, 5798, 5800, 5802 | `0x0001` | `ROBOT_DEADLY` |
| ShooterBot | 5708, 5780, 5782, 5784 | `0x0120` | `CAN_SHOOT \| SHOOT_DEADLY` |
| FlameBot | 5710, 5786, 5788, 5790 | `0x0160` | `CAN_SHOOT \| LAVA \| SHOOT_DEADLY` |
| SearBot | 6146, 6148, 6150, 6152 | `0x0040` | `ROBOT_LAVA` |

Stock commands **[data]**: Move Left `5672`, Move Right `5674`, Move Up `5676`,
Move Down `5678`, Pause `5680`, and the 12 shots `5682..5704` (Basic
`5682/5684/5686/5688`, Improved `5690..5696`, Long `5698..5704`, each
Left/Right/Up/Down). Move commands have `flags2 = 0`; each shot carries exactly
one `ROBOT_SHOOT_*` bit.

### 2.2 `cybot_related` — the 60-byte field

Location: items.dat parse version ≥ 9, raw 60 bytes, read by the client as **15
little-endian u32 at in-memory item offset `+0x78`** (immediately after
`flags2` at `+0x74`) **[verified: `deserializeItemDatabase` 0x14053C9A0 writes
`a1+30..a1+44`; asm read sites in `cybotRebuildCommands` (0x1403EB8B0) at
`[item+0x78]`, `[item+0x84]`, `[item+0x88]`, `[item+0x10C]` and in
`cybotExecuteCommand` (0x1403EA820) at `[item+0x7C]`, `[item+0x80]`,
`[item+0xA4]`, `[item+0x8C..0xA0]`]**.

#### COMMAND items (item_type 114)

| idx | off | field | stock values **[data]** |
|---|---|---|---|
| 0 | 0x78 | **mirror command item id** (0 = none) | Move Left↔5674, Move Right↔5672, Move Up↔5678, Move Down↔5676, Pause→5680 (self), **all 12 shots = 0** |
| 1 | 0x7C | **shot speed / 100** (px per ms, float used as `[1]/100.0`) | 16 → 0.16 px/ms for every shot; 0 for move/pause |
| 2 | 0x80 | **shot lifetime (ms)** | Basic 800, Improved 1600, Long 2400; 0 for move/pause |
| 3 | 0x84 | **move offset dx (tiles, signed)** | Left −1, Right +1, others 0 |
| 4 | 0x88 | **move offset dy (tiles, signed)** | Up −1, Down +1, others 0 |
| 5,6 | 0x8C/0x90 | muzzle offset left (dx, dy px) | 0 |
| 7,8 | 0x94/0x98 | muzzle offset up (dx, dy px) | 0 |
| 9,10 | 0x9C/0xA0 | muzzle offset down (dx, dy px) | 0 |
| 11–14 | 0xA4..0xB0 | unused for commands | 0 |

Meaning of indices 1–4 is **[verified]** from the consumers
(`cybotExecuteCommand` 0x1403EA820 for 1/2, `cybotRecomputeTarget` 0x1403EB000
for 3/4 read as `*(int*)… * 32.0` px, `cybotRebuildCommands` 0x1403EB8B0 for
0 and for the mirror-pass gate on Σ3/Σ4); the muzzle offsets 5–10 are read by
`cybotExecuteCommand` but are 0 for every stock command **[data]** (their
up/down meaning is therefore [unknown] beyond the read sites).

Projectile range = `idx1/100 × idx2`: 0.16 px/ms × 800/1600/2400 ms =
128/256/384 px = **4/8/12 tiles** — the documented Basic/Improved/Long ranges.

#### ROBOT items (item_type 113)

| idx | off | field | stock values **[data]** |
|---|---|---|---|
| 0 | 0x78 | **unknown, constant 11** for all 20 robots (not an offset: it reads as "Rock Seed" only by coincidence of item ids) | [unknown] |
| 1 | 0x7C | **sprite base frame** in `game/npc1.rttex` | ShooterBot 0/23/46/69; FlameBot 96/119/142/165; SpikeBot 192/195/198/201; ShockBot 224/227/230/233; SearBot 256/259/262/265 |
| 2 | 0x80 | **idle/walk frame count** (200 ms per frame) | 3 |
| 3 | 0x84 | **directional frame count** (400 ms per frame) | 6 |
| 4 | 0x88 | **projectile frame count** | 2 |
| 5,6 | 0x8C/0x90 | muzzle offset left (dx, dy px) | 0 |
| 7,8 | 0x94/0x98 | muzzle offset up (dx, dy px) | 0 |
| 9,10 | 0x9C/0xA0 | muzzle offset down (dx, dy px) | 0 |
| 11 | 0xA4 | **melee hit cooldown (ms)** added to the world gate | 0 |
| 12–14 | 0xA8..0xB0 | unused | 0 |

The muzzle offsets are read in `cybotExecuteCommand` as `int → float` px added
to the shot origin: left uses `+[5],+[6]`, right `−[5],+[6]`, up `+[7],+[8]`,
down `+[9],+[10]` **[verified]**.

The level-to-level base-frame steps (23 for the shooters, 3 for the walkers) are
explained by the sprite layout in §9: a shooter's per-level block is 3 + 3×6 + 2
= **23 frames**, a walker's is only the 3-frame idle cycle because walkers never
receive a shoot direction.

#### Companion fields next to the blob

- `item+0x10C` = **`frame_interval_ms`** (the 4-byte items.dat field parsed right
  after `extra_file_hash`; unique per-command varying field) — used by the
  client as the **command duration in ms** **[verified read sites: 0x1403EBF60,
  0x1403EC090, 0x1403EB1D0, 0x1403EB8B0 (sum) — all `[item+0x10C]`; data:
  500 move/pause, 2400 shots, 100 robots]**.
- `flags2` at `+0x74` is *not* part of the blob (it precedes it) but is read by
  the same code.
- The IDB's `ItemDat` struct is **mis-modelled** in this region (`flags2` at
  `0x6F`, blob at `0x73`); a comment at `deserializeItemDatabase` records the
  verified offsets. The runtime record stride is **1616** bytes
  (`itemDatabaseFromId` 0x14053A170), not the 4435-byte `ItemDat` struct.

---

## 3. The tile extra — `CY_BOT_TILE` (`0x3F`)

Parsed by `TileExtra::Parse` (0x1405588F0, its `CY_BOT_TILE` switch case)
**[verified]**:

```
u32 count                     // number of command entries
repeat count:
    u32 itemId                // command item id (COMMAND item)
    u8  enabled?              // always 1 in all 39 captured tiles   [unknown meaning]
    u32 unk20                 // always 0                            [unknown]
    i32 unk24                 // always 0                            [unknown]
    pascal string "H"         // always empty in all captured tiles  [unknown]
u32 anchor                    // extra+0x70  — command-cycle anchor (ms)
u32 activated                 // extra+0x7C  — "robot is on" flag (server-set)
```

- In memory each entry is a **48-byte struct**: `std::string name` at `+0x00`
  (32 B), `u32 unk20` at `+0x20`, `i32 unk24` at `+0x24`, `u32 itemId` at
  `+0x28`, `u8 enabled` at `+0x2C`. The vector lives at
  `TileExtra+0xD8` (begin) / `+0xE0` (end) — stride **48**.
- The client simulation reads only **`entry+0x28` (the item id)**; `enabled`,
  `unk20` and `unk24` are parsed and re-serialized but never read by the cybot
  code, and the entries' strings are unused. **[verified by exhaustion of the
  vector's readers: `TileExtra::Parse`, `cybotRebuildCommands`,
  `cybotRefreshAtTile`, tile init]**
- gtools names: `sync_timer` = `extra+0x70` (**correct**: it is the cycle
  anchor), `activated` = `extra+0x7C` (**correct**: the client tests it `> 0` as
  "armed"). Those two are the generic `intParam1` / `placedTimestamp` slots in
  the IDB `TileExtra` struct.
- `activated` behaviour **[verified]**: `> 0` enables melee damage
  (`cybotArmedForDamage`), gives full draw alpha and lets non-owners see the
  robot; `0` keeps the robot drawn at alpha 128 for the lock owner only and
  prevents its shots from being deadly. The tiles in the wild have `activated =
  1` whenever the program is non-empty and `0` for an empty program. Provenance
  `[server-side]`.

---

## 4. Runtime objects

### 4.1 `WorldView` slots

| offset | contents | evidence |
|---|---|---|
| `+0x35E8` (13800) | `std::vector<CyBot*>` — robots | all robot functions are called with `WorldView+13800` |
| `+0x3600` (13824) | dword **"next robot hit allowed at"** (ms clock) | `cybotApplyMeleeDamage` gate |
| `+0x3608` (13832) | projectile pool (two vectors: active `+0/+8/+10`, free stack `+0x18/+0x20/+0x28`) | spawn/update/render calls |
| `+0x128` (296) | cybot tile **counter** (`++`/`--` only) | `cybotTileCounterInc/Dec` (0x14055F340 / 0x14055FAE0) |

`WorldView` is `*(GameState+0x110)` (`sub_1403F2800` is the getter
`mov rax,[rcx+110h]`) **[verified]**.

### 4.2 `CyBot` object (0x90 bytes, no vtable)

Declared in the IDB as `CyBot` **[verified: ctor 0x1403EA0E0 + all use sites]**:

| off | field | notes |
|---|---|---|
| `0x00/08/10` | `cmdBegin/cmdEnd/cmdCap` | vector of 8-byte heap records `{u32 direction; u32 itemId}` |
| `0x18` | `cycleDurationMs` | Σ command durations (from `item+0x10C`) |
| `0x1C` | `currentIndex` | index into the command vector |
| `0x20` | `cmdStartMs` | current window start (clock ms) |
| `0x24` | `cmdEndMs` | current window end |
| `0x28` | `lastMoveTimeMs` | used for the movement dt |
| `0x2C` | `cycleAnchorMs` | copied from the tile extra `+0x70` |
| `0x30/34` | `posX/posY` | float world px (tile centre + accumulated offsets) |
| `0x38/3C` | `targetX/targetY` | lerp target |
| `0x40` | `facingLeft` | 1 = moving left (drives the sprite flip) |
| `0x44` | `drawCounter` | reset at each command start, `++` per draw |
| `0x48..0x77` | 4 probe records `{u32 id=0..3; float x; float y}` | scratch for the melee box |
| `0x78` | `shootDeadly` | 1 iff the robot item has `flags2 & 0x100` (cleared when unactivated) |
| `0x7C` | `hitAxis` | −1 none / 0 X knockback / 1 Y knockback |
| `0x80` | unknown | cleared to −1 with `0x7C`, no reader found |
| `0x88` | `tile` | the robot's `Tile*` |

### 4.3 Projectile object (0x48 bytes)

Pool at `WorldView+0x3608`; recycled through the free stack **[verified:
factory 0x1403E97E0, update 0x1403E9C70, render 0x1403E9B00]**:

| off | field |
|---|---|
| `0x00` | `SurfaceAnim*` (npc1.rttex) |
| `0x08` | sprite base frame (`robotBlob[1] + robotBlob[2] + 3*robotBlob[3]`) |
| `0x0C` | frame count (robot blob[4] = 2) |
| `0x10` | **angle** (−90 up / +90 down / 0 left-right) — passed to the blit |
| `0x14/18` | spawn origin (px) |
| `0x1C` | **flip byte** (1 = established for left shots, 0 otherwise) — passed to the blit |
| `0x20` | sentinel: −1 armed / −128 unactivated (also an argument of the blit, meaning unknown) |
| `0x24` | **lifetime ms** (command blob[2]) |
| `0x28` | accrued ms |
| `0x2C` | last update clock |
| `0x30` | **speed px/ms** (command blob[1]/100) |
| `0x34/38` | direction unit vector |
| `0x3C/40` | current position (px) |
| `0x44` | **deadly** (= robot `shootDeadly`) |

---

## 5. Lifecycle and flow

```
world enter / tile change / tile update
   └─ cybotRegisterAllFromWorld 0x1403EAE70   (every ROBOT tile, world enter)
      cybotRegisterAtTile      0x1403EB310   (placed ROBOT, via applyTileChange 0x140566510)
      cybotRefreshAtTile       0x1403EBD60   (server TILE_UPDATE of a ROBOT tile)
         └─ cybotRebuildCommands 0x1403EB8B0  (build the command list + mirrors)
            └─ cybotScheduleFromClock 0x1403EB1D0  (phase-sync from the clock)

per frame (OnUpdate sub_140404280 → WorldView update sub_140586670)
   ├─ cybotTickAll   0x1403EC040  →  cybotTick 0x1403EBF60 (per robot)
   │       ├─ cybotExecuteCommand 0x1403EA820   (when a window ends)
   │       ├─ cybotRecomputeTarget 0x1403EB000
   │       └─ cybotMove 0x1403EC090
   ├─ cybotProjectilesUpdate 0x1403E9C70
   └─ (via FindNearestInteractableTile 0x140512690, per avatar tick)
          ├─ cybotProbeAll 0x1403EA730 → cybotApplyMeleeDamage 0x1403EA370
          └─ cybotProjectilesCheckKill 0x1403E9670

per frame render (onRender 0x1403FFFA0 → sub_140585AB0)
   ├─ cybotRenderAll 0x1403EB860 → cybotRender 0x1403EB420
   └─ cybotProjectilesRender 0x1403E9C20 → cybotProjectileRender 0x1403E9B00
```

### 5.1 Building the command list (`cybotRebuildCommands` 0x1403EB8B0)

1. Frees the previous list (`DebugLog("Deleting All Commands")`).
2. Stores the tile pointer (`CyBot+0x88`) and `shootDeadly` from the robot
   item's `flags2 & 0x100`.
3. For each 48-byte tile entry → one `{direction, itemId}` record, where
   **direction** comes from the *command item's* `flags2` through
   `cybotCommandDirection`: `LEFT(0x2)→1`, `RIGHT(0x4)→2`, `UP(0x10)→3`,
   `DOWN(0x8)→4`, else `0`. `DebugLog("Adding Command , %i")`.
4. **Mirror pass** — only when `Σ cmdItem.cybot_related[3] != 0` or
   `Σ cmdItem.cybot_related[4] != 0` (i.e. the program actually moves): iterate
   the list **in reverse**; for each command item whose `cybot_related[0]`
   resolves to a **COMMAND** item, append that mirror item as another command
   (its own direction from its `flags2`). `DebugLog("Adding Mirror Command ,
   %i")`. → a one-way route becomes an out-and-back patrol; an explicitly
   balanced route (Σ = 0, e.g. WOLFWORLD8 tile 0: 5×Right + 5×Left) gets no
   mirrors.
5. Sums each command's duration (`item+0x10C`) into `cycleDurationMs` — this
   sum runs over the **final** list (mirrors included); the `Σ3/Σ4` sums from
   step 4 are only the mirror gate.
6. `cycleAnchorMs = tileExtra+0x70`; then `cybotScheduleFromClock`.

Empty program → `cycleDurationMs = 0` → `cybotScheduleFromClock` does nothing
and `cybotTick` early-outs; the robot just idles at its tile centre.

### 5.2 Scheduling (`cybotScheduleFromClock` 0x1403EB1D0)

```
anchor = tileExtra+0x70                       // saved cycle start (ms)
now    = GameState+0x328                      // server-synced clock (ms)
if (now < anchor) { Log("Problem , saved time has to be less"); anchor = now; }
elapsed = now - anchor
phase   = elapsed % cycleDurationMs
cycles  = floor(elapsed / cycleDurationMs)
walk the commands while acc + duration <= phase  → index, acc
cmdStartMs = anchor + cycles*cycleDurationMs + acc
cmdEndMs   = cmdStartMs + duration(index)
cybotRecomputeTarget(index, resetPos=1)
```

### 5.3 Per-frame tick (`cybotTick` 0x1403EBF60)

```
now = GameState+0x328
if (now > cmdEndMs):
    cybotExecuteCommand(currentIndex)     // side effect of the command that just ENDED
    currentIndex = (currentIndex + 1) % count
    cmdStartMs = old cmdEndMs
    cmdEndMs   = cmdStartMs + duration(newIndex)
    cybotRecomputeTarget(newIndex, resetPos=0)
cybotMove()
```

Note the semantics: a command's **effect fires when its window closes** — for
shot commands that is the end of the 2400 ms window, not the start **[verified
in `cybotTick` + `cybotExecuteCommand`]**. Movement happens *during* the window.

### 5.4 Movement (`cybotRecomputeTarget` 0x1403EB000 + `cybotMove` 0x1403EC090)

- `cybotRecomputeTarget(resetPos=1)` (scheduling): `pos = tileToWorldCenter(tile)`
  then adds `(cybot_related[3]*32, cybot_related[4]*32)` px for every command
  **before** `index`; then `target = pos + current command's offset` and
  `drawCounter = 0`.
- `cybotRecomputeTarget(resetPos=0)` (tick): only `target = pos + offset`;
  the caller-supplied `pos` is retained (index 0 re-centres on the tile).
- `cybotMove()`: if `now ∉ [cmdStartMs, cmdEndMs)` → `DebugLog("Skipping
  Movement")`; else `step = (now − lastMoveTimeMs) * 32.0 / duration`, then
  `lerpTo(posX, targetX, step)` / `lerpTo(posY, targetY, step)` (clamped), and
  `facingLeft = 1` if x decreased else `0` if it increased. Over a whole window
  the accumulated step is exactly one tile, so the robot arrives as the window
  ends; with the stock 500 ms move commands that is **64 px/s**.
- **The robot's position is cosmetic**: no collision, tile or permission query
  exists in the movement path. It is reconstructed from the command offsets on
  schedule, so it is stateless and deterministic.

### 5.5 Clock

All cybot code reads `GameState+0x328` **[verified in asm at 0x1403EBF60,
0x1403EC090, 0x1403EB1D0, 0x1403EA370, 0x1403E97E0, 0x1403E9C70, 0x1403EB420,
0x1403E9B00]** — the decompiler renders it as `sdk::GetGameState()->inventory.pad_00[380]`.
`ProcessTankUpdatePacket` (SEND_MAP_DATA) stores the map-data tank's `int_x`
(decompiler: `maybeWorldId`) at `+0x320`, `GetTickCount()` at `+0x324` and
copies `+0x320` to `+0x328`; the per-frame `OnUpdate` (0x140404280) then keeps
`+0x328 = (+0x320 − +0x324) + GetTickCount()` — i.e. **an estimated current
server time in milliseconds** (for the arithmetic to be meaningful `int_x` must
be a server ms timestamp; its exact provenance is [unknown], the old
"maybeWorldId" name is a leftover guess). Unit proofs: 32 px per 500 ms command;
0.16 px/ms × 800 ms = 128 px = 4 tiles; sprite animations divide the same value
by 200/400. Note this is *not* `getTick` (AppContext) nor `GetTickCount`
directly — but the estimate is anchored to the local `GetTickCount`.

---

## 6. Shots (`cybotExecuteCommand` 0x1403EA820 + projectile code)

Called at the end of every command window; only shot commands do anything:

1. `direction = cybotCommandDirection(cmdItem.flags2)` (1 left, 2 right, 3 up, 4 down, 0 none);
   `if (direction == 0) return;` (move/pause commands end silently).
2. Loads `game/npc1.rttex`, computes the projectile base frame
   `robotItem.cybot_related[1] + [2] + 3*[3]` and the frame count
   `robotItem.cybot_related[4]`.
3. `armed = tileExtra+0x7C > 0`; when unarmed it clears `CyBot.shootDeadly`
   (non-deadly shots) and passes the −128 sentinel.
4. Requires `cybotIsActive` (§8) and the command item to be `COMMAND`.
5. Spawns into the pool: origin
   `pos + muzzle offsets` (left `+[5],[6]`, right `−[5],[6]`, up `+[7],[8]`,
   down `+[9],[10]`), unit direction (left `(−1,0)`, right `(1,0)`, up
   `(0,−1)`, down `(0,1)`), angle `0` (left/right) / `−90` / `90`, speed
   `cmdBlob[1]/100`, lifetime `cmdBlob[2]`, deadly `CyBot.shootDeadly`.

Projectile update: `pos += dt * speed * dir`, retire when `accrued >= life`;
**no tile/wall collision**. Render: `frame = baseFrame + clock/200 % frameCount`.

The draw call (`cybotProjectileRender` 0x1403E9B00) passes `+0x1C` (flip) and
`+0x10` (angle) as stack arguments to `spriteDraw` — visible in the asm
(`movzx eax, byte ptr [rsi+1Ch]`, `movss xmm0, dword ptr [rsi+10h]`), the
decompiler's 6-argument prototype drops them. So the faithful orientation is:
left shots mirrored, up/down shots **rotated ∓90°**, everything else upright.

Deadly check (`cybotProjectilesCheckKill` 0x1403E9670, called from
`FindNearestInteractableTile`): for each projectile with `+0x44 == 1` (fired by
a `ROBOT_SHOOT_DEADLY` robot) overlapping the player's collision rect, call
`killPlayer` unless the avatar state byte `+0x2088 == 6` (suppresses the kill;
the exact state name is unverified) **[verified]**. Non-deadly projectiles never
hurt the player.

## 7. Melee contact (`cybotApplyMeleeDamage` 0x1403EA370)

Called through `cybotProbeAll` (0x1403EA730, "all robots must return 1, stop at
the first 0") from `FindNearestInteractableTile` (0x140512690) — the same probe
pass that handles damaging tiles; the two `float*` arguments are the avatar's
horizontal/vertical velocity components, which the knockback responses write.

Conditions **[verified]**:

1. `cybotArmedForDamage` (0x1403EA240): local player exists, no
   `CharacterFlags.IGNORE_SPIKES` (`NetAvatar+0x188` bit `0x400`), if
   `avatar+0x179 || +0x17A` are set then `NOCLIP` (bit `0x1`) must be clear, and
   `tileExtra+0x7C > 0` (activated).
2. Robot item has `ROBOT_DEADLY (0x1)`, `ROBOT_LAVA (0x40)` or `ROBOT_POINTY (0x80)`.
3. The player's own tile (`getTileAtPlayerPosition`) is not a **Main Door**
   (item id 6) — no robot contact while standing on one.
4. Build a 20×20 px box around `posX/posY` (the four probe records) and test it
   against the player's collision rect (four corner-in-rect tests).

On overlap:

- `ROBOT_DEADLY` → `killPlayer` immediately (unless avatar state `+0x2088 == 6`)
  and the scan stops; **no cooldown**.
- Otherwise the world gate `WorldView+0x3600 > now` must be false; then
  `WorldView+0x3600 = now + robotItem.cybot_related[11]` (0 for stock robots —
  so only the same-tick double-hit is prevented) and the robot is knocked back:
  angle between the robot and the player's rect centre decides **X axis**
  (robots mostly to the side → `handleDamagingTileCollision`,
  `CyBot.hitAxis = 0`) or **Y axis** (`sub_1404FC0B0`, `hitAxis = 1`), i.e. the
  same responses as lava/spike tiles → the player is pushed and optionally
  burned.

### 7.1 The knockback is velocity-relative, not robot-relative

The X response (`handleDamagingTileCollision` 0x1404FBFF0) is `*vx = -*vx`,
clamped to ≥300 px/s in the new direction while `damageSlip` is clear; the Y
response (`sub_1404FC0B0`) launches `vy` to -800 / flips a rising `vy` / -50
without a vertical axis, sets `damageSlip` and clamps `vx`. Both write the
avatar's velocity components that `NetAvatar::tickAux` (0x140503160) unpacks
before `FindNearestInteractableTile` and re-packs afterwards — the knockback is
plainly a velocity flip, with **no notion of where the robot is**.

Consequences (all measured in the engine port, `tests/test_cybot_sim.py`):

- Touching the box while standing still (or moving away from it) flips `-0.0`
  to **+300 px/s — into the box** when the bot is on that side. This is the
  "clipped into the cybot" feel: the response itself shoves the player in.
- The corner test passes for the player's whole 40 px engagement band
  (`box.left - 20 … box.right` at floor level), and stock cooldown is 0, so
  once inside, **every frame hits**: measured 240/240 and 600/600 frames of
  contact, the player jittering ±5 px around the touch point (one 5 px step per
  flip at 300 px/s / 60 Hz).
- **No input escapes a running juggle**: walking away, walking into the bot and
  jump spam are all re-flipped on the next frame (the flip always reverses the
  step). It ends only when the box moves away with the robot's command cycle,
  the robot is disarmed, `IGNORE_SPIKES` is set, or the player dies.
- The normal knockback feel (bounce out) happens only when the *first* contact
  catches the player moving toward the box near the band's edge: the flip then
  points out and the 5 px step clears the band before the next hit.
- The angle fold is `acos(dot(v, +X̂) / (|v|·1))` in degrees
  (`sub_14002F9F0` + `sub_14002EA70`): X axis iff `< 45° or > 135°`, i.e.
  `|dx| > |dy|` — equivalent to the port's `atan2(|dy|, |dx|) < 45°`.

## 8. Rendering and the "active" gate

- `cybotIsActive` (0x1403EA2B0) gates **both drawing and shots**: a robot is
  processed when `GameState.world != 0` and the local player either **governs
  the robot tile's lock** (`tileLockOwnedByUser` 0x1405559C0: own `LOCK_TILE`
  owner id, or the parent/world lock's owner — same model as
  `docs/lock-permissions.md`), or `activated > 0`, or `avatar+0x179/+0x17A`
  (the owner/override bytes used elsewhere for punch reach and display-box
  access). Non-owners do not see or simulate unactivated robots.
- `cybotRender` (0x1403EB420): sprite `game/npc1.rttex`, alpha **255 when
  activated / 128 when not**, position `posX/posY`, `++drawCounter`.

**Sprite layout** in `npc1.rttex` (32×32 frames) **[verified formulas + spot
checks against `out/npc1.png`]**:

| animation | frame index (relative to blob[1]) | rate |
|---|---|---|
| idle / walking (direction 0: move & pause commands) | `0 .. blob[2]−1` (3) | `clock/200 % blob[2]` |
| left/right (dir 1–2 share frames, `facingLeft` flips) | `blob[2] .. blob[2]+blob[3]−1` (6) | `clock/400 % blob[3]` |
| up (dir 3) | `+blob[3]` window (6) | `clock/400 % blob[3]` |
| down (dir 4) | `+2*blob[3]` window (6) | `clock/400 % blob[3]` |
| projectile | `+blob[2]+3*blob[3]` (2) | `clock/200 % blob[4]` |

Total per robot level = `blob[2] + 3*blob[3] + blob[4]` = 3+18+2 = **23 frames**
— exactly the ShooterBot/FlameBot level stride. Walker robots never get a shoot
direction (their commands have `flags2 = 0`), so they only ever use the 3-frame
idle cycle, which is why their level stride is 3 (12 frames per family). The
frame→(x,y) mapping is `x = index % rowWidth`, `y = index / rowWidth`
(rowWidth from the surface, 32 for npc1.rttex).

## 9. Worked example — `WOLFWORLD8`

6 CYBOT tiles **[data]**:

| tile | fg | program (tile-extra order) | anchor | activated |
|---|---|---|---|---|
| (32,24) | ShockBot L4 (5796) | 5× Move Right, 5× Move Left | 27,044,457 | 1 |
| (86,35) | FlameBot L4 (5790) | 1× Basic Shot Right | 285,145,971 | 1 |
| (90,35) | ShooterBot L4 (5784) | 1× Basic Shot Left | 285,217,961 | 1 |
| (76,44) | ShockBot L4 (5796) | 18 commands (R/L/U/P/D pattern, Σ offsets = 0) | 279,682,575 | 1 |
| (84,44) | ShooterBot L4 (5784) | Shot Up, 2× Move Left, Shot Right, Pause, 2× Move Right | 284,218,295 | 1 |
| (90,46) | ShockBot L4 (5796) | 13 commands (Σ offsets = 0) | 279,416,567 | 1 |

Raw bytes of one entry (28-byte extra, FlameBot): `3f | 01 00 00 00 |
34 16 00 00 | 01 | 00 00 00 00 | 00 00 00 00 | 00 00 | 73 fb fe 10 | 01 00 00 00`
= type 0x3F, count 1, entry (`itemId 5684`, enabled 1, 0, 0, empty string), anchor
285,145,971 ms, activated 1.

Because Σ(dx) and Σ(dy) are 0 for these programs, **no mirror commands** are
generated for any of these tiles at runtime (the routes are already closed
loops); a single Move command would become "Move X, mirror(Move X)".

## 10. gtools status (implemented)

| layer | module | what it does |
|---|---|---|
| items.dat | `items_dat.py` | the 60-byte field is parsed at load into typed `Item.cybot`: `ItemInfoCyBotCommand` (mirror id, shot speed/lifetime, move dx/dy, muzzle offsets, unknowns) or `ItemInfoCyBotRobot` (sprite base + frame counts, muzzle offsets, melee cooldown). Any future non-ROBOT/COMMAND payload is logged, never dropped silently. `ItemInfoCyBotCommand.muzzle_for_direction()`, `shot_speed_px_per_ms`, `ItemInfoCyBotRobot.projectile_base_frame`/`sprite_block_frames` carry the derived client math. |
| world format | `world.py` | `CyBotCommandData` now matches the real entry (`item_id; enabled; unk20; unk24; H string`) and `CybotTile` exposes `anchor_ms` / `activated`; round-trip is pinned by `tests/test_cybot_data.py` incl. captured WOLFWORLD8 bytes. |
| simulation | `cybot.py` | `CyBot` (commands/mirrors, scheduling, window-end effects, one-tile-per-window movement, sprite frame/flip/alpha), `CyBotProjectile`, `CyBotWorld` (load/sync_tile/tick/apply_melee/check_kills) — a direct port of the functions in §4–§8. |
| local player | `physics/controller.py` | `PlayerController.cybots` hook: the probe pass (`_touch`) runs `apply_melee` + `check_kills`, exactly where the client's `FindNearestInteractableTile` runs them. Damage reuses the controller's own `_kill` / `_damaging_x` / `_damaging_y` (the same client functions the robot path calls). The physics demo binds it with `controller.cybots = world_renderer.cybots` (the renderer owns and ticks the simulation). |
| renderer | `gui/lib/cybot_renderer.py` + `shaders/cybot*.vert` | world-renderer sub-renderer: robots + projectiles from `game/npc1.rttex`, frame/flip/alpha/angle as in §8, ticked from `WorldRenderer.update` (which also keeps the view dirty), tile updates forwarded to `CyBotWorld.sync_tile`. |

Renderer-space note: the GUI world space centres tile `(x, y)` at
`(x*32, y*32)` (`highlight_renderer`, the tile meshes), while the client puts the
tile centre at `tile*32 + 16` (`tileToWorldCenter`) — the cybot renderer shifts
sprites by `-16` px (`cybot_renderer.WORLD_OFFSET`) so they line up with the rest
of the world. The viewer also draws unactivated robots (at alpha 128), which the
client only does for the tile's lock owner / build overrides.

Tests: `tests/test_cybot_data.py`, `tests/test_cybot_sim.py`,
`tests/test_cybot_renderer.py` (headless — no GL needed).

## 11. Open questions

| # | question | evidence so far |
|---|---|---|
| 1 | `cybot_related[0] == 11` on every ROBOT item | never read by the cybot code paths found; constant in data |
| 2 | tile-extra entry `enabled` (always 1), `unk20`, `unk24` (always 0), command string (always empty) | parsed/serialized, no client reader inside the cybot code; likely server bookkeeping `[server-side]` |
| 3 | robot blob[11] "melee cooldown" is 0 for all stock robots | unit/clock domain = same ms clock (added to `now`), but no stock item exercises it |
| 4 | muzzle offsets blob[5..10] are 0 for all stock items | read as px offsets; sign conventions verified from asm, magnitudes not observable |
| 5 | what exactly the server does — who may edit a robot's program, when `activated` flips, whether illegal command/robot combinations are rejected | not visible in the client `[server-side]` |
| 6 | why the command effect fires at the window **end** | verified behaviour; rationale unknown |
| 7 | `CyBot+0x80` cleared to −1 with `hitAxis`, no reader | unknown/dead state |
| 7b | projectile `+0x20` sentinel (−1 / −128) is passed to the sprite blit (E9B00) | its effect in the blit is undecoded; the engine keeps the field |
| 8 | walker families' directional frames would read into neighbouring NPC sprites if a shoot command were attached to them | client has no guard; presumably prevented server-side `[server-side]` |
| 9 | `avatar+0x179/+0x17A` semantics in `cybotIsActive` | same bytes gate punch reach and display-box access (owner/override); exact flag names unverified |

## 12. Evidence index (functions, after the IDB rename)

| address | name | role |
|---|---|---|
| 0x14053C9A0 | `deserializeItemDatabase` | items.dat field parser; comment lists the verified item-record offsets |
| 0x14053A170 / 0x14053A120 | `itemDatabaseFromId` / `getItemById` | 1616-byte record stride |
| 0x1405588F0 | `TileExtra::Parse` | `CY_BOT_TILE` wire format |
| 0x14055F340 / 0x14055FAE0 | `cybotTileCounterInc/Dec` | `WorldView+0x128` counting |
| 0x140566510 | `applyTileChange` | local + server tile changes; registers robots |
| 0x1403EAE70 | `cybotRegisterAllFromWorld` | world enter |
| 0x1403EB310 | `cybotRegisterAtTile` | placed ROBOT tile |
| 0x1403EBD60 | `cybotRefreshAtTile` | server TILE_UPDATE |
| 0x1403EB8B0 | `cybotRebuildCommands` | command list + mirrors + durations |
| 0x1403EB1D0 | `cybotScheduleFromClock` | phase sync |
| 0x1403EBF60 / 0x1403EC040 | `cybotTick` / `cybotTickAll` | per-frame tick |
| 0x1403EC090 | `cybotMove` | lerp + facing |
| 0x1403EB000 | `cybotRecomputeTarget` | position/target reconstruction |
| 0x1403EA820 | `cybotExecuteCommand` | shot spawn at window end |
| 0x1403EACA0 | `cybotCommandDirection` | flags2 → 1..4 |
| 0x1403E97E0 / 0x1403E9C70 / 0x1403E9C20 / 0x1403E9B00 / 0x1403E9A40 / 0x1403EA050 | projectile spawn/update/render/retire/free | pool at `+0x3608` |
| 0x1403E9670 | `cybotProjectilesCheckKill` | deadly projectile kill |
| 0x1403EA730 / 0x1403EA370 | `cybotProbeAll` / `cybotApplyMeleeDamage` | melee box + kill/knockback |
| 0x1403EA240 / 0x1403EA2B0 | `cybotArmedForDamage` / `cybotIsActive` | gates |
| 0x1403EAD10 / 0x1403EADC0 | `cybotDamageResponseX/Y` | damaging-tile responses |
| 0x1403EB420 / 0x1403EB860 | `cybotRender` / `cybotRenderAll` | sprites |
| 0x1403EA0E0 / 0x1403EA160 / 0x1403EA200 / 0x1403EA7A0 | ctor / dtor / list free / list clear | — |
| 0x1405559C0 | `tileLockOwnedByUser` | lock governor check |
| 0x140512690 | `FindNearestInteractableTile` | melee + deadly projectile call site |
| 0x140586670 / 0x140404280 | WorldView update / OnUpdate | tick chain |
| 0x140404280 (`+0x328` init in 0x140405470) | clock maintenance | `GameState+0x320/0x324/0x328` |

IDB enrichment applied this session: `CyBot` struct, renamed ~30 functions
(the table above), comments on all key sites. Legacy names (pre-rename) are the
`sub_*` names used in the recon artifacts and previous docs; the mapping is in
the table.
