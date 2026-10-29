# TILE_CHANGE_REQUEST — send path, cadence, and coupling to STATE

Target: **Growtopia** client (protocol 226, `game_version 5.58`), PE x64, image base `0x140000000`.
All addresses are IDA virtual addresses in `Growtopia.exe.i64`. Every claim is annotated in the
IDA database at the cited address, or quoted from the read-only logs in `~/.gtools/logs`.

Status: phase `t1-sender` complete, cadence measured, STATE coupling resolved. Flow tracing
continues (input gating, hand-slot selection, packet send mechanics).

---

## 1. Executive summary

| Question | Answer |
|---|---|
| Cadence | **Event-driven, but gated onto the same ~200 ms grid as `STATE`.** Dominant rate **5/s**; hard ceiling **10/s**. No second ever exceeded 10 across 32,432 active seconds. |
| Flow | `HandleTouch` (`0x140411CF0`) → gates → `sendTileChangeRequest` (`0x140407570`) → `SendPacketRaw(4, …, 56, 0, …)`. Four other entry points exist. |
| STATE coupling | **Independent emitters on a shared tick.** `STATE` is a ~5 Hz heartbeat present in 33,014 of the session's active seconds; **99.7 %** of seconds containing a `TILE_CHANGE_REQUEST` also contain a `STATE` packet. `STATE` does **not** wait for tile edits — it is simply always running. |

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
    pkt.value     = itemId;                      // +0x14   item placed; 0 = break
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

**Packet**: 56 bytes, ENet **channel 4**, reliable.

**The `999999` sentinel.** `getProtocolVersion()` is ~226 in practice, so `999999` is a
never-yet-enabled feature flag. With `hasExtraFloat` set, `999999`-style protocols are required
or the send is aborted. The same gate guards the only caller that uses that branch
(`sendSignDurationRequest`, §4.4), so that path is dead code in the shipped client.

**Position stamp.** `vector_x`/`vector_y` carry the player's own position at the moment of the
edit — *"I was standing here when I changed that tile"*. This is the server's reach validation
input. Log confirmation, `20261002_141139_app.log`:

```
from client (TANK_PACKET) TankPacket(type=TILE_CHANGE_REQUEST, value=340,
    vector_x=422.0, vector_y=738.0, int_x=11, int_y=21)
from client (TANK_PACKET) TankPacket(type=TILE_CHANGE_REQUEST, flags=<TankFlags.FACING_LEFT: 16>,
    value=340, vector_x=422.0, vector_y=738.0, int_x=12, int_y=21)
from client (TANK_PACKET) TankPacket(type=TILE_CHANGE_REQUEST, value=340,
    vector_x=422.0, vector_y=738.0, int_x=13, int_y=21)
```

`vector_x=422.0, vector_y=738.0` is byte-identical across all three while `int_x` steps
11 → 12 → 13. The player is stationary, sweeping a line of tiles. `flags=FACING_LEFT` matches
`TANKFLAG_FACING_LEFT` set from `player->isFacingLeft`.

### Callers (7 sites, 5 distinct entry points)

| Caller | Address | Trigger |
|---|---|---|
| `HandleTouch` | `0x140411CF0` | **player tap** — the main front end |
| `NetAvatar::placeSign` | `0x1404FFC20` | `itemId = 0x12` (18) = SIGN |
| `NetAvatar::updateTileInteraction` | `0x1404FFCA0` | **per-tick**, from `NetControllerLocal::Update` |
| `sub_140506910` | `0x140506910` | 3 sites |
| `sendSignDurationRequest` | `0x14054ADF0` | protocol ≥ 999999 only — dead |

---

## 3. Flow — pointer tap to packet

`HandleTouch` @ `0x140411CF0` (4182 bytes, 711 lines)

```
void __fastcall HandleTouch(TouchInputState *state /*rcx -> r14*/,
                            float screenX /*xmm0*/,
                            vec2f *worldPos /*rdx*/,
                            bool isBreakTap /*r8b*/)
```

### 3.1 Early rejects

