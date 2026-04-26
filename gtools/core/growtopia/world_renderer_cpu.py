from collections import defaultdict
from dataclasses import dataclass
from enum import Enum, auto
import math
from typing import ClassVar, Iterable, Iterator, Protocol, Sequence
import numpy as np
from PIL import Image, ImageFont, ImageDraw
from pyglm.glm import ivec2
from pyglm import glm
from gtools import setting
from gtools.baked.items import GEMS, MUTATED_SEED, PAINTING_EASEL
from gtools.baked.items import COPPER_PLUMBING, STEAM_PIPE, STEAM_REVOLVER, STEAM_TUBES
from gtools.core.color import color_matrix_filter, color_tint
from gtools.core.growtopia.items_dat import ItemFlag, ItemInfoColor, ItemInfoTextureType, ItemInfoType, get_tex_stride, item_database
from gtools.core.growtopia.rttex import RTTexManager
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
    _COLOR_MATRICES,
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


class Command(Protocol):
    layer: RenderLayer

    def render(self, canvas: np.ndarray, mgr: RTTexManager, options: RenderOptions, origin: ivec2 | None = None) -> None: ...


@dataclass(slots=True)
class RenderCommand(Command):
    tile_pos: ivec2
    item_id: int
    layer: RenderLayer
    texture_file: str
    tex_grid_pos: ivec2
    pixel_pos: tuple[int, int] | None = None
    sprite_size: int = 32
    sample_size: int = 32
    paint_index: int = 0
    tint: np.ndarray | tuple[int, int, int] | ItemInfoColor | None = None
    is_flipped: bool = False
    opacity: float = 1.0

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

    def render(self, canvas: np.ndarray, mgr: RTTexManager, options: RenderOptions, origin: ivec2 | None = None) -> None:
        target_size = max(1, int(round(self.sprite_size * options.scale)))
        tint_key = self.get_tint()
        cache_key = (
            self.texture_file,
            self.tex_grid_pos.x,
            self.tex_grid_pos.y,
            self.sample_size,
            target_size,
            self.paint_index,
            self.is_flipped,
            tint_key.tobytes() if tint_key is not None else None,
            round(self.opacity, 4),
            options.alpha_threshold,
        )
        sprite_cache: dict[tuple, np.ndarray] = {}
        tex = sprite_cache.get(cache_key)
        if tex is None:
            tex = _load_sprite(
                mgr,
                self,
                target_size,
                alpha_threshold=options.alpha_threshold,
            )
            sprite_cache[cache_key] = tex

        if self.pixel_pos is not None:
            ox = int(round(self.pixel_pos[0] * options.scale))
            oy = int(round(self.pixel_pos[1] * options.scale))
        else:
            base_x = (self.tile_pos.x - (origin.x if origin else 0)) * options.tile_size
            base_y = (self.tile_pos.y - (origin.y if origin else 0)) * options.tile_size
            ox = int(round(base_x * options.scale))
            oy = int(round(base_y * options.scale))

        _composite(canvas, tex, ox, oy)


