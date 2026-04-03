from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from enum import IntFlag, auto
from typing import ClassVar

from OpenGL.GL import GL_FALSE, GL_TRUE, glDepthMask
from pyglm.glm import ivec2, vec2

from gtools import setting
from gtools.baked.items import GEMS, MUTATED_SEED
from gtools.core.growtopia.items_dat import ItemFlag, ItemInfoType, item_database
from gtools.core.growtopia.world import DroppedItem
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.renderer import Renderer
from gtools.gui.lib.seed_icon_renderer import SeedIconRenderer
from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.gui.texture import GLTexManager, TextureArray
from gtools.gui.lib.text_renderer import TextRenderer
import numpy as np

REGION_TILE_SIZE = 3
MAX_PER_REGION = 8192

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

GEMS_TO_TEX_OFFSET = {1: 0, 5: 1, 10: 2, 50: 3, 100: 4}


@dataclass(slots=True)
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


@dataclass(slots=True)
class IconInfo:
    texture_path: str
    world_pos: vec2
    tex_pos: ivec2
    z: float


PICKUP_BOX_BLUE = 0
PICKUP_BOX_YELLOW = 1
PICKUP_BOX_RED = 2
PICKUP_BOX_GREEN = 3
PICKUP_BOX_GOLD = 4
PICKUP_BOX_PURPLE = 5
PICKUP_BOX_ORANGE = 6
PICKUP_BOX_GRAY = 7
PICKUP_BOX_WHITE = 8


