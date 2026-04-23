import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator

import mido

# fmt: off
GM_INSTRUMENTS = [
    "Acoustic Grand Piano", "Bright Acoustic Piano", "Electric Grand Piano",
    "Honky-tonk Piano", "Electric Piano 1", "Electric Piano 2", "Harpsichord",
    "Clavi", "Celesta", "Glockenspiel", "Music Box", "Vibraphone", "Marimba",
    "Xylophone", "Tubular Bells", "Dulcimer", "Drawbar Organ", "Percussive Organ",
    "Rock Organ", "Church Organ", "Reed Organ", "Accordion", "Harmonica",
    "Tango Accordion", "Acoustic Guitar (nylon)", "Acoustic Guitar (steel)",
    "Electric Guitar (jazz)", "Electric Guitar (clean)", "Electric Guitar (muted)",
    "Overdriven Guitar", "Distortion Guitar", "Guitar Harmonics",
    "Acoustic Bass", "Electric Bass (finger)", "Electric Bass (pick)",
    "Fretless Bass", "Slap Bass 1", "Slap Bass 2", "Synth Bass 1", "Synth Bass 2",
    "Violin", "Viola", "Cello", "Contrabass", "Tremolo Strings",
    "Pizzicato Strings", "Orchestral Harp", "Timpani",
    "String Ensemble 1", "String Ensemble 2", "Synth Strings 1", "Synth Strings 2",
    "Choir Aahs", "Voice Oohs", "Synth Voice", "Orchestra Hit",
    "Trumpet", "Trombone", "Tuba", "Muted Trumpet", "French Horn",
    "Brass Section", "Synth Brass 1", "Synth Brass 2",
    "Soprano Sax", "Alto Sax", "Tenor Sax", "Baritone Sax",
    "Oboe", "English Horn", "Bassoon", "Clarinet",
    "Piccolo", "Flute", "Recorder", "Pan Flute", "Blown Bottle",
    "Shakuhachi", "Whistle", "Ocarina",
    "Lead 1 (square)", "Lead 2 (sawtooth)", "Lead 3 (calliope)", "Lead 4 (chiff)",
    "Lead 5 (charang)", "Lead 6 (voice)", "Lead 7 (fifths)", "Lead 8 (bass+lead)",
    "Pad 1 (new age)", "Pad 2 (warm)", "Pad 3 (polysynth)", "Pad 4 (choir)",
    "Pad 5 (bowed)", "Pad 6 (metallic)", "Pad 7 (halo)", "Pad 8 (sweep)",
    "FX 1 (rain)", "FX 2 (soundtrack)", "FX 3 (crystal)", "FX 4 (atmosphere)",
    "FX 5 (brightness)", "FX 6 (goblins)", "FX 7 (echoes)", "FX 8 (sci-fi)",
    "Sitar", "Banjo", "Shamisen", "Koto", "Kalimba", "Bag Pipe", "Fiddle",
    "Shanai", "Tinkle Bell", "Agogo", "Steel Drums", "Woodblock",
    "Taiko Drum", "Melodic Tom", "Synth Drum", "Reverse Cymbal",
    "Guitar Fret Noise", "Breath Noise", "Seashore", "Bird Tweet",
    "Telephone Ring", "Helicopter", "Applause", "Gunshot",
]
# fmt: on

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

_DEFAULT_TEMPO = 500_000  # microseconds per beat (120 BPM)


@dataclass(slots=True)
class _TempoEvent:
    tick: int
    tempo: int


