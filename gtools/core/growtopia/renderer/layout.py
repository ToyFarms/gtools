"""Static sprite layout for the Growtopia avatar.

Coordinates are **body-cell pixels**: origin (0, 0) is the top-left corner of
the 32x32 ``player_head`` tile, which is the avatar's whole body (head, torso,
legs and feet in one cell). Every other part is placed relative to it.

How a part is placed (all from the decompiled client, see
``docs/player-avatar-render.md`` for the per-constant citations):

``renderSprite`` @ ``0x14056F2A0`` is the single sprite draw used by every
avatar part::

    renderSprite(camera, sprite, frameX, frameY, pos*, scale*, align,
                     tint, angle, offsetVec*, flipX, flipY, roundMode)

* ``scale`` is a multiplier where ``1.0`` means "one atlas cell, in pixels";
  it is multiplied by the camera zoom and passed on to the blitter, which
  builds the quad as ``cell * scale`` (``sub_1400D3F80`` @ ``0x1400D3F80``).
* ``align`` selects the pivot that ``pos`` refers to
  (``sub_1400DFBF0`` @ ``0x1400DFBF0``)::

      0 (0,0)   1 (w/2,h/2)   2 (w/2,h)   3 (w,0)   4 (0,h)
      5 (w/2,0) 6 (0,h/2)     7 (w,h)     8 (w,h/2)

  so with ``align 2`` the caller passes the cell's *bottom centre* and the
  cell's top-left is ``pos - (w/2, h)``.
* every part is handed the *same* base: ``renderClothes`` puts the avatar's
  position and scale into ``renderer[+0x48]``/``renderer[+0x4C]``
  (``0x1402616D0``-``0x1402616F8``), adds the camera offsets
  (``0x1402617E9``-``0x1402617F2``) and passes that base (x, y) - the body
  cell's bottom centre - to the body, eyes, arm, feet and accessory drawers
  alike, in ``xmm10``/``xmm9`` (e.g. ``movaps xmm1, xmm10`` @ ``0x1402625E8``
  for the arm, @ ``0x140262865`` for the feet). All per-part offsets therefore
  live *inside* the drawers, so the constants below are body-local pixels.
* ``frameX``/``frameY`` index the atlas cell; the atlas comes out of the
  ``.rttex`` file, whose cell size is set in ``loadAvatarTexture``
  @ ``0x14025F1E0`` (frame size via vtable +0x50, frame *grid* via +0x48).
* ``flipX`` mirrors the cell's texture; callers mirror the *anchor* by hand
  (``(8 - 16*flip)`` and friends), which is equivalent to mirroring the whole
  32px body column - what :class:`~.renderer.PlayerRenderer` does. The arm is
  the exception: ``sub_1402671F0`` mirrors its cell through a negative
  ``scale``, i.e. the opposite way round from the hand-mirrored anchors, so its
  sprites set ``mirror_invert``.
"""

import math
from dataclasses import dataclass
from typing import Literal

from gtools.core.growtopia.items_dat import ItemInfoFlag2, ItemInfoVisualEffect

AVATAR_TILE = 32

#: Where a sprite's tint colour comes from. Every sprite the client draws goes
#: through a multiply, so the only per-part question is which colour:
#:
#: * ``skin`` - the renderer's skin colour, ``AvatarRenderer[+0x28]``, itself
#:   set from the avatar's skin field in ``renderClothes``. Body, arm, mouth.
#: * ``eye``  - ``avatar[7184]``, the eye-white colour (white by default).
#: * ``lens`` - ``avatar[7188]``, the lens/pupil colour. ``Player`` carries no
#:   lens, so the renderer falls back to black, the plain-avatar look.
#: * ``face`` - ``AvatarRenderer[+0x2C]``, the face overlay colour; that cell
#:   is almost fully transparent, so this is cosmetic.
#: * ``none``  - drawn as stored (only the body sprites that need no tint).
Tint = Literal["none", "skin", "eye", "lens", "face"]

#: Canvas handed back by the renderer. The 32x32 body column sits at
#: ``CANVAS_ORIGIN`` so accessories that overhang the body still fit: wings-type
#: back items and mounts draw well outside the body cell (a reference render of
#: ``Spirit of Anubis`` reaches 30 px above the head and ``Firework Wings``
#: 30 px to each side), so the box is four body cells with the body centred.
CANVAS_SIZE = AVATAR_TILE * 5  # 160
CANVAS_ORIGIN = CANVAS_SIZE // 2 - AVATAR_TILE // 2  # 64: body cell centred

# Textures loaded by loadAvatarTexture @ 0x14025F1E0, with the cell sizes it
# configures. player_head is a 128x64 atlas (4x2 cells); the eye/face
# textures are 256x256 atlases with an 8x8 frame grid (32x32 cells).
BODY_TEXTURE = "player_head.rttex"
ARM_TEXTURE = "player_arm.rttex"
EYES_TEXTURE = "player_eyes.rttex"
EYES2_TEXTURE = "player_eyes2.rttex"
FACE_TEXTURE = "player_face.rttex"

BODY_CELL = (AVATAR_TILE, AVATAR_TILE)
ARM_CELL = (6, 10)

#: Texture drawn for the **empty** shoes slot: the client's feet drawer
#: ``sub_1402789A0`` @ 0x1402789A0 is called with item id 0 for a bare-footed
#: avatar and blits the default feet instead of an item cell. ``player_feet``
#: is a 256x256 atlas (8x8 cells of 32 px); the bare pair lives in cells
#: ``(0, 0)`` and ``(0, 1)`` - one foot each, art in atlas rows 29..31:
#:
#: * ``(0, 0)`` -> art columns 8..16, ``(0, 1)`` -> art columns 20..26;
#: * both cells are blitted at ``body + (0, 0)`` with ``align 2``, so their
#:   rows 29..31 are the four rows below the 22x28 body art (row 28 belongs to
#:   the leg stretcher, see ``docs/player-avatar-render.md``);
#: * the art is greyscale (181/200) and takes the **skin** tint like the body.
#:
#: Verified pixel-exact against a bare reference render: all 17 lit pixels of
#: rows 29..31 match, including the skin colour, when the tint is rounded.
BARE_FEET_TEXTURE = "player_feet.rttex"
BARE_FEET_FRAMES: tuple[tuple[int, int], ...] = ((0, 0), (0, 1))

