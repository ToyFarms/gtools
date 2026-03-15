import numpy as np
from pyglm import glm
from pyglm.glm import mat4x4, vec3, vec2
from gtools import setting
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.renderer import Renderer
from gtools.gui.lib.text_renderer import TextRenderer
from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.gui.texture import get_texture
from gtools.gui.lib import layer


class GuiMenuRenderer(Renderer):
    def __init__(self) -> None:
        self.shader = ShaderProgram.get("shaders/gui_box")
        self.u_proj = self.shader.get_uniform("u_proj")
        self.u_model = self.shader.get_uniform("u_model")
        self.u_texture = self.shader.get_uniform("u_texture")
        self.u_layer = self.shader.get_uniform("u_layer")
        self.u_size = self.shader.get_uniform("u_size")
        self.u_texRes = self.shader.get_uniform("u_texRes")
        self.u_z = self.shader.get_uniform("u_z")

        self.shader3d = ShaderProgram.from_file("shaders/gui_box3d.vert", "shaders/gui_box.frag")
        self.u_vp3d = self.shader3d.get_uniform("u_view_proj")
        self.u_model3d = self.shader3d.get_uniform("u_model")
        self.u_texture3d = self.shader3d.get_uniform("u_texture")
        self.u_layer3d = self.shader3d.get_uniform("u_layer")
        self.u_z3d = self.shader3d.get_uniform("u_z")
        self.u_spread3d = self.shader3d.get_uniform("u_layer_spread")
        self.u_size3d = self.shader3d.get_uniform("u_size")
        self.u_texRes3d = self.shader3d.get_uniform("u_texRes")

        self.tex = get_texture(setting.asset_path / "game/gui_box.rttex")
        self.mesh = Mesh(Mesh.RECT_WITH_UV_VERTS, [2, 2], Mesh.RECT_INDICES)

        self.text_renderer = TextRenderer("resources/fonts/centurygothic_bold.ttf", size=14)

    def _wrap_text(self, text: str, max_width: float) -> list[str]:
        lines = []
        for paragraph in text.split("\n"):
            words = paragraph.split(" ")
            current_line = []
            for word in words:
                test_line = " ".join(current_line + [word])
                w, _ = self.text_renderer.get_text_size(test_line)
                if w > max_width and current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                else:
                    current_line.append(word)
            if current_line:
                lines.append(" ".join(current_line))
        return lines

    def draw(self, camera: Camera2D, text: str, world_pos: vec2) -> None:
        if not text:
            return

        max_width = 300.0
        padding = 10.0

        lines = self._wrap_text(text, max_width)
        lines.reverse()
        font = self.text_renderer.font

        line_height = font.height * 1.1

        tw_max = 0.0
        for line in lines:
            lw, _ = self.text_renderer.get_text_size(line)
            tw_max = max(tw_max, lw)

        th_total = (len(lines) - 1) * line_height + (font.ascender - font.descender)
        bw, bh = tw_max + padding * 2, th_total + padding * 2

        self.shader.use()
        self.u_proj.set_mat4x4(camera.proj_as_numpy())

        self.tex.array.bind(unit=0)
        self.u_texture.set_int(0)
        self.u_layer.set_float(float(self.tex.layer))
        self.u_size.set_vec2(np.array([bw, bh], dtype=np.float32))
        self.u_texRes.set_vec2(np.array([self.tex.width, self.tex.height], dtype=np.float32))
        self.u_z.set_float(layer.GUI_MENU)

        center_y = world_pos.y - bh / 2 - 20

        model = mat4x4(1.0)
        model = glm.translate(model, vec3(world_pos.x, center_y, 0.0))
        model = glm.scale(model, vec3(bw, bh, 1.0))
        self.u_model.set_mat4x4(glm.value_ptr(model))

        self.mesh.draw()

        self.text_renderer._batch_data.clear()

        text_block_top = th_total / 2
        current_baseline_y = center_y + text_block_top - font.ascender + 8

        for line in lines:
            lw, _ = self.text_renderer.get_text_size(line)
            tx = world_pos.x - lw / 2
            self.text_renderer.build_text(line, tx, current_baseline_y, layer.GUI_MENU_TEXT)
            current_baseline_y -= line_height

        self.text_renderer.build()
        self.text_renderer.draw(camera, color=(1.0, 1.0, 1.0))

    def draw_3d(self, camera3d: Camera3D, text: str, world_pos: vec2, layer_spread: float) -> None:
        if not text:
            return

        max_width = 300.0
        padding = 10.0

        lines = self._wrap_text(text, max_width)
        font = self.text_renderer.font
        line_height = font.height * 1.1

        tw_max = 0.0
        for line in lines:
            lw, _ = self.text_renderer.get_text_size(line)
            tw_max = max(tw_max, lw)

        th_total = (len(lines) - 1) * line_height + (font.ascender - font.descender)
        bw, bh = tw_max + padding * 2, th_total + padding * 2

        self.shader3d.use()
        self.u_vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self.u_spread3d.set_float(layer_spread)
        self.u_z3d.set_float(layer.GUI_MENU)

        self.tex.array.bind(unit=0)
        self.u_texture3d.set_int(0)
        self.u_layer3d.set_float(float(self.tex.layer))
        self.u_size3d.set_vec2(np.array([bw, bh], dtype=np.float32))
        self.u_texRes3d.set_vec2(np.array([self.tex.width, self.tex.height], dtype=np.float32))

        center_y = world_pos.y - bh / 2 - 20

        model = mat4x4(1.0)
        model = glm.translate(model, vec3(world_pos.x, center_y, 0.0))
        model = glm.scale(model, vec3(bw, bh, 1.0))
        self.u_model3d.set_mat4x4(glm.value_ptr(model))

        self.mesh.draw()

        self.text_renderer._batch_data.clear()
        text_block_top = th_total / 2
        current_baseline_y = center_y + text_block_top - font.ascender

        for line in lines:
            lw, _ = self.text_renderer.get_text_size(line)
            tx = world_pos.x - lw / 2
            self.text_renderer.build_text(line, tx, current_baseline_y, layer.GUI_MENU_TEXT)
            current_baseline_y -= line_height

        self.text_renderer.build()
        self.text_renderer.draw_3d(camera3d, layer_spread, color=(1.0, 1.0, 1.0))

    def delete(self) -> None:
        self.mesh.delete()
        self.text_renderer.delete()
