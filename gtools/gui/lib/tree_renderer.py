from dataclasses import dataclass
from OpenGL.GL import GL_DEPTH_TEST, glDisable, glEnable
from OpenGL.raw.GL._types import GL_UNSIGNED_INT
from pyglm.glm import vec2
from gtools import setting
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.world import DroppedItem, SeedTile, Tile, World
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.chunked_renderer import ChunkBounds, ChunkedRenderer, ChunkKey
from gtools.gui.lib.layer import OBJECT_POST_FOREGROUND_END, OBJECT_POST_FOREGROUND_START, WORLD_FOREGROUND
from gtools.gui.lib.object_renderer import ObjectRenderMesh, ObjectRenderer
from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.gui.texture import GLTexManager
import numpy as np


@dataclass(slots=True)
class TreeMesh:
    tree: Mesh | None
    object: ObjectRenderMesh | None

    def delete(self) -> None:
        if self.tree:
            self.tree.delete()
        if self.object:
            self.object.delete()


# TODO: scale based on time left
r"""
Time Formula

In this case,

r = rarity
t = time taken (seconds)

The formula to figure out the time, based on rarity is:

t = r³ + 30r
Rarity Formula

In this case,

r = rarity
t = time taken (seconds)

r = cbrt(t/2 + sqrt(t^2/4 + 1000)) + cbrt(t/2 - sqrt(t^2/4 + 1000))
"""

_TREE_ITEM_OFFSET = {
    0: (-4, -7),
    1: (6, -7),
    2: (-10, 2),
    3: (0, 2),
}


class TreeRenderer(ChunkedRenderer):
    def __init__(self) -> None:
        self.tex_mgr = GLTexManager()
        self.tex = self.tex_mgr.load_texture(setting.gt_path / "game/tiles_page1.rttex")
        self.tex_mgr.flush()

        self.shader = ShaderProgram.get("shaders/seed")
        self.texture = self.shader.get_uniform("u_texture")
        self.mvp = self.shader.get_uniform("u_mvp")
        self.tile_size = self.shader.get_uniform("u_tileSize")

        self.shader3d = ShaderProgram.from_files("shaders/seed3d.vert", "shaders/seed.frag")
        self.vp3d = self.shader3d.get_uniform("u_view_proj")
        self.tex3d = self.shader3d.get_uniform("u_texture")
        self.spread3d = self.shader3d.get_uniform("u_layer_spread")
        self.tile_size3d = self.shader3d.get_uniform("u_tileSize")

        self._obj_renderer = ObjectRenderer(OBJECT_POST_FOREGROUND_START, OBJECT_POST_FOREGROUND_END)
        self._chunks: dict[ChunkKey, tuple[ChunkBounds, TreeMesh]] = {}

    def any(self) -> bool:
        return bool(self._chunks)

    def build_chunk(self, world: World, chunk_x: int, chunk_y: int) -> None:
        start_x, start_y, end_x, end_y = self.chunk_tile_range(world, chunk_x, chunk_y)

        tiles: list[Tile] = []
        for y in range(start_y, end_y):
            for x in range(start_x, end_x):
                tile = world.get_tile(x, y)
                if tile and tile.fg_id and tile.extra is not None and isinstance(tile.extra, SeedTile):
                    tiles.append(tile)

        if not tiles:
            return

        mesh = self._build_mesh(tiles)
        self._chunks[(chunk_x, chunk_y)] = (self.chunk_bounds(chunk_x, chunk_y), mesh)

    def delete_chunk(self, chunk_key: ChunkKey) -> None:
        entry = self._chunks.pop(chunk_key, None)
        if entry is not None:
            _, mesh = entry
            mesh.delete()

    def _build_mesh(self, tiles: list[Tile]) -> TreeMesh:
        data_dtype = np.dtype(
            [
                ("tilePos", np.float32, 3),
                ("baseColor", np.uint32),
                ("overlayColor", np.uint32),
                ("baseTexCoord", np.float32, 2),
                ("overlayTexCoord", np.float32, 2),
                ("layer", np.float32),
            ]
        )
        data = np.zeros(len(tiles), dtype=data_dtype)

        tex_w = self.tex.width
        tex_h = self.tex.height
        items: list[DroppedItem] = []

        for i, tile in enumerate(tiles):
            if tile.extra is None or not isinstance(tile.extra, SeedTile):
                continue

            item = item_database.get(tile.fg_id)

            overlay_r = item.seed_overlay_color.r
            overlay_g = item.seed_overlay_color.g
            overlay_b = item.seed_overlay_color.b
            overlay_color = (overlay_r << 24) | (overlay_g << 16) | (overlay_b << 8)

            trunk = item.seed_base.value % 8
            leaf = item.seed_overlay.value % 8

            data[i]["tilePos"] = [tile.pos.x * 32, tile.pos.y * 32, WORLD_FOREGROUND]
            data[i]["baseColor"] = item.seed_color.to_rgba()
            data[i]["overlayColor"] = overlay_color
            data[i]["baseTexCoord"] = [trunk * 32 / tex_w, 19 * 32 / tex_h]
            data[i]["overlayTexCoord"] = [leaf * 32 / tex_w, 18 * 32 / tex_h]
            data[i]["layer"] = self.tex.layer

            for j in range(tile.extra.item_on_tree):
                # fg_id is seed, -1 becomes the item
                items.append(DroppedItem(tile.fg_id - 1, pos=vec2(tile.pos) * 32 + vec2(_TREE_ITEM_OFFSET[j]), amount=1))

        return TreeMesh(
            tree=(
                Mesh(
                    Mesh.RECT_WITH_UV_VERTS,
                    [2, 2],
                    Mesh.RECT_INDICES,
                    instance_data=data,
                    instance_layout=[3, (1, GL_UNSIGNED_INT), (1, GL_UNSIGNED_INT), 2, 2, 1],
                    instance_attrib_base=2,
                )
                if items
                else None
            ),
            object=(
                self._obj_renderer.build(items, flags=ObjectRenderer.Flags.NO_OVERLAY | ObjectRenderer.Flags.NO_SHADOW | ObjectRenderer.Flags.NO_TEXT, icon_scale=0.25)
                if items
                else None
            ),
        )

    def draw(self, camera: Camera2D, culling_camera: Camera2D | None = None) -> None:
        if not self.tex or not self._chunks:
            return

        self.shader.use()
        self.mvp.set_mat4x4(camera.proj_as_numpy())
        self.tile_size.set_float(32.0)
        self.tex.array.bind(unit=0)
        self.texture.set_int(0)

        cull = culling_camera or camera
        visible_meshes = [mesh for bounds, mesh in self._chunks.values() if cull is None or cull.is_visible(*bounds)]

        for mesh in visible_meshes:
            if mesh.tree:
                mesh.tree.draw_instanced()

        for mesh in visible_meshes:
            if mesh.object:
                self._obj_renderer.draw(camera, mesh.object)

    def draw_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        if not self.tex or not self._chunks:
            return

        self.shader3d.use()
        self.vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self.spread3d.set_float(layer_spread)
        self.tile_size3d.set_float(32.0)
        self.tex.array.bind(unit=0)
        self.tex3d.set_int(0)

        for _, mesh in self._chunks.values():
            if mesh.tree:
                mesh.tree.draw_instanced()
            if mesh.object:
                self._obj_renderer.draw_3d(camera3d, mesh.object, layer_spread)

    def delete(self) -> None:
        for key in list(self._chunks.keys()):
            self.delete_chunk(key)
        self._obj_renderer.delete()