class _TempoMap:
    def __init__(self, events: list[_TempoEvent], ticks_per_beat: int) -> None:
        self._events = events or [_TempoEvent(0, _DEFAULT_TEMPO)]
        self._tpb = ticks_per_beat

    @property
    def primary_bpm(self) -> float:
        return 60_000_000 / self._events[0].tempo

    def tick_to_sec(self, tick: int) -> float:
        elapsed = 0.0
        prev_tick = 0
        prev_tempo = _DEFAULT_TEMPO

        for ev in self._events:
            if ev.tick >= tick:
                break
            elapsed += mido.tick2second(ev.tick - prev_tick, self._tpb, prev_tempo)
            prev_tick = ev.tick
            prev_tempo = ev.tempo

        elapsed += mido.tick2second(tick - prev_tick, self._tpb, prev_tempo)

        return elapsed

    def sec_to_tick(self, seconds: float) -> int:
        elapsed = 0.0
        prev_tick = 0
        prev_tempo = _DEFAULT_TEMPO

        for ev in self._events:
            seg_ticks = ev.tick - prev_tick
            seg_sec = mido.tick2second(seg_ticks, self._tpb, prev_tempo)
            if elapsed + seg_sec >= seconds:
                remaining = seconds - elapsed
                return prev_tick + int(mido.second2tick(remaining, self._tpb, prev_tempo))
            elapsed += seg_sec
            prev_tick = ev.tick
            prev_tempo = ev.tempo

        remaining = seconds - elapsed

        return prev_tick + int(mido.second2tick(remaining, self._tpb, prev_tempo))

    def tick_to_beat(self, tick: int) -> float:
        return tick / self._tpb

    @classmethod
    def from_midi_tracks(cls, raw_tracks: list[mido.MidiTrack], ticks_per_beat: int) -> "_TempoMap":
        events: list[tuple[int, int]] = []
        for track in raw_tracks:
            abs_tick = 0
            for msg in track:
                abs_tick += msg.time
                if msg.type == "set_tempo":
                    events.append((abs_tick, msg.tempo))

        events.sort(key=lambda e: e[0])
        if not events or events[0][0] != 0:
            events.insert(0, (0, _DEFAULT_TEMPO))

        seen: set[int] = set()
        deduped = [_TempoEvent(tick, tempo) for tick, tempo in events if not (tick in seen or seen.add(tick))]
        return cls(deduped, ticks_per_beat)


@dataclass(slots=True)
class Note:
    pitch: int
    name: str
    channel: int
    velocity: int
    off_velocity: int
    program: int
    instrument_name: str
    is_drum: bool

    track_index: int
    track_name: str

    start_sec: float
    end_sec: float
    duration_sec: float

    start_beat: float
    end_beat: float
    duration_beats: float


@dataclass(slots=True)
class QuantizedNote:
    pitch: int
    name: str
    channel: int
    velocity: int
    off_velocity: int
    program: int
    instrument_name: str
    is_drum: bool
    track_index: int
    track_name: str

    start_sec: float
    end_sec: float
    duration_sec: float

    start_beat: float
    end_beat: float
    duration_beats: float

    bps: float
    start_slot: int
    end_slot: int
    duration_slots: int

    start_error_sec: float
    end_error_sec: float

    source: Note

    @classmethod
    def from_note(cls, note: Note, bps: float, *, min_duration_slots: int = 1) -> "QuantizedNote":
        start_slot = round(note.start_sec * bps)
        end_slot = round(note.end_sec * bps)
        if end_slot - start_slot < min_duration_slots:
            end_slot = start_slot + min_duration_slots

        start_snapped = start_slot / bps
        end_snapped = end_slot / bps

        return cls(
            pitch=note.pitch,
            name=note.name,
            channel=note.channel,
            velocity=note.velocity,
            off_velocity=note.off_velocity,
            program=note.program,
            instrument_name=note.instrument_name,
            is_drum=note.is_drum,
            track_index=note.track_index,
            track_name=note.track_name,
            start_sec=start_snapped,
            end_sec=end_snapped,
            duration_sec=end_snapped - start_snapped,
            start_beat=note.start_beat,
            end_beat=note.end_beat,
            duration_beats=note.duration_beats,
            bps=bps,
            start_slot=start_slot,
            end_slot=end_slot,
            duration_slots=end_slot - start_slot,
            start_error_sec=abs(note.start_sec - start_snapped),
            end_error_sec=abs(note.end_sec - end_snapped),
            source=note,
        )


