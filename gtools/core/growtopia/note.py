from collections import defaultdict
from enum import Enum
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
import threading

from gtools import setting
from gtools.core.midi import GM_INSTRUMENTS
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


def _invert_dict[K, V](d: dict[K, V]) -> dict[V, K]:
    inv = {}
    for k, v in d.items():
        if v in inv:
            raise ValueError(f"duplicate value detected: {v}")
        inv[v] = k
    return inv


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
    accidental: int = NATURAL
    instrument: InstrumentSet = InstrumentSet.PIANO
    timestamp: int = 0
    duration: float = 0.0
    volume: float = 1.0
    userdata: Any = field(default=None, compare=False)

    logger = logging.getLogger("note")

    def transpose_octaves(self, octaves: int) -> "Note":
        return Note(
            base=self.base,
            octave=self.octave + octaves,
            accidental=self.accidental,
            instrument=self.instrument,
            timestamp=self.timestamp,
            duration=self.duration,
            volume=self.volume,
            userdata=self.userdata,
        )

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
        elif self.instrument in (InstrumentSet.SPOOKY, InstrumentSet.FESTIVE):
            index = 12 * self.octave + self.base
        else:
            index = 12 * self.octave + self.base + self.accidental

        return index

    @classmethod
    def from_code(cls, code: bytes, timestamp: int = 0, volume: float = 1.0) -> "Note | None":
        try:
            if len(code) < 3:
                return

            instr, pitch, accidental = list(code.decode())
            base, octave = CODE_TO_PITCH[pitch]

            return Note(
                base=base,
                octave=octave,
                accidental=CODE_TO_ACCIDENT[accidental],
                instrument=CODE_TO_INSTRUMENT_SET[instr],
                timestamp=timestamp,
                volume=volume,
            )
        except:
            return

    def to_code(self) -> bytes:
        return f"{INSTRUMENT_SET_TO_CODE[self.instrument]}{PITCH_TO_CODE[self.base, self.octave]}{ACCIDENT_TO_CODE[self.accidental]}".encode()

    def to_path(self) -> Path:
        return setting.gt_path / "audio/notes" / f"{self.instrument.value}_{self.to_index()}.wav"

    @classmethod
    def from_midi(cls, note: int, instrument: int, is_drum: bool, time: int, velocity: int) -> "Note | None":
        if is_drum:
            instr = InstrumentSet.DRUM
            if note not in MIDI_DRUMS_TO_INSTRUMENT_SET:
                cls.logger.warning(f"drums note {note} have no suitable mapping")
                return

            base = MIDI_DRUMS_TO_INSTRUMENT_SET[note]
            accidental = Note.NATURAL
            octave = 0
        else:
            pitch_class = note % 12
            octave = note // 12 - 1
            if instrument not in MIDI_INSTRUMENT_TO_INSTRUMENT_SET:
                cls.logger.warning(f"midi {GM_INSTRUMENTS[instrument]} have no suitable instrument mapping")
                return

            base, accidental = MIDI_PITCH_TO_NOTE[pitch_class]
            instr = MIDI_INSTRUMENT_TO_INSTRUMENT_SET.get(instrument)
            if not instr:
                cls.logger.warning(f"no suitable instrument mapping for {GM_INSTRUMENTS[instrument]}, defaulting to piano")
                instr = InstrumentSet.PIANO

        return Note(
            base=base,
            octave=octave,
            accidental=accidental,
            instrument=instr,
            timestamp=time,
            volume=velocity / 127 if velocity else 0.0,
        )

    def y_pos(self) -> int:
        """relative to the staff"""
        return (1 - self.octave) * len(PITCH_Y) + PITCH_Y[self.base]

    @staticmethod
    def y_pitch(y: int) -> tuple[int, int]:
        """get base, octave from y pos relative to staff"""
        base_index = y % len(Y_PITCH)
        octave = 1 - y // len(Y_PITCH)
        return Y_PITCH[base_index], octave


PITCH_Y = {
    Note.B: 0,
    Note.A: 1,
    Note.G: 2,
    Note.F: 3,
    Note.E: 4,
    Note.D: 5,
    Note.C: 6,
}
Y_PITCH = _invert_dict(PITCH_Y)