#: The leg stretcher drawn between the body art and the feet. ``player_extraleg``
#: (and its 2/3/4 variants) is a 16x16 texture holding a single row - the leg
#: cross-section ``######......####`` - that the client stretches over the gap
#: between the 28-row body art and the feet. A still, bare-footed avatar needs
#: exactly one row, at cell ``(8, 28)``: the reference render's row 28 is that
#: row to within 9/10 pixels (the miss is the skin shading of one texel).
#:
#: The row count is what the per-item leg offsets in
#: :data:`SHOE_OFFSET_Y_BY_ITEM` change - a foot item drawn lower stretches the
#: legs further - and is not modelled here yet: this is the bare-footed
#: standing case only.
LEG_TEXTURE = "player_extraleg.rttex"
LEG_ROW_CELL = (16, 1)
LEG_ROW_OFFSET = (8, 28)

#: Hat and hair cells are drawn half a cell above the body cell. Proven in the
#: accessory pass ``sub_140272AA0`` @ 0x140272AA0, called for the hair and hat
#: slots (call sites 0x1402636E4 / 0x140263748); its y (``xmm6`` = arg2,
#: saved at 0x140272ABE) takes a chain of per-item-class adjustments:
#:
#: * class 12 / 17 -> ``y += 16 * renderer[+0x4C]`` - the half-tile lift,
#:   ``kHalfTile_16p0`` @ 0x140272C92, ``mulss``/``addss`` @ 0x140272CAB /
#:   0x140272CB0 (``renderer[+0x4C]`` is the avatar scale set in
#:   renderClothes @ 0x1402616F8);
#: * class 0x2F / 0x30 -> ``y += renderer[+0x4C] * flt_1408BB49C``
#:   @ 0x140272CC2;
#: * one predicate branch instead removes ``renderer[+0x4C] *
#:   dword_1408BE098`` (3.0) @ 0x140272B24-0x140272B2F.
#:
#: Net top-left offset for the plain case: ``body + (0, -16)`` - an alignment
#: measured across the hair (267 px) and hat (176 px) cells in the reference
#: render: zero mismatching pixels (see docs, "Verification").
ACCESSORY_OFFSET_Y = -16

#: Shoes cells sit on the body cell by default: top-left ``body + (0, 0)``.
#: Chain, per foot: ``renderClothes`` calls the feet drawer
#: ``sub_1402789A0`` @ 0x1402789A0 (call site 0x14026286C) with the same base
#: it gives every other part, the drawer applies its own per-item x/y
#: adjustments (e.g. the ``kHalfTile_16p0`` / ``flt_1408BE09C`` terms @
#: 0x14027B0E5 / 0x14027B113), and the per-foot blitter ``sub_14027E7B0``
#: @ 0x14027E7B0 then
#:
#: * builds the frame row as ``2*item[+0x61] + flip`` - ``movzx
#:   ecx,[rax+61h]`` / ``lea edi,[rax+rcx*2]`` @ 0x14027E82D-0x14027E841,
#: * shifts the position by ``-2 * renderer[+0x4C]`` @ 0x14027E7EB,
#: * and draws with ``align 2`` (bottom centre) @ 0x14027E9C1.
#:
#: Net y offset for the plain case: 0. Measured against a reference render of
#: an ordinary shoe (item 40, art at cell rows 29..31): IoU 0.9964 at 0 vs
#: 0.9512 at 12 (docs, "Verification").
SHOE_OFFSET_Y = 0

#: Arm anchors, ``align 5`` (top centre), cell 6x10, y = ``base_y - 14``
#: = 18 for every arm. Which x depends on which *side* the arm hangs on, and
#: the drawer's ``flip`` argument is exactly that side selector:
#:
#:     pos.x = x + (8 - 16*flip) * sx        sub_1402671F0
#:     scale = (1 - 2*flip) * sx            ; flip=1 also mirrors the art
#:
#: With the shared base x = 16 and the align-5 pivot (w/2 = 3):
#:
#: * flip = 1 -> pos.x = 8  -> top-left 5  = the **near/front** arm, which
#:   hangs on the avatar's *left* while it faces right;
#: * flip = 0 -> pos.x = 24 -> top-left 21 = the **far/behind** arm.
#:
#: The client draws both: ``renderClothes`` calls the drawer at 0x1402625F3
#: (before the body's own call at 0x14026260C, so that arm is *behind* the
#: body) and again at 0x140263907 (after the clothing block, so *in front*).
#: The flip byte reaches the drawer as stack arg 7 (``movzx r15d,[rsp+71h]`` /
#: ``mov [rsp+38h],r15b`` @ 0x1402625B1 / 0x1402625C5).
#:
#: Colours: the far arm sits behind the body cell and is normally invisible -
#: a reference render is byte-identical with and without it.
ARM_OFFSET = (5, 18)
ARM_BACK_OFFSET = (21, 18)

