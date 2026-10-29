# Static player avatar rendering

Scope: draw a Growtopia player from the `Player` dataclass in
`gtools/gtools/core/growtopia/player.py` as one still image. No animation, no
camera projection, no shader work - only the per-part atlas cells and their
anchors, as the client computes them.

* Implementation: `gtools/gtools/core/growtopia/renderer/` (`layout.py` holds the
  draw spec, `renderer.py` the compositor).
* Entry point: `gtools/scripts/render_player.py`.
* Verification harness (scratch, `gtools/.tmp_tex/`): `ref_fetch.py`,
  `compare_oracle.py`, `attribute_diff.py`, `anchor_tests.py` against cached
  reference renders. Those come from a public endpoint, so each one is fetched
  once, settled, and cached as `ref_<name>.png` (1x, colour-exact) plus
  `ref_<name>_x4.png` - never re-requested in a loop.

Every constant below is either quoted from the disassembly with its address, or
listed under *Approximations*. Nothing here comes from eyeballing a screenshot.
Where a constant is only *confirmed* by picture comparison, the section says so
and gives the number.

## One draw primitive, one base

All avatar parts go through one wrapper:

```
spriteDraw(camera, sprite, frameX, frameY, pos*, scale*, align, tint,
                 angle, offset*, flipX, flipY, ...)        @ 0x14056F2A0
```

Three facts drive the whole layout:

1. **`align` is a pivot selector** (`sub_1400DFBF0` @ `0x1400DFBF0`):

   | align | pivot |
   | --- | --- |
   | 0 | (0,0) |
   | 1 | (w/2, h/2) |
   | 2 | (w/2, h) - bottom centre |
   | 3 | (w, 0) |
   | 4 | (0, h) |
   | 5 | (w/2, 0) - top centre |
   | 6 | (0, h/2) |
   | 7 | (w, h) |
   | 8 | (w, h/2) |

   So with `align 2` the caller passes the cell's **bottom centre** and the
   cell's top-left is `pos - (w/2, h)`.

2. **`scale` is a multiplier of the atlas cell**, `1.0` = one cell in pixels.
   The blitter builds the quad as `cell * scale` (`sub_1400D3F80` @
   `0x1400D3F80`). The avatar's own scale lives in `renderer[+0x4C]`
   (`movss [rsi+4], xmm1` @ `0x1402616F8`), the position in `renderer[+0x48]`
   (`0x1402616F4`); both are set from the avatar's slot coordinates, and
   `renderClothes` then adds the camera offsets (`addss xmm13,[rdi+1C48h]` @
   `0x1402617E9`, `addss xmm14,[rdi+1C4Ch]` @ `0x1402617F2`).

3. **Every part is handed the same base.** The base (x, y) - the body cell's
   bottom centre in screen space - travels in non-volatile registers `xmm10`
   (x) and `xmm9` (y) and is reloaded at each call: `movaps xmm1,xmm10` /
   `movaps xmm2,xmm9` @ `0x1402625E8`-`0x1402625EC` (arm, call `0x1402625F3`),
   @ `0x140262861`-`0x140262865` (feet, call `0x14026286C`). All per-part
   offsets therefore live *inside* the part drawers, which is what makes the
   body-local pixel constants below meaningful.

## Texture table

`loadAvatarTexture` @ `0x14025F1E0` (called once from the avatar constructor
`initNetAvatar` @ `0x14025E200`, call site `0x14025E263`) loads every base
texture and configures it through the `SurfaceAnim` vtable:

* `vtbl+0x50(w, h)` = frame size, `vtbl+0x48(cx, cy)` = frame grid.

| File | Renderer field | Configuration | Cell |
| --- | --- | --- | --- |
| `game/player_head.rttex` | `+0x50` | size `(0x20, 0x20)` @ `0x14025F2DE` | 32x32, 4x2 cells in a 128x64 atlas |
| `game/player_severedhead.rttex` | `+0x58` | size `(0x20, 0x20)` | 32x32 |
| `game/player_arm.rttex` | `+0x60` | size `(6, 10)` @ `0x14025F56B` | 6x10, in an 8x16 atlas |
| `game/player_arm_thumbsup.rttex` | `+0x98` | size `(8, 10)` | 8x10 |
| `game/player_arm_pointerup.rttex` | `+0x150` | size `(8, 16)` | 8x16 |
| `game/player_puncharm.rttex` | `+0x88` | size `(0x14, 0x30)` | 20x48 |
| `game/pom.rttex` | `+0xC0` | size `(4, 8)` | 4x8 |
| `game/player_face.rttex` | `+0x78` | grid `(8, 8)` @ `0x14025F7FB` | 32x32 |
| `game/player_eyes.rttex` | `+0x68` | grid `(8, 8)` @ `0x14025F884` | 32x32 |
| `game/player_eyes2.rttex` | `+0x70` | grid `(8, 8)` @ `0x14025F90D` | 32x32 |
| `game/player_iris1.rttex` | `+0x138` | grid `(8, 8)` | 32x32 |
| `game/player_face2.rttex` | `+0x140` | grid `(8, 8)` | 32x32 |
| `game/player_eyes3.rttex` | `+0x148`-ish | grid `(8, 8)` | 32x32 |

The eye/face atlases are 256x256, so an 8x8 grid means 32x32 cells - **not** 8x8
pixel frames.

The body tile is **not** the whole avatar. `player_head`'s cell is 22x28 px of
art (rows 0..27 of the 32 px cell), and the feet come from separate textures:
`player_feet.rttex` for the default pair, `player_extraleg*.rttex` for the leg
stretcher between the body and the feet, and the per-slot item atlases
(`player_feet2..16`, `player_feet_large*`, `player_feet_monthly1`) for worn
shoes. Those are opened by the feet drawer rather than by `loadAvatarTexture`,
which is why they do not appear in the table above.

Item textures (`player_hair*.rttex`, `player_pants.rttex`,
`player_cosmetics1.rttex`, ...) are not loaded here; they share the 32 px cell
grid, addressed by the item's `tex_coord_x` / `tex_coord_y`.

## Per-part spec

Call sites are inside `renderClothes` @ `0x140261610` (recovered with
`xrefs_to`), so the table doubles as the draw order of the normal outfit branch.

