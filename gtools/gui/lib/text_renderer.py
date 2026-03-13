import numpy as np
from OpenGL.GL import glBindTexture, GL_TEXTURE_2D, glActiveTexture, GL_TEXTURE0, glDepthFunc, GL_LEQUAL, GL_LESS
from gtools.gui.camera import Camera2D
from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.gui.lib.font import FontManager


class TextRenderer:
    INSTANCE_LAYOUT = [2, 2, 2, 2, 1]

    def __init__(self, font_path: str, size: int = 16):
        self.font = FontManager(font_path, size)
        self.shader = ShaderProgram.get("shaders/text")
        self._mvp = self.shader.get_uniform("u_mvp")
        self._offset = self.shader.get_uniform("u_offset")
        self._tex = self.shader.get_uniform("u_texture")
        self._color = self.shader.get_uniform("u_textColor")

        self._batch_data = []
        self._mesh = None

    def clear(self):
        self._batch_data.clear()
        if self._mesh:
            self._mesh.delete()
            self._mesh = None

    def get_text_size(self, text: str, scale: float = 1.0) -> tuple[float, float]:
        width = 0.0
        max_height = 0.0
        for char in text:
            glyph = self.font.get_char(char)
            width += (glyph.advance >> 6) * scale
            max_height = max(max_height, glyph.size[1] * scale)
        return width, max_height

    def draw_text(self, text: str, x: float, y: float, z: float, scale: float = 1.0):
        current_x = x
        for char in text:
            glyph = self.font.get_char(char)
            if glyph.size[0] == 0:
                current_x += (glyph.advance >> 6) * scale
                continue

            w = glyph.size[0] * scale
            h = glyph.size[1] * scale

            xpos = current_x + glyph.bearing[0] * scale
            ypos = y - (glyph.size[1] - glyph.bearing[1]) * scale

            self._batch_data.extend([xpos, ypos, w, h, glyph.tex_offset[0], glyph.tex_offset[1], glyph.tex_size[0], glyph.tex_size[1], z])

            current_x += (glyph.advance >> 6) * scale

    def build(self):
        if not self._batch_data:
            return

        instance_data = np.array(self._batch_data, dtype=np.float32)
        self._mesh = Mesh(Mesh.RECT_WITH_UV_VERTS, [2, 2], Mesh.RECT_INDICES, instance_data=instance_data, instance_layout=self.INSTANCE_LAYOUT, instance_attrib_base=2)
        self._batch_data.clear()

    def render(
        self,
        camera: Camera2D,
        color: tuple[float, float, float] = (1.0, 1.0, 1.0),
        shadow_color: tuple[float, float, float] | None = None,
        shadow_offset: tuple[float, float] = (1.0, -1.0),
    ):
        if not self._mesh:
            return

        self.shader.use()
        self._mvp.set_mat4x4(camera.proj_as_numpy())

        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self.font.atlas_tex)
        self._tex.set_int(0)

        glDepthFunc(GL_LEQUAL)

        if shadow_color is not None:
            self._color.set_vec3(np.array(shadow_color, dtype=np.float32))
            self._offset.set_vec2(np.array(shadow_offset, dtype=np.float32))
            self._mesh.draw_instanced()

        self._color.set_vec3(np.array(color, dtype=np.float32))
        self._offset.set_vec2(np.array([0.0, 0.0], dtype=np.float32))
        self._mesh.draw_instanced()

        glDepthFunc(GL_LESS)