#: Per-item feet lift, taken from the leg-offset switch in the per-foot blitter
#: ``sub_14027E7B0`` @ 0x14027E7B0. Its ``v128`` holds the *leg* offset and the
#: cell's y is shifted by ``-v128`` (``subss``/``mulss`` @ 0x14027E7EB region):
#:
#:     v128 = 0                       ; default            -> lift 0
#:     v128 = avatar[7576] - 2        ; shoe/effect class  -> lift +2
#:     v128 = avatar[7576] - 3        ; B740/B7C0/rideable -> lift +3
#:     switch (item) { 0xC9E:+2  0x8A8:-10  0xA0E:-6  0x137E:-2  0x1EEE:+2 }
#:
#: ``avatar[7576]`` is the walk bob, 0 for a still avatar, so the switch cases
#: land at ``-2 + delta``: 3230 -> 0, 2216 -> -12, 2574 -> -8, 4990 -> -4,
#: 7918 -> 0. Classes come from the id predicates the same block calls:
#: ``sub_14053C450`` (hard-coded id list -> lift 2), ``sub_14053C770``
#: (rides: 4822/4824/4826/4828 + fishing dinghy &c -> lift 3),
#: ``sub_14053B740`` (2048/2064/3788/9134 -> lift 3), ``sub_14053BB60``
#: (1740/9648 -> lift 3), ``(id-8898) & 0xFFFFFFF9 == 0`` (8898/8899/8904/8905
#: -> lift 3), ``sub_14053BC50`` (2974 -> lift 0).
#:
#: Measured checks: plain shoes (40/42/78/80/154/250) land at 0 (IoU 0.9964 at
#: 0 vs 0.9512 at 12) and ``2216`` Edvoid's Fire-Nado at 12 (IoU 0.9975 at 12 vs
#: 0.8249 at 0) - both agree with the switch, which is why this table is derived
#: from it rather than fitted. Items in the ``sub_14053B7C0`` list (a long
#: hard-coded rideable list) are not transcribed yet and fall through to 0.
SHOE_OFFSET_Y_BY_ITEM: dict[int, int] = {
    3230: 0,
    7918: 0,
    4990: 4,
    2574: 8,
    2216: 12,
}

#: Frame size of an item's own sheet. ``loadTilesheet`` @ 0x14056DC20 sizes the
#: surface every clothing drawer then slices (the drawers all fetch it through
#: ``sub_14056DB70`` @ 0x14056DB70 and pass only ``frameX``/``frameY`` on to
#: ``renderSprite``, so the cell size is *not* a per-drawer constant)::
#:
#:     14056de28  mov     eax, [rbp+64h]     ; item->texture_type
#:     14056de2b  dec     eax
#:     14056de2d  cmp     eax, 9
#:     14056de30  ja      loc_14056DE80      ; SINGLE_FRAME_ALONE: keep the default
#:     14056de32  mov     eax, 139Ch         ; item 5020
#:     14056de37  cmp     di, ax
#:     14056de3a  jz      loc_14056DE69
#:     14056de3c  mov     eax, 2072h         ; item 8306
#:     14056de41  cmp     di, ax
#:     14056de44  jz      loc_14056DE69
#:     14056de51  test    byte ptr [rbp+76h], 1
#:     14056de55  jz      loc_14056DE62      ; flags2 bit 16 clear
#:     14056de57  mov     edx, 40h           ; 64
#:     14056de5c  lea     r8d, [rdx-20h]     ; 32
#:     14056de62  mov     edx, 20h           ; 32
#:     14056de69  / 14056de74             mov edx, 40h           ; 64 (both 64x64)
#:     14056de7c  call    qword ptr [rax+50h]    ; surface->SetFrameSize(w=edx, h=r8d)
#:
#: ``byte ptr [rbp+76h]`` bit 0 is bit 16 of the dword at +0x74, i.e.
#: ``ItemInfoFlag2.LONG_HAND_ITEM64x32`` (the flag's name states the 64x32
#: grid). Verified against the data: ``player_longhanditem3.rttex`` (512x512)
#: cell (0, 3) holds only 40 opaque pixels in 32x32 but 336 in 64x32 - the
#: whole Ice Dragon Scythe blade - so the 64-wide read is the real one.
ITEM_FRAME_SIZE_OVERRIDES: dict[int, tuple[int, int]] = {
    0x139C: (64, 64),
    0x2072: (64, 64),
}


def item_frame_size(item) -> tuple[int, int]:
    """Pixel size of one frame of ``item``'s sheet (see above).

    ``SINGLE_FRAME_ALONE`` items are not covered by the binary rule above: the
    loader leaves those surfaces at their default frame size, which is the
    single 32x32 cell every avatar sheet this renderer draws is built from.
    """

    override = ITEM_FRAME_SIZE_OVERRIDES.get(item.id)
    if override is not None:
        return override
    if int(item.flags2) & int(ItemInfoFlag2.LONG_HAND_ITEM64x32):
        return (2 * AVATAR_TILE, AVATAR_TILE)
    return (AVATAR_TILE, AVATAR_TILE)


@dataclass(frozen=True, slots=True)
class Sprite:
    """One static sprite of the avatar body."""

    name: str
    texture: str
    offset: tuple[int, int] = (0, 0)
    cell: tuple[int, int] = BODY_CELL
    frame: tuple[int, int] = (0, 0)
    tint: Tint = "skin"
    #: Mirror the cell's art with the *opposite* sign of the body's facing.
    #: True for the arm: the drawer mirrors it through ``scale = (1 - 2*flip)``
    #: while the caller mirrors every other cell by hand, so the arm's texture
    #: is mirrored exactly when the body is not.
    mirror_invert: bool = False


#: Body sprites, with the draw call each anchor comes from.
#:
#: * body   - sub_14026B240 @ 0x14026B240: pos = (x, y), align 2 -> (0, 0).
#:            Frame X is built from the clothing slots: ``shirt?1:0`` +
#:            ``pants?2:0`` (``Clothes+2``/``Clothes+4``); frame Y is 0 unless
#:            the player wears one of the hard-coded "alternate body" items.
#: * eye layers - sub_14026D0F0 @ 0x14026D0F0: three eye/face cells plus the
#:            mouth, all at ``base + (sx*player[7568], sy*player[7572])`` with
#:            align 2, i.e. aligned with the body cell. player[7568]/[7572]
#:            are per-frame animation offsets, so 0 here.
#: * arm    - sub_1402671F0 @ 0x1402671F0 (see ARM_OFFSET).
BODY_LAYERS: tuple[Sprite, ...] = (
    Sprite("body", BODY_TEXTURE),
    Sprite("expr_eyes", EYES_TEXTURE, tint="eye"),
    Sprite("expr_face", FACE_TEXTURE, tint="face"),
    Sprite("expr_eyes2", EYES2_TEXTURE, tint="lens"),
    # Expression state n uses frame (n % 8, n / 8); the mouth is the face
    # texture one cell-row further down. sub_14026D0F0 passes ``a4`` for it,
    # which renderClothes feeds from ``AvatarRenderer[+0x28]`` - the skin
    # colour, so the grey mouth mask is multiplied into a skin-toned mouth.
    Sprite("expr_mouth", FACE_TEXTURE, frame=(0, 4)),
    # The arm atlas is greyscale (8x16 px, one 6x10 cell), so it is tinted with
    # the skin colour like the body tile. Two draws, as the client does them:
    # the far arm first (behind the body) and the near arm last (in front).
    Sprite(
        "arm_back",
        ARM_TEXTURE,
        offset=ARM_BACK_OFFSET,
        cell=ARM_CELL,
        tint="skin",
        mirror_invert=True,
    ),
    Sprite("arm", ARM_TEXTURE, offset=ARM_OFFSET, cell=ARM_CELL, tint="skin", mirror_invert=True),
)