type _AnyNote = Note | QuantizedNote


@dataclass
class Instrument[N: _AnyNote]:
    channel: int
    program: int
    is_drum: bool
    name: str
    notes: list[N]

    def __iter__(self) -> Iterator[N]:
        yield from self.notes

    def __len__(self) -> int:
        return len(self.notes)

    def __repr__(self) -> str:
        return f"Instrument({self.name!r}, channel={self.channel}, notes={len(self.notes)})"


@dataclass
class Track[N: _AnyNote]:
    index: int
    name: str
    notes: list[N]
    instruments: list[Instrument[N]]

    def __iter__(self) -> Iterator[N]:
        yield from self.notes

    def __len__(self) -> int:
        return len(self.notes)

    def __repr__(self) -> str:
        return f"Track({self.name!r}, index={self.index}, notes={len(self.notes)})"

    def by_channel(self) -> dict[int, list[N]]:
        groups: dict[int, list[N]] = defaultdict(list)
        for n in self.notes:
            groups[n.channel].append(n)
        return dict(groups)

    def by_instrument(self) -> dict[str, list[N]]:
        groups: dict[str, list[N]] = defaultdict(list)
        for n in self.notes:
            groups[n.instrument_name].append(n)
        return dict(groups)


class MidiFile:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._mid = mido.MidiFile(str(self._path))

        self.ticks_per_beat: int = self._mid.ticks_per_beat
        self.type: int = self._mid.type

        self._tempo_map = _TempoMap.from_midi_tracks(self._mid.tracks, self.ticks_per_beat)
        self._tracks: list[Track[Note]] = [self._parse_track(i, t) for i, t in enumerate(self._mid.tracks)]
        self._notes: list[Note] = sorted(
            (n for t in self._tracks for n in t.notes),
            key=lambda n: n.start_sec,
        )
        self._instruments: list[Instrument[Note]] = _build_instruments(self._notes)

    def __iter__(self) -> Iterator[Note]:
        yield from self._notes

    @property
    def tracks(self) -> list[Track[Note]]:
        return self._tracks

    @property
    def instruments(self) -> list[Instrument[Note]]:
        return self._instruments

    def by_instrument(self) -> dict[str, list[Note]]:
        return _group_by(self._notes, lambda n: n.instrument_name)

    def by_channel(self) -> dict[int, list[Note]]:
        return _group_by(self._notes, lambda n: n.channel)

    def by_track(self) -> dict[str, list[Note]]:
        return _group_by(self._notes, lambda n: n.track_name or f"Track {n.track_index}")

    @property
    def duration_sec(self) -> float:
        return max((n.end_sec for n in self._notes), default=0.0)

    def __repr__(self) -> str:
        return f"MidiFile(path={self._path.name!r}, type={self.type}, " f"tracks={len(self._tracks)}, duration={self.duration_sec:.2f}s)"

    def quantize(self, bps: float, *, min_duration_slots: int = 1) -> "QuantizedMidiFile":
        q_tracks: list[Track[QuantizedNote]] = []

        for track in self._tracks:
            q_notes = sorted(
                (QuantizedNote.from_note(n, bps, min_duration_slots=min_duration_slots) for n in track.notes),
                key=lambda qn: qn.start_slot,
            )
            q_instruments = _build_instruments(q_notes)
            q_tracks.append(Track(index=track.index, name=track.name, notes=q_notes, instruments=q_instruments))

        return QuantizedMidiFile(bps=bps, tracks=q_tracks)

    def get_best_bps(self, *, search_radius: int = 4, max_bps: int = 128, weight_fn: Callable[[Note], float] | None = None) -> float:
        if not self._notes:
            raise ValueError("no notes found")

        gcd_raw = _tick_gcd_bps(self._notes, self.ticks_per_beat, self._tempo_map)

        lo = max(1, round(gcd_raw) - search_radius)
        hi = round(gcd_raw) + search_radius
        local_best = _optimal_bps(self._notes, range(lo, hi + 1), weight_fn=weight_fn)

        all_err = _error_curve(self._notes, range(1, max_bps + 1), weight_fn=weight_fn)
        global_best = min(all_err, key=lambda x: x[1])[0]

        if local_best <= max_bps and _total_error(self._notes, local_best, weight_fn) <= _total_error(self._notes, global_best, weight_fn) * 1.05:
            return local_best

        return global_best

    def error_curve(self, candidates: Iterable[float] | None = None, *, max_bps: int = 128, weight_fn: Callable[[Note], float] | None = None) -> list[tuple[float, float]]:
        if candidates is None:
            candidates = range(1, max_bps + 1)

        return _error_curve(self._notes, candidates, weight_fn=weight_fn)

    def _parse_track(self, index: int, raw_track: mido.MidiTrack) -> Track[Note]:
        track_name = ""
        program_map: dict[int, int] = {}
        pending: dict[tuple[int, int], list[tuple[int, int, int]]] = defaultdict(list)
        notes: list[Note] = []

        abs_tick = 0
        for msg in raw_track:
            abs_tick += msg.time

            if msg.type == "track_name":
                track_name = msg.name

            elif msg.type == "program_change":
                program_map[msg.channel] = msg.program

            elif msg.type == "note_on" and msg.velocity > 0:
                key = (msg.channel, msg.note)
                pending[key].append((abs_tick, msg.velocity, program_map.get(msg.channel, 0)))

            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                key = (msg.channel, msg.note)
                if pending.get(key):
                    on_tick, on_vel, program = pending[key].pop(0)
                    off_tick = abs_tick
                    is_drum = msg.channel == 9

                    start_sec = self._tempo_map.tick_to_sec(on_tick)
                    end_sec = self._tempo_map.tick_to_sec(off_tick)
                    start_beat = self._tempo_map.tick_to_beat(on_tick)
                    end_beat = self._tempo_map.tick_to_beat(off_tick)

                    notes.append(
                        Note(
                            pitch=msg.note,
                            name=_note_name(msg.note),
                            channel=msg.channel,
                            velocity=on_vel,
                            off_velocity=getattr(msg, "velocity", 0),
                            program=program,
                            instrument_name=_instrument_name(program, is_drum),
                            is_drum=is_drum,
                            track_index=index,
                            track_name=track_name,
                            start_sec=start_sec,
                            end_sec=end_sec,
                            duration_sec=end_sec - start_sec,
                            start_beat=start_beat,
                            end_beat=end_beat,
                            duration_beats=end_beat - start_beat,
                        )
                    )

        notes.sort(key=lambda n: (n.start_sec, n.channel, n.pitch))
        instruments = _build_instruments(notes)

        return Track(index=index, name=track_name, notes=notes, instruments=instruments)