| Part | Draw function | Call site | Frame | Anchor (body-cell px) |
| --- | --- | --- | --- | --- |
| back item | `sub_140268BC0` | `0x1402624AF` | item `tex_coord` | `(0, -16)` |
| neck (behind body) | `sub_14026BC30` | `0x1402624F6` | item `tex_coord` | `(0, 0)` |
| arm (far, behind body) | `sub_1402671F0` | `0x1402625F3` | arm frames | `(21, 18)` |
| body | `sub_14026B240` | `0x14026260C` | `(shirt?1:0 \| pants?2:0, 0)` | `(0, 0)` |
| expression | `sub_14026D0F0` | `0x140262686` | `(state%8, state/8)` | `(0, 0)` |
| clothing tiles | `sub_1402760A0` | `0x140262836`, `0x140262936`, `0x140262A1C`, `0x140262B6E`, `0x140263020`... | item `tex_coord` | `(0, 0)` |
| face item | `sub_1402760A0` | same tile group, **after** the expression | item `tex_coord` | `(0, 0)` |
| hand item | `sub_1402671F0` (arm pass) | `0x1402625F3` / `0x140263907` | item `tex_coord` | `(-8, 18)`, mirrored `(8, 18)` |
| shoes | `sub_1402789A0` | `0x14026286C` | `(tex_x, 2*tex_y + flip)` | `(0, 0)`, `(0, 12)` for 2216 |
| hair | `sub_140272AA0` | `0x1402636E4` | item `tex_coord` | `(0, -16)` |
| hat | `sub_140273210` | `0x140263748` | item `tex_coord` | `(0, -16)` |
| neck (front) | `sub_14026BC30` | `0x140263621`, `0x1402637D0` | item `tex_coord` | `(0, 0)` |
| arm (near, in front) | `sub_1402671F0` | `0x140263907` | arm frames | `(5, 18)` |

### Body (the "head" tile)

`sub_14026B240`, `align 2`, anchored at the shared base - so the 32x32
`player_head` cell lands at body-local `(0, 0)`. Frame, `0x14026B302`-`0x14026B32D`:

```asm
14026b302  cmp     word ptr [rsi+2], 0     ; clothes.shirt
14026b307  mov     ebx, 2
14026b30f  lea     eax, [rbx-1]            ; 1
14026b312  jz      short loc_14026B325
14026b314  cmp     word ptr [rsi+4], 0     ; clothes.pants
14026b319  mov     r12d, 3
14026b31f  cmovz   r12d, eax               ; pants? 3 : 1
14026b325  xor     r12d, r12d              ; shirt == 0
14026b328  cmp     [rsi+4], r12w
14026b32d  cmovnz  r12d, ebx               ; pants? 2 : 0
```

so `frameX = (shirt ? 1 : 0) | (pants ? 2 : 0)`, `frameY = 0` -
`layout.body_frame()`.

### Expression (eyes / face / pupils / mouth)

`sub_14026D0F0` draws four cells, all `align 2` and all at
`base + (scaleX * player[7568], scaleY * player[7572])` - the animation jitter,
0 for a static pose:

```c
v63 = v18 % 8;            // frameX
v80 = v18 / 8;            // frameY
for (v26 = 0; v26 < 3; ++v26) {
    // v26 == 0: sprite = renderer[+0x68] = player_eyes,  tint = player[7184]
    // v26 == 1: sprite = renderer[+0x78] = player_face,  tint = a5
    // v26 == 2: sprite = renderer[+0x70] = player_eyes2, tint = player[7188]
    spriteDraw(cam, sprite, v63, v80, pos, scale, 2, tint, ...);
}
spriteDraw(cam, renderer[+0x78] /* player_face */, v63, v80 + 4,
                 pos, scale, 2, a4, ...);          // mouth row
```

So the static face is `eyes(0,0) -> face(0,0) -> eyes2(0,0) -> face(0,4)`; the
three tints are avatar fields (`player[7184]` eye white, `player[7188]` lens)
and the mouth's `a4` is `AvatarRenderer[+0x28]`, the skin colour - the mouth
cell is a grey mask, so it must be tinted. `layout.DRAW_ORDER` follows that
order and `renderer.py` maps `tint="eye"/"lens"/"face"/"skin"` to those three
tints plus the skin.

### Feet

`renderClothes` calls `sub_1402789A0` (a big per-item dispatcher) once per foot
pair; the placement itself is done by `sub_14027E7B0` @ `0x14027E7B0`, which the
dispatcher calls at `0x14027AA1A` / `0x14027B666` (both `align 2` through
`spriteDraw`). Fully decoded in this session:

```asm
14027e7cc  movss   xmm1, dword ptr [rcx+4Ch]     ; renderer scale
14027e7d1  mov     rbp, r9                       ; r9 = offset vec
14027e7d4  movss   xmm0, dword ptr [r8+4]        ; r8 = pos vec -> y
14027e7da  addss   xmm1, xmm1                    ; 2 * scale
14027e7eb  subss   xmm0, xmm1                    ; pos.y -= 2 * scale
14027e7ef  movss   dword ptr [r8+4], xmm0
...
14027e82d  movzx   ecx, byte ptr [rax+61h]       ; item.tex_coord_y   (arg_30)
14027e831  movzx   ebx, byte ptr [rax+60h]       ; item.tex_coord_x -> frameX
14027e837  cmp     [rsp+0B8h+arg_38], al         ; flip byte
14027e83e  setnz   al
14027e841  lea     edi, [rax+rcx*2]              ; frameY = 2*tex_coord_y + flip
...
14027e9c1  mov     [rsp+0B8h+var_88], 2          ; align 2
14027e9db  call    spriteDraw
```

Between the frame build and the draw, the function re-derives the frame for
coarser zoom steps from the current zoom (`r10d = [appCtx+0x25C]` against
`[avatar+0x2928]` / `[avatar+0x2924]`): the three middle steps add `frameY += 2`
and `frameX += 1..3` (`0x14027E861`-`0x14027E8D9`), and the closest step adds
`frameX += 2` - plus one more on a mod-3 phase (`0x14027E8DB`-`0x14027E931`).
A still render sits at the closest step.

Both rows are drawn at the same anchor: the `2*ty` cell paints the left shoe into
the left half of the 32 px tile and the `2*ty + 1` cell the right shoe into the
right half, so the pair composes the same 32 px column as every other slot.
`layout.shoe_frames()` returns both rows and the renderer composites both.

Net anchor at scale 1, plain shoes: the cell's top-left is `body + (0, 0)` -
i.e. the caller-side lift inside `sub_1402789A0` (its own x/y terms are visible
at `0x14027B0E5` / `0x14027B0FF` / `0x14027B11F`) minus the blitter's
`-2 * scale` cancels out for the ordinary case. Confirmed by picture comparison
(*Verification*): IoU 0.9964 for an ordinary shoe, 0.9512 with a 12 px lift.

### The per-item leg offset (decoded, no longer fitted)

`sub_14027E7B0` keeps a local `v128` = the *leg* offset in pixels and shifts the
cell by `-v128` (`0x14027E7EB` region). Its value is a class table, not a
per-item hack:

```c
v128 = 0.0;                                        // else: no lift
if (sub_14053C450(id) || id == 2216 || id == 3074 || sub_14053C770(id)) {
    v128 = avatar[7576] - 2.0;                     // shoe / effect class
    if (sub_14053BB60(id) || sub_14053C770(id)) { v128 -= 1.0; ... }
    switch (id) {
      case 0xC9E:  v128 += 2.0;  break;            // 3230
      case 0x8A8:  v128 -= 10.0; break;            // 2216
      case 0xA0E:  v128 -= 6.0;  break;            // 2574
      case 0x137E: v128 -= 2.0;  break;            // 4990
      case 0x1EEE: v128 += 2.0;  break;            // 7918
    }
} else if (sub_14053BC50(id))   v128 = avatar[7576];      // 2974
else if (id == 7144)            v128 = avatar[7576];
else if (sub_14053B740(id) || sub_14053B7C0(id) || ((id - 8898) & 0xFFFFFFF9) == 0)
                                v128 = avatar[7576] - 3.0;
else if (id == 8370 || id == 8512) v128 = -1.0;
```

