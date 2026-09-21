from typing import Iterable

from pyglm.glm import vec2

from gtools.core.growtopia.world import DroppedItem
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.layer import OBJECT_DROPPED_END, OBJECT_DROPPED_START
from gtools.gui.lib.object_renderer import ObjectRenderer


class DroppedObjectRenderer:
    def __init__(self) -> None:
        self._renderer = ObjectRenderer(OBJECT_DROPPED_START, OBJECT_DROPPED_END)

    @property
    def total_items(self) -> int:
        return self._renderer.total_items

    @property
    def visible_count(self) -> int:
        return self._renderer.visible_count

    def any(self) -> bool:
        return self._renderer.any()

    def _build_kwargs(self) -> dict:
        return {
            "icon_scale": 0.5,
            "overlay_scale": 1,
            "pos_offset": vec2(-8, -8),
            "flags": ObjectRenderer.Flags.ORDER_BY_UID,
        }

    def sync(self, items: Iterable[DroppedItem]) -> None:
        self._renderer.sync(items, **self._build_kwargs())

    def sync_diff(
        self,
        added: Iterable[DroppedItem],
        removed: Iterable[DroppedItem],
        modified: Iterable[DroppedItem],
    ) -> None:
        self._renderer.sync_diff(added, removed, modified, **self._build_kwargs())

    def draw(self, camera: Camera2D, culling_camera: Camera2D | None = None) -> None:
        self._renderer.draw_chunks(camera, culling_camera)

    def draw_shadow(self, camera: Camera2D, culling_camera: Camera2D | None = None) -> None:
        self._renderer.draw_chunks_shadow(camera, culling_camera)

    def draw_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        self._renderer.draw_chunks_3d(camera3d, layer_spread)

    def draw_shadow_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        self._renderer.draw_chunks_shadow_3d(camera3d, layer_spread)

    def delete(self) -> None:
        self._renderer.delete()