#: Clothing slots -> where their 32x32 item cell lands. Slot order is the
#: client's clothes struct (10 uint16 at NetAvatar+0x288C): hair, shirt, pants,
#: shoes, face, hand, back, hat, neck, artifacts.
#:
#: Proven: shirt/pants (sub_1402760A0 @ 0x1402760A0, pos = base, align 2),
#: shoes (sub_1402789A0 @ 0x1402789A0, pos = base - item offset, align 2),
#: hat (0x140272AA0) and hair (0x140273210). The remaining slots keep the
#: body-cell anchor; they are drawn by functions not yet decompiled.
#: Slots whose cell art is mirrored the other way round from the body
#: (``Sprite.mirror_invert`` for the body layers). The hand item is drawn by the
#: arm drawer, which mirrors with a negative ``scale``.
#: Draw-order names for the second copy of a ``BOTHARMS`` hand item (see
#: :data:`BOTHARMS`) and of a ``FOREGROUND`` back item (see
#: :data:`BACK_PAIR_OFFSET`), and the ``Clothing`` field each renders.
HAND_BACK_LAYER = "hand_back"
BACK_FRONT_LAYER = "back_front"
LAYER_SLOT: dict[str, str] = {HAND_BACK_LAYER: "hand", BACK_FRONT_LAYER: "back"}

#: Slots whose cell art is mirrored the *opposite* way round from the body.
#: Empty: every blit in the arm drawer passes ``flipX = r12b``, the drawer's own
#: argument 7 (``movzx r12d, [rbp+0A0h+arg_38]`` @ ``0x140267683``), and pushes
#: that same byte as ``renderSprite``'s flipX at every one of its nine call
#: sites - including the hand-item blit at ``0x140268b36``
#: (``mov [rsp+1A0h+var_150], r12b``). So the hand item mirrors exactly like the
#: body: the drawer's extra ``(1 - 2*flip)`` factor only reaches ``scale``, which
#: flips the quad's texel order, not which side of the avatar the cell lands on.
CLOTHING_MIRROR_INVERT: frozenset[str] = frozenset()


#: ``ItemInfoVisualEffect`` is the byte at **item+0x58** - the field right after
#: ``texture_file_hash`` in the dat stream (``deserializeItemDatabase`` writes it
#: from ``a1+0x58`` to the item as a single byte @ ``0x14053CAE6``-``0x14053CB04``,
#: and every drawer reads it back as ``cmp dword ptr [item+58h], imm``). It is
#: the *per-item* switch behind most of the avatar's special cases, so these
#: tables are keyed by it rather than by item id.
#:
#: Face item y, ``sub_14026DA80`` @ ``0x14026DA80`` - the face-slot drawer. It
#: offsets y by ``-16 * scale`` for the two high-face effects:
#:
#:     14026dd2e  lea     eax, [rcx-17h]          ; visual_effect - 23
#:     14026dd31  cmp     eax, 1                  ; 23 (HIGHFACE) or 24 (HIGHFACE_ANIM)
#:     14026dd3c  mulss   xmm0, cs:kHalfTile_16p0 ; 16.0
#:     14026dd44  subss   xmm6, xmm0              ; pos.y -= 16 * scale
#:
#: 117 face items use it, so a still face is regularly half a cell higher than
#: the body cell anchor. Everything else in that slot sits at ``(0, 0)``.
FACE_OFFSET_Y = 0
FACE_OFFSET_Y_BY_EFFECT: dict[ItemInfoVisualEffect, int] = {
    ItemInfoVisualEffect.HIGHFACE: -16,
    ItemInfoVisualEffect.HIGHFACE_ANIM: -16,
}

#: Hair/hat/back item y, ``sub_140272AA0`` @ ``0x140272AA0`` (the accessory pass)
#: - the same drawer whose half-tile lift gives :data:`ACCESSORY_OFFSET_Y`. On
#: top of that ``-16 * scale`` it *adds back* pixels per visual effect:
#:
#:     140272c8e  movsxd  rcx, [item+58h]        ; visual_effect
#:     if (ve == 12 || ve == 17) y += scale * 16.0   ; LOWHAIR, LOWHAIR_MASK
#:     if (ve - 47 <= 1)          y += scale * 10.0   ; VERYLOWHAIR, VERYLOWHAIR_MASK
#:
#: So low hair sits on the forehead (net 0) and very-low hair 6 px above the
#: plain anchor (net -6). 90 hair items use these four values.
ACCESSORY_OFFSET_Y_BY_EFFECT: dict[ItemInfoVisualEffect, int] = {
    ItemInfoVisualEffect.LOWHAIR: 16,
    ItemInfoVisualEffect.LOWHAIR_MASK: 16,
    ItemInfoVisualEffect.VERYLOWHAIR: 10,
    ItemInfoVisualEffect.VERYLOWHAIR_MASK: 10,
}

