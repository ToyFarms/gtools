from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar, Iterable

from pyglm.glm import ivec2, vec2

from gtools.baked.items import PAINTING_EASEL
from gtools.core.growtopia.world import (
    DisplayBlockTile,
    DroppedItem,
    HeartOfGaiaTile,
    ItemSuckerTile,
    PaintingEaselTile,
    SeedTile,
    ShelfTile,
    TechnoOrganicEngineTile,
    Tile,
    TesseractManipulatorTile,
    VendingMachineTile,
)
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.chunked_renderer import ChunkKey
from gtools.gui.lib.layer import (
    OBJECT_POST_FOREGROUND_END,
    OBJECT_POST_FOREGROUND_START,
    OBJECT_PRE_FOREGROUND_END,
    OBJECT_PRE_FOREGROUND_START,
)
from gtools.gui.lib.object_renderer import ObjectRenderer

_TREE_ICON_OFFSET = {
    0: (-4, -7),
    1: (6, -7),
    2: (-10, 2),
    3: (0, 2),
}

_QUIET_FLAGS = ObjectRenderer.Flags.NO_OVERLAY | ObjectRenderer.Flags.NO_SHADOW | ObjectRenderer.Flags.NO_TEXT


@dataclass(slots=True)
class TileIconGroup:
    pre_foreground: bool
    icon_scale: float = 1.0
    overlay_scale: float = 1.0
    tex_offset: ivec2 = field(default_factory=lambda: ivec2(0, 0))
    pos_offset: vec2 = field(default_factory=lambda: vec2(0, 0))
    tint: tuple[float, float, float] = (1, 1, 1)
    flags: "ObjectRenderer.Flags" = _QUIET_FLAGS
    rotation: float = 0.0
    pixel_scale: float = 1.0
    z_offset: float = 0.0


def _extract_group_items(tiles: Iterable[Tile]) -> dict[str, list[DroppedItem]]:
    groups: defaultdict[str, list[DroppedItem]] = defaultdict(list)

    for tile in tiles:
        extra = tile.extra
        if not extra:
            continue

        if isinstance(extra, DisplayBlockTile) and extra.item_id != 0:
            groups["display"].append(DroppedItem(pos=vec2(tile.pos) * 32, id=extra.item_id))
        elif isinstance(extra, SeedTile):
            for i in range(extra.item_on_tree):
                groups["tree"].append(DroppedItem(pos=vec2(tile.pos) * 32 + _TREE_ICON_OFFSET[i], id=tile.fg_id - 1))
        elif isinstance(extra, VendingMachineTile) and extra.item_id != 0 and extra.price != 0:
            groups["vending"].append(DroppedItem(pos=vec2(tile.pos) * 32 + vec2(-2, -3), id=extra.item_id))
        elif isinstance(extra, PaintingEaselTile) and extra.item_id != 0:
            groups["easel"].append(DroppedItem(pos=vec2(tile.pos) * 32 + vec2(2, -6), id=extra.item_id))
            groups["easel_mark"].append(DroppedItem(pos=vec2(tile.pos) * 32 + vec2(2, 0), id=PAINTING_EASEL))
        elif isinstance(extra, ShelfTile):
            for item_id, pos in (
                (extra.top_left_item_id, (-5, -8)),
                (extra.top_right_item_id, (7, -8)),
                (extra.bottom_left_item_id, (-5, 7)),
                (extra.bottom_right_item_id, (7, 7)),
            ):
                if item_id != 0:
                    groups["shelf"].append(DroppedItem(pos=vec2(tile.pos) * 32 + vec2(pos), id=item_id))
        elif isinstance(extra, ItemSuckerTile):
            groups["sucker"].append(DroppedItem(pos=vec2(tile.pos) * 32, id=extra.item_id))
        elif isinstance(extra, (TesseractManipulatorTile, HeartOfGaiaTile)):
            groups["sucker"].append(DroppedItem(pos=vec2(tile.pos) * 32, id=extra.item_id))
        elif isinstance(extra, TechnoOrganicEngineTile):
            groups["sucker"].append(DroppedItem(pos=vec2(tile.pos) * 32, id=extra.item_id))

    return groups


