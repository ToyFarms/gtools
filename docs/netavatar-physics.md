# NetAvatar physics — reverse-engineering map

Target: **Growtopia** client (protocol 226, `game_version 5.58`), PE x64, image base `0x140000000`.
All addresses are IDA virtual addresses in `Growtopia.exe.i64`.

Every claim below is annotated in the IDA database at the cited address.

---

## 1. Executive summary

The local physics step is **not** in the network handler. It lives in a separate
per-tick controller, `NetControllerLocal::Update`:

```
NetControllerLocal::Update          @ 0x140511A50   <- per-tick entry (virtual)
  |- reads input axes, maps to a signed magnitude
  |- NetAvatar::integrateVerticalAxis @ 0x140510580 <- integration
  |- NetAvatar::validatePhysics       @ 0x1405051E0 <- anti-cheat + bounce resolution
  \- position/velocity drift check -> sendAppIntegrityFail(.., 0x0C, 0)
```

The `TANK_STATE` (`TankPacket.type == STATE`) path is a **separate, lower-rate state
snapshot** that *snaps* rather than interpolates:

```
ProcessTankUpdatePacket            @ 0x140405470
  case STATE: (*(avatar->vtable + 0x28))(avatar, pkt)
    -> NetAvatar::onTankStatePacket      @ 0x1404FFA40
       -> NetAvatar::applyTankStatePacket @ 0x1404F58C0   (snapshot only)
    -> NetAvatar::applyTankStateAndEvents @ 0x14050C560   (position snap + events)
```

---

## 2. Class map

| Symbol | Address | Notes |
|---|---|---|
| `NetAvatar::vftable` | `0x14095B8B8` | 12 slots; RTTI COL `0x14095B8B0` = `??_R4NetAvatar@@6B@` |
| `NetControllerLocal::vftable` | `0x14095C5A0` | RTTI COL `0x140A069B8` -> TypeDescriptor `0x140B42AC8` = `.?AVNetControllerLocal@@` |
| `NetAvatar::NetAvatar_ctor` | `0x1404F65E0` | sets `*this = &NetAvatar::vftable`; reveals full layout |
| `NetControllerLocal::Update` | `0x140511A50` | **the per-tick physics step** |
| `NetAvatar::integrateVerticalAxis` | `0x140510580` | axis integration + tile/item modifiers |
| `NetAvatar::validatePhysics` | `0x1405051E0` | invariants, water, **bounce**, idle damping |
| `NetAvatar::tickAux` | `0x140503160` | per-tick avatar update; calls `sendTankState` every tick |
| `sendTankState` | `0x1404F5E30` | **the client's send gate**: 200 ms poll + changed-packet check (§7.1) |
| `NetAvatar::fillTankStatePacket` | `0x1404FBEB0` | builds the STATE frame; floors positions to whole pixels first |

`NetControllerLocal` layout: `vtable` at `+0x00`, **`NetAvatar *avatar` at `+0x08`**,
input latch/tick fields at `+0x10..+0x28`.

---

## 3. The axis-triplet storage scheme (verified in the constructor)

Every movement quantity is stored as a 16-byte triplet:

| Offset in group | Field | Value |
|---|---|---|
| `+0x00` | `half`  | `base*0.5 + C` |
| `+0x04` | `flags` | int |
| `+0x08` | `value` | `base + C` |
| `+0x0C` | `base`  | `randFloat(3.0, 29384.0)` |

The real constant `C` is **never stored**. Code recovers it as:

```c
effective = half - base * 0.5;      // == C
```

`base` is randomized per avatar, so the constant is camouflaged. `validatePhysics`
additionally enforces the complementary identity with tolerance `0.2`:

```c
fabs(value - ((half - base*0.5) + base)) > 0.2f   -> sendAppIntegrityFail
```

### Movement fields found in `NetAvatar::NetAvatar_ctor` (`0x1404F65E0`)

| Group offset | `C` | Interpretation |
|---|---|---|
| `+0x080` (128) | `0.0` | unused / cap |
| `+0x0E4` (228) | `0.0` | **horizontal velocity** — `pos_x += value*dt` in `tickAux`; `validatePhysics` integrates the input magnitude into it and caps it at `±gravity` (250) |
| `+0x0F4` (244) | `0.0` | **vertical velocity** — `pos_y += value*dt` in `tickAux`; integrated by `integrateVerticalAxis` |
| `+0x1C4` (452) | `1000.0` | vertical acceleration (gravity) |
| `+0x1D4` (468) | `1200.0` | horizontal move acceleration (input magnitude) |
| `+0x1E4` (484) | `250.0` | **gravity / max horizontal speed** — used as the horizontal velocity cap in `validatePhysics` |
| `+0x1F4` (500) | `125.0` | **velocityInWater / horizontal cap** — a plain float, not a triplet; `validatePhysics` uses it when `avatar[0x1A1]` is set |
| `+0x1FC` (508) | `0.0` | jump / punch strength triplet (initial C=0; `OnPunched` can set 400; not the local jump launch) |

A second block of six full triplets lives at `+0x2CE0..+0x2D3F`; the ctor writes
qwords at `+0x2CC0` and `+0x2CD0` immediately before it.

`+0x270` and `+0x274` are initialised to `1.0f`.

> The IDB type is **`NetAvatar`** (25,224 bytes, 131 members). The physics
> allocation is **`0x2DB8` = 11,704 bytes** (confirmed by `operator new(0x2DB8)`
> at `0x140402019`). `NetAvatarX` no longer exists in the current IDB; the
> physics fields below are the `NetAvatar` fields at these offsets. See §8 and
> §9.

---

## 4. Constants — obfuscation scheme

All tunable constants are stored as a pair of globals and evaluated as `X - Y*0.5`:

```c
// sub_140019FB0 and 21 siblings, 0x78 bytes each
if (!byte_140B52C04) { byte_140B52C04 = 1; srand(GetTickCount()); }
dword_140B52C7C = 0;
dword_140B52C84 = randFloat(3.0, 29384.0);              // Y  (randomiser)
*(float*)&dword_140B52C80 = Y + 400.0;                  // full
*(float*)&dword_140B52C78 = Y*0.5 + 400.0;              // X
// use site:  X - Y*0.5  ==  400.0
```

Layout invariant: **`X = Y - 0xC`**. Static reads show `0xFFFFFFFF` because the
pairs are seeded at runtime — read the `initObfConst_*` helpers, not the data.

### Decoded constant table

| X (the value slot) | Value | Symbol | Role |
|---|---|---|---|
| `0x140B52C28` | `1.0` | `kConst_1p0_C28` | — |
| `0x140B52C78` | `400.0` | `kVertAxisMaxSpeed_400p0` | axis speed clamp |
| `0x140B52C88` | `5000.0` | `kConst_5000p0_C88` | airborne accel bonus |
| `0x140B52C98` | `1000.0` | `kBounceCrossZero_1000p0` | bounce clamp when crossing zero |
| `0x140B52CA8` | `100.0` | `kBounceClamp_100p0` | bounce clamp, same sign |
| `0x140B52CB8` | `48.0` | `kConst_48p0_CB8` | — |
| `0x140B52CC8` | `1200.0` | `kNoInputDamping_1200p0` | idle friction coefficient |
| `0x140B52CE8` | `0.15` | `kConst_0p15_CE8` | validator scale |
| `0x140B52CF8` | `300.0` | `kConst_300p0_CF8` | — |
| `0x140B52D08` | `800.0` | `kConst_800p0_D08` | — |
| `0x140B52D18` | `800.0` | `kConst_800p0_D18` | — |
| `0x140B52D28` | `500.0` | `kConst_500p0_D28` | — |
| `0x140B52D38` | `400.0` | `kJumpStrengthOffset_400p0` | jump strength offset |
| `0x140B52D48` | `0.3` | `kBootSpeedMul_0p3` | boot & slipper speed multiplier |
| `0x140B52D58` | `0.3` | `kSlideFriction_0p3` | water / flag-pole vertical damping (not the floor slide; that uses `0.15`) |
| `0x140B52D68` | `0.75` | `kConst_0p75_D68` | antigravity multiplier |
| `0x140B52D78` | `1000.0` | `kFixedStepDivisor_1000p0` | timestep divisor |
| `0x140B52D88` | `330.0` | `kConst_330p0_D88` | gravity while frozen (`flags & 1`) |
| `0x140B52D98` | `3000.0` | `kConst_3000p0_D98` | — |
| `0x140B52DA8` | `0.2` | `kConst_0p2_DA8` | — |
| `0x140B52DB8` | `15000.0` | `kConst_15000p0_DB8` | anti-cheat report cooldown |

> **Correction.** An earlier pass of this document mislabelled eight of these: the
> names were placed on the `full` slot (`X + 8`) instead of `X`. The X addresses
> above were re-derived empirically from each `initObfConst_*` helper and then
> machine-checked — every `kObfRand_*` at `B` has a matching X at `B - 0xC` whose
> name carries the same value. Verification now reports **21/21 consistent, 0
> mismatches**. `kBounceClamp_100p0` in particular is `0x140B52CA8`, not `CB0`.

