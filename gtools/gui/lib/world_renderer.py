from collections import defaultdict
from dataclasses import dataclass
from enum import IntFlag, auto
import ctypes
import logging

from OpenGL.GL import *  # pyright: ignore[reportWildcardImportFromLibrary]
import numpy as np
import numpy.typing as npt
from pyglm.glm import vec2, mat4x4
from pyglm import glm

from gtools import setting
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.world import Tile, World

from gtools.gui.opengl import Mesh, Uniform
from gtools.gui.texture import GLTexManager, TextureArray

logger = logging.getLogger("gui")


class Camera2D:
    def __init__(self, width: int, height: int) -> None:
        self.pos = vec2(0.0, 0.0)
        self.zoom = 1.0
        self.width = width
        self.height = height
        self.min_zoom = 0.05
        self.max_zoom = 10.0

    def proj(self) -> mat4x4:
        hw = self.width / (2.0 * self.zoom)
        hh = self.height / (2.0 * self.zoom)
        return glm.ortho(self.pos.x - hw, self.pos.x + hw, self.pos.y + hh, self.pos.y - hh, -1.0, 1.0)

    def proj_as_numpy(self) -> npt.NDArray[np.float32]:
        m = self.proj()
        ptr = glm.value_ptr(m)
        return np.frombuffer(ctypes.string_at(ptr, 16 * ctypes.sizeof(ctypes.c_float)), dtype=np.float32).reshape((4, 4), order="C")

    def screen_to_world(self, sx: float, sy: float) -> vec2:
        hw = self.width / (2.0 * self.zoom)
        hh = self.height / (2.0 * self.zoom)
        nx, ny = sx / self.width, sy / self.height
        return vec2((self.pos.x - hw) + nx * 2 * hw, (self.pos.y - hh) + ny * 2 * hh)

    def zoom_around(self, factor: float, screen_x: float, screen_y: float) -> None:
        before = self.screen_to_world(screen_x, screen_y)
        self.zoom = max(self.min_zoom, min(self.zoom * factor, self.max_zoom))
        after = self.screen_to_world(screen_x, screen_y)
        self.pos += before - after

    def pan_by_screen(self, dx: float, dy: float) -> None:
        self.pos.x -= dx / self.zoom
        self.pos.y -= dy / self.zoom

    def reset(self) -> None:
        self.pos = vec2(0.0, 0.0)
        self.zoom = 1.0

    def resize(self, width: int, height: int) -> None:
        self.width = width
        self.height = height


class WorldRenderer:
    LAYOUT = [2, 2]
    INSTANCE_LAYOUT = [2, 4, 1]
    TILE_SIZE = 32

    class Flags(IntFlag):
        NONE = 0
        RENDER_FG = auto()
        RENDER_BG = auto()

    def __init__(self, tex_mgr: GLTexManager | None = None) -> None:
        self._tex_mgr = tex_mgr if tex_mgr else GLTexManager()
        self._bg_meshes: dict[TextureArray, Mesh] = {}
        self._fg_meshes: dict[TextureArray, Mesh] = {}
        self.flags = WorldRenderer.Flags.RENDER_FG | WorldRenderer.Flags.RENDER_BG

    def load(self, world: World) -> None:
        self._build_meshes(world)
        self._tex_mgr.flush()

    def any(self) -> bool:
        return bool(self._bg_meshes) or bool(self._fg_meshes)

    def draw(self, tex: Uniform) -> None:
        if self.flags & WorldRenderer.Flags.RENDER_BG:
            for tex_array, mesh in self._bg_meshes.items():
                tex_array.bind(unit=0)
                tex.set_int(0)
                mesh.draw_instanced()
        if self.flags & WorldRenderer.Flags.RENDER_FG:
            for tex_array, mesh in self._fg_meshes.items():
                tex_array.bind(unit=0)
                tex.set_int(0)
                mesh.draw_instanced()

    @staticmethod
    def _get_unit_quad_data() -> tuple[npt.NDArray[np.float32], npt.NDArray[np.uint16]]:
        # fmt: off
        verts = np.array([
            -0.5, -0.5, 0.0, 0.0,
            0.5, -0.5, 1.0, 0.0,
            0.5,  0.5, 1.0, 1.0,
            -0.5,  0.5, 0.0, 1.0,
        ], dtype=np.float32)
        # fmt: on
        inds = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint16)
        return verts, inds

    def _build_meshes(self, world: World) -> None:
        unit_verts, unit_inds = self._get_unit_quad_data()

        bg_instances: dict[TextureArray, list[float]] = defaultdict(list)
        fg_instances: dict[TextureArray, list[float]] = defaultdict(list)

        for tile in world.tiles:
            if tile.bg_id:
                tex_array, instance_data = self._tile_instance_data(tile, tile.bg_id, tile.bg_tex_index)
                bg_instances[tex_array].extend(instance_data)
            if tile.fg_id:
                tex_array, instance_data = self._tile_instance_data(tile, tile.fg_id, tile.fg_tex_index)
                fg_instances[tex_array].extend(instance_data)

        for tex_array, instances in bg_instances.items():
            instance_arr = np.array(instances, dtype=np.float32)
            self._bg_meshes[tex_array] = Mesh(
                unit_verts.copy(),
                WorldRenderer.LAYOUT,
                unit_inds.copy(),
                instance_data=instance_arr,
                instance_layout=WorldRenderer.INSTANCE_LAYOUT,
            )

        for tex_array, instances in fg_instances.items():
            instance_arr = np.array(instances, dtype=np.float32)
            self._fg_meshes[tex_array] = Mesh(
                unit_verts.copy(),
                WorldRenderer.LAYOUT,
                unit_inds.copy(),
                instance_data=instance_arr,
                instance_layout=WorldRenderer.INSTANCE_LAYOUT,
            )

    def _tile_instance_data(self, tile: Tile, item_id: int, tex_index: int) -> tuple[TextureArray, list[float]]:
        tile_pos_x = tile.pos.x * self.TILE_SIZE
        tile_pos_y = tile.pos.y * self.TILE_SIZE

        item = item_database.get(item_id)
        tex = self._tex_mgr.push_texture(setting.asset_path / item.texture_file.decode())
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
        ]

        return tex.array, instance_data

    def delete(self) -> None:
        for mesh in self._bg_meshes.values():
            mesh.delete()
        for mesh in self._fg_meshes.values():
            mesh.delete()

        self._bg_meshes.clear()
        self._fg_meshes.clear()