MIDI_PITCH_TO_NOTE = {
    0: (Note.C, Note.NATURAL),
    1: (Note.C, Note.SHARP),
    2: (Note.D, Note.NATURAL),
    3: (Note.D, Note.SHARP),
    4: (Note.E, Note.NATURAL),
    5: (Note.F, Note.NATURAL),
    6: (Note.F, Note.SHARP),
    7: (Note.G, Note.NATURAL),
    8: (Note.G, Note.SHARP),
    9: (Note.A, Note.NATURAL),
    10: (Note.A, Note.SHARP),
    11: (Note.B, Note.NATURAL),
}


MIDI_INSTRUMENT_TO_INSTRUMENT_SET = {
    # piano family
    0: InstrumentSet.PIANO,
    1: InstrumentSet.PIANO,
    2: InstrumentSet.PIANO,
    3: InstrumentSet.PIANO,
    4: InstrumentSet.PIANO,
    5: InstrumentSet.PIANO,
    6: InstrumentSet.PIANO,
    7: InstrumentSet.PIANO,
    6: InstrumentSet.LYRE,  # Harpsichord
    46: InstrumentSet.LYRE,  # Orchestral Harp
    # spanish / acoustic guitar
    24: InstrumentSet.SPANISH_GUITAR,  # Nylon Acoustic Guitar
    # electric guitar family
    25: InstrumentSet.ELECTRIC_GUITAR,  # Steel Acoustic Guitar
    26: InstrumentSet.ELECTRIC_GUITAR,  # Jazz Guitar
    27: InstrumentSet.ELECTRIC_GUITAR,  # Clean Electric Guitar
    28: InstrumentSet.ELECTRIC_GUITAR,  # Muted Guitar
    29: InstrumentSet.ELECTRIC_GUITAR,  # Overdriven Guitar
    30: InstrumentSet.ELECTRIC_GUITAR,  # Distortion Guitar
    31: InstrumentSet.ELECTRIC_GUITAR,  # Guitar Harmonics
    # bass family
    32: InstrumentSet.BASS,
    33: InstrumentSet.BASS,
    34: InstrumentSet.BASS,
    35: InstrumentSet.BASS,
    36: InstrumentSet.BASS,
    37: InstrumentSet.BASS,
    38: InstrumentSet.BASS,
    39: InstrumentSet.BASS,
    # violin / strings
    40: InstrumentSet.VIOLIN,
    41: InstrumentSet.VIOLIN,
    42: InstrumentSet.VIOLIN,
    43: InstrumentSet.VIOLIN,
    44: InstrumentSet.VIOLIN,
    45: InstrumentSet.VIOLIN,
    47: InstrumentSet.VIOLIN,
    # trumpet / brass
    56: InstrumentSet.MEXICAN_TRUMPET,  # Trumpet
    57: InstrumentSet.MEXICAN_TRUMPET,  # Trombone
    58: InstrumentSet.MEXICAN_TRUMPET,  # Tuba
    59: InstrumentSet.MEXICAN_TRUMPET,  # Muted Trumpet
    60: InstrumentSet.MEXICAN_TRUMPET,  # French Horn
    61: InstrumentSet.MEXICAN_TRUMPET,  # Brass Section
    62: InstrumentSet.MEXICAN_TRUMPET,  # Synth Brass 1
    63: InstrumentSet.MEXICAN_TRUMPET,  # Synth Brass 2
    # sax family
    64: InstrumentSet.SAX,  # Soprano Sax
    65: InstrumentSet.SAX,  # Alto Sax
    66: InstrumentSet.SAX,  # Tenor Sax
    67: InstrumentSet.SAX,  # Baritone Sax
    # flute / pipes
    72: InstrumentSet.FLUTE,  # Piccolo
    73: InstrumentSet.FLUTE,
    74: InstrumentSet.FLUTE,
    75: InstrumentSet.FLUTE,
    76: InstrumentSet.FLUTE,
    77: InstrumentSet.FLUTE,
    78: InstrumentSet.FLUTE,
    79: InstrumentSet.FLUTE,
    # TODO: find suitable mapping for this
    # festive / bells / chimes-like material
    8: InstrumentSet.PIANO,
    9: InstrumentSet.PIANO,
    10: InstrumentSet.PIANO,
    11: InstrumentSet.PIANO,
    12: InstrumentSet.PIANO,
    13: InstrumentSet.PIANO,
    14: InstrumentSet.PIANO,
    15: InstrumentSet.PIANO,
    # spooky / eerie / effect-like material
    48: InstrumentSet.PIANO,
    49: InstrumentSet.PIANO,
    50: InstrumentSet.PIANO,
    51: InstrumentSet.PIANO,
    52: InstrumentSet.PIANO,
    53: InstrumentSet.PIANO,
    54: InstrumentSet.PIANO,
    55: InstrumentSet.PIANO,
    69: InstrumentSet.FLUTE,
}

