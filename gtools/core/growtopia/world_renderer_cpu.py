"""CPU rasterizer backend for the render command system.

Consumes the commands built by :mod:`gtools.core.growtopia.render_commands`
and composites them into a numpy image (offline map export, item icons).
The GUI consumes the same commands through ``gtools.gui.lib.sprite_batch``.
"""

from collections import OrderedDict
import math
from typing import Iterable, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from pyglm.glm import ivec2

from gtools import setting
from gtools.core.color import color_matrix_filter, color_tint
from gtools.core.growtopia.rttex import RTTexManager
from gtools.core.growtopia.world import Tile, World, _COLOR_MATRICES

# The command system is defined in render_commands; re-exported here so the
# established import path keeps working.
from gtools.core.growtopia.render_commands import (
    GEMS_TO_TEX_OFFSET,
    LAYER_ORDER,
    LAYER_RANK,
    PICKUP_BOX_BLUE,
    PICKUP_BOX_GOLD,
    PICKUP_BOX_GRAY,
    PICKUP_BOX_GREEN,
    PICKUP_BOX_ORANGE,
    PICKUP_BOX_PURPLE,
    PICKUP_BOX_RED,
    PICKUP_BOX_WHITE,
    PICKUP_BOX_YELLOW,
    Command,
    RenderCommand,
    RenderLayer,
    RenderOptions,
    TextCommand,
    TileConnectionState,
    build_dropped_commands,
    build_dropped_item_commands,
    build_object_commands,
    build_tile_commands,
    build_tile_object_commands,
    build_world_commands,
    sort_commands,
)

_process_mgr: RTTexManager | None = None


def _get_process_mgr() -> RTTexManager:
    global _process_mgr
    if _process_mgr is None:
        _process_mgr = RTTexManager()

    return _process_mgr


class _LRU:
    def __init__(self, capacity: int) -> None:
        self._data: OrderedDict = OrderedDict()
        self._capacity = capacity

    def get(self, key):
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key, value) -> None:
        if key in self._data:
            self._data.move_to_end(key)
            self._data[key] = value
            return
        self._data[key] = value
        if len(self._data) > self._capacity:
            self._data.popitem(last=False)


def _numpy_resize_nearest(arr: np.ndarray, target: int) -> np.ndarray:
    src_h, src_w = arr.shape[:2]
    if src_h == target and src_w == target:
        return arr

    row_idx = np.arange(target, dtype=np.int32) * src_h // target
    col_idx = np.arange(target, dtype=np.int32) * src_w // target

    return arr[np.ix_(row_idx, col_idx)]


_SPRITE_CACHE: _LRU = _LRU(4096)
_FONT_CACHE: dict = {}
_TEXT_CACHE: dict = {}


def _load_sprite(mgr: RTTexManager, cmd: RenderCommand, target_size: int, *, alpha_threshold: int) -> np.ndarray:
    size = max(1, cmd.sample_size)
    raw = mgr.get(
        setting.gt_path / "game" / cmd.texture_file,
        cmd.tex_pos.x * size,
        cmd.tex_pos.y * size,
        size,
        size,
        flip_x=cmd.is_flipped,
    )

    if target_size != size:
        raw = _numpy_resize_nearest(raw, target_size)

    tex = Image.fromarray(raw, "RGBA")
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


def _render_sprite(cmd: RenderCommand, canvas: np.ndarray, mgr: RTTexManager, options: RenderOptions, origin: ivec2 | None) -> None:
    target_size = max(1, int(round(cmd.sprite_size * options.scale)))
    tint_key = cmd.get_tint()

    cache_key = (
        cmd.texture_file,
        cmd.tex_pos.x,
        cmd.tex_pos.y,
        cmd.sample_size,
        target_size,
        cmd.paint_index,
        cmd.is_flipped,
        tint_key.tobytes() if tint_key is not None else None,
        round(cmd.opacity, 4),
        options.alpha_threshold,
    )

    tex = _SPRITE_CACHE.get(cache_key)

    if tex is None:
        tex = _load_sprite(mgr, cmd, target_size, alpha_threshold=options.alpha_threshold)
        _SPRITE_CACHE.put(cache_key, tex)

    if cmd.pixel_pos is not None:
        ox = int(round(cmd.pixel_pos[0] * options.scale))
        oy = int(round(cmd.pixel_pos[1] * options.scale))
    else:
        base_x = (cmd.tile_pos.x - (origin.x if origin else 0)) * options.tile_size
        base_y = (cmd.tile_pos.y - (origin.y if origin else 0)) * options.tile_size
        ox = int(round(base_x * options.scale))
        oy = int(round(base_y * options.scale))

    _composite(canvas, tex, ox, oy)


def _render_text(cmd: TextCommand, canvas: np.ndarray, mgr: RTTexManager, options: RenderOptions, origin: ivec2 | None) -> None:
    scale = options.scale
    scaled_size = max(1, int(round(cmd.size * scale)))

    cache_key = (cmd.font, scaled_size, cmd.text, cmd.color)

    arr = _TEXT_CACHE.get(cache_key)

    if arr is None:
        font_key = (cmd.font, scaled_size)
        font = _FONT_CACHE.get(font_key)
        if font is None:
            font = ImageFont.truetype(cmd.font, scaled_size)
            _FONT_CACHE[font_key] = font

        dummy = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        draw = ImageDraw.Draw(dummy)
        bbox = draw.textbbox((0, 0), cmd.text, font=font)
        left, top, right, bottom = bbox
        w = right - left + 4
        h = bottom - top + 4

        img = Image.new("RGBA", (int(math.ceil(w)), int(math.ceil(h))), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((-left, -top), cmd.text, font=font, fill=cmd.color)

        arr = np.array(img, dtype=np.uint8).astype(np.float32)
        arr[..., :3] *= arr[..., 3:4] * (1.0 / 255.0)

        _TEXT_CACHE[cache_key] = arr

    ox = int(round(cmd.pixel_pos[0] * scale + cmd.offset[0]))
    oy = int(round(cmd.pixel_pos[1] * scale + cmd.offset[1]))
    _composite(canvas, arr, ox, oy)


def _render_command(cmd: Command, canvas: np.ndarray, mgr: RTTexManager, options: RenderOptions, origin: ivec2 | None) -> None:
    if isinstance(cmd, RenderCommand):
        _render_sprite(cmd, canvas, mgr, options, origin)
    elif isinstance(cmd, TextCommand):
        _render_text(cmd, canvas, mgr, options, origin)


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


def _rasterize(commands: Sequence[Command], width_px: int, height_px: int, *, options: RenderOptions, tile_origin: ivec2 | None = None) -> np.ndarray:
    mgr = _get_process_mgr()
    canvas = np.zeros((height_px, width_px, 4), dtype=np.float32)
    for cmd in sort_commands(commands):
        _render_command(cmd, canvas, mgr, options, tile_origin)
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


def render_tile_array(tile: Tile, connection: TileConnectionState | None = None, *, options: RenderOptions | None = None) -> np.ndarray:
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

    return img


def render_commands(commands: Iterable[Command], width_px: int, height_px: int, *, options: RenderOptions | None = None) -> np.ndarray:
    options = options or RenderOptions()
    return _rasterize(
        list(commands),
        width_px=width_px,
        height_px=height_px,
        options=options,
    )
