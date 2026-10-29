from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from gtools import setting
from gtools.core.growtopia.items_dat import ItemFlag, ItemInfoVisualEffect, item_database
from gtools.core.growtopia.player import CharacterFlags, Player
from gtools.core.growtopia.rttex import RTTexManager

from gtools.core.growtopia.renderer.layout import (
    BACK_FRONT_LAYER,
    BACK_FRONT_SKIP_IDS,
    BACK_HIDDEN_IDS,
    BACK_PAIR_OFFSET,
    BOTHARMS,
    HAND_BACK_LAYER,
    LAYER_SLOT,
    MASK_EFFECTS,
    NO_ARMS,
    NO_RENDER,
    OFFHAND,
    OFFHAND_FRAME_OFFSET,
    OFFHAND_FRAME_OFFSET_2_IDS,
    OFFHAND_OFFSET,
    PULSE,
    PULSE_2,
    PULSE_COMPANION_SLOTS,
    SKINTINT,
    UNDERFACE,
    AVATAR_TILE,
    BARE_FEET_FRAMES,
    BARE_FEET_TEXTURE,
    BODY_LAYERS,
    CANVAS_ORIGIN,
    CANVAS_SIZE,
    CLOTHING_MIRROR_INVERT,
    CLOTHING_OFFSETS,
    DRAW_ORDER,
    LEG_ROW_CELL,
    LEG_ROW_OFFSET,
    LEG_TEXTURE,
    SHOE_OFFSET_Y_BY_ITEM,
    Sprite,
    Tint,
    accessory_offset_y,
    body_frame,
    face_offset_y,
    item_frame_size,
    neck_offset_y,
    pulse_alpha,
    shoe_frames,
)

#: The two effects that add a companion cell (see ``layout.PULSE``).
PULSE_EFFECTS: frozenset[ItemInfoVisualEffect] = frozenset({PULSE, PULSE_2})

#: Tints the client takes from the avatar rather than from the item data.
#: ``avatar[7184]`` is the eye-white colour; ``avatar[7188]`` the lens colour,
#: which is black on a plain avatar (an unset lens draws nothing, but the
#: eye2 cell it multiplies is the pupil block, so black is what the client
#: ends up showing). ``Player`` has no field for either yet.
EYE_TINT = (255, 255, 255, 255)
LENS_TINT = (0, 0, 0, 255)
FACE_TINT = (255, 255, 255, 255)


@dataclass(slots=True)
class RenderOptions:
    facing: int = 1  # -1 flips the avatar horizontally
    background: tuple[int, int, int, int] | None = None