@dataclass(slots=True)
class TextCommand(Command):
    text: str
    pixel_pos: tuple[int, int]
    layer: RenderLayer
    font: str
    size: int
    color: tuple[int, int, int, int] = (255, 255, 255, 255)
    offset: tuple[int, int] = (0, 0)

    _font_cache: ClassVar[dict[tuple[str, int], ImageFont.FreeTypeFont]] = {}
    _text_cache: ClassVar[dict[tuple[str, int, str, tuple[int, int, int, int]], np.ndarray]] = {}

    def render(self, canvas: np.ndarray, mgr: RTTexManager, options: RenderOptions, origin: ivec2 | None = None) -> None:
        scale = options.scale
        scaled_size = int(round(self.size * scale))
        if scaled_size < 1:
            scaled_size = 1

        cache_key = (self.font, scaled_size, self.text, self.color)
        if cache_key in TextCommand._text_cache:
            arr = TextCommand._text_cache[cache_key]
            ox = int(self.pixel_pos[0] * scale + self.offset[0])
            oy = int(self.pixel_pos[1] * scale + self.offset[1])

            _composite(canvas, arr, ox, oy)
            return

        font_key = (self.font, scaled_size)
        if font_key not in TextCommand._font_cache:
            TextCommand._font_cache[font_key] = ImageFont.truetype(self.font, scaled_size)

        font = TextCommand._font_cache[font_key]

        dummy = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        draw = ImageDraw.Draw(dummy)

        bbox = draw.textbbox((0, 0), self.text, font=font)
        left, top, right, bottom = bbox

        w = right - left + 4
        h = bottom - top + 4

        img = Image.new("RGBA", (int(math.ceil(w)), int(math.ceil(h))), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        draw.text((-left, -top), self.text, font=font, fill=self.color)

        arr = np.array(img, dtype=np.uint8).astype(np.float32)
        arr[..., :3] *= arr[..., 3:4] * (1.0 / 255.0)

        TextCommand._text_cache[cache_key] = arr

        ox = int(round(self.pixel_pos[0] * scale))
        oy = int(round(self.pixel_pos[1] * scale))

        _composite(canvas, arr, ox, oy)


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


def _base_sprite_command(tile: Tile, item_id: int, tex_index: int, layer: RenderLayer) -> RenderCommand:
    item = item_database.get(item_id)
    tex_grid_pos, is_flipped = tile.tex_pos(item_id, tex_index)
    tint: np.ndarray | None = None
    if item_id in (STEAM_PIPE, COPPER_PLUMBING):
        seed = item_database.get(item_id + 1)
        tint = np.array(
            [seed.seed_overlay_color.r, seed.seed_overlay_color.g, seed.seed_overlay_color.b, 255],
            dtype=np.uint8,
        )

    return RenderCommand(
        tile_pos=tile.pos,
        item_id=item_id,
        layer=layer,
        texture_file=item.texture_file.decode(),
        tex_grid_pos=tex_grid_pos,
        paint_index=tile.get_paint_index(),
        tint=tint,
        is_flipped=is_flipped,
    )


def _raw_sprite_command(tile: Tile, item_id: int, layer: RenderLayer, texture_file: str, tex_grid_pos: ivec2) -> RenderCommand:
    return RenderCommand(
        tile_pos=tile.pos,
        item_id=item_id,
        layer=layer,
        texture_file=texture_file,
        tex_grid_pos=tex_grid_pos,
        paint_index=tile.get_paint_index(),
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
) -> None:
    if dropped.id <= 0:
        return None

    item = item_database.get(dropped.id)
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
            tex_grid_pos=tex_pos,
            pixel_pos=(px, py),
            sprite_size=size,
        )
    )

    if render_pickup_overlay:
        _pickup_overlay_command(dropped, RenderLayer.OBJ_POST, commands, icon_scale=1.0, pos_offset=(0, 0))

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


def _pickup_overlay_command(dropped: DroppedItem, layer: RenderLayer, commands: list[Command], *, pos_offset: tuple[int, int], icon_scale: float = 1.0) -> RenderCommand | None:
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
            tex_grid_pos=ivec2(tex_index, 0),
            pixel_pos=(px, py),
            sprite_size=size,
            sample_size=20,
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
                tex_grid_pos=ivec2(item.seed_base.value, 0),
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
                tex_grid_pos=ivec2(item.seed_overlay.value, 1),
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


