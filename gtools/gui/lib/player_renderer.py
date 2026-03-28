import numpy as np
from pyglm import glm
from pyglm.glm import mat4x4, vec3
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.renderer import Renderer
from gtools.gui.lib.text_renderer import TextRenderer
from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.gui.lib import layer
from gtools.core.growtopia.packet import TankFlags
from gtools.core.growtopia.player import Player

class PlayerRenderer(Renderer):
    def __init__(self) -> None:
        self.shader = ShaderProgram.get("shaders/solid")
        self.u_proj = self.shader.get_uniform("u_proj")
        self.u_model = self.shader.get_uniform("u_model")

        self.shader3d = ShaderProgram.from_file("shaders/solid3d.vert", "shaders/solid.frag")
        self.u_vp3d = self.shader3d.get_uniform("u_view_proj")
        self.u_model3d = self.shader3d.get_uniform("u_model")
        self.u_z3d = self.shader3d.get_uniform("u_z")
        self.u_spread3d = self.shader3d.get_uniform("u_layer_spread")

        body_vertices = np.array([
            -0.5, -0.5, 1.0, 1.0, 1.0, 1.0,
            0.5,  -0.5, 1.0, 1.0, 1.0, 1.0,
            0.5,  0.5,  1.0, 1.0, 1.0, 1.0,
            -0.5, 0.5,  1.0, 1.0, 1.0, 1.0,
        ], dtype=np.float32)
        self.body_mesh = Mesh(body_vertices, [2, 4], Mesh.RECT_INDICES)

        line_vertices = np.array([
            -0.5, -0.5, 1.0, 1.0, 1.0, 1.0,
            0.5,  -0.5, 1.0, 1.0, 1.0, 1.0,
            0.5,  0.5,  1.0, 1.0, 1.0, 1.0,
            -0.5, 0.5,  1.0, 1.0, 1.0, 1.0,
        ], dtype=np.float32)
        self.line_mesh = Mesh(line_vertices, [2, 4], Mesh.RECT_INDICES)

        self.text_renderer = TextRenderer("resources/fonts/centurygothic_bold.ttf", size=14)

    def draw(self, camera: Camera2D, players: list[Player]) -> None:
        if not players:
            return

        self.shader.use()
        self.u_proj.set_mat4x4(camera.proj_as_numpy())

        self.text_renderer._batch_data.clear()

        for player in players:
            w, h = 20.0, 30.0
            if player.colrect.z > 0 and player.colrect.w > 0:
                w, h = float(player.colrect.z), float(player.colrect.w)

            model = mat4x4(1.0)
            model = glm.translate(model, vec3(player.pos.x - w/2, player.pos.y - h/2, 0.0))
            model = glm.scale(model, vec3(w, h, 1.0))
            self.u_model.set_mat4x4(glm.value_ptr(model))
            self.body_mesh.draw()

            eye_y = player.pos.y + h * 0.25
            line_w = 10.0
            line_h = 2.0
            facing_left = (player.flags & TankFlags.FACING_LEFT) != 0

            line_x = player.pos.x - w/2 + w/2 + (-line_w/2 if facing_left else line_w/2)

            line_model = mat4x4(1.0)
            line_model = glm.translate(line_model, vec3(line_x, eye_y, 0.0))
            line_model = glm.scale(line_model, vec3(line_w, line_h, 1.0))
            self.u_model.set_mat4x4(glm.value_ptr(line_model))
            self.line_mesh.draw()

            name_str = player.name.decode(errors="ignore")
            name_w, _ = self.text_renderer.get_text_size(name_str)
            self.text_renderer.build_text(name_str, player.pos.x - w/2 - name_w/2 + w/2, player.pos.y - h/2 - 5, layer.PLAYER)

        self.text_renderer.build()
        self.text_renderer.draw(camera, color=(1.0, 1.0, 1.0))

    def draw_3d(self, camera3d: Camera3D, layer_spread: float, players: list[Player]) -> None:
        if not players:
            return

        self.shader3d.use()
        self.u_vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self.u_spread3d.set_float(layer_spread)
        self.u_z3d.set_float(layer.PLAYER)

        self.text_renderer._batch_data.clear()

        for player in players:
            w, h = 20.0, 30.0
            if player.colrect.z > 0 and player.colrect.w > 0:
                w, h = float(player.colrect.z), float(player.colrect.w)

            model = mat4x4(1.0)
            model = glm.translate(model, vec3(player.pos.x - w/2, player.pos.y - h/2, 0.0))
            model = glm.scale(model, vec3(w, h, 1.0))
            self.u_model3d.set_mat4x4(glm.value_ptr(model))
            self.body_mesh.draw()

            eye_y = player.pos.y - h/2 + h * 0.25
            line_w = 10.0
            line_h = 2.0
            facing_left = (player.flags & TankFlags.FACING_LEFT) != 0
            line_x = player.pos.x - w/2 + w/2 + (-line_w/2 if facing_left else line_w/2)

            line_model = mat4x4(1.0)
            line_model = glm.translate(line_model, vec3(line_x, eye_y, 0.0))
            line_model = glm.scale(line_model, vec3(line_w, line_h, 1.0))
            self.u_model3d.set_mat4x4(glm.value_ptr(line_model))
            self.u_z3d.set_float(layer.PLAYER_DIRECTION)
            self.line_mesh.draw()
            self.u_z3d.set_float(layer.PLAYER)

            name_str = player.name.decode(errors="ignore")
            name_w, _ = self.text_renderer.get_text_size(name_str)
            self.text_renderer.build_text(name_str, player.pos.x - name_w/2, player.pos.y - h/2 - 5, layer.PLAYER)

        self.text_renderer.build()
        self.text_renderer.draw_3d(camera3d, layer_spread, color=(1.0, 1.0, 1.0))

    def delete(self) -> None:
        self.body_mesh.delete()
        self.line_mesh.delete()
        self.text_renderer.delete()
