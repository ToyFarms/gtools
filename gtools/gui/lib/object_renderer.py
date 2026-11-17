"""Chunked dropped-object renderer driven by the command system.

This module owns the dynamic chunking + diff-sync machinery for dropped
objects; the chunk content comes from ``build_dropped_commands`` -- icon,
pickup overlay, amount text and drop shadow are the command system's
decisions, not this file's.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Sequence

from OpenGL.GL import GL_DYNAMIC_DRAW

from gtools.core.growtopia.render_commands import Command, RenderLayer, build_dropped_commands
from gtools.core.growtopia.world import DroppedItem
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.chunked_renderer import ChunkBounds, ChunkKey
from gtools.gui.lib.sprite_batch import SpriteBatch, SpriteMeshes


@dataclass(slots=True)
class _Chunk:
    bounds: ChunkBounds
    meshes: SpriteMeshes
    count: int
    signature: int | None


class ObjectRenderer:
    CHUNK_SIZE: int = 8
    TILE_SIZE: int = 32

    def __init__(self) -> None:
        self._batch = SpriteBatch()
        self._chunks: dict[ChunkKey, _Chunk] = {}
        self._item_to_chunk: dict[int, ChunkKey] = {}
        self._chunk_items: dict[ChunkKey, dict[int, DroppedItem]] = {}

        self._visible_count = 0

    @property
    def visible_count(self) -> int:
        return self._visible_count

    @property
    def total_items(self) -> int:
        return sum(chunk.count for chunk in self._chunks.values())

    def any(self) -> bool:
        return bool(self._chunks)

    @staticmethod
    def _chunk_bounds(chunk_x: int, chunk_y: int) -> ChunkBounds:
        return (
            chunk_x * ObjectRenderer.CHUNK_SIZE * ObjectRenderer.TILE_SIZE - 16,
            chunk_y * ObjectRenderer.CHUNK_SIZE * ObjectRenderer.TILE_SIZE - 16,
            ObjectRenderer.CHUNK_SIZE * ObjectRenderer.TILE_SIZE,
            ObjectRenderer.CHUNK_SIZE * ObjectRenderer.TILE_SIZE,
        )

    def _chunk_key_for_pos(self, x: float, y: float) -> ChunkKey:
        span = self.CHUNK_SIZE * self.TILE_SIZE
        return (int(x // span), int(y // span))

    def sync(self, items: Iterable[DroppedItem]) -> None:
        self._item_to_chunk.clear()
        self._chunk_items.clear()

        buckets: dict[ChunkKey, list[DroppedItem]] = defaultdict(list)
        for item in items:
            key = self._chunk_key_for_pos(item.pos.x, item.pos.y)
            buckets[key].append(item)
            self._item_to_chunk[item.uid] = key
            self._chunk_items.setdefault(key, {})[item.uid] = item

        for key in set(self._chunks.keys()) - buckets.keys():
            self._delete_chunk(key)

        for key, chunk_items in buckets.items():
            self._rebuild_chunk(key, chunk_items)

    def sync_diff(
        self,
        added: Iterable[DroppedItem],
        removed: Iterable[DroppedItem],
        modified: Iterable[DroppedItem],
    ) -> None:
        dirty_chunks: set[ChunkKey] = set()

        for item in removed:
            key = self._item_to_chunk.pop(item.uid, None)
            if key is None:
                continue

            chunk = self._chunk_items.get(key)
            if chunk is None:
                continue

            chunk.pop(item.uid, None)
            dirty_chunks.add(key)
            if not chunk:
                self._delete_chunk(key)
                self._chunk_items.pop(key, None)
                dirty_chunks.discard(key)

        for item in added:
            key = self._chunk_key_for_pos(item.pos.x, item.pos.y)
            self._item_to_chunk[item.uid] = key
            self._chunk_items.setdefault(key, {})[item.uid] = item
            dirty_chunks.add(key)

        for item in modified:
            old_key = self._item_to_chunk.get(item.uid)
            new_key = self._chunk_key_for_pos(item.pos.x, item.pos.y)
            if old_key is None:
                self._item_to_chunk[item.uid] = new_key
                self._chunk_items.setdefault(new_key, {})[item.uid] = item
                dirty_chunks.add(new_key)
                continue

            if old_key != new_key:
                old_chunk = self._chunk_items.get(old_key)
                if old_chunk is not None:
                    old_chunk.pop(item.uid, None)
                    dirty_chunks.add(old_key)
                    if not old_chunk:
                        self._delete_chunk(old_key)
                        self._chunk_items.pop(old_key, None)
                        dirty_chunks.discard(old_key)

                self._item_to_chunk[item.uid] = new_key
                self._chunk_items.setdefault(new_key, {})[item.uid] = item
                dirty_chunks.add(new_key)
            else:
                self._chunk_items[new_key][item.uid] = item
                dirty_chunks.add(new_key)

        for key in dirty_chunks:
            chunk = self._chunk_items.get(key)
            if chunk is None:
                continue

            self._rebuild_chunk(key, chunk.values())

    def delete(self) -> None:
        for key in list(self._chunks.keys()):
            self._delete_chunk(key)

    @staticmethod
    def _signature(items: Iterable[DroppedItem]) -> tuple:
        return tuple(sorted((item.uid, item.id, item.amount, round(item.pos.x, 2), round(item.pos.y, 2)) for item in items))

    def _rebuild_chunk(self, key: ChunkKey, items: Iterable[DroppedItem]) -> None:
        items = list(items)
        signature_hash = hash(self._signature(items))
        existing = self._chunks.get(key)
        if existing is not None and existing.signature == signature_hash:
            return

        meshes = self._batch.build(self._build_commands(items), existing=existing.meshes if existing is not None else None, usage=GL_DYNAMIC_DRAW)
        self._chunks[key] = _Chunk(self._chunk_bounds(*key), meshes, len(items), signature_hash)

    def _delete_chunk(self, key: ChunkKey) -> None:
        entry = self._chunks.pop(key, None)
        if entry is not None:
            entry.meshes.delete()

        chunk = self._chunk_items.pop(key, None)
        if chunk is not None:
            for uid in chunk:
                self._item_to_chunk.pop(uid, None)

    def _build_commands(self, items: Sequence[DroppedItem]) -> list[Command]:
        commands: list[Command] = []
        build_dropped_commands(items, commands)
        return commands

    def draw(self, camera: Camera2D, culling_camera: Camera2D | None = None) -> None:
        cull = culling_camera or camera
        self._visible_count = 0
        for chunk in self._chunks.values():
            if not cull.is_visible(*chunk.bounds):
                continue
            self._visible_count += chunk.count
            self._batch.draw(camera, chunk.meshes, RenderLayer.OBJ_POST)

    def draw_shadow(self, camera: Camera2D, culling_camera: Camera2D | None = None) -> None:
        cull = culling_camera or camera
        for chunk in self._chunks.values():
            if cull.is_visible(*chunk.bounds):
                self._batch.draw_shadows(camera, chunk.meshes)

    def draw_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        for chunk in self._chunks.values():
            self._batch.draw_3d(camera3d, layer_spread, chunk.meshes, RenderLayer.OBJ_POST)

    def draw_shadow_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        for chunk in self._chunks.values():
            self._batch.draw_shadows_3d(camera3d, layer_spread, chunk.meshes)
