import numpy as np
import math
from pyglm import glm
from pyglm.glm import mat4x4, vec3
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.renderer import Renderer
from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.gui.lib import layer
from gtools.core.growtopia.world import Npc

class NpcRenderer(Renderer):
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
            -0.5, -0.5, 1.0, 0.0, 0.0, 1.0,
            0.5,  -0.5, 1.0, 0.0, 0.0, 1.0,
            0.5,  0.5,  1.0, 0.0, 0.0, 1.0,
            -0.5, 0.5,  1.0, 0.0, 0.0, 1.0,
        ], dtype=np.float32)
        self.body_mesh = Mesh(body_vertices, [2, 4], Mesh.RECT_INDICES)

        line_vertices = np.array([
            -0.5, -0.5, 1.0, 0.0, 0.0, 1.0,
            0.5,  -0.5, 1.0, 0.0, 0.0, 1.0,
            0.5,  0.5,  1.0, 0.0, 0.0, 1.0,
            -0.5, 0.5,  1.0, 0.0, 0.0, 1.0,
        ], dtype=np.float32)
        self.line_mesh = Mesh(line_vertices, [2, 4], Mesh.RECT_INDICES)

        self.debug_line = False

    def draw(self, camera: Camera2D, npcs: list[Npc]) -> None:
        if not npcs:
            return

        self.shader.use()
        self.u_proj.set_mat4x4(camera.proj_as_numpy())

        for npc in npcs:
            w, h = 20.0, 20.0

            model = mat4x4(1.0)
            model = glm.translate(model, vec3(npc.pos.x, npc.pos.y, 0.0))
            model = glm.scale(model, vec3(w, h, 1.0))
            self.u_model.set_mat4x4(glm.value_ptr(model))
            self.body_mesh.draw()

            if self.debug_line:
                start = npc.pos
                end = npc.target_pos

                diff = end - start
                dist = glm.length(diff)
                if dist > 0.1:
                    angle = math.atan2(diff.y, diff.x)
                    mid = (start + end) / 2.0

                    line_model = mat4x4(1.0)
                    line_model = glm.translate(line_model, vec3(mid.x, mid.y, 0.0))
                    line_model = glm.rotate(line_model, angle, vec3(0, 0, 1))
                    line_model = glm.scale(line_model, vec3(dist, 1.0, 1.0))
                    self.u_model.set_mat4x4(glm.value_ptr(line_model))

                    self.line_mesh.draw()

    def draw_3d(self, camera3d: Camera3D, layer_spread: float, npcs: list[Npc]) -> None:
        if not npcs:
            return

        self.shader3d.use()
        self.u_vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self.u_spread3d.set_float(layer_spread)
        self.u_z3d.set_float(layer.NPC)

        for npc in npcs:
            w, h = 20.0, 20.0

            model = mat4x4(1.0)
            model = glm.translate(model, vec3(npc.pos.x, npc.pos.y, 0.0))
            model = glm.scale(model, vec3(w, h, 1.0))
            self.u_model3d.set_mat4x4(glm.value_ptr(model))
            self.body_mesh.draw()

            if self.debug_line:
                start = npc.pos
                end = npc.target_pos
                diff = end - start
                dist = glm.length(diff)
                if dist > 0.1:
                    angle = math.atan2(diff.y, diff.x)
                    mid = (start + end) / 2.0

                    line_model = mat4x4(1.0)
                    line_model = glm.translate(line_model, vec3(mid.x, mid.y, 0.0))
                    line_model = glm.rotate(line_model, angle, vec3(0, 0, 1))
                    line_model = glm.scale(line_model, vec3(dist, 1.0, 1.0))
                    self.u_model3d.set_mat4x4(glm.value_ptr(line_model))
                    self.line_mesh.draw()

    def delete(self) -> None:
        self.body_mesh.delete()
        self.line_mesh.delete()
