from PIL import Image
import click
from pyglm.glm import ivec2, ivec4
import numpy as np

from gtools.core.growtopia.rttex import RTTexManager
from gtools.core.growtopia.world import Tile, World

autotile_47 = [
    [
        [0, 0, 0],
        [0, 1, 0],
        [0, 0, 0],
    ],
    [
        [0, 1, 0],
        [0, 1, 0],
        [0, 0, 0],
    ],
    [
        [0, 0, 0],
        [0, 1, 1],
        [0, 0, 0],
    ],
    [
        [0, 0, 0],
        [0, 1, 0],
        [0, 1, 0],
    ],
    [
        [0, 0, 0],
        [1, 1, 0],
        [0, 0, 0],
    ],
    [
        [0, 1, 0],
        [0, 1, 0],
        [0, 1, 0],
    ],
    [
        [0, 0, 0],
        [1, 1, 1],
        [0, 0, 0],
    ],
    [
        [0, 1, 0],
        [0, 1, 1],
        [0, 0, 0],
    ],
    [
        [0, 1, 0],
        [1, 1, 0],
        [0, 0, 0],
    ],
    [
        [0, 0, 0],
        [1, 1, 0],
        [0, 1, 0],
    ],
    [
        [0, 0, 0],
        [0, 1, 1],
        [0, 1, 0],
    ],
    [
        [0, 1, 0],
        [1, 1, 1],
        [0, 0, 0],
    ],
    [
        [0, 0, 0],
        [1, 1, 1],
        [0, 1, 0],
    ],
    [
        [0, 1, 0],
        [0, 1, 1],
        [0, 1, 0],
    ],
    [
        [0, 1, 0],
        [1, 1, 0],
        [0, 1, 0],
    ],
    [
        [0, 1, 0],
        [1, 1, 1],
        [0, 1, 0],
    ],
    [
        [1, 1, 0],
        [1, 1, 0],
        [0, 0, 0],
    ],
    [
        [0, 1, 1],
        [0, 1, 1],
        [0, 0, 0],
    ],
    [
        [0, 0, 0],
        [1, 1, 0],
        [1, 1, 0],
    ],
    [
        [0, 0, 0],
        [0, 1, 1],
        [0, 1, 1],
    ],
    [
        [0, 1, 0],
        [1, 1, 1],
        [1, 0, 0],
    ],
    [
        [0, 1, 0],
        [1, 1, 1],
        [0, 0, 1],
    ],
    [
        [1, 0, 0],
        [1, 1, 1],
        [0, 1, 0],
    ],
    [
        [0, 0, 1],
        [1, 1, 1],
        [0, 1, 0],
    ],
    [
        [0, 1, 1],
        [1, 1, 1],
        [1, 1, 1],
    ],
    [
        [1, 1, 0],
        [1, 1, 1],
        [1, 1, 1],
    ],
    [
        [1, 1, 1],
        [1, 1, 1],
        [0, 1, 1],
    ],
    [
        [1, 1, 1],
        [1, 1, 1],
        [1, 1, 0],
    ],
    [
        [1, 1, 1],
        [1, 1, 1],
        [1, 1, 1],
    ],
]


@click.command()
@click.argument("id", type=int)
def tileset(id: int) -> None:
    world = World()
    for c, conf in enumerate(autotile_47):
        for y, row in enumerate(conf):
            for x, col in enumerate(row):
                pos = ivec2(x + c * 4, y)
                world.width = max(world.width, pos.x)
                world.height = max(world.height, pos.y)
                if not col:
                    world.tiles.append(Tile(0, pos=pos))
                else:
                    world.tiles.append(Tile(id, pos=pos))

    world.fix()
    world.update_all_connection()
    mgr = RTTexManager()

    img = np.zeros((world.height * 32, world.width * 32, 4), dtype=np.uint8)
    for tile in world.tiles:
        if tile.bg_id > 0:
            tex = tile.get_bg_texture(mgr)
            dst = ivec4(tile.pos.x * 32, tile.pos.y * 32, 32, 32)
            alpha_mask = tex[:, :, 3] > 4
            dst_slice = img[dst.y : dst.y + dst.z, dst.x : dst.x + dst.w, :]
            dst_slice[alpha_mask] = tex[:, :, : dst_slice.shape[2]][alpha_mask]

        if tile.fg_id > 0:
            tex = tile.get_fg_texture(mgr)
            dst = ivec4(tile.pos.x * 32, tile.pos.y * 32, 32, 32)
            alpha_mask = tex[:, :, 3] > 4
            dst_slice = img[dst.y : dst.y + dst.z, dst.x : dst.x + dst.w, :]
            dst_slice[alpha_mask] = tex[:, :, : dst_slice.shape[2]][alpha_mask]

    Image.fromarray(img).show()