class ObjectRendererBase(Renderer, ABC):
    LAYOUT: ClassVar[list[int]] = [2, 2]
    INSTANCE_LAYOUT: ClassVar[list[int]]

    class Flags(IntFlag):
        NONE = 0
        NO_TEXT = auto()
        NO_SHADOW = auto()
        NO_OVERLAY = auto()
        NO_ICON = auto()
        # if texture has _icon variant, it will choose that instead
        # this flag disables that behaviour and uses the original texture
        USE_ORIGINAL_TEXTURE = auto()

        # will order such that the frontmost object is the highest uid
        ORDER_BY_UID = auto()

    def __init__(self, z_start: float, z_end: float) -> None:
        self._tex_mgr = GLTexManager()
        self._seed_renderer = SeedIconRenderer()

        z_mid = (z_start + z_end) / 2.0
        self._shadow_z_start = z_start
        self._shadow_z_end = z_mid
        self._object_z_start = z_mid
        self._object_z_end = z_end

        self._shadow_shader = ShaderProgram.get("shaders/object_shadow")
        self._shadow_mvp = self._shadow_shader.get_uniform("u_mvp")
        self._shadow_tex = self._shadow_shader.get_uniform("texArray")
        self._shadow_tile_size = self._shadow_shader.get_uniform("u_tileSize")
        self._shadow_offset = self._shadow_shader.get_uniform("u_shadowOffset")
        self._shadow_alpha = self._shadow_shader.get_uniform("u_shadowAlpha")
        self._shadow_z_offset = self._shadow_shader.get_uniform("u_zOffset")

        self._shadow_shader3d = ShaderProgram.from_file("shaders/object_shadow3d.vert", "shaders/object.frag")
        self._shadow_vp3d = self._shadow_shader3d.get_uniform("u_view_proj")
        self._shadow_tex3d = self._shadow_shader3d.get_uniform("texArray")
        self._shadow_tile_size3d = self._shadow_shader3d.get_uniform("u_tileSize")
        self._shadow_offset3d = self._shadow_shader3d.get_uniform("u_shadowOffset")
        self._shadow_alpha3d = self._shadow_shader3d.get_uniform("u_shadowAlpha")
        self._shadow_spread3d = self._shadow_shader3d.get_uniform("u_layer_spread")
        self._shadow_z_offset3d = self._shadow_shader3d.get_uniform("u_zOffset")

        self._shader3d = ShaderProgram.get("shaders/object3d")
        self._vp3d = self._shader3d.get_uniform("u_view_proj")
        self._tex3d = self._shader3d.get_uniform("texArray")
        self._tile_size3d = self._shader3d.get_uniform("u_tileSize")
        self._spread3d = self._shader3d.get_uniform("u_layer_spread")
        self._rotation3d = self._shader3d.get_uniform("u_rotation")
        self._pixel_scale3d = self._shader3d.get_uniform("u_pixelScale")
        self._tint3d = self._shader3d.get_uniform("u_tint")
        self._z_offset3d = self._shader3d.get_uniform("u_zOffset")

        self._init_main_shader()

    @abstractmethod
    def _init_main_shader(self) -> None: ...
    @abstractmethod
    def draw(
        self,
        camera: Camera2D,
        render_mesh: ObjectRenderMesh,
        rotation: float = 0,
        pixel_scale: float = 1,
    ) -> None: ...
    @abstractmethod
    def _make_icon_instance(
        self,
        x: float,
        y: float,
        icon_scale: float,
        uv_x: float,
        uv_y: float,
        tex_layer: float,
        z: float,
        dropped: DroppedItem,
    ) -> list[float]: ...

    def draw_shadow(self, camera: Camera2D, render_mesh: ObjectRenderMesh, z_offset: float = 0) -> None:
        if not render_mesh.dropped_meshes:
            return

        glDepthMask(GL_FALSE)

        self._shadow_shader.use()
        self._shadow_mvp.set_mat4x4(camera.proj_as_numpy())
        self._shadow_alpha.set_float(0.4)
        self._shadow_z_offset.set_float(z_offset)
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

    def draw_shadow_3d(self, camera3d: Camera3D, render_mesh: ObjectRenderMesh, layer_spread: float, z_offset: float = 0) -> None:
        if not render_mesh.dropped_meshes:
            return

        glDepthMask(GL_FALSE)

        self._shadow_shader3d.use()
        self._shadow_vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self._shadow_alpha3d.set_float(0.4)
        self._shadow_spread3d.set_float(layer_spread)
        self._shadow_z_offset3d.set_float(z_offset)
        offset = 5.0
        self._shadow_offset3d.set_vec2(np.array([-offset, offset], dtype=np.float32))

        self._shadow_tile_size3d.set_float(32.0)
        for arr, mesh in render_mesh.icon_shadows.items():
            arr.bind(unit=0)
            self._shadow_tex3d.set_int(0)
            mesh.draw_instanced()

        self._shadow_tile_size3d.set_float(20.0)
        for arr, mesh in render_mesh.overlay_shadows.items():
            arr.bind(unit=0)
            self._shadow_tex3d.set_int(0)
            mesh.draw_instanced()

        glDepthMask(GL_TRUE)

    def draw_3d(
        self,
        camera3d: Camera3D,
        render_mesh: ObjectRenderMesh,
        layer_spread: float,
        rotation: float = 0,
        pixel_scale: float = 1,
        tint: tuple[float, float, float] = (1, 1, 1),
        z_offset: float = 0,
    ) -> None:
        if not render_mesh.dropped_meshes:
            return

        self._shader3d.use()
        self._vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self._spread3d.set_float(layer_spread)
        self._rotation3d.set_float(rotation)
        self._pixel_scale3d.set_float(pixel_scale)
        self._tint3d.set_vec3(np.array(tint, dtype=np.float32))
        self._z_offset3d.set_float(z_offset)

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

        if render_mesh.text_renderer is not None:
            render_mesh.text_renderer.draw_3d(camera3d, layer_spread, offset=(0.3, 0.3), shadow_color=(0, 0, 0))

    def build(
        self,
        items: list[DroppedItem],
        tex_offset: ivec2 = ivec2(0, 0),
        pos_offset: vec2 = vec2(0, 0),
        overlay_scale: float = 1,
        icon_scale: float = 1,
        flags: "ObjectRendererBase.Flags" = Flags(0),
    ) -> ObjectRenderMesh:
        region_counters: dict[tuple[int, int], int] = defaultdict(int)
        bucketed: defaultdict[int, list[DroppedItem]] = defaultdict(list)

        if flags & ObjectRendererBase.Flags.ORDER_BY_UID:
            items = sorted(items, key=lambda x: x.uid)

        for dropped in items:
            tile_x = int(dropped.pos.x // 32)
            tile_y = int(dropped.pos.y // 32)
            region = (tile_x // REGION_TILE_SIZE, tile_y // REGION_TILE_SIZE)
            local_index = region_counters[region]
            region_counters[region] += 1
            bucketed[local_index].append(dropped)

        no_text = flags & ObjectRendererBase.Flags.NO_TEXT
        no_shadow = flags & ObjectRendererBase.Flags.NO_SHADOW
        no_overlay = flags & ObjectRendererBase.Flags.NO_OVERLAY
        no_icon = flags & ObjectRendererBase.Flags.NO_ICON

        text_renderer = None if no_text else TextRenderer("resources/fonts/centurygothic_bold.ttf", size=32)

        icons: dict[TextureArray, list[float]] = defaultdict(list)
        overlay: dict[TextureArray, list[float]] = defaultdict(list)
        icon_shadows: dict[TextureArray, list[float]] = defaultdict(list)
        overlay_shadows: dict[TextureArray, list[float]] = defaultdict(list)
        seeds: list[tuple[DroppedItem, float]] = []

        for local_index, drops in bucketed.items():
            for dropped in drops:
                item = item_database.get(dropped.id)
                x = dropped.pos.x + pos_offset.x
                y = dropped.pos.y + pos_offset.y

                NON_SEED_ID = [
                    MUTATED_SEED,
                ]
                if item.is_seed() and item.id not in NON_SEED_ID:
                    seeds.append((dropped, self._get_object_z(local_index, SUBLAYER_ICON)))
                    if text_renderer is not None and dropped.amount > 1:
                        self._build_text(vec2(16), text_renderer, dropped, local_index, x, y)
                    continue

                if item.id != GEMS and (text_renderer is not None and dropped.amount > 1):
                    self._build_text(vec2(20 * overlay_scale), text_renderer, dropped, local_index, x, y)

                if not no_icon:
                    if flags & ObjectRendererBase.Flags.USE_ORIGINAL_TEXTURE:
                        tex_file = item.texture_file.decode()
                    else:
                        tex_file = item.get_icon_texture() or item.texture_file.decode()

                    tex = self._tex_mgr.load_texture(setting.asset_path / "game" / tex_file)

                    if item.id == GEMS:
                        tex_index = GEMS_TO_TEX_OFFSET[dropped.amount]
                        stride = 5
                    else:
                        tex_index = item.get_default_tex()
                        stride = item.get_tex_stride()

                    off = ivec2(tex_index % max(stride, 1), tex_index // stride if stride else 0)
                    tex_pos = ivec2(item.tex_coord_x, item.tex_coord_y) + off + tex_offset

                    uv_x = tex_pos.x * 32 / tex.width
                    uv_y = tex_pos.y * 32 / tex.height
                    z = self._get_object_z(local_index, SUBLAYER_ICON)

                    icons[tex.array].extend(self._make_icon_instance(x, y, icon_scale, uv_x, uv_y, tex.layer, z, dropped))

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
                    tex = PICKUP_BOX_BLUE
                    if item.item_type == ItemInfoType.CONSUMABLE:
                        tex = PICKUP_BOX_PURPLE
                    elif item.item_type == ItemInfoType.LOCK:
                        tex = PICKUP_BOX_ORANGE
                    elif item.flags & ItemFlag.UNTRADEABLE:
                        tex = PICKUP_BOX_WHITE

                    uv_x = tex * 20 / overlay_tex.width

                    overlay[overlay_tex.array].extend(
                        [
                            x,
                            y,
                            overlay_scale,
                            overlay_scale,
                            uv_x,
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
            seed_mesh=self._seed_renderer.build(seeds, pos_offset) if seeds else None,
            text_renderer=text_renderer,
        )

    def build_icon(
        self,
        icons: list[IconInfo],
        icon_scale: float = 1,
        shadow: bool = False,
    ) -> ObjectRenderMesh:
        icon_data: dict[TextureArray, list[float]] = defaultdict(list)
        shadow_data: dict[TextureArray, list[float]] = defaultdict(list)

        for info in icons:
            tex = self._tex_mgr.load_texture(setting.asset_path / "game" / info.texture_path)
            uv_x = info.tex_pos.x / tex.width
            uv_y = info.tex_pos.y / tex.height

            x, y = info.world_pos.x, info.world_pos.y
            instance = [
                x,
                y,
                icon_scale,
                icon_scale,
                uv_x,
                uv_y,
                tex.layer,
                info.z,
            ]
            icon_data[tex.array].extend(instance)

            if shadow:
                shadow_instance = [
                    x,
                    y,
                    icon_scale,
                    icon_scale,
                    uv_x,
                    uv_y,
                    tex.layer,
                    info.z - 0.0001,
                ]
                shadow_data[tex.array].extend(shadow_instance)

        self._tex_mgr.flush()

        return ObjectRenderMesh(
            dropped_meshes=self._make_meshes(icon_data),
            icon_shadows=self._make_meshes(shadow_data) if shadow else {},
        )

    def _get_shadow_z(self, local_index: int, sublayer: int) -> float:
        slot = local_index * SHADOW_STRIDE + sublayer
        t = slot / MAX_SHADOW_LAYER
        return self._shadow_z_start + t * (self._shadow_z_end - self._shadow_z_start)

    def _get_object_z(self, local_index: int, sublayer: int) -> float:
        slot = local_index * LAYER_STRIDE + sublayer
        t = slot / MAX_LAYER
        return self._object_z_start + t * (self._object_z_end - self._object_z_start)

    def _build_text(
        self,
        container: vec2,
        text_renderer: TextRenderer,
        dropped: DroppedItem,
        local_index: int,
        x: float,
        y: float,
    ) -> None:
        text_width = 16

        ref_width, _ = text_renderer.get_text_size("000", scale=1.0)
        auto_scale = text_width / ref_width if ref_width > 0 else 0.25

        text_str = str(dropped.amount)
        text_w, text_h = text_renderer.get_text_size(text_str, scale=auto_scale)

        text_x = x + container.x / 2 - text_w - 2
        text_y = y + text_h

        text_renderer.build_text(
            text_str,
            text_x,
            text_y,
            self._get_object_z(local_index, SUBLAYER_TEXT),
            scale=auto_scale,
            shadow_z=self._get_object_z(local_index, SUBLAYER_TEXT_SHADOW),
        )

    def _make_meshes(
        self,
        src: dict[TextureArray, list[float]],
    ) -> dict[TextureArray, Mesh]:
        return {
            arr: Mesh(
                Mesh.RECT_WITH_UV_VERTS,
                self.LAYOUT,
                Mesh.RECT_INDICES,
                instance_data=np.array(inst, dtype=np.float32),
                instance_layout=self.INSTANCE_LAYOUT,
                instance_attrib_base=2,
            )
            for arr, inst in src.items()
        }

    def delete(self) -> None:
        self._seed_renderer.delete()


class ObjectRenderer(ObjectRendererBase):
    INSTANCE_LAYOUT: ClassVar[list[int]] = [2, 2, 2, 1, 1]

    def _init_main_shader(self) -> None:
        self._shader = ShaderProgram.get("shaders/object")
        self._mvp = self._shader.get_uniform("u_mvp")
        self._tex = self._shader.get_uniform("texArray")
        self._tile_size = self._shader.get_uniform("u_tileSize")
        self._rotation = self._shader.get_uniform("u_rotation")
        self._pixel_scale = self._shader.get_uniform("u_pixelScale")
        self._tint = self._shader.get_uniform("u_tint")
        self._z_offset = self._shader.get_uniform("u_zOffset")

    def draw(
        self,
        camera: Camera2D,
        render_mesh: ObjectRenderMesh,
        rotation: float = 0,
        pixel_scale: float = 1,
        tint: tuple[float, float, float] = (1, 1, 1),
        z_offset: float = 0,
    ) -> None:
        if not render_mesh.dropped_meshes:
            return

        self._shader.use()
        self._rotation.set_float(rotation)
        self._pixel_scale.set_float(pixel_scale)
        self._tint.set_vec3(np.array(tint, dtype=np.float32))
        self._z_offset.set_float(z_offset)
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
            render_mesh.text_renderer.draw(camera, offset=(0.3, 0.3), shadow_color=(0, 0, 0))

    def _make_icon_instance(
        self,
        x: float,
        y: float,
        icon_scale: float,
        uv_x: float,
        uv_y: float,
        tex_layer: float,
        z: float,
        dropped: DroppedItem,
    ) -> list[float]:
        return [x, y, icon_scale, icon_scale, uv_x, uv_y, tex_layer, z]