`avatar[7576]` is the walk bob, `0` for a still avatar, so the switch cases land
at `-2 + delta`: 3230 -> 0, 2216 -> -12, 2574 -> -8, 4990 -> -4, 7918 -> 0. The
id predicates are small hard-coded functions, read directly:

| predicate | contents | lift |
| --- | --- | --- |
| `sub_14053C450` @ `0x14053C450` | 1496, 1740, 9648, 1758, 11140, 2574, 3230, 4990, 6372, 7918, 8834, 8948, 10390, 10404, 10878 | +2 |
| `sub_14053C770` @ `0x14053C770` | 4822/4824/4826/4828 (bitset `85` over `id-4822`) + FISHING_DINGHY, GO_ANYWHERE_SURFBOARD, CARDBOARD_NESSIE, JET_SKI_CHARIOT, SWAN_BOAT | +3 |
| `sub_14053B740` @ `0x14053B740` | 2048, 2064, 3788, 9134 | +3 |
| `sub_14053BB60` @ `0x14053BB60` | 1740, 9648 | +3 |
| `(id - 8898) & 0xFFFFFFF9 == 0` | 8898, 8899, 8904, 8905 | +3 |
| `sub_14053BC50` @ `0x14053BC50` | 2974 | 0 |

The two independently measured cases agree with the switch exactly - plain
shoes at 0 (IoU 0.9964 at 0 vs 0.9512 at 12) and Fire-Nado `2216` at 12 (0.9975
vs 0.8249) - which is why `layout.SHOE_OFFSET_Y_BY_ITEM` is now *derived* from
this table (3230/7918 -> 0, 4990 -> 4, 2574 -> 8, 2216 -> 12) instead of fitted.
The `sub_14053B7C0` list (a long hard-coded rideable list, still untranscribed)
is the one place where the table is incomplete.

### Bare feet and the leg stretcher

With an empty shoes slot the client still calls the feet drawer. `renderClothes`
passes it item id 0 in several branches of the shoes switch (for example the
`clothes[3] == 9650` branch, which calls `sub_1402789A0(a1, ..., 0, ...)` right
after the item's own pass), so an empty slot is "draw the default pair", not
"draw nothing". What that pair is can be read off the textures:

* `player_feet.rttex` - 256x256, 8x8 cells. Cell `(0, 0)` holds one foot at
  atlas columns 8..16 and cell `(0, 1)` the other at 20..26, both in rows
  29..31. Both are blitted at `body + (0, 0)` with `align 2`, so their art lands
  four rows below the body art.
* `player_extraleg.rttex` - 16x16 with a single art row, `######......####`,
  the leg cross-section. It is drawn at cell `(8, 28)`, i.e. directly between
  the body art's last row (27) and the feet art's first row (29).

Both are greyscale and take the **skin** tint, like the body. `layout` carries
the four constants (`BARE_FEET_TEXTURE`, `BARE_FEET_FRAMES`, `LEG_TEXTURE`,
`LEG_ROW_OFFSET`) and `renderer._bare_feet()` draws them in that order inside the
shoes slot, so the bare feet land in the same painter's-order position a worn
shoe would.

### Hand item

Hand items are **not** body-cell tiles: the client draws them inside the arm
pass, so their cell is placed with the arm's own arithmetic - `align 5`,
`pos = (base_x + 8 - 16*flip, base_y - 14)`, and since their cells are 32 px
wide the top-left is `(-8, 18)` facing right (`(8, 18)` mirrored), with the art
mirrored through the negative scale like the arm. At `(0, 0)` a boxing glove
lands on the avatar's face, which is how this was found (item 96, 52 px on the
nose; the reference render has none there).

### Arm, both arms

`sub_1402671F0` (`0x1402625F3` early, `0x140263907` late in `renderClothes`),
`align 5` (top centre), cell 6x10:

```
pos.x = x + (8 - 16 * flip) * sx
pos.y = y - 14 * sy
scale = (1 - 2 * flip) * sx        ; negative = mirrored art
```

With `align 5` the top-left is `pos - (w/2, 0)` = `(x + 8 - 16*flip - 3, y - 14)`,
and the shared base is `(16, 32)`, so:

* `flip = 1` -> `(5, 18)`: the **near** arm, which hangs on the avatar's *left*
  while it faces right. Art mirrored (`scale` negative).
* `flip = 0` -> `(21, 18)`: the **far** arm, on the right, drawn *behind* the
  body. Art unmirrored.

The client draws both: the call at `0x1402625F3` happens before the body call at
`0x14026260C` (so that arm lies behind the body cell), the one at `0x140263907`
after the clothing block (in front). The flip byte reaches the drawer as stack
arg 7: `movzx r15d,[rsp+71h]` / `mov [rsp+38h],r15b` @ `0x1402625B1` /
`0x1402625C5`.

Because the drawer mirrors through the *scale* while every other cell is
mirrored by hand through its anchor, the arm's texture is mirrored exactly when
the rest is not - `layout.Sprite.mirror_invert`, used by `renderer._sprite`.

Consequence for a still image: the far arm at `(21, 18)` is completely covered
by the 32 px body cell (a reference render is byte-identical with and without
it), so only the near arm is visible on a normal avatar.

### Hair, hat, and the accessory pass

`sub_140272AA0` is the accessory pass (`0x1402636E4`, `0x140263748`). It reads
the item's **visual effect** from `[item+0x58]` (see the visual-effects section;
this used to be mislabelled "item class" here) and adjusts y (`xmm6` = arg2,
saved at `0x140272ABE`) by effect:

```asm
140272c8e  movsxd  rcx, dword ptr [rdi+58h]      ; visual_effect
140272c92  movss   xmm13, cs:kHalfTile_16p0      ; 16.0
140272c9b  cmp     ecx, 0Ch
140272c9e  jz      short loc_140272CA5
140272ca0  cmp     ecx, 11h
140272ca3  jnz     short loc_140272CB4
140272ca5  movss   xmm0, dword ptr [r14+4Ch]     ; avatar scale
140272cab  mulss   xmm0, xmm13
140272cb0  addss   xmm6, xmm0                    ; y += 16 * scale
140272cb4  lea     eax, [rcx-2Fh]
140272cb7  cmp     eax, 1
140272cba  ja      short loc_140272CCE
140272cbc  movss   xmm0, dword ptr [r14+4Ch]
140272cc2  mulss   xmm0, cs:flt_1408BB49C        ; class 0x2F/0x30
140272cca  addss   xmm6, xmm0
...
140272b06  movss   xmm15, cs:dword_1408BE098     ; = 3.0
140272b24  movss   xmm0, dword ptr [r14+4Ch]
140272b2a  mulss   xmm0, xmm15
140272b2f  subss   xmm6, xmm0                    ; y -= 3 * scale
```

