from typing import Iterable

from gtools.core.growtopia.world import DroppedItem
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.object_renderer import ObjectRenderer


class DroppedObjectRenderer:
    """Thin driver over :class:`ObjectRenderer`; the scene content is the
    command system's (``build_dropped_commands``)."""

    def __init__(self) -> None:
        self._renderer = ObjectRenderer()

    @property
    def total_items(self) -> int:
        return self._renderer.total_items

    @property
    def visible_count(self) -> int:
        return self._renderer.visible_count

    def any(self) -> bool:
        return self._renderer.any()

    def sync(self, items: Iterable[DroppedItem]) -> None:
        self._renderer.sync(items)

    def sync_diff(
        self,
        added: Iterable[DroppedItem],
        removed: Iterable[DroppedItem],
        modified: Iterable[DroppedItem],
    ) -> None:
        self._renderer.sync_diff(added, removed, modified)

    def draw(self, camera: Camera2D, culling_camera: Camera2D | None = None) -> None:
        self._renderer.draw(camera, culling_camera)

    def draw_shadow(self, camera: Camera2D, culling_camera: Camera2D | None = None) -> None:
        self._renderer.draw_shadow(camera, culling_camera)

    def draw_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        self._renderer.draw_3d(camera3d, layer_spread)

    def draw_shadow_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        self._renderer.draw_shadow_3d(camera3d, layer_spread)

    def delete(self) -> None:
        self._renderer.delete()
