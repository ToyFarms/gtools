from pathlib import Path
import time

from imgui_bundle import imgui
import numpy as np

from gtools.core import ndialog
from gtools.core.growtopia.note import Note, compress_notes
from gtools.core.growtopia.world import World
from gtools.core.midi import MidiFile, QuantizedMidiFile
from gtools.gui.event import Event
from gtools.gui.lib.world_renderer import WorldRenderer
from gtools.gui.panels.panel import Panel
from gtools.core.midi import _instrument_name
from gtools.core.growtopia.note import Note, compress_notes, InstrumentSet, MIDI_INSTRUMENT_TO_INSTRUMENT_SET

_PING_DECAY = 0.5


class MidiWorkspace(Panel):
    def __init__(self, dock_id: int) -> None:
        super().__init__(dock_id)
        self._is_docked = False
        self._first_render = True
        self.midi_file: MidiFile | None = None
        self.midi: QuantizedMidiFile | None = None
        self.world = World()
        self.world_renderer = WorldRenderer(self.world)
        self.visible_instruments: set[tuple[int, int, int]] = set()
        self.highlighted_instruments: set[tuple[int, int, int]] = set()
        self.show_instrument_panel = True
        self._dragging_marquee = False
        self._marquee_start = imgui.ImVec2(0, 0)

        self._error_curve_cache: list[tuple[float, float]] | None = None

        self._ping_times: dict[tuple[int, int, int], float] = {}

        self._instrument_search = ""
        self._active_instrument_key: tuple[int, int, int] | None = None
        self._should_open_popup = False
        self.max_bpm = 200
        self.wrap_enabled = True
        self.wrap_width = 100
        self._arbitrary_bpm = 0.0

        if Panel.dev_mode:
            self.load("./resources/bohemian.mid")

    def load(self, path: str | Path) -> None:
        self.visible_instruments.clear()
        self.highlighted_instruments.clear()
        self._ping_times.clear()

        self.world.clear()

        self.midi_file = MidiFile(path)
        self._error_curve_cache = self.midi_file.error_curve(max_bps=128)
        best_bpm = self.midi_file.get_best_bps(max_bps=int(self.max_bpm / 15)) * 15
        self._set_bpm(best_bpm)
        self.world_renderer.center()

    def _set_bpm(self, bpm: float) -> None:
        if not self.midi_file:
            return

        bps = bpm / 15.0
        self._arbitrary_bpm = bpm
        old_bpm = self.midi.bps * 15 if self.midi else None

        self.midi = self.midi_file.quantize(bps)
        self._update_world_size()

        if not self.visible_instruments:
            for track in self.midi.tracks:
                for inst in track.instruments:
                    self.visible_instruments.add((track.index, inst.channel, inst.program))

        self._rebuild_sheet()

        if old_bpm and self.world.sheet:
            self.world.sheet.playhead = int(self.world.sheet.playhead * (bpm / old_bpm))

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

        if self._should_open_popup:
            imgui.open_popup("InstrumentSelector")
            self._should_open_popup = False
            self._instrument_search = ""

        self._render_instrument_change()

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
        imgui.text(f"BPM: {self.midi.bps * 15:.2f}")
        imgui.same_line()
        imgui.text_disabled(f"({self.midi.total_error_sec():.3f}s error)")

        if imgui.button("Show All"):
            for track in self.midi.tracks:
                for inst in track.instruments:
                    self.visible_instruments.add((track.index, inst.channel, inst.program))
            self._rebuild_sheet()
        imgui.same_line()
        if imgui.button("Hide All"):
            self.visible_instruments.clear()
            self._rebuild_sheet()

        imgui.separator()

        now = time.monotonic()
        row_h = imgui.get_text_line_height_with_spacing()

        inst_rows: list[tuple[tuple, imgui.ImVec2, imgui.ImVec2]] = []

        imgui.begin_child("InstListScroll", (0, 0), False, imgui.WindowFlags_.no_move)
        draw_list = imgui.get_window_draw_list()
        card_w = imgui.get_content_region_avail()[0]

        for track in self.midi.tracks:
            if not track.instruments:
                continue

            track_name = track.name
            if not track_name and track.instruments:
                track_name = track.instruments[0].name
            if not track_name:
                track_name = "Unnamed"

            card_start = imgui.get_cursor_screen_pos()
            card_pad = 6.0
            inner_h = row_h * len(track.instruments) + card_pad * 2

            imgui.push_id(f"card_{track.index}")
            imgui.begin_group()

            hdr_h = row_h + card_pad
            draw_list.add_rect_filled(
                imgui.ImVec2(card_start.x, card_start.y),
                imgui.ImVec2(card_start.x + card_w, card_start.y + hdr_h),
                imgui.get_color_u32((0.18, 0.20, 0.25, 1.0)),
                rounding=4.0,
                flags=imgui.ImDrawFlags_.round_corners_top,
            )
            imgui.set_cursor_screen_pos(imgui.ImVec2(card_start.x + card_pad, card_start.y + card_pad * 0.5))
            imgui.text_colored((0.75, 0.85, 1.0, 1.0), f"Track {track.index}: {track_name}")

            body_start_y = card_start.y + hdr_h
            body_end_y = body_start_y + inner_h
            draw_list.add_rect_filled(
                imgui.ImVec2(card_start.x, body_start_y),
                imgui.ImVec2(card_start.x + card_w, body_end_y),
                imgui.get_color_u32((0.12, 0.13, 0.17, 1.0)),
                rounding=4.0,
                flags=imgui.ImDrawFlags_.round_corners_bottom,
            )
            draw_list.add_rect(
                imgui.ImVec2(card_start.x, card_start.y),
                imgui.ImVec2(card_start.x + card_w, body_end_y),
                imgui.get_color_u32((0.3, 0.35, 0.45, 0.6)),
                rounding=4.0,
            )

            imgui.set_cursor_screen_pos(imgui.ImVec2(card_start.x + card_pad, body_start_y + card_pad))

            for inst in track.instruments:
                key = (track.index, inst.channel, inst.program)
                is_visible = key in self.visible_instruments
                is_highlighted = key in self.highlighted_instruments

                ping_t = self._ping_times.get(key, 0.0)
                ping_age = now - ping_t
                ping_alpha = max(0.0, 1.0 - ping_age / _PING_DECAY)

                row_pos = imgui.get_cursor_screen_pos()
                row_min = row_pos
                row_max = imgui.ImVec2(card_start.x + card_w - card_pad, row_pos.y + row_h)
                inst_rows.append((key, row_min, row_max))
                row_width = row_max.x - row_min.x

                if is_highlighted:
                    draw_list.add_rect_filled(
                        imgui.ImVec2(row_min.x - 2, row_min.y),
                        imgui.ImVec2(row_max.x + 2, row_max.y),
                        imgui.get_color_u32((0.3, 0.45, 0.8, 0.35)),
                        rounding=3.0,
                    )

                selected, _ = imgui.selectable(
                    f"##row_{track.index}_{inst.channel}_{inst.program}",
                    is_highlighted,
                    imgui.SelectableFlags_.allow_overlap,
                    (row_width, row_h),
                )
                if imgui.is_item_clicked(imgui.MouseButton_.right):
                    self._active_instrument_key = key
                    self._should_open_popup = True

                imgui.set_cursor_screen_pos(row_pos)
                imgui.begin_group()

                changed, new_visible = imgui.checkbox(f"##vis_{track.index}_{inst.channel}_{inst.program}", is_visible)
                imgui.same_line()

                imgui.text_colored((1.0, 1.0, 1.0, 0.9) if is_visible else (0.5, 0.5, 0.5, 0.7), inst.name)
                imgui.end_group()

                dot_r = 4.0
                dot_cx = row_max.x - dot_r - 2.0
                dot_cy = row_pos.y + row_h * 0.5
                if ping_alpha > 0.0:
                    draw_list.add_circle_filled(imgui.ImVec2(dot_cx, dot_cy), dot_r + 2.0, imgui.get_color_u32((0.2, 1.0, 0.5, ping_alpha * 0.5)))
                    t = ping_alpha
                    dot_col = imgui.get_color_u32(
                        (
                            0.3 * (1 - t) + 0.2 * t,
                            0.3 * (1 - t) + 1.0 * t,
                            0.35 * (1 - t) + 0.5 * t,
                            1.0,
                        )
                    )
                else:
                    dot_col = imgui.get_color_u32((0.25, 0.25, 0.3, 1.0))
                draw_list.add_circle_filled(imgui.ImVec2(dot_cx, dot_cy), dot_r, dot_col)

                if not self._dragging_marquee:
                    if selected:
                        if not imgui.get_io().key_ctrl:
                            self.highlighted_instruments.clear()
                        if is_highlighted and imgui.get_io().key_ctrl:
                            self.highlighted_instruments.discard(key)
                        else:
                            self.highlighted_instruments.add(key)

                if changed:
                    if key not in self.highlighted_instruments:
                        self.highlighted_instruments.clear()
                        self.highlighted_instruments.add(key)
                    target_keys = set(self.highlighted_instruments)
                    for k in target_keys:
                        if new_visible:
                            self.visible_instruments.add(k)
                        else:
                            self.visible_instruments.discard(k)
                    self._rebuild_sheet()

                if ping_alpha > 0.0:
                    self.world_renderer._dirty = True

            imgui.end_group()
            imgui.pop_id()

            imgui.set_cursor_screen_pos(imgui.ImVec2(card_start.x, body_end_y + 6))
            imgui.dummy((0, 0))

        mouse_pos = imgui.get_mouse_pos()

        if imgui.is_window_hovered() and imgui.is_mouse_clicked(imgui.MouseButton_.left) and not imgui.is_any_item_active():
            if not imgui.get_io().key_ctrl:
                self.highlighted_instruments.clear()
            self._dragging_marquee = True
            self._marquee_start = mouse_pos

        if self._dragging_marquee:
            if imgui.is_mouse_released(imgui.MouseButton_.left):
                self._dragging_marquee = False
            else:
                m_min_x = min(self._marquee_start.x, mouse_pos.x)
                m_min_y = min(self._marquee_start.y, mouse_pos.y)
                m_max_x = max(self._marquee_start.x, mouse_pos.x)
                m_max_y = max(self._marquee_start.y, mouse_pos.y)

                for key, rmin, rmax in inst_rows:
                    if not (rmax.x < m_min_x or rmin.x > m_max_x or rmax.y < m_min_y or rmin.y > m_max_y):
                        self.highlighted_instruments.add(key)

                fg = imgui.get_foreground_draw_list()
                fg.add_rect(imgui.ImVec2(m_min_x, m_min_y), imgui.ImVec2(m_max_x, m_max_y), imgui.get_color_u32((1, 1, 1, 1)), 0, 0, 2.0)
                fg.add_rect_filled(imgui.ImVec2(m_min_x, m_min_y), imgui.ImVec2(m_max_x, m_max_y), imgui.get_color_u32((1, 1, 1, 0.1)))

        imgui.end_child()

    def _render_instrument_change(self) -> None:
        if not self._active_instrument_key or not self.midi:
            return

        imgui.set_next_window_size((400, 500), imgui.Cond_.first_use_ever)
        if imgui.begin_popup("InstrumentSelector"):
            key = self._active_instrument_key

            q_instr = None
            for track in self.midi.tracks:
                for inst in track.instruments:
                    if (track.index, inst.channel, inst.program) == key:
                        q_instr = inst
                        break
                if q_instr:
                    break

            if not q_instr:
                imgui.text_disabled("Selected instrument is no longer available.")
                if imgui.button("Close"):
                    imgui.close_current_popup()
                imgui.end_popup()
                return

            imgui.spacing()
            imgui.set_next_item_width(-1)
            _, self._instrument_search = imgui.input_text_with_hint("##search", "Search instruments", self._instrument_search)
            imgui.spacing()

            search_lower = self._instrument_search.lower()
            EXCLUDED = {InstrumentSet.BLANK, InstrumentSet.REPEAT_BEGIN, InstrumentSet.REPEAT_END}
            OPTIONS = [i for i in InstrumentSet if i not in EXCLUDED]
            filtered = [opt for opt in OPTIONS if search_lower in opt.value.lower().replace("_", " ")]

            imgui.begin_child("ctx_scroll", (0, 0), True)

            def get_instrument_params(target_set):
                if target_set == InstrumentSet.DRUM:
                    return 0, True
                for prog, s in MIDI_INSTRUMENT_TO_INSTRUMENT_SET.items():
                    if s == target_set:
                        return prog, False

                return 0, False

            for opt in filtered:
                label = opt.value.replace("_", " ").title()
                is_current = MIDI_INSTRUMENT_TO_INSTRUMENT_SET.get(q_instr.program) == opt

                clicked, _ = imgui.selectable(f"  {label}##{opt.name}", is_current)
                if clicked:
                    targets = self.highlighted_instruments if key in self.highlighted_instruments else {key}
                    new_prog, new_is_drum = get_instrument_params(opt)
                    new_name = _instrument_name(new_prog, new_is_drum)
                    self._apply_instrument_change(targets, new_prog, new_name, new_is_drum)
                    imgui.close_current_popup()
                    self._active_instrument_key = None

            if not filtered:
                imgui.text_disabled("No matches found")

            imgui.end_child()
            imgui.end_popup()

    def _apply_instrument_change(self, targets: set[tuple[int, int, int]], new_prog: int, new_name: str, new_is_drum: bool) -> None:
        if not self.midi:
            return

        for track in self.midi.tracks:
            for inst in track.instruments:
                if (track.index, inst.channel, inst.program) in targets:
                    old_key = (track.index, inst.channel, inst.program)
                    inst.program = new_prog
                    inst.name = new_name
                    inst.is_drum = new_is_drum
                    for qn in inst.notes:
                        qn.program = new_prog
                        qn.instrument_name = new_name
                        qn.is_drum = new_is_drum
                        qn.source.program = new_prog
                        qn.source.instrument_name = new_name
                        qn.source.is_drum = new_is_drum

                    if old_key in self.visible_instruments:
                        self.visible_instruments.discard(old_key)
                        self.visible_instruments.add((track.index, inst.channel, new_prog))

                    if old_key in self.highlighted_instruments:
                        self.highlighted_instruments.discard(old_key)
                        self.highlighted_instruments.add((track.index, inst.channel, new_prog))

        self._rebuild_sheet()


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

        imgui.text("Max Search BPM")
        imgui.set_next_item_width(-1)
        _, self.max_bpm = imgui.slider_int("##MaxSearchBPM", self.max_bpm, 15, 1920)
        if imgui.is_item_deactivated_after_edit() and self.midi_file:
            self._error_curve_cache = self.midi_file.error_curve(max_bps=128)
            best_bpm = self.midi_file.get_best_bps(max_bps=int(self.max_bpm / 15)) * 15
            self._set_bpm(best_bpm)

        if self.midi:
            cur_bpm = self.midi.bps * 15
            imgui.text(f"Current BPM: {cur_bpm:.2f}")
            imgui.text("Arbitrary BPM")
            imgui.set_next_item_width(-1)
            changed, new_bpm = imgui.drag_float("##ArbitraryBPM", self._arbitrary_bpm, 0.1, 1.0, 3000.0, "%.2f BPM")
            if changed:
                self._arbitrary_bpm = new_bpm
            if imgui.is_item_deactivated_after_edit():
                self._set_bpm(self._arbitrary_bpm)

        if self.midi_file and self._error_curve_cache:
            imgui.text("BPM Error Curve")
            curve = self._error_curve_cache
            bpm_vals = [c[0] * 15 for c in curve]
            err_vals = [c[1] for c in curve]

            min_err = min(err_vals)
            max_err = max(err_vals)

            imgui.plot_lines(
                "##ErrorCurve",
                np.array(err_vals, dtype=np.float32),
                values_offset=0,
                overlay_text=f"Total Error: {self.midi.total_error_sec():.4f}s" if self.midi else "Total Error (sec)",
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
                    idx = int(rel_x * (len(bpm_vals) - 1))
                    target_bpm = bpm_vals[idx]
                    imgui.begin_tooltip()
                    imgui.text(f"BPM: {target_bpm:.2f}")
                    imgui.text(f"Error: {err_vals[idx]:.4f}s")
                    imgui.end_tooltip()

                    if imgui.is_mouse_clicked(imgui.MouseButton_.left):
                        self._set_bpm(target_bpm)

    def _on_note_played(self, note: Note) -> None:
        if isinstance(note.userdata, tuple):
            self._ping_times[note.userdata] = time.monotonic()

    def _rebuild_sheet(self) -> None:
        if not self.midi:
            return

        notes: list[Note] = []
        for track in self.midi.tracks:
            for inst in track.instruments:
                key = (track.index, inst.channel, inst.program)
                if key not in self.visible_instruments:
                    continue

                for note in inst:
                    n = Note.from_midi(note.pitch, note.program, note.is_drum, note.start_slot, note.velocity)
                    if n:
                        n.userdata = (track.index, inst.channel, inst.program)
                        notes.append(n)

        bpm = self.midi.bps * 15
        self.world.remove_sheet()
        if self.world.sheet:
            self.world.sheet.replace_notes(compress_notes(notes))
            self.world.materialize_sheet()
            self.world.sheet.bpm = int(bpm)
            self.world.sheet.on_note_played = self._on_note_played

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