class PlayerRenderer:
    """Composites the body and clothing of a :class:`Player` into an image."""

    def __init__(self, textures: RTTexManager | None = None, game_path: Path | None = None) -> None:
        self._textures = textures if textures is not None else RTTexManager()
        self._game_path = Path(game_path) if game_path is not None else setting.gt_path / "game"

    def render(self, player: Player, options: RenderOptions | None = None) -> Image.Image:
        opts = options if options is not None else RenderOptions()
        facing = -1 if opts.facing < 0 else 1
        flip = facing < 0

        canvas = Image.new("RGBA", (CANVAS_SIZE, CANVAS_SIZE), (0, 0, 0, 0))
        if opts.background is not None:
            canvas.paste(Image.new("RGBA", canvas.size, opts.background), (0, 0))

        flags = player.state.flags
        if player.invis or flags & CharacterFlags.INVISIBLE:
            return canvas

        tints = self._tint_table(player)
        clothing = player.clothing

        no_arms = self._no_arms(clothing)
        back_overlay = self._is_foreground(clothing.back)
        for name in self._draw_order(clothing):
            if no_arms and name in ("arm", "arm_back", "hand", HAND_BACK_LAYER):
                # A shirt with IVE_NO_ARMS stops the whole arm pass, which is
                # also where the hand item (and its BOTHARMS second copy) is
                # drawn.
                continue
            layer = next((part for part in BODY_LAYERS if part.name == name), None)
            if layer is not None:
                if self._skip_body_layer(layer.name, flags):
                    continue
                frame = layer.frame
                if layer.name == "body":
                    # sub_14026B240 @ 0x14026B240 picks the body cell from the
                    # worn shirt/pants: shirt?1:0 | pants?2:0.
                    frame = body_frame(clothing.shirt, clothing.pants)
                parts = [
                    (
                        self._sprite(layer, frame, tints[layer.tint], flip=flip),
                        layer.offset,
                        layer.cell,
                    )
                ]
            else:
                if self._skip_clothing(name, flags):
                    continue
                if name == BACK_FRONT_LAYER and not back_overlay:
                    # The FOREGROUND back overlay: the front pass
                    # ``sub_140271FA0`` reads bit 13 of the item's flags word
                    # before it blits anything -
                    #
                    #     1402720c7  movzx ecx, word ptr [rsi+72h]
                    #     1402720cb  shr   cx, 0Dh
                    #     1402720cf  test  cl, 1
                    #     1402720d2  jz    loc_14027233A   ; -> return
                    #
                    # so an item without ``ItemFlag.FOREGROUND`` never reaches
                    # the ``tex_coord_x + 1`` blit. Skip before building the
                    # sprite: that cell can be off the sheet (Da Vinci Wings
                    # sits at column 7 of an 8-wide player_back.rttex), which
                    # the client is never asked to draw.
                    continue
                parts = self._clothing_parts(name, getattr(clothing, LAYER_SLOT.get(name, name)), flip=flip, tints=tints)

            for sprite, (x, y), size in parts:
                if sprite is None:
                    continue
                if flip:
                    x = AVATAR_TILE - x - size[0]
                canvas.alpha_composite(sprite, (CANVAS_ORIGIN + x, CANVAS_ORIGIN + y))

        return canvas

    @staticmethod
    def _effect(item_id: int) -> ItemInfoVisualEffect:
        """``ItemInfoVisualEffect`` of a worn item (item+0x58), NONE if empty."""

        if not item_id:
            return ItemInfoVisualEffect.NONE
        try:
            return item_database.get(item_id).visual_effect
        except (KeyError, IndexError):
            return ItemInfoVisualEffect.NONE

    def _draw_order(self, clothing) -> tuple[str, ...]:
        """``DRAW_ORDER`` adjusted for the worn items' visual effects.

        The face item's position in the order follows the same three rules the
        client uses in the hair/hat block of ``renderClothes`` (labels 336 in
        the pseudocode): 1 for mask-type hair, 2 when the *face* item carries
        ``ItemFlag.FOREGROUND`` (``sub_14025F010(face)`` forces it, so the face
        is drawn after the hair), 0 when the *hat* carries it (drawn before),
        and ``UNDERFACE`` -1, before the body entirely (``layout.UNDERFACE``).

        The ``BOTHARMS`` second hand copy is drawn where the arm drawer draws
        it: in the near-arm pass, i.e. on top of the body, right after the
        primary hand - not behind it.
        """

        order = list(DRAW_ORDER)
        face_effect = self._effect(clothing.face)
        if face_effect == UNDERFACE:
            order.remove("face")
            order.insert(order.index("body"), "face")
        elif self._is_foreground(clothing.face) or self._effect(clothing.hair) in MASK_EFFECTS:
            order.remove("face")
            order.insert(order.index("hair") + 1, "face")
        elif self._is_foreground(clothing.hat):
            order.remove("face")
            order.insert(order.index("hat"), "face")
        return tuple(order)

    @staticmethod
    def _is_foreground(item_id: int) -> bool:
        """``ItemFlag.FOREGROUND`` of a worn item (see ``sub_14025F010``).

        ``sub_14025F010`` @ ``0x14025F010`` reads bit 13 of the u16 at
        ``item + 0x72``; ``deserializeItemDatabase`` writes the dat's *second*
        field to that exact offset (``*(uint16_t *)((char *)&item->itemId + v10)
        = *((_WORD *)a1 + 57)`` right after the id), and that field is
        :attr:`ItemFlag` - so this flag is what moves the face sprite in front
        of the hair/hat and what gates the front back-item pass.
        """

        if not item_id:
            return False
        try:
            return bool(int(item_database.get(item_id).flags) & ItemFlag.FOREGROUND)
        except (KeyError, IndexError):
            return False

    @staticmethod
    def _skip_body_layer(name: str, flags: CharacterFlags) -> bool:
        # NO_BODY/NO_HANDS/NO_FACE are CharacterFlags bits sent by the server for
        # ghost-style avatars; the client renderer skips the whole tile for them.
        if name == "body" and flags & CharacterFlags.NO_BODY:
            return True
        if name in ("arm", "arm_back") and flags & CharacterFlags.NO_HANDS:
            return True
        if name.startswith("expr_") and flags & CharacterFlags.NO_FACE:
            return True
        return False

    @staticmethod
    def _skip_clothing(name: str, flags: CharacterFlags) -> bool:
        if name in ("shirt", "pants", "shoes") and flags & CharacterFlags.NO_BODY:
            return True
        if name in ("hand", HAND_BACK_LAYER) and flags & CharacterFlags.NO_HANDS:
            return True
        if name == "face" and flags & CharacterFlags.NO_FACE:
            return True
        return False

    @staticmethod
    def _tint_table(player: Player) -> dict[Tint, np.ndarray | None]:
        """Colour each :data:`Tint` source resolves to for this player."""

        return {
            "none": None,
            "skin": np.array(player.clothing.skin_color.to_tuple(), dtype=np.uint8),
            "eye": np.array(EYE_TINT, dtype=np.uint8),
            "lens": np.array(LENS_TINT, dtype=np.uint8),
            "face": np.array(FACE_TINT, dtype=np.uint8),
        }

    def _sprite(self, layer: Sprite, frame: tuple[int, int], tint: np.ndarray | None, *, flip: bool) -> Image.Image | None:
        # The arm mirror is inverted: the client flips its art with
        # ``scale = (1 - 2*flip)`` while every other cell is mirrored by hand
        # through its anchor, so for a given facing the two disagree.
        return self._tile(
            layer.texture,
            frame,
            layer.cell,
            tint=tint,
            flip=flip != layer.mirror_invert,
        )

    def _clothing_parts(self, name: str, item_id: int, *, flip: bool, tints: dict[Tint, np.ndarray | None]) -> list[tuple[Image.Image, tuple[int, int], tuple[int, int]]]:
        """Tiles contributed by one clothing slot, in draw order."""

        if item_id == 0:
            # An empty feet slot is not bare canvas: the client's feet drawer
            # (sub_1402789A0 @ 0x1402789A0) is still called with item id 0 and
            # blits the default feet pair from player_feet.rttex.
            if name != "shoes":
                return []
            return self._bare_feet(tints["skin"], flip=flip)

        if name == HAND_BACK_LAYER:
            # BOTHARMS second copy: same cell, mirrored anchor (see layout).
            return self._one_cell("hand", item_id, CLOTHING_OFFSETS[HAND_BACK_LAYER], flip=flip) if self._effect(item_id) == BOTHARMS else []

        if name == BACK_FRONT_LAYER:
            # Cell tex_coord_x + 1 of the back item, at the same anchor. Items in
            # BACK_FRONT_SKIP_IDS never reach the front pass (see layout).
            item = item_database.get(item_id)
            if not item.texture_file or self._effect(item_id) == NO_RENDER:
                return []
            if item_id in BACK_FRONT_SKIP_IDS or item_id in BACK_HIDDEN_IDS:
                return []
            if not (int(item.flags) & ItemFlag.FOREGROUND):
                # Gated by the front pass itself (``sub_140271FA0`` reads bit 13
                # of item+0x72 before its ``tex_coord_x + 1`` blit); kept here so
                # every caller of _clothing_parts sees the client's rule, not
                # just the render loop.
                return []
            return self._one_cell("back", item_id, CLOTHING_OFFSETS[BACK_FRONT_LAYER], frame=(item.tex_coord_x + 1, item.tex_coord_y), flip=flip)

        item = item_database.get(item_id)
        if name == "artifacts":
            # The artifacts slot paints nothing. ``renderClothes`` @ 0x140261610
            # reads ``clothes+0`` .. ``clothes+8`` (hat, shirt, pants, shoes,
            # face, hand, back, hair, neck) and never ``clothes+9``, so no blit
            # in the avatar pass can be fed from this slot. The client handles
            # artifact items as *particles* instead: ``0x14010B2B0  cmp dword
            # ptr [rax+4], 6Bh`` (item_type == 107, the field at item+4) picks a
            # particle type id per artifact and calls ``spawnParticleActual``,
            # and the emitter is ``maybeRenderAura`` @ 0x1402605B0. A static
            # renderer has no particle system, so it draws no cell - drawing
            # ``player_artifact.rttex`` here put the Tesseract cube on the body,
            # which the reference render does not do.
            return []
        if not item.texture_file:
            return []
        effect = item.visual_effect
        if effect == NO_RENDER:
            # IVE_NO_RENDER: the drawer returns before it blits anything.
            return []
        if name == "back" and item_id in BACK_HIDDEN_IDS:
            # The behind pass returns before it blits anything for these ids
            # (sub_14053BBA0); they are drawn by another system entirely.
            return []

        if name == "back" and item_id in BACK_PAIR_OFFSET:
            # Left/right pair with the right copy mirrored (see the table).
            left, right, dy = BACK_PAIR_OFFSET[item_id]
            parts = []
            for x, mirror in ((left, False), (right, True)):
                sprite = self._tile(
                    item.texture_file.decode(),
                    (item.tex_coord_x, item.tex_coord_y),
                    (AVATAR_TILE, AVATAR_TILE),
                    tint=None,
                    flip=flip != mirror,
                )
                if sprite is not None:
                    parts.append((sprite, (x, dy), (AVATAR_TILE, AVATAR_TILE)))
            return parts

        frames = [(item.tex_coord_x, item.tex_coord_y)]
        anchor = CLOTHING_OFFSETS[name]
        if name in ("hair", "hat"):
            anchor = (anchor[0], accessory_offset_y(effect))
        elif name == "face":
            anchor = (anchor[0], face_offset_y(effect))
        elif name == "neck":
            anchor = (anchor[0], neck_offset_y(effect))
        elif name == "shoes":
            # One cell per foot, at the same anchor (see layout.shoe_frames),
            # plus the client's per-item lift for large/effect foot items.
            frames = [(item.tex_coord_x, row) for row in shoe_frames(item.tex_coord_y)]
            anchor = (anchor[0], SHOE_OFFSET_Y_BY_ITEM.get(item_id, anchor[1]))
        size = item_frame_size(item)
        parts = []
        art_flip = flip != (name in CLOTHING_MIRROR_INVERT)
        tint = tints["skin"] if effect == SKINTINT else None
        if name == "hand" and size[0] != AVATAR_TILE:
            # The hand item's anchor is align 5, whose pivot is ``(cellW/2, 0)``
            # (see layout.CLOTHING_OFFSETS["hand"]), and the arm drawer's own
            # position does not depend on the cell width. A wider frame therefore
            # moves the cell's top-left left by ``cellW/2 - 16``.
            anchor = (anchor[0] - (size[0] // 2 - AVATAR_TILE // 2), anchor[1])
        for frame in frames:
            sprite = self._tile(item.texture_file.decode(), frame, size, tint=tint, flip=art_flip)
            if sprite is not None:
                parts.append((sprite, anchor, size))
        if effect == OFFHAND and name == "hand":
            # The off-hand copy: the cell one (or two) columns to the right, at
            # 7*scale - 14*scale*flip, base_y - 20*scale, align 5.
            step = 2 if item_id in OFFHAND_FRAME_OFFSET_2_IDS else OFFHAND_FRAME_OFFSET
            frame = (item.tex_coord_x + step, item.tex_coord_y)
            sprite = self._tile(item.texture_file.decode(), frame, size, tint=tint, flip=art_flip)
            if sprite is not None:
                off = OFFHAND_OFFSET
                if size[0] != AVATAR_TILE:
                    off = (off[0] - (size[0] // 2 - AVATAR_TILE // 2), off[1])
                parts.append((sprite, off, size))
        elif effect in PULSE_EFFECTS and name in PULSE_COMPANION_SLOTS:
            # The pulse overlay: the cell one column right, at the same anchor,
            # its alpha driven by the item's own pulse (reverse-engineered from
            # sub_140277640 / sub_1400E4860).
            pulse = pulse_alpha(item.frame_interval_ms)
            sprite = self._tile(
                item.texture_file.decode(),
                (item.tex_coord_x + 1, item.tex_coord_y),
                size,
                tint=tint,
                flip=art_flip,
            )
            if sprite is not None:
                sprite.putalpha(sprite.getchannel("A").point(lambda a: a * pulse // 255))
                parts.append((sprite, anchor, size))
        return parts

    def _one_cell(self, name: str, item_id: int, anchor: tuple[int, int], *, frame=None, flip: bool) -> list[tuple[Image.Image, tuple[int, int], tuple[int, int]]]:
        """One cell of ``item_id`` at ``anchor`` (used by the extra copies)."""

        item = item_database.get(item_id)
        if not item.texture_file:
            return []
        size = item_frame_size(item)
        frame = (item.tex_coord_x, item.tex_coord_y) if frame is None else frame
        sprite = self._tile(item.texture_file.decode(), frame, size, tint=None, flip=flip)
        return [] if sprite is None else [(sprite, anchor, size)]

    def _no_arms(self, clothing) -> bool:
        """True when the worn shirt carries ``IVE_NO_ARMS``."""

        return self._effect(clothing.shirt) == NO_ARMS

    def _bare_feet(self, skin: np.ndarray | None, *, flip: bool) -> list[tuple[Image.Image, tuple[int, int], tuple[int, int]]]:
        """Default feet plus the leg stretcher row, at the body cell's anchor."""

        parts = []
        stretch = self._tile(LEG_TEXTURE, (0, 0), LEG_ROW_CELL, tint=skin, flip=flip)
        if stretch is not None:
            parts.append((stretch, LEG_ROW_OFFSET, LEG_ROW_CELL))

        size = (AVATAR_TILE, AVATAR_TILE)
        for frame in BARE_FEET_FRAMES:
            sprite = self._tile(BARE_FEET_TEXTURE, frame, size, tint=skin, flip=flip)
            if sprite is not None:
                parts.append((sprite, CLOTHING_OFFSETS["shoes"], size))
        return parts

    def _tile(
        self,
        texture: str,
        frame: tuple[int, int],
        size: tuple[int, int],
        *,
        tint: np.ndarray | None,
        flip: bool,
    ) -> Image.Image | None:
        path = self._game_path / texture
        if not path.is_file():
            return None

        pixels = self._textures.get(
            path,
            frame[0] * size[0],
            frame[1] * size[1],
            size[0],
            size[1],
            flip_x=flip,
        )
        if tint is not None:
            pixels = _tint(pixels, tint)
        return Image.fromarray(pixels, "RGBA")


def _tint(pixels: np.ndarray, color: np.ndarray) -> np.ndarray:
    """Multiply a tile by a tint colour the way the client's shader does.

    Every avatar sprite is handed a tint (``renderSprite``'s ``a8``
    argument) that the pixel shader multiplies into the sampled texel, then
    rounds to 8 bits. Rounding matters at the low end: atlas grey 200 under the
    skin ``(120, 92, 80)`` is ``200 * 80 / 255 = 62.7``, and a reference render
    shows 63 where truncation would give 62 - a 1/255 error on every tinted
    pixel with a channel below 255.
    """

    out = pixels.copy()
    out[..., :3] = np.rint(pixels[..., :3].astype(np.float32) * color[:3] / 255.0).astype(np.uint8)
    return out


def render_player(player: Player, options: RenderOptions | None = None) -> Image.Image:
    """Convenience wrapper around :class:`PlayerRenderer` for one-off renders."""

    return PlayerRenderer().render(player, options)
