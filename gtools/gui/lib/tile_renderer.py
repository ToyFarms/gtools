"""World tile chunks built from the render command system.

The chunking/dirty machinery lives in :class:`ChunkedRenderer`; the chunk
content is the command system's output (``build_tile_commands`` +
``build_tile_object_commands``) translated into instanced meshes by
:class:`SpriteBatch`. Trees, tile-extra object icons, seed sprites and the
elemental overlays all arrive as commands -- there is no per-feature geometry
code here.
"""

from enum import IntFlag, auto

from gtools.core.growtopia.render_commands import Command, RenderLayer, RenderOptions, build_tile_commands, build_tile_object_commands
from gtools.core.growtopia.world import World
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.chunked_renderer import ChunkBounds, ChunkedRenderer, ChunkKey
from gtools.gui.lib.sprite_batch import SpriteBatch, SpriteMeshes

_RENDER_FG_LAYERS = frozenset({RenderLayer.FG_BEFORE, RenderLayer.FG, RenderLayer.FG_AFTER, RenderLayer.FIRE, RenderLayer.WATER})
_OBJECT_LAYERS = frozenset({RenderLayer.OBJ_PRE, RenderLayer.OBJ_POST, RenderLayer.OBJ_TEXT})


class TileRenderer(ChunkedRenderer):
    class Flags(IntFlag):
        NONE = 0
        RENDER_FG = auto()
        RENDER_BG = auto()

    def __init__(self, options: RenderOptions | None = None) -> None:
        self.flags = TileRenderer.Flags.RENDER_FG | TileRenderer.Flags.RENDER_BG
        # the interactive view renders the whole world (the map export stops at
        # the garbage section instead)
        self._options = options or RenderOptions(stop_at_garbage_start=False)
        self._batch = SpriteBatch()
        # chunk key -> (bounds, meshes, tile-object instance count)
        self._chunks: dict[ChunkKey, tuple[ChunkBounds, SpriteMeshes, int]] = {}
        self._visible_objects = 0

    def any(self) -> bool:
        return any(meshes.layers for _, meshes, _ in self._chunks.values())

    @property
    def texture_count(self) -> int:
        return self._batch.texture_count

    @property
    def tile_object_count(self) -> int:
        return sum(count for _, _, count in self._chunks.values())

    @property
    def visible_count(self) -> int:
        return self._visible_objects

    def draw(self, camera: Camera2D, layer_name: RenderLayer, culling_camera: Camera2D | None = None) -> None:
        if not self._layer_allowed(layer_name):
            return

        cull = culling_camera or camera
        self._visible_objects = 0
        for bounds, meshes, object_count in self._chunks.values():
            if not cull.is_visible(*bounds):
                continue
            self._visible_objects += object_count
            self._batch.draw(camera, meshes, layer_name)

    def draw_3d(self, camera3d: Camera3D, layer_spread: float, layer_name: RenderLayer) -> None:
        if not self._layer_allowed(layer_name):
            return

        self._visible_objects = 0
        for _, meshes, object_count in self._chunks.values():
            self._visible_objects += object_count
            self._batch.draw_3d(camera3d, layer_spread, meshes, layer_name)

    def draw_shadows(self, camera: Camera2D, culling_camera: Camera2D | None = None) -> None:
        cull = culling_camera or camera
        for bounds, meshes, _ in self._chunks.values():
            if cull.is_visible(*bounds):
                self._batch.draw_shadows(camera, meshes)

    def draw_shadows_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        for _, meshes, _ in self._chunks.values():
            self._batch.draw_shadows_3d(camera3d, layer_spread, meshes)

    def delete(self) -> None:
        for _, meshes, _ in self._chunks.values():
            meshes.delete()
        self._chunks.clear()

    def delete_chunk(self, chunk_key: ChunkKey) -> None:
        entry = self._chunks.pop(chunk_key, None)
        if entry is not None:
            entry[1].delete()

    def build_chunk(self, world: World, chunk_x: int, chunk_y: int) -> None:
        commands: list[Command] = []
        start_x, start_y, end_x, end_y = self.chunk_tile_range(world, chunk_x, chunk_y)
        for y in range(start_y, end_y):
            for x in range(start_x, end_x):
                tile = world.get_tile(x, y)
                if not tile:
                    continue

                build_tile_commands(tile, options=self._options, commands=commands)
                build_tile_object_commands(tile, commands=commands)

        meshes = self._batch.build(commands)
        self._chunks[(chunk_x, chunk_y)] = (self.chunk_bounds(chunk_x, chunk_y), meshes, meshes.instance_count(_OBJECT_LAYERS))

    def _layer_allowed(self, layer_name: RenderLayer) -> bool:
        if layer_name == RenderLayer.BG:
            return bool(self.flags & TileRenderer.Flags.RENDER_BG)
        if layer_name in _RENDER_FG_LAYERS:
            return bool(self.flags & TileRenderer.Flags.RENDER_FG)
        return True
