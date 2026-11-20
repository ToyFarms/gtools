"""The renderer-agnostic world scene: render commands + builders.

This module is the single source of truth for *what* a world render contains.
Both backends consume it:

* ``gtools.core.growtopia.world_renderer_cpu`` rasterizes the commands into a
  numpy image (offline map export, item icons),
* the GUI pipeline (``gtools/gui/lib/sprite_batch.py``) translates them into
  instanced GL meshes.

Commands describe the scene in client world space with one convention: a
tile's top-left corner is ``(x * 32, y * 32)`` and a sprite's ``pixel_pos`` /
``tile_pos`` is its top-left corner. Backends convert to their own anchor and
space (the GUI centres tiles at ``x * 32``) from this single description.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterable, Protocol

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pyglm import glm
from pyglm.glm import ivec2

from gtools.baked.items import GEMS, MUTATED_SEED, PAINTING_EASEL
from gtools.baked.items import STEAM_REVOLVER, STEAM_TUBES
from gtools.core.growtopia.items_dat import ItemFlag, ItemInfoColor, ItemInfoTextureType, ItemInfoType, ItemInfoVisualEffect, get_default_tex, get_tex_stride, item_database
from gtools.core.growtopia.world import (
    DisplayBlockTile,
    DroppedItem,
    HeartOfGaiaTile,
    ItemSuckerTile,
    PaintingEaselTile,
    SeedTile,
    ShelfTile,
    TechnoOrganicEngineTile,
    TesseractManipulatorTile,
    Tile,
    TileFlags,
    VendingMachineTile,
    World,
)


class RenderLayer(Enum):
    BG = auto()
    FG_BEFORE = auto()
    OBJ_PRE = auto()
    FG = auto()
    FG_AFTER = auto()
    OBJ_POST = auto()
    OBJ_TEXT = auto()
    FIRE = auto()
    WATER = auto()


@dataclass(slots=True)
class RenderOptions:
    tile_size: int = 32
    scale: float = 1.0
    alpha_threshold: int = 1
    include_special_overlays: bool = True
    include_elemental_overlays: bool = True
    include_objects: bool = True
    stop_at_garbage_start: bool = True


@dataclass(slots=True)
class TileConnectionState:
    fg: int | None = None
    bg: int | None = None
    overlay: int | None = None

    @classmethod
    def default(cls, tile: Tile) -> "TileConnectionState":
        return TileConnectionState(
            fg=item_database.get(tile.fg_id).get_default_tex(),
            bg=item_database.get(tile.bg_id).get_default_tex(),
            overlay=get_default_tex(ItemInfoTextureType.SMART_EDGE),
        )


class Command(Protocol):
    """A scene element. Backends dispatch on the concrete command type."""

    layer: RenderLayer


@dataclass(slots=True)
class RenderCommand(Command):
    tile_pos: ivec2
    item_id: int
    layer: RenderLayer
    texture_file: str
    tex_pos: ivec2
    pixel_pos: tuple[int, int] | None = None
    sprite_size: int = 32
    sample_size: int = 32
    paint_index: int = 0
    tint: np.ndarray | tuple[int, int, int] | ItemInfoColor | None = None
    is_flipped: bool = False
    opacity: float = 1.0
    # the backend may draw a drop shadow copy under this sprite (dropped objects)
    shadow: bool = False

    def with_tint(self, tint: np.ndarray | tuple[int, int, int] | ItemInfoColor | None = None) -> "RenderCommand":
        self.tint = tint
        return self

    def get_tint(self) -> np.ndarray | None:
        if isinstance(self.tint, np.ndarray):
            return self.tint
        elif isinstance(self.tint, tuple):
            self.tint = np.array(self.tint, dtype=np.uint8)
        elif isinstance(self.tint, ItemInfoColor):
            self.tint = np.array([self.tint.r, self.tint.g, self.tint.b, 255], dtype=np.uint8)
        return self.tint


@dataclass(slots=True)
class TextCommand(Command):
    text: str
    pixel_pos: tuple[int, int]
    layer: RenderLayer
    font: str
    size: int
    color: tuple[int, int, int, int] = (255, 255, 255, 255)
    offset: tuple[int, int] = (0, 0)


LAYER_ORDER = [
    RenderLayer.BG,
    RenderLayer.FG_BEFORE,
    RenderLayer.OBJ_PRE,
    RenderLayer.FG,
    RenderLayer.FG_AFTER,
    RenderLayer.OBJ_POST,
    RenderLayer.OBJ_TEXT,
    RenderLayer.FIRE,
    RenderLayer.WATER,
]

LAYER_RANK = {layer: i for i, layer in enumerate(LAYER_ORDER)}


def _get_discolor_tint(item_id: int) -> tuple[int, int, int] | None:
    if item_database.get(item_id).visual_effect == ItemInfoVisualEffect.DISCOLOR:
        seed = item_database.get(item_id + 1)
        return (seed.seed_overlay_color.r, seed.seed_overlay_color.g, seed.seed_overlay_color.b)


def _base_sprite_command(tile: Tile, item_id: int, tex_index: int, layer: RenderLayer) -> RenderCommand:
    item = item_database.get(item_id)
    tex_pos, is_flipped = tile.tex_pos(item_id, tex_index)

    return RenderCommand(
        tile_pos=tile.pos,
        item_id=item_id,
        layer=layer,
        texture_file=item.texture_file.decode(),
        tex_pos=tex_pos,
        paint_index=tile.get_paint_index(),
        tint=_get_discolor_tint(item_id),
        is_flipped=is_flipped,
    )


def _raw_sprite_command(tile: Tile, item_id: int, layer: RenderLayer, texture_file: str, tex_pos: ivec2) -> RenderCommand:
    return RenderCommand(
        tile_pos=tile.pos,
        item_id=item_id,
        layer=layer,
        texture_file=texture_file,
        tex_pos=tex_pos,
        paint_index=tile.get_paint_index(),
        tint=_get_discolor_tint(item_id),
    )


GEMS_TO_TEX_OFFSET = {1: 0, 5: 1, 10: 2, 50: 3, 100: 4}
PICKUP_BOX_BLUE = 0
PICKUP_BOX_YELLOW = 1
PICKUP_BOX_RED = 2
PICKUP_BOX_GREEN = 3
PICKUP_BOX_GOLD = 4
PICKUP_BOX_PURPLE = 5
PICKUP_BOX_ORANGE = 6
PICKUP_BOX_GRAY = 7
PICKUP_BOX_WHITE = 8


def _object_icon_command(
    dropped: DroppedItem,
    layer: RenderLayer,
    commands: list[Command],
    *,
    pos_offset: tuple[int, int] = (0, 0),
    tex_offset: tuple[int, int] = (0, 0),
    icon_scale: float = 1.0,
    use_original_texture: bool = False,
    render_pickup_overlay: bool = False,
    shadow: bool = False,
) -> None:
    if dropped.id <= 0:
        return None

    item = item_database.get(dropped.id)

    # seeds always render as their 16px base/overlay pair (the dedicated seed
    # sprite), never as the item icon scaled by the group. The pair anchors at
    # its top-left corner, so shift by half a cell to stay centred in the
    # 32px cell the group positions.
    if item.is_seed() and item.id != MUTATED_SEED:
        _seed_icon_commands(dropped, layer, commands, pos_offset=(pos_offset[0] + 8, pos_offset[1] + 8))
        return

    texture_file = item.texture_file.decode() if use_original_texture else (item.get_icon_texture() or item.texture_file.decode())
    if item.id == GEMS:
        tex_index = GEMS_TO_TEX_OFFSET.get(dropped.amount, 0)
        stride = 5
        off = ivec2(tex_index % max(stride, 1), tex_index // stride if stride else 0)
        tex_pos = ivec2(item.tex_coord_x, item.tex_coord_y) + off
    elif item.texture_type == ItemInfoTextureType.SINGLE_FRAME:
        tex_pos = ivec2(item.tex_coord_x, item.tex_coord_y)
    else:
        tex_index = item.get_default_tex()
        stride = item.get_tex_stride()
        off = ivec2(tex_index % max(stride, 1), tex_index // stride if stride else 0)
        tex_pos = ivec2(item.tex_coord_x, item.tex_coord_y) + off

    tex_pos += tex_offset
    px = int(dropped.pos.x + pos_offset[0])
    py = int(dropped.pos.y + pos_offset[1])
    size = max(1, int(32 * icon_scale))

    commands.append(
        RenderCommand(
            tile_pos=ivec2(0, 0),
            item_id=dropped.id,
            layer=layer,
            texture_file=texture_file,
            tex_pos=tex_pos,
            pixel_pos=(px, py),
            sprite_size=size,
            tint=_get_discolor_tint(dropped.id),
            shadow=shadow,
        )
    )

    if render_pickup_overlay:
        _pickup_overlay_command(dropped, RenderLayer.OBJ_POST, commands, icon_scale=1.0, pos_offset=(0, 0), shadow=shadow)

    if dropped.amount > 1 and dropped.id != GEMS:
        _text_command(
            "resources/fonts/centurygothic_bold.ttf",
            dropped.amount,
            px,
            py,
            20,
            (0, 0, 0, 150),
            RenderLayer.OBJ_POST,
            commands,
            offset=(1, 1),
        )
        _text_command(
            "resources/fonts/centurygothic_bold.ttf",
            dropped.amount,
            px,
            py,
            20,
            (255, 255, 255, 255),
            RenderLayer.OBJ_POST,
            commands,
        )


def _pickup_overlay_command(dropped: DroppedItem, layer: RenderLayer, commands: list[Command], *, pos_offset: tuple[int, int], icon_scale: float = 1.0, shadow: bool = False) -> RenderCommand | None:
    if dropped.id <= 0:
        return None

    item = item_database.get(dropped.id)
    if item.id == GEMS:
        return None

    tex_index = PICKUP_BOX_BLUE
    if item.item_type == ItemInfoType.CONSUMABLE:
        tex_index = PICKUP_BOX_PURPLE
    elif item.item_type == ItemInfoType.LOCK:
        tex_index = PICKUP_BOX_ORANGE
    elif item.flags & ItemFlag.UNTRADEABLE:
        tex_index = PICKUP_BOX_WHITE

    px = int(dropped.pos.x + pos_offset[0])
    py = int(dropped.pos.y + pos_offset[1])
    size = max(1, int(20 * icon_scale))

    commands.append(
        RenderCommand(
            tile_pos=ivec2(0, 0),
            item_id=dropped.id,
            layer=layer,
            texture_file="pickup_box.rttex",
            tex_pos=ivec2(tex_index, 0),
            pixel_pos=(px, py),
            sprite_size=size,
            sample_size=20,
            shadow=shadow,
        )
    )


def _text_command(
    text_renderer_font: str,
    amount: int,
    x: float,
    y: float,
    container_size: float,
    color: tuple[int, int, int, int],
    layer: RenderLayer,
    commands: list[Command],
    *,
    offset: tuple[int, int] = (0, 0),
) -> None:
    if amount <= 1:
        return

    text_str = str(amount)

    dummy = Image.new("RGBA", (1, 1))
    draw = ImageDraw.Draw(dummy)
    font = ImageFont.truetype(text_renderer_font, 32)
    ref_width, _ = draw.textbbox((0, 0), "000", font=font)[2:4]

    auto_scale = (16 / ref_width) if ref_width > 0 else 0.25

    bbox = draw.textbbox((0, 0), text_str, font=ImageFont.truetype(text_renderer_font, int(32 * auto_scale)))
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    text_x = x + (container_size - 4) - text_w
    text_y = y + (container_size - 4) - text_h

    commands.append(
        TextCommand(
            text=text_str,
            pixel_pos=(int(text_x), int(text_y)),
            layer=layer,
            font=text_renderer_font,
            size=int(32 * auto_scale),
            color=color,
            offset=offset,
        )
    )


def _seed_icon_commands(dropped: DroppedItem, layer: RenderLayer, commands: list[Command], *, pos_offset: tuple[int, int]) -> bool:
    if dropped.id <= 0:
        return False

    item = item_database.get(dropped.id)
    if not item.is_seed() or item.id == MUTATED_SEED:
        return False

    px = int(dropped.pos.x + pos_offset[0])
    py = int(dropped.pos.y + pos_offset[1])
    overlay_tint = np.array(
        [
            (item.seed_color.r + item.seed_overlay_color.r) // 2,
            (item.seed_color.g + item.seed_overlay_color.g) // 2,
            (item.seed_color.b + item.seed_overlay_color.b) // 2,
            255,
        ],
        dtype=np.uint8,
    )

    commands.extend(
        [
            RenderCommand(
                tile_pos=ivec2(0, 0),
                item_id=dropped.id,
                layer=layer,
                texture_file="seed.rttex",
                tex_pos=ivec2(item.seed_base.value, 0),
                pixel_pos=(px, py),
                sprite_size=16,
                sample_size=16,
                tint=np.array([item.seed_color.r, item.seed_color.g, item.seed_color.b, 255], dtype=np.uint8),
            ),
            RenderCommand(
                tile_pos=ivec2(0, 0),
                item_id=dropped.id,
                layer=layer,
                texture_file="seed.rttex",
                tex_pos=ivec2(item.seed_overlay.value, 1),
                pixel_pos=(px, py),
                sprite_size=16,
                sample_size=16,
                tint=overlay_tint,
            ),
        ]
    )

    if dropped.amount > 1:
        _text_command(
            "resources/fonts/centurygothic_bold.ttf",
            dropped.amount,
            px,
            py,
            20,
            (0, 0, 0, 150),
            RenderLayer.OBJ_POST,
            commands,
            offset=(1, 1),
        )
        _text_command(
            "resources/fonts/centurygothic_bold.ttf",
            dropped.amount,
            px,
            py,
            20,
            (255, 255, 255, 255),
            RenderLayer.OBJ_POST,
            commands,
        )

    return True


def build_tile_commands(tile: Tile, connection: TileConnectionState | None = None, *, options: RenderOptions | None = None, commands: list[Command]) -> None:
    """Emit one tile's own sprites (background, foreground variants, overlays)."""
    options = options or RenderOptions()

    if connection:
        default = TileConnectionState.default(tile)
        bg_tex = connection.bg if connection.bg else default.bg
        fg_tex = connection.fg if connection.fg else default.fg
        overlay_tex = connection.overlay if connection.overlay else default.overlay
        assert bg_tex is not None and fg_tex is not None and overlay_tex is not None
    else:
        bg_tex = tile.bg_tex_index
        fg_tex = tile.fg_tex_index
        overlay_tex = tile.overlay_tex_index

    if tile.bg_id > 0:
        commands.append(_base_sprite_command(tile, tile.bg_id, bg_tex, RenderLayer.BG))

    if tile.fg_id > 0:
        item = item_database.get(tile.fg_id)
        handled_fg_main = False
        if tile.extra:
            if isinstance(tile.extra, DisplayBlockTile):
                commands.append(
                    _raw_sprite_command(
                        tile,
                        tile.fg_id,
                        RenderLayer.FG_BEFORE,
                        item.texture_file.decode(),
                        ivec2(item.tex_coord_x, item.tex_coord_y + 1),
                    )
                )
            elif isinstance(tile.extra, VendingMachineTile):
                tex_off = 1 if tile.extra.price == 0 else 0
                commands.append(
                    _raw_sprite_command(
                        tile,
                        tile.fg_id,
                        RenderLayer.FG,
                        item.texture_file.decode(),
                        ivec2(item.tex_coord_x + tex_off, item.tex_coord_y),
                    )
                )
                if tile.flags & TileFlags.FG_ALT_MODE:
                    commands.append(
                        _raw_sprite_command(
                            tile,
                            tile.fg_id,
                            RenderLayer.FG_AFTER,
                            item.texture_file.decode(),
                            ivec2(item.tex_coord_x + 3, item.tex_coord_y),
                        )
                    )
                if tile.extra.price == 0 or tile.extra.item_id == 0:
                    commands.append(
                        _raw_sprite_command(
                            tile,
                            tile.fg_id,
                            RenderLayer.FG_AFTER,
                            item.texture_file.decode(),
                            ivec2(item.tex_coord_x + 2, item.tex_coord_y),
                        )
                    )
                handled_fg_main = True
            elif isinstance(tile.extra, SeedTile):
                commands.append(
                    _raw_sprite_command(
                        tile,
                        tile.fg_id,
                        RenderLayer.FG,
                        "tiles_page1.rttex",
                        ivec2(item.seed_base.value % 8, 19),
                    ).with_tint(item.seed_color)
                )
                commands.append(
                    _raw_sprite_command(
                        tile,
                        tile.fg_id,
                        RenderLayer.FG,
                        "tiles_page1.rttex",
                        ivec2(item.seed_overlay.value % 8, 18),
                    ).with_tint(item.seed_overlay_color)
                )
                handled_fg_main = True

        if options.include_special_overlays:
            if item.is_steam():
                anchor = item_database.get(STEAM_TUBES)
                stride = get_tex_stride(ItemInfoTextureType.SMART_EDGE)
                off = ivec2(fg_tex % max(stride, 1), fg_tex // stride if stride else 0)
                commands.append(
                    _raw_sprite_command(
                        tile,
                        tile.fg_id,
                        RenderLayer.FG_AFTER,
                        anchor.texture_file.decode(),
                        ivec2(anchor.tex_coord_x + 1, anchor.tex_coord_y) + off,
                    )
                )
            elif tile.fg_id == STEAM_REVOLVER:
                commands.append(
                    _raw_sprite_command(
                        tile,
                        tile.fg_id,
                        RenderLayer.FG_AFTER,
                        item.texture_file.decode(),
                        ivec2(item.tex_coord_x, item.tex_coord_y + 1),
                    )
                )
        if not handled_fg_main:
            commands.append(_base_sprite_command(tile, tile.fg_id, fg_tex, RenderLayer.FG))

    if options.include_elemental_overlays:
        stride = get_tex_stride(ItemInfoTextureType.SMART_EDGE)
        tex_pos = ivec2(overlay_tex % max(stride, 1), overlay_tex // stride if stride else 0)
        if tile.flags & TileFlags.ON_FIRE:
            cmd = _raw_sprite_command(tile, 0, RenderLayer.FIRE, "fire.rttex", tex_pos)
            cmd.opacity = 0.6
            commands.append(cmd)
        elif tile.flags & TileFlags.IS_WET:
            cmd = _raw_sprite_command(tile, 0, RenderLayer.WATER, "water.rttex", tex_pos)
            cmd.opacity = 0.6
            commands.append(cmd)


def build_tile_object_commands(tile: Tile, commands: list[Command]) -> None:
    """Emit the tile-extra object icons (display blocks, vending machines, easels, shelves, ...).

    A tile's extra belongs to exactly one group; the per-group scales/offsets
    below are the canonical (client-faithful) placements.
    """
    extra = tile.extra
    if not extra:
        return

    tile_px = glm.vec2(tile.pos) * 32

    if isinstance(extra, DisplayBlockTile) and extra.item_id != 0:
        _object_icon_command(DroppedItem(pos=tile_px, id=extra.item_id), RenderLayer.OBJ_PRE, commands, icon_scale=1.0)
    elif isinstance(extra, VendingMachineTile) and extra.item_id != 0 and extra.price != 0:
        _object_icon_command(DroppedItem(pos=tile_px + glm.vec2(6, 5), id=extra.item_id), RenderLayer.OBJ_POST, commands, icon_scale=0.5)
    elif isinstance(extra, PaintingEaselTile) and extra.item_id != 0:
        _object_icon_command(DroppedItem(pos=tile_px + glm.vec2(10, 2), id=extra.item_id), RenderLayer.OBJ_POST, commands, icon_scale=0.5, pos_offset=(14, 19))
        _object_icon_command(DroppedItem(pos=tile_px + glm.vec2(10, 8), id=PAINTING_EASEL), RenderLayer.OBJ_POST, commands, icon_scale=1.1, tex_offset=(0, 1))
    elif isinstance(extra, ShelfTile):
        for item_id, pos in (
            (extra.top_left_item_id, (3, 0)),
            (extra.top_right_item_id, (15, 0)),
            (extra.bottom_left_item_id, (3, 15)),
            (extra.bottom_right_item_id, (15, 15)),
        ):
            if item_id != 0:
                _object_icon_command(DroppedItem(pos=tile_px + glm.vec2(pos), id=item_id), RenderLayer.OBJ_POST, commands, icon_scale=0.3)
    elif isinstance(extra, (ItemSuckerTile, TesseractManipulatorTile, HeartOfGaiaTile, TechnoOrganicEngineTile)):
        _object_icon_command(DroppedItem(pos=tile_px, id=extra.item_id), RenderLayer.OBJ_PRE, commands, icon_scale=0.5)
    elif isinstance(extra, SeedTile):
        for i in range(extra.item_on_tree):
            pos = [(8, 5), (18, 5), (2, 14), (12, 14)][i]
            _object_icon_command(DroppedItem(pos=tile_px + glm.vec2(pos), id=tile.fg_id - 1), RenderLayer.OBJ_POST, commands, icon_scale=0.25)


def build_dropped_item_commands(dropped: DroppedItem, commands: list[Command]) -> None:
    """Emit one dropped object: seed pair or icon + pickup overlay + amount text."""
    if _seed_icon_commands(dropped, RenderLayer.OBJ_POST, commands, pos_offset=(0, 0)):
        return

    _object_icon_command(dropped, RenderLayer.OBJ_POST, commands, icon_scale=0.5, pos_offset=(2, 2), render_pickup_overlay=True, shadow=True)


def build_dropped_commands(dropped_items: Iterable[DroppedItem], commands: list[Command]) -> None:
    """Emit dropped objects in uid order (the frontmost object is the highest uid)."""
    for dropped in sorted(dropped_items, key=lambda item: item.uid):
        build_dropped_item_commands(dropped, commands)


def build_object_commands(world: World, commands: list[Command]) -> None:
    """Emit every object icon in the world: tile-extra icons, then dropped objects."""
    for tile in world.tiles.values():
        build_tile_object_commands(tile, commands=commands)

    build_dropped_commands(world.dropped, commands)


def sort_commands(commands: Iterable[Command]) -> list[Command]:
    """Stable back-to-front order shared by every backend (LAYER_ORDER)."""
    return [
        x[1]
        for x in sorted(
            enumerate(commands),
            key=lambda pair: (LAYER_RANK.get(pair[1].layer, 10**9), pair[0]),
        )
    ]


def build_world_commands(world: World, *, options: RenderOptions | None = None) -> list[Command]:
    """Build the complete scene command list for a world snapshot."""
    options = options or RenderOptions()
    commands: list[Command] = []
    for i in sorted(world.tiles):
        if options.stop_at_garbage_start and world.garbage_start is not None and i == world.garbage_start:
            break
        build_tile_commands(world.tiles[i], options=options, commands=commands)

    if options.include_objects:
        build_object_commands(world, commands)

    return commands
