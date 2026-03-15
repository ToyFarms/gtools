from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntFlag, auto
import logging
from OpenGL.GL import GL_FALSE, GL_TRUE, glDepthMask
import numpy as np
from pyglm.glm import ivec2

from gtools import setting
from gtools.core.growtopia.items_dat import ItemInfoTextureType, item_database
from gtools.core.growtopia.world import DisplayBlockTile, Tile, TileFlags, VendingMachineTile, World

from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib import layer
from gtools.gui.lib.renderer import Renderer
from gtools.gui.opengl import Mesh, ShaderProgram, Uniform
from gtools.gui.texture import TextureArray, get_tex_manager

logger = logging.getLogger("gui-world-renderer")


@dataclass
class _RenderLayer:
    depth: float
    render_flag: "WorldRenderer.Flags"
    depth_write: bool = True
    # TextureArray -> list[((x, y, w, h), Mesh)]
    chunks: dict[TextureArray, list[tuple[tuple[float, float, float, float], Mesh]]] = field(default_factory=dict)
    opacity: float = 1.0


class WorldRenderer(Renderer):
    LAYOUT = [2, 2]
    INSTANCE_LAYOUT = [2, 4, 1, 1]
    TILE_SIZE = 32

    class Flags(IntFlag):
        NONE = 0
        RENDER_FG = auto()
        RENDER_BG = auto()

    def __init__(self) -> None:
        self._tex_mgr = get_tex_manager()
        self.flags = WorldRenderer.Flags.RENDER_FG | WorldRenderer.Flags.RENDER_BG

        F = WorldRenderer.Flags
        self._layers: dict[str, _RenderLayer] = {
            "bg": _RenderLayer(layer.WORLD_BACKGROUND, F.RENDER_BG),
            "fg_before": _RenderLayer(layer.WORLD_FOREGROUND_BEFORE, F.RENDER_FG),
            "fg": _RenderLayer(layer.WORLD_FOREGROUND, F.RENDER_FG),
            "fg_after": _RenderLayer(layer.WORLD_FOREGROUND_AFTER, F.RENDER_FG, depth_write=False),
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

    def load(self, world: World) -> None:
        self._build_meshes(world)
        self._tex_mgr.flush()

    def any(self) -> bool:
        return any(rl.chunks for rl in self._layers.values())

    def draw(self, camera: Camera2D) -> None:
        if not self.any():
            return
        self._shader.use()
        self._mvp.set_mat4x4(camera.proj_as_numpy())
        self._draw_layers(camera, self._tex, self._layer, self._opacity)

    def draw_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        if not self.any():
            return
        self._shader3d.use()
        self._vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self._spread3d.set_float(layer_spread)
        self._draw_layers(None, self._tex3d, self._layer3d, self._opacity3d)

    def delete(self) -> None:
        for rl in self._layers.values():
            for chunk_list in rl.chunks.values():
                for _, mesh in chunk_list:
                    mesh.delete()
            rl.chunks.clear()

    def _draw_layers(self, camera: Camera2D | None, tex_uniform: Uniform, layer_uniform: Uniform, opacity: Uniform) -> None:
        for rl in self._layers.values():
            if not (self.flags & rl.render_flag) or not rl.chunks:
                continue

            if not rl.depth_write:
                glDepthMask(GL_FALSE)

            opacity.set_float(rl.opacity)
            layer_uniform.set_float(rl.depth)

            for tex_array, chunk_list in rl.chunks.items():
                tex_array.bind(unit=0)
                tex_uniform.set_int(0)
                for bounds, mesh in chunk_list:
                    if camera is None or camera.is_visible(*bounds):
                        mesh.draw_instanced()

            if not rl.depth_write:
                glDepthMask(GL_TRUE)

    def _build_meshes(self, world: World) -> None:
        CHUNK_SIZE = 20
        # layer -> (chunk_x, chunk_y) -> tex_array -> list[float]
        instances: dict[str, dict[tuple[int, int], dict[TextureArray, list[float]]]] = {
            key: defaultdict(lambda: defaultdict(list)) for key in self._layers
        }

        for tile in world.tiles.values():
            chunk_x = int(tile.pos.x // CHUNK_SIZE)
            chunk_y = int(tile.pos.y // CHUNK_SIZE)
            chunk_key = (chunk_x, chunk_y)

            item = item_database.get(tile.fg_id)

            if tile.bg_id:
                tex_array, data = self._tile_instance_data(tile, tile.bg_id, tile.bg_tex_index)
                instances["bg"][chunk_key][tex_array].extend(data)

            if tile.fg_id:
                handled = False

                if tile.extra:
                    if isinstance(tile.extra, DisplayBlockTile):
                        tex_array, data = self._tile_instance_data_raw(
                            tile,
                            item.texture_file.decode(),
                            ivec2(item.tex_coord_x, item.tex_coord_y + 1),
                        )
                        instances["fg_before"][chunk_key][tex_array].extend(data)

                    elif isinstance(tile.extra, VendingMachineTile):
                        tex = 0
                        tex_array, data = self._tile_instance_data_raw(
                            tile,
                            item.texture_file.decode(),
                            ivec2(item.tex_coord_x + tex, item.tex_coord_y),
                        )
                        instances["fg"][chunk_key][tex_array].extend(data)

                        if tile.flags & TileFlags.FG_ALT_MODE:  # has wl inside
                            tex_array, data = self._tile_instance_data_raw(
                                tile,
                                item.texture_file.decode(),
                                ivec2(item.tex_coord_x + 3, item.tex_coord_y),
                            )
                            instances["fg_after"][chunk_key][tex_array].extend(data)

                        if tile.extra.price == 0 or tile.extra.item_id == 0:
                            tex_array, data = self._tile_instance_data_raw(
                                tile,
                                item.texture_file.decode(),
                                ivec2(item.tex_coord_x + 2, item.tex_coord_y),
                            )
                            instances["fg_after"][chunk_key][tex_array].extend(data)

                        handled = True

                if not handled:
                    tex_array, data = self._tile_instance_data(tile, tile.fg_id, tile.fg_tex_index)
                    instances["fg"][chunk_key][tex_array].extend(data)

            if tile.flags & TileFlags.ON_FIRE:
                stride = item_database.get_tex_stride(ItemInfoTextureType.SMART_EDGE)
                tex_index = tile.overlay_tex_index
                tex_pos = ivec2(tex_index % max(stride, 1), tex_index // stride if stride else 0)

                tex_array, data = self._tile_instance_data_raw(tile, "fire.rttex", tex_pos)
                instances["fire"][chunk_key][tex_array].extend(data)
            elif tile.flags & TileFlags.IS_WET:
                stride = item_database.get_tex_stride(ItemInfoTextureType.SMART_EDGE)
                tex_index = tile.overlay_tex_index
                tex_pos = ivec2(tex_index % max(stride, 1), tex_index // stride if stride else 0)

                tex_array, data = self._tile_instance_data_raw(tile, "water.rttex", tex_pos)
                instances["water"][chunk_key][tex_array].extend(data)

        for key, chunks_data in instances.items():
            rl = self._layers[key]
            for (cx, cy), per_tex in chunks_data.items():
                # Correct bounding box for the chunk including tile size
                # Subtract 16 for center-based tiles? No, tile.pos is in 32x32 grid.
                # Actually tiles are 32x32.
                bounds = (
                    cx * CHUNK_SIZE * self.TILE_SIZE - 16,
                    cy * CHUNK_SIZE * self.TILE_SIZE - 16,
                    CHUNK_SIZE * self.TILE_SIZE,
                    CHUNK_SIZE * self.TILE_SIZE,
                )

                for tex_array, inst_list in per_tex.items():
                    mesh = Mesh(
                        Mesh.RECT_WITH_UV_VERTS,
                        WorldRenderer.LAYOUT,
                        Mesh.RECT_INDICES,
                        instance_data=np.array(inst_list, dtype=np.float32),
                        instance_layout=WorldRenderer.INSTANCE_LAYOUT,
                        instance_attrib_base=3,
                    )
                    if tex_array not in rl.chunks:
                        rl.chunks[tex_array] = []
                    rl.chunks[tex_array].append((bounds, mesh))

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
