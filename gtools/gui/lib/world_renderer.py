from collections import defaultdict
from enum import IntFlag, auto
import logging
from OpenGL.GL import GL_FALSE, GL_TRUE, glDepthMask
import numpy as np
from pyglm.glm import ivec2

from gtools import setting
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.world import DisplayBlockTile, PaintingEaselTile, Tile, TileFlags, VendingMachineTile, World

from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib import layer
from gtools.gui.lib.renderer import Renderer
from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.gui.texture import TextureArray, get_tex_manager

logger = logging.getLogger("gui-world-renderer")


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
        self._bg_meshes: dict[TextureArray, Mesh] = {}
        self._fg_meshes: dict[TextureArray, Mesh] = {}
        self._fg_before: dict[TextureArray, Mesh] = {}
        self._fg_after: dict[TextureArray, Mesh] = {}

        self.flags = WorldRenderer.Flags.RENDER_FG | WorldRenderer.Flags.RENDER_BG

        self._shader = ShaderProgram.get("shaders/world")
        self._mvp = self._shader.get_uniform("u_mvp")
        self._tex = self._shader.get_uniform("texArray")
        self._layer = self._shader.get_uniform("u_layer")

        self._shader3d = ShaderProgram.get("shaders/world3d")
        self._vp3d = self._shader3d.get_uniform("u_view_proj")
        self._tex3d = self._shader3d.get_uniform("texArray")
        self._layer3d = self._shader3d.get_uniform("u_layer")
        self._spread3d = self._shader3d.get_uniform("u_layer_spread")

    def load(self, world: World) -> None:
        self._build_meshes(world)
        self._tex_mgr.flush()

    def any(self) -> bool:
        return bool(self._bg_meshes) or bool(self._fg_meshes)

    def draw(self, camera: Camera2D) -> None:
        if not self.any():
            return

        self._shader.use()
        self._mvp.set_mat4x4(camera.proj_as_numpy())

        if self.flags & WorldRenderer.Flags.RENDER_BG:
            self._layer.set_float(layer.WORLD_BACKGROUND)
            for tex_array, mesh in self._bg_meshes.items():
                tex_array.bind(unit=0)
                self._tex.set_int(0)
                mesh.draw_instanced()
        if self.flags & WorldRenderer.Flags.RENDER_FG:
            self._layer.set_float(layer.WORLD_FOREGROUND_BEFORE)
            for tex_array, mesh in self._fg_before.items():
                tex_array.bind(unit=0)
                self._tex.set_int(0)
                mesh.draw_instanced()

            self._layer.set_float(layer.WORLD_FOREGROUND)
            for tex_array, mesh in self._fg_meshes.items():
                tex_array.bind(unit=0)
                self._tex.set_int(0)
                mesh.draw_instanced()

            glDepthMask(GL_FALSE)
            self._layer.set_float(layer.WORLD_FOREGROUND_AFTER)
            for tex_array, mesh in self._fg_after.items():
                tex_array.bind(unit=0)
                self._tex.set_int(0)
                mesh.draw_instanced()
            glDepthMask(GL_TRUE)

    def draw_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        if not self.any():
            return

        self._shader3d.use()
        self._vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self._spread3d.set_float(layer_spread)

        if self.flags & WorldRenderer.Flags.RENDER_BG:
            self._layer3d.set_float(layer.WORLD_BACKGROUND)
            for tex_array, mesh in self._bg_meshes.items():
                tex_array.bind(unit=0)
                self._tex3d.set_int(0)
                mesh.draw_instanced()
        if self.flags & WorldRenderer.Flags.RENDER_FG:
            self._layer3d.set_float(layer.WORLD_FOREGROUND_BEFORE)
            for tex_array, mesh in self._fg_before.items():
                tex_array.bind(unit=0)
                self._tex3d.set_int(0)
                mesh.draw_instanced()

            self._layer3d.set_float(layer.WORLD_FOREGROUND)
            for tex_array, mesh in self._fg_meshes.items():
                tex_array.bind(unit=0)
                self._tex3d.set_int(0)
                mesh.draw_instanced()

            glDepthMask(GL_FALSE)
            self._layer3d.set_float(layer.WORLD_FOREGROUND_AFTER)
            for tex_array, mesh in self._fg_after.items():
                tex_array.bind(unit=0)
                self._tex3d.set_int(0)
                mesh.draw_instanced()
            glDepthMask(GL_TRUE)

    def _build_meshes(self, world: World) -> None:
        bg_instances: dict[TextureArray, list[float]] = defaultdict(list)
        fg_instances: dict[TextureArray, list[float]] = defaultdict(list)
        fg_before: dict[TextureArray, list[float]] = defaultdict(list)
        fg_after: dict[TextureArray, list[float]] = defaultdict(list)

        for tile in world.tiles.values():
            if tile.bg_id:
                tex_array, instance_data = self._tile_instance_data(tile, tile.bg_id, tile.bg_tex_index)
                bg_instances[tex_array].extend(instance_data)
            if tile.fg_id:
                handled = False

                if tile.extra:
                    item = item_database.get(tile.fg_id)
                    if isinstance(tile.extra, DisplayBlockTile):
                        tex_array, instance_data = self._tile_instance_data_raw(tile, item.texture_file.decode(), ivec2(item.tex_coord_x, item.tex_coord_y + 1))
                        fg_before[tex_array].extend(instance_data)
                    elif isinstance(tile.extra, VendingMachineTile):
                        tex = 0
                        if tile.extra.item_id == 0 and tile.extra.price == 0:
                            tex = 1

                        tex_array, instance_data = self._tile_instance_data_raw(tile, item.texture_file.decode(), ivec2(item.tex_coord_x + tex, item.tex_coord_y))
                        fg_instances[tex_array].extend(instance_data)

                        # has wl inside
                        if tile.flags & TileFlags.FG_ALT_MODE:
                            tex_array, instance_data = self._tile_instance_data_raw(tile, item.texture_file.decode(), ivec2(item.tex_coord_x + 3, item.tex_coord_y))
                            fg_after[tex_array].extend(instance_data)

                        if tile.extra.price == 0 or tile.extra.item_id == 0:
                            tex_array, instance_data = self._tile_instance_data_raw(tile, item.texture_file.decode(), ivec2(item.tex_coord_x + 2, item.tex_coord_y))
                            fg_after[tex_array].extend(instance_data)

                        handled = True

                if not handled:
                    tex_array, instance_data = self._tile_instance_data(tile, tile.fg_id, tile.fg_tex_index)
                    fg_instances[tex_array].extend(instance_data)

                # TODO:
                # if item.is_steam():
                #     print(item.get_tex_stride())
                #     tex_array, instance_data = self._tile_instance_data_raw(tile, item.texture_file.decode(), ivec2(item.tex_coord_x, item.tex_coord_y + 1))
                #     fg_before[tex_array].extend(instance_data)

        for inst, meshes in (
            (bg_instances, self._bg_meshes),
            (fg_instances, self._fg_meshes),
            (fg_before, self._fg_before),
            (fg_after, self._fg_after),
        ):
            for tex_array, instances in inst.items():
                instance_arr = np.array(instances, dtype=np.float32)
                meshes[tex_array] = Mesh(
                    Mesh.RECT_WITH_UV_VERTS,
                    WorldRenderer.LAYOUT,
                    Mesh.RECT_INDICES,
                    instance_data=instance_arr,
                    instance_layout=WorldRenderer.INSTANCE_LAYOUT,
                    instance_attrib_base=3,
                )

    def _tile_instance_data(self, tile: Tile, item_id: int, tex_index: int) -> tuple[TextureArray, list[float]]:
        tile_pos_x = tile.pos.x * self.TILE_SIZE
        tile_pos_y = tile.pos.y * self.TILE_SIZE

        item = item_database.get(item_id)
        tex = self._tex_mgr.load_texture(setting.asset_path / "game" / item.texture_file.decode())
        tex_pos, is_flipped = tile.tex_pos(item_id, tex_index)

        u0 = (tex_pos.x * self.TILE_SIZE) / tex.width
        v0 = (tex_pos.y * self.TILE_SIZE) / tex.height
        u1 = ((tex_pos.x + 1) * self.TILE_SIZE) / tex.width
        v1 = ((tex_pos.y + 1) * self.TILE_SIZE) / tex.height

        if is_flipped:
            u0, u1 = u1, u0

        instance_data = [
            tile_pos_x,
            tile_pos_y,
            u0,
            v0,
            u1,
            v1,
            float(tex.layer),
            float(tile.get_paint_index()),
        ]

        return tex.array, instance_data

    def _tile_instance_data_raw(self, tile: Tile, texture_file: str, tex_pos: ivec2) -> tuple[TextureArray, list[float]]:
        tile_pos_x = tile.pos.x * self.TILE_SIZE
        tile_pos_y = tile.pos.y * self.TILE_SIZE

        tex = self._tex_mgr.load_texture(setting.asset_path / "game" / texture_file)
        u0 = (tex_pos.x * self.TILE_SIZE) / tex.width
        v0 = (tex_pos.y * self.TILE_SIZE) / tex.height
        u1 = ((tex_pos.x + 1) * self.TILE_SIZE) / tex.width
        v1 = ((tex_pos.y + 1) * self.TILE_SIZE) / tex.height

        instance_data = [
            tile_pos_x,
            tile_pos_y,
            u0,
            v0,
            u1,
            v1,
            float(tex.layer),
            float(tile.get_paint_index()),
        ]

        return tex.array, instance_data

    def delete(self) -> None:
        for meshes in (self._bg_meshes, self._fg_meshes, self._fg_before, self._fg_after):
            for mesh in meshes.values():
                mesh.delete()

            meshes.clear()