MIDI_DRUMS_TO_INSTRUMENT_SET = {
    # Kick (cluster)
    35: Note.B,  # Acoustic Bass Drum (kind of Kick)
    36: Note.B,  # Bass Drum 1 (Kick)
    # Snare (cluster)
    37: Note.F,  # Side Stick (kind of Snare alt)
    38: Note.F,  # Acoustic Snare
    40: Note.F,  # Electric Snare
    # Clap
    39: Note.A,  # Hand Clap
    # Hi-hat (cluster)
    42: Note.G,  # Closed Hi-hat
    44: Note.G,  # Pedal Hi-hat (kind of Hi-hat)
    46: Note.G,  # Open Hi-hat
    # Low tom (cluster)
    41: Note.E,  # Low Floor Tom (kind of Low tom)
    43: Note.E,  # High Floor Tom (kind of Low tom)
    45: Note.E,  # Low Tom
    # High tom (cluster)
    47: Note.D,  # Low-Mid Tom (kind of High tom)
    48: Note.D,  # Hi-Mid Tom
    50: Note.D,  # High Tom
    # Crash (and cymbal-like -> crash approximation)
    49: Note.C,  # Crash Cymbal 1
    51: Note.C,  # Ride Cymbal 1 (kind of Crash)
    52: Note.C,  # Chinese Cymbal (kind of Crash)
    53: Note.C,  # Ride Bell (kind of Crash)
    55: Note.C,  # Splash Cymbal (kind of Crash)
    57: Note.C,  # Crash Cymbal 2
    # Extra percussion mapped to closest feel
    # Snare-ish / sharp hits
    54: Note.F,  # Tambourine (kind of Snare-like transient)
    56: Note.F,  # Cowbell (kind of Snare-like cut)
    # Hi-hat-ish / high noise
    58: Note.G,  # Vibraslap (kind of noisy, hat-like)
    59: Note.C,  # Ride Cymbal 2 (kind of Crash)
    69: Note.G,  # Cabasa (kind of hi-hat texture)
    70: Note.G,  # Maracas (kind of hi-hat texture)
    # Tom-ish / body hits
    60: Note.E,  # Hi Bongo (kind of small tom -> low tom group)
    61: Note.E,  # Low Bongo
    62: Note.D,  # Mute Hi Conga (kind of higher tom)
    63: Note.E,  # Open Hi Conga
    64: Note.E,  # Low Conga
    65: Note.E,  # High Timbale
    66: Note.E,  # Low Timbale
    73: Note.D,  # Short Guiro (kind of high percussive)
    74: Note.E,  # Long Guiro
    # Kick-ish / low hits
    67: Note.B,  # High Agogo (weak fit -> mapped low-end intent)
    68: Note.B,  # Low Agogo (kind of Kick-ish body)
    # Remaining high percussion -> default to hi-hat or crash feel
    71: Note.G,  # Short Whistle (kind of high freq)
    72: Note.G,  # Long Whistle
    75: Note.G,  # Claves (kind of sharp high)
    76: Note.G,  # Hi Wood Block
    77: Note.E,  # Low Wood Block (kind of low body)
    78: Note.G,  # Mute Cuica
    79: Note.G,  # Open Cuica
    80: Note.G,  # Mute Triangle
    81: Note.C,  # Open Triangle (kind of cymbal-like -> crash)
}

_SOUNDS: dict[Path, Sound] = {}


