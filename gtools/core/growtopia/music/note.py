from collections import defaultdict
from enum import Enum
import logging
from dataclasses import dataclass
from pathlib import Path
import threading
import time

from gtools import setting
from gtools.core.mixer import AudioMixer, Sound


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

        self._preload_thread = threading.Thread(target=self._preload, daemon=True)
        self._preload_thread.start()
        self._can_go = threading.Event()

    def _preload(self) -> None:
        for col in range(self.start, self.end):
            if col == 10:
                self._can_go.set()

            for note in self.notes[col]:
                if note.instrument in (InstrumentSet.REPEAT_BEGIN, InstrumentSet.REPEAT_END, InstrumentSet.BLANK):
                    continue

                path = note.to_path()
                if path not in _SOUNDS:
                    _SOUNDS[path] = Sound.from_file(str(path))

        self._can_go.set()

    def advance_playhead(self) -> None:
        self._can_go.wait()
        for note in self.notes[self.playhead]:
            if note.instrument in (InstrumentSet.REPEAT_BEGIN, InstrumentSet.REPEAT_END, InstrumentSet.BLANK):
                continue

            path = note.to_path()
            if path not in _SOUNDS:
                _SOUNDS[path] = Sound.from_file(str(path))

            self.mixer.play(_SOUNDS[path])

        self.playhead += 1

        if self.playhead > self.end:
            self.playhead = self.start

    def update(self, dt: float) -> None:
        self._can_go.wait()
        tick_duration = 1.0 / self.bps

        self._accum += min(dt, tick_duration)
        while self._accum >= tick_duration:
            self.advance_playhead()
            self._accum -= tick_duration
