from pyglm.glm import vec2
from gtools import setting
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.world import DroppedItem
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.renderer import Renderer
from OpenGL.GL import GL_UNSIGNED_INT
import numpy as np

from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.gui.texture import GLTex, GLTexManager


class SeedIconRenderer(Renderer):
    def __init__(self) -> None:
        self.tex_mgr = GLTexManager()
        self.tex: GLTex | None = None
        self.shader = ShaderProgram.get("shaders/seed")
        self.texture = self.shader.get_uniform("u_texture")
        self.mvp = self.shader.get_uniform("u_mvp")
        self.tile_size = self.shader.get_uniform("u_tileSize")

        self.shader3d = ShaderProgram.from_file("shaders/seed3d.vert", "shaders/seed.frag")
        self.vp3d = self.shader3d.get_uniform("u_view_proj")
        self.tex3d = self.shader3d.get_uniform("u_texture")
        self.spread3d = self.shader3d.get_uniform("u_layer_spread")
        self.tile_size3d = self.shader3d.get_uniform("u_tileSize")

    def build(self, items: list[tuple[DroppedItem, float]], pos_offset: vec2 = vec2(0, 0)) -> Mesh:
        self.tex = self.tex_mgr.load_texture(setting.asset_path / "game/seed.rttex")

        data_dtype = np.dtype(
            [
                ("tilePos", np.float32, 3),
                ("baseColor", np.uint32),
                ("overlayColor", np.uint32),
                ("baseUV", np.float32, 2),
                ("overlayUV", np.float32, 2),
                ("layer", np.float32),
            ]
        )
        data = np.zeros(len(items), dtype=data_dtype)
        for i, (drop, z) in enumerate(items):
            item = item_database.get(drop.id)

            base_color = (item.seed_color.r << 16) | (item.seed_color.g << 8) | item.seed_color.b

            overlay_r = (item.seed_color.r + item.seed_overlay_color.r) // 2
            overlay_g = (item.seed_color.g + item.seed_overlay_color.g) // 2
            overlay_b = (item.seed_color.b + item.seed_overlay_color.b) // 2
            overlay_color = (overlay_r << 16) | (overlay_g << 8) | overlay_b

            data[i]["tilePos"] = [drop.pos.x + pos_offset.x, drop.pos.y + pos_offset.y, z]
            data[i]["baseColor"] = base_color
            data[i]["overlayColor"] = overlay_color
            data[i]["baseUV"] = [item.seed_base.value * 16 / self.tex.width, 0 / self.tex.height]
            data[i]["overlayUV"] = [item.seed_overlay.value * 16 / self.tex.width, 16 / self.tex.height]
            data[i]["layer"] = self.tex.layer

        self.tex_mgr.flush()

        return Mesh(
            Mesh.RECT_WITH_UV_VERTS,
            [2, 2],
            Mesh.RECT_INDICES,
            instance_data=data,
            instance_layout=[3, (1, GL_UNSIGNED_INT), (1, GL_UNSIGNED_INT), 2, 2, 1],
            instance_attrib_base=2,
        )

    def draw(self, camera: Camera2D, mesh: Mesh) -> None:
        if self.tex:
            self.shader.use()
            self.mvp.set_mat4x4(camera.proj_as_numpy())
            self.tile_size.set_float(16.0)

            self.tex.array.bind(unit=0)
            self.texture.set_int(0)
            mesh.draw_instanced()

    def draw_3d(self, camera3d: Camera3D, mesh: Mesh, layer_spread: float) -> None:
        if self.tex:
            self.shader3d.use()
            self.vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
            self.spread3d.set_float(layer_spread)
            self.tile_size3d.set_float(16.0)

            self.tex.array.bind(unit=0)
            self.tex3d.set_int(0)
            mesh.draw_instanced()

    def delete(self) -> None:
        pass
