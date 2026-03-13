from collections import defaultdict

from OpenGL.GL import (
    GL_EQUAL,
    GL_FALSE,
    GL_KEEP,
    GL_REPLACE,
    GL_STENCIL_BUFFER_BIT,
    GL_STENCIL_TEST,
    GL_TRUE,
    glClear,
    glDepthMask,
    glDisable,
    glEnable,
    glStencilFunc,
    glStencilMask,
    glStencilOp,
)
from pyglm.glm import ivec2

from gtools import setting
from gtools.baked.items import GEMS
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.world import World
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.layer import OBJECT_DROPPED_END, OBJECT_DROPPED_SHADOW_END, OBJECT_DROPPED_SHADOW_START, OBJECT_DROPPED_START
from gtools.gui.lib.renderer import Renderer
from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.gui.texture import TextureArray, get_tex_manager
from gtools.gui.lib.text_renderer import TextRenderer
import numpy as np

SHADOW_Z_START = OBJECT_DROPPED_SHADOW_START
SHADOW_Z_END = OBJECT_DROPPED_SHADOW_END
OBJECT_Z_START = OBJECT_DROPPED_START
OBJECT_Z_END = OBJECT_DROPPED_END

REGION_TILE_SIZE = 3
MAX_PER_REGION = 64

SHADOW_SUBLAYER_OVERLAY = 0
SHADOW_SUBLAYER_ICON = 1
SHADOW_STRIDE = 2
MAX_SHADOW_LAYER = MAX_PER_REGION * SHADOW_STRIDE

SUBLAYER_ICON = 0
SUBLAYER_OVERLAY = 1
SUBLAYER_TEXT_SHADOW = 2
SUBLAYER_TEXT = 3
LAYER_STRIDE = 4
MAX_LAYER = MAX_PER_REGION * LAYER_STRIDE


