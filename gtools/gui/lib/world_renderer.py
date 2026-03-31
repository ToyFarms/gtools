from collections import defaultdict, deque
from functools import cache
import math
from dataclasses import dataclass
import threading
import time
from typing import Any, Callable
from OpenGL.GL import (
    GL_COLOR_BUFFER_BIT,
    GL_DEPTH_BUFFER_BIT,
    GL_FALSE,
    GL_FILL,
    GL_FRONT_AND_BACK,
    GL_LINE,
    GL_TRUE,
    glClear,
    glClearColor,
    glDepthMask,
    glPolygonMode,
    glGetString,
    GL_VENDOR,
    GL_RENDERER,
    GL_VERSION,
)
import glfw
from imgui_bundle import ImVec2, imgui, imgui_knobs  # pyright: ignore[reportMissingModuleSource]
from pyglm import glm
from pyglm.glm import ivec2, vec2
import hashlib
import colorsys

from gtools.baked.items import PAINTING_EASEL
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.world import DisplayBlockTile, DroppedItem, PaintingEaselTile, SeedTile, ShelfTile, Tile, VendingMachineTile, World, WorldEvent
from gtools.core.mixer import AudioMixer
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib.layer import OBJECT_PRE_FOREGROUND_END, OBJECT_PRE_FOREGROUND_START, OBJECT_DROPPED_END, OBJECT_POST_FOREGROUND_START, WORLD_POST_FOREGROUND
from gtools.gui.lib.object_renderer import ObjectRenderMesh, ObjectRenderer
from gtools.gui.opengl import Framebuffer
from gtools.gui.event import Event, ScrollEvent, MouseButtonEvent, CursorMoveEvent, KeyEvent, TouchEvent
from gtools.gui.lib.tile_renderer import TileRenderer
from gtools.gui.lib.highlight_renderer import HighlightRenderer
from gtools.gui.lib.gui_menu_renderer import GuiMenuRenderer
from gtools.gui.lib.player_renderer import PlayerRenderer
from gtools.gui.lib.npc_renderer import NpcRenderer
import gtools.gui.lib.perf_stats as perf_stats


@dataclass(slots=True)
class ObjectRenderable:
    mesh: ObjectRenderMesh
    renderer: ObjectRenderer
    rotation: float = 0.0
    pixel_scale: float = 1.0
    tint: tuple[float, float, float] = (1.0, 1.0, 1.0)
    z_offset: float = 0.0


type RenderOrder2D = Callable[[Camera2D, Camera2D | None], Any]
type RenderOrder3D = Callable[[Camera3D, float], Any]


class RenderOrder:
    _SMOOTH_WINDOW = 30

    def __init__(self) -> None:
        self._renderer: list[tuple[str, RenderOrder2D, RenderOrder3D]] = []
        self._last_times: dict[str, float] = {}
        self._smooth_windows: defaultdict[str, deque[float]] = defaultdict(lambda: deque(maxlen=self._SMOOTH_WINDOW))

        self._last_overall_times: dict[str, float] = {}
        self._overall_smooth_windows: defaultdict[str, deque[float]] = defaultdict(lambda: deque(maxlen=self._SMOOTH_WINDOW))

    def add(self, name: str, draw_2d: RenderOrder2D, draw_3d: RenderOrder3D) -> None:
        self._renderer.append((name, draw_2d, draw_3d))

    def clear(self) -> None:
        self._renderer.clear()
        self._last_times.clear()
        self._smooth_windows.clear()
        self._last_overall_times.clear()
        self._overall_smooth_windows.clear()

    @property
    def last_times(self) -> dict[str, float]:
        return self._last_times

    @property
    def smoothed_times(self) -> dict[str, float]:
        return {name: sum(window) / len(window) for name, window in self._smooth_windows.items() if window}

    @property
    def last_overall_times(self) -> dict[str, float]:
        return self._last_overall_times

    @property
    def smoothed_overall_times(self) -> dict[str, float]:
        return {name: sum(window) / len(window) for name, window in self._overall_smooth_windows.items() if window}

    def _record(self, name: str, elapsed_ms: float) -> None:
        self._last_times[name] = elapsed_ms
        self._smooth_windows[name].append(elapsed_ms)

    def _record_overall(self, kind: str, elapsed_ms: float) -> None:
        self._last_overall_times[kind] = elapsed_ms
        self._overall_smooth_windows[kind].append(elapsed_ms)

    def draw_2d(self, camera: Camera2D, culling_camera: Camera2D | None = None) -> None:
        start_overall = time.perf_counter_ns()

        for name, draw_2d, _ in self._renderer:
            start = time.perf_counter_ns()
            draw_2d(camera, culling_camera)
            self._record(name, (time.perf_counter_ns() - start) / 1_000_000.0)

        self._record_overall("draw_2d", (time.perf_counter_ns() - start_overall) / 1_000_000.0)

    def draw_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        start_overall = time.perf_counter_ns()

        for name, _, draw_3d in self._renderer:
            start = time.perf_counter_ns()
            draw_3d(camera3d, layer_spread)
            self._record(name, (time.perf_counter_ns() - start) / 1_000_000.0)

        self._record_overall("draw_3d", (time.perf_counter_ns() - start_overall) / 1_000_000.0)