def build_object_commands(world: World, commands: list[Command]) -> None:
    icons: defaultdict[str, list[DroppedItem]] = defaultdict(list)
    for tile in world.tiles.values():
        if not tile.extra:
            continue
        tile_px = glm.vec2(tile.pos) * 32
        if isinstance(tile.extra, DisplayBlockTile) and tile.extra.item_id != 0:
            icons["display"].append(DroppedItem(pos=tile_px, id=tile.extra.item_id))
        elif isinstance(tile.extra, VendingMachineTile) and tile.extra.item_id != 0 and tile.extra.price != 0:
            icons["vending"].append(DroppedItem(pos=tile_px + glm.vec2(6, 5), id=tile.extra.item_id))
        elif isinstance(tile.extra, PaintingEaselTile) and tile.extra.item_id != 0:
            icons["easel"].append(DroppedItem(pos=tile_px + glm.vec2(10, 2), id=tile.extra.item_id))
            icons["easel_mark"].append(DroppedItem(pos=tile_px + glm.vec2(10, 8), id=PAINTING_EASEL))
        elif isinstance(tile.extra, ShelfTile):
            for item_id, pos in (
                (tile.extra.top_left_item_id, (3, 0)),
                (tile.extra.top_right_item_id, (15, 0)),
                (tile.extra.bottom_left_item_id, (3, 15)),
                (tile.extra.bottom_right_item_id, (15, 15)),
            ):
                if item_id != 0:
                    icons["shelf"].append(DroppedItem(pos=tile_px + glm.vec2(pos), id=item_id))
        elif isinstance(tile.extra, (ItemSuckerTile, TesseractManipulatorTile, HeartOfGaiaTile, TechnoOrganicEngineTile)):
            icons["sucker"].append(DroppedItem(pos=tile_px, id=tile.extra.item_id))
        elif isinstance(tile.extra, SeedTile):
            for i in range(tile.extra.item_on_tree):
                pos = [(8, 5), (18, 5), (2, 14), (12, 14)][i]
                icons["tree_icon"].append(DroppedItem(pos=tile_px + pos, id=tile.fg_id - 1))

    for obj in icons["sucker"]:
        _object_icon_command(obj, RenderLayer.OBJ_PRE, commands, icon_scale=0.5)

    for obj in icons["display"]:
        _object_icon_command(obj, RenderLayer.OBJ_PRE, commands, icon_scale=1.0)

    for obj in world.dropped.items:
        if _seed_icon_commands(obj, RenderLayer.OBJ_POST, commands, pos_offset=(0, 0)):
            continue

        _object_icon_command(obj, RenderLayer.OBJ_POST, commands, icon_scale=0.5, pos_offset=(2, 2), render_pickup_overlay=True)

    for obj in icons["easel"]:
        _object_icon_command(obj, RenderLayer.OBJ_POST, commands, icon_scale=0.5, pos_offset=(14, 19))

    for obj in icons["easel_mark"]:
        _object_icon_command(obj, RenderLayer.OBJ_POST, commands, icon_scale=1.1, tex_offset=(0, 1))

    for obj in icons["vending"]:
        _object_icon_command(obj, RenderLayer.OBJ_POST, commands, icon_scale=0.5)

    for obj in icons["shelf"]:
        _object_icon_command(obj, RenderLayer.OBJ_POST, commands, icon_scale=0.3)

    for obj in icons["tree_icon"]:
        _object_icon_command(obj, RenderLayer.OBJ_POST, commands, icon_scale=0.25)


def build_tile_commands(tile: Tile, connection: TileConnectionState | None = None, *, options: RenderOptions | None = None, commands: list[Command]) -> None:
    options = options or RenderOptions()
    connection = connection or TileConnectionState()

    bg_tex = tile.bg_tex_index if connection.bg is None else connection.bg
    fg_tex = tile.fg_tex_index if connection.fg is None else connection.fg

    overlay_tex = tile.overlay_tex_index if connection.overlay is None else connection.overlay
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


def build_world_commands(world: World, *, options: RenderOptions | None = None) -> list[Command]:
    options = options or RenderOptions()
    commands: list[Command] = []
    for i in sorted(world.tiles):
        if options.stop_at_garbage_start and world.garbage_start is not None and i == world.garbage_start:
            break

        build_tile_commands(world.tiles[i], options=options, commands=commands)

    if options.include_objects:
        build_object_commands(world, commands)

    return commands