class QuantizedMidiFile:
    def __init__(self, bps: float, tracks: list[Track[QuantizedNote]]) -> None:
        self.bps = bps
        self._tracks = tracks
        self._notes: list[QuantizedNote] = sorted(
            (n for t in tracks for n in t.notes),
            key=lambda n: (n.start_slot, n.channel, n.pitch),
        )
        self._instruments: list[Instrument[QuantizedNote]] = _build_instruments(self._notes)

    def __iter__(self) -> Iterator[QuantizedNote]:
        yield from self._notes

    @property
    def tracks(self) -> list[Track[QuantizedNote]]:
        return self._tracks

    @property
    def instruments(self) -> list[Instrument[QuantizedNote]]:
        return self._instruments

    def by_instrument(self) -> dict[str, list[QuantizedNote]]:
        return _group_by(self._notes, lambda n: n.instrument_name)

    def by_channel(self) -> dict[int, list[QuantizedNote]]:
        return _group_by(self._notes, lambda n: n.channel)

    def by_track(self) -> dict[str, list[QuantizedNote]]:
        return _group_by(self._notes, lambda n: n.track_name or f"Track {n.track_index}")

    @property
    def slot_duration_sec(self) -> float:
        return 1.0 / self.bps

    @property
    def duration_slots(self) -> int:
        return max((n.end_slot for n in self._notes), default=0)

    @property
    def duration_sec(self) -> float:
        return self.duration_slots / self.bps

    def total_error_sec(self) -> float:
        """Sum of all start + end snapping errors across every note."""
        return sum(n.start_error_sec + n.end_error_sec for n in self._notes)

    def __repr__(self) -> str:
        return f"QuantizedMidiFile(bps={self.bps}, " f"duration={self.duration_slots} slots / {self.duration_sec:.2f}s, " f"total_error={self.total_error_sec():.4f}s)"