Plus two plain (non-obfuscated) read-only floats:

| Symbol | Address | Value |
|---|---|---|
| `kHalfMultiplier_0p5` | `0x1408B8FEC` | `0.5` |
| `kMinGravity_0p01` | `0x1408EE7A4` | `0.01` |

`validateObfuscatedConstantPool` (`0x1400F5600`) sums 13 of these and compares the
total against `*(float *)(this + 3612)`; mismatch `> 0.1` tears down the context.

---

## 5. Order of operations in the physics step

### 5.1 `NetControllerLocal::Update` — `0x140511A50`

1. Read input axes (`v33` = left, `v34` = right) via `sub_140036050`.
2. Map input to a signed magnitude using the **horizontal move speed** axis:
   ```c
   m = avatar[0x1D4] - avatar[0x1E0]*0.5;      // == 1200.0
   if (avatar[0x18C] & 0x800) m = -m;          // inverted
   avatar[0x61] = (avatar[0x18C] & 0x800) == 0;
   ```
3. If `avatar[0x138] != 1`:
   - `avatar[0x104] = 0`
   - `NetAvatar::integrateVerticalAxis(avatar)`
   - `NetAvatar::validatePhysics(avatar, m)`
   - position/velocity drift check -> `sendAppIntegrityFail(.., 0x0C, 0)`
4. Pet axis groups reset when their effective value becomes non-zero.
5. Stale-input watchdog: `(getTick() - avatar[0x14]) / 1000 <= 15`.

### 5.2 `NetAvatar::integrateVerticalAxis` — `0x140510580`

```c
cur    = avatar[0x0F4] - avatar[0x100]*0.5;    // C = 0.0
accel  = avatar[0x1C4] - avatar[0x1D0]*0.5;    // == 1000.0

// Grounded / frozen path (flag_DC, set by the tile-step query 0x140505CB0):
if (avatar[0xDC] != 0) {
    if (cur > 0.0) cur = 0.0;                  // kill downward motion
    if (accel > 0.0) { avatar[0x104] = 1; return; }   // no integration
}

maxSpd = kVertAxisMaxSpeed_400p0;              // 400.0
dt     = (float)(int)sub_140029810(app) / kFixedStepDivisor_1000p0;

// Jump cut / fast-fall: rising, latch released, and no character-mod override.
if (accel > 0.0 && cur < 0.0 && avatar[0x130] == 0 && avatar[0x1A9] == 0)
    accel += 5000.0;

accel *= <tile / item modifiers>;
cur   += dt * accel;

// Asymmetric clamp: the upward clamp is only applied while accelerating up.
if (cur >  maxSpd) cur =  maxSpd;
if (accel < 0.0 && cur < -maxSpd) cur = -maxSpd;

avatar[0x0F4] = cur;                           // new velocity
avatar[0x0FC] = cur + dt*0.5;                  // interpolated value
avatar[0x104] = 1;                             // axis active this tick
```

The clamp paths keep the same half-step convention: a clamped `+400` stores
`0x0F4 = 400 + 0.5*dt` and `0x0FC = 400 + dt` (the `-400` branch mirrors it).

`0x130` is set/cleared together with `0x105` by `NetAvatar::setJumpHeld`
(`0x14050C280`); the `+5000` branch therefore fires when the jump latch is
**released while the avatar is still rising** — this is the client-side jump
cut. It adds to the **acceleration** (`1000 + 5000 = 6000 px/s²`), not to the
velocity; there is no `-100 px/s` clamp in the client. `0x1A9` is bit 0 of
`NetAvatar::SetCharacterMods` (`0x14050B980`) and can disable the cut. The
`0x131` branch (boot/slipper variant) adds `0.85 * 5000` instead.

Modifiers on `accel`:

| Condition | Effect |
|---|---|
| standing on a boot/slipper item id (long list at `avatar+0x2D0..0x2D6`) | `*= kBootSpeedMul_0p3` (0.3) |
| `SLIPPERY_FLAG_POLE` foreground tile (a pole, not a floor) | vertical `cur` and `maxSpd` both `*= kSlideFriction_0p3`; calls `sub_140101810` |
| `avatar[0x1A1]` (in-water flag) set | same 0.3 scaling on the vertical `cur` and `maxSpd` |
| `HYPERTECH_ANTIGRAVITY_FIELD` tile or particle flag `0x40` | `accel *= kConst_0p75_D68 * 0.5` |
| particle type `7` | `accel *= kConst_0p75_D68` |
| `avatar[0x1B2]` (`434`) set | `accel *= 15.0` |
| `avatar[0x11480]` ramp active | damping `*= 0.5625` per tick |

Boot item ids checked: `1020, 7696, 10186, 11292, 7034, 9424, 7144, 10718, 1876,
3074, 5278, 1762, 4880, 4946, 6372, 1784, 8286, 5206, 9088, 5322, 5482, 6758,
8552, 9132, 10632, 10634, 11318, 10666, 10714, 10754`.

> The horizontal **floor slide** is a separate mechanic. It is driven by
> `avatar[0xDD]`, which `sub_140505CB0` sets from the tile below (see §6.4),
> and `validatePhysics` scales the horizontal acceleration by `0.15` — not the
> `0.3` vertical damping above. `SLIPPERY_FLAG_POLE` is a pole and must not be
> treated as a slippery floor.

---

## 6. Gravity, water, bounce, slide

All in `NetAvatar::validatePhysics` — `0x1405051E0`, except the bounce tiles
(§6.2), which are handled by the collision vfuncs.

### 6.1 Horizontal speed cap and water

`validatePhysics` (`0x1405051E0`) reads the effective `+0x1E4` (250) as the
**horizontal speed cap** for axis `+0x0E4`, not as vertical gravity. The
vertical axis `+0x0F4` is integrated separately in `integrateVerticalAxis`
(`0x140510580`) with the `+0x1C4` acceleration (1000 px/s²).

Horizontal cap overrides in `validatePhysics`:

| Condition | Result |
|---|---|
| `avatar[0x1A1]` (auto-detected in-water flag) set and `!(input_flags & 1)` | cap -> `velocityInWater` (`+0x1F4`) = **125.0** |
| `tile->flags & 0x800 && bg_id == BLANK` | cap `*= 0.5` |
| `flags & 1` (frozen) | cap -> `kConst_330p0_D88` = **330.0** |
| `avatar[0x0DE]` (`BYTE6`) path | cap `*= 0.60000002` |

Vertical water/pole branch in `integrateVerticalAxis`:

```c
if (avatar[0x1A1]) {                  // in-water flag
    accel   *= kSlideFriction_0p3;    // +0x1C4 * 0.3
    maxFall *= kSlideFriction_0p3;    // 400 * 0.3 = 120
}
else if (foreground == SLIPPERY_FLAG_POLE) {  // a pole, not a floor
    accel   *= kSlideFriction_0p3;
    maxFall *= kSlideFriction_0p3;
}
```

`avatar[0x1A0]` is the action-500005 water **input**; it is not the
auto-detected water flag. The in-water flag is `avatar[0x1A1]`, written by
`updateBlockStateFromPlayerInteraction` (`0x140509C20`) from tile flag bit 10
(`TileFlags.IS_WET`, `0x400`) at the player collision-rect center.

### 6.2 Bounce tiles

Bounce is **not** in `validatePhysics`. The collision dispatcher routes into
two NetAvatar vfuncs that inspect the tile's `*(u32*)(itemRecord + 4)`
(i.e. `ItemInfoType`) column:

| vfunc | Address | Resolves | Bounce branch |
|---|---|---|---|
| `vfunc_40` | `0x140501DF0` | horizontal collision (wall bump) | `item_type == 24` → radial launch |
| `vfunc_48` | `0x1405021D0` | landing / ceiling collision | `24`, `7`, `108`, steam launcher → launch |

Types in this build (verified against the shipped `items.dat`):

- **`ItemInfoType.BOUNCY` (24)** — collision-direction bouncers:
  Bouncy Turret, HyperTech Multi-Jet Energy Pulser, Lime/Orange/White Grape
  Jelly Block, Pinball Bumper.
- **`ItemInfoType.TRAMPOLINE` (7)** — upward-only trampolines:
  Baroque Fountain, Black/Blue/Green awnings, Bouncy Mushroom variants,
  the Jelly blocks except Lime/Orange/White Grape/Lemon, Ladybug/Pillow
  Trampolines, Diving Board, Fire Hydrant, Grow-Cola Block, Jack-in-the-Box,
  Pinball Sproinger, Punchy Fist, Sea Sponge, Shepard's Pie Block,
  Whoopie Pie Block, and others (41 items).
