from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntFlag, auto
import logging
from OpenGL.GL import GL_FALSE, GL_TRUE, glDepthMask
import numpy as np
from pyglm.glm import ivec2

from gtools import setting
from gtools.baked.items import STEAM_REVOLVER, STEAM_TUBES
from gtools.core.growtopia.items_dat import ItemInfoTextureType, get_tex_stride, item_database
from gtools.core.growtopia.world import DisplayBlockTile, SeedTile, Tile, TileFlags, VendingMachineTile, World

from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib import layer
from gtools.gui.lib.renderer import Renderer
from gtools.gui.lib.tree_renderer import TreeMesh, TreeRenderer
from gtools.gui.opengl import Mesh, ShaderProgram, Uniform
from gtools.gui.texture import GLTexManager, TextureArray

logger = logging.getLogger("gui-world-renderer")


@dataclass
class _RenderLayer:
    depth: float
    render_flag: "TileRenderer.Flags"
    depth_write: bool = True
    # TextureArray -> list[((x, y, w, h), Mesh)]
    chunks: dict[TextureArray, list[tuple[tuple[float, float, float, float], Mesh]]] = field(default_factory=dict)
    opacity: float = 1.0


class TileRenderer(Renderer):
    LAYOUT = [2, 2]
    INSTANCE_LAYOUT = [2, 4, 1, 1]
    TILE_SIZE = 32

    class Flags(IntFlag):
        NONE = 0
        RENDER_FG = auto()
        RENDER_BG = auto()

    def __init__(self) -> None:
        self._tex_mgr = GLTexManager()
        self.flags = TileRenderer.Flags.RENDER_FG | TileRenderer.Flags.RENDER_BG

        F = TileRenderer.Flags
        self._layers: dict[str, _RenderLayer] = {
            "bg": _RenderLayer(layer.WORLD_BACKGROUND, F.RENDER_BG),
            "fg_before": _RenderLayer(layer.WORLD_PRE_FOREGROUND, F.RENDER_FG),
            "fg": _RenderLayer(layer.WORLD_FOREGROUND, F.RENDER_FG),
            "fg_after": _RenderLayer(layer.WORLD_POST_FOREGROUND, F.RENDER_FG, depth_write=False),
            "fire": _RenderLayer(layer.WORLD_FIRE, F.RENDER_FG, opacity=0.75),
            "water": _RenderLayer(layer.WORLD_WATER, F.RENDER_FG, opacity=0.75),
        }

        self._shader = ShaderProgram.get("shaders/world")
        self._mvp = self._shader.get_uniform("u_mvp")
        self._tex = self._shader.get_uniform("texArray")
        self._layer = self._shader.get_uniform("u_layer")
        self._opacity = self._shader.get_uniform("u_opacity")

        self._shader3d = ShaderProgram.get("shaders/world3d")
        self._vp3d = self._shader3d.get_uniform("u_view_proj")
        self._tex3d = self._shader3d.get_uniform("texArray")
        self._layer3d = self._shader3d.get_uniform("u_layer")
        self._spread3d = self._shader3d.get_uniform("u_layer_spread")
        self._opacity3d = self._shader3d.get_uniform("u_opacity")

        self._tree_renderer = TreeRenderer()
        self.tree_mesh: TreeMesh | None = None
        self._chunk_meshes: dict[tuple[int, int], list[tuple[str, TextureArray, Mesh]]] = {}
        self.CHUNK_SIZE = 8

    def load(self, world: World) -> None:
        self.delete()
        self._build_meshes(world)
        self._tex_mgr.flush()

    def any(self) -> bool:
        return any(rl.chunks for rl in self._layers.values())

    def draw(self, camera: Camera2D, layer: str | None = None, culling_camera: Camera2D | None = None) -> None:
        if not self.any():
            return

        self._shader.use()
        self._mvp.set_mat4x4(camera.proj_as_numpy())
        if layer:
            self.draw_layer(layer, camera, self._tex, self._layer, self._opacity, culling_camera=culling_camera)
        else:
            self._draw_layers(camera, self._tex, self._layer, self._opacity, culling_camera=culling_camera)
        if self.tree_mesh:
            self._tree_renderer.draw(camera, self.tree_mesh, culling_camera=culling_camera)

    def draw_3d(self, camera3d: Camera3D, layer_spread: float, layer: str | None = None) -> None:
        if not self.any():
            return

        self._shader3d.use()
        self._vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self._spread3d.set_float(layer_spread)
        if layer:
            self.draw_layer(layer, None, self._tex3d, self._layer3d, self._opacity3d)
        else:
            self._draw_layers(None, self._tex3d, self._layer3d, self._opacity3d)
        if self.tree_mesh:
            self._tree_renderer.draw_3d(camera3d, self.tree_mesh, layer_spread)

    def delete(self) -> None:
        if self.tree_mesh:
            self.tree_mesh.delete()
            self.tree_mesh = None

        for chunk_list in self._chunk_meshes.values():
            for _, _, mesh in chunk_list:
                mesh.delete()
        self._chunk_meshes.clear()

        for rl in self._layers.values():
            rl.chunks.clear()

    def _draw_layers(self, camera: Camera2D | None, tex_uniform: Uniform, layer_uniform: Uniform, opacity: Uniform, culling_camera: Camera2D | None = None) -> None:
        for rl in self._layers.values():
            if not (self.flags & rl.render_flag) or not rl.chunks:
                continue

            if not rl.depth_write:
                glDepthMask(GL_FALSE)

            opacity.set_float(rl.opacity)
            layer_uniform.set_float(rl.depth)

            cull = culling_camera or camera
            for tex_array, chunk_list in rl.chunks.items():
                tex_array.bind(unit=0)
                tex_uniform.set_int(0)
                for bounds, mesh in chunk_list:
                    if cull is None or cull.is_visible(*bounds):
                        mesh.draw_instanced()

            if not rl.depth_write:
                glDepthMask(GL_TRUE)

    def draw_layer(self, layer: str, camera: Camera2D | None, tex_uniform: Uniform, layer_uniform: Uniform, opacity: Uniform, culling_camera: Camera2D | None = None) -> None:
        rl = self._layers[layer]
        if not (self.flags & rl.render_flag) or not rl.chunks:
            return

        if not rl.depth_write:
            glDepthMask(GL_FALSE)

        opacity.set_float(rl.opacity)
        layer_uniform.set_float(rl.depth)

        cull = culling_camera or camera
        for tex_array, chunk_list in rl.chunks.items():
            tex_array.bind(unit=0)
            tex_uniform.set_int(0)
            for bounds, mesh in chunk_list:
                if cull is None or cull.is_visible(*bounds):
                    mesh.draw_instanced()

        if not rl.depth_write:
            glDepthMask(GL_TRUE)

    def delete_chunk(self, chunk_key: tuple[int, int]) -> None:
        if chunk_key not in self._chunk_meshes:
            return

        for layer_name, tex_array, mesh in self._chunk_meshes[chunk_key]:
            rl = self._layers[layer_name]
            if tex_array in rl.chunks:
                rl.chunks[tex_array] = [x for x in rl.chunks[tex_array] if x[1] != mesh]
            mesh.delete()

        del self._chunk_meshes[chunk_key]

    def _build_meshes(self, world: World) -> None:
        self.delete()

        chunk_coords = set()
        for tile in world.tiles.values():
            chunk_coords.add((tile.pos.x // self.CHUNK_SIZE, tile.pos.y // self.CHUNK_SIZE))

        for cx, cy in chunk_coords:
            self._build_chunk(world, cx, cy)

        trees = [t for t in world.tiles.values() if t.fg_id and t.extra and isinstance(t.extra, SeedTile)]
        self.tree_mesh = self._tree_renderer.build(trees)

    def _build_chunk(self, world: World, chunk_x: int, chunk_y: int) -> None:
        # layer -> tex_array -> list[float]
        instances: dict[str, dict[TextureArray, list[float]]] = {key: defaultdict(list) for key in self._layers}

        start_x = chunk_x * self.CHUNK_SIZE
        start_y = chunk_y * self.CHUNK_SIZE
        end_x = min(start_x + self.CHUNK_SIZE, world.width)
        end_y = min(start_y + self.CHUNK_SIZE, world.height)

        for y in range(start_y, end_y):
            for x in range(start_x, end_x):
                tile = world.get_tile(x, y)
                if not tile:
                    continue

                item = item_database.get(tile.fg_id)

                if tile.bg_id:
                    tex_array, data = self._tile_instance_data(tile, tile.bg_id, tile.bg_tex_index)
                    instances["bg"][tex_array].extend(data)

                if tile.fg_id:
                    handled = False

                    if tile.extra:
                        if isinstance(tile.extra, DisplayBlockTile):
                            tex_array, data = self._tile_instance_data_raw(
                                tile,
                                item.texture_file.decode(),
                                ivec2(item.tex_coord_x, item.tex_coord_y + 1),
                            )
                            instances["fg_before"][tex_array].extend(data)

                        elif isinstance(tile.extra, VendingMachineTile):
                            tex = 0
                            if tile.extra.price == 0 and tile.extra.item_id == 0:
                                tex = 1

                            tex_array, data = self._tile_instance_data_raw(
                                tile,
                                item.texture_file.decode(),
                                ivec2(item.tex_coord_x + tex, item.tex_coord_y),
                            )
                            instances["fg"][tex_array].extend(data)

                            if tile.flags & TileFlags.FG_ALT_MODE:  # has wl inside
                                tex_array, data = self._tile_instance_data_raw(
                                    tile,
                                    item.texture_file.decode(),
                                    ivec2(item.tex_coord_x + 3, item.tex_coord_y),
                                )
                                instances["fg_after"][tex_array].extend(data)

                            if tile.extra.price == 0 or tile.extra.item_id == 0:
                                tex_array, data = self._tile_instance_data_raw(
                                    tile,
                                    item.texture_file.decode(),
                                    ivec2(item.tex_coord_x + 2, item.tex_coord_y),
                                )
                                instances["fg_after"][tex_array].extend(data)

                            handled = True
                        elif isinstance(tile.extra, SeedTile):
                            handled = True

                    if item.is_steam():
                        anchor = item_database.get(STEAM_TUBES)
                        tex_pos = ivec2(anchor.tex_coord_x + 1, anchor.tex_coord_y)
                        stride = get_tex_stride(ItemInfoTextureType.SMART_EDGE)
                        off = ivec2(tile.fg_tex_index % max(stride, 1), tile.fg_tex_index // stride if stride else 0)

                        tex_array, data = self._tile_instance_data_raw(tile, anchor.texture_file.decode(), tex_pos + off)
                        instances["fg_after"][tex_array].extend(data)
                    elif tile.fg_id == STEAM_REVOLVER:
                        tex_array, data = self._tile_instance_data_raw(
                            tile,
                            item.texture_file.decode(),
                            ivec2(item.tex_coord_x, item.tex_coord_y + 1),
                        )
                        instances["fg_after"][tex_array].extend(data)

                    if not handled:
                        tex_array, data = self._tile_instance_data(tile, tile.fg_id, tile.fg_tex_index)
                        instances["fg"][tex_array].extend(data)

                if tile.flags & TileFlags.ON_FIRE:
                    stride = get_tex_stride(ItemInfoTextureType.SMART_EDGE)
                    tex_index = tile.overlay_tex_index
                    tex_pos = ivec2(tex_index % max(stride, 1), tex_index // stride if stride else 0)

                    tex_array, data = self._tile_instance_data_raw(tile, "fire.rttex", tex_pos)
                    instances["fire"][tex_array].extend(data)
                elif tile.flags & TileFlags.IS_WET:
                    stride = get_tex_stride(ItemInfoTextureType.SMART_EDGE)
                    tex_index = tile.overlay_tex_index
                    tex_pos = ivec2(tex_index % max(stride, 1), tex_index // stride if stride else 0)

                    tex_array, data = self._tile_instance_data_raw(tile, "water.rttex", tex_pos)
                    instances["water"][tex_array].extend(data)

        bounds = (
            chunk_x * self.CHUNK_SIZE * self.TILE_SIZE - 16,
            chunk_y * self.CHUNK_SIZE * self.TILE_SIZE - 16,
            self.CHUNK_SIZE * self.TILE_SIZE,
            self.CHUNK_SIZE * self.TILE_SIZE,
        )

        chunk_key = (chunk_x, chunk_y)
        self._chunk_meshes[chunk_key] = []

        for layer_key, per_tex in instances.items():
            rl = self._layers[layer_key]
            for tex_array, inst_list in per_tex.items():
                if not inst_list:
                    continue
                mesh = Mesh(
                    Mesh.RECT_WITH_UV_VERTS,
                    TileRenderer.LAYOUT,
                    Mesh.RECT_INDICES,
                    instance_data=np.array(inst_list, dtype=np.float32),
                    instance_layout=TileRenderer.INSTANCE_LAYOUT,
                    instance_attrib_base=3,
                )
                if tex_array not in rl.chunks:
                    rl.chunks[tex_array] = []
                rl.chunks[tex_array].append((bounds, mesh))
                self._chunk_meshes[chunk_key].append((layer_key, tex_array, mesh))

    def _tile_instance_data(self, tile: Tile, item_id: int, tex_index: int) -> tuple[TextureArray, list[float]]:
        item = item_database.get(item_id)
        tex = self._tex_mgr.load_texture(setting.asset_path / "game" / item.texture_file.decode())
        tex_pos, is_flipped = tile.tex_pos(item_id, tex_index)

        u0 = (tex_pos.x * self.TILE_SIZE) / tex.width
        v0 = (tex_pos.y * self.TILE_SIZE) / tex.height
        u1 = ((tex_pos.x + 1) * self.TILE_SIZE) / tex.width
        v1 = ((tex_pos.y + 1) * self.TILE_SIZE) / tex.height
        if is_flipped:
            u0, u1 = u1, u0

        return tex.array, [
            tile.pos.x * self.TILE_SIZE,
            tile.pos.y * self.TILE_SIZE,
            u0,
            v0,
            u1,
            v1,
            float(tex.layer),
            float(tile.get_paint_index()),
        ]

    def _tile_instance_data_raw(self, tile: Tile, texture_file: str, tex_pos: ivec2) -> tuple[TextureArray, list[float]]:
        tex = self._tex_mgr.load_texture(setting.asset_path / "game" / texture_file)
        u0 = (tex_pos.x * self.TILE_SIZE) / tex.width
        v0 = (tex_pos.y * self.TILE_SIZE) / tex.height
        u1 = ((tex_pos.x + 1) * self.TILE_SIZE) / tex.width
        v1 = ((tex_pos.y + 1) * self.TILE_SIZE) / tex.height

        return tex.array, [
            tile.pos.x * self.TILE_SIZE,
            tile.pos.y * self.TILE_SIZE,
            u0,
            v0,
            u1,
            v1,
            float(tex.layer),
            float(tile.get_paint_index()),
        ]