class TileObjectRenderer:
    GROUPS: ClassVar[dict[str, TileIconGroup]] = {
        "sucker": TileIconGroup(pre_foreground=True, icon_scale=0.5),
        "display": TileIconGroup(pre_foreground=True, icon_scale=1.0),
        "tree": TileIconGroup(pre_foreground=False, icon_scale=0.30),
        "easel": TileIconGroup(
            pre_foreground=False,
            icon_scale=0.5,
            pos_offset=vec2(-2, 3),
            rotation=0.2,
            pixel_scale=1.2,
        ),
        "easel_mark": TileIconGroup(
            pre_foreground=False,
            icon_scale=1.1,
            tex_offset=ivec2(0, 1),
            tint=(0.3, 0.3, 0.3),
            rotation=0.1,
            z_offset=0.001,
        ),
        "vending": TileIconGroup(pre_foreground=False, icon_scale=0.5),
        "shelf": TileIconGroup(pre_foreground=False, icon_scale=0.3),
    }

    def __init__(self) -> None:
        self._renderers: dict[str, ObjectRenderer] = {
            name: ObjectRenderer(
                *((OBJECT_PRE_FOREGROUND_START, OBJECT_PRE_FOREGROUND_END) if group.pre_foreground else (OBJECT_POST_FOREGROUND_START, OBJECT_POST_FOREGROUND_END))
            )
            for name, group in self.GROUPS.items()
        }
        self._visible_count = 0

    @property
    def total_items(self) -> int:
        return sum(r.total_items for r in self._renderers.values())

    @property
    def visible_count(self) -> int:
        return sum(r.visible_count for r in self._renderers.values())

    def any_pre_foreground(self) -> bool:
        return any(r.any() for name, r in self._renderers.items() if self.GROUPS[name].pre_foreground)

    def any_post_foreground(self) -> bool:
        return any(r.any() for name, r in self._renderers.items() if not self.GROUPS[name].pre_foreground)

    def sync_chunk_tiles(self, chunk_key: ChunkKey, tiles: Iterable[Tile]) -> None:
        extracted = _extract_group_items(tiles)
        for name, group in self.GROUPS.items():
            self._renderers[name].set_chunk(
                chunk_key,
                extracted.get(name, []),
                icon_scale=group.icon_scale,
                overlay_scale=group.overlay_scale,
                tex_offset=group.tex_offset,
                pos_offset=group.pos_offset,
                flags=group.flags,
                tint=group.tint,
            )

    def delete_chunk(self, chunk_key: ChunkKey) -> None:
        self.sync_chunk_tiles(chunk_key, [])

    def _for_each(self, pre_foreground: bool, draw_fn: Callable[[str, TileIconGroup], Any]) -> None:
        for name, group in self.GROUPS.items():
            if group.pre_foreground == pre_foreground:
                draw_fn(name, group)

    def draw_pre_foreground(self, camera: Camera2D, culling_camera: Camera2D | None = None) -> None:
        self._for_each(
            True,
            lambda name, group: self._renderers[name].draw_chunks(camera, culling_camera, rotation=group.rotation, pixel_scale=group.pixel_scale, z_offset=group.z_offset),
        )

    def draw_post_foreground(self, camera: Camera2D, culling_camera: Camera2D | None = None) -> None:
        self._for_each(
            False,
            lambda name, group: self._renderers[name].draw_chunks(camera, culling_camera, rotation=group.rotation, pixel_scale=group.pixel_scale, z_offset=group.z_offset),
        )

    def draw_pre_foreground_shadow(self, camera: Camera2D, culling_camera: Camera2D | None = None) -> None:
        self._for_each(True, lambda name, group: self._renderers[name].draw_chunks_shadow(camera, culling_camera, z_offset=group.z_offset))

    def draw_post_foreground_shadow(self, camera: Camera2D, culling_camera: Camera2D | None = None) -> None:
        self._for_each(False, lambda name, group: self._renderers[name].draw_chunks_shadow(camera, culling_camera, z_offset=group.z_offset))

    def draw_pre_foreground_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        self._for_each(
            True,
            lambda name, group: self._renderers[name].draw_chunks_3d(camera3d, layer_spread, rotation=group.rotation, pixel_scale=group.pixel_scale, z_offset=group.z_offset),
        )

    def draw_post_foreground_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        self._for_each(
            False,
            lambda name, group: self._renderers[name].draw_chunks_3d(camera3d, layer_spread, rotation=group.rotation, pixel_scale=group.pixel_scale, z_offset=group.z_offset),
        )

    def draw_pre_foreground_shadow_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        self._for_each(True, lambda name, group: self._renderers[name].draw_chunks_shadow_3d(camera3d, layer_spread, z_offset=group.z_offset))

    def draw_post_foreground_shadow_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        self._for_each(False, lambda name, group: self._renderers[name].draw_chunks_shadow_3d(camera3d, layer_spread, z_offset=group.z_offset))

    def delete(self) -> None:
        for renderer in self._renderers.values():
            renderer.delete()
