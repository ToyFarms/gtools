from pathlib import Path
from PIL import Image
import click
from pyglm.glm import ivec2, ivec4
import numpy as np

from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.rttex import get_image_buffer
from gtools.core.growtopia.world import Tile, World
from gtools.core.wsl import windows_home
from gtools.protogen.growtopia_pb2 import Item


def get_tile_index(world: World, tile: Tile) -> int:
    connectivity = 0

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
    item = item_database.get(id)
    tex_file = windows_home() / "AppData/Local/Growtopia/game" / item.texture_file.decode()

    arr = get_image_buffer(str(tex_file))
    if arr is None:
        return

    base = ivec2(item.tex_coord_x, item.tex_coord_y) * 32

    tile = arr[base.y:base.y + 32, base.x:base.x + 32, :]

    tile_configuration = len(autotile_47)
    img_width = tile_configuration * 32 * 3 + tile_configuration * 5
    img_height = 32 * 3

    img = np.zeros((img_height, img_width, 4), dtype=np.uint8)
    for c, conf in enumerate(autotile_47):
        for y, row in enumerate(conf):
            for x, col in enumerate(row):
                if not col:
                    continue

                dst = ivec4((x + c * 3) * 32 + c * 5, y * 32, 32, 32)
                img[dst.y:dst.y+32, dst.x:dst.x+32, :] = tile

    Image.fromarray(img).show()
