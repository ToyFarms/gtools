from PIL import Image
import click
from pyglm.glm import ivec2, ivec4
import numpy as np

from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.renderer.world_renderer import WorldRenderer
from gtools.core.growtopia.rttex import get_image_buffer
from gtools.core.growtopia.world import Tile, World
from gtools.core.wsl import windows_home

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

    arr = get_image_buffer(str(tex_file))
    if arr is None:
        return

    world.update_all_connection()

    renderer = WorldRenderer()
    img = np.zeros((world.height * 32, world.width * 32, 4), dtype=np.uint8)
    for tile in world.tiles:
        for cmd in renderer.get_render_cmd(tile):
            for dst in cmd.dst:
                dst = ivec4(dst)
                alpha_mask = cmd.buffer[:, :, 3] > 4
                dst_slice = img[dst.y : dst.y + dst.z, dst.x : dst.x + dst.w, :]
                dst_slice[alpha_mask] = cmd.buffer[:, :, : dst_slice.shape[2]][alpha_mask]

    Image.fromarray(img).show()
