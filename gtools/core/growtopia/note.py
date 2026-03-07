from collections import defaultdict
from enum import Enum
import logging
from dataclasses import dataclass
from pathlib import Path
import threading

from gtools import setting
from gtools.core.mixer import AudioMixer, Sound
from gtools.baked.items import (
    SHEET_MUSIC_COLON_BASS_NOTE,
    SHEET_MUSIC_COLON_BLANK,
    SHEET_MUSIC_COLON_DRUMS,
    SHEET_MUSIC_COLON_ELECTRIC_GUITAR,
    SHEET_MUSIC_COLON_FLAT_BASS,
    SHEET_MUSIC_COLON_FLAT_ELECTRIC_GUITAR,
    SHEET_MUSIC_COLON_FLAT_FLUTE,
    SHEET_MUSIC_COLON_FLAT_LYRE,
    SHEET_MUSIC_COLON_FLAT_MEXICAN_TRUMPET,
    SHEET_MUSIC_COLON_FLAT_PIANO,
    SHEET_MUSIC_COLON_FLAT_SAX,
    SHEET_MUSIC_COLON_FLAT_SPANISH_GUITAR,
    SHEET_MUSIC_COLON_FLAT_VIOLIN,
    SHEET_MUSIC_COLON_FLUTE_NOTE,
    SHEET_MUSIC_COLON_LYRE_NOTE,
    SHEET_MUSIC_COLON_MEXICAN_TRUMPET,
    SHEET_MUSIC_COLON_PIANO_NOTE,
    SHEET_MUSIC_COLON_REPEAT_BEGIN,
    SHEET_MUSIC_COLON_REPEAT_END,
    SHEET_MUSIC_COLON_SAX_NOTE,
    SHEET_MUSIC_COLON_SHARP_BASS,
    SHEET_MUSIC_COLON_SHARP_ELECTRIC_GUITAR,
    SHEET_MUSIC_COLON_SHARP_FLUTE,
    SHEET_MUSIC_COLON_SHARP_LYRE,
    SHEET_MUSIC_COLON_SHARP_MEXICAN_TRUMPET,
    SHEET_MUSIC_COLON_SHARP_PIANO,
    SHEET_MUSIC_COLON_SHARP_SAX,
    SHEET_MUSIC_COLON_SHARP_SPANISH_GUITAR,
    SHEET_MUSIC_COLON_SHARP_VIOLIN,
    SHEET_MUSIC_COLON_SPANISH_GUITAR_NOTE,
    SHEET_MUSIC_COLON_SPOOKY,
    SHEET_MUSIC_COLON_VIOLIN_NOTE,
    SHEET_MUSIC_COLON_WINTERFEST,
)


class InstrumentSet(Enum):
    BLANK = "blank"
    REPEAT_BEGIN = "repeat_begin"
    REPEAT_END = "repeat_end"
    BASS = "bass"
    DRUM = "drum"
    ELECTRIC_GUITAR = "electric_guitar"
    FESTIVE = "festive"
    FLUTE = "flute"
    LYRE = "lyre"
    MEXICAN_TRUMPET = "mexican_trumpet"
    PIANO = "piano"
    SAX = "sax"
    SPANISH_GUITAR = "spanish_guitar"
    SPOOKY = "spooky"
    VIOLIN = "violin"


@dataclass(slots=True)
class Note:
    C = 1
    D = 3
    E = 5
    F = 6
    G = 8
    A = 10
    B = 12
    FLAT = -1
    NATURAL = 0
    SHARP = 1

    base: int
    octave: int
    accident: int = NATURAL
    instrument: InstrumentSet = InstrumentSet.PIANO
    timestamp: int = 0
    duration: float = 0.0
    volume: float = 1.0

    def to_index(self) -> int:
        if self.instrument == InstrumentSet.DRUM:
            index = {
                Note.C: 6,
                Note.D: 5,
                Note.E: 4,
                Note.F: 3,
                Note.G: 2,
                Note.A: 1,
                Note.B: 0,
            }[self.base]
        else:
            index = 12 * self.octave + self.base + self.accident

        return index

    def to_path(self) -> Path:
        return setting.asset_path / "audio/notes" / f"{self.instrument.value}_{self.to_index()}.wav"


_SOUNDS: dict[Path, Sound] = {}


