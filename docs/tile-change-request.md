# TILE_CHANGE_REQUEST — send path, cadence, and coupling to STATE

Target: **Growtopia** client (protocol 226, `game_version 5.58`), PE x64, image base `0x140000000`.
All addresses are IDA virtual addresses in `Growtopia.exe.i64`. Every claim is annotated in the
IDA database at the cited address, or quoted from the read-only logs in `~/.gtools/logs`.

Status: press/hold/release pipeline traced (`onTouchInput` / `onTouchHoldTick` /
`HandleTouch`), rate gates located, action-bit coupling resolved. The port lives in
`gtools/core/growtopia/physics/controller.py` (`PlayerController.touch_press` /
`touch_hold` / `request_change`).

---

## 1. Executive summary

| Question | Answer |
|---|---|
| Cadence | **Event-driven.** Per-tile de-dup + the punch-animation gate bound the repeats; a 333 ms/80 ms pair gates the special-item tap paths. Measured dominant rate **5/s**, hard ceiling **10/s** (32,432 active seconds). |
| Flow | `onTouchInput` (press) / `onTouchHoldTick` (hold) → `HandleTouch` (`0x140411CF0`) → `sendTileChangeRequest` (`0x140407570`) → `SendPacketRaw(4, …, 56, 0, …)`. Five other entry points exist. |
| STATE coupling | **Independent emitters on a shared tick.** The action bits ORed into `avatar+0x134` (`PUNCH|TILE_CHANGE` / `PLACE|TILE_CHANGE`) reset the `sendTankState` 200 ms gate, so the chained frame leaves on the next tick. |
| Held button | Repeats the **Fist punch** only (the Fist's `item_type` is 0, which bypasses the per-tile de-dup); placeable items fire once per press. Hold stops after 11 s. |

---

## 2. The sender

`sendTileChangeRequest` @ `0x140407570` (345 bytes)

```c
void __fastcall sendTileChangeRequest(GameState *gameState, Tile *tile,
                                      uint32_t itemId, bool hasExtraFloat, float extraFloat)
{
    TankPacket pkt; memset(&pkt, 0, sizeof pkt);
    pkt.type      = TANK_TILE_CHANGE_REQUEST;   // +0x00
    pkt.int_x     = tile->tileX;                 // +0x2C   target tile column
    pkt.int_y     = tile->tileY;                 // +0x30   target tile row
    pkt.value     = itemId;                      // +0x14   item used (18 = FIST punch)
    if (hasExtraFloat) {
        if (getProtocolVersion() < 999999) return;      // KILL SWITCH - aborts
        pkt.float_var = extraFloat;              // +0x10
    }
    pkt.vector_x  = player->playerPosX;          // +0x18   <-- PLAYER POSITION STAMPED IN
    pkt.vector_y  = player->playerPosY;          // +0x1C
    if (player->isFacingLeft) pkt.flags |= TANKFLAG_FACING_LEFT;   // +0x0C

    if (gameState->gapDC[28]) {                  // local-preview mode: do NOT send
        if (getItemManager()->itemsBegin[itemId].item_type)
            handleTileTreeState(gameState->world, &pkt);
        else
            toggleOnOff(tile, 1, 0, -1);
    } else {
        SendPacketRaw(4, &pkt, 56, 0, getAppContext()->networkContext->enetHost);
    }
}
```

**Packet**: 56 bytes, ENet **channel 4**, reliable. `vector_x`/`vector_y` carry the
player's own position at the moment of the edit — the server's reach-validation input.

## 3. Flow — press, hold and `HandleTouch`

### 3.1 `onTouchInput` @ `0x140414020` — the press path

```c
void onTouchInput(TouchInputState *state, void *evt)      // "OnTouchStart"
{
    state->lastTileIndex /* +0xB8 */ = -1;                // reset the de-dup guard
    if (!getLocalPlayer(gs)) { DebugLog("Can't touch yet"); return; }
    /* ... pinch/drag setup reads the two touch points ... */
    state->screenPos.x /* +0xCC */ = input.x;             // cached cursor
    state->screenPos.y /* +0xD0 */ = input.y;
    // inventory/held-item read: itemId = gs->heldItemId /* +0x248 */;
    // item = itemsBegin + itemId * 0x650; item->item_type at +0x4
    if (findAvatarAtPosition(getAllPlayer(), worldPos)) {       // cursor on a player
        /* send "action|wrench|<netid>" (channel 2) + audio/tile_remov.wav */ return;
    }
    if (item && item->item_type == WRENCH && findAvatarAtTile(...)) { /* same wrench path */ return; }
    state->holdActive /* +0xC8 */ = 1;
    screenToWorld(cam, state->screenPos, &worldPos);
    HandleTouch(state, state->screenPos.x, &worldPos, /*isBreakTap=*/true);
}
```

### 3.2 `onTouchHoldTick` @ `0x1404146D0` — the held path (per frame)

```c
void onTouchHoldTick(TouchInputState *state)              // "OnTouchHold"
{
    /* state[0xDC] / state[0xDD] drive two drag helpers (sub_140412D80) */
    byte_140B51D68 = 0;                                   // the "in-reach" latch, see 3.4
    if (!state->holdActive) { state->holdStartTick = 0; return; }
    if (state->holdStartTick == 0) state->holdStartTick /* +0xD8 */ = getTick();
    if (!getLocalPlayer(gs)) { state->holdActive = 0; return; }
    if (getTick() - state->holdStartTick >= 0x2AF8 /* 11 s */) { state->holdActive = 0; state->holdStartTick = 0; return; }
    screenToWorld(cam, state->screenPos, &worldPos);
    HandleTouch(state, state->screenPos.x, &worldPos, /*isBreakTap=*/false);
}
```

Confirmed by the event registration in `sub_140412EC0` (`OnTouchStart` → `onTouchInput`,
`OnTouchEnd`/hold → `onTouchHoldTick`), the `LevelTouchComponent` ctor
`sub_140411AD0` (state +0xB8 `lastTileIndex = -1`, +0xC8 `holdActive = 0`,
+0xD8 hold start, +0xE0/+0xE4 throttle stamps) and `vtable` `0x14094A708`.

### 3.3 `HandleTouch` @ `0x140411CF0` — the gates

Entry: `(TouchInputState *state, float screenX, vec2f *worldPos, bool isBreakTap)`.
`tile = getTileAtPosition(world, worldPos)`; `item = itemsBegin + gs->heldItemId`.

| Gate | Behaviour |
|---|---|
| dying / frozen | `avatar[0x138] != 0` or `flags(0x188) & 0x800` → abort ("Can't, you are frozen!") |
| work stations | item types 37 / 64 / 129 accepted only on GOLDEN_TICKET_BOOTH / DISPLAY_BLOCK / DNA_EXTRACTOR / GIANT_POT_O_GOLD / STUFF_4_TOYS_BOX / FOOD_GRINDER |
| **per-tile de-dup** | `if (item_type != 0 && state->lastTileIndex == tile->index) return;` then `lastTileIndex = tile->index`. **The Fist's `item_type` is 0 (`ItemInfoType.FIST`) — it is the only item that may re-trigger the same tile.** Each new press resets the guard to `-1`. |
| reach (special items) | the **mod item's** `flags2` bit 20/21/22 selects a radius (70.4 / 166.4 / 102.4 px; `dword_14094A800/808/804`); `distance(playerCentre, worldPos) > radius` → abort. Gated on the held item being the dead `null_item9638` (`0x25A6`), so it does not fire in the shipped build — `PlayerController` only models the 150 px path. |
| reach (normal) | the tile is collected from the collision rect expanded by `(levelReach + 2) * 32` (`sub_1403F24C0`; `sub_1403F2760` for item 18) via `WorldView__collectGridTilesInRect`. In-rect + `distance <= 150.0` (`0x1408EE898`) sets `byte_140B51D68 = 1` and **returns** (the per-tick auto-punch in 4.2 handles the actual repeat). Outside the rect the full path below runs and may send immediately. |
| `isBreakTap` | press: full action (plant validation → "Can't plant a tree in the air!" feedback, door handling, `HandleTileActionResult`, placement preparation, item-type rate gates). Hold: skips the placement preparation (`0x14041254E`, `0x1404128A8`) — **holding never places**. |
| empty-tile guard | item_type 0 + empty tile + slot5 != 3716 → send only when `findAvatarAtPosition(worldPos)` finds an avatar (the click is on the player) |
| hand item | `gs->heldItemId` (+0x248). If 0: `isTileBreakable(tile)` → **WRENCH (32)**, else `inventoryHasItem(18)` → **FIST (18)** |
| pet interaction | `NetAvatar::isPetTileInteractionPending` aborts the edit while a pet axis is armed |

### 3.4 The action result vs the request

* **Fist**: `HandleTileActionResult` @ `0x140500220` is the local result (it gates on
  `checkIfAbleToPunch` for fuel-pack items) — it sets the anim fields, ORs
  `POWER_UP_PUNCH_START` and `PUNCH|TILE_CHANGE` (`0xA00`) into `avatar+0x134`, stamps
  `bounceTileX/Y` (+0xD0/+0xD4) and plays the punch effect; **it does not send**.
  `NetAvatar::punchTile` @ `0x1404FFC20` is the pure sender: same bounce stamp, ORs
  `TILE_CHANGE|POWER_UP_PUNCH_END` (`0x800800`), then
  `sendTileChangeRequest(gs, tile, 0x12 /* FIST */, 0, 0.0)`.
* **Placement**: `NetAvatar::beginPlaceTile` @ `0x140501DB0` ORs
  `PLACE|TILE_CHANGE` (`0xC00`) and prepares the local preview (pending tile + item id
  in `bounceTileX/Y` and `+0x17C`); it does **not** send — `HandleTouch`'s tail calls
  `sendTileChangeRequest(gs, tile, itemId, 0, 0.0)` for the send. A **seed plant is the
  same request** as a block placement: the `hasExtraFloat`/`float_var` variant is dead
  in the shipped build (`getProtocolVersion() >= 999999` kill switch at `0x1404075D8`),
  so the wire packet carries only the item id (the seed's odd id), the tile and the
  position stamp. Seeds differ only in the client-side validation (`isItemSeed` +
  `IsTileBelowPlantable`, "Can't plant a tree in the air!") and in the splice case (a
  seed on an existing seed tile / `BUNNY_EGG`); the splice is marked by the *server*
  broadcast's `jump_count == 1` -> `WILL_SPAWN_SEEDS_TOO`. See `docs/02_packet`
  ("tile harvest / plant") for the harvest (tractor) and plant (chicken plow) flows
  ported in `PlayerController._walk_item_mods`.
* **Wrench (type 1)** ends in the "can't place" branch for breakable tiles.

So the chained STATE frame's flag word matches the action: `PUNCH|TILE_CHANGE` for a
punch, `PLACE|TILE_CHANGE` for a placement (both include `0x800`, the `sendTankState`
poll reset).

### 3.5 The punch repeat

Both paths repeat through the **punch animation** `avatar+0x1A4 == 18`:

* hold ticks: `if (item_type == 0 && avatar[0x1A4] == 18) { HandleTileActionResult(tile); return; }`
  (`0x1404121BE`); when the animation is not running the hold tick takes the long path
  and sends;
* per-tick auto-punch: `NetAvatar::updateTileInteraction` @ `0x1404FFCA0` (4.2) sends only
  when `0x1A4 != 18`.

The sent cadence is therefore one punch per animation; the measured mode (5/s) is
consistent with a ~200 ms swing. The exact animation duration lives in the animation
data and is **not yet extracted** — `PlayerController` models it with
`PUNCH_REPEAT_MS = 200.0`.

---

## 4. Secondary entry points

### 4.1 `NetAvatar::punchTile` @ `0x1404FFC20`

Pure punch sender, see 3.4. Its only caller is `sub_1401407F0` (particle effect + punch).

### 4.2 `NetAvatar::updateTileInteraction` @ `0x1404FFCA0` — per-tick

Called from `NetControllerLocal::Update`. Requires a Fist in the inventory; handles the
door branch (`GetDamageTileType`); when the punch animation is running
(`avatar+0x1A4 == 18`) it refreshes `HandleTileActionResult` only; otherwise it scans the
row at the avatar's position in the facing direction (0..96 px, 32 px steps) and, for the
first non-empty tile, calls `HandleTileActionResult` + `sendTileChangeRequest(... 18)`.
This is the client's auto-punch (walking into a block).

### 4.3 `NetAvatar::tryPlaceSeedOrFertilizer` @ `0x140506910` — per-tick, from `tickAux`

11 KB function with 3 send sites (0x140506B16 seed planting, 0x140506F89 fist request,
0x1405070DF selected-item request). Most branches are pet/seed-label/work-station
specific; the seed path checks `IsTileBelowPlantable`. The walk-over item mods live
here: **Tree Harvesting** shoes (898/1830/1966/9650/10504) send the FIST request for a
planted seed tile (0x140506F89) and **Chicken Plow / Doom Plow** (5022/5212) send the
selected seed's placement request while walking (0x140506B16, plus the splice re-request
for an already-planted tile). The state gate shared with `HandleTouch` and
`updateTileInteraction` is `canAvatarInteract` (renamed from `isGoblin` — it is not a
goblin test; only its fallback branch reads the Present Goblin Disguise item 4260).
Full packet/field breakdown: `docs/02_packet` ("tile harvest / plant"); port:
`PlayerController._walk_item_mods`.

### 4.4 `handlePveNpcProjectileHit` @ `0x14054ADF0` — dead code

Entire body gated behind `getProtocolVersion() >= 999999`.

---

## 5. Cadence (measured, `~/.gtools/logs`, read-only)

`20261002_141139_app.log`, client → server:

- **161,598** client `TILE_CHANGE_REQUEST`
- **42,176** server → client `TILE_CHANGE_REQUEST` (broadcast confirmations, ~26 % of the client's volume)

### Requests per second — a hard ceiling at 10

| req/s | seconds |
|---|---|
| 4 | 1,893 |
| **5** | **28,815** |
| 6 | 664 |
| 7 | 151 |
| 8 | 139 |
| 9 | 227 |
| **10** | **94** |

Across **32,432** active seconds the count **never exceeded 10**.

### The gates (found in code)

* **Punch animation** (`avatar+0x1A4 == 18`): one Fist punch per swing — the dominant
  5/s rate.
* **Per-tile de-dup** (`state+0xB8`): a placeable item cannot re-trigger the same tile
  from hold ticks; only a fresh press resets the guard.
* **Touch-state throttles** (badly named in earlier passes — they take the
  `TouchInputState *`, not an item id; renamed in the IDB):
  * `TouchInputState_throttle80ms` (was `GetTileChangeTypeFromItem`) @ `0x140411C40` =
    **80 ms** gate, stamp at `state+0xE0` (12.5/s ceiling);
  * `TouchInputState_throttle333ms` (was `GetTileChangeFlagsFromItem`) @ `0x140411C80` =
    **333 ms** gate, stamp at `state+0xE4`;
  they run only in the tap branch for the special item types in the `0x2000100100` /
   107 / 129 sets (work stations and friends), not for the Fist or normal blocks.
* The 11 s `onTouchHoldTick` timeout stops long holds (4.3 GB: `0x2AF8`).

The earlier "100 ms floor not yet located" open item is therefore resolved: there is no
global 100 ms sender gate; the measured distribution is the sum of the gates above.

---

## 6. Relationship to STATE

Measured over the same session, client → server:

| | active seconds |
|---|---|
| seconds containing `STATE` | 33,014 |
| seconds containing `TILE_CHANGE_REQUEST` | 32,432 |
| seconds containing **both** | **32,348** |

**32,348 / 32,432 = 99.75 %** of seconds with a tile edit also contain a `STATE` packet.

The two packets are **independent emitters that share the tick grid**:
`STATE` is a ~5 Hz heartbeat (`sendTankState` gate, seen in
`docs/netavatar-physics.md` §7.1), `TILE_CHANGE_REQUEST` is event-driven. The genuine
coupling is the **event mask**: the action paths OR `TILE_CHANGE` (and
`PUNCH`/`PLACE`/`POWER_UP_*`) into `avatar+0x134`; `sendTankState` zeroes its poll timer
when bit `0x800` is set, so the frame carrying the action bits leaves on the next tick —
the "chained STATE".

---

## 7. Open items

1. The exact punch-animation duration (id 18) — the model uses 200 ms from the measured
   5/s mode. The animation table was not located.
2. The two `TouchInputState` drag modes (`+0xDC`, `+0xDD` → `sub_140412D80`,
   `AppContext+0x27C * 0.05f` scaling) are not classified.
3. `sub_1403F5AA0` (`var_AF`, item types in `0x10C40000` + type 112) is not classified —
   it decides the breakable-vs-plant branch for "plant in the air" items.
4. `isTileBreakable` reads `word[item+0x72] & 2` (the item record's flags2 high bytes);
   the exact flag name is not mapped to `ItemInfoFlag2`.
5. Item `9638` (`0x25A6`) is a null item used by the legacy "long hand" reach branch
   (3.3) — the mod item that carries the flags2 reach bits is not identified.
6. The wrench (`item_type == 1`) edit path (`HandleTileActionResult` / door branches)
   is only partially classified.

---

## 8. IDB changes applied so far

- `NetAvatar` struct, `TouchInputState`, `SignState` declared and verified.
- Renamed the two misnamed touch throttles (`GetTileChangeTypeFromItem` /
  `GetTileChangeFlagsFromItem` → `TouchInputState_throttle80ms` / `_throttle333ms`) with
  block comments.
- Renamed: `NetAvatar::punchTile`, `NetAvatar::updateTileInteraction`,
  `NetAvatar::tryPlaceSeedOrFertilizer`, `NetAvatar::beginPlaceTile`,
  `NetAvatar::isPetTileInteractionPending`, `HandleTileActionResult`, `findAvatarAtPosition`,
  `onTouchInput`, `onTouchHoldTick`, `checkIfAbleToPunch`,
  `handlePunchDisplayEffectAndSfx`, `handlePveNpcProjectileHit`.
- Signatures applied so parameters propagate as `GameState *` / `Tile *` / `NetAvatar *` /
  `TouchInputState *` instead of `__int64`.
- Block comments at `0x140407570`, `0x1404FFC20`, `0x1404FFCA0`, `0x140411CF0`,
  `0x140414020`, `0x1404146D0`, `0x140513780`, `0x140411CC0`, `0x14054ADF0`.

Tooling notes: `list_funcs` filters under the `filter` key; `rename` on data needs
`{addr, old, new}`; `declare_type` splits input on commas, so each declaration must be its
own array element with comma-free comments. IDA inserts alignment padding for odd-offset
members (`__int16` at `0x1B1`, `__int64` at `0x1B4`) — use `char`/`char[N]` there to keep
offsets true. `read_struct` takes `{struct: "Name"}`, not a bare string.
