from pathlib import Path

from imgui_bundle import imgui
import numpy as np

from gtools.core import ndialog
from gtools.core.growtopia.note import Note, compress_notes
from gtools.core.growtopia.world import World
from gtools.core.midi import MidiFile, QuantizedMidiFile
from gtools.gui.event import Event
from gtools.gui.lib.world_renderer import WorldRenderer
from gtools.gui.panels.panel import Panel


class MidiWorkspace(Panel):
    def __init__(self, dock_id: int) -> None:
        super().__init__(dock_id)
        self._is_docked = False
        self._first_render = True
        self.midi_file: MidiFile | None = None
        self.midi: QuantizedMidiFile | None = None
        self.world = World()
        self.world_renderer = WorldRenderer(self.world)
        self.visible_instruments: set[tuple[int, int]] = set()
        self.highlighted_instruments: set[tuple[int, int]] = set()
        self.show_instrument_panel = True
        self._dragging_marquee = False
        self._marquee_start = imgui.ImVec2(0, 0)

        self._error_curve_cache: list[tuple[float, float]] | None = None

        self.max_bps = 13
        self.wrap_enabled = True
        self.wrap_width = 100

        if Panel.dev_mode:
            self.load("./resources/unravel.mid")

    def load(self, path: str | Path) -> None:
        self.visible_instruments.clear()
        self.highlighted_instruments.clear()

        self.world.tiles.clear()

        self.midi_file = MidiFile(path)
        self._error_curve_cache = self.midi_file.error_curve(max_bps=128)
        self._set_bps(self.midi_file.get_best_bps(max_bps=self.max_bps))

    def _set_bps(self, bps: float) -> None:
        if not self.midi_file:
            return

        old_bps = self.midi.bps if self.midi else None

        self.midi = self.midi_file.quantize(bps)
        self._update_world_size()

        if not self.visible_instruments:
            for track in self.midi.tracks:
                for inst in track.instruments:
                    self.visible_instruments.add((track.index, inst.program))

        self._rebuild_sheet()

        if old_bps and self.world.sheet:
            self.world.sheet.playhead = int(self.world.sheet.playhead * (bps / old_bps))

    def _update_world_size(self) -> None:
        if not self.midi:
            return

        if self.wrap_enabled:
            w = self.wrap_width
            num_staves = (self.midi.duration_slots + w - 1) // w if w > 0 else 1
            h = max(14, num_staves * 14)
        else:
            w = self.midi.duration_slots + 1
            h = 14

        self.world.remove_sheet()
        self.world.resize(w, h)

    def _render_body(self) -> None:
        avail_w, avail_h = imgui.get_content_region_avail()
        panel_w = 300 if self.show_instrument_panel else 0

        if self.show_instrument_panel:
            imgui.begin_child("SettingsPanel", (panel_w, avail_h), True)
            self._render_panel_content()
            imgui.end_child()
            imgui.same_line()

        world_view_w = avail_w - (panel_w + imgui.get_style().item_spacing.x if self.show_instrument_panel else 0)
        imgui.begin_child("WorldView", (world_view_w, avail_h))
        self.world_renderer.render()
        imgui.end_child()

    def _render_panel_content(self) -> None:
        if imgui.button("Load MIDI"):
            path = ndialog.open_file("Load MIDI File", filters=[("MIDI files", "*.mid *.midi")])
            if isinstance(path, str):
                self.load(path)

        imgui.same_line()
        if imgui.button("Rebuild"):
            self._rebuild_sheet()

        if imgui.begin_tab_bar("PanelTabs"):
            if imgui.begin_tab_item("Instruments")[0]:
                self._render_instrument_list()
                imgui.end_tab_item()
            if imgui.begin_tab_item("Settings")[0]:
                self._render_settings()
                imgui.end_tab_item()
            imgui.end_tab_bar()

    def _render_instrument_list(self) -> None:
        if not self.midi:
            imgui.text_disabled("No MIDI loaded")
            return

        imgui.text(f"Total slots: {self.midi.duration_slots}")
        imgui.text(f"BPS: {self.midi.bps:.2f}")

        if imgui.button("Show All"):
            for track in self.midi.tracks:
                for inst in track.instruments:
                    self.visible_instruments.add((track.index, inst.program))
            self._rebuild_sheet()
        imgui.same_line()
        if imgui.button("Hide All"):
            self.visible_instruments.clear()
            self._rebuild_sheet()

        imgui.separator()

        avail_w, _ = imgui.get_content_region_avail()

        imgui.begin_child("InstListScroll", (0, 0), False, imgui.WindowFlags_.no_move)

        tree_flags = imgui.TreeNodeFlags_.default_open | imgui.TreeNodeFlags_.open_on_arrow | imgui.TreeNodeFlags_.open_on_double_click

        for track in self.midi.tracks:
            if imgui.tree_node_ex(f"Track {track.index}: {track.name or 'Unnamed'}", tree_flags):
                for inst in track.instruments:
                    key = (track.index, inst.program)
                    is_visible = key in self.visible_instruments
                    is_highlighted = key in self.highlighted_instruments

                    if is_highlighted:
                        imgui.push_style_color(imgui.Col_.header, (0.4, 0.4, 0.8, 0.5))
                        imgui.push_style_color(imgui.Col_.header_hovered, (0.5, 0.5, 0.9, 0.5))
                        bg_color = (0.3, 0.3, 0.7, 0.3)
                    else:
                        bg_color = (0, 0, 0, 0)

                    cursor_pos = imgui.get_cursor_screen_pos()
                    item_h = imgui.get_text_line_height_with_spacing()

                    draw_list = imgui.get_window_draw_list()
                    if is_highlighted:
                        draw_list.add_rect_filled(cursor_pos, imgui.ImVec2(cursor_pos.x + avail_w, cursor_pos.y + item_h), imgui.get_color_u32(bg_color))

                    changed, new_visible = imgui.checkbox(f"##vis_{track.index}_{inst.program}", is_visible)
                    imgui.same_line()

                    if imgui.is_item_clicked():
                        if not imgui.get_io().key_ctrl:
                            self.highlighted_instruments.clear()
                        if is_highlighted:
                            self.highlighted_instruments.discard(key)
                        else:
                            self.highlighted_instruments.add(key)

                    item_rect_min = imgui.get_item_rect_min()
                    item_rect_max = imgui.get_item_rect_max()
                    item_rect_min.x -= 25

                    if self._dragging_marquee:
                        m_min = imgui.ImVec2(min(self._marquee_start.x, imgui.get_mouse_pos().x), min(self._marquee_start.y, imgui.get_mouse_pos().y))
                        m_max = imgui.ImVec2(max(self._marquee_start.x, imgui.get_mouse_pos().x), max(self._marquee_start.y, imgui.get_mouse_pos().y))

                        if not (item_rect_max.x < m_min.x or item_rect_min.x > m_max.x or item_rect_max.y < m_min.y or item_rect_min.y > m_max.y):
                            self.highlighted_instruments.add(key)

                    if is_highlighted:
                        imgui.pop_style_color(2)

                    if changed:
                        target_keys = self.highlighted_instruments if key in self.highlighted_instruments else {key}
                        for k in target_keys:
                            if new_visible:
                                self.visible_instruments.add(k)
                            else:
                                self.visible_instruments.discard(k)
                        self._rebuild_sheet()
                imgui.tree_pop()

        if imgui.is_window_hovered() and imgui.is_mouse_clicked(imgui.MouseButton_.left):
            if not imgui.get_io().key_ctrl:
                self.highlighted_instruments.clear()
            self._dragging_marquee = True
            self._marquee_start = imgui.get_mouse_pos()

        if self._dragging_marquee:
            if imgui.is_mouse_released(imgui.MouseButton_.left):
                self._dragging_marquee = False
            else:
                draw_list = imgui.get_foreground_draw_list()
                m_min = imgui.ImVec2(min(self._marquee_start.x, imgui.get_mouse_pos().x), min(self._marquee_start.y, imgui.get_mouse_pos().y))
                m_max = imgui.ImVec2(max(self._marquee_start.x, imgui.get_mouse_pos().x), max(self._marquee_start.y, imgui.get_mouse_pos().y))
                draw_list.add_rect(m_min, m_max, imgui.get_color_u32((1, 1, 1, 1)), 0, 0, 2.0)
                draw_list.add_rect_filled(m_min, m_max, imgui.get_color_u32((1, 1, 1, 0.1)))

        imgui.end_child()

    def _render_settings(self) -> None:
        changed_wrap, self.wrap_enabled = imgui.checkbox("Wrap", self.wrap_enabled)
        if changed_wrap:
            self._update_world_size()
            self._rebuild_sheet()

        if self.wrap_enabled:
            imgui.text("Wrap Width")
            imgui.set_next_item_width(-1)
            _, self.wrap_width = imgui.slider_int("##WrapWidth", self.wrap_width, 10, 1000)
            if imgui.is_item_deactivated_after_edit():
                self._update_world_size()
                self._rebuild_sheet()

        imgui.separator()
        imgui.text("Quantization")

        imgui.text("Max Search BPS")
        imgui.set_next_item_width(-1)
        _, self.max_bps = imgui.slider_int("##MaxSearchBPS", self.max_bps, 1, 128)
        if imgui.is_item_deactivated_after_edit() and self.midi_file:
            self._error_curve_cache = self.midi_file.error_curve(max_bps=128)
            self._set_bps(self.midi_file.get_best_bps(max_bps=self.max_bps))

        if self.midi:
            cur_bps = self.midi.bps
            imgui.text(f"Current BPS: {cur_bps:.2f}")
            imgui.text("Arbitrary BPS")
            imgui.set_next_item_width(-1)
            _, new_bps = imgui.input_float("##ArbitraryBPS", cur_bps)
            if imgui.is_item_deactivated_after_edit():
                self._set_bps(new_bps)

        if self.midi_file and self._error_curve_cache:
            imgui.text("BPS Error Curve")
            curve = self._error_curve_cache
            bps_vals = [c[0] for c in curve]
            err_vals = [c[1] for c in curve]

            min_err = min(err_vals)
            max_err = max(err_vals)

            imgui.plot_lines(
                "##ErrorCurve",
                np.array(err_vals, dtype=np.float32),
                values_offset=0,
                overlay_text="Total Error (sec)",
                scale_min=min_err,
                scale_max=max_err,
                graph_size=imgui.ImVec2(0, 80),
            )

            if imgui.is_item_hovered():
                mouse_pos = imgui.get_mouse_pos()
                rect_min = imgui.get_item_rect_min()
                rect_max = imgui.get_item_rect_max()

                width = rect_max.x - rect_min.x
                rel_x = (mouse_pos.x - rect_min.x) / width
                if 0 <= rel_x <= 1:
                    idx = int(rel_x * (len(bps_vals) - 1))
                    target_bps = bps_vals[idx]
                    imgui.begin_tooltip()
                    imgui.text(f"BPS: {target_bps}")
                    imgui.text(f"Error: {err_vals[idx]:.4f}s")
                    imgui.end_tooltip()

                    if imgui.is_mouse_clicked(imgui.MouseButton_.left):
                        self._set_bps(target_bps)

    def _rebuild_sheet(self) -> None:
        if not self.midi:
            return

        notes: list[Note] = []
        for track in self.midi.tracks:
            for inst in track.instruments:
                key = (track.index, inst.program)
                if key not in self.visible_instruments:
                    continue

                for note in inst:
                    notes.append(
                        Note.from_midi(
                            note.pitch,
                            note.program,
                            note.start_slot,
                            note.velocity,
                        )
                    )

        bpm = int(self.midi.bps * 60 / 4)
        self.world.remove_sheet()
        if self.world.sheet:
            self.world.sheet.replace_notes(compress_notes(notes))
            self.world.materialize_sheet()
            self.world.sheet.bpm = bpm

    @property
    def is_dirty(self) -> bool:
        return self.world_renderer.is_dirty

    @is_dirty.setter
    def is_dirty(self, x: bool) -> None:
        self.world_renderer._dirty = x

    def update(self, dt: float) -> None:
        self.world_renderer.update(dt)

    def render(self) -> None:
        if not self._is_docked and self.dock_id:
            imgui.set_next_window_dock_id(self.dock_id)

        opened, self._open = imgui.begin("MIDI Workspace", self._open)

        if not self._is_docked and imgui.is_window_docked():
            self._is_docked = True

        if self._first_render:
            self._first_render = False

        if opened:
            self._render_body()

        imgui.end()

    def handle_event(self, event: Event) -> bool:
        return self.world_renderer.handle_event(event)

    def delete(self) -> None:
        self.world_renderer.delete()
