import numpy as np
from OpenGL.GL import glBindTexture, GL_TEXTURE_2D, glActiveTexture, GL_TEXTURE0
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.renderer import Renderer
from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.gui.lib.font import FontManager


class TextRenderer(Renderer):
    INSTANCE_LAYOUT = [2, 2, 2, 2, 1]

    def __init__(
        self,
        font_path: str,
        size: int = 16,
        sdf_pixel_range: float = 12.0,
        raster_scale: int = 4,
        atlas_min_size: int = 1024,
        edge_softness: float = 0.1,
        weight: float = 0.0,
    ) -> None:
        self.font = FontManager(
            font_path,
            size=size,
            sdf_pixel_range=sdf_pixel_range,
            raster_scale=raster_scale,
            atlas_min_size=atlas_min_size,
        )
        self.edge_softness = edge_softness
        self.weight = weight
        self.shader = ShaderProgram.get("shaders/text")
        self._mvp = self.shader.get_uniform("u_mvp")
        self._offset = self.shader.get_uniform("u_offset")
        self._tex = self.shader.get_uniform("u_texture")
        self._color = self.shader.get_uniform("u_textColor")
        self._sdf_range = self.shader.get_uniform("u_sdfPxRange")
        self._softness = self.shader.get_uniform("u_edgeSoftness")
        self._weight = self.shader.get_uniform("u_weight")

        self.shader3d = ShaderProgram.from_file("shaders/text3d.vert", "shaders/text.frag")
        self._vp3d = self.shader3d.get_uniform("u_view_proj")
        self._offset3d = self.shader3d.get_uniform("u_offset")
        self._tex3d = self.shader3d.get_uniform("u_texture")
        self._color3d = self.shader3d.get_uniform("u_textColor")
        self._spread3d = self.shader3d.get_uniform("u_layer_spread")
        self._sdf_range3d = self.shader3d.get_uniform("u_sdfPxRange")
        self._softness3d = self.shader3d.get_uniform("u_edgeSoftness")
        self._weight3d = self.shader3d.get_uniform("u_weight")

        self._batch_data: list[float] = []
        self._shadow_batch_data: list[float] = []
        self._mesh: Mesh | None = None
        self._shadow_mesh: Mesh | None = None

    def delete(self) -> None:
        self.font.delete()
        self._batch_data.clear()
        self._shadow_batch_data.clear()
        if self._mesh:
            self._mesh.delete()
            self._mesh = None
        if self._shadow_mesh:
            self._shadow_mesh.delete()
            self._shadow_mesh = None

    def get_text_size(self, text: str, scale: float = 1.0) -> tuple[float, float]:
        width = 0.0
        max_height = 0.0
        for i, char in enumerate(text):
            glyph = self.font.get_char(char)
            if i == len(text) - 1:
                width += (glyph.bearing[0] + glyph.size[0]) * scale
            else:
                width += (glyph.advance >> 6) * scale
            max_height = max(max_height, glyph.size[1] * scale)
        return width, max_height

    def build_text(self, text: str, x: float, y: float, z: float, scale: float = 1.0, shadow_z: float | None = None) -> None:
        current_x = x
        for char in text:
            glyph = self.font.get_char(char)
            if glyph.size[0] == 0:
                current_x += (glyph.advance >> 6) * scale
                continue

            w = glyph.size[0] * scale
            h = glyph.size[1] * scale

            xpos = current_x + glyph.bearing[0] * scale
            ypos = y - glyph.bearing[1] * scale

            self._batch_data.extend([xpos, ypos, w, h, glyph.tex_offset[0], glyph.tex_offset[1], glyph.tex_size[0], glyph.tex_size[1], z])

            if shadow_z is not None:
                self._shadow_batch_data.extend([xpos, ypos, w, h, glyph.tex_offset[0], glyph.tex_offset[1], glyph.tex_size[0], glyph.tex_size[1], shadow_z])

            current_x += (glyph.advance >> 6) * scale

    def build(self) -> None:
        if self._batch_data:
            if self._mesh:
                self._mesh.delete()
            instance_data = np.array(self._batch_data, dtype=np.float32)
            self._mesh = Mesh(Mesh.RECT_WITH_UV_VERTS, [2, 2], Mesh.RECT_INDICES, instance_data=instance_data, instance_layout=self.INSTANCE_LAYOUT, instance_attrib_base=2)
            self._batch_data.clear()

        if self._shadow_batch_data:
            if self._shadow_mesh:
                self._shadow_mesh.delete()
            shadow_instance_data = np.array(self._shadow_batch_data, dtype=np.float32)
            self._shadow_mesh = Mesh(Mesh.RECT_WITH_UV_VERTS, [2, 2], Mesh.RECT_INDICES, instance_data=shadow_instance_data, instance_layout=self.INSTANCE_LAYOUT, instance_attrib_base=2)
            self._shadow_batch_data.clear()

    def draw(
        self,
        camera: Camera2D,
        color: tuple[float, float, float] = (1.0, 1.0, 1.0),
        offset: tuple[float, float] = (0.0, 0.0),
        shadow_color: tuple[float, float, float] | None = None,
    ) -> None:
        if not self._mesh:
            return

        self.shader.use()
        self._mvp.set_mat4x4(camera.proj_as_numpy())
        self._sdf_range.set_float(self.font.sdf_pixel_range)
        self._softness.set_float(self.edge_softness)
        self._weight.set_float(self.weight)

        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self.font.atlas_tex)
        self._tex.set_int(0)

        if self._shadow_mesh and shadow_color is not None:
            self._color.set_vec3(np.array(shadow_color, dtype=np.float32))
            self._offset.set_vec2(np.array(offset, dtype=np.float32))
            self._shadow_mesh.draw_instanced()

        self._color.set_vec3(np.array(color, dtype=np.float32))
        self._offset.set_vec2(np.zeros(2, dtype=np.float32))
        self._mesh.draw_instanced()

    def draw_3d(
        self,
        camera3d: Camera3D,
        layer_spread: float,
        color: tuple[float, float, float] = (1.0, 1.0, 1.0),
        offset: tuple[float, float] = (0.0, 0.0),
        shadow_color: tuple[float, float, float] | None = None,
    ) -> None:
        if not self._mesh:
            return

        self.shader3d.use()
        self._vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self._spread3d.set_float(layer_spread)
        self._sdf_range3d.set_float(self.font.sdf_pixel_range)
        self._softness3d.set_float(self.edge_softness)
        self._weight3d.set_float(self.weight)

        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self.font.atlas_tex)
        self._tex3d.set_int(0)

        if self._shadow_mesh and shadow_color is not None:
            self._color3d.set_vec3(np.array(shadow_color, dtype=np.float32))
            self._offset3d.set_vec2(np.array(offset, dtype=np.float32))
            self._shadow_mesh.draw_instanced()

        self._color3d.set_vec3(np.array(color, dtype=np.float32))
        self._offset3d.set_vec2(np.zeros(2, dtype=np.float32))
        self._mesh.draw_instanced()