- **`ItemInfoType.TRAMPOLINE_MOMENTUM` (108)** — Lemon Jelly Block only.
- **Steam Launcher (item 3498)** — `TileFlags.IS_ON` (0x40) gate.

#### 6.2.1 BOUNCY (24) — radial launch

`NetAvatar::bounceRadiallyFromTileCenter` (`0x1404F71E0`, called from both
vfuncs):

```c
angle = atan2f(playerCenter.y - tileCenter.y,
               playerCenter.x - tileCenter.x);
this[0xEC] = this[0xE0]/*base*/ + cosf(angle) * 500.0f; // horizontal axis
this[0xF0] = this[0xE0] + sinf(angle) * 500.0f;         // half slot
this[0xFC] = ... + sinf(angle) * 500.0f;                // vertical axis
this[0x100] = ... + sinf(angle) * 500.0f;
this[0xDC] = 0;                                        // clear on-ground
```

The avatar launches at exactly **500 px/s** along the direction from the tile
center to the player's collision-rect center. `500.0` is exact: the handlers
pair `kConst − kObfRand*0.5` with the initializer that stores
`value*0.5 + rand` (NetAvatar_ctor `0x1404F66C0`), so the random always
cancels. In vfunc_48 the BOUNCY branch is checked **first**, before the
acceleration gate, and fires on both the horizontal and the vertical
collision direction.

#### 6.2.2 TRAMPOLINE (7) / TRAMPOLINE_MOMENTUM (108) / Steam Launcher

`vfunc_48` only runs the branch on a true landing, with all of:

1. **falling**: the vertical axis effective value `>= 0`;
2. **feet below the tile top**: `getPlayerCollisionRect` returns a rect
   `(left, top, right, bottom)` (the `vec4f` IDB field names are misleading)
   and the check is `tileTop >= playerBottom`;
3. **the vertical-acceleration axis enabled**: `[0x1C4] − 0.5*[0x1D0] > 0`
   (the `+0x1C4` triplet, C=1000; collapse to 0 under antigravity). BOUNCY
   does not require this gate.

Then (vfunc_48, raw asm):

```c
// item_type == TRAMPOLINE (7) or the steam launcher id 3498 (IS_ON only)
launch = -800.0f;
// item_type == TRAMPOLINE_MOMENTUM (108):
launch = -800.0f * 1.5f * ((momentum /* avatar[0x1F8C] */ / 400.0f) ^ 2);
if (launch > -531.25f) launch = -531.25f;   // weak-bounce floor
if (this[0x130] /* jump latch */ && launch <= -10000.0f/*check*/)
    launch = -10000.0f;                     // held-jump cap
this[0xF4-triplet] = launch;               // vertical axis
this[0xDC] = 0;
```

Steam launcher additionally runs `clearTileFlag(IS_ON)` +
`sendTileActivateRequest` after the launch. The shared bookkeeping helper
`NetAvatar::onTileBounceHit` (`0x140502AB0`) stores the bounce tile in
`avatar+0xD0/0xD4`, ORs an event
bit into `+0x134`, and plays the bounce audio.

`+0x1F8C` has **one reader** (this branch) and **no writer** found so far in
this build, so the 108 momentum input is not yet mapped and the momentum
class degrades to the **-531.25 floor** (its weaker bounce). See §8.3.

#### 6.2.3 WIND (60) — the old "item_type 60 bounce"

The dispatch below is **not** a bounce tile. `ItemInfoType` 60 is `WIND` —
Summer Breeze, Clover Fan, Conveyor Block and friends — and their push lives
in `validatePhysics` (`0x1405051E0`):

```c
tile = getTileAtPlayerPosition(this);
if (getItemById(getItemManager(), getForeground(tile))->item_type == 60) {
    axis = this[0xE4] - this[0xF0]*0.5;             // horizontal velocity

    if (tile->flags & 0x20) {                        // push "upward"
        if (axis >  kBounceClamp_100p0 ||
            (axis <= 0 && (c = -kBounceCrossZero_1000p0, axis > c)))
            axis = kBounceClamp_100p0;               // clamp to +100
        v16 = -v16;                                  // gravity term flips
        keep = v16 <= axis;
    } else {                                         // push "downward"
        if (-kBounceClamp_100p0 > axis ||
            (axis >= 0 && (kBounceCrossZero_1000p0 > axis)))
            axis = -kBounceClamp_100p0;              // clamp to -100
        keep = axis <= v16;
    }
    if (!keep) axis = v16;                           // fall back to gravity value
    this[0xEC] = axis + base;                        // active
    this[0xE4] = axis*0.5 + base;                    // half
}
```

Conveyor/clamp constants: `100.0` (same-sign) and `1000.0` (cross-zero),
tile flag `0x20` selects the push direction. There is no restitution
coefficient — it is a hard clamp with a direction flip, then a fallback to
the gravity-derived velocity.

### 6.3 Idle damping (friction)

```c
// validatePhysics: only when the horizontal input is zero and neither the
// boot (0x131) nor the slide (0x0DD) override is active.
if (inputAxis == 0.0 && avatar[0x131] == 0 && avatar[0x0DD] == 0) {
    float cur = avatar[0x0E4] - avatar[0x0F0]*0.5;
    lerpTo(&cur, 0.0, kNoInputDamping_1200p0 * dt);   // 1200.0
    avatar[0x0E4] = cur + avatar[0x0F0]*0.5;
}
```

The damped axis is **`+0x0E4` (horizontal velocity)**, not `+0x0F4`. The
vertical axis has no idle damping; it is governed by gravity in
`integrateVerticalAxis`. The Python port in `physics_step.py` currently
applies this damping to `vertical_axis_secondary`, which is a port bug; the
demo overrides the vertical axis after the step, so it does not affect the
jump.

### 6.4 Slide

`sub_140505CB0` (`0x140505CB0`, called from `NetAvatar::tickAux` at
`0x140503C88`) sets `avatar[0x0DD]` from the tile below. It queries the player
collision rect `(pos_x, pos_y + 1, width, height)` through
`sub_140512960` / `sub_140564570`; that query extends 32 px down/right and
returns the first passable overlapping tile. The flag is set when:

- `item_type == 29` (`ItemInfoType.ICE`) — this is the game's **slippery**
  type, not just literal ice. It covers Ice, Ice Cube, Slime, Strawberry Slime
  Block, the dancefloors, Slick Red/Blue/Green, Oil Slick, Flowstone, Nacho
  Block, Frozen Pineapple, Snowflake Block, Space Rock, Fatberg, Block o'
  Barf, Rink of Love, Sideways Vines, Waterslide Strut, and the rest of the
  slippery list; or
- item id `5602` (`ICE_CRUST_BLOCK`, item type 110); or
- the avatar is wearing a slide clothing combination: `7408` + `7410`, or
  `8374`, `9078`, or `10404` — except `5418` (`ICE_SKATES_OF_WINTER`).

`SLIPPERY_FLAG_POLE` is **not** a slippery floor. It is a pole and only gets
the `0.3` vertical damping in `integrateVerticalAxis` (see §5.2).

If `sub_140512960` fails — no `isOn` tile overlaps the player rect, which is
the normal case while airborne — `sub_140505CB0` jumps to its exit and leaves
`+0xDD` **unchanged**. Jumping off a slippery tile therefore preserves the
slide flag and horizontal momentum; the flag clears only when a non-slippery
tile is found on landing. `engine.py`'s `_update_world_state` does this.

`NetAvatar::setJumpHeld` (`0x14050C280`) writes only `+0x105` and `+0x130`; it
does **not** touch the on-ground flag `+0xDC`. The demo's `NetAvatar.grounded`
is the +0xDC mirror, so `set_jump_held` must not write it. Otherwise holding
jump makes the avatar look grounded on the next tick, `_update_world_state`
clears `slide_flag`, and idle damping kills the horizontal momentum on the
first airborne tick after a slide-jump.

`fillTankStatePacket` (`0x1404FBEB0`) reports `avatar[0x0DD]` as
`TANKFLAG_SLIDE` (`0x20000`). In `validatePhysics`, `avatar[0x0DD]`:

- scales horizontal input/acceleration by `0.15` while the vertical axis is
  not falling (`effective <= 0`);
- skips idle damping (the `inputAxis == 0` friction lerp);
- only accelerates toward the current speed cap from *inside* the cap. If the
  horizontal axis is already past the cap (for example `250 px/s` while water
  lowers the cap to `125 px/s`), the client's `v16 > v17` / `v17 <= -v16`
  checks fail and the axis is left unchanged; because idle damping is skipped
  for slide, that above-cap momentum is preserved until the player inputs the
  opposite direction. The engine mirrors this in `integrate_position`;
- makes `vfunc_40` (`0x140501DF0`) apply `vx *= -0.7` on a horizontal
  collision instead of zeroing it.

### 6.5 Floors and the universal half-multiplier

Two plain (non-obfuscated) read-only floats are used throughout:

| Symbol | Address | Value | Meaning |
|---|---|---|---|
| `kHalfMultiplier_0p5` | `0x1408B8FEC` | `0.5` | the `base*0.5` term of the triplet identity |
| `kMinGravity_0p01` | `0x1408EE7A4` | `0.01` | gravity floor when antigravity/zeros-g applies |

In `handleSetCharacterState` (`0x14050B9C0`):

```c
if (gravityHalf - baseGravity*0.5 <= 0.0f) {   // antigravity / zero-g
    gravity     = baseGravity     + 0.01f;
    gravityHalf = baseGravity*0.5 + 0.01f;
}
if (velocityInWater >= 0.0f) velocityInWater = 0.01f;   // 0x3C23D70A floor
```

### 6.6 World-state detection (water and slide)

Both flags are derived from tiles, not from the action input:

| Flag | Written by | Source |
|---|---|---|
| `avatar[0x1A1]` (`waterFlag`) | `updateBlockStateFromPlayerInteraction` (`0x140509C20`) | tile at the player collision-rect center; `tile->flags bit 10` = `TileFlags.IS_WET` (`0x400`) |
| `avatar[0x0DD]` (`slideFlag`) | `sub_140505CB0` (`0x140505CB0`), called from `tickAux` at `0x140503C88` | first passable tile overlapping the player rect extended 32 px down/right; `item_type == 29` (`ItemInfoType.ICE`, the slippery type) or item id `5602` (`ICE_CRUST_BLOCK`), plus slide clothing |

`updateBlockStateFromPlayerInteraction` also calls the water entry/exit effects
(`sub_140132860`) when `0x1A1` changes. `TryPlaceSeedAtTile` (`0x140506430`)
ORs `0x100000` (`TANKFLAG_SWIM`) into the transient `+0x134` mask when
`0x1A1` is set; `fillTankStatePacket` (`0x1404FBEB0`) ORs `+0x134` into the
packet flags and sets `TANKFLAG_SLIDE` from `0x0DD`.

The engine (`gtools/core/growtopia/physics/engine.py`) mirrors this:

- `_detect_water_tile` uses `_tile_index(avatar.pos_x/pos_y)` (the avatar
  position is the collision-rect center) and tests `TileFlags.IS_WET`.
- `_detect_slide_tile` checks the tile under the feet (`pos_y + height/2`)
  across the avatar width and accepts `ItemInfoType.ICE` or `5602`.