class Sheet:
    logger = logging.getLogger("sheet")

    def __init__(self, bpm: int, notes: list[Note], mixer: AudioMixer | None) -> None:
        self._notes = notes
        self.notes: defaultdict[int, list[Note]] = defaultdict(list)
        self.any = bool(notes)
        for note in notes:
            self.notes[note.timestamp].append(note)

        if notes:
            self.start = min(notes, key=lambda x: x.timestamp).timestamp
            self.end = max(notes, key=lambda x: x.timestamp).timestamp
        else:
            self.start = 0
            self.end = 0

        self._bpm = bpm
        self.bps = (bpm * 4) / 60

        self.mixer = mixer
        self.on_note_played: Callable[[Note], None] | None = None

        self.playhead = self.start
        self._accum = 0.0

        self._activated_repeats: set[tuple[int, int]] = set()
        self._pending_backtrack: int | None = None

        self._can_go = threading.Event()
        if mixer:
            self._preload_thread = threading.Thread(target=self._preload, daemon=True)
            self._preload_thread.start()
        else:
            self._can_go.set()

    @property
    def total_notes(self) -> int:
        return sum(len(n) for n in self.notes.values())

    @property
    def bpm(self) -> int:
        return self._bpm

    @bpm.setter
    def bpm(self, x: float) -> None:
        self._bpm = int(x)
        self.bps = (x * 4) / 60

    def replace_notes(self, notes: list[Note], playhead_bound_check: bool = False) -> None:
        self._notes = notes
        self.notes.clear()
        self.any = bool(notes)
        for note in notes:
            self.notes[note.timestamp].append(note)

        if notes:
            self.start = min(notes, key=lambda x: x.timestamp).timestamp
            self.end = max(notes, key=lambda x: x.timestamp).timestamp
        else:
            self.start = 0
            self.end = 0

        if playhead_bound_check:
            self.playhead = min(self.playhead, self.end)

    def add_notes(self, notes: list[Note]) -> None:
        for note in notes:
            self.notes[note.timestamp].append(note)

        self._notes = notes

        self.any = bool(self.notes)

        if notes:
            self.start = min(notes, key=lambda x: x.timestamp).timestamp
            self.end = max(notes, key=lambda x: x.timestamp).timestamp
        else:
            self.start = 0
            self.end = 0

        self.playhead = min(self.playhead, self.end)

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

    def _find_repeat_begin(self, end_note: Note) -> int:
        row = end_note.to_index()
        for col in range(end_note.timestamp - 1, self.start - 1, -1):
            for note in self.notes[col]:
                if note.instrument == InstrumentSet.REPEAT_BEGIN and note.to_index() == row:
                    return col
        return self.start

    def advance_playhead(self, n: int = 1) -> None:
        if not self.any:
            return

        self._can_go.wait()

        if self.playhead > self.end:
            self.playhead = self.start
            self._activated_repeats.clear()
            self._pending_backtrack = None

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

            if self.mixer:
                path = note.to_path()
                if path not in _SOUNDS:
                    _SOUNDS[path] = Sound.from_file(str(path))
                self.mixer.play(_SOUNDS[path], note.volume)

            if self.on_note_played:
                self.on_note_played(note)

        self.playhead += n

    def seek(self, direction: int, play: bool = False) -> None:
        if not self.any:
            return

        if play:
            self.advance_playhead(direction)
        else:
            self.playhead += direction

        if direction < 0:
            self._activated_repeats.clear()
            self._pending_backtrack = None

    def update(self, dt: float) -> bool:
        if not self.any:
            return False

        self._can_go.wait()
        tick_duration = 1.0 / self.bps if self.bps != 0 else 0
        self._accum += dt

        any_change = False
        while self._accum >= tick_duration:
            self.advance_playhead()
            self._accum -= tick_duration
            any_change = True

        return any_change


