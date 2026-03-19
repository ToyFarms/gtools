from PIL import Image
import click
import numpy as np
from pyglm.glm import ivec2, ivec4

from gtools.baked.items import PAINT_BUCKET_AQUA, PAINT_BUCKET_BLUE, PAINT_BUCKET_CHARCOAL, PAINT_BUCKET_GREEN, PAINT_BUCKET_PURPLE, PAINT_BUCKET_RED, PAINT_BUCKET_YELLOW
from gtools.core.growtopia.rttex import RTTexManager
from gtools.core.growtopia.world import Tile, TileFlags, World


@click.command()
@click.argument("id", type=int)
def paint(id: int) -> None:
    tiles: list[Tile] = []
    for i in range(1 << 3):
        pos = ivec2(i * 2 + 1, 1)
        tile = Tile(id, pos=ivec2(pos))
        tile.flags |= i << (TileFlags.PAINTED_RED.bit_length() - 1)
        tiles.append(tile)

        PAINT_LOOKUP: dict[tuple[bool, bool, bool], int] = {
            (False, False, False): 0,
            (True, False, False): PAINT_BUCKET_RED,
            (False, True, False): PAINT_BUCKET_GREEN,
            (True, True, False): PAINT_BUCKET_YELLOW,
            (False, False, True): PAINT_BUCKET_BLUE,
            (True, False, True): PAINT_BUCKET_AQUA,
            (False, True, True): PAINT_BUCKET_PURPLE,
            (True, True, True): PAINT_BUCKET_CHARCOAL,
        }
        pos.y += 1
        tile = Tile(PAINT_LOOKUP[tile.flags & TileFlags.PAINTED_RED != 0, tile.flags & TileFlags.PAINTED_GREEN != 0, tile.flags & TileFlags.PAINTED_BLUE != 0], pos=pos)
        tiles.append(tile)

    tiles.append(Tile(pos=ivec2((1 << 3) * 2, 2)))

    world = World.from_tiles(tiles)
    world.update_all_connection()

    mgr = RTTexManager()

    img = np.zeros((world.height * 32, world.width * 32, 4), dtype=np.uint8)
    for tile in world.tiles.values():
        if tile.fg_id:
            tex = tile.get_fg_texture(mgr)

            dst = ivec4(tile.pos.x * 32, tile.pos.y * 32, 32, 32)
            alpha_mask = tex[:, :, 3] > 4
            dst_slice = img[dst.y : dst.y + dst.z, dst.x : dst.x + dst.w, :]
            dst_slice[alpha_mask] = tex[:, :, : dst_slice.shape[2]][alpha_mask]

    Image.fromarray(img).show()