and takes the frame from the item: `movzx ebx,[rdi+61h]` (tex_coord_y `@
0x140272DAB`), `movzx edi,[rdi+60h]` (tex_coord_x `@ 0x140272DB8`), plus a per
class `frameX` offset (`add edi, r13d` `@ 0x140272DC1`).
`dword_1408BE098` = `3.0` and `flt_1408BE09C` = `4.0` are read straight out of
`.rdata` at `0x1408BE098` / `0x1408BE09C`.

For effects outside the two low-hair families the net top-left is
`body + (0, -16)`, i.e. one half cell above the body cell - see *Verification*
for the pixel-exact confirmation. `LOWHAIR`/`LOWHAIR_MASK` add the half cell
back (net 0) and `VERYLOWHAIR`/`VERYLOWHAIR_MASK` end at `-6`; those two
families cover 90 hair items, so this is not a corner case.

## Tint: one multiply, rounded

Every sprite is handed a tint colour (`spriteDraw`'s tint argument, which
arrives as a packed RGBA in a register and is copied into the blitter's vertex
colour). The body, arm, mouth, bare feet and leg stretcher all get
`AvatarRenderer[+0x28]`, the avatar's **skin colour** - which the client stores
as an RGB value on the avatar (`clothing.skin_color` in `Player`), not as an
index the renderer has to look up.

The multiplication happens in the shader and is rounded to 8 bits, which is
1/255 different from a truncating multiply. `renderer._tint()` rounds:

```
atlas grey 200 * skin blue 80 / 255 = 62.7  ->  client 63, PIL `multiply` 62
```

That single-pixel level difference was measurable on *every* tinted pixel and is
what capped the earlier colour comparisons at 62-77 % even when the geometry was
pixel-exact. With it fixed the dressed outfit below scores 96.9 % exact RGB and
the remaining mismatches are concentrated in item art, not in the skin.

### The skin colour the reference renders use

`gtools/avatar_render_oracle.py` asks for `skincolor: "8"`, so every cached
reference render is skin 8. Solving `ref = round(atlas * S / 255)` over the
greys of the body cell gives one solution that fits every texel:

| atlas grey | reference | implied S |
| --- | --- | --- |
| 120 | (56, 43, 38) | (119.0, 91.4, 80.8) |
| 163 | (77, 59, 51) | (120.5, 92.3, 79.8) |
| 181 | (85, 65, 57) | (119.8, 91.6, 80.3) |
| 200 | (94, 72, 63) | (119.8, 91.8, 80.3) |
| 218 | (103, 79, 68) | (120.5, 92.4, 79.5) |
| 237 | (112, 86, 74) | (120.5, 92.5, 79.6) |
| 255 | (120, 92, 80) | (120.0, 92.0, 80.0) |

So **skin 8 = (120, 92, 80)**, and the multiply is confirmed exact (not
approximate) once rounded. A 9x9x9 sweep around it scores the same value - the
fit is unique in its neighbourhood. `scripts/render_player.py` now uses it.

## Item visual effects (`ItemInfoVisualEffect`)

The byte at **item+0x58** is the item's visual effect (the dat field right after
`texture_file_hash`; every drawer reads it as `cmp dword ptr [item+58h], imm8`).
IDA renders it as `item->?[6]` because the struct is typed as dwords from
`+0x40`; `?[6]` *is* `+0x58`.

**Proof of the field identity** (the dat parse and the client's own reads agree
field for field). In `deserializeItemDatabase` - dumped as
[`gtools/deserializeItem.txt`](../gtools/deserializeItem.txt) - `a1` is the
in-memory item and `item` the wire buffer, and the counter `*a3` walks the
buffer while `a1`'s fields are written back at *fixed* offsets:

| `deserializeItem.txt` | offset | field | `items_dat.py` |
| --- | --- | --- | --- |
| L117 / L126 `v20 = *((_BYTE *)a1 + 88); a1[22] = v20;` | +0x58 (22*4) | u8 | `visual_effect` (u8, read at L920) |
| L130 `a1[23]` | +0x5C | i32 | `cooking_time` (i32, L921) |
| L139 `*((_BYTE *)a1 + 96)` | +0x60 | u8 | `tex_coord_x` (L922) |
| L148 `*((_BYTE *)a1 + 97)` | +0x61 | u8 | `tex_coord_y` (L923) |
| L154 `*((_BYTE *)a1 + 100)` | +0x64 | u8 | the next field (L163 `a1[25] = v24`) |

That is exactly the ordering the Python dat reader uses, so the byte the drawers
switch on at `+0x58` is the same one `items_dat.py` exposes as
`Item.visual_effect`. Independent cross-check from the draw side: the accessory
drawer (`accessory.c`, whole function) takes its item as
`ItemManager->itemsBegin + 1616 * ItemID` and reads the *same* three fields -
`*(_DWORD *)(v23 + 88)` for the effect switch, `*(unsigned __int8 *)(v23 + 96)`
and `+ 97` for the two tex coords.

**It is not an item class** - earlier notes here called it ``[item+58h] class``,
which was wrong: the values are ``ItemInfoVisualEffect``. The value names used
below are IDA's own `enum ItemInfoVisualEffect : unsigned __int8` from
the database header, and each one is matched to a `cmp [item+58h], imm` in the
draw path (right-hand column of the table).

It is the per-item switch behind most avatar special cases. Everything below was
read out of the draw path rather than guessed:

| value | effect | still-frame behaviour | where |
| --- | --- | --- | --- |
| 4 | `ANIM` | `frameX += (tick/100)&1` in face/clothing drawers, `(tick/200)&1` in the accessory pass | bitmasks `0x1000090` / `0x10090` @ `0x14026DC79`, `0x140272C9B` |
| 7 | `PET_ANIM` | same | same |
| 8 | `NO_ARMS` | on the **shirt**: the arm pass (and the hand item it draws) never runs | `v258` @ `0x1402625xx`, gates `sub_1402671F0` |
| 11 | `BOTHARMS` | second copy of the item cell, `frameX + 1` | `cmp [rsi+58h], 0Bh` @ `0x1402686CD` |
| 12 / 17 | `LOWHAIR` / `LOWHAIR_MASK` | accessory `y += 16 * scale` (net 0 with the half-tile lift) | `0x140272C8E`-`0x140272CB0` |
| 13 | `UNDERFACE` | face item drawn **before the body cell** | `v177 = -1` in `renderClothes`, `sub_14026DA80` after `sub_14026B240` |
| 14 | `SKINTINT` | face tile tinted with the skin colour (`renderer[+0x28]`) | `cmp ecx, 0Eh` / `mov r12d,[r14+28h]` @ `0x14026DD4E` |
| 15 / 16 / 17 | `MASK` / `ANIM_MASK` / `LOWHAIR_MASK` | on the **hair**: the face slot moves *after* the hair | `v177 = (ve-15) <= 2` @ `0x140263020`-region |
| 19 / 45 | `PULSE` / `LIGHTSOURCE_PULSE` | scale/alpha pulse from the timing system | `cmp eax, 13h` / `2Dh` @ `0x14026DED6` |
| 20 / 22 / 27 / 38 / 39 | `COLORIZE`, `COLORIZE_ANIM`, `COLORIZE_WITH_SKIN`, `PETCOLORED`, `SILKFOOT` | dye-driven: tint from the item's colour + a second overlay sprite (`frameX + 1`) | bitmask `0xC008500000` @ `0x140276896`, `0x140272CC4`, `0x14026DD60` |
| 23 / 24 | `HIGHFACE` / `HIGHFACE_ANIM` | face `y -= 16 * scale` | `0x14026DD2E`-`0x14026DD44` |
| 25 | `RAINBOW_SHIFT` | tint cycles through `sub_14025E9B0(item+0x10C)` | `cmp [item+58h], 19h` @ `0x1402675CE`, `0x1402762C3` |
| 28 | `NO_RENDER` | drawer returns without blitting | `cmp r12d, 1Ch` @ `0x14026DB6F` |
| 30 | `OFFHAND` | hand item drawn on the other arm (own branch with punch state) | `cmp [rsi+58h], 1Eh` @ `0x140267577` |
| 47 / 48 | `VERYLOWHAIR` / `VERYLOWHAIR_MASK` | accessory `y += 10 * scale` (net -6) | `(ve - 47) <= 1` @ `0x140272CB4`-region |

Counted over the whole item database (16 480 items, `Item.visual_effect`):
`ANIM` 453, `PET` 380, `COLORIZE` 195, `PULSE` 161, `HIGHFACE`+
`HIGHFACE_ANIM` 136, the low/very-low hair family 96 (`VERYLOWHAIR` 77,
`LOWHAIR` 10, `LOWHAIR_MASK` 9), `MASK` 27, `NO_ARMS` 22, `BOTHARMS` 33,
`UNDERFACE` 15, `OFFHAND` 14, `SKINTINT` 11, `NO_RENDER` 2. The biggest
**static**-visible effect still unimplemented is `BOTHARMS` 33 (a second copy of
the item cell at `frameX + 1`); `PET`/`COLORIZE`/`PULSE` need a pet, a dye or
the timing system that a still `Player` does not carry.

Implemented in the renderer (`layout.py` tables, `renderer.py` application):
`HIGHFACE`/`HIGHFACE_ANIM`, `LOWHAIR`/`LOWHAIR_MASK`,
`VERYLOWHAIR`/`VERYLOWHAIR_MASK`, `NO_ARMS`, `UNDERFACE`, mask-hair face order,
`SKINTINT`, `NO_RENDER`, `BOTHARMS`, `OFFHAND`, `PULSE` (dynamic alpha from
`frame_interval_ms` via `layout.pulse_alpha()`).

Not implemented, because a still `Player` carries no dye colour:
`COLORIZE*`, `RAINBOW_SHIFT`, `PETCOLORED`, `SILKFOOT` - they only fire when a
dye (`>= 0xE1`) is present. Also left out: `PULSE`'s animation phase (tick is
always 0 for a still render, so the pulse is a fixed per-item alpha), `SPIN`/
`STEP_SPIN`/`TILTY` (rotation), `GHOST`, `WINGED`, `SINK`, `BACKFORE`, and the
multi-cell animation below. `NO_RENDER` was traced in the face drawer
(`cmp r12d, 1Ch` @ `0x14026DB6F`); the renderer skips *any* clothing slot
carrying it.

## Item-specific note: LIGHTSOURCE (34)

`LIGHTSOURCE` / `LIGHTSOURCE_PULSE` (value 34/45) appears on 37 items including
wearable wings (`Hyperlight Wings`, `Soulforge Wings`, ...) and shoes
(`MagTron LightCycle`, `Riding Firefly`). No draw-path handling for the effect
itself was found in the face/shirt/accessory/back drawers - it falls through to
the normal item cell draw. It is therefore rendered as an ordinary cell. If the
client adds a glow/aura pass for `LIGHTSOURCE` items, that pass has not been
located in the disassembly.

### Multi-cell items (`animating_coordinates`)

A separate mechanism, often mistaken for a visual effect: items whose
`animating_coordinates` string is set draw **several cells** from the same atlas,
and their `extra_file` is a second texture. Phoenix Hair (8588) is a clean
example - `animating_coordinates = "0,0|1,0|0,1|1,0|"` plus
`extra_file = game/ld_phw.rttex`, which is exactly the wide flame plume a
reference render shows around a 32 px hair cell. The static renderer draws one
cell, so such an item renders small. Nothing here models it yet.

## Facing

The client never mirrors the cell positions: it passes `flipX` to the blitter
(and a negative `scale` for the arm) and bakes the facing into the x term
(`8 - 16*flip`, `2*tex_y + flip`). `PlayerRenderer` mirrors the whole 32 px body
column instead (`x = 32 - x - w`), which is identical for every anchor that is
symmetric about the body cell - the near-arm anchor `5` mirrors to `21`, exactly
the far arm's client x. `facing=+1` = the unmirrored body art (`flip = 0`); the
arm cell alone is mirrored the other way round (`Sprite.mirror_invert`), because
the client flips it with a negative scale instead of by hand.

## Verification

Reference renders come from the third-party gtsetplanner endpoint
(`gtools/avatar_render_oracle.py`), downscaled from its 4x canvas to game-pixel
scale by *sampling* every 4th pixel (so colours stay exact, no resampling).

### Bare avatar: every layer pixel-exact

A bare player (no clothing, all ten slots 0) is the cleanest test because it
exercises only the body, expression, arms and the new bare-feet path. Against
`gtools/.tmp_tex/ref_bare.png` (32x22 tight crop, skin 8):

| metric | before this pass | after |
| --- | --- | --- |
| silhouette IoU | 0.9006 | **0.9840** |
| reference pixels not drawn | 39 | **0** |
| solid-RGB exact | 19.8 % | **92.7 %** |

Rows 29..31 (the bare feet) are **17/17 pixels exact**, including colour, which
simultaneously proves the feet cells, their anchor and the rounded tint. Row 28
(the stretcher) is 9/10 exact. Every reference pixel is covered - the render is
a superset - and the only surplus pixels are one column of the near arm.

### Visual-effect outfit (VERYLOWHAIR + HIGHFACE + NO_ARMS)

Hair 10080 (Tied-up Buns, `VERYLOWHAIR`), face 3790 (Techno Visor, `HIGHFACE`),
shirt 7026 (Pink Kimono, `NO_ARMS`), everything else bare - one reference render,
aligned by best IoU shift:

| variant (one command each, reference cached) | IoU | solid-RGB exact |
| --- | --- | --- |
| `ref_fetch.py fx2 hair=10080 face=3790 shirt=7026` | **1.0000** | **904/907 (99.7 %)** |
| same, `--no-effects` | 0.8092 | 388/759 (51.1 %) |

