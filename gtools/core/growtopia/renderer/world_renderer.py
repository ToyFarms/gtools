from collections import defaultdict
from pyglm.glm import ivec2, vec2, vec4
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.renderer.renderer import RenderCommand
from gtools.core.growtopia.rttex import RtTexManager
from gtools.core.growtopia.world import Tile
from gtools.proxy.setting import setting
import numpy as np
import numpy.typing as npt


class WorldRenderer:
    def __init__(self) -> None:
        self._tex_mgr = RtTexManager()

    def get_tex_from_id(self, id: int, offset: int = 0, stride: int = 0) -> npt.NDArray[np.uint8]:
        try:
            item = item_database.get(id)
        except:
            item = item_database.get(18)

        tex = (ivec2(item.tex_coord_x, item.tex_coord_y) + ivec2(offset % stride, offset // stride)) * 32
        return self._tex_mgr.get(setting.asset_path / item.texture_file.decode(), tex.x, tex.y, 32, 32)

    def get_render_cmd(self, tile: Tile) -> list[RenderCommand]:
        r: list[RenderCommand] = []
        if tile.bg_id != 0:
            r.append(RenderCommand(tile.get_bg_texture(self._tex_mgr), [vec4(tile.pos.x * 32, tile.pos.y * 32, 32, 32)]))
        if tile.fg_id != 0:
            r.append(RenderCommand(tile.get_fg_texture(self._tex_mgr), [vec4(tile.pos.x * 32, tile.pos.y * 32, 32, 32)]))
        return r

    # TODO: batch_render is not really faster than normal, probably because its just the same thing rebranded
    # TODO: render command doesnt have the thing to become frontend agnostic yet, need to rethink what it would actually need
    def batch_render_cmd(self, tiles: list[Tile]) -> list[RenderCommand]:
        r: list[RenderCommand] = []
        bg_tile_by_types: defaultdict[int, list[ivec2]] = defaultdict(list)
        fg_tile_by_types: defaultdict[int, list[ivec2]] = defaultdict(list)
        for tile in tiles:
            bg_tile_by_types[tile.bg_id].append(tile.pos * 32)
            fg_tile_by_types[tile.fg_id].append(tile.pos * 32)

        # TODO: we cannot batch with different tex index
        for id, pos_list in bg_tile_by_types.items():
            r.append(RenderCommand(self.get_tex(id), list(map(lambda x: vec4(x.x, x.y, 32, 32), pos_list))))
        for id, pos_list in fg_tile_by_types.items():
            r.append(RenderCommand(self.get_tex(id), list(map(lambda x: vec4(x.x, x.y, 32, 32), pos_list))))

        return r