#: Visual effects with a still-visible *tint* rather than a position.
#: ``SKINTINT`` makes the face drawer take the skin colour
#: (``cmp ecx, 0Eh`` / ``mov r12d, [r14+28h]`` @ ``0x14026DD4E``-``0x14026DD53``),
#: and ``NO_RENDER`` skips the sprite entirely (``cmp r12d, 1Ch`` @
#: ``0x14026DB6F`` jumps to the function's exit).
SKINTINT = ItemInfoVisualEffect.SKINTINT
NO_RENDER = ItemInfoVisualEffect.NO_RENDER

#: Effects that make a sprite animate its frame on a timer, so a still frame uses
#: the base cell: ``ANIM``, ``PET_ANIM``, ``ANIM_MASK`` and ``HIGHFACE_ANIM``
#: toggle ``frameX`` with ``(gameTick / 100) & 1`` in the face and clothing
#: drawers (``mul 51EB851Fh`` / ``shr 6`` @ ``0x14026DC8C``, ``0x1402763CE``) and
#: with ``(gameTick / 200) & 1`` in the accessory pass (bitmask ``0x10090`` @
#: ``0x140272C9B``).
#: Back items the behind pass refuses to draw at all: ``sub_140268BC0``
#: returns on its third statement (``140268c05  mov     ecx, [rbp+1B0h+arg_20]`` /
#: ``140268c0b  call    sub_14053BBA0`` / ``140268c10  test    al, al`` /
#: ``140268c12  jnz     loc_140268D8C`` -> the function's exit) when
#: ``sub_14053BBA0(item)`` is true::
#:
#:     sub_14053BBA0 @ 0x14053BBA0
#:     return id == 2722 || id == 3114
#:         || ((id - 4970) <= 0x32 && _bittest64(&0x4000000000005, id - 4970))
#:         || id == 6284 || id == 8026 || id == 8024;
#:
#: i.e. 2722, 3114, 4970, 4972, 5020, 6284, 8026 and 8024. The items are drawn
#: by a *different* system (they are the chairs/pets the avatar sits on or holds),
#: so nothing is missing from the avatar render - the pixels come from that other
#: drawer. Both the behind and the front pass must skip them.
BACK_HIDDEN_IDS: frozenset[int] = frozenset({2722, 3114, 4970, 4972, 5020, 6284, 8026, 8024})

#: Back items with no front overlay even when they carry ``ItemFlag.FOREGROUND``:
#: the front pass skips item 9088 outright - ``sub_140271FA0`` @ 0x140271FA0:
#:
#:     140271fbc  cmp     [rbp+1B0h+arg_18], 2380h    ; 9088
#:     140271fc4  jz      loc_14027242C              ; -> jump to the exit
#:
#: so 9088 is a behind-pass-only item. (It *is* in the behind pass's pair switch
#: at 0x140268BC0 - ``case 0x2380``.)
BACK_FRONT_SKIP_IDS: frozenset[int] = frozenset({9088})

#: ``OFFHAND`` on a **hand** item: the same item is wielded in the other hand as
#: well. In the arm drawer ``sub_1402671F0`` (branch ``cmp dword ptr
#: [r33+58h], 1Eh`` -> ``140267579: cmp     dword ptr [rbx+58h], 1Eh``) the
#: second copy is blitted at its own anchor:
#:
#:     14026762e  movss   xmm0, [r13+48h]           ; scale
#:     1402676xx  mulss/movss                       ; 7*scale, 14*scale*flip
#:     x = base_x + 7*scale - 14*scale*flip          ; the mirrored arm line
#:     y = base_y - 20*scale
#:     align = 5 (top centre), flip = arg7, angle = (1 - 2*flip)*handSwing
#:     frameX = tex_coord_x + (sub_14053BFB0(id) || id == 6382 ? 2 : 1)
#:
#: and ``sub_14053BFB0`` @ 0x14053BFB0 is ``(id - 6866) <= 12``, i.e. the ids
#: 6866..6878 sit one cell further right (their off-hand art is two cells along).
#: With the shared base ((16, 32) in body-cell pixels) and the align-5 pivot on a
#: 32 px cell (w/2 = 16) the facing-right copy lands at ``(-7, 12)``: the same
#: relation ``hand``'s ``(-8, 18)`` has to ``8 - 16*flip`` and ``-14*scale``.
OFFHAND = ItemInfoVisualEffect.OFFHAND
OFFHAND_OFFSET = (-7, 12)
OFFHAND_FRAME_OFFSET = 1
OFFHAND_FRAME_OFFSET_2_IDS: frozenset[int] = frozenset(range(6866, 6879)) | {6382}

#: ``PULSE`` and ``LIGHTSOURCE_PULSE`` add a companion cell one column to the
#: right of the item's own cell, drawn *on top of it* at the same anchor. Three
#: drawers do it and no other does (the back, arm, feet, pants, hair/hat and body
#: drawers have no such branch - ``grep "== 19"`` over their decompilations):
#:
#: * shirt ``sub_140277C40`` @ 0x140277C40: ``if (v36 == 19 || v36 == 45)``
#:   then ``renderSprite(..., v44 + 1, v43, ...)`` - frameX + 1, same pos,
#:   align 2;
#: * neck ``sub_14026BC30`` @ 0x14026BC30: ``if ((_DWORD)v8 == 19 || (_DWORD)v8
#:   == 45) sub_140277640(...)`` with ``v66 = tex_coord_x + 1``;
#: * face ``sub_14026DA80`` @ 0x14026DA80: ``if (v41 == 19 || v41 == 45)`` then
#:   ``renderSprite(..., v48 + 1, v47, ...)``.
#:
#: The overlay's tint keeps the item's own RGB but replaces the alpha with the
#: pulse: ``sub_140277640`` @ 0x140277640 builds ``((byte1 + ((byte2 + (c >> 24
#: << 8)) << 8)) << 8) - (int)((float)((float)(v18 + 1.0) * 0.5) * -255.0)``,
#: i.e. alpha = ``(sin + 1) / 2 * 255`` for a sine with the item's own period
#: (``item+0x10C``, 2500 when 0).
#:
#: ``sub_1400E4860`` @ 0x1400E4860 is ``sinf(2 * pi * (a2 % a1) / a1)``, and
#: ``sub_140277640`` @ 0x140277640 calls it with ``a1 = frame_interval_ms``
#: (2500 default) and ``a2 = frame_interval_ms / 10 + Tick + 10 * (frame_interval_ms
#: / 13)``. For a still frame (Tick = 0) this gives a fixed phase per item, so
#: the pulse alpha is deterministic and item-specific.
PULSE = ItemInfoVisualEffect.PULSE
PULSE_2 = ItemInfoVisualEffect.LIGHTSOURCE_PULSE
PULSE_COMPANION_SLOTS: frozenset[str] = frozenset({"shirt", "neck", "face"})


