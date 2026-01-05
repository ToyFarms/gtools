from collections import defaultdict
from pyglm.glm import ivec2, vec2, vec4
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.renderer.renderer import RenderCommand
from gtools.core.growtopia.rttex import RtTexManager
from gtools.core.growtopia.world import Tile
from gtools.proxy.setting import setting


class WorldRenderer:
    def __init__(self) -> None:
        self._tex_mgr = RtTexManager()

    def render_tile(self, id: int, pos: vec2 | ivec2) -> RenderCommand:
        item = item_database.get(id)
        tex = self._tex_mgr.get(setting.asset_path / item.texture_file.decode(), item.tex_coord_x * 32, item.tex_coord_y * 32, 32, 32)

        return RenderCommand(tex, [vec4(pos.x, pos.y, 32, 32)])

    def get_render_cmd(self, tile: Tile) -> list[RenderCommand]:
        r: list[RenderCommand] = []
        if tile.bg_id != 0:
            r.append(self.render_tile(tile.bg_id, tile.pos * 32))
        if tile.fg_id != 0:
            r.append(self.render_tile(tile.fg_id, tile.pos * 32))
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

        for id, poss in bg_tile_by_types.items():
            for pos in poss:
                r.append(self.render_tile(id, pos))

        for id, poss in fg_tile_by_types.items():
            for pos in poss:
                r.append(self.render_tile(id, pos))

        return r