| Check | Meaning |
|---|---|
| `!getLocalPlayer(gs)` | no local avatar |
| `getLocalPlayer(gs) + 11444 > -1` | mounted / in a vehicle |
| `GameLogicComponent::DialogIsOpened()` | UI modal |
| `sub_1404FB580(localPlayer, 1) + 8 == 4260` | blocked costume |
| `state->rejectD4` (`0xD4`) | latched reject |
| `!isGoblin(localPlayer + 856)` | **this path is goblin-gated** |
| `localPlayer[0x138] != 0` or `flags(0x188) & 0x800` | frozen → shows `"`!(Can't, you are frozen!)`"` |

### 3.2 Item and target selection

```c
itemId = GameState->gap224[36];                                  // held hand item
item   = &getItemManager()->itemsBegin->itemId + 808 * itemId;   // 808-byte stride
tile   = getTileAtPosition(sub_1403F27B0(gameState), worldPos);
```

Item types **37 / 64 / 129** are the goblin work stations and are accepted only on these
foreground tiles: `GOLDEN_TICKET_BOOTH`, `DISPLAY_BLOCK`, `DNA_EXTRACTOR`,
`GIANT_POT_O_GOLD`, `STUFF_4_TOYS_BOX`, `FOOD_GRINDER` (the last also when
`tile item_type == 98`).

`state->lastTileIndex` (`0xB8`) caches the last targeted tile — **a repeat tap on the same
tile index aborts**, which is a de-duplication guard rather than a timing guard.

### 3.3 Pre-send gates

```c
// hand slots
slot5 = sub_1405445F0(&inventory.items, 5);
slot6 = sub_1405445F0(&inventory.items, 6);
v121 = (slot5 == 3716 || slot5 == 6086) && slot6 != 3714 && itemId == 18;
v122 = (slot5 == 1748 || slot5 == 3274) && !isFuelPackLike(slot6) && itemId == 18;
if (v121 || v122 || !v80) goto ABORT;

// weapon-ish bit test
v123 = state.dword[1];
if ((v123 <= 0x25 && bittest64(0x2000100100, v123)) || v123 == 107 || v123 == 129)
    state->flagC8 = 0;

// empty tile guard
if (!tile->bg_id && !tile->fg_id && slot5 != 3716) {
    if (NetAvatar::isPetTileInteractionPending(localPlayer)) goto ABORT;
    sub_1403FE9D0(gameState);
}

// must be standing here
if (!findAvatarAtPosition(getAllPlayer(), worldPos)) goto ABORT;

sendTileChangeRequest(sdk::GetGameState(), tile, itemId, 0, 0.0);
```

Failure feedback plays **`audio/cant_place_tile.wav`** through the AudioManager vtable.

### 3.4 Reach check — it is containment, not distance

`findAvatarAtPosition` @ `0x140513780`

```c
NetAvatar *findAvatarAtPosition(NetAvatar *players /*rcx*/, vec2f *pos /*rdx*/)
{
    // walks the player map (tree root at players+0x18)
    // skips avatars with byte[76] set
    // returns the first avatar whose collision rect CONTAINS pos, else NULL
}
```

There is **no distance/reach test** anywhere on this path — the tap point must fall literally
inside an avatar's collision rect. Tile size is **32 px**
(`NetAvatar::clampToWorldBounds`, `0x1404FF550`: `width*32.0`, `height*32.0`).

### 3.5 Pet interaction gate

`NetAvatar::isPetTileInteractionPending` @ `0x140411CC0`

```c
return (this[11504] - this[11516]*0.5) != 0.0f;
```

`11504`/`11516` are the `half` and `base` of a pet axis triplet in the second triplet block
(`11488..11580`). Non-zero means the pet owns a pending tile interaction and the edit is refused.

---

## 4. Secondary entry points

### 4.1 `NetAvatar::placeSign` @ `0x1404FFC20`

```c
this[0xD0] = tile->tileX;  this[0xD4] = tile->tileY;  this[0x17C] = 0;
if (!this[0x120]) this[0x134] |= 0x800800;
sendTileChangeRequest(GetGameState(), tile, 0x12 /* 18 = SIGN */, 0, 0.0);
```
Then `sub_14050B830(this)`.

### 4.2 `NetAvatar::updateTileInteraction` @ `0x1404FFCA0` — **per-tick**

Called from `NetControllerLocal::Update` (`0x140511A50`) when the pet axis settles.
**This is the one caller on the same per-tick path that emits `STATE`.**

```c
if (isGoblin(localPlayer + 856) || petAxis(localPlayer + 11520) != 0) {
    if (this[0x138] == 0 && (this[0x188] & 0x800) == 0) {
        tile = getTileAtPlayerPosition(this);
        if (isTileDoorTile(tile) && item_type(tile->fg_id) != 43)
            sub_140504B00(this, tile, 0);                       // door handling
        if (inventoryHasItem(&gs->inventory.items, 18 /* SIGN */) &&
            localPlayer[0x1A4] == 18)
            sub_140500220(localPlayer, tile);                  // sign placement
        if ((this[0x18A] & 1) == 0 && this[0x2D0] == 5480 && this[0x2CC] != 4288) { ... }
    }
}
```

### 4.3 `sub_140506910` @ `0x140506910` (11,291 bytes) — 3 call sites

Largest caller of the sender. Not yet classified.

### 4.4 `sendSignDurationRequest` @ `0x14054ADF0` — dead code

Entire body gated behind `getProtocolVersion() >= 999999`. When enabled it either writes
`0.5f / 1.5f / 1.5f / 1.5f` into the avatar at `+0x20C+44..+56`, or calls
`sendTileChangeRequest(gs, tile, 0x12, 1, sign->duration)` — the only caller exercising the
sender's extra-float branch, which is itself killed by the same check.

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

Across **32,432** active seconds the count **never exceeded 10**. The mode is 5/s.

**Conclusion: a 100 ms floor (max 10 Hz) with the dominant rate landing on 5/s (200 ms) —
the same period as the `STATE` heartbeat.** The tap handler is gated onto the shared tick
rather than sending immediately per input event.

---

## 6. Relationship to STATE

Measured over the same session, client → server:

| | active seconds |
|---|---|
| seconds containing `STATE` | 33,014 |
| seconds containing `TILE_CHANGE_REQUEST` | 32,432 |
| seconds containing **both** | **32,348** |

**32,348 / 32,432 = 99.75 %** of seconds with a tile edit also contain a `STATE` packet.

`STATE` per-second distribution peaks at the same place:

| req/s | seconds (STATE) |
|---|---|
| **5** | **22,437** |
| 6 | 2,089 |
| 7 | 1,755 |
| 8 | 2,098 |
| 9 | 1,853 |
| 10 | 1,007 |
| 11 | 8 |

### Interpretation

The two packets are **independent emitters that share a 200 ms tick grid**:

- `STATE` is a **heartbeat** — it runs at ~5 Hz whether or not anything happens, which is why
  it appears in essentially every active second. It goes up to 11/s, i.e. it is *not* capped
  at the same 10/s ceiling.
- `TILE_CHANGE_REQUEST` is **event-driven** — driven by taps — but clamped to the same grid,
  hence the 5/s mode and the 10/s ceiling.
- Therefore the observation "a `TILE_CHANGE_REQUEST` usually comes with a `STATE` packet" is
  explained by **coincidence of a shared clock**, not by one packet triggering the other.
  No causal dependency has been found in code.

The one genuine code-level coupling is the **position stamp**: the tile packet embeds
`vector_x`/`vector_y`, so the server can check the edit against the position the client
asserted in its heartbeat.

---

## 7. Open items

1. `sub_140506910` (`0x140506910`, 3 call sites) is unclassified — the largest caller.
2. The exact source of the 100 ms floor / 200 ms grid is not yet located in code. Expected
   near `HandleTouch` or a shared tick dispatcher; note `NetAvatar::CanMessageT4`
   (`0x1404F7330`) implements a *different* limiter (15,000 ticks) for anti-cheat reports only.
3. `sub_140554FD0`, `sub_140411C40`, `sub_140411C80`, `sub_1403FE9D0`, `sub_140501DB0`,
   `sub_1405445F0` (inventory slots 5/6) are still unnamed.
4. Hand-slot → item-id mapping for `gap224[36]` not yet traced to the inventory.
5. Place vs break vs plant discrimination is partially mapped (`isBreakTap`, item types
   37/64/129, `itemId == 18`) but the full decision tree is not yet written out.

---

## 8. IDB changes applied so far

- `NetAvatar` struct, `TouchInputState`, `SignState` declared and verified.
- Renamed: `NetAvatar::placeSign`, `NetAvatar::updateTileInteraction`,
  `NetAvatar::isPetTileInteractionPending`, `findAvatarAtPosition`,
  `sendSignDurationRequest`.
- Signatures applied so parameters propagate as `GameState *` / `Tile *` / `NetAvatar *` /
  `SignState *` / `TouchInputState *` instead of `__int64`.
- 5 block comments at `0x140407570`, `0x1404FFC20`, `0x1404FFCA0`, `0x140411CF0`,
  `0x140513780`, `0x140411CC0`, `0x14054ADF0`.

Tooling notes: `list_funcs` filters under the `filter` key; `rename` on data needs
`{addr, old, new}`; `declare_type` splits input on commas, so each declaration must be its own
array element with comma-free comments. IDA inserts alignment padding for odd-offset members
(`__int16` at `0x1B1`, `__int64` at `0x1B4`) — use `char`/`char[N]` there to keep offsets true.