`--no-effects` empties `ACCESSORY_OFFSET_Y_BY_EFFECT` and
`FACE_OFFSET_Y_BY_EFFECT` and stops `NO_ARMS` matching, i.e. it turns off
exactly the three rules this outfit exercises. The silhouette then breaks by
19 % and the colour-exact count halves, so the 16 px face lift, the 10 px
very-low-hair shift and the suppressed arm pass are confirmed against the
client's own output, not just against code.

The three remaining pixels are the eye overlay's whites: this render draws
`(230,230,230)`, the reference `(217,216,215)`/`(218,216,216)` (about a x0.945
shade). They are attributed to `expr_eyes` (`player_eyes.rttex`), not to any
effect rule.

### Dressed avatar: the script's own outfit

Hair 6008, hat 46, pants 344, shoes 2216, neck 7576, no shirt/face/hand/back/
artifacts - exactly what `scripts/render_player.py` renders:

| metric | before the tint fix | after |
| --- | --- | --- |
| silhouette IoU | 0.9975 | 0.9975 |
| solid-RGB exact | 77.4 % | **96.9 %** (1160/1197) |

The 37 remaining pixels, by the harness's per-layer attribution
(`ref_fetch.py script hair=6008 hat=46 pants=344 shoes=2216 neck=7576`):
arm 21/41, body 5/195, `expr_face` 5/5, shoes 5/279. The hat texels
(`(230,230,230)` here, `(218,216,216)` in the reference) and the Fire-Nado's
lower edge are part of the shoe/hat rows; the arm's 21 px are the known open
item below (a shirtless avatar's arm art sits at a different column inside its
cell than the drawer arithmetic implies). The earlier per-layer attribution
table (below) still describes where the colour residual *used* to sit - all of
it was skin, which the rounded tint fixed.

Three reference renders were captured with `gtools/.tmp_tex/ref_fetch.py`
(one request each, cached as `ref_<name>.png` + `ref_<name>_x4.png`; the 1x crop
is *sampled* from the 4x canvas so colours stay exact):

| reference | outfit | IoU | solid-RGB (at the time) |
| --- | --- | --- | --- |
| `oracle_native` (early capture) | hair 6008, hat 46, pants 344, shoes 2216, neck 7576 | 0.9975 | 77.4% |
| `ref_plain` | hair 44, shirt 36, pants 48, hat 46, shoes 40 | 0.9964 | 62.6% |
| `ref_mixed` | hat 66, hair 70, face 34 (Shades), hand 96, back 350, neck 1456, shoes 42, pants 76, shirt 124 | 0.9553 | 70.6% |
| `ref_bare` | all slots 0 | 0.9840 | 92.7% |
| `ref_script` | the script's outfit above | 0.9975 | 96.9% |

The three early rows predate the tint fix, so their colour numbers are floors.
Their IoU - which is colour-independent - is what validated the anchors.

`ref_mixed` after the fixes below: face 0/79, hat 0/322, hair 0/34, neck 0/22,
shoes 0/48, shirt 12/189, hand 11/22, and every remaining large mismatch on
skin-tinted layers (body 212/212, arm 44/44, mouth 7/7 - the endpoint's own
skin colour). The glove's 11 px are its own dye: the atlas red is
`(203,30,31)`, the reference draws `(215,36,37)`.

What that comparison caught (all fixed in this session):

* the face item must be drawn **after** the expression pass - otherwise eyes,
  pupils and mouth paint over worn sunglasses (`face` went from 16/16
  mismatching to 0/79);
* the feet anchor is per-item, not a constant (plain shoes were floating 12 px
  below the body);
* hand items belong at the arm anchor, not at the body cell.

The older alignment harness numbers (integer translation search, my canvas
shifted by `(-16, -3)`; silhouette = IoU of the alpha masks):

