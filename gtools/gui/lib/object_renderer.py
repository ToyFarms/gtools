from collections import defaultdict

from gtools import setting
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.world import World
from gtools.gui.camera import Camera2D
from gtools.gui.lib.layer import OBJECT_DROPPED_END, OBJECT_DROPPED_START
from gtools.gui.lib.renderer import Renderer
from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.gui.texture import TextureArray, get_tex_manager
import numpy as np

MAX_DROPPED = 10000
LAYER_RANGE = OBJECT_DROPPED_END - OBJECT_DROPPED_START

SUBLAYER_ICON = 0
SUBLAYER_OVERLAY = 1
LAYER_STRIDE = 2

MAX_LAYER = MAX_DROPPED * LAYER_STRIDE


class ObjectRenderer(Renderer):
    LAYOUT = [2, 2]
    INSTANCE_LAYOUT = [2, 2, 2, 1, 1]

    def __init__(self) -> None:
        self._tex_mgr = get_tex_manager()
        self._dropped_meshes: dict[TextureArray, Mesh] = {}
        self._pickup_overlay: dict[TextureArray, Mesh] = {}

        self._shader = ShaderProgram.get("shaders/object")
        self._mvp = self._shader.get_uniform("u_mvp")
        self._tex = self._shader.get_uniform("texArray")
        self._tile_size = self._shader.get_uniform("u_tileSize")

    def draw(self, camera: Camera2D) -> None:
        if not self._dropped_meshes:
            return

        self._shader.use()
        self._mvp.set_mat4x4(camera.proj_as_numpy())

        self._tile_size.set_float(20.0)
        for arr, mesh in self._pickup_overlay.items():
            arr.bind(unit=0)
            self._tex.set_int(0)
            mesh.draw_instanced()

        self._tile_size.set_float(32.0)
        for arr, mesh in self._dropped_meshes.items():
            arr.bind(unit=0)
            self._tex.set_int(0)
            mesh.draw_instanced()

    def get_object_z(self, index: int, sublayer: int) -> float:
        slot = index * LAYER_STRIDE + sublayer
        t = slot / MAX_LAYER

        return OBJECT_DROPPED_START + t * LAYER_RANGE

    def load(self, world: World) -> None:
        instances: dict[TextureArray, list[float]] = defaultdict(list)
        overlay: dict[TextureArray, list[float]] = defaultdict(list)

        for i, dropped in enumerate(world.dropped.items):
            item = item_database.get(dropped.id)
            tex = self._tex_mgr.push_texture(setting.asset_path / "game" / item.texture_file.decode())
            instances[tex.array].extend(
                [
                    dropped.pos.x,
                    dropped.pos.y,
                    0.5,
                    0.5,
                    item.tex_coord_x * 32 / tex.width,
                    item.tex_coord_y * 32 / tex.height,
                    tex.layer,
                    self.get_object_z(i, SUBLAYER_ICON),
                ]
            )

            overlay_tex = self._tex_mgr.push_texture(setting.asset_path / "game/pickup_box.rttex")
            # TODO: determine pickup color, idk what is it based on though, for now default to 0,0
            overlay[overlay_tex.array].extend(
                [
                    dropped.pos.x,
                    dropped.pos.y,
                    1.2,
                    1.2,
                    0,
                    0,
                    overlay_tex.layer,
                    self.get_object_z(i, SUBLAYER_OVERLAY),
                ]
            )

        for arr, inst in instances.items():
            instance_arr = np.array(inst, dtype=np.float32)
            self._dropped_meshes[arr] = Mesh(
                Mesh.RECT_WITH_UV_VERTS,
                ObjectRenderer.LAYOUT,
                Mesh.RECT_INDICES,
                instance_data=instance_arr,
                instance_layout=ObjectRenderer.INSTANCE_LAYOUT,
                instance_attrib_base=2,
            )

        for arr, inst in overlay.items():
            instance_arr = np.array(inst, dtype=np.float32)
            self._pickup_overlay[arr] = Mesh(
                Mesh.RECT_WITH_UV_VERTS,
                ObjectRenderer.LAYOUT,
                Mesh.RECT_INDICES,
                instance_data=instance_arr,
                instance_layout=ObjectRenderer.INSTANCE_LAYOUT,
                instance_attrib_base=2,
            )

        self._tex_mgr.flush()

    def delete(self) -> None:
        for mesh in self._dropped_meshes.values():
            mesh.delete()

        self._dropped_meshes.clear()