def pulse_alpha(frame_interval_ms: int, tick: int = 0) -> int:
    """Pulse overlay alpha at the given tick, reverse-engineered from
    ``sub_140277640`` @ 0x140277640 and ``sub_1400E4860`` @ 0x1400E4860.

    The client computes ``v18 = sinf(2 * pi * (tick % period) / period)`` where
    ``period = frame_interval_ms`` and ``tick = period / 10 + Tick + 10 * (period
    / 13)``, then sets alpha = ``(int)((v18 + 1.0) * 0.5 * 255.0)`` - a value in
    [0, 255] that replaces the sprite's alpha channel entirely.
    """
    if frame_interval_ms <= 0:
        period = 2500
    else:
        period = frame_interval_ms
    phase_tick = period // 10 + tick + 10 * (period // 13)
    v18 = math.sin(2.0 * math.pi * (phase_tick % period) / period)
    return int((v18 + 1.0) * 0.5 * 255.0)



#: Visual effects that toggle ``frameX`` on a timer (see below).
ANIM = ItemInfoVisualEffect.ANIM
PET_ANIM = ItemInfoVisualEffect.PET_ANIM
COLORIZE_ANIM = ItemInfoVisualEffect.COLORIZE_ANIM
HIGHFACE_ANIM = ItemInfoVisualEffect.HIGHFACE_ANIM

#: Effects whose frameX advances on a timer. ANIM/PET_ANIM toggle
#: frameX every 200 ms in every drawer (the shirt drawer at
#: ``sub_140277C40`` uses ``(gameTick / 0xC8) & 1`` = ``(tick // 200) & 1``;
#: the accessory pass uses ``(tick // 200) & 1`` per the bitmask at
#: ``0x140272C9B``). COLORIZE_ANIM and HIGHFACE_ANIM share the same
#: toggle behaviour on top of their dye/high-face rules.
ANIM_EFFECTS: frozenset[ItemInfoVisualEffect] = frozenset({ANIM, PET_ANIM, COLORIZE_ANIM, HIGHFACE_ANIM})