| configuration | silhouette | IoU | solid-pixel RGB |
| --- | --- | --- | --- |
| facing +1, shoes +12 (item 2216's override), both foot rows | 99.84% | 0.9975 | 897/1194 |
| facing +1, shoes +0 | 88.43% | 0.8249 | 635/994 |
| facing +1, shoes +14 | 96.88% | 0.9541 | - |
| facing -1, shoes +12 | 88.98% | 0.8449 | 225/1095 |
| facing +1, foot row 0 only | 93.37% | 0.8989 | - |
| facing +1, foot row 1 only | 94.13% | 0.9106 | - |
| near arm at (5, 18), art mirrored (current) | 99.84% | 0.9975 | 927/1197 |
| near arm at (21, 18) - the old, wrong side | 99.84% | 0.9975 | 897/1194 |
| near arm at (6, 18) | 99.95% | 0.9992 | - |
| far arm added behind the body | 99.84% | 0.9975 | no pixel change |

Per-layer attribution of the residual mismatch
(`gtools/.tmp_tex/attribute_diff.py`, mismatching / solid pixels owned):

| layer | mismatch | covered |
| --- | --- | --- |
| body | 195 | 195 |
| arm (near) | 41 | 41 |
| expr_mouth | 23 | 23 |
| expr_face | 5 | 5 |
| shoes | 5 | 279 |
| arm_back (far) | 1 | 1 |
| expr_eyes / expr_eyes2 | 0 | 21 / 8 |
| hair | 0 | 267 |
| hat | 0 | 176 |
| pants | 0 | 10 |
| neck | 0 | 171 |

Read as: every untinted slot (hair, hat, pants, shoes, scarf, eyes) is
pixel-identical or off by a handful of anti-aliased edge pixels, and the whole
remaining difference (270 of 1197 solid px) sits on skin-tinted cells, which is
the endpoint's own skin colour. Geometry is therefore pixel-exact at 1x for
this avatar; anchors, frame rows and the +/- 1 px alignments all agree.

## Approximations and gaps

* **Arm anchor, 1-2 px.** The reference renders agree on the *side* (left while
  facing right) but not on the exact column: the dressed reference prefers x = 6
  (0.9992 vs 0.9975 IoU) and the bare reference shows its arm's outer edge at
  cell x = 7, i.e. +2 from the client's align-5 value 5. `layout` keeps the
  client arithmetic - the general arm draw at `0x140267660`-`0x1402676E6` is
  unambiguous (`pos.x = base_x + x*(8 - 16*flip)`, `align 5`, `- 14*scale` in
  y) - so the difference must come from somewhere this pass did not reach: a
  shirtless avatar may be drawn with a different arm texture (`player_arm_snd` /
  `player_arm_sno` / `player_arm2..4` all exist), whose art sits at a different
  column inside its cell. Open, and the last geometric difference left.
* **Arm art mirroring is not checkable from the reference.** The comparison only
  scores alpha masks and colour, and the 6x10 arm tile's silhouette is symmetric,
  so a flipped and an unflipped arm score identically. The mirror comes from the
  client's `scale = (1 - 2*flip)`, and only the facing-right case is exercised
  against a reference at all - no reference render exists for facing left, where
  the body cell art itself is mirrored by `PlayerRenderer`.
* **Visual effects are only partly modelled.** Positions, `NO_ARMS`, face draw
  order, `SKINTINT` and `NO_RENDER` are implemented and the position ones are
  reference-verified (IoU 1.0000 vs 0.8092 with the rules off); `BOTHARMS`,
  `OFFHAND`, the dye family, `PULSE` and the
  multi-cell `animating_coordinates` items are not (see the visual-effects
  section for what each needs).
* **Per-class overrides are only partly modelled.** The feet leg offsets are now
  decoded (see above) but the `sub_14053B7C0` rideable list inside them is not
  transcribed, and `sub_1402789A0` also has its own x/y terms
  (`0x14027B0E5` `kHalfTile_16p0` and friends) for large foot art. The accessory
  pass `sub_140272AA0` still uses one anchor for every class (class 12/17,
  0x2F/0x30, the 3.0-scale branch and the `sub_140132B50` predicate are read but
  collapsed into `(0, -16)`), which is what the reference-render check validates
  for this item set.
* **Expression state.** Fixed to `(0, 0)` (neutral). The client derives it from
  `NetAvatar+7604` and the emote at `+8820`, which `Player` does not carry.
* **Neck.** Drawn once, in front. The client blits it twice (behind and in front
  of the body); both calls use the same cell and anchor.
* **Far arm is invisible on a normal avatar** - one pixel of it shows past the
  body silhouette in the reference comparison. It is drawn because the client
  draws it, not because a still image needs it.
* **Hand item modes are not modelled.** `sub_1402671F0` switches texture and
  pose per hand item (`player_arm_thumbsup`, `player_puncharm`, pointer-up, and
  per-id branches); the renderer always draws the item's own cell at the arm
  anchor. Good enough for held objects, wrong for the special arm poses.
* **Shirt/torso shading.** 6-12% of shirt pixels still differ from the two
  reference renders (single-digit px). Not yet traced - either the reference
  tints shirt art or a torso pass (`sub_1402760A0` variants) is missing.
* **Leg stretcher row count.** Only the bare-footed, standing case is modelled
  (one row at `(8, 28)`), which is what a reference render shows. The stretcher
  is by construction the filler between the body art and the feet, so items in
  `SHOE_OFFSET_Y_BY_ITEM` that are lifted more (Fire-Nado at +12) should stretch
  it by that many rows; that stretch is not implemented, and the reference
  outfit above shows it as the Fire-Nado's lower-edge residual.
* **Hat shading, 5 px.** This render gives `(230,230,230)` where the reference
  draws `(218,216,216)` on five hat texels - a dye/shading multiply on top of the
  item art that is not modelled. The eye overlay shows the same thing on three
  texels, at `expr_eyes` on the effect outfit above: `(230,230,230)` in this
  render, `(217,216,215)`/`(218,216,216)` in the reference, i.e. about x0.945.
* **Dedicated render objects are not implemented at all.** Some 114 wearable
  item ids are not drawn from their atlas cell: `initRenderObjectGeneric`
  @ `0x14015AAF0` registers a per-id render object instead (see the section
  below). Round 3 of the feedback set wears one (`9006` Spirit of Anubis) and
  round 4 wears another (`7100` Famine's Steed), which is exactly where those
  two rounds stay low (IoU 0.24 / 0.59).
* **Not implemented:** sleeve / severed-head / pet overlays, the registered
  render objects above (wings, vehicles/sleighs, Anubis), chairs, ghost tinting,
  item dyes, animation, the closest-zoom `frameX + 2` phase the feet blitter
  applies at `0x14027E8DB`.
* **Facing left is unverified.** The only reference render is right-facing.
  `facing=-1` mirrors the anchors *and* the cell art (including the body tile),
  which is what the client's align-2 anchors imply but has not been compared
  against a picture.
* **Provenance.** Loader table, base registers, body frame bits, expression
  pass, feet blitter (whole function), accessory class table, arm call sites and
  side semantics, the whole visual-effect pass (dat field identity from the
  `deserializeItemDatabase` dump, the per-effect byte tests in the face,
  clothing, accessory and arm drawers, the counts over the item database) and
  the reference-render verification were read in the latest session. The
  `back`/`neck` slot offsets, the `sub_1400DFBF0` align table and
  the clothing-tile call sites were extracted in earlier sessions and were not
  re-read here; they are marked as such above.

## Item sheet frame size, and the items that are not cells at all

### Frame size: `loadTilesheet` @ `0x14056DC20`

Every clothing drawer fetches the item's surface through
`sub_14056DB70` @ `0x14056DB70` (which loads it with `loadTilesheet` on first
use, or `sub_14056DF10` for the *extra* slot) and then passes only
`frameX`/`frameY` to `spriteDraw`. The cell size is therefore a property
of the surface, set once in the loader::

```asm
14056de28  mov     eax, [rbp+64h]      ; item->texture_type
14056de2b  dec     eax
14056de2d  cmp     eax, 9
14056de30  ja      loc_14056DE80       ; SINGLE_FRAME_ALONE: keep the default
14056de32  mov     eax, 139Ch          ; item 5020
14056de3a  jz      loc_14056DE69
14056de3c  mov     eax, 2072h          ; item 8306
14056de44  jz      loc_14056DE69
14056de51  test    byte ptr [rbp+76h], 1   ; flags2 & LONG_HAND_ITEM64x32
14056de57  mov     edx, 40h            ; 64
14056de5c  lea     r8d, [rdx-20h]      ; 32
14056de62  mov     edx, 20h            ; 32
14056de69  mov     edx, 40h            ; 64       (the two ids: 64x64)
14056de7c  call    qword ptr [rax+50h]     ; surface->SetFrameSize(w, h)
```

* `[rbp+64h]` is `ItemInfoTextureType` (the enum's `SINGLE_FRAME_ALONE = 0`,
  `SINGLE_FRAME = 1` .. `SMART_EDGE_DIAGON = 10`, so `(t - 1) <= 9` means
  "anything but `SINGLE_FRAME_ALONE`"). Items outside that range keep the
  surface default; every sheet this renderer draws has 32 px cells.
* `byte ptr [rbp+76h]` bit 0 is bit 16 of the dword at `+0x74`,
  `ItemInfoFlag2.LONG_HAND_ITEM64x32` - the flag that names the 64x32 grid.
* Two hard-coded ids, `0x139C` (5020) and `0x2072` (8306), get 64x64.

Implemented as `layout.item_frame_size`, used by the renderer for the item's
own cell (the arm and hand copies included). Cross-check from the shipped art:
for the Ice Dragon Scythe (`player_longhanditem3.rttex`, 512x512, coord
`(0, 3)`) the 32x32 slice at `(0, 96)` holds 40 opaque pixels and the 64x32
slice 336 - the whole blade - so the 64-wide read is the real one.

The hand anchor follows from the same rule: the arm drawer's blits use **align
5** (`mov [rsp+1A0h+var_170], 5` before each of the blits at `0x140267754`,
`0x14026789F`, `0x140267AB0`, `0x140267C9F`, `0x140267DBD`, `0x140268398`,
`0x140268B36` in `sub_1402671F0`) and the align-5 pivot is `(cellW/2, 0)`
(`sub_1400DFBF0`), while the drawer's own `pos.x` does not depend on the cell
width. A 64-wide frame therefore moves the cell's top-left 16 px left of the
32 px case.

### Items with a registered render object instead of a cell

`initRenderObjectGeneric` @ `0x14015AAF0` builds a per-id table of render
objects of about **114 wearable ids** (Scepter of the Honor Guard, Odin's
Ravens, Rayman's Hair, the sleighs / carriages, the Ancestral artefacts, ...).
Two of them carry their *own* texture and class rather than the shared
clothing sheets:

```asm
14015d1e4  lea     rdx, aLdBisunaRttex ; "ld_bisuna.rttex"
14015d1f2  call    memcpy
14015d1f7  mov     r8d, 232Eh           ; item 9006 Spirit of Anubis
14015d207  call    sub_140158400        ; its render object
14015d277  lea     rdx, aMiMinbotRttex ; "mi_minbot.rttex"
14015d28a  mov     r8d, 24A0h           ; item 9376
14015d29a  call    sub_1401DC8A0
```

`ld_bisuna.rttex` is referenced from exactly this one place in the binary
(`find` string -> `0x1408F42B8`, one xref), which is what proves the Anubis
spirit is *not* an atlas cell of `player_cosmetics1.rttex`.

Status: **not implemented**. An offline probe adds a 64x32 slice of the
`ld_bisuna` sheet (128x64) to the round-3 outfit and lifts its IoU from 0.2393
to 0.5388 at body-local `(-18, -24)`, which is strong evidence for the shape of
the missing art, but the object's own draw code (`sub_140158400` and its
vtable) has not been read, so no anchor or cell from it is used in the
renderer. The same applies to `7100` Famine's Steed in round 4.

### The front back overlay is gated by `ItemFlag.FOREGROUND`

The `back_front` layer (cell `tex_coord_x + 1`) is not drawn for every back
item. The front pass `sub_140271FA0` reads bit 13 of the item's flags word
before it blits anything:

```asm
1402720b1  call    getItemManager
1402720b6  imul    rsi, rdi, 650h      ; ItemDat, stride 1616
1402720bd  add     rsi, [rax+8]
1402720c1  jz      loc_14027233A       ; no items -> return
1402720c7  movzx   ecx, word ptr [rsi+72h]
1402720cb  shr     cx, 0Dh             ; bit 13
1402720cf  test    cl, 1
1402720d2  jz      loc_14027233A       ; clear -> return, no blit
```

`item+0x72` is the dat's second field, `ItemFlag` - the same offset
`sub_14025F010` tests and the same bit the face-order rule uses. Only 4 of the
102 `player_back.rttex` items carry it (1746 Fuel Pack, 1762 Soda Jetpack,
1958 Genuine Rings, 1960 Ecto Pack); Da Vinci Wings has `0x14`.

This matters beyond the pixel rule: with `tex_coord_x = 7` on the 8-column
`player_back.rttex` the `+ 1` cell is column 8, i.e. **off the 256 px sheet**,
so building that sprite before applying the gate raised
`crop (256,64,32,32) out of bounds` in `scripts/render_player.py`. The client
is never asked to build it, because the gate returns first. Both the render
loop and `_clothing_parts` now test `ItemFlag.FOREGROUND` before the cell.

### The artifacts slot paints no cell

`renderClothes` @ `0x140261610` reads `clothes+0` .. `clothes+8` only (hat,
shirt, pants, shoes, face, hand, back, hair, neck) and never `clothes+9`, the
artifacts slot, so no blit in the avatar pass can be fed from it. Artifact
items are dispatched purely as **particles**:

```asm
14010b2a1  call    getItemManager
14010b2ab  call    itemDatabaseFromId
14010b2b0  cmp     dword ptr [rax+4], 6Bh   ; item_type == 107 (ARTIFACT)
14010b2b4  jnz     loc_14010B70A
14010b2ba  cmp     dword ptr [rax], 2414h   ; 9236 excluded
...
14010b3d5  call    spawnParticleActual      ; two emitter sites, per-item type id
```

and the emitter is `maybeRenderAura` @ `0x1402605B0` (it also handles the
pendant/ring items at `clothes+8` and `clothes+10`). The aura's own colour
(132,255,255) appears in **no** cell of `player_artifact.rttex` (all 30 cells
scanned), which is further proof it is particle art, not an atlas cell.

Status: the renderer draws **nothing** for the slot (drawing
`player_artifact.rttex` cell (0,0) had put the Tesseract cube on the body).
Reference check, artifacts alone: at best fit the body matches at IoU 0.8236,
and the only reference pixels the render does not cover are 130 cyan
(`(132,255,255)`-family) px in rows 20-32, i.e. the aura beside the legs -
130/751 = 17% of the reference, the exact thing described. The aura itself is
**not implemented**: it is a particle system (`spawnParticleActual`), not a
sprite cell, and a static renderer has nothing to drive it from.

### `extra_file` is not avatar art

`Item.extra_file` holds a generic extra asset path, not a second texture for
the avatar: over the feedback outfits it is an `interface/large/...` icon, a
`game/particles_large*.rttex` sheet, `game/spazip.rttex`, or even
`audio/mlaunch.wav` (Ice Dragon Scythe). It must not be used as a slot texture.

### Re-check numbers (offline, cached references, no new requests)

`.tmp_tex/recheck_rounds.py` compares against the references already cached by
`scripts/render_feedback.py`. Before this pass -> now:

| round | slot that matters | IoU | solid-RGB |
|---|---|---|---|
| 1 | back 1574, hand 3644 | 0.6412 -> **0.7151** | 66.2% -> 66.6% |
| 2 | back 13372, hand 6058 | 0.2333 -> **0.8640** | 16.7% -> 54.3% |
| 3 | back 9006 (registered object) | 0.2467 -> 0.2393 | 5.9% -> 7.3% |
| 4 | back 13062, shoes 7100 (registered object) | 0.5919 -> 0.5945 | 10.0% -> 10.1% |
| 5 | back 11664 | 0.5537 -> **0.5737** | 42.3% -> 48.6% |
| 6 | hand 11464 (long hand) | 0.2375 -> **0.4987** | 0.8% -> 6.6% |

Round 6 is the long-hand change (its scythe was clipped to 32 px before); round
3 and round 4 are the registered-object gap above.

## Flags

`CharacterFlags` handling mirrors the client's hide bits:

* `INVISIBLE` (`0x4`) and `Player.invis` -> empty canvas.
* `NO_BODY` (`0x20`) -> skip body tile and shirt/pants/shoes.
* `NO_HANDS` (`0x8`) -> skip arm and hand item.
* `NO_FACE` (`0x10`) -> skip face item and expression layers.

## Usage

```bash
cd gtools && uv run python -m scripts.render_player --out player.png
cd gtools && uv run python -m scripts.render_player --facing -1 --out player_left.png
```