class Sheet:
    logger = logging.getLogger("sheet")

    def __init__(self, bpm: int, notes: list[Note], mixer: AudioMixer) -> None:
        self.notes: defaultdict[int, list[Note]] = defaultdict(list)
        for note in notes:
            self.notes[note.timestamp].append(note)

        self.start = min(notes, key=lambda x: x.timestamp).timestamp
        self.end = max(notes, key=lambda x: x.timestamp).timestamp

        self.bpm = bpm
        self.bps = (bpm * 4) / 60

        self.mixer = mixer

        self.playhead = self.start
        self._accum = 0.0

        self._activated_repeats: set[tuple[int, int]] = set()
        self._pending_backtrack: int | None = None

        self._can_go = threading.Event()
        self._preload_thread = threading.Thread(target=self._preload, daemon=True)
        self._preload_thread.start()
        # TODO: configurable volume

    def _preload(self) -> None:
        for col in range(self.start, self.end):
            if col == 10:
                self._can_go.set()
            for note in self.notes[col]:
                if note.instrument in (InstrumentSet.REPEAT_BEGIN, InstrumentSet.REPEAT_END, InstrumentSet.BLANK):
                    continue
                path = note.to_path()
                if path not in _SOUNDS:
                    _SOUNDS[path] = Sound.from_file(str(path), volume=0.5)
        self._can_go.set()

    def _find_repeat_begin(self, end_note: Note) -> int:
        row = end_note.to_index()
        for col in range(end_note.timestamp - 1, self.start - 1, -1):
            for note in self.notes[col]:
                if note.instrument == InstrumentSet.REPEAT_BEGIN and note.to_index() == row:
                    return col
        return self.start

    def advance_playhead(self, n: int = 1) -> None:
        self._can_go.wait()

        if self._pending_backtrack is not None:
            self.playhead = self._pending_backtrack
            self._pending_backtrack = None

        for note in self.notes[self.playhead]:
            if note.instrument != InstrumentSet.REPEAT_END:
                continue
            key = (note.timestamp, note.to_index())
            if key in self._activated_repeats:
                continue

            self._activated_repeats.add(key)
            backtrack = self._find_repeat_begin(note)
            row = note.to_index()

            for col in range(backtrack, self.playhead):
                for inner in self.notes[col]:
                    if inner.instrument == InstrumentSet.REPEAT_END and inner.to_index() == row:
                        self._activated_repeats.discard((inner.timestamp, inner.to_index()))

            self._pending_backtrack = backtrack
            break

        for note in self.notes[self.playhead]:
            if note.instrument in (InstrumentSet.REPEAT_BEGIN, InstrumentSet.REPEAT_END, InstrumentSet.BLANK):
                continue
            path = note.to_path()
            if path not in _SOUNDS:
                _SOUNDS[path] = Sound.from_file(str(path), volume=0.5)
            self.mixer.play(_SOUNDS[path])

        self.playhead += n
        if self.playhead > self.end:
            self.playhead = self.start
            self._activated_repeats.clear()
            self._pending_backtrack = None

    def seek(self, direction: int, play: bool = False) -> None:
        if play:
            self.advance_playhead(direction)
        else:
            self.playhead += direction

        if direction < 0:
            self._activated_repeats.clear()
            self._pending_backtrack = None

    def update(self, dt: float) -> None:
        self._can_go.wait()
        tick_duration = 1.0 / self.bps
        self._accum += min(dt, tick_duration)
        while self._accum >= tick_duration:
            self.advance_playhead()
            self._accum -= tick_duration


CODE_TO_INSTRUMENT_SET = {
    "B": InstrumentSet.BASS,
    "D": InstrumentSet.DRUM,
    "E": InstrumentSet.ELECTRIC_GUITAR,
    "F": InstrumentSet.FLUTE,
    "G": InstrumentSet.SPANISH_GUITAR,
    "L": InstrumentSet.LYRE,
    "P": InstrumentSet.PIANO,
    "S": InstrumentSet.SAX,
    "T": InstrumentSet.MEXICAN_TRUMPET,
    "V": InstrumentSet.VIOLIN,
}
ACCIDENT_MAP = {
    "#": Note.SHARP,
    "-": Note.NATURAL,
    "b": Note.FLAT,
}
CODE_TO_PITCH_MAP = {
    "c": (Note.C, 0),
    "d": (Note.D, 0),
    "e": (Note.E, 0),
    "f": (Note.F, 0),
    "g": (Note.G, 0),
    "a": (Note.A, 0),
    "b": (Note.B, 0),
    "C": (Note.C, 1),
    "D": (Note.D, 1),
    "E": (Note.E, 1),
    "F": (Note.F, 1),
    "G": (Note.G, 1),
    "A": (Note.A, 1),
    "B": (Note.B, 1),
}

Y_TO_PITCH_MAP = [
    (Note.B, 1),
    (Note.A, 1),
    (Note.G, 1),
    (Note.F, 1),
    (Note.E, 1),
    (Note.D, 1),
    (Note.C, 1),
    (Note.B, 0),
    (Note.A, 0),
    (Note.G, 0),
    (Note.F, 0),
    (Note.E, 0),
    (Note.D, 0),
    (Note.C, 0),
]


