from gtools import setting
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.world import DroppedItem
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.renderer import Renderer
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

        self.shader3d = ShaderProgram.from_file("shaders/seed3d.vert", "shaders/seed.frag")
        self.vp3d = self.shader3d.get_uniform("u_view_proj")
        self.tex3d = self.shader3d.get_uniform("u_texture")
        self.spread3d = self.shader3d.get_uniform("u_layer_spread")

    def build(self, items: list[tuple[DroppedItem, float]]) -> Mesh:
        self.tex = self.tex_mgr.push_texture(setting.asset_path / "game/seed.rttex")

        data: list[float] = []
        for drop, z in items:
            item = item_database.get(drop.id)
            data.extend(
                [
                    drop.pos.x - 8,
                    drop.pos.y - 8,
                    z,
                    float(item.seed_color.r) / 255.0,
                    float(item.seed_color.g) / 255.0,
                    float(item.seed_color.b) / 255.0,
                    (item.seed_color.r + item.seed_overlay_color.r) / 2.0 / 255.0,
                    (item.seed_color.g + item.seed_overlay_color.g) / 2.0 / 255.0,
                    (item.seed_color.b + item.seed_overlay_color.b) / 2.0 / 255.0,
                    float(item.seed_base.value * 16 / self.tex.width),
                    float(item.seed_overlay.value * 16 / self.tex.width),
                    self.tex.layer,
                ]
            )

        self.tex_mgr.flush()

        return Mesh(
            Mesh.RECT_WITH_UV_VERTS,
            [2, 2],
            Mesh.RECT_INDICES,
            instance_data=np.array(data, dtype=np.float32),
            instance_layout=[3, 3, 3, 1, 1, 1],
            instance_attrib_base=2,
        )

    def draw(self, camera: Camera2D, mesh: Mesh) -> None:
        self.shader.use()
        self.mvp.set_mat4x4(camera.proj_as_numpy())

        if self.tex:
            self.tex.array.bind(unit=0)
            self.texture.set_int(0)
            mesh.draw_instanced()

    def draw_3d(self, camera3d: Camera3D, mesh: Mesh, layer_spread: float) -> None:
        self.shader3d.use()
        self.vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self.spread3d.set_float(layer_spread)

        if self.tex:
            self.tex.array.bind(unit=0)
            self.tex3d.set_int(0)
            mesh.draw_instanced()

    def delete(self) -> None:
        pass
