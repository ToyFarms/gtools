from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntFlag, auto

from OpenGL.GL import GL_FALSE, GL_TRUE, glDepthMask
from pyglm.glm import ivec2

from gtools import setting
from gtools.baked.items import GEMS
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.world import DroppedItem
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.renderer import Renderer
from gtools.gui.lib.seed_icon_renderer import SeedIconRenderer
from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.gui.texture import TextureArray, get_tex_manager
from gtools.gui.lib.text_renderer import TextRenderer
import numpy as np

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


@dataclass
class ObjectRenderMesh:
    dropped_meshes: dict[TextureArray, Mesh] = field(default_factory=dict)
    pickup_overlay: dict[TextureArray, Mesh] = field(default_factory=dict)
    icon_shadows: dict[TextureArray, Mesh] = field(default_factory=dict)
    overlay_shadows: dict[TextureArray, Mesh] = field(default_factory=dict)
    seed_mesh: Mesh | None = None
    text_renderer: TextRenderer | None = None

    def delete(self) -> None:
        for meshes in (
            self.dropped_meshes,
            self.pickup_overlay,
            self.icon_shadows,
            self.overlay_shadows,
        ):
            for mesh in meshes.values():
                mesh.delete()
            meshes.clear()

        if self.seed_mesh is not None:
            self.seed_mesh.delete()
            self.seed_mesh = None

        if self.text_renderer is not None:
            self.text_renderer.delete()
            self.text_renderer = None