- `_update_world_state` writes the water flag every fixed tick and sets or
  clears the slide flag from the feet tile. While airborne with no tile under
  the feet it preserves the previous slide flag (matching
  `sub_140505CB0`'s early exit), so a jump off a slippery tile keeps its
  horizontal momentum.
- `_sync_player_entity` adds `TankFlags.SWIM` and `TankFlags.SLIDE` to the
  rendered player flags.

### 6.7 Recording physics for analysis (F6)

`physics_demo_gpu.py` can record a session to JSON Lines. Press **F6** to
start, reproduce the behaviour, then press **F6** again to stop. The file is
written to `gtools/core/growtopia/physics/recordings/physics_<timestamp>.jsonl`;
`recordings/latest.txt` contains the path of the most recent recording.

Each line is one JSON object:

- `header` — constants, world size, source path, starting avatar and local
  world state.
- `frame` — one per render frame: `dt`, `tick`, pressed keys, key events, and
  the avatar state.
- `tick` — one per fixed physics tick: the same input/avatar data plus
  `pre_integrate` (position and velocities before collision), `horizontal`
  (`vx_before`/`vx_after`, `target_speed`, `slide_scale_applied`,
  `idle_damping_skipped`, `idle_damping_applied`, `above_cap_no_decel`,
  collision/bounce flags), `vertical` (previous and post-integration velocity,
  acceleration, jump-cut flag, fall clamp), and a local world snapshot
  (`feet_tiles`, `below_feet_tiles`, 3x3 neighbourhood, detected/used water and
  slide tiles).
- `final_events` / `footer` — pending key events and the final state.

For the slide-jump question, compare a tick's `pre_integrate.horizontal_velocity`
with `horizontal.vx_after` and check `avatar.slide_flag`,
`horizontal.idle_damping_skipped`, `horizontal.above_cap_no_decel`, and
`world.slide_tile_used`. The avatar block also includes `avatar_jump_held` and
`jump_latch_130` (`+0x105` / `+0x130`) so `setJumpHeld` behaviour can be
checked separately from the on-ground flag.

---

## 6A. Which packets modify the axes (the buffs answer)

`handleSetCharacterState` — `0x14050B9C0` — handles
`TankPacket type == SET_CHARACTER_STATE` (295 packets in the captured session),
**not** the `STATE` packet. Its four vector fields are repurposed as **deltas**:

| Packet field | Offset | Target axis (base / half / value) |
|---|---|---|
| `vector_x`  | `+0x18` | horizontal acceleration — `0x1E0 / 0x1D4 / 0x1DC` (C=1200) |
| `vector_y`  | `+0x1C` | jump / punch strength — `0x208 / 0x1FC / 0x204` (C=400) |
| `vector_x2` | `+0x20` | gravity / max horizontal speed — `0x1F0 / 0x1E4 / 0x1EC` (C=250) |
| `vector_y2` | `+0x24` | vertical acceleration — `0x1D0 / 0x1C4 / 0x1CC` (C=1000) |
| `float_var` | `+0x10` | `velocityInWater` (`+0x1F4`) written directly (C=125) |

Identity preserved by every write:

```c
value = base + delta;
half  = base*0.5 + delta;      // (half - base*0.5) == delta, i.e. the new C
```

So buffs replace the axis constant outright — this is how "which tiles/flags/buffs
modify gravity" is answered at the network level. Tile/item effects in
`integrateVerticalAxis` (§5.2) are the local, per-tick half of the same story.

> The same four offsets mean something different on the `STATE` packet: there
> `vector_x2` (`+0x20`) and `vector_y2` (`+0x24`) are written straight into the
> **velocity** axes `+0x0E4` / `+0x0F4` by `applyTankStateAndEvents`
> (`0x14050C560`), not into the acceleration axes. Interpretation is strictly
> per-packet-type.

Also in this function, when `net_id == 0`:
`GameState->field_28C = animation_type - 0x80` and
`GameState->field_290 = jump_count - 0x80`.

---

## 7. Network reconciliation

### 7.1 Cadence (measured in logs, **verified in IDA**)

Verbose logs carry `[T+<seconds>]` = time since the previous packet.

| Log | client->server deltas | p50 | p75 | count in 190-210 ms band |
|---|---|---|---|---|
| `20260103_225642_app.log` | 2,216 | 0.066 | **0.200** | — |
| `20260104_202305_app.log` | 14,922 | 0.010 | 0.053 | **1,173** |
| `20251226_161042_app.log` | 164 | **0.207** | 0.536 | 19 |

The binary now explains both the ~200 ms clustering *and* the faster bursts.
**200 ms is only the poll gate — an upper bound. The packet is sent only when
its content changed since the last send.** `sendTankState` (`0x1404F5E30`,
called from `NetAvatar::tickAux` every fixed tick, so the *attempt* runs at
tick rate and the gates below decide what goes on the wire):

```c
// v3 = the object behind obj->unknown_8C (not fully mapped; +0x134/0x138/0x1A2
// match NetAvatar offsets, so v3 is most likely the avatar):
//   force path: avatar+0x134 has bit 0x800 (event bit), or pad_90[11] is set
//   -> reset the poll timer so the next tick sends immediately.
if ( (*(DWORD *)(v3 + 0x134) & 0x800) != 0 || obj->pad_90[11] )
    obj->pad_90[4] = 0;
// early-out: avatar byte +0x1A2 set AND dword +0x138 set (the 0x138 "special
// state" that NetControllerLocal::Update also checks) -> skip this poll.
else if ( *(BYTE *)(v3 + 0x1A2) && *(DWORD *)(v3 + 0x138) )
    return;

// rate gate: attempt at most every 200 ms
if ( obj->pad_90[4] < getTick(0) )
{
    obj->pad_90[4] = getTick(0) + 200;                 // next poll
    NetAvatar::fillTankStatePacket(avatar, &obj->pkt); // build the 56-byte frame
    if ( obj->pad_90[8] ) { obj->pkt.flags |= 4; obj->pad_90[8] = 0; }  // one-shot RESET_VISUAL_STATE

    // send gate: only when the state actually changed
    if ( memcmp(&obj->pkt, &obj->lastSentPkt, 0x38)    // (a) 56-byte compare
      || (obj->pkt.flags & 0x10C16740) != 0            // (b) event flags set
      || obj->pad_90[11] )                             // (c) forced-send latch
    {
        memcpy(&obj->lastSentPkt, &obj->pkt, 0x38);
        obj->pad_90[9] = 0;                            // re-arm the duplicate latch
        SendPacketRaw(4, &obj->pkt, 56, 0, peer);      // SEND
    }
    else if ( !obj->pad_90[9] )
    {
        SendPacketRaw(...);                            // one confirmation copy
        obj->pad_90[9] = 1;                            // then silence
    }
    // else: unchanged state at the poll -> send NOTHING (no idle heartbeat)
}
```

Consequences:

- **Moving**: position/velocity/flags change every poll → one STATE per
  200 ms (5 Hz). This matches the 190-210 ms log band.
- **Idle**: the compare succeeds, the confirmation copy is already spent
  (`pad_90[9]`), and the client simply stops sending STATE until the avatar
  moves again. There is **no keep-alive at 5 Hz**.
- **Not-quite-idle**: a sub-pixel change is invisible —
  `fillTankStatePacket` (`0x1404FBEB0`) stores
  `pkt->vector_x = floorf(pos_x + 0.5)` (same for `vector_y`), so only
  whole-pixel differences trip the 56-byte `memcmp`.
- **Faster than 200 ms**: possible only through the force path —
  `pad_90[11]` (or the `+0x134` event bit `0x800`) zeroes the poll timer, so
  the next tick bypasses the gate. Normal motion never exceeds 5 Hz.
- The event mask **`0x10C16740`** decodes exactly against the `TankFlags`
  enum as the one-shot event bits: `FIRE_DAMAGE`, `GOT_KILLED`, `PLACE`,
  `RESPAWN`, `OBJECT_COLLECT`, `DAMAGE`, `POWER_UP_PUNCH_START`,
  `POWER_UP_PUNCH_END`, `ACID_DAMAGE`. Those force a resend even when the
  packet body is otherwise identical (they are cleared again inside
  `fillTankStatePacket`). `SLIDE`/`SWIM`/`STANDING`/`FACING_LEFT` are not in
  the mask; they send via the `memcmp` path like any other change.
- The sub-200 ms bursts in the logs (p50 0.066 / 0.010) are the *other*
  client->server packets (SET_ICON_STATE etc.); they are unaffected by this
  gate, which governs only `TankPacket.type == STATE`.

### 7.2 Packet contents

From the proxy's own decode of `TankPacket(type=STATE, ...)`:

```
flags=<TankFlags...>, vector_x, vector_y, vector_x2, vector_y2, int_x, int_y
```

`vector_x`/`vector_y` carry the avatar position as **whole pixels**
(tile size 32); `fillTankStatePacket` (`0x1404FBEB0`) writes
`floorf(pos + 0.5)` before the packet is compared and sent (§7.1).
The meaning of `vector_x2`/`vector_y2` is resolved in §8.1: on `STATE` they
are the horizontal/vertical velocity written into `+0x0E4`/`+0x0F4` by
`applyTankStateAndEvents`. 187,089 client `STATE` packets in a
single session.

Packet offsets are fixed by the `TankPacket` type:

| Offset | Field | Offset | Field |
|---|---|---|---|
| `0x00` | `type` | `0x18` | `vector_x` |
| `0x01` | `object_type` | `0x1C` | `vector_y` |
| `0x02` | `jump_count` | `0x20` | `vector_x2` |
| `0x03` | `animation_type` | `0x24` | `vector_y2` |
| `0x04` | `net_id` | `0x28` | `particle_rotation` |
| `0x08` | `target_net_id` | `0x2C` | `int_x` |
| `0x0C` | `flags` | `0x30` | `int_y` |
| `0x10` | `float_var` | `0x34` | `extended_len` |
| `0x14` | `value` | | |

### 7.3 Application — snap, not lerp

`NetAvatar::applyTankStateAndEvents` — `0x14050C560`:

```c
if (pkt->dword[3] /* +0x0C */ & 4) {          // position present
    avatar->x = pkt->dword[6];                // +0x18
    avatar->y = pkt->dword[7];                // +0x1C
} else {                                       // delta-only
    avatar->velX = stateBlock[24] - avatar->x;
    avatar->velY = stateBlock[28] - avatar->y;
}
...
if (flags & 0x100) {                          // explicit position flag
    avatar->x = pkt->dword[6];
    avatar->y = pkt->dword[7];
    NetAvatar::onPositionSnapped(avatar, 0);  // 0x1404FF2D0
}

// Later in the same function, when the freshness check passes:
avatar->0x0E4 = pkt->float[0x20] + avatar->0x0F0*0.5;  // vector_x2 -> horizontal velocity
avatar->0x0F4 = pkt->float[0x24] + avatar->0x100*0.5;  // vector_y2 -> vertical velocity
avatar->0x0FC = pkt->float[0x24] + avatar->0x100;      // interpolated value

// The same block decodes TankPacket flag bits into avatar flags:
//   bit 4  -> 0x61
//   bit 5  -> 0xDC   (on-ground / frozen)
//   bit 17 -> 0xDD   (slide; idle-damping guard, TANKFLAG_SLIDE)
//   bit 18 -> 0xDF   (boot variant A)
//   bit 19 -> 0xE0   (boot variant B)
//   bit 26 -> 0xE1   (double_jumped animation flag)
```

**Double jump is server-driven.** A mid-air second jump arrives as a `STATE`
packet with a fresh negative `vector_y2` and flag bit 26 set. The client writes
the new velocity into `+0x0F4` and sets `+0xE1`; `setJumpHeld` never applies a
second impulse. The same `+0xE1` flag is also set by the local trampoline path
in `NetAvatar::onTileUpdateEvent` (`0x1404FEA50`, tile-id branch at
`0x1404FF0E1`), so it means "bounced / double-jumped" for animation purposes,
not "double-jump ability available".

The velocity snap is what makes the `STATE` packet authoritative: `tickAux`
integrates `+0x0E4`/`+0x0F4` between packets, and each new snapshot replaces
them. This is also the key to reading the jump trace in §8.1.

**No interpolation and no extrapolation.** Two snapshot buffers exist
(`avatar+0x10..0x47` and `avatar+0x80..0xB7`), stamped with
`AppContext->field_25C`; the second is filled only when `pkt->byte[0x0C] & 4`.

`NetAvatar::applyTankStatePacket` (`0x1404F58C0`) copies 13 dwords from
`pkt+0x04..0x34` into `avatar+0x14..0x44`. Position (`+0x08`/`+0x0C`) is **not**
written there — it stays under the local simulation.

### 7.4 Event bits (`stateBlock->dword[12]` = `avatar+0x1C`)

| Mask | Action |
|---|---|
| `0x00000001` | `NetAvatar::onTileStepEvent` |
| `0x00000040` | `onTileEnterEvent` |
| `0x00000080` | `onTileUpdateEvent` |
| `0x00000100` | **position snap** |
| `0x00000200` | punch/hazard -> `OnPunched` + `TANK_GOT_PUNCHED` |
| `0x00000400` | records `tileX`/`tileY` |
| `0x00000800` | `sub_140502AB0` |
| `0x00001000` | `sub_140118B20` |
| `0x00002000` | `sub_1404F7410` + tile enter |
| `0x00004000` | `audio/object_collect.wav` |
| `0x00040000` | `TANKFLAG_POWER_UP_PUNCH_END` branch |
| `0x00100000` | `onTileHazardEvent` |
| `0x01000000` | axis `+= 1` while effective `< 3` |

---

## 8. Open items / discrepancies

1. **The transmitted `vector_y2` cannot be read as a plain velocity — earlier
   "≈680 units/s²" reading withdrawn.**
   Raw consecutive client `STATE` packets from `20261002_141139_app.log`
   (16:56:33–36), exactly as the proxy decoded them:

   ```
   16:56:33  x=226  y=738  x2=289.599609375  y2=-
   16:56:33  x=283  y=738  x2=207.998046875  y2=-
   16:56:33  x=299  y=738  x2=-              y2=-
   16:56:33  x=293  y=738  x2=-              y2=-
   16:56:33  x=293  y=738  x2=-              y2=-
   16:56:34  x=293  y=731  x2=-              y2=-450.0
   16:56:34  x=293  y=672  x2=-              y2=-307.201171875
   16:56:34  x=293  y=672  x2=-              y2=-164.40234375
   16:56:34  x=293  y=672  x2=-              y2=-21.603515625
   16:56:34  x=293  y=683  x2=-              y2=121.1953125
   16:56:35  x=293  y=724  x2=-              y2=263.994140625
   16:56:35  x=293  y=738  x2=-              y2=-
   16:56:35  x=293  y=676  x2=-              y2=-354.80078125
   16:56:35  x=299  y=672  x2=40.80078125    y2=-127.001953125
   16:56:36  x=299  y=696  x2=-              y2=185.796875
   16:56:36  x=299  y=738  x2=-              y2=-
   16:56:36  x=299  y=682  x2=-              y2=-366.70068359375
   16:56:36  x=304  y=673  x2=-              y2=31.09814453125
   16:56:36  x=304  y=674  x2=-              y2=-
   ```

   Two facts:
   - `vector_y2` advances by **exactly +142.798828125** per packet across five
     consecutive packets, then the field is omitted for one packet and resumes.
   - `y` is pinned at `672.0` across three packets while `vector_y2` sweeps
     307 units, and `y` returns to `738` on packets where the field is absent.

   **Corrected interpretation (verified in `applyTankStateAndEvents`,
   `0x14050C560`):** that function writes `avatar+0x0E4 = pkt+0x20` and
   `avatar+0x0F4 = pkt+0x24` when its freshness check passes. On a `STATE`
   packet `vector_x2` **is** the horizontal velocity and `vector_y2` **is** the
   vertical velocity. The pinned `y = 672` is a **ceiling clamp**: the player is
   jumping into a ceiling, the server keeps the (negative, upward) velocity
   while clamping the position, and the velocity keeps decelerating until it
   crosses zero and the player falls. That is exactly the ceiling behaviour the
   demo must reproduce.

   The +142.798 quantum per packet is the server's own integration step, not a
   client-side 1000 px/s² step. It implies either a ~0.143 s effective packet
   interval or a server-side deceleration of ~714 px/s²; the exact server tick
   is still open. It does **not** invalidate the velocity semantics.

   Consequences:
   - The **`250.0` axis** is the horizontal speed cap used by `validatePhysics`
     (`|vx| <= 250`); the vertical axis uses the separate `1000` acceleration
     (`+0x1C4`).
   - `vector_x2` / `vector_y2` are the **proxy's decoder labels**; on
     `SET_CHARACTER_STATE` the same offsets are repurposed (see §6A), so
     interpretation is per-packet-type.

2. **Two movement axes.** `+0x0E4` (C=0) is the **horizontal** velocity:
   `tickAux` does `pos_x += value*dt`, and `validatePhysics` integrates the
   horizontal input into it and caps it at `±250`. `+0x0F4` (C=0) is the
   **vertical** velocity: `tickAux` does `pos_y += value*dt`, and
   `integrateVerticalAxis` integrates it with the `+0x1C4` acceleration
   (1000 px/s²). Note it is the **WIND (60)** tile code in `validatePhysics`
   (§6.2.3) that clamps `+0x0E4` at `±100` — the true bounce tiles resolve
   in the vfuncs (`vfunc_40`/`vfunc_48`, §6.2), not in `validatePhysics`.

3. **Physics fields are in `NetAvatar`, allocation `0x2DB8`.** The type used
   by `integrateVerticalAxis` / `validatePhysics` is the IDB `NetAvatar`
   (25,224 bytes, 131 members). The physics allocation is **`0x2DB8` = 11704
   bytes**, confirmed by `operator new(0x2DB8)` at `0x140402019` (reached from
   `sub_140401DB0`). There is no `NetAvatarX` type in the current IDB. The
   fields below are the `NetAvatar` fields at those offsets, with explicit pads.
   Verified against the ctor writes at `0x1404F65E0` and the field reads in
   `integrateVerticalAxis` (`0x140510580`) and `validatePhysics` (`0x1405051E0`).

   Key offsets in the expanded type:

   | Offset | Field | Evidence |
   |---|---|---|
   | `0x00` | vtable | ctor `[rdi] = rax` |
   | `0x08` / `0x0C` | `posx` / `posy` | `tickAux` |
   | `0x1C` / `0x20` | `velx` / `vely` | network/render velocity |
   | `0x80` | `axis80` triplet (C=0) | ctor writes `0x80/0x84/0x88/0x8C` |
   | `0xDC` | `flag_DC` (on-ground) | ctor `[rdi+0DC]=1`; `integrateVerticalAxis` |
   | `0xDD` | `slideFlag` | `sub_140505CB0` writes it; `fillTankStatePacket` -> `TANKFLAG_SLIDE`; `validatePhysics` `cmp [rcx+0DD]` |
   | `0xE4` | `horizontalVelocity` triplet | ctor `0xE4/0xE8/0xEC/0xF0`; `validatePhysics` |
   | `0xF4` | `verticalVelocity` triplet | ctor `0xF4/0xF8/0xFC/0x100`; `integrateVerticalAxis` |
   | `0x104` / `0x105` | `axisValid` / `jumpHeld` | ctor, `setJumpHeld` |
   | `0x130` / `0x131` | `jumpLatch` / `bootVariant` | `integrateVerticalAxis` |
   | `0x134` | `bitmask134` | ctor qword write; `or dword [rbx+134]` |
   | `0x158` | `antigravity` | `validatePhysics` / gravity overrides |
   | `0x188` / `0x18C` | `field_188` / `inputFlags18C` | ctor qword write at `0x188` |
   | `0x1A0` / `0x1A1` | `waterInput` / `waterFlag` | action 500005 -> `0x1A0`; `updateBlockStateFromPlayerInteraction` -> `0x1A1` from `TileFlags.IS_WET` |
   | `0x1A8` | `mods` byte | `SetCharacterMods` |
   | `0x1A9` / `0x1AA` / `0x1B0` | `modBit0/1/2` | `SetCharacterMods` |
   | `0x1B2` | `accelMul` | `integrateVerticalAxis` |
   | `0x1BC` / `0x1BD` | `inputFlag1BC/1BD` | ctor word write |
   | `0x1C4` | `verticalAcceleration` triplet (C=1000) | ctor, `integrateVerticalAxis`. The IDB name `m_actionDuration` on the `0x1C4` member is a leftover from the truncated struct — `vfunc_48` (`0x1405021D0`) reads `[0x1C4] − 0.5*[0x1D0]` as the trampoline gate, i.e. the triplet's effective value. |
   | `0x1D4` | `horizontalMoveSpeed` triplet (C=1200) | ctor, `validatePhysics` |
   | `0xD0` / `0xD4` | `bounceTileX` / `bounceTileY` | `sub_140502AB0` stores them after every bounce (§6.2.2) |
   | `0x1F8C` | **unknown** (single reader) | read as a float by the TRAMPOLINE_MOMENTUM (108) branch of `vfunc_48`: `launch = -800 * 1.5 * (this[0x1F8C]/400)^2`, clamped `>= -531.25` and `<= -10000` while `0x130` (jumpLatch) is held. No writer found yet in this build; tentatively `trampolineMomentum`. |
   | `0x1E4` | `gravity` triplet (C=250) | ctor, `validatePhysics` |
   | `0x1F4` | `velocityInWater` **float** (125) | ctor `(gravity_C)*0.5`; `validatePhysics` reads a float |
   | `0x1FC` | `jumpStrength` triplet | ctor writes `0x1FC/0x200/0x204/0x208` (initial C=0) |
   | `0x2CC0` / `0x2CD0` | qword fields | ctor `[rdi+2CC0]/[rdi+2CD0]` |
   | `0x2CE0..0x2D3F` | six pet-axis triplets | ctor writes each half/flags/value/base |
   | `0x2D40` / `0x2D44` / `0x2D48` | tail fields | ctor writes `0`, byte `0`, dword `6` |
   | `0x2DB0` | final byte | ctor `[rdi+2DB0]=0` |

   The old `0x1F4` triplet reading was wrong: `0x1F4` is a plain float and the
   real 16-byte triplet is at `0x1FC`. The pet block also starts at `0x2CE0`
   (six full triplets), not at `0x2CC0`; the `0x2CC0`/`0x2CD0` qwords precede it.
   The underlying instructions are plain `[reg+disp32]`, so this type change is
   display-only, but it now matches the client offsets exactly.

4. **World bounds / tile size**: `sub_1404FF550` (`0x1404FF550`, vtable `+0x18`)
   clamps position to `world->width * 32.0` and `world->height * 32.0`
   => **tile size 32 px**, before calling `sub_1404F8F20`.

5. **Local position integration is in `tickAux`.** `NetAvatar::tickAux`
   (`0x140503160`) writes `avatar+0x0C` (`pos_y`) from `+0x0F4` and
   `avatar+0x08` (`pos_x`) from `+0x0E4`:

   ```c
   pos_y += (avatar[0x0F4] - avatar[0x100]*0.5) * dt;
   pos_x += (avatar[0x0E4] - avatar[0x0F0]*0.5) * dt;
   ```

   The `STATE` packet snaps the axes (send-on-change, poll gated at 200 ms,
   §7.1); `tickAux` integrates them
   between packets. There is no separate renderer/interpolation path.

---

## 9. IDB changes applied

- **`NetAvatar` physics layout expanded** (`0x2DB8` bytes, layout
  machine-verified against the ctor and the physics functions). Key corrections:
  - `+0x00..+0x07` is the vtable pointer; `posx`/`posy` are at `+0x08`/`+0x0C`.
  - Axis triplets are named `axis80`, `horizontalVelocity` (`0xE4`),
    `verticalVelocity` (`0xF4`), `verticalAcceleration` (`0x1C4`),
    `horizontalMoveSpeed` (`0x1D4`), `gravity` (`0x1E4`), `jumpStrength` (`0x1FC`).
  - `0x1F4` is `velocityInWater` as a **float** (125), not a triplet; the old
    `trip1F4_*` fields were misaligned. The `0x1FC` triplet is the real one.
  - Flags: `flag_DC` (on-ground), `slideFlag` (`0xDD`), `jumpHeld` (`0x105`),
    `jumpLatch` (`0x130`), `bootVariant` (`0x131`), `antigravity` (`0x158`),
    `waterInput` (`0x1A0`), `waterFlag` (`0x1A1`), `mods`/`modBit0/1/2`
    (`0x1A8`/`0x1A9`/`0x1AA`/`0x1B0`), `accelMul` (`0x1B2`),
    `inputFlag1BC/1BD`.
  - Pet block: `0x2CC0`/`0x2CD0` qwords, six full `petAxis0..5` triplets at
    `0x2CE0..0x2D3F`, tail fields at `0x2D40/0x2D44/0x2D48`, final byte `0x2DB0`.
  - The old `field_1B1` / `field_1B4` alignment workaround is replaced by explicit
    pads; every known field is now at its client offset.
- **69 function renames** — the full `NetAvatar` vtable (`scalarDeletingDestructor`,
  `vfunc_08` … `vfunc_58`, `clampToWorldBounds`, `tickAux`,
  `renderEffectsAndNameplate`, `initFromJoinData`, `initFlagA/B`),
  `NetControllerLocal::*`, and 22 `initObfConst_*`.
- **~95 function signatures** applied so `this` propagates as `NetAvatar *`
  rather than `__int64` — previously the renames had landed but the parameter
  types had not, which was the main readability problem.
- **Bounce-path renames (second pass)** — `sub_1404F71E0` →
  `NetAvatar::bounceRadiallyFromTileCenter`, `vfunc_40` (`0x140501DF0`) →
  `resolveHorizontalCollision`, `vfunc_48` (`0x1405021D0`) →
  `resolveLandingCollision`, with block comments documenting the exact
  item-type dispatch, the 500/800/−531.25 launch constants and the landing
  gates (see §6.2).
- **~70 global renames** — the obfuscated pool is now fully and correctly named:
  21 `kObfRand_*` (randomiser, at `B`), 21 `kConst_*`/semantic names (value, at
  `X`), 23 `kObfFull_*` (at `X+8`), plus `kHalfMultiplier_0p5` and
  `kMinGravity_0p01`.
- **20 block comments** at the addresses cited above.
- **New types declared**: `NetAvatarAxis`, `ObfConst`, `NetControllerLocal`.

After this pass `NetAvatar::validatePhysics` reads with named fields and named
constants throughout (`this->gravityHalf`, `this->baseGravity`, `this->slideFlag`,
`this->velocityInWater`, `kBounceClamp_100p0`, `kBounceCrossZero_1000p0`, …)
instead of raw offsets.

### Input action map (`NetControllerLocal::onInputAction`, `0x140511800`)

| Action id | Avatar setter | Field(s) | Meaning |
|---|---|---|---|
| `500004` | `NetAvatar::setJumpHeld` (`0x14050C280`) | `0x105`, `0x130` | jump/action latch — `0x130` gates the `+5000` jump-cut; `0x105` is read by `TryPlaceSeedAtTile` |
| `500005` | `NetAvatar::setWaterInput` (`0x14050C250`) | `0x1A0` | water input action. The auto-detected in-water flag is `0x1A1` (`TileFlags.IS_WET`), and `validatePhysics` uses it for the 125 horizontal cap. |
| `500006` | `NetAvatar::setInputFlag_1BC` (`0x14050C2B0`) | `0x1BC` | modifier bit (+ report channel 0) |
| `500007` | `NetAvatar::setInputFlag_1BD` (`0x14050C2C0`) | `0x1BD` | modifier bit (+ report channel 1) |
| `500056` | `NetAvatar::setJumpHeld` (`0x14050C280`) | `0x105`, `0x130` | alternate jump/action binding |

Each also calls `NetControllerLocal::latchInput` (`0x140511EB0`) on the matching
controller slot (`+0x14`, `+0x18`, `+0x1C`, `+0x20`), stamping it with
`getTick()`; `Update` discards input older than `(now - stamp)/1000 > 15`.

Tooling notes:
- `xrefs_to_field` returns zero for every field in this IDB (including fields
  verified to be used), so field-level navigation was done with a raw
  displacement sweep (`find_bytes` over `0x1CC`–`0x208`) instead.
- `list_funcs` takes its filter under the `filter` key (`name`/`name_like`/etc.
  are silently ignored); `rename` on data requires `{addr, old, new}`;
  `declare_type` splits its input on commas, so each declaration must be a
  separate array element with comma-free comments.

---

## 10. Jump / vertical motion model (demo reference)

`NetAvatar::setJumpHeld` does **not** apply a local impulse; it only latches the
input (`0x105`/`0x130`). The launch arrives as a `STATE` snapshot
(`+0x0F4 = vector_y2`, §7.3), and `tickAux` integrates it between packets with
the `+0x1C4` acceleration (1000 px/s²). The model below is the client's own,
verified in IDA, and cross-checked against the tracked clips:

| Quantity | Value | Source |
|---|---|---|
| launch velocity | `-450 px/s` | `STATE` `vector_y2` (§7.3, §8.1); the packet log shows `y2=-450` |
| vertical acceleration | `+1000 px/s²` | `+0x1C4`, integrated by `integrateVerticalAxis` |
| jump cut (release mid-air) | `+5000 px/s²` added to the acceleration while `0x130 == 0` and `cur < 0` | `integrateVerticalAxis` (§5.2) — an acceleration, not a velocity clamp |
| apex gravity | none; flat `+1000 px/s²` | `integrateVerticalAxis`; no apex branch |
| terminal fall speed | `400 px/s` | `+400` clamp in `integrateVerticalAxis` |
| gravity on the launch tick | **skipped** — the tick that receives the launch is still `0xDC`-grounded, so the avatar travels the full `-450 px/s` before gravity starts | grounded path of `integrateVerticalAxis` (§5.2); nothing clears `0xDC` on a jump press |
| axis clamp | `+400` always, `-400` only while `accel < 0` | `integrateVerticalAxis` (§5.2) |
| double jump | server `STATE` with a new negative `vector_y2` and flag bit 26 (`+0xE1`) | `applyTankStateAndEvents` (§7.3) — no local impulse |

**Trajectory check.** The short-jump clip (`half_jump.txt`) cuts from about
`-472` to `-120` units/s in one 30 Hz frame and reaches apex about `0.15 s`
after launch. A 60 Hz fit of the client model (launch `-450`, `+5000` cut)
gives RMSE `1.09`; the old `-100 px/s` clamp model gives `1.43` and reaches
the same height ~0.07 s later (too floaty) — that was an earlier, differently
aligned fit, so it is not comparable with the unconstrained fits below. The full jump (`diagonal.txt`)
rises `106.09` units from a standing start and reaches its apex `0.433-0.467 s`
after the launch; the client model — launch `-450`, flat `+1000`, **gravity
skipped on the launch tick** — gives `105.00 px` (`3.28` tiles, `-1.0%`) with the
zero crossing at `0.4667 s`. Before that rule was known the fit needed a
`scale 1.08` fudge factor (`105.00/97.50 = 1.080`), which was exactly the
missing tick: applying gravity on the launch tick gives `97.50 px`, `8.1%`
short of the clip. The same tick also explains the logged `STATE` line
`y=731, y2=-450` (the avatar had risen exactly `7 px` — the launch tick's
displacement — while the velocity was still the untouched `-450`).
Free-launch-time fits of both clips at 60 Hz (launch time and, where
applicable, release time free; no scale factor) prefer the rule:

| clip | gravity skipped on the launch tick | gravity applied on it |
|---|---|---|
| `diagonal.txt` (full hold) | **RMSE 2.33 px** | RMSE 6.24 px |
| `half_jump.txt` (released) | **RMSE 2.28 px** | RMSE 2.33 px |

The second jump in `double_jump.txt` is mid-air, applies a
fresh normal-speed launch, and its second apex is ~`96 px` above the first
(recorded gap ~`93 px` after scale), consistent with the server event.

**Ceiling:** clamp the position only. The client keeps integrating `+0x0F4`, so
the upward velocity survives and resumes when the avatar moves out from under
the ceiling. Zeroing the velocity on contact turns a jump into a dead stop —
that was the demo bug.

`gtools/core/growtopia/physics/engine.py` implements this model, wrapped by
the renderer shell `physics_demo_gpu.py`:

- `PLAYER_JUMP_SPEED = 450`, `PLAYER_JUMP_CUT_ACCELERATION = 5000`,
  `PLAYER_MAX_FALL_SPEED = 400`; no `PLAYER_VERTICAL_MOMENTUM` or
  `PLAYER_APEX_GRAVITY_MULTIPLIER`.
- `step_fixed` adds the `+5000` cut acceleration while rising with the jump
  latch released (`+0x130`; see §11.2 — the button alone is not enough),
  integrates flat `+1000` gravity, and only clamps the *fall* speed (the `-450`
  launch is allowed while rising).
- `set_input` applies the grounded launch **without clearing the ground
  flags**: flag `0xDC` is only re-evaluated against the position the avatar has
  already moved to (end of `integrate_position`), so the launch tick is still
  grounded and takes no gravity. Clearing the flags there shortened the jump to
  `97.50 px` instead of `105.00 px`. With `F5` (or
  `PLAYER_ENABLE_DOUBLE_JUMP = True`) an airborne second press emulates the
  server's double-jump `STATE` by reusing the launch speed.
- `step_fixed`'s grounded branch mirrors `integrateVerticalAxis` exactly:
  kill a *downward* velocity (`cur > 0`), keep an upward one, integrate
  nothing (no gravity, no jump cut). Zeroing the axis unconditionally deleted
  the launch.
- `integrate_position` clamps the ceiling position without zeroing
  `vertical_axis_secondary`.

---

## 11. Tile contacts and bounce resolution (demo reference)

§6.2 gives the handler bodies. The part that makes bounce behave like the
client is *when* those handlers run and what they are handed, which lives in
`NetAvatar::tickAux` (`0x140503160`) and `FindNearestInteractableTile`
(`0x140512690`):

1. **Before moving**, `tickAux` calls `FindNearestInteractableTile`, which
   gathers the collision-rect tiles for the position each axis is *about to*
   reach and calls `vfunc_40` (X) then `vfunc_48` (Y) with pointers to both
   velocity axes. The handler rewrites the velocity, and only then does the
   mover run. So a bounce always starts from a non-overlapping position and
   gives the avatar a full tick at the new velocity — the body never spends a
   frame inside the tile and never has its launch eaten by a correction.
2. **X probe** = collision rect translated by the tick's whole X displacement
   (clamped to one tile). **Y probe** = the same for the Y displacement, with
   one quirk: if the rounded Y delta is `0` and the avatar is grounded, the
   probe is `+1 px` down (`if (v9 == 0.0 && isGrounded) v10 = 1.0`). That is why
   an avatar resting on a bouncy tile keeps firing, and why a trampoline under
   the feet triggers without any fall.
3. **First actionable tile wins.** The handlers return `0` once they act and
   the scan breaks. The tile list comes from
   `WorldView::collectGridTilesInRect` (`0x140561580`), which walks the grid
   **column-major** (X in the outer loop, Y inner, left to right then top to
   bottom within a column). Ordering only matters when the rect touches two
   candidate tiles at once (a diagonal seam), but there it decides the launch
   direction, so the demo's `_overlap_tiles` uses the same order.
4. **The mover** (`NetAvatar::moveByPixels`, `0x140512080`) keeps the
   sub-pixel remainder in `+0x64`/`+0x68`, rounds the displacement to whole
   pixels and steps one pixel at a time, stopping on the first tile the axis
   predicate rejects. The body stops *on* a tile edge; it is never pushed
   inside and then resolved back out.

`engine.py` implements this as `_resolve_contacts` (called from
`integrate_position` before any movement) plus `_move_axis` / `_x_blocked` /
`_y_blocked`. The previous implementation resolved collisions *after* moving,
which is what produced the three reported symptoms: the body ended up inside
the tile (penetration), the radial direction was computed from an overlapping
position (launch straight back into the tile, i.e. "wrong direction"), and the
landing gate meant a bounce from below never fired.

### 11.1 Why a corner hit throws further than a centre hit

The launch **speed is constant at 500 px/s**; only the direction depends on
the contact point, because the angle is measured from the tile centre to the
avatar's collision-rect centre. With the demo's `20 × 30` rect (centre = `pos`)
standing on a tile, the vertical offset is fixed at `31 px` (half the body plus
half the tile) while the horizontal offset runs from `0` (dead centre) to
`±26 px` (corner graze):| Contact | offset (dx, dy) | angle | vx | vy | apex after the cut | sideways drift |
|---|---|---|---|---|---|---|
| dead centre | `(0, −31)` | `−90°` | `0` | `−500` | `~21 px` | `0` |
| quarter tile | `(13, −31)` | `−67°` | `193` | `−461` | `~18 px` | `~16 px` |
| corner graze | `(26, −31)` | `−50°` | `321` | `−383` | `~12 px` | `~31 px` |

So "stronger near the corner" is a direction effect, not a magnitude effect:
the launch is always 500 px/s, but near an edge most of it points sideways, and
the avatar drifts about a tile instead of going straight up. These are
resting-contact numbers — `bounceRadiallyFromTileCenter` reads the avatar's
*current* collision rect, not the probe rect used to find the tile, so a fast
fall is caught up to one tick above the tile and launches slightly steeper.
A bounce from below is the mirror image — the player centre is under the tile
centre, so the same formula sends the avatar away downward, which is correct
and needs no special case. Because `vfunc_48` checks `item_type == 24` *before*
the trampoline gates, BOUNCY is ungated in both directions; only trampolines (7),
Lemon Jelly (108) and the steam launcher (3498) require the landing gates from
§6.2.2.

The apex column is why the launch speed alone is misleading: every BOUNCY
launch is **cut** (§11.2), so the flight is `6000 px/s²`, not `1000`, and the
rise is only `vy² / 12000`. Without the cut a corner graze keeps `−383` for `0.77 s` and
drifts ~`250 px` (7½ tiles) — exactly the "it throws me much further at the
corner" bug. With it, the same launch is a short pop with ~`31 px` of sideways
drift, and a centre bounce rises ~`21 px`.

### 11.2 The slide flag and the latch are BOUNCY-only

`NetAvatar::onTileBounceHit` (`0x140502AB0`) is called for all three bounce item
types (`7 || 108 || 24`), and for every one of them it stores the tile in
`+0xD0`/`+0xD4`, writes the item id to `+0x17C` and ORs `0x8000` into `+0x134`.
The slide flag and the jump-latch clear sit inside a *second*, narrower test:

```asm
140502cc9  cmp  dword ptr [rsi+4], 18h    ; item_type == 24 (BOUNCY)
140502ccd  jnz  loc_140502CEE             ; trampoline / Lemon Jelly -> done
140502ccf  or   dword ptr [rbx+134h], 20000h
140502cd9  mov  byte ptr [rbx+0DDh], 1     ; slide flag
140502ce0  mov  byte ptr [rbx+140h], 0
140502ce7  mov  byte ptr [rbx+130h], 0     ; jump latch
```

So only a **bouncy** hit sets `+0xDD` and clears `+0x130`; `+0x105` (jump held)
is left alone in every case. A trampoline leaves both bytes untouched, which is
the whole reason a trampoline must not put the avatar into the airborne slide
state the way a bouncy block does: the client never arms `+0xDD` for it, and
`sub_140505CB0` only *rebuilds* the flag from a slippery tile under the feet —
with no tile under the feet it leaves `+0xDD` as it found it.

The latch matters because `integrateVerticalAxis` gates the cut on it, not on
the button (`0x1405106CE`–`0x1405106E4`):

```c
if (cur < 0.0f && avatar[0x130] == 0 && avatar[0x1A9] == 0)
    accel += 5000.0f;                 // else if (avatar[0x131]) accel += 0.85f * 5000.0f
```

`NetAvatar::setJumpHeld` (`0x14050C280`) writes `+0x105` and `+0x130` together,
and it is an **input action** (500004), fired on the press and the release — not
a per-frame poll. The two bounce families therefore behave differently:

| tile | latch after the hit | arc |
|---|---|---|
| BOUNCY (24) | forced to `0` | always cut: `6000 px/s²`, rise `vy²/12000` (a 500 px/s launch peaks at ~`21 px`) |
| TRAMPOLINE (7/108), steam | untouched | cut only while the button is up — released it rises `800²/12000 ≈ 53 px`, held it gets the uncut `800²/2000 ≈ 320 px` |

That is why a held jump cannot stretch a bouncy launch (the latch is cleared
behind the player's back, and a still-held button does not re-arm it), while a
trampoline still answers to the button. `+0x1A9` is read here and in three
other places but has **no writer** in `.text` outside a possible wide store, so
nothing else suppresses the cut for tile launches.

The demo mirrors this: `latch_jump` forwards to `set_jump_held` only when the
button changes state, `_on_tile_bounce_hit(fg_type)` returns immediately for
everything but `ItemInfoType.BOUNCY`, and the cut in `update_physics` tests the
latch. The slide flag the client sets on a bouncy hit is transient in the demo
too — `_update_world_state` rebuilds it from the tile below at the top of the
next tick.