SHEET_SHARP_ID = {
    SHEET_MUSIC_COLON_SHARP_BASS,
    SHEET_MUSIC_COLON_SHARP_PIANO,
    SHEET_MUSIC_COLON_SHARP_SAX,
    SHEET_MUSIC_COLON_SHARP_FLUTE,
    SHEET_MUSIC_COLON_SHARP_SPANISH_GUITAR,
    SHEET_MUSIC_COLON_SHARP_VIOLIN,
    SHEET_MUSIC_COLON_SHARP_LYRE,
    SHEET_MUSIC_COLON_SHARP_ELECTRIC_GUITAR,
    SHEET_MUSIC_COLON_SHARP_MEXICAN_TRUMPET,
}

SHEET_FLAT_ID = {
    SHEET_MUSIC_COLON_FLAT_BASS,
    SHEET_MUSIC_COLON_FLAT_PIANO,
    SHEET_MUSIC_COLON_FLAT_SAX,
    SHEET_MUSIC_COLON_FLAT_FLUTE,
    SHEET_MUSIC_COLON_FLAT_SPANISH_GUITAR,
    SHEET_MUSIC_COLON_FLAT_VIOLIN,
    SHEET_MUSIC_COLON_FLAT_LYRE,
    SHEET_MUSIC_COLON_FLAT_ELECTRIC_GUITAR,
    SHEET_MUSIC_COLON_FLAT_MEXICAN_TRUMPET,
}


ID_TO_INSTRUMENT_SET = {
    SHEET_MUSIC_COLON_BLANK: InstrumentSet.BLANK,
    SHEET_MUSIC_COLON_BASS_NOTE: InstrumentSet.BASS,
    SHEET_MUSIC_COLON_SHARP_BASS: InstrumentSet.BASS,
    SHEET_MUSIC_COLON_FLAT_BASS: InstrumentSet.BASS,
    SHEET_MUSIC_COLON_PIANO_NOTE: InstrumentSet.PIANO,
    SHEET_MUSIC_COLON_SHARP_PIANO: InstrumentSet.PIANO,
    SHEET_MUSIC_COLON_FLAT_PIANO: InstrumentSet.PIANO,
    SHEET_MUSIC_COLON_DRUMS: InstrumentSet.DRUM,
    SHEET_MUSIC_COLON_SPOOKY: InstrumentSet.SPOOKY,
    SHEET_MUSIC_COLON_SAX_NOTE: InstrumentSet.SAX,
    SHEET_MUSIC_COLON_SHARP_SAX: InstrumentSet.SAX,
    SHEET_MUSIC_COLON_FLAT_SAX: InstrumentSet.SAX,
    SHEET_MUSIC_COLON_REPEAT_BEGIN: InstrumentSet.REPEAT_BEGIN,
    SHEET_MUSIC_COLON_REPEAT_END: InstrumentSet.REPEAT_END,
    SHEET_MUSIC_COLON_WINTERFEST: InstrumentSet.FESTIVE,
    SHEET_MUSIC_COLON_FLUTE_NOTE: InstrumentSet.FLUTE,
    SHEET_MUSIC_COLON_SHARP_FLUTE: InstrumentSet.FLUTE,
    SHEET_MUSIC_COLON_FLAT_FLUTE: InstrumentSet.FLUTE,
    SHEET_MUSIC_COLON_SPANISH_GUITAR_NOTE: InstrumentSet.SPANISH_GUITAR,
    SHEET_MUSIC_COLON_SHARP_SPANISH_GUITAR: InstrumentSet.SPANISH_GUITAR,
    SHEET_MUSIC_COLON_FLAT_SPANISH_GUITAR: InstrumentSet.SPANISH_GUITAR,
    SHEET_MUSIC_COLON_VIOLIN_NOTE: InstrumentSet.VIOLIN,
    SHEET_MUSIC_COLON_SHARP_VIOLIN: InstrumentSet.VIOLIN,
    SHEET_MUSIC_COLON_FLAT_VIOLIN: InstrumentSet.VIOLIN,
    SHEET_MUSIC_COLON_LYRE_NOTE: InstrumentSet.LYRE,
    SHEET_MUSIC_COLON_SHARP_LYRE: InstrumentSet.LYRE,
    SHEET_MUSIC_COLON_FLAT_LYRE: InstrumentSet.LYRE,
    SHEET_MUSIC_COLON_ELECTRIC_GUITAR: InstrumentSet.ELECTRIC_GUITAR,
    SHEET_MUSIC_COLON_SHARP_ELECTRIC_GUITAR: InstrumentSet.ELECTRIC_GUITAR,
    SHEET_MUSIC_COLON_FLAT_ELECTRIC_GUITAR: InstrumentSet.ELECTRIC_GUITAR,
    SHEET_MUSIC_COLON_MEXICAN_TRUMPET: InstrumentSet.MEXICAN_TRUMPET,
    SHEET_MUSIC_COLON_SHARP_MEXICAN_TRUMPET: InstrumentSet.MEXICAN_TRUMPET,
    SHEET_MUSIC_COLON_FLAT_MEXICAN_TRUMPET: InstrumentSet.MEXICAN_TRUMPET,
}