def compress_notes(note_list: list[Note], low_octave: int = 0, high_octave: int = 1, search_octaves: int = 6, window_size: int = 8) -> list[Note]:
    low = 12 * low_octave + 1
    high = 12 * high_octave + 12

    def is_pitched(n: Note) -> bool:
        return n.instrument not in {
            InstrumentSet.DRUM,
            InstrumentSet.REPEAT_BEGIN,
            InstrumentSet.REPEAT_END,
            InstrumentSet.FESTIVE,
            InstrumentSet.SPOOKY,
            InstrumentSet.BLANK,
        }

    notes: defaultdict[int, list[Note]] = defaultdict(list)
    for note in note_list:
        notes[note.timestamp].append(note)

    timestamps = sorted(notes)
    k_per_ts: dict[int, int] = {}

    for i, ts in enumerate(timestamps):
        window_start = max(0, i - window_size // 2)
        window_end = min(len(timestamps), i + window_size // 2 + 1)

        window_notes = [n for j in range(window_start, window_end) for n in notes[timestamps[j]] if is_pitched(n)]

        if not window_notes:
            k_per_ts[ts] = 0
            continue

        best_k = 0
        best_score = None

        for k in range(-search_octaves, search_octaves + 1):
            moved = [n.to_index() + 12 * k for n in window_notes]
            outside = sum(v < low or v > high for v in moved)
            in_range = [v for v in moved if low <= v <= high]
            span = (max(in_range) - min(in_range)) if in_range else 0

            score = (outside, -span)

            if best_score is None or score < best_score:
                best_score = score
                best_k = k

        k_per_ts[ts] = best_k

    out: list[Note] = []
    for ts in timestamps:
        for n in notes[ts]:
            if is_pitched(n):
                transposed = n.transpose_octaves(k_per_ts[ts])
                index = transposed.to_index()
                if index < low:
                    clamp_octaves = (low - index + 11) // 12
                    transposed = transposed.transpose_octaves(clamp_octaves)
                elif index > high:
                    clamp_octaves = (index - high + 11) // 12
                    transposed = transposed.transpose_octaves(-clamp_octaves)
                out.append(transposed)
            else:
                out.append(n)

    return out


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
INSTRUMENT_SET_TO_CODE = _invert_dict(CODE_TO_INSTRUMENT_SET)
CODE_TO_ACCIDENT = {
    "#": Note.SHARP,
    "-": Note.NATURAL,
    "b": Note.FLAT,
}
ACCIDENT_TO_CODE = _invert_dict(CODE_TO_ACCIDENT)
CODE_TO_PITCH = {
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
PITCH_TO_CODE = _invert_dict(CODE_TO_PITCH)

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
INSTRUMENT_SET_TO_ID = {instr: id for id, instr in ID_TO_INSTRUMENT_SET.items() if id not in SHEET_SHARP_ID and id not in SHEET_FLAT_ID}

INSTRUMENT_ACCIDENT_TO_ID = {
    (InstrumentSet.BLANK, Note.SHARP): SHEET_MUSIC_COLON_BLANK,
    (InstrumentSet.BASS, Note.SHARP): SHEET_MUSIC_COLON_SHARP_BASS,
    (InstrumentSet.PIANO, Note.SHARP): SHEET_MUSIC_COLON_SHARP_PIANO,
    (InstrumentSet.DRUM, Note.SHARP): SHEET_MUSIC_COLON_DRUMS,
    (InstrumentSet.SPOOKY, Note.SHARP): SHEET_MUSIC_COLON_SPOOKY,
    (InstrumentSet.SAX, Note.SHARP): SHEET_MUSIC_COLON_SHARP_SAX,
    (InstrumentSet.REPEAT_BEGIN, Note.SHARP): SHEET_MUSIC_COLON_REPEAT_BEGIN,
    (InstrumentSet.REPEAT_END, Note.SHARP): SHEET_MUSIC_COLON_REPEAT_END,
    (InstrumentSet.FESTIVE, Note.SHARP): SHEET_MUSIC_COLON_WINTERFEST,
    (InstrumentSet.FLUTE, Note.SHARP): SHEET_MUSIC_COLON_SHARP_FLUTE,
    (InstrumentSet.SPANISH_GUITAR, Note.SHARP): SHEET_MUSIC_COLON_SHARP_SPANISH_GUITAR,
    (InstrumentSet.VIOLIN, Note.SHARP): SHEET_MUSIC_COLON_SHARP_VIOLIN,
    (InstrumentSet.LYRE, Note.SHARP): SHEET_MUSIC_COLON_SHARP_LYRE,
    (InstrumentSet.ELECTRIC_GUITAR, Note.SHARP): SHEET_MUSIC_COLON_SHARP_ELECTRIC_GUITAR,
    (InstrumentSet.MEXICAN_TRUMPET, Note.SHARP): SHEET_MUSIC_COLON_SHARP_MEXICAN_TRUMPET,
    (InstrumentSet.BLANK, Note.FLAT): SHEET_MUSIC_COLON_BLANK,
    (InstrumentSet.BASS, Note.FLAT): SHEET_MUSIC_COLON_FLAT_BASS,
    (InstrumentSet.PIANO, Note.FLAT): SHEET_MUSIC_COLON_FLAT_PIANO,
    (InstrumentSet.DRUM, Note.FLAT): SHEET_MUSIC_COLON_DRUMS,
    (InstrumentSet.SPOOKY, Note.FLAT): SHEET_MUSIC_COLON_SPOOKY,
    (InstrumentSet.SAX, Note.FLAT): SHEET_MUSIC_COLON_FLAT_SAX,
    (InstrumentSet.REPEAT_BEGIN, Note.FLAT): SHEET_MUSIC_COLON_REPEAT_BEGIN,
    (InstrumentSet.REPEAT_END, Note.FLAT): SHEET_MUSIC_COLON_REPEAT_END,
    (InstrumentSet.FESTIVE, Note.FLAT): SHEET_MUSIC_COLON_WINTERFEST,
    (InstrumentSet.FLUTE, Note.FLAT): SHEET_MUSIC_COLON_FLAT_FLUTE,
    (InstrumentSet.SPANISH_GUITAR, Note.FLAT): SHEET_MUSIC_COLON_FLAT_SPANISH_GUITAR,
    (InstrumentSet.VIOLIN, Note.FLAT): SHEET_MUSIC_COLON_FLAT_VIOLIN,
    (InstrumentSet.LYRE, Note.FLAT): SHEET_MUSIC_COLON_FLAT_LYRE,
    (InstrumentSet.ELECTRIC_GUITAR, Note.FLAT): SHEET_MUSIC_COLON_FLAT_ELECTRIC_GUITAR,
    (InstrumentSet.MEXICAN_TRUMPET, Note.FLAT): SHEET_MUSIC_COLON_FLAT_MEXICAN_TRUMPET,
    (InstrumentSet.BLANK, Note.NATURAL): SHEET_MUSIC_COLON_BLANK,
    (InstrumentSet.BASS, Note.NATURAL): SHEET_MUSIC_COLON_BASS_NOTE,
    (InstrumentSet.PIANO, Note.NATURAL): SHEET_MUSIC_COLON_PIANO_NOTE,
    (InstrumentSet.DRUM, Note.NATURAL): SHEET_MUSIC_COLON_DRUMS,
    (InstrumentSet.SPOOKY, Note.NATURAL): SHEET_MUSIC_COLON_SPOOKY,
    (InstrumentSet.SAX, Note.NATURAL): SHEET_MUSIC_COLON_SAX_NOTE,
    (InstrumentSet.REPEAT_BEGIN, Note.NATURAL): SHEET_MUSIC_COLON_REPEAT_BEGIN,
    (InstrumentSet.REPEAT_END, Note.NATURAL): SHEET_MUSIC_COLON_REPEAT_END,
    (InstrumentSet.FESTIVE, Note.NATURAL): SHEET_MUSIC_COLON_WINTERFEST,
    (InstrumentSet.FLUTE, Note.NATURAL): SHEET_MUSIC_COLON_FLUTE_NOTE,
    (InstrumentSet.SPANISH_GUITAR, Note.NATURAL): SHEET_MUSIC_COLON_SPANISH_GUITAR_NOTE,
    (InstrumentSet.VIOLIN, Note.NATURAL): SHEET_MUSIC_COLON_VIOLIN_NOTE,
    (InstrumentSet.LYRE, Note.NATURAL): SHEET_MUSIC_COLON_LYRE_NOTE,
    (InstrumentSet.ELECTRIC_GUITAR, Note.NATURAL): SHEET_MUSIC_COLON_ELECTRIC_GUITAR,
    (InstrumentSet.MEXICAN_TRUMPET, Note.NATURAL): SHEET_MUSIC_COLON_MEXICAN_TRUMPET,
}