class ObjectRenderer(Renderer):
    LAYOUT = [2, 2]
    INSTANCE_LAYOUT = [2, 2, 2, 1, 1]

    def __init__(self) -> None:
        self._tex_mgr = get_tex_manager()

        self._dropped_meshes: dict[TextureArray, Mesh] = {}
        self._pickup_overlay: dict[TextureArray, Mesh] = {}

        self._icon_shadows: dict[TextureArray, Mesh] = {}
        self._overlay_shadows: dict[TextureArray, Mesh] = {}

        self._shader = ShaderProgram.get("shaders/object")
        self._mvp = self._shader.get_uniform("u_mvp")
        self._tex = self._shader.get_uniform("texArray")
        self._tile_size = self._shader.get_uniform("u_tileSize")

        self._shadow_shader = ShaderProgram.get("shaders/object_shadow")
        self._shadow_mvp = self._shadow_shader.get_uniform("u_mvp")
        self._shadow_tex = self._shadow_shader.get_uniform("texArray")
        self._shadow_tile_size = self._shadow_shader.get_uniform("u_tileSize")
        self._shadow_offset = self._shadow_shader.get_uniform("u_shadowOffset")
        self._shadow_alpha = self._shadow_shader.get_uniform("u_shadowAlpha")

        self._shader3d = ShaderProgram.get("shaders/object3d")
        self._vp3d = self._shader3d.get_uniform("u_view_proj")
        self._tex3d = self._shader3d.get_uniform("texArray")
        self._tile_size3d = self._shader3d.get_uniform("u_tileSize")
        self._spread3d = self._shader3d.get_uniform("u_layer_spread")

        self._text_renderer = TextRenderer("resources/fonts/centurygothic_bold.ttf", size=32)

    def get_shadow_z(self, local_index: int, sublayer: int) -> float:
        slot = local_index * SHADOW_STRIDE + sublayer
        t = slot / MAX_SHADOW_LAYER
        return SHADOW_Z_START + t * (SHADOW_Z_END - SHADOW_Z_START)

    def get_object_z(self, local_index: int, sublayer: int) -> float:
        slot = local_index * LAYER_STRIDE + sublayer
        t = slot / MAX_LAYER
        return OBJECT_Z_START + t * (OBJECT_Z_END - OBJECT_Z_START)

    def draw_shadow(self, camera: Camera2D) -> None:
        if not self._dropped_meshes:
            return

        glDepthMask(GL_FALSE)

        self._shadow_shader.use()
        self._shadow_mvp.set_mat4x4(camera.proj_as_numpy())
        self._shadow_alpha.set_float(0.4)
        self._shadow_offset.set_vec2(np.array([-8.0, 8.0], dtype=np.float32))

        self._shadow_tile_size.set_float(32.0)
        for arr, mesh in self._icon_shadows.items():
            arr.bind(unit=0)
            self._shadow_tex.set_int(0)
            mesh.draw_instanced()

        self._shadow_tile_size.set_float(20.0)
        for arr, mesh in self._overlay_shadows.items():
            arr.bind(unit=0)
            self._shadow_tex.set_int(0)
            mesh.draw_instanced()

        glDepthMask(GL_TRUE)

    def draw(self, camera: Camera2D) -> None:
        if not self._dropped_meshes:
            return

        self._shader.use()
        self._mvp.set_mat4x4(camera.proj_as_numpy())

        self._tile_size.set_float(32.0)
        for arr, mesh in self._dropped_meshes.items():
            arr.bind(unit=0)
            self._tex.set_int(0)
            mesh.draw_instanced()

        self._tile_size.set_float(20.0)
        for arr, mesh in self._pickup_overlay.items():
            arr.bind(unit=0)
            self._tex.set_int(0)
            mesh.draw_instanced()

        self._text_renderer.draw(camera, offset=(0.2, 0.2), shadow_color=(0, 0, 0))

    def draw_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        if not self._dropped_meshes:
            return

        self._shader3d.use()
        self._vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self._spread3d.set_float(layer_spread)

        self._tile_size3d.set_float(32.0)
        for arr, mesh in self._dropped_meshes.items():
            arr.bind(unit=0)
            self._tex3d.set_int(0)
            mesh.draw_instanced()

        self._tile_size3d.set_float(20.0)
        for arr, mesh in self._pickup_overlay.items():
            arr.bind(unit=0)
            self._tex3d.set_int(0)
            mesh.draw_instanced()

    def load(self, world: World) -> None:
        icons: dict[TextureArray, list[float]] = defaultdict(list)
        overlay: dict[TextureArray, list[float]] = defaultdict(list)
        icon_shadows: dict[TextureArray, list[float]] = defaultdict(list)
        overlay_shadows: dict[TextureArray, list[float]] = defaultdict(list)

        region_counters: dict[tuple[int, int], int] = defaultdict(int)

        for dropped in world.dropped.items:
            tile_x = int(dropped.pos.x // 32)
            tile_y = int(dropped.pos.y // 32)
            region = (tile_x // REGION_TILE_SIZE, tile_y // REGION_TILE_SIZE)

            local_index = region_counters[region]
            region_counters[region] += 1

            item = item_database.get(dropped.id)
            tex_file = item.get_icon_texture() or item.texture_file.decode()
            tex = self._tex_mgr.push_texture(setting.asset_path / "game" / tex_file)

            tex_index = item.get_default_tex()
            stride = item.get_tex_stride()
            off = ivec2(tex_index % max(stride, 1), tex_index // stride if stride else 0)
            tex_pos = ivec2(item.tex_coord_x, item.tex_coord_y) + off

            uv_x = tex_pos.x * 32 / tex.width
            uv_y = tex_pos.y * 32 / tex.height

            x = dropped.pos.x - 8
            y = dropped.pos.y - 8

            icons[tex.array].extend(
                [
                    x,
                    y,
                    0.67,
                    0.67,
                    uv_x,
                    uv_y,
                    tex.layer,
                    self.get_object_z(local_index, SUBLAYER_ICON),
                ]
            )

            icon_shadows[tex.array].extend(
                [
                    x,
                    y,
                    0.67,
                    0.67,
                    uv_x,
                    uv_y,
                    tex.layer,
                    self.get_shadow_z(local_index, SHADOW_SUBLAYER_ICON),
                ]
            )

            overlay_tex = self._tex_mgr.push_texture(setting.asset_path / "game/pickup_box.rttex")

            if not item.is_seed() or item.id != GEMS:
                overlay[overlay_tex.array].extend(
                    [
                        x,
                        y,
                        1.2,
                        1.2,
                        0,
                        0,
                        overlay_tex.layer,
                        self.get_object_z(local_index, SUBLAYER_OVERLAY),
                    ]
                )

                overlay_shadows[overlay_tex.array].extend(
                    [
                        x,
                        y,
                        1.2,
                        1.2,
                        0,
                        0,
                        overlay_tex.layer,
                        self.get_shadow_z(local_index, SHADOW_SUBLAYER_OVERLAY),
                    ]
                )

            if dropped.amount > 1:
                target_width = 24.0
                padding = 4.0
                max_text_width = target_width - padding * 2

                ref_width, _ = self._text_renderer.get_text_size("000", scale=1.0)
                auto_scale = max_text_width / ref_width if ref_width > 0 else 0.25

                text_str = str(dropped.amount)
                _, text_h = self._text_renderer.get_text_size(text_str, scale=auto_scale)

                half = 20 * 1.2 / 2
                text_x = x - half + padding
                text_y = y + half - (text_h + padding)

                self._text_renderer.build_text(
                    text_str,
                    text_x,
                    text_y,
                    self.get_object_z(local_index, SUBLAYER_TEXT),
                    scale=auto_scale,
                    shadow_z=self.get_object_z(local_index, SUBLAYER_TEXT_SHADOW),
                )

        self._text_renderer.build()

        def _build_meshes(src: dict[TextureArray, list[float]]) -> dict[TextureArray, Mesh]:
            return {
                arr: Mesh(
                    Mesh.RECT_WITH_UV_VERTS,
                    ObjectRenderer.LAYOUT,
                    Mesh.RECT_INDICES,
                    instance_data=np.array(inst, dtype=np.float32),
                    instance_layout=ObjectRenderer.INSTANCE_LAYOUT,
                    instance_attrib_base=2,
                )
                for arr, inst in src.items()
            }

        self._dropped_meshes = _build_meshes(icons)
        self._pickup_overlay = _build_meshes(overlay)
        self._icon_shadows = _build_meshes(icon_shadows)
        self._overlay_shadows = _build_meshes(overlay_shadows)

        self._tex_mgr.flush()

    def delete(self) -> None:
        for meshes in (
            self._dropped_meshes,
            self._pickup_overlay,
            self._icon_shadows,
            self._overlay_shadows,
        ):
            for mesh in meshes.values():
                mesh.delete()
            meshes.clear()

        self._text_renderer.delete()
