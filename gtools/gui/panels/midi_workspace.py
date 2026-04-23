from pathlib import Path

from imgui_bundle import imgui

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
        self.midi: QuantizedMidiFile | None = None
        self.world = World()
        self.world_renderer = WorldRenderer(self.world)
        self.selected_instruments: set[tuple[int, int]] = set()

        if Panel.dev_mode:
            self.load("./resources/unravel.mid")

    def load(self, path: str | Path) -> None:
        midi = MidiFile(path)
        self.midi = midi.quantize(midi.get_best_bps(max_bps=13))

        row = 20
        self.world.width = int(self.midi.duration_slots // row)
        self.world.height = 14 * row
        self.world.fill()

    def _render_body(self) -> None:
        if imgui.button("Load MIDI"):
            path = ndialog.open_file("Load MIDI File", filters=[("MIDI files", "*.mid *.midi")])
            if isinstance(path, str):
                self.load(path)

        if self.midi:
            for track in self.midi.tracks:
                for inst in track.instruments:
                    key = (track.index, inst.program)
                    checked = key in self.selected_instruments
                    changed, new_value = imgui.checkbox(f"{track.index}: {inst.name}", checked)
                    if changed:
                        if new_value:
                            self.selected_instruments.add(key)
                        else:
                            self.selected_instruments.discard(key)
                        self._rebuild_sheet()

        self.world_renderer.render()

    def _rebuild_sheet(self) -> None:
        if not self.midi:
            return

        notes: list[Note] = []
        for track in self.midi.tracks:
            for inst in track.instruments:
                key = (track.index, inst.program)
                if key not in self.selected_instruments:
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
        if self.world.sheet:
            self.world.sheet.replace_notes(compress_notes(notes))
            self.world.update_sheet_flags()
            self.world.fix()
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