def anim_frame_offset(effect: ItemInfoVisualEffect, tick: int) -> int:
    """Frame-X offset from the animation timer.

    ANIM/PET_ANIM/COLORIZE_ANIM/HIGHFACE_ANIM toggle ``frameX`` with
    ``(tick // 200) & 1``. Returns 0 for non-animating effects.
    """
    if effect not in ANIM_EFFECTS:
        return 0
    return (tick // 200) & 1


def parse_animating_coordinates(coords: bytes) -> list[tuple[int, int]]:
    """Parse an ``animating_coordinates`` string like ``b'0,0|1,0|0,1|1,0|'``
    into a list of ``(frameX, frameY)`` pairs.
    """
    if not coords:
        return []
    result: list[tuple[int, int]] = []
    for pair in coords.split(b"|"):
        pair = pair.strip()
        if not pair:
            continue
        try:
            x, y = pair.split(b",")
            result.append((int(x), int(y)))
        except ValueError:
            continue
    return result


def animating_frame(item, tick: int) -> tuple[int, int] | None:
    """Return the animated ``(frameX, frameY)`` for an item whose
    ``animating_coordinates`` string is set, or ``None`` if the item doesn't
    use this mechanism.

    The frame index advances every ``frame_interval_ms`` milliseconds
    (100 ms default when unset).
    """
    if not item.animating_coordinates:
        return None
    coords = parse_animating_coordinates(item.animating_coordinates)
    if not coords:
        return None
    period = item.frame_interval_ms if item.frame_interval_ms > 0 else 100
    frame_index = (tick // period) % len(coords)
    return coords[frame_index]


#: Neck item y, ``sub_14026BC30`` @ ``0x14026BC30`` - the neck drawer. Besides the
#: Neck item y, ``sub_14026BC30`` @ 0x14026BC30 - the neck drawer. Besides the
#: item's own cell it takes the same high-face lift the face slot has:
#:
#:     14026c1xx  mov     v32, [r21+58h]      ; visual_effect
#:     14026c1xx  lea     eax, [rcx-17h]      ; effect - 23
#:     14026c1xx  cmp     eax, 1              ; HIGHFACE (23) / HIGHFACE_ANIM (24)
#:     14026c1xx  mulss   xmm0, kHalfTile_16p0
#:     14026c1xx  subss   xmm6, xmm0          ; y -= 16 * scale
#:
#: so the two high-face effects lift the neck cell exactly like the face cell
#: (see :data:`FACE_OFFSET_Y_BY_EFFECT`).
NECK_OFFSET_Y = 0
NECK_OFFSET_Y_BY_EFFECT: dict[ItemInfoVisualEffect, int] = {
    ItemInfoVisualEffect.HIGHFACE: -16,
    ItemInfoVisualEffect.HIGHFACE_ANIM: -16,
}

ANIMATED_EFFECTS: frozenset[ItemInfoVisualEffect] = frozenset(
    {
        ItemInfoVisualEffect.ANIM,
        ItemInfoVisualEffect.PET_ANIM,
        ItemInfoVisualEffect.ANIM_MASK,
        ItemInfoVisualEffect.HIGHFACE_ANIM,
    }
)

#: Hair effects that are *masks*: the face slot is then drawn **after** the hair
#: instead of before it. ``renderClothes`` @ ``0x140263020``-``0x140263060``:
#:
#:     v177 = (visual_effect(hair) - 15) <= 2   ; MASK, ANIM_MASK, LOWHAIR_MASK
#:     if (v177 == 1) sub_14026DA80(face)       ; face after hair, before the hat
#:     else           sub_14026DA80(face)       ; face before the hair
#:
#: and ``UNDERFACE`` short-circuits to ``v177 = -1``, which skips every one of
#: those face calls and takes the *other* path in ``renderClothes``: the three
#: ``sub_14026DA80`` calls that sit right after ``sub_14026B240`` (the body
#: drawer), i.e. the face item is blitted **before the body cell** instead of
#: over it. 15 face items use it.
MASK_EFFECTS: frozenset[ItemInfoVisualEffect] = frozenset(
    {
        ItemInfoVisualEffect.MASK,
        ItemInfoVisualEffect.ANIM_MASK,
        ItemInfoVisualEffect.LOWHAIR_MASK,
    }
)
UNDERFACE = ItemInfoVisualEffect.UNDERFACE

#: ``NO_ARMS`` on the **shirt** hides both arms and the hand item. In
#: ``renderClothes`` the shirt item is the one whose effect is compared:
#:
#:     v104 = clothes[1]                                  ; shirt
#:     v258 = v105 && [v105+58h] == 8                     ; NO_ARMS
#:     if (sub_14025EA50(..., v258, ...)) sub_1402671F0(...)  ; arm pass
#:
#: @ ``0x1402625xx``: the predicate short-circuits to false, so the arm drawer -
#: which also draws the hand item - never runs. 22 shirts use it.
NO_ARMS = ItemInfoVisualEffect.NO_ARMS

#: ``BOTHARMS`` on a **hand** item: the same hand item goes on both arms. In the
#: arm drawer ``sub_1402671F0`` the near hand is blitted first and the item is
#: blitted a *second* time right after it when its effect byte is 0x0B:
#:
#:     1402686cd  cmp     dword ptr [rsi+58h], 0Bh     ; BOTHARMS
#:     1402686d1  jnz     loc_14026882B
#:     1402686d7  call    sub_1400F6BA0 / sub_14056DB70 ; resolve the item again
#:     140268731  mov     r8d, edi   ; frameX = item.tex_coord_x  (no +r13 pose)
#:     1402687ee  mov     [rsp+var_170], 5          ; the arm's align again
#:     140268805  jmp     loc_140267C9F              ; the shared blit
#:
#: so the second copy is the same cell of the same item, drawn through the arm
#: blit (align 5, ``scale = (1 - 2*flip)``, the same float argument as the near
#: hand). Its x is built like the near hand's - ``base + sx*C1 - sx*C2*flip`` -
#: with the two constants in :data:`HAND_BACK_OFFSET`'s frame instead of the
#: near arm's ``8 - 16*flip``, i.e. the mirrored arm. The two constants sit in
#: the data section (``dword_1408B8FBC`` / ``xmm15``) and their values were not
#: read out of the database; the anchor below is the near hand's entry mirrored
#: about the 32 px body cell, which is the same relation ``8 - 16*flip`` has.
#: 29 hand items carry it (and 4 neck items, where it duplicates the neck in
#: front of the body).
BOTHARMS = ItemInfoVisualEffect.BOTHARMS




def accessory_offset_y(effect: ItemInfoVisualEffect) -> int:
    """Top-left y of a hair/hat/back cell, in body-cell pixels."""

    return ACCESSORY_OFFSET_Y + ACCESSORY_OFFSET_Y_BY_EFFECT.get(effect, 0)


def face_offset_y(effect: ItemInfoVisualEffect) -> int:
    """Top-left y of a face item cell, in body-cell pixels."""

    return FACE_OFFSET_Y + FACE_OFFSET_Y_BY_EFFECT.get(effect, 0)


def neck_offset_y(effect: ItemInfoVisualEffect) -> int:
    """Top-left y of a neck item cell, in body-cell pixels."""

    return NECK_OFFSET_Y + NECK_OFFSET_Y_BY_EFFECT.get(effect, 0)


CLOTHING_OFFSETS: dict[str, tuple[int, int]] = {
    "hair": (0, ACCESSORY_OFFSET_Y),
    "shirt": (0, 0),
    "pants": (0, 0),
    "shoes": (0, SHOE_OFFSET_Y),
    # shoes take their own per-item anchor, see SHOE_OFFSET_Y_BY_ITEM
    "face": (0, 0),
    # Hand items are drawn *by the arm drawer* (sub_1402671F0), not as a
    # body-cell tile: align 5 with the arm's own position, so the top-left is
    # ``base + (8 - 16*flip) - cellW/2, base_y - 14``. Their cells are 32 px
    # wide, giving (-8, 18) facing right and (8, 18) mirrored. Measured: at
    # (0, 0) a boxing glove lands on the avatar's face (52 px on the nose).
    "hand": (-8, 18),
    # The BOTHARMS second copy: the drawer's own anchor for it,
    # ``pos.x = base_x + (8 - 16*flip)*sx`` (``dword_1408B8FBC`` = 8.0 @
    # 0x14026873b/0x140268751-0x14026878b), which is the near hand anchor
    # mirrored about the 32 px body cell: 32 - (-8) - 32 = 8. Drawn in the same
    # pass as the near hand, i.e. on top of the body, not behind it.
    "hand_back": (8, 18),
    # The back slot is *not* an accessory: the default path of the behind pass
    # ``sub_140268BC0`` blits at ``pos = (a2, a3)`` - the same base every drawer
    # is handed - with align 2, so the cell lands exactly on the body cell.
    # (The half-tile lift belongs to the hair/hat pass ``sub_140272AA0``.)
    "back": (0, 0),
    # The FOREGROUND back overlay: the front pass ``sub_140271FA0`` blits cell
    # ``tex_coord_x + 1`` at that same base (``lea r8d, [rdi+1]`` @
    # 0x14027231d, pos pushed from xmm10/xmm9 @ 0x1402722c7-0x1402722cd).
    "back_front": (0, 0),
    "hat": (0, ACCESSORY_OFFSET_Y),
    "neck": (0, 0),
    "artifacts": (0, 0),
}

#: Back items drawn as a left/right **pair** by the behind pass
#: ``sub_140268BC0``: instead of one sprite at the body anchor it blits two, the
#: right one mirrored (``flipX = 1``). Value = the x distance of each copy from
#: the body centre, straight out of the switch cases:
#:
#: * ``0x11B6``/``0x21AC``/``0x229E``/``0x24B2`` (4534, 8620, 8862, 9394):
#:   ``x = a2 - 20*sx`` then ``x = (a2 - 20*sx) + 40*sx``, align 2;
#: * ``0x23D4``/``0x23DE`` (9172, 9182): same shape with 16;
#: * ``0x206E``/``0x2074``/``0x20AE`` (8302, 8308, 8366): same shape with 20;
#: * ``0x6F8``/``0x205E``/``0x1E9A``/``0x1E36``/``0x24CE`` (1784, 8286, 7834,
#:   7734, 9422): ``x = a2 - 7*sx`` align 8 then ``x = a2 + 7*sx`` align 6 with
#:   ``flipX = 1`` - align 8 pivots on the cell's right-centre and align 6 on its
#:   left-centre, so the two cells still sit 14 px apart, 16 px above the base
#:   row (``y = a3 - 16*sy``).
#:
#: Items the switch draws in other, animated ways (820/1934/7670 sine pairs,
#: 8552, 1958 and 9088) keep the single body-anchor cell.
#:
#: Value = ``(left, right, y)`` - the two cells' top-left x and y in body-cell
#: pixels, converted from the calls above with the body base at (16, 32): the
#: align 2 groups put the left cell at ``(a2 - 20) - 16`` and the right at
#: ``(a2 + 20) - 16``, and the align 8/6 group at ``(a2 - 7) - 32`` / ``a2 + 7``.
#: The right cell is blitted with ``flipX = 1``.
BACK_PAIR_OFFSET: dict[int, tuple[int, int, int]] = {
    4534: (-20, 20, 0),
    8620: (-20, 20, 0),
    8862: (-20, 20, 0),
    9394: (-20, 20, 0),
    8302: (-20, 20, 0),
    8308: (-20, 20, 0),
    8366: (-20, 20, 0),
    9182: (-16, 16, 0),
    # 9172 (0x23D4) takes the same shape with ``y = a3 - 6*sy``.
    9172: (-16, 16, -6),
    1784: (-23, 23, 0),
    8286: (-23, 23, 0),
    7834: (-23, 23, 0),
    7734: (-23, 23, 0),
    9422: (-23, 23, 0),
}

#: Painter's order taken from renderClothes @ 0x140261610, sorted by call
#: site: back item (0x1402624AF), neck (0x1402624F6), far arm (0x1402625F3),
#: body (0x14026260C), expression (0x140262686), then the clothing tiles
#: (0x140262836 onward - face, pants, shoes, shirt), the FOREGROUND back
#: overlay right after the shirt (the ``sub_140271FA0`` call), hair
#: (0x1402636E4), hat (0x140263748), neck again (0x140263621), near arm
#: (0x140263907) - and with it the hand item, which is why ``hand_back`` (the
#: BOTHARMS copy) is drawn there too and not behind the body.
#:
#: Note the face *item* comes **after** the expression pass, so shades cover
#: the eyes the client drew underneath. Order matters: with the face item first
#: a reference render shows sunglasses where this renderer drew eyes and mouth
#: on top of them (fixed in this session).
#:
#: The client draws the neck slot twice - once behind the body and once in
#: front of it. Both calls blit the same cell, so the static renderer keeps the
#: front one only and drops the hidden back copy.
DRAW_ORDER: tuple[str, ...] = (
    "arm_back",
    "back",
    "body",
    "expr_eyes",
    "expr_face",
    "expr_eyes2",
    "expr_mouth",
    "face",
    "pants",
    "shoes",
    "shirt",
    "back_front",
    "hair",
    "hat",
    "neck",
    "hand",
    "hand_back",
    "artifacts",
    "arm",
)


def body_frame(shirt: int, pants: int) -> tuple[int, int]:
    """Atlas cell of the body cell: ``shirt?1:0 | pants?2:0``, row 0.

    sub_14026B240 @ 0x14026B240 builds exactly this before the draw:
    both -> 3, shirt only -> 1, pants only -> 2, neither -> 0.
    """

    return ((1 if shirt else 0) | (2 if pants else 0), 0)


def shoe_frames(tex_coord_y: int) -> tuple[int, int]:
    """Atlas rows used by the shoes slot: ``2*ty`` and ``2*ty + 1``.

    sub_1402789A0 draws the item twice, once per foot, and sub_14027E7B0 @
    ``0x14027E7B0`` - the per-foot blitter it calls - builds the frame row as
    ``2*item[+0x61] + flip`` (``movzx ecx,[rax+61h]`` / ``lea edi,[rax+rcx*2]``
    @ ``0x14027E82D``), then ``renderSprite(..., align 2)``. Both rows are
    blitted at the same anchor: the left shoe is painted into the left half of
    the cell and the right shoe into the right half, so the pair composes the
    same 32 px tile as every other clothing slot.

    The blitter selects which of the two rows is used per draw from the flip
    byte, not the facing alone: the flip argument is ``arg_38`` (``cmp
    [rsp+arg_38],al`` / ``setnz al`` @ 0x14027E837), and on top of that the
    frame is shifted by a distance/zoom dependent amount - ``add edi,2`` with a
    frameX shift of ``+1..+3`` for the coarser zoom steps @ 0x14027E861-0x14027E8D9,
    and ``frameX += 2`` (plus one on a mod-3 phase) for the closest one
    @ 0x14027E8DB-0x14027E931. Drawing both rows is what the still render
    matches: a reference render agrees at 99.84% silhouette with both rows and
    drops to 93.4% / 94.1% with either row alone (see docs, "Verification").
    """

    return (2 * tex_coord_y, 2 * tex_coord_y + 1)