class WorldRenderer:
    def __init__(self, world: World) -> None:
        self._world = world
        self._camera = Camera2D(800, 600)
        self._camera.fit_to_rect(0, 0, self._world.width * 32, self._world.height * 32)
        self._fbo = Framebuffer(800, 600)

        self._hovered = False
        self._drag: dict = {"active": False}
        self._selection_drag: dict = {"active": False, "start": (0.0, 0.0), "current": (0.0, 0.0)}
        self._image_origin: tuple[float, float] = (0.0, 0.0)
        self._viewport_size: tuple[int, int] = (800, 600)
        self._cursor_pos: tuple[float, float] = (0.0, 0.0)
        self._last_touch_event = 0.0

        self._is_active = True
        self._dirty = True

        self._mixer = AudioMixer()
        self._mixer.master_gain = 0.5
        self._sheet = self._world.get_sheet(self._mixer)

        self._highlight_renderer = HighlightRenderer()
        self._gui_menu_renderer = GuiMenuRenderer()
        self._player_renderer = PlayerRenderer()
        self._npc_renderer = NpcRenderer()
        self._playing = True
        self._seek = 0
        self._hovered_tile: Tile | None = None

        self._mode_3d = False
        self._camera3d = Camera3D(800, 600)
        self._camera3d.fit_to_rect(0, 0, self._world.width * 32, self._world.height * 32)
        self._layer_spread: float = 200.0

        self._keys_held: set[int] = set()
        self._wireframe = False

        self._tile_renderer = TileRenderer()
        self._tile_renderer.load(self._world)

        self._renderer_pre_fg = ObjectRenderer(OBJECT_PRE_FOREGROUND_START, OBJECT_PRE_FOREGROUND_END)
        self._renderer_post_fg = ObjectRenderer(OBJECT_POST_FOREGROUND_START, OBJECT_DROPPED_END)

        self._history_2d: deque[tuple[glm.vec2, float]] = deque(maxlen=10)
        self._history_3d: deque[tuple[glm.vec3, float, float]] = deque(maxlen=10)
        self._last_right_click_time = 0.0
        self._last_right_click_pos = (0.0, 0.0)

        self._render_order = RenderOrder()
        self._obj_meshes: list[ObjectRenderMesh] = []
        self._culling_debug_zoom: float = 1.0

        self._show_settings = False
        self._settings_width = 250.0

        self._frame_times: deque[float] = deque(maxlen=50)
        self._last_frame_start = time.perf_counter_ns()
        self._peak_l, self._peak_r = 0.0, 0.0
        self._rms_l, self._rms_r = 0.0, 0.0
        self._debug_rects: dict[str, tuple[Any, Any]] = {}

        try:
            self._gl_vendor = glGetString(GL_VENDOR).decode()  # pyright: ignore[reportAttributeAccessIssue]
            self._gl_renderer = glGetString(GL_RENDERER).decode()  # pyright: ignore[reportAttributeAccessIssue]
            self._gl_version = glGetString(GL_VERSION).decode()  # pyright: ignore[reportAttributeAccessIssue]
        except Exception:
            self._gl_vendor = self._gl_renderer = self._gl_version = "unavailable"

        self._smoothed_times_cache: dict[str, float] = {}
        self._smoothed_times_last_update: float = 0.0
        self._SMOOTHED_TIMES_INTERVAL = 0.1

        self.tile_objects = 0
        self._init_render_order()

        self._needs_obj_rebuild = False
        self._tile_updates: set[tuple[int, int]] = set()
        self._tile_update_lock = threading.Lock()
        self._entity_update: bool = False
        self._entity_update_lock = threading.Lock()

        self._world.subscribe(WorldEvent.TILE_UPDATE, self._on_tile_update)
        self._world.subscribe(WorldEvent.DROPPED_UPDATE, self._on_dropped_update)
        self._world.subscribe(WorldEvent.PLAYER_UPDATE, self._on_player_update)
        self._world.subscribe(WorldEvent.NPC_UPDATE, self._on_npc_update)

    @property
    def hovered_tile(self) -> Tile | None:
        return self._hovered_tile

    @property
    def mixer(self) -> AudioMixer:
        return self._mixer

    @property
    def sheet(self):
        return self._sheet

    @property
    def playing(self) -> bool:
        return self._playing

    @playing.setter
    def playing(self, value: bool) -> None:
        if self._playing != value:
            self._playing = value
            self._dirty = True

    @property
    def mode_3d(self) -> bool:
        return self._mode_3d

    @mode_3d.setter
    def mode_3d(self, value: bool) -> None:
        if self._mode_3d != value:
            self._mode_3d = value
            self._dirty = True

    @property
    def layer_spread(self) -> float:
        return self._layer_spread

    @layer_spread.setter
    def layer_spread(self, value: float) -> None:
        if self._layer_spread != value:
            self._layer_spread = value
            self._dirty = True

    @property
    def wireframe(self) -> bool:
        return self._wireframe

    @wireframe.setter
    def wireframe(self, value: bool) -> None:
        if self._wireframe != value:
            self._wireframe = value
            self._dirty = True

    @property
    def culling_debug_zoom(self) -> float:
        return self._culling_debug_zoom

    @culling_debug_zoom.setter
    def culling_debug_zoom(self, value: float) -> None:
        if self._culling_debug_zoom != value:
            self._culling_debug_zoom = value
            self._dirty = True

    @property
    def npc_debug_line(self) -> bool:
        return self._npc_renderer.debug_line

    @npc_debug_line.setter
    def npc_debug_line(self, value: bool) -> None:
        if self._npc_renderer.debug_line != value:
            self._npc_renderer.debug_line = value
            self._dirty = True

    @property
    def tile_flags(self) -> TileRenderer.Flags:
        return self._tile_renderer.flags

    @tile_flags.setter
    def tile_flags(self, value: TileRenderer.Flags) -> None:
        if self._tile_renderer.flags != value:
            self._tile_renderer.flags = value
            self._dirty = True

    def set_active(self, active: bool) -> None:
        if self._is_active and not active:
            self._keys_held.clear()
        self._is_active = active

    @property
    def camera3d_speed(self) -> float:
        return float(self._camera3d.speed)

    def get_perf(self, out: dict[str, float]) -> None:
        if self.mode_3d:
            out["render_layer"] = self._render_order.last_overall_times["draw_3d"]
        else:
            out["render_layer"] = self._render_order.last_overall_times["draw_2d"]

    def _build_object_renderable(self) -> list[ObjectRenderable]:
        self.tile_objects = 0
        icons: defaultdict[str, list[DroppedItem]] = defaultdict(list)
        for tile in self._world.tiles.values():
            if not tile.extra:
                continue

            if isinstance(tile.extra, DisplayBlockTile) and tile.extra.item_id != 0:
                icons["display"].append(DroppedItem(pos=vec2(tile.pos) * 32, id=tile.extra.item_id))
            elif isinstance(tile.extra, VendingMachineTile) and tile.extra.item_id != 0 and tile.extra.price != 0:
                icons["vending"].append(DroppedItem(pos=vec2(tile.pos) * 32 + vec2(-2, -3), id=tile.extra.item_id))
            elif isinstance(tile.extra, PaintingEaselTile) and tile.extra.item_id != 0:
                icons["easel"].append(DroppedItem(pos=vec2(tile.pos) * 32 + vec2(2, -6), id=tile.extra.item_id))
                icons["easel_mark"].append(DroppedItem(pos=vec2(tile.pos) * 32 + vec2(2, 0), id=PAINTING_EASEL))
            elif isinstance(tile.extra, ShelfTile):
                for id, pos in (
                    (tile.extra.top_left_item_id, (-5, -8)),
                    (tile.extra.top_right_item_id, (7, -8)),
                    (tile.extra.bottom_left_item_id, (-5, 7)),
                    (tile.extra.bottom_right_item_id, (7, 7)),
                ):
                    if id != 0:
                        icons["shelf"].append(DroppedItem(pos=vec2(tile.pos) * 32 + vec2(pos), id=id))

        for obj in icons.values():
            self.tile_objects += len(obj)

        renderable: list[ObjectRenderable] = []
        if icons["display"]:
            renderable.append(
                ObjectRenderable(
                    mesh=self._renderer_pre_fg.build(
                        icons["display"],
                        flags=ObjectRenderer.Flags.NO_OVERLAY | ObjectRenderer.Flags.NO_SHADOW | ObjectRenderer.Flags.NO_TEXT,
                        icon_scale=1,
                    ),
                    renderer=self._renderer_pre_fg,
                )
            )
            self._obj_meshes.append(renderable[-1].mesh)

        if self._world.dropped.items:
            renderable.append(
                ObjectRenderable(
                    mesh=self._renderer_post_fg.build(
                        self._world.dropped.items,
                        icon_scale=0.67,
                        overlay_scale=1.2,
                        pos_offset=vec2(-8, -8),
                        flags=ObjectRenderer.Flags.ORDER_BY_UID,
                    ),
                    renderer=self._renderer_post_fg,
                )
            )
            self._obj_meshes.append(renderable[-1].mesh)

        flag = ObjectRenderer.Flags.NO_OVERLAY | ObjectRenderer.Flags.NO_SHADOW | ObjectRenderer.Flags.NO_TEXT
        if icons["easel"]:
            renderable.append(
                ObjectRenderable(
                    mesh=self._renderer_post_fg.build(icons["easel"], flags=flag, icon_scale=0.5, pos_offset=vec2(-2, 3)),
                    renderer=self._renderer_post_fg,
                    rotation=0.2,
                    pixel_scale=1.2,
                )
            )
            self._obj_meshes.append(renderable[-1].mesh)
            renderable.append(
                ObjectRenderable(
                    mesh=self._renderer_post_fg.build(icons["easel_mark"], flags=flag, icon_scale=1.1, tex_offset=ivec2(0, 1)),
                    renderer=self._renderer_post_fg,
                    rotation=0.1,
                    tint=(0.3, 0.3, 0.3),
                    z_offset=0.001,
                )
            )
            self._obj_meshes.append(renderable[-1].mesh)

        if icons["vending"]:
            renderable.append(ObjectRenderable(mesh=self._renderer_post_fg.build(icons["vending"], flags=flag, icon_scale=0.5), renderer=self._renderer_post_fg))
            self._obj_meshes.append(renderable[-1].mesh)

        if icons["shelf"]:
            renderable.append(ObjectRenderable(mesh=self._renderer_post_fg.build(icons["shelf"], flags=flag, icon_scale=0.3), renderer=self._renderer_post_fg))
            self._obj_meshes.append(renderable[-1].mesh)

        return renderable

    def _init_render_order(self) -> None:
        self._render_order.clear()
        for mesh in self._obj_meshes:
            mesh.delete()
        self._obj_meshes.clear()

        obj_renderable = self._build_object_renderable()

        self._render_order.add(
            "Obj Shadows",
            lambda cam, cull: self._draw_obj_group_shadows_2d(cam, obj_renderable),
            lambda cam3d, s: self._draw_obj_group_shadows_3d(cam3d, s, obj_renderable),
        )

        self._render_order.add(
            "Tile BG",
            lambda camera, cull: self._tile_renderer.draw(camera, "bg", culling_camera=cull),
            lambda camera3d, layer_spread: self._tile_renderer.draw_3d(camera3d, layer_spread, "bg"),
        )
        self._render_order.add(
            "Tile pre-FG",
            lambda camera, cull: self._tile_renderer.draw(camera, "fg_before", culling_camera=cull),
            lambda camera3d, layer_spread: self._tile_renderer.draw_3d(camera3d, layer_spread, "fg_before"),
        )

        pre_fg_tasks = [t for t in obj_renderable if t.renderer == self._renderer_pre_fg]
        self._render_order.add(
            "Obj pre-FG",
            lambda cam, cull: self._draw_obj_group_main_2d(cam, pre_fg_tasks),
            lambda cam3d, s: self._draw_obj_group_main_3d(cam3d, s, pre_fg_tasks),
        )

        self._render_order.add(
            "Tile FG",
            lambda camera, cull: self._tile_renderer.draw(camera, "fg", culling_camera=cull),
            lambda camera3d, layer_spread: self._tile_renderer.draw_3d(camera3d, layer_spread, "fg"),
        )
        self._render_order.add(
            "Tile post-FG",
            lambda camera, cull: self._tile_renderer.draw(camera, "fg_after", culling_camera=cull),
            lambda camera3d, layer_spread: self._tile_renderer.draw_3d(camera3d, layer_spread, "fg_after"),
        )

        post_fg_tasks = [t for t in obj_renderable if t.renderer == self._renderer_post_fg]
        self._render_order.add(
            "Obj Post-FG",
            lambda cam, cull: self._draw_obj_group_main_2d(cam, post_fg_tasks),
            lambda cam3d, s: self._draw_obj_group_main_3d(cam3d, s, post_fg_tasks),
        )

        self._render_order.add(
            "Players",
            lambda camera, cull: self._player_renderer.draw(camera, list(self._world.players.values())),
            lambda camera3d, layer_spread: self._player_renderer.draw_3d(camera3d, layer_spread, list(self._world.players.values())),
        )

        self._render_order.add(
            "NPCs",
            lambda camera, cull: self._npc_renderer.draw(camera, list(self._world.npcs.values())),
            lambda camera3d, layer_spread: self._npc_renderer.draw_3d(camera3d, layer_spread, list(self._world.npcs.values())),
        )

        self._render_order.add(
            "Fire",
            lambda camera, cull: self._tile_renderer.draw(camera, "fire", culling_camera=cull),
            lambda camera3d, layer_spread: self._tile_renderer.draw_3d(camera3d, layer_spread, "fire"),
        )
        self._render_order.add(
            "Water",
            lambda camera, cull: self._tile_renderer.draw(camera, "water", culling_camera=cull),
            lambda camera3d, layer_spread: self._tile_renderer.draw_3d(camera3d, layer_spread, "water"),
        )

        self._render_order.add(
            "Highlight",
            lambda camera, cull: self._highlight_renderer.draw_hover(camera, vec2(self._hovered_tile.pos)) if self._hovered_tile else None,
            lambda camera3d, layer_spread: self._highlight_renderer.draw_hover_3d(camera3d, vec2(self._hovered_tile.pos), layer_spread) if self._hovered_tile else None,
        )

        self._render_order.add(
            "Playhead",
            lambda camera, cull: self._highlight_renderer.draw_playhead(camera, self._sheet, self._world.width),
            lambda camera3d, layer_spread: self._highlight_renderer.draw_playhead_3d(camera3d, self._sheet, self._world.width, layer_spread),
        )

    def _draw_obj_group_shadows_2d(self, camera: Camera2D, tasks: list[ObjectRenderable]) -> None:
        glDepthMask(GL_FALSE)
        for task in tasks:
            task.renderer.draw_shadow(camera, task.mesh, z_offset=task.z_offset)
        glDepthMask(GL_TRUE)

    def _draw_obj_group_shadows_3d(self, camera3d: Camera3D, layer_spread: float, tasks: list[ObjectRenderable]) -> None:
        glDepthMask(GL_FALSE)
        for task in tasks:
            task.renderer.draw_shadow_3d(camera3d, task.mesh, layer_spread, z_offset=task.z_offset)
        glDepthMask(GL_TRUE)

    def _draw_obj_group_main_2d(self, camera: Camera2D, tasks: list[ObjectRenderable]) -> None:
        for task in tasks:
            task.renderer.draw(camera, task.mesh, rotation=task.rotation, pixel_scale=task.pixel_scale, tint=task.tint, z_offset=task.z_offset)

    def _draw_obj_group_main_3d(self, camera3d: Camera3D, layer_spread: float, tasks: list[ObjectRenderable]) -> None:
        for task in tasks:
            task.renderer.draw_3d(camera3d, task.mesh, layer_spread, rotation=task.rotation, pixel_scale=task.pixel_scale, tint=task.tint, z_offset=task.z_offset)

    def _on_tile_update(self, x: int, y: int) -> None:
        with self._tile_update_lock:
            self._tile_updates.add((x, y))

    def _on_dropped_update(self) -> None:
        self._needs_obj_rebuild = True
        self._dirty = True

    def _on_player_update(self) -> None:
        with self._entity_update_lock:
            self._entity_update = True

    def _on_npc_update(self) -> None:
        with self._entity_update_lock:
            self._entity_update = True

    def delete(self) -> None:
        self._world.unsubscribe(WorldEvent.TILE_UPDATE, self._on_tile_update)
        self._world.unsubscribe(WorldEvent.DROPPED_UPDATE, self._on_dropped_update)
        self._world.unsubscribe(WorldEvent.PLAYER_UPDATE, self._on_player_update)
        self._world.unsubscribe(WorldEvent.NPC_UPDATE, self._on_npc_update)

        self._mixer.stop()

        self._tile_renderer.delete()
        for mesh in self._obj_meshes:
            mesh.delete()
        self._obj_meshes.clear()

        self._render_order.clear()

        self._renderer_pre_fg.delete()
        self._renderer_post_fg.delete()

        self._fbo.delete()
        self._highlight_renderer.delete()
        self._gui_menu_renderer.delete()
        self._player_renderer.delete()
        self._npc_renderer.delete()

    def _render_settings(self) -> None:
        imgui.text("World Settings")
        imgui.separator()

        hovered = self._hovered_tile
        if hovered:
            if hovered.extra:
                imgui.text_wrapped(f"{hovered.extra}")
            else:
                imgui.text("-")
        else:
            imgui.text("-")

        imgui.separator()

        sheet = self._sheet
        _, sheet.bpm = imgui_knobs.knob("BPM", sheet.bpm, 20.0, 200.0, format="%.0f", size=32, variant=imgui_knobs.ImGuiKnobVariant_.wiper_only)
        imgui.same_line()
        _, self._mixer.master_gain = imgui_knobs.knob("GAIN", self._mixer.master_gain, 0.0, 1.0, format="%.2f", size=32, variant=imgui_knobs.ImGuiKnobVariant_.wiper_only)

        imgui.separator()

        _, playing = imgui.checkbox("Play", self._playing)
        self.playing = playing

        imgui.separator()

        FLAGS: list[tuple[str, TileRenderer.Flags]] = [
            ("FG", TileRenderer.Flags.RENDER_FG),
            ("BG", TileRenderer.Flags.RENDER_BG),
        ]
        for label, flag in FLAGS:
            flags = self.tile_flags
            changed, is_set = imgui.checkbox(label, flags & flag != 0)
            if changed:
                if is_set:
                    flags |= flag
                else:
                    flags &= ~flag
                self.tile_flags = flags

        imgui.separator()

        _, mode_3d = imgui.checkbox("3D", self._mode_3d)
        self.mode_3d = mode_3d

        if self._mode_3d:
            imgui.set_next_item_width(self._settings_width - 16)
            changed, spread = imgui.slider_float("Spread", self._layer_spread, 10.0, 1000.0)
            if changed:
                self.layer_spread = spread
            imgui.text(f"Speed: {self.camera3d_speed:.0f}")

        imgui.separator()

        _, wireframe = imgui.checkbox("Wireframe", self._wireframe)
        self.wireframe = wireframe

        imgui.separator()

        _, npc_debug_line = imgui.checkbox("NPC Debug Line", self.npc_debug_line)
        self.npc_debug_line = npc_debug_line

        imgui.separator()

        imgui.set_next_item_width(self._settings_width - 16)
        changed, debug_zoom = imgui.slider_float("##debug_zoom", self._culling_debug_zoom, 1.0, 10.0)
        if changed:
            self.culling_debug_zoom = debug_zoom
        imgui.text("Culling Debug")

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def update(self, dt: float) -> None:
        if self._playing:
            if self._sheet.update(dt):
                self._dirty = True

        if self._seek != 0:
            self._sheet.seek(self._seek)
            self._dirty = True

        if self._is_active:
            if self._mode_3d:
                fwd = 0.0
                rgt = 0.0
                vert = 0.0
                if glfw.KEY_W in self._keys_held:
                    fwd += 1.0
                if glfw.KEY_S in self._keys_held:
                    fwd -= 1.0
                if glfw.KEY_D in self._keys_held:
                    rgt += 1.0
                if glfw.KEY_A in self._keys_held:
                    rgt -= 1.0
                if glfw.KEY_LEFT_SHIFT in self._keys_held:
                    vert -= 1.0
                if glfw.KEY_SPACE in self._keys_held:
                    vert += 1.0

                boost = glfw.KEY_LEFT_CONTROL in self._keys_held or glfw.KEY_RIGHT_CONTROL in self._keys_held

                if fwd != 0.0 or rgt != 0.0 or vert != 0.0:
                    self._camera3d.move(fwd, rgt, vert, dt, speed_mul=2 if boost else 1)
                    self._dirty = True
            else:
                dx = 0.0
                dy = 0.0
                if glfw.KEY_W in self._keys_held:
                    dy -= 1.0
                if glfw.KEY_S in self._keys_held:
                    dy += 1.0
                if glfw.KEY_A in self._keys_held:
                    dx -= 1.0
                if glfw.KEY_D in self._keys_held:
                    dx += 1.0

                if dx != 0.0 or dy != 0.0:
                    speed = 1000.0 * dt
                    boost = glfw.KEY_LEFT_SHIFT in self._keys_held or glfw.KEY_RIGHT_SHIFT in self._keys_held
                    if boost:
                        speed *= 2.5

                    self._camera.pan_by_screen(-dx * speed, -dy * speed)
                    self._dirty = True

        if perf_stats.SHOW_DEBUG_OVERLAY:
            self._peak_l *= 0.95
            self._peak_r *= 0.95
            self._rms_l *= 0.8
            self._rms_r *= 0.8
            mixer_peaks = self._mixer.peaks
            mixer_rms = self._mixer.rms
            self._peak_l = max(self._peak_l, mixer_peaks[0])
            self._peak_r = max(self._peak_r, mixer_peaks[1])
            self._rms_l = max(self._rms_l, mixer_rms[0])
            self._rms_r = max(self._rms_r, mixer_rms[1])

        self._world.update_npc(dt)

    def render(self) -> None:
        frame_start = time.perf_counter_ns()
        self._frame_times.append((frame_start - self._last_frame_start) / 1_000_000.0)
        self._last_frame_start = frame_start

        total_w, total_h = imgui.get_content_region_avail()
        spacing = imgui.get_style().item_spacing.x

        main_w = total_w
        if self._show_settings:
            main_w = total_w - self._settings_width - spacing

        with self._tile_update_lock:
            if self._tile_updates:
                affected_chunks = set()
                for x, y in self._tile_updates:
                    affected_chunks.add((x // self._tile_renderer.CHUNK_SIZE, y // self._tile_renderer.CHUNK_SIZE))

                for cx, cy in affected_chunks:
                    self._tile_renderer.delete_chunk((cx, cy))
                    self._tile_renderer._build_chunk(self._world, cx, cy)

                trees = [t for t in self._world.tiles.values() if t.fg_id and t.extra and isinstance(t.extra, SeedTile)]
                if self._tile_renderer.tree_mesh:
                    self._tile_renderer.tree_mesh.delete()

                self._tile_renderer.tree_mesh = self._tile_renderer._tree_renderer.build(trees)
                self._tile_renderer._tex_mgr.flush()

                self._tile_updates.clear()
                self._dirty = True

        with self._entity_update_lock:
            if self._entity_update:
                self._dirty = True
                self._entity_update = False

        imgui.begin_group()

        cw, ch = int(main_w), int(total_h)
        if cw > 0 and ch > 0:
            if self._fbo.width != cw or self._fbo.height != ch:
                self._fbo.resize(cw, ch)
                self._camera.resize(cw, ch)
                self._camera3d.resize(cw, ch)
                self._dirty = True

            if self._needs_obj_rebuild:
                self._init_render_order()
                self._needs_obj_rebuild = False

            self._update_hover()

            if self._dirty:
                self._render_to_fbo()

            imgui.image(
                imgui.ImTextureRef(self._fbo.color_tex),
                (cw, ch),
                uv0=(0, 1),
                uv1=(1, 0),
            )
            self._hovered = imgui.is_item_hovered()
            rect_min = imgui.get_item_rect_min()
            self._image_origin = (rect_min.x, rect_min.y)
            self._viewport_size = (cw, ch)

            imgui.set_cursor_screen_pos(imgui.ImVec2(rect_min.x + cw - 40, rect_min.y + 10))
            if imgui.button("<" if not self._show_settings else "x", (30, 25)):
                self._show_settings = not self._show_settings

            if self._selection_drag["active"]:
                draw_list = imgui.get_window_draw_list()
                ox, oy = self._image_origin
                s = self._selection_drag["start"]
                c = self._selection_drag["current"]
                draw_list.add_rect(
                    imgui.ImVec2(ox + s[0], oy + s[1]),
                    imgui.ImVec2(ox + c[0], oy + c[1]),
                    imgui.get_color_u32(imgui.Col_.text, 1.0),
                    thickness=2.0,
                )
                draw_list.add_rect_filled(
                    imgui.ImVec2(ox + s[0], oy + s[1]),
                    imgui.ImVec2(ox + c[0], oy + c[1]),
                    imgui.get_color_u32(imgui.Col_.text, 0.2),
                )

        imgui.end_group()

        if self._show_settings:
            imgui.same_line()
            imgui.begin_child("##settings", (self._settings_width, total_h), child_flags=imgui.ChildFlags_.borders)
            self._render_settings()
            imgui.end_child()

        if perf_stats.SHOW_DEBUG_OVERLAY:
            self._render_debug_overlay()

    def _draw_vu_meter(self, draw_list: imgui.ImDrawList, pos: ImVec2, size: ImVec2, level: float, rms_level: float, label: str) -> None:
        def level_to_log(lvl: float) -> float:
            if lvl <= 0.0:
                return 0.0
            db = 20 * math.log10(max(lvl, 1e-6))
            return max(0.0, (db + 60) / 60.0)

        def level_to_color(lvl: float) -> int:
            if lvl > 0.9:
                return imgui.get_color_u32((1.0, 0.2, 0.2, 0.8))
            if lvl > 0.7:
                return imgui.get_color_u32((1.0, 1.0, 0.2, 0.8))
            return imgui.get_color_u32((0.2, 1.0, 0.2, 0.8))

        log_peak = level_to_log(level)
        log_rms = level_to_log(rms_level)

        peak_y = pos.y + size.y - size.y * min(log_peak, 1.0)
        draw_list.add_line(imgui.ImVec2(pos.x, peak_y), imgui.ImVec2(pos.x + size.x, peak_y), imgui.get_color_u32((1.0, 1.0, 1.0, 0.8)), thickness=1)

        rms_h = size.y * min(log_rms, 1.0)
        color = level_to_color(rms_level)
        draw_list.add_rect_filled(imgui.ImVec2(pos.x, pos.y + size.y - rms_h), imgui.ImVec2(pos.x + size.x, pos.y + size.y), color)

        db = 20 * math.log10(max(rms_level, 1e-6))
        db_text = f"{db:.0f}"
        text_size = imgui.calc_text_size(db_text)
        imgui.set_cursor_screen_pos(imgui.ImVec2(pos.x + (size.x - text_size.x) / 2, pos.y - 18))
        imgui.text(db_text)

        imgui.set_cursor_screen_pos(imgui.ImVec2(pos.x + (size.x - imgui.calc_text_size(label).x) / 2, pos.y + size.y + 5))
        imgui.text(label)

    @cache
    def _get_layer_color(self, name: str) -> tuple[float, float, float, float]:
        h = hashlib.md5(name.encode()).digest()
        r = 0.3 + (h[0] % 128) / 255.0
        g = 0.3 + (h[1] % 128) / 255.0
        b = 0.3 + (h[2] % 128) / 255.0
        hue, sat, _ = colorsys.rgb_to_hsv(r, g, b)
        r, g, b = colorsys.hsv_to_rgb(hue, min(sat * 1.5, 1.0), 0.8)
        return (r, g, b, 0.8)

    def _draw_pie_chart(self, draw_list, center, radius, values, labels):
        total = sum(values)
        if total == 0:
            return

        start_angle = -math.pi / 2
        for i, (val, label) in enumerate(zip(values, labels)):
            if val <= 0:
                continue
            angle = (val / total) * (math.pi * 2)

            color = imgui.get_color_u32(self._get_layer_color(label))

            num_segments = max(3, int(angle * 50))
            draw_list.path_line_to(center)
            draw_list.path_arc_to(center, radius, start_angle, start_angle + angle, num_segments)
            draw_list.path_fill_convex(color)

            start_angle += angle

    def _render_debug_overlay(self) -> None:
        ox, oy = self._image_origin
        vw, vh = self._viewport_size

        if self._frame_times:
            _ft_list = list(self._frame_times)
            _ft_sum = sum(_ft_list)
            _ft_count = len(_ft_list)
            _avg_frame = _ft_sum / _ft_count
            _fps = 1000.0 / _avg_frame
            _max_frame = max(_ft_list)
        else:
            _ft_list, _avg_frame, _fps, _max_frame = [], 0.0, 0.0, 0.0

        imgui.set_next_window_pos(imgui.ImVec2(ox, oy))
        imgui.set_next_window_size(imgui.ImVec2(vw, vh))
        imgui.begin("##debug_overlay", flags=imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.no_background | imgui.WindowFlags_.no_inputs | imgui.WindowFlags_.tooltip)

        draw_list = imgui.get_window_draw_list()
        padding = 5
        bg_col = imgui.get_color_u32((0.0, 0.0, 0.0, 0.4))

        for rect_min, rect_max in self._debug_rects.values():
            draw_list.add_rect_filled(rect_min, rect_max, bg_col, 5.0)

        imgui.set_cursor_pos((10, 10))
        imgui.begin_group()

        imgui.text_colored((1.0, 1.0, 1.0, 0.8), "gtools")

        imgui.text(f"I={1000.0 / self._frame_times[-1]:.1f} A={_fps:.1f} FPS")
        imgui.spacing()
        imgui.text(f"World: {self._world.name}")
        imgui.text(f"Dimension: {'3D' if self._mode_3d else '2D'}")

        if self._mode_3d:
            p = self._camera3d.pos
            imgui.text(f"XYZ: {p.x:.3f} / {p.y:.3f} / {p.z:.3f}")
            imgui.text(f"Block: {int(p.x // 32)}, {int(p.y // 32)}, {int(p.z // 32)}")
        else:
            p = self._camera.pos
            imgui.text(f"XYZ: {p.x:.3f} / {p.y:.3f}")
            imgui.text(f"Block: {int(p.x // 32)}, {int(p.y // 32)}")
            imgui.text(f"Chunk: {int(p.x // (32 * self._tile_renderer.CHUNK_SIZE))}, {int(p.y // (32 * self._tile_renderer.CHUNK_SIZE))}")

        if self._hovered_tile:
            imgui.text(f"Hovered: [{self._hovered_tile.pos.x}, {self._hovered_tile.pos.y}]")
            imgui.text(f"FG: {item_database.get(self._hovered_tile.fg_id).name} / BG: {item_database.get(self._hovered_tile.bg_id).name}")

        imgui.end_group()

        min_p = imgui.get_item_rect_min()
        max_p = imgui.get_item_rect_max()
        self._debug_rects["left"] = (imgui.ImVec2(min_p.x - padding, min_p.y - padding), imgui.ImVec2(max_p.x + padding, max_p.y + padding))

        padding = 10
        right_w = 320
        imgui.set_cursor_pos((vw - right_w - padding, 10))
        imgui.begin_group()

        imgui.begin_group()
        imgui.text(f"GPU: {self._gl_vendor}")
        imgui.text(f"Renderer: {self._gl_renderer}")
        imgui.text(f"GL: {self._gl_version}")
        imgui.text(f"Display: {int(vw)}x{int(vh)}")

        imgui.spacing()
        imgui.text(f"Textures: {self._tile_renderer.texture_count}")
        imgui.text(f"Objects: {len(self._world.dropped.items)}")
        imgui.text(f"Tile Objects: {self.tile_objects}")
        imgui.end_group()

        min_p = imgui.get_item_rect_min()
        max_p = imgui.get_item_rect_max()
        self._debug_rects["hw"] = (imgui.ImVec2(vw - right_w - padding, min_p.y - padding), imgui.ImVec2(vw - padding, max_p.y + padding))

        imgui.dummy((0, 20))

        imgui.begin_group()

        now_mono = time.monotonic()
        if now_mono - self._smoothed_times_last_update >= self._SMOOTHED_TIMES_INTERVAL:
            self._smoothed_times_cache = dict(self._render_order.smoothed_times)
            self._smoothed_times_last_update = now_mono
        layer_items = list(self._smoothed_times_cache.items())
        imgui.text_colored((0.6, 0.8, 1.0, 1.0), f"Render Layers ({len(layer_items)}):")

        if layer_items:
            sorted_items = sorted(layer_items, key=lambda x: x[1], reverse=True)
            layer_times = [v for _, v in sorted_items]
            layer_names = [k for k, _ in sorted_items]

            chart_radius = 35
            imgui.spacing()
            chart_cursor = imgui.get_cursor_screen_pos()
            chart_center = imgui.ImVec2(chart_cursor.x + 100, chart_cursor.y + chart_radius)
            self._draw_pie_chart(draw_list, chart_center, chart_radius, layer_times, layer_names)

            imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + chart_radius * 2 + 10)
            imgui.dummy((0, 0))

            all_times = [v for _, v in sorted_items]
            min_t = min(all_times) if all_times else 0
            max_t_layer = max(all_times) if all_times else 1
            range_t = max_t_layer - min_t if max_t_layer > min_t else 1.0

            for name, duration in sorted_items:
                color = self._get_layer_color(name)
                imgui.color_button(f"##{name}_col", color, flags=imgui.ColorEditFlags_.no_tooltip | imgui.ColorEditFlags_.no_drag_drop, size=(12, 12))
                imgui.same_line()
                imgui.text_colored(color, f"{name}:")

                imgui.same_line(offset_from_start_x=right_w - 130.0)
                imgui.text(f"{duration:.3f}ms")

                imgui.same_line(offset_from_start_x=right_w - 60.0)
                bar_pos = imgui.get_cursor_screen_pos()
                bar_w, bar_h = 30, 10

                t = (duration - min_t) / range_t
                bar_color = imgui.get_color_u32((t, 1.0 - t, 0.0, 0.8))
                draw_list.add_rect_filled(bar_pos, imgui.ImVec2(bar_pos.x + bar_w, bar_pos.y + bar_h), bar_color)

                imgui.new_line()
                imgui.set_cursor_pos_y(imgui.get_cursor_pos_y() + 2)

            imgui.dummy((0, 0))

        imgui.end_group()

        min_p = imgui.get_item_rect_min()
        max_p = imgui.get_item_rect_max()
        self._debug_rects["layers"] = (imgui.ImVec2(vw - right_w - padding, min_p.y - padding), imgui.ImVec2(vw - padding, max_p.y + padding))

        imgui.dummy((0, 20))

        imgui.begin_group()
        imgui.text_colored((1.0, 0.8, 0.4, 1.0), "Audio:")
        imgui.text(f"  BPM: {self._sheet.bpm}")
        imgui.text(f"  Streams: {self._mixer.active_streams} ({self._mixer.pending_count} pending)")
        imgui.text(f"  Playhead: {self._sheet.playhead:.1f} / {self._sheet.end}")
        imgui.end_group()

        min_p = imgui.get_item_rect_min()
        max_p = imgui.get_item_rect_max()
        self._debug_rects["audio"] = (imgui.ImVec2(vw - right_w - padding, min_p.y - padding), imgui.ImVec2(vw - padding, max_p.y + padding))

        imgui.end_group()

        vu_w, vu_h, vu_spacing = 20.0, 200.0, 15.0
        imgui.set_cursor_pos((10.0, vh - vu_h - 20.0))

        imgui.begin_group()
        vu_start_pos = imgui.get_cursor_screen_pos()
        self._draw_vu_meter(draw_list, vu_start_pos, ImVec2(vu_w, vu_h), self._peak_l, self._rms_l, "L")
        self._draw_vu_meter(draw_list, ImVec2(vu_start_pos.x + vu_w + vu_spacing, vu_start_pos.y), ImVec2(vu_w, vu_h), self._peak_r, self._rms_r, "R")
        imgui.end_group()

        min_p = imgui.get_item_rect_min()
        max_p = imgui.get_item_rect_max()
        self._debug_rects["vu"] = (
            imgui.ImVec2(min_p.x - 5.0, min_p.y - 20.0),
            imgui.ImVec2(max_p.x + 5.0, max_p.y + 5.0),
        )
        imgui.end()

    def handle_event(self, event: Event) -> bool:
        if isinstance(event, KeyEvent):
            if not self._is_active:
                return False
            if event.action == glfw.PRESS:
                self._keys_held.add(event.key)
                if event.key == glfw.KEY_3:
                    self._mode_3d = not self._mode_3d
                    self._dirty = True
                    return True
                if event.key == glfw.KEY_0:
                    self._tile_renderer.flags |= TileRenderer.Flags.RENDER_FG | TileRenderer.Flags.RENDER_BG
                    self._dirty = True
                    return True
                elif event.key == glfw.KEY_1:
                    self._tile_renderer.flags ^= TileRenderer.Flags.RENDER_FG
                    self._dirty = True
                    return True
                elif event.key == glfw.KEY_2:
                    self._tile_renderer.flags ^= TileRenderer.Flags.RENDER_BG
                    self._dirty = True
                    return True
                elif event.key == glfw.KEY_LEFT:
                    self._seek = -1
                    self._dirty = True
                    return True
                elif event.key == glfw.KEY_RIGHT:
                    self._seek = 1
                    self._dirty = True
                    return True
                elif event.key == glfw.KEY_COMMA:
                    self._sheet.seek(-1, play=True)
                    self._dirty = True
                    return True
                elif event.key == glfw.KEY_PERIOD:
                    self._sheet.seek(1, play=True)
                    self._dirty = True
                    return True
                elif event.key == glfw.KEY_R:
                    if self._mode_3d:
                        self._camera3d.fit_to_rect(0, 0, self._world.width * 32, self._world.height * 32)
                    else:
                        self._camera.fit_to_rect(0, 0, self._world.width * 32, self._world.height * 32)
                    self._dirty = True
                    return True
                elif event.key == glfw.KEY_TAB:
                    self._show_settings = not self._show_settings
                    return True
                elif event.key == glfw.KEY_F3:
                    perf_stats.SHOW_DEBUG_OVERLAY = not perf_stats.SHOW_DEBUG_OVERLAY
                    return True
                elif event.key == glfw.KEY_SPACE and not self._mode_3d:
                    self._playing = not self._playing
                    self._dirty = True
                    return True
            elif event.action == glfw.RELEASE:
                self._keys_held.discard(event.key)
                if event.key == glfw.KEY_LEFT:
                    self._seek = 0
                    return True
                elif event.key == glfw.KEY_RIGHT:
                    self._seek = 0
                    return True

        if self._mode_3d:
            return self._handle_event_3d(event)
        return self._handle_event_2d(event)

    def _handle_event_3d(self, event: Event) -> bool:
        if isinstance(event, ScrollEvent):
            if self._hovered:
                self._camera3d.speed *= 1.1**event.yoff
                self._camera3d.speed = max(50.0, min(self._camera3d.speed, 10000.0))
                self._dirty = True
                return True
        elif isinstance(event, MouseButtonEvent):
            if event.button == glfw.MOUSE_BUTTON_LEFT:
                if event.action == glfw.PRESS and self._hovered:
                    if self._selection_drag.get("active"):
                        self._selection_drag["active"] = False
                        self._dirty = True
                        return True

                    lx, ly = self._to_local(event.screen_x, event.screen_y)
                    self._drag = {
                        "active": True,
                        "last_screen": (lx, ly),
                    }
                    return True
                elif event.action == glfw.RELEASE and self._drag.get("active"):
                    self._drag["active"] = False
                    return True
            elif event.button == glfw.MOUSE_BUTTON_MIDDLE:
                if event.action == glfw.PRESS and self._hovered:
                    lx, ly = self._to_local(event.screen_x, event.screen_y)
                    now = time.monotonic()
                    if now - self._last_right_click_time < 0.3 and math.hypot(lx - self._last_right_click_pos[0], ly - self._last_right_click_pos[1]) < 10:
                        self._camera3d.fit_to_rect(0, 0, self._world.width * 32, self._world.height * 32)
                        self._last_right_click_time = 0.0
                        self._dirty = True
                        return True

                    self._last_right_click_time = now
                    self._last_right_click_pos = (lx, ly)
                    self._selection_drag = {
                        "active": True,
                        "start": (lx, ly),
                        "current": (lx, ly),
                    }
                    return True
                elif event.action == glfw.RELEASE and self._selection_drag.get("active"):
                    s = self._selection_drag["start"]
                    e = self._selection_drag["current"]
                    dist = math.hypot(e[0] - s[0], e[1] - s[1])

                    self._selection_drag["active"] = False

                    if dist < 5:
                        if self._history_3d:
                            pos, yaw, pitch = self._history_3d.pop()
                            self._camera3d.pos = pos
                            self._camera3d.yaw = yaw
                            self._camera3d.pitch = pitch
                            self._dirty = True
                        return True

                    s = self._selection_drag["start"]
                    e = self._selection_drag["current"]

                    if abs(s[0] - e[0]) > 5 and abs(s[1] - e[1]) > 5:
                        self._history_3d.append((glm.vec3(self._camera3d.pos), self._camera3d.yaw, self._camera3d.pitch))
                        z = WORLD_POST_FOREGROUND * self._layer_spread
                        p1 = self._camera3d.unproject(s[0], s[1], z_plane=z)
                        p2 = self._camera3d.unproject(e[0], e[1], z_plane=z)
                        min_x, max_x = min(p1.x, p2.x), max(p1.x, p2.x)
                        min_y, max_y = min(p1.y, p2.y), max(p1.y, p2.y)
                        self._camera3d.fit_to_rect(min_x, min_y, max_x - min_x, max_y - min_y, z=z)
                        self._dirty = True

                    return True
        elif isinstance(event, CursorMoveEvent):
            self._cursor_pos = (event.xpos, event.ypos)
            lx, ly = self._to_local(event.xpos, event.ypos)
            if self._drag.get("active"):
                prev = self._drag["last_screen"]
                dx = lx - prev[0]
                dy = ly - prev[1]
                self._drag["last_screen"] = (lx, ly)
                self._camera3d.look(dx, dy)
                self._dirty = True
                return True
            if self._selection_drag.get("active"):
                self._selection_drag["current"] = (lx, ly)
                self._dirty = True
                return True
        elif isinstance(event, TouchEvent):
            if self._hovered:
                self._last_touch_event = time.monotonic()
                self._camera3d.look(event.dx, event.dy)
                self._dirty = True
                return True
        return False

    def _handle_event_2d(self, event: Event) -> bool:
        if isinstance(event, ScrollEvent):
            if self._hovered and time.monotonic() - self._last_touch_event >= 0.5:
                lx, ly = self._to_local(event.screen_x, event.screen_y)
                self._camera.zoom_around(1.1**event.yoff, lx, ly)
                self._dirty = True
                return True
        elif isinstance(event, MouseButtonEvent):
            if event.button == glfw.MOUSE_BUTTON_LEFT:
                if event.action == glfw.PRESS and self._hovered:
                    if self._selection_drag.get("active"):
                        self._selection_drag["active"] = False
                        self._dirty = True
                        return True

                    lx, ly = self._to_local(event.screen_x, event.screen_y)
                    self._drag = {
                        "active": True,
                        "start_screen": (lx, ly),
                        "start_cam": glm.vec2(self._camera.pos),
                    }
                    return True
                elif event.action == glfw.RELEASE and self._drag.get("active"):
                    self._drag["active"] = False
                    return True
            elif event.button == glfw.MOUSE_BUTTON_MIDDLE:
                if event.action == glfw.PRESS and self._hovered:
                    lx, ly = self._to_local(event.screen_x, event.screen_y)
                    now = time.monotonic()
                    if now - self._last_right_click_time < 0.3 and math.hypot(lx - self._last_right_click_pos[0], ly - self._last_right_click_pos[1]) < 10:
                        self._camera.fit_to_rect(0, 0, self._world.width * 32, self._world.height * 32)
                        self._last_right_click_time = 0.0
                        self._dirty = True
                        return True

                    self._last_right_click_time = now
                    self._last_right_click_pos = (lx, ly)
                    self._selection_drag = {
                        "active": True,
                        "start": (lx, ly),
                        "current": (lx, ly),
                    }
                    return True
                elif event.action == glfw.RELEASE and self._selection_drag.get("active"):
                    s = self._selection_drag["start"]
                    e = self._selection_drag["current"]
                    dist = math.hypot(e[0] - s[0], e[1] - s[1])

                    self._selection_drag["active"] = False

                    if dist < 5:
                        if self._history_2d:
                            pos, zoom = self._history_2d.pop()
                            self._camera.pos = pos
                            self._camera.zoom = zoom
                            self._dirty = True
                        return True

                    s = self._selection_drag["start"]
                    e = self._selection_drag["current"]

                    if abs(s[0] - e[0]) > 5 and abs(s[1] - e[1]) > 5:
                        self._history_2d.append((glm.vec2(self._camera.pos), self._camera.zoom))
                        p1 = self._camera.screen_to_world(s[0], s[1])
                        p2 = self._camera.screen_to_world(e[0], e[1])
                        min_x, max_x = min(p1.x, p2.x), max(p1.x, p2.x)
                        min_y, max_y = min(p1.y, p2.y), max(p1.y, p2.y)
                        self._camera.fit_to_rect(min_x, min_y, max_x - min_x, max_y - min_y)
                        self._dirty = True

                    return True
        elif isinstance(event, CursorMoveEvent):
            self._cursor_pos = (event.xpos, event.ypos)
            lx, ly = self._to_local(event.xpos, event.ypos)
            if self._drag.get("active"):
                dx = lx - self._drag["start_screen"][0]
                dy = ly - self._drag["start_screen"][1]
                self._camera.pos.x = self._drag["start_cam"].x - dx / self._camera.zoom
                self._camera.pos.y = self._drag["start_cam"].y - dy / self._camera.zoom
                self._dirty = True
                return True
            if self._selection_drag.get("active"):
                self._selection_drag["current"] = (lx, ly)
                self._dirty = True
                return True
        elif isinstance(event, TouchEvent):
            if self._hovered:
                self._last_touch_event = time.monotonic()
                self._camera.pos.x -= event.dx / self._camera.zoom
                self._camera.pos.y -= event.dy / self._camera.zoom

                lx, ly = self._to_local(self._cursor_pos[0], self._cursor_pos[1])
                self._camera.zoom_around(event.scale_factor, lx, ly)
                self._dirty = True

                return True
        return False

    def _to_local(self, sx: float, sy: float) -> tuple[float, float]:
        ox, oy = self._image_origin
        return sx - ox, sy - oy

    def _render_to_fbo(self) -> None:
        self._fbo.bind()

        glClearColor(0.08, 0.08, 0.08, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)  # pyright: ignore[reportOperatorIssue]

        if self._wireframe:
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)

        if self._mode_3d:
            self._render_to_fbo_3d()
        else:
            self._render_to_fbo_2d()

        if self._wireframe:
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)

        self._fbo.unbind()

    def _render_to_fbo_3d(self) -> None:
        self._render_order.draw_3d(self._camera3d, self._layer_spread)
        if self._hovered_tile and self._hovered_tile.extra:
            self._gui_menu_renderer.draw_3d(self._camera3d, str(self._hovered_tile.extra), vec2(self._hovered_tile.pos) * 32, self._layer_spread)

    def _render_to_fbo_2d(self) -> None:
        if self._culling_debug_zoom > 1.0:
            visual_camera = Camera2D(self._camera.width, self._camera.height)
            visual_camera.pos = vec2(self._camera.pos)
            visual_camera.zoom = self._camera.zoom / self._culling_debug_zoom
            self._render_order.draw_2d(visual_camera, culling_camera=self._camera)
            if self._hovered_tile and self._hovered_tile.extra:
                self._gui_menu_renderer.draw(visual_camera, str(self._hovered_tile.extra), vec2(self._hovered_tile.pos) * 32)
        else:
            self._render_order.draw_2d(self._camera)
            if self._hovered_tile and self._hovered_tile.extra:
                self._gui_menu_renderer.draw(self._camera, str(self._hovered_tile.extra), vec2(self._hovered_tile.pos) * 32)

    def _update_hover(self) -> None:
        if not self._hovered:
            if self._hovered_tile is not None:
                self._hovered_tile = None
                self._dirty = True
            return

        old_hovered_tile = self._hovered_tile

        local = self._to_local(self._cursor_pos[0], self._cursor_pos[1])

        if self._mode_3d:
            z = WORLD_POST_FOREGROUND * self._layer_spread
            world = self._camera3d.unproject(local[0], local[1], z_plane=z)
        else:
            world = self._camera.screen_to_world(local[0], local[1])

        tile_x = math.floor((world.x + 16) / 32)
        tile_y = math.floor((world.y + 16) / 32)

        if 0 <= tile_x < self._world.width and 0 <= tile_y < self._world.height:
            self._hovered_tile = self._world.get_tile(tile_x, tile_y)
        else:
            self._hovered_tile = None

        if self._hovered_tile != old_hovered_tile:
            self._dirty = True