def _load_sprite(mgr: RTTexManager, cmd: RenderCommand, target_size: int, *, alpha_threshold: int) -> np.ndarray:
    size = max(1, cmd.sample_size)
    raw = mgr.get(
        setting.gt_path / "game" / cmd.texture_file,
        cmd.tex_grid_pos.x * size,
        cmd.tex_grid_pos.y * size,
        size,
        size,
        flip_x=cmd.is_flipped,
    )

    tex = Image.fromarray(raw, "RGBA")
    if target_size != size:
        tex = tex.resize((target_size, target_size), Image.Resampling.NEAREST)

    tex = color_matrix_filter(tex, _COLOR_MATRICES[cmd.paint_index], linear=False)
    if (tint := cmd.get_tint()) is not None:
        tex = color_tint(tex, tint)

    if cmd.opacity < 1.0:
        alpha = np.asarray(tex.getchannel("A"), dtype=np.float32)
        alpha *= cmd.opacity
        np.clip(alpha, 0, 255, out=alpha)
        tex.putalpha(Image.fromarray(alpha.astype(np.uint8), mode="L"))

    arr = np.array(tex, dtype=np.uint8, copy=True)
    if alpha_threshold > 0:
        alpha = arr[..., 3]
        alpha[alpha <= alpha_threshold] = 0

    out = arr.astype(np.float32)
    out[..., :3] *= out[..., 3:4] * (1.0 / 255.0)

    return out


def _composite(dst: np.ndarray, src: np.ndarray, x: int, y: int) -> None:
    h, w = src.shape[:2]
    if x >= dst.shape[1] or y >= dst.shape[0] or x + w <= 0 or y + h <= 0:
        return

    sx0 = 0 if x >= 0 else -x
    sy0 = 0 if y >= 0 else -y
    sx1 = w if x + w <= dst.shape[1] else dst.shape[1] - x
    sy1 = h if y + h <= dst.shape[0] else dst.shape[0] - y
    dx0 = x if x >= 0 else 0
    dy0 = y if y >= 0 else 0

    src_crop = src[sy0:sy1, sx0:sx1]
    dst_crop = dst[dy0 : dy0 + (sy1 - sy0), dx0 : dx0 + (sx1 - sx0)]
    sa = src_crop[..., 3:4] * (1.0 / 255.0)

    np.multiply(dst_crop, (1.0 - sa), out=dst_crop)
    dst_crop += src_crop


LAYER_RANK = {layer: i for i, layer in enumerate(LAYER_ORDER)}


def _sort_commands_by_layer(commands: Sequence[Command]) -> Iterator[Command]:
    return (
        x[1]
        for x in sorted(
            enumerate(commands),
            key=lambda pair: (LAYER_RANK.get(pair[1].layer, 10**9), pair[0]),
        )
    )


def _rasterize(commands: Sequence[Command], width_px: int, height_px: int, *, options: RenderOptions, tile_origin: ivec2 | None = None) -> np.ndarray:
    mgr = RTTexManager()
    canvas = np.zeros((height_px, width_px, 4), dtype=np.float32)
    for cmd in _sort_commands_by_layer(commands):
        cmd.render(canvas, mgr, options, tile_origin)

    return canvas.astype(np.uint8)


def render_world(world: World, *, options: RenderOptions | None = None) -> np.ndarray:
    options = options or RenderOptions()
    commands = build_world_commands(world, options=options)
    scale = max(0.01, options.scale)

    return _rasterize(
        commands,
        width_px=max(1, int(round(world.width * options.tile_size * scale))),
        height_px=max(1, int(round(world.height * options.tile_size * scale))),
        options=options,
    )


def render_world_image(world: World, *, options: RenderOptions | None = None) -> Image.Image:
    return Image.fromarray(render_world(world, options=options), mode="RGBA")


def render_tile(tile: Tile, connection: TileConnectionState | None = None, *, options: RenderOptions | None = None) -> Image.Image:
    options = options or RenderOptions()
    scale = max(0.01, options.scale)
    commands: list[Command] = []
    build_tile_commands(tile, connection=connection, options=options, commands=commands)

    img = _rasterize(
        commands,
        width_px=max(1, int(round(options.tile_size * scale))),
        height_px=max(1, int(round(options.tile_size * scale))),
        options=options,
        tile_origin=tile.pos,
    )

    return Image.fromarray(img, mode="RGBA")


def render_commands(commands: Iterable[Command], width_px: int, height_px: int, *, options: RenderOptions | None = None) -> np.ndarray:
    options = options or RenderOptions()
    return _rasterize(
        list(commands),
        width_px=width_px,
        height_px=height_px,
        options=options,
    )
