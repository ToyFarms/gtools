import logging
from pathlib import Path
from imgui_bundle import imgui, ImVec2
import glfw
import OpenGL.GL as gl
from pyglm.glm import vec2
from pyglm import glm

from gtools.core import ndialog
from gtools.gui.event import Event, ScrollEvent, MouseButtonEvent, CursorMoveEvent
from gtools.gui.panels.panel import Panel
from gtools.gui.camera import Camera2D
from gtools.gui.opengl import Framebuffer
from gtools.gui.lib.midi_track_renderer import MidiTrackRenderer

logger = logging.getLogger("gui-midi-panel")


class MidiPanel(Panel):
    def __init__(self, dock_id: int) -> None:
        super().__init__(dock_id)
        self._is_docked = False
        self._first_render = True
        self._midi_path: Path | None = None
        self._renderer = MidiTrackRenderer()
        self._camera = Camera2D(800, 600)
        self._fbo = Framebuffer(800, 600)

        self._viewport_hovered = False
        self._view_min = ImVec2(0, 0)
        self._drag = {"active": False, "start_screen": (0.0, 0.0), "start_cam": None}

    def _render_body(self) -> None:
        if imgui.button("Load MIDI"):
            path = ndialog.open_file("Load MIDI File", filters=[("MIDI files", "*.mid *.midi")])
            if isinstance(path, str):
                self.load_midi(Path(path))

        imgui.same_line()
        if self._midi_path:
            imgui.text(f"File: {self._midi_path.name}")
        else:
            imgui.text("No file loaded")

        imgui.separator()

        avail_w, avail_h = imgui.get_content_region_avail()
        track_list_w = 200

        imgui.begin_child("TrackList", (track_list_w, avail_h), True)
        imgui.text("Tracks")
        imgui.separator()
        for idx, (name, visible, color) in self._renderer.track_info.items():
            changed, is_visible = imgui.checkbox(f"##track_{idx}", visible)
            if changed:
                self._renderer.set_track_visibility(idx, is_visible)

            imgui.same_line()
            imgui.color_button(f"##color_{idx}", color, imgui.ColorEditFlags_.no_tooltip, (16, 16))
            imgui.same_line()
            imgui.text(name)
        imgui.end_child()

        imgui.same_line()

        viewport_w = avail_w - track_list_w - imgui.get_style().item_spacing.x
        if viewport_w > 0 and avail_h > 0:
            if self._fbo.width != int(viewport_w) or self._fbo.height != int(avail_h):
                self._fbo.resize(int(viewport_w), int(avail_h))
                self._camera.resize(int(viewport_w), int(avail_h))

            self._fbo.bind()

            gl.glClearColor(0.1, 0.1, 0.1, 1.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)  # pyright: ignore[reportOperatorIssue]
            self._renderer.draw(self._camera)
            self._fbo.unbind()

            imgui.image(imgui.ImTextureRef(self._fbo.color_tex), (viewport_w, avail_h), uv0=(0, 1), uv1=(1, 0))
            self._viewport_hovered = imgui.is_item_hovered()
            self._view_min = imgui.get_item_rect_min()

            if viewport_w > 0 and avail_h > 0:
                draw_list = imgui.get_window_draw_list()

                key_w = 40
                draw_list.add_rect_filled(self._view_min, ImVec2(self._view_min.x + key_w, self._view_min.y + avail_h), imgui.get_color_u32((0.12, 0.12, 0.12, 1.0)))

                for p in range(128):
                    y_world = (127 - p) * 32.0
                    hh = avail_h / (2.0 * self._camera.zoom)
                    norm_y = (y_world - (self._camera.pos.y - hh)) / (2.0 * hh)
                    screen_y = self._view_min.y + (norm_y * avail_h)

                    h = 32.0 * self._camera.zoom
                    if screen_y < self._view_min.y - h or screen_y > self._view_min.y + avail_h + h:
                        continue

                    is_black = (p % 12) in (1, 3, 6, 8, 10)
                    draw_list.add_rect(ImVec2(self._view_min.x, screen_y), ImVec2(self._view_min.x + key_w, screen_y + h), imgui.get_color_u32((0.5, 0.5, 0.5, 0.3)))
                    if is_black:
                        draw_list.add_rect_filled(ImVec2(self._view_min.x, screen_y), ImVec2(self._view_min.x + key_w * 0.7, screen_y + h), imgui.get_color_u32((0, 0, 0, 1.0)))
                    else:
                        draw_list.add_rect_filled(ImVec2(self._view_min.x, screen_y), ImVec2(self._view_min.x + key_w, screen_y + h), imgui.get_color_u32((1, 1, 1, 1.0)))
                        if p % 12 == 0:
                            imgui.set_cursor_screen_pos(ImVec2(self._view_min.x + 2, screen_y + 2))
                            imgui.text_disabled(f"C{p//12}")

                bar_h = 24
                draw_list.add_rect_filled(self._view_min, ImVec2(self._view_min.x + viewport_w, self._view_min.y + bar_h), imgui.get_color_u32((0.1, 0.1, 0.1, 0.9)))

                ppq_scaled = self._renderer.ppq * 0.1
                bpb = self._renderer.beats_per_bar
                ticks_per_bar = ppq_scaled * bpb

                pixels_per_bar = ticks_per_bar * self._camera.zoom
                bar_step = 1
                if pixels_per_bar < 20:
                    bar_step = 16
                elif pixels_per_bar < 40:
                    bar_step = 8
                elif pixels_per_bar < 80:
                    bar_step = 4
                elif pixels_per_bar < 150:
                    bar_step = 2

                hw = viewport_w / (2.0 * self._camera.zoom)
                visible_min_x = self._camera.pos.x - hw
                visible_max_x = self._camera.pos.x + hw

                start_bar = int(visible_min_x / ticks_per_bar)
                end_bar = int(visible_max_x / ticks_per_bar) + 1

                for b in range(start_bar, end_bar):
                    if b % bar_step != 0:
                        continue

                    x_scaled = b * ticks_per_bar
                    mx = x_scaled - visible_min_x
                    norm_x = mx / (2.0 * hw)
                    screen_x = self._view_min.x + (norm_x * viewport_w)

                    if screen_x < self._view_min.x or screen_x > self._view_min.x + viewport_w:
                        continue

                    draw_list.add_line(ImVec2(screen_x, self._view_min.y), ImVec2(screen_x, self._view_min.y + bar_h), imgui.get_color_u32((1, 1, 1, 0.3)))
                    imgui.set_cursor_screen_pos(ImVec2(screen_x + 2, self._view_min.y + 2))
                    imgui.text_disabled(f"{b+1}")

    def _apply_constraints(self) -> None:
        min_x, max_x = 0, 0
        min_y, max_y = 0, 128 * 32.0
        for track in self._renderer._tracks.values():
            for note in track:
                max_x = max(max_x, (note["start"] + note["duration"]) * 0.1)

        max_x += 200

        self._camera.zoom = max(0.01, min(self._camera.zoom, 10.0))

        hw = self._camera.width / (2.0 * self._camera.zoom)
        hh = self._camera.height / (2.0 * self._camera.zoom)

        self._camera.pos.x = max(min_x - hw, min(self._camera.pos.x, max_x + hw))
        self._camera.pos.y = max(min_y - hh, min(self._camera.pos.y, max_y + hh))

    def load_midi(self, path: Path) -> None:
        self._midi_path = path
        self._renderer.load_midi(path)

        min_x, max_x = float("inf"), float("-inf")
        min_y, max_y = float("inf"), float("-inf")
        any_notes = False
        for track in self._renderer._tracks.values():
            for note in track:
                any_notes = True

                min_x = min(min_x, note["start"] * 0.1)
                max_x = max(max_x, (note["start"] + note["duration"]) * 0.1)

                y_val = (127 - note["pitch"]) * 32.0
                min_y = min(min_y, y_val)
                max_y = max(max_y, y_val + 32.0)

        if any_notes:
            self._camera.fit_to_rect(min_x, min_y, max_x - min_x, max_y - min_y, padding=100)
        else:

            self._camera.pos = vec2(0, 64 * 32.0)
            self._camera.zoom = 1.0
        self._apply_constraints()

    @property
    def is_dirty(self) -> bool:
        return True

    @is_dirty.setter
    def is_dirty(self, x: bool) -> None:
        pass

    def update(self, dt: float) -> None:
        pass

    def render(self) -> None:
        if not self._is_docked and self.dock_id:
            imgui.set_next_window_dock_id(self.dock_id)

        opened, self._open = imgui.begin("Midi", self._open)
        if not self._is_docked and imgui.is_window_docked():
            self._is_docked = True

        if self._first_render:
            self._first_render = False

        if opened:
            self._render_body()
        imgui.end()

    def handle_event(self, event: Event) -> bool:
        if isinstance(event, ScrollEvent):
            if self._viewport_hovered:
                mx = event.screen_x - self._view_min.x
                my = event.screen_y - self._view_min.y
                self._camera.zoom_around(1.1**event.yoff, mx, my)
                self._apply_constraints()
                return True
        elif isinstance(event, MouseButtonEvent):
            if event.button == glfw.MOUSE_BUTTON_LEFT:
                if event.action == glfw.PRESS and self._viewport_hovered:
                    self._drag = {
                        "active": True,
                        "start_screen": (event.screen_x - self._view_min.x, event.screen_y - self._view_min.y),
                        "start_cam": glm.vec2(self._camera.pos),
                    }
                    return True
                elif event.action == glfw.RELEASE and self._drag["active"]:
                    self._drag["active"] = False
                    return True
        elif isinstance(event, CursorMoveEvent):
            if self._drag["active"]:
                mx = event.xpos - self._view_min.x
                my = event.ypos - self._view_min.y
                dx = mx - self._drag["start_screen"][0]
                dy = my - self._drag["start_screen"][1]
                self._camera.pos.x = self._drag["start_cam"].x - dx / self._camera.zoom
                self._camera.pos.y = self._drag["start_cam"].y - dy / self._camera.zoom
                self._apply_constraints()
                return True
        return False

    def delete(self) -> None:
        self._renderer.delete()
        self._fbo.delete()