def _note_name(midi_pitch: int) -> str:
    return f"{NOTE_NAMES[midi_pitch % 12]}{midi_pitch // 12 - 1}"


def _instrument_name(program: int, is_drum: bool) -> str:
    if is_drum:
        return "Drums (Channel 10)"
    if 0 <= program <= 127:
        return GM_INSTRUMENTS[program]

    return "Unknown"


def _build_instruments[N: _AnyNote](notes: list[N]) -> list[Instrument[N]]:
    groups: dict[tuple[int, int, bool], list[N]] = defaultdict(list)
    for n in notes:
        groups[(n.channel, n.program, n.is_drum)].append(n)

    return [Instrument(channel=ch, program=prog, is_drum=drum, name=_instrument_name(prog, drum), notes=ns) for (ch, prog, drum), ns in sorted(groups.items())]


def _group_by[N, K](notes: list[N], key_fn: Callable[[N], K]) -> dict[K, list[N]]:
    groups: dict[K, list[N]] = defaultdict(list)
    for n in notes:
        groups[key_fn(n)].append(n)

    return dict(groups)


def _note_error(note: Note | QuantizedNote, bps: float) -> float:
    start_err = abs(note.start_sec - round(note.start_sec * bps) / bps)
    end_err = abs(note.end_sec - round(note.end_sec * bps) / bps)

    return start_err + end_err


def _total_error(
    notes: list[Note],
    bps: float,
    weight_fn: Callable[[Note], float] | None = None,
) -> float:
    if not notes:
        return 0.0

    return sum((weight_fn(n) if weight_fn else 1.0) * _note_error(n, bps) for n in notes)


def _error_curve(
    notes: list[Note],
    candidates: Iterable[float],
    weight_fn: Callable[[Note], float] | None = None,
) -> list[tuple[float, float]]:
    return [(bps, _total_error(notes, bps, weight_fn)) for bps in candidates]


def _optimal_bps(
    notes: list[Note],
    candidates: Iterable[float],
    weight_fn: Callable[[Note], float] | None = None,
) -> float:
    best_bps, best_err = 1.0, float("inf")
    for bps in candidates:
        err = _total_error(notes, bps, weight_fn)
        if err < best_err:
            best_err = err
            best_bps = bps

    return float(best_bps)


def _tick_gcd_bps(notes: list[Note], ticks_per_beat: int, tempo_map: _TempoMap) -> float:
    ticks: list[int] = []
    for n in notes:
        start_tick = tempo_map.sec_to_tick(n.start_sec)
        end_tick = tempo_map.sec_to_tick(n.end_sec)
        dur_tick = end_tick - start_tick
        if start_tick > 0:
            ticks.append(start_tick)
        if end_tick > 0:
            ticks.append(end_tick)
        if dur_tick > 0:
            ticks.append(dur_tick)

    if not ticks:
        return 1.0

    gcd_ticks = ticks[0]
    for t in ticks[1:]:
        gcd_ticks = math.gcd(gcd_ticks, t)
        if gcd_ticks == 1:
            break

    subdivisions_per_beat = ticks_per_beat / gcd_ticks

    return subdivisions_per_beat * (tempo_map.primary_bpm / 60.0)