class ObjectRenderer(Renderer):
    LAYOUT = [2, 2]
    INSTANCE_LAYOUT = [2, 2, 2, 1, 1]

    class Flags(IntFlag):
        NO_TEXT = auto()
        NO_SHADOW = auto()
        NO_OVERLAY = auto()
        NO_ICON = auto()

    def __init__(self, z_start: float, z_end: float) -> None:
        self._tex_mgr = get_tex_manager()
        self._seed_renderer = SeedIconRenderer()

        z_mid = (z_start + z_end) / 2.0
        self._shadow_z_start = z_start
        self._shadow_z_end = z_mid
        self._object_z_start = z_mid
        self._object_z_end = z_end

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

    def _get_shadow_z(self, local_index: int, sublayer: int) -> float:
        slot = local_index * SHADOW_STRIDE + sublayer
        t = slot / MAX_SHADOW_LAYER
        return self._shadow_z_start + t * (self._shadow_z_end - self._shadow_z_start)

    def _get_object_z(self, local_index: int, sublayer: int) -> float:
        slot = local_index * LAYER_STRIDE + sublayer
        t = slot / MAX_LAYER
        return self._object_z_start + t * (self._object_z_end - self._object_z_start)

    def draw_shadow(self, camera: Camera2D, render_mesh: ObjectRenderMesh) -> None:
        if not render_mesh.dropped_meshes:
            return

        glDepthMask(GL_FALSE)

        self._shadow_shader.use()
        self._shadow_mvp.set_mat4x4(camera.proj_as_numpy())
        self._shadow_alpha.set_float(0.4)
        offset = 5.0
        self._shadow_offset.set_vec2(np.array([-offset, offset], dtype=np.float32))

        self._shadow_tile_size.set_float(32.0)
        for arr, mesh in render_mesh.icon_shadows.items():
            arr.bind(unit=0)
            self._shadow_tex.set_int(0)
            mesh.draw_instanced()

        self._shadow_tile_size.set_float(20.0)
        for arr, mesh in render_mesh.overlay_shadows.items():
            arr.bind(unit=0)
            self._shadow_tex.set_int(0)
            mesh.draw_instanced()

        glDepthMask(GL_TRUE)

    def draw(self, camera: Camera2D, render_mesh: ObjectRenderMesh) -> None:
        if not render_mesh.dropped_meshes:
            return

        self._shader.use()
        self._mvp.set_mat4x4(camera.proj_as_numpy())

        self._tile_size.set_float(32.0)
        for arr, mesh in render_mesh.dropped_meshes.items():
            arr.bind(unit=0)
            self._tex.set_int(0)
            mesh.draw_instanced()

        self._tile_size.set_float(20.0)
        for arr, mesh in render_mesh.pickup_overlay.items():
            arr.bind(unit=0)
            self._tex.set_int(0)
            mesh.draw_instanced()

        if render_mesh.seed_mesh is not None:
            self._seed_renderer.draw(camera, render_mesh.seed_mesh)

        if render_mesh.text_renderer is not None:
            render_mesh.text_renderer.draw(camera, offset=(0.2, 0.2), shadow_color=(0, 0, 0))

    def draw_3d(self, camera3d: Camera3D, render_mesh: ObjectRenderMesh, layer_spread: float) -> None:
        if not render_mesh.dropped_meshes:
            return

        self._shader3d.use()
        self._vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self._spread3d.set_float(layer_spread)

        self._tile_size3d.set_float(32.0)
        for arr, mesh in render_mesh.dropped_meshes.items():
            arr.bind(unit=0)
            self._tex3d.set_int(0)
            mesh.draw_instanced()

        self._tile_size3d.set_float(20.0)
        for arr, mesh in render_mesh.pickup_overlay.items():
            arr.bind(unit=0)
            self._tex3d.set_int(0)
            mesh.draw_instanced()

        if render_mesh.seed_mesh is not None:
            self._seed_renderer.draw_3d(camera3d, render_mesh.seed_mesh, layer_spread)

    def build(self, items: list[DroppedItem], overlay_scale: float = 1.2, icon_scale: float = 0.67, flags: "ObjectRenderer.Flags" = Flags(0)) -> ObjectRenderMesh:
        region_counters: dict[tuple[int, int], int] = defaultdict(int)
        bucketed: defaultdict[int, list[DroppedItem]] = defaultdict(list)

        for dropped in items:
            tile_x = int(dropped.pos.x // 32)
            tile_y = int(dropped.pos.y // 32)
            region = (tile_x // REGION_TILE_SIZE, tile_y // REGION_TILE_SIZE)
            local_index = region_counters[region]
            region_counters[region] += 1
            bucketed[local_index].append(dropped)

        no_text = ObjectRenderer.Flags.NO_TEXT in flags
        no_shadow = ObjectRenderer.Flags.NO_SHADOW in flags
        no_overlay = ObjectRenderer.Flags.NO_OVERLAY in flags
        no_icon = ObjectRenderer.Flags.NO_ICON in flags

        text_renderer = None if no_text else TextRenderer("resources/fonts/centurygothic_bold.ttf", size=32)

        icons: dict[TextureArray, list[float]] = defaultdict(list)
        overlay: dict[TextureArray, list[float]] = defaultdict(list)
        icon_shadows: dict[TextureArray, list[float]] = defaultdict(list)
        overlay_shadows: dict[TextureArray, list[float]] = defaultdict(list)
        seeds: list[tuple[DroppedItem, float]] = []

        for local_index, drops in bucketed.items():
            for dropped in drops:
                item = item_database.get(dropped.id)
                x = dropped.pos.x - 8
                y = dropped.pos.y - 8

                if item.is_seed():
                    seeds.append((dropped, self._get_object_z(local_index, SUBLAYER_ICON)))
                    if text_renderer is not None and dropped.amount > 1:
                        self._build_text(text_renderer, dropped, local_index, x, y)
                    continue

                if text_renderer is not None and dropped.amount > 1:
                    self._build_text(text_renderer, dropped, local_index, x, y)

                if not no_icon:
                    tex_file = item.get_icon_texture() or item.texture_file.decode()
                    tex = self._tex_mgr.load_texture(setting.asset_path / "game" / tex_file)

                    tex_index = item.get_default_tex()
                    stride = item.get_tex_stride()
                    off = ivec2(tex_index % max(stride, 1), tex_index // stride if stride else 0)
                    tex_pos = ivec2(item.tex_coord_x, item.tex_coord_y) + off

                    uv_x = tex_pos.x * 32 / tex.width
                    uv_y = tex_pos.y * 32 / tex.height

                    icons[tex.array].extend(
                        [
                            x,
                            y,
                            icon_scale,
                            icon_scale,
                            uv_x,
                            uv_y,
                            tex.layer,
                            self._get_object_z(local_index, SUBLAYER_ICON),
                        ]
                    )

                    if not no_shadow:
                        icon_shadows[tex.array].extend(
                            [
                                x,
                                y,
                                icon_scale,
                                icon_scale,
                                uv_x,
                                uv_y,
                                tex.layer,
                                self._get_shadow_z(local_index, SHADOW_SUBLAYER_ICON),
                            ]
                        )

                if not no_overlay and item.id != GEMS:
                    overlay_tex = self._tex_mgr.load_texture(setting.asset_path / "game/pickup_box.rttex")
                    overlay[overlay_tex.array].extend(
                        [
                            x,
                            y,
                            overlay_scale,
                            overlay_scale,
                            0,
                            0,
                            overlay_tex.layer,
                            self._get_object_z(local_index, SUBLAYER_OVERLAY),
                        ]
                    )

                    if not no_shadow:
                        overlay_shadows[overlay_tex.array].extend(
                            [
                                x,
                                y,
                                overlay_scale,
                                overlay_scale,
                                0,
                                0,
                                overlay_tex.layer,
                                self._get_shadow_z(local_index, SHADOW_SUBLAYER_OVERLAY),
                            ]
                        )

        self._tex_mgr.flush()

        if text_renderer is not None:
            text_renderer.build()

        return ObjectRenderMesh(
            dropped_meshes=self._make_meshes(icons),
            pickup_overlay=self._make_meshes(overlay),
            icon_shadows=self._make_meshes(icon_shadows),
            overlay_shadows=self._make_meshes(overlay_shadows),
            seed_mesh=self._seed_renderer.build(seeds) if seeds else None,
            text_renderer=text_renderer,
        )

    def _build_text(
        self,
        text_renderer: TextRenderer,
        dropped: DroppedItem,
        local_index: int,
        x: float,
        y: float,
    ) -> None:
        overlay_size = 20 * 1.2
        vpadding = 2.0
        hpadding = 2.0
        text_width = overlay_size - hpadding * 4

        ref_width, _ = text_renderer.get_text_size("000", scale=1.0)
        auto_scale = text_width / ref_width if ref_width > 0 else 0.25

        text_str = str(dropped.amount)
        text_w, text_h = text_renderer.get_text_size(text_str, scale=auto_scale)

        if len(text_str) == 3:
            text_x = x - overlay_size / 2 + (overlay_size - text_w) / 2
        else:
            text_x = x + overlay_size / 2 - hpadding - text_w

        text_y = y + overlay_size / 2 - vpadding - text_h

        text_renderer.build_text(
            text_str,
            text_x,
            text_y,
            self._get_object_z(local_index, SUBLAYER_TEXT),
            scale=auto_scale,
            shadow_z=self._get_object_z(local_index, SUBLAYER_TEXT_SHADOW),
        )

    @staticmethod
    def _make_meshes(
        src: dict[TextureArray, list[float]],
    ) -> dict[TextureArray, Mesh]:
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

    def delete(self) -> None:
        self._seed_renderer.delete()
