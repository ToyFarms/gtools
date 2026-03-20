from collections import defaultdict, deque
import math
from dataclasses import dataclass
import time
from typing import Any, Callable
from OpenGL.GL import GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_FALSE, GL_FILL, GL_FRONT_AND_BACK, GL_LINE, GL_TRUE, glClear, glClearColor, glDepthMask, glPolygonMode

import glfw
from imgui_bundle import imgui
from pyglm import glm
from pyglm.glm import ivec2, vec2

from gtools.baked.items import PAINTING_EASEL
from gtools.core.growtopia.world import DisplayBlockTile, DroppedItem, PaintingEaselTile, ShelfTile, Tile, VendingMachineTile, World

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


@dataclass(slots=True)
class ObjectRenderable:
    mesh: ObjectRenderMesh
    renderer: ObjectRenderer
    rotation: float = 0.0
    pixel_scale: float = 1.0
    tint: tuple[float, float, float] = (1.0, 1.0, 1.0)
    z_offset: float = 0.0


class RenderOrder:
    def __init__(self) -> None:
        self._renderer: list[tuple[Callable[[Camera2D], Any], Callable[[Camera3D, float], Any]]] = []

    def add(self, draw_2d: Callable[[Camera2D], Any], draw_3d: Callable[[Camera3D, float], Any]) -> None:
        self._renderer.append((draw_2d, draw_3d))

    def clear(self) -> None:
        self._renderer.clear()

    def draw_2d(self, camera: Camera2D) -> None:
        for draw_2d, _ in self._renderer:
            draw_2d(camera)

    def draw_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        for _, draw_3d in self._renderer:
            draw_3d(camera3d, layer_spread)


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
        self._cursor_pos: tuple[float, float] = (0.0, 0.0)
        self._last_touch_event = 0.0

        self._is_active = True
        self._dirty = True

        self._mixer = AudioMixer()
        self._mixer.master_gain = 0.5
        self._sheet = self._world.get_sheet(self._mixer)

        self._highlight_renderer = HighlightRenderer()
        self._gui_menu_renderer = GuiMenuRenderer()
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
        self._init_render_order()

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

    def _build_object_renderable(self) -> list[ObjectRenderable]:
        icons: defaultdict[str, list[DroppedItem]] = defaultdict(list)
        for tile in self._world.tiles.values():
            if not tile.extra:
                continue

            if isinstance(tile.extra, DisplayBlockTile) and tile.extra.item_id != 0:
                icons["display"].append(DroppedItem(pos=vec2(tile.pos) * 32, id=tile.extra.item_id))
            elif isinstance(tile.extra, VendingMachineTile) and tile.extra.item_id != 0:
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

        if self._world.dropped.items:
            renderable.append(
                ObjectRenderable(
                    mesh=self._renderer_post_fg.build(self._world.dropped.items, icon_scale=0.67, overlay_scale=1.2, pos_offset=vec2(-8, -8)),
                    renderer=self._renderer_post_fg,
                )
            )

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
            renderable.append(
                ObjectRenderable(
                    mesh=self._renderer_post_fg.build(icons["easel_mark"], flags=flag, icon_scale=1.1, tex_offset=ivec2(0, 1)),
                    renderer=self._renderer_post_fg,
                    rotation=0.1,
                    tint=(0.3, 0.3, 0.3),
                    z_offset=0.001,
                )
            )

        if icons["vending"]:
            renderable.append(ObjectRenderable(mesh=self._renderer_post_fg.build(icons["vending"], flags=flag, icon_scale=0.5), renderer=self._renderer_post_fg))

        if icons["shelf"]:
            renderable.append(ObjectRenderable(mesh=self._renderer_post_fg.build(icons["shelf"], flags=flag, icon_scale=0.3), renderer=self._renderer_post_fg))

        return renderable

    def _init_render_order(self) -> None:
        self._render_order.clear()
        obj_renderable = self._build_object_renderable()

        self._render_order.add(
            lambda cam: self._draw_obj_group_shadows_2d(cam, obj_renderable),
            lambda cam3d, s: self._draw_obj_group_shadows_3d(cam3d, s, obj_renderable),
        )

        pre_fg_tasks = [t for t in obj_renderable if t.renderer == self._renderer_pre_fg]
        self._render_order.add(
            lambda cam: self._draw_obj_group_main_2d(cam, pre_fg_tasks),
            lambda cam3d, s: self._draw_obj_group_main_3d(cam3d, s, pre_fg_tasks),
        )

        self._render_order.add(
            lambda camera: self._tile_renderer.draw(camera),
            lambda camera3d, layer_spread: self._tile_renderer.draw_3d(camera3d, layer_spread),
        )

        post_fg_tasks = [t for t in obj_renderable if t.renderer == self._renderer_post_fg]
        self._render_order.add(
            lambda cam: self._draw_obj_group_main_2d(cam, post_fg_tasks),
            lambda cam3d, s: self._draw_obj_group_main_3d(cam3d, s, post_fg_tasks),
        )

        self._render_order.add(
            lambda camera: self._highlight_renderer.draw_hover(camera, vec2(self._hovered_tile.pos)) if self._hovered_tile else None,
            lambda camera3d, layer_spread: self._highlight_renderer.draw_hover_3d(camera3d, vec2(self._hovered_tile.pos), layer_spread) if self._hovered_tile else None,
        )

        self._render_order.add(
            lambda camera: self._highlight_renderer.draw_playhead(camera, self._sheet, self._world.width),
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

    def delete(self) -> None:
        self._mixer.stop()

        self._tile_renderer.delete()

        self._render_order.clear()

        self._renderer_pre_fg.delete()
        self._renderer_post_fg.delete()

        self._fbo.delete()
        self._highlight_renderer.delete()
        self._gui_menu_renderer.delete()

    @property
    def is_dirty(self) -> bool:
        return self._dirty or self._playing

    def update(self, dt: float) -> None:
        if self._playing:
            self._sheet.update(dt)
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

    def render(self) -> None:
        cw, ch = imgui.get_content_region_avail()
        cw, ch = int(cw), int(ch)
        if cw <= 0 or ch <= 0:
            return

        if self._fbo.width != cw or self._fbo.height != ch:
            self._fbo.resize(cw, ch)
            self._camera.resize(cw, ch)
            self._camera3d.resize(cw, ch)
            self._dirty = True

        if self._dirty:
            self._render_to_fbo()
            self._dirty = False

        imgui.image(
            imgui.ImTextureRef(self._fbo.color_tex),
            (cw, ch),
            uv0=(0, 1),
            uv1=(1, 0),
        )
        self._hovered = imgui.is_item_hovered()
        rect_min = imgui.get_item_rect_min()
        self._image_origin = (rect_min.x, rect_min.y)
        self._update_hover()

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
            elif event.button == glfw.MOUSE_BUTTON_RIGHT:
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
            elif event.button == glfw.MOUSE_BUTTON_RIGHT:
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
