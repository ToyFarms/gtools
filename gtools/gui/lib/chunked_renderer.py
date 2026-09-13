from typing import Iterable

from gtools.core.growtopia.world import Tile, World
from gtools.gui.lib.renderer import Renderer

ChunkKey = tuple[int, int]
ChunkBounds = tuple[float, float, float, float]


class ChunkedRenderer(Renderer):
    CHUNK_SIZE: int = 8
    TILE_SIZE: int = 32

    def chunk_key(self, tile: Tile) -> ChunkKey:
        return (tile.pos.x // self.CHUNK_SIZE, tile.pos.y // self.CHUNK_SIZE)

    def chunk_coords(self, tiles: Iterable[Tile]) -> set[ChunkKey]:
        return {self.chunk_key(tile) for tile in tiles}

    def chunk_tile_range(self, world: World, chunk_x: int, chunk_y: int) -> tuple[int, int, int, int]:
        start_x = chunk_x * self.CHUNK_SIZE
        start_y = chunk_y * self.CHUNK_SIZE
        end_x = min(start_x + self.CHUNK_SIZE, world.width)
        end_y = min(start_y + self.CHUNK_SIZE, world.height)
        return start_x, start_y, end_x, end_y

    def chunk_bounds(self, chunk_x: int, chunk_y: int) -> ChunkBounds:
        return (
            chunk_x * self.CHUNK_SIZE * self.TILE_SIZE - 16,
            chunk_y * self.CHUNK_SIZE * self.TILE_SIZE - 16,
            self.CHUNK_SIZE * self.TILE_SIZE,
            self.CHUNK_SIZE * self.TILE_SIZE,
        )

    def load(self, world: World) -> None:
        self.delete()
        for cx, cy in self.chunk_coords(world.tiles.values()):
            self.build_chunk(world, cx, cy)

    def build_chunk(self, world: World, chunk_x: int, chunk_y: int) -> None:
        raise NotImplementedError

    def delete_chunk(self, chunk_key: ChunkKey) -> None:
        raise NotImplementedError

    def any(self) -> bool:
        raise NotImplementedError

    def delete(self) -> None:
        raise NotImplementedError
