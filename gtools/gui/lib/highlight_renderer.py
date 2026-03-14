import numpy as np
from pyglm import glm
from pyglm.glm import mat4x4, vec3, vec2
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.gui.lib import layer

class HighlightRenderer:
    def __init__(self) -> None:
        self._shader = ShaderProgram.get("shaders/solid")
        self._u_proj = self._shader.get_uniform("u_proj")
        self._u_model = self._shader.get_uniform("u_model")

        self._shader3d = ShaderProgram.from_file("shaders/solid3d.vert", "shaders/solid.frag")
        self._u_vp3d = self._shader3d.get_uniform("u_view_proj")
        self._u_model3d = self._shader3d.get_uniform("u_model")
        self._u_z3d = self._shader3d.get_uniform("u_z")
        self._u_spread3d = self._shader3d.get_uniform("u_layer_spread")

        # fmt: off
        playhead_vertices = np.array([
            -0.5, -0.5, 1.0, 1.0, 1.0, 0.2,
            0.5,  -0.5, 1.0, 1.0, 1.0, 0.2,
            0.5,  0.5,  1.0, 1.0, 1.0, 0.2,
            -0.5, 0.5,  1.0, 1.0, 1.0, 0.2,
        ], dtype=np.float32)
        # fmt: on
        self._playhead_mesh = Mesh(playhead_vertices, [2, 4], Mesh.RECT_INDICES)

        # fmt: off
        hover_vertices = np.array([
            -0.5, -0.5, 1.0, 1.0, 1.0, 0.3,
            0.5,  -0.5, 1.0, 1.0, 1.0, 0.3,
            0.5,  0.5,  1.0, 1.0, 1.0, 0.3,
            -0.5, 0.5,  1.0, 1.0, 1.0, 0.3,
        ], dtype=np.float32)
        # fmt: on
        self._hover_mesh = Mesh(hover_vertices, [2, 4], Mesh.RECT_INDICES)

    def draw_playhead(self, camera: Camera2D, sheet, world_width: int) -> None:
        if not sheet or not sheet.any:
            return

        self._shader.use()
        self._u_proj.set_mat4x4(camera.proj_as_numpy())

        model = self._get_playhead_model(sheet.playhead - 1, world_width)
        self._u_model.set_mat4x4(glm.value_ptr(model))
        self._playhead_mesh.draw()

    def draw_playhead_3d(self, camera3d: Camera3D, sheet, world_width: int, layer_spread: float) -> None:
        if not sheet or not sheet.any:
            return

        self._shader3d.use()
        self._u_vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self._u_spread3d.set_float(layer_spread)
        self._u_z3d.set_float(layer.WORLD_FOREGROUND_AFTER_END)

        model = self._get_playhead_model(sheet.playhead - 1, world_width)
        self._u_model3d.set_mat4x4(glm.value_ptr(model))
        self._playhead_mesh.draw()

    def draw_hover(self, camera: Camera2D, tile_pos: vec2) -> None:
        self._shader.use()
        self._u_proj.set_mat4x4(camera.proj_as_numpy())

        model = mat4x4(1.0)
        model = glm.translate(model, vec3(tile_pos.x * 32, tile_pos.y * 32, 0.0))
        model = glm.scale(model, vec3(32.0, 32.0, 1.0))
        self._u_model.set_mat4x4(glm.value_ptr(model))
        self._hover_mesh.draw()

    def draw_hover_3d(self, camera3d: Camera3D, tile_pos: vec2, layer_spread: float) -> None:
        self._shader3d.use()
        self._u_vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self._u_spread3d.set_float(layer_spread)
        self._u_z3d.set_float(layer.WORLD_FOREGROUND_AFTER_END)

        model = mat4x4(1.0)
        model = glm.translate(model, vec3(tile_pos.x * 32, tile_pos.y * 32, 0.0))
        model = glm.scale(model, vec3(32.0, 32.0, 1.0))
        self._u_model3d.set_mat4x4(glm.value_ptr(model))
        self._hover_mesh.draw()

    def _get_playhead_model(self, playhead: int, world_width: int) -> mat4x4:
        model = mat4x4(1.0)
        width = 32.0
        height = 14.0 * 32.0
        model = glm.translate(
            model,
            vec3(
                (playhead % world_width) * 32 - 16 + width / 2,
                (playhead // world_width) * 14 * 32 - 16 + height / 2,
                0.0,
            ),
        )
        model = glm.scale(model, vec3(width, height, 1.0))
        return model

    def delete(self) -> None:
        self._playhead_mesh.delete()
        self._hover_mesh.delete()
