import logging
from pathlib import Path
import mido
import numpy as np
import colorsys
from OpenGL.GL import GL_DEPTH_TEST, glDisable, glEnable

from gtools.gui.camera import Camera2D
from gtools.gui.lib.renderer import Renderer
from gtools.gui.opengl import Mesh, ShaderProgram

logger = logging.getLogger("gui-midi-renderer")

# fmt: off
INSTRUMENTS = [ "Acoustic Grand", "Bright Acoustic", "Electric Grand", "Honky-Tonk", "Electric Piano 1", "Electric Piano 2", "Harpsichord", "Clavinet", "Celesta", "Glockenspiel", "Music Box", "Vibraphone", "Marimba", "Xylophone", "Tubular Bells", "Dulcimer", "Drawbar Organ", "Percussive Organ", "Rock Organ", "Church Organ", "Reed Organ", "Accoridan", "Harmonica", "Tango Accordian", "Nylon String Guitar", "Steel String Guitar", "Electric Jazz Guitar", "Electric Clean Guitar", "Electric Muted Guitar", "Overdriven Guitar", "Distortion Guitar", "Guitar Harmonics", "Acoustic Bass", "Electric Bass(finger)", "Electric Bass(pick)", "Fretless Bass", "Slap Bass 1", "Slap Bass 2", "Synth Bass 1", "Synth Bass 2", "Violin", "Viola", "Cello", "Contrabass", "Tremolo Strings", "Pizzicato Strings", "Orchestral Strings", "Timpani", "String Ensemble 1", "String Ensemble 2", "SynthStrings 1", "SynthStrings 2", "Choir Aahs", "Voice Oohs", "Synth Voice", "Orchestra Hit", "Trumpet", "Trombone", "Tuba", "Muted Trumpet", "French Horn", "Brass Section", "SynthBrass 1", "SynthBrass 2", "Soprano Sax", "Alto Sax", "Tenor Sax", "Baritone Sax", "Oboe", "English Horn", "Bassoon", "Clarinet", "Piccolo", "Flute", "Recorder", "Pan Flute", "Blown Bottle", "Skakuhachi", "Whistle", "Ocarina", "Square Wave", "Saw Wave", "Syn. Calliope", "Chiffer Lead", "Charang", "Solo Vox", "5th Saw Wave", "Bass& Lead", "Fantasia", "Warm Pad", "Polysynth", "Space Voice", "Bowed Glass", "Metal Pad", "Halo Pad", "Sweep Pad", "Ice Rain", "Soundtrack", "Crystal", "Atmosphere", "Brightness", "Goblin", "Echo Drops", "Star Theme", "Sitar", "Banjo", "Shamisen", "Koto", "Kalimba", "Bagpipe", "Fiddle", "Shanai", "Tinkle Bell", "Agogo", "Steel Drums", "Woodblock", "Taiko Drum", "Melodic Tom", "Synth Drum", "Reverse Cymbal", "Guitar Fret Noise", "Breath Noise", "Seashore", "Bird Tweet", "Telephone Ring", "Helicopter", "Applause", "Gunshot"]
# fmt: on


class MidiTrackRenderer(Renderer):
    LAYOUT = [2, 2]
    INSTANCE_LAYOUT = [2, 2, 4]

    def __init__(self) -> None:
        self._shader = ShaderProgram.get("shaders/midi_note")
        self._u_proj = self._shader.get_uniform("u_proj")

        self._grid_shader = ShaderProgram.get("shaders/midi_grid")
        self._u_grid_proj = self._grid_shader.get_uniform("u_proj")
        self._u_grid_min = self._grid_shader.get_uniform("u_min")
        self._u_grid_max = self._grid_shader.get_uniform("u_max")
        self._u_grid_ppq = self._grid_shader.get_uniform("u_ticksPerBeat")
        self._u_grid_bpb = self._grid_shader.get_uniform("u_beatsPerBar")
        self._u_grid_zoom = self._grid_shader.get_uniform("u_zoom")

        self._mesh: Mesh | None = None
        # fmt: off
        self._grid_mesh: Mesh = Mesh(
            np.array([
                0.0, 0.0, 0.0, 0.0,
                1.0, 0.0, 1.0, 0.0,
                1.0, 1.0, 1.0, 1.0,
                0.0, 1.0, 0.0, 1.0,
            ], dtype=np.float32),
            [2, 2],
            Mesh.RECT_INDICES
        )
        # fmt: on

        self._tracks: dict[int, list[dict]] = {}
        self._visible_tracks: set[int] = set()
        self._track_colors: dict[int, tuple[float, float, float, float]] = {}
        self._track_names: dict[int, str] = {}

        self.ppq = 480
        self.beats_per_bar = 4

    def load_midi(self, path: Path) -> None:
        midi = mido.MidiFile(path)
        self.ppq = midi.ticks_per_beat
        self.beats_per_bar = 4

        self._tracks.clear()
        self._visible_tracks.clear()
        self._track_colors.clear()
        self._track_names.clear()

        track_count = len(midi.tracks)
        for i in range(track_count):
            h = i / max(track_count, 1)
            r, g, b = colorsys.hsv_to_rgb(h, 0.8, 0.9)
            self._track_colors[i] = (r, g, b, 1.0)
            self._visible_tracks.add(i)

        for i, track in enumerate(midi.tracks):
            self._tracks[i] = []
            self._track_names[i] = f"Track {i}"
            current_instrument = None
            current_time = 0
            active_notes = {}

            for msg in track:
                current_time += msg.time
                if msg.type == "track_name":
                    self._track_names[i] = msg.name
                elif msg.type == "time_signature":
                    self.beats_per_bar = msg.numerator
                elif msg.type == "note_on" and msg.velocity > 0:
                    active_notes[msg.note] = current_time
                elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                    if msg.note in active_notes:
                        start_time = active_notes.pop(msg.note)
                        duration = current_time - start_time
                        self._tracks[i].append(
                            {
                                "pitch": msg.note,
                                "start": start_time,
                                "duration": duration,
                            }
                        )
                elif msg.type == "program_change":
                    current_instrument = INSTRUMENTS[msg.program]
                    self._track_names[i] = current_instrument

        self.rebuild_mesh()

    def set_track_visibility(self, track_idx: int, visible: bool) -> None:
        if visible:
            self._visible_tracks.add(track_idx)
        else:
            self._visible_tracks.discard(track_idx)
        self.rebuild_mesh()

    def rebuild_mesh(self) -> None:
        if self._mesh:
            self._mesh.delete()
            self._mesh = None

        instance_data = []
        for i in self._visible_tracks:
            notes = self._tracks.get(i, [])
            color = self._track_colors.get(i, (1.0, 1.0, 1.0, 1.0))
            for note in notes:
                instance_data.extend([float(note["start"]) * 0.1, float(127 - note["pitch"]) * 32.0])
                instance_data.extend([float(note["duration"]) * 0.1, 32.0 * 0.8])
                instance_data.extend(list(color))

        if instance_data:
            self._mesh = Mesh(
                Mesh.RECT_WITH_UV_VERTS,
                self.LAYOUT,
                Mesh.RECT_INDICES,
                instance_data=np.array(instance_data, dtype=np.float32),
                instance_layout=self.INSTANCE_LAYOUT,
                instance_attrib_base=2,
            )

    def draw(self, camera: Camera2D) -> None:

        glDisable(GL_DEPTH_TEST)

        self._grid_shader.use()
        self._u_grid_proj.set_mat4x4(camera.proj_as_numpy())

        min_x, min_y, w, h = camera.get_bounds()
        self._u_grid_min.set_vec2(np.array([min_x, min_y], dtype=np.float32))
        self._u_grid_max.set_vec2(np.array([min_x + w, min_y + h], dtype=np.float32))

        self._u_grid_ppq.set_float(float(self.ppq) * 0.1)
        self._u_grid_bpb.set_int(self.beats_per_bar)
        self._u_grid_zoom.set_vec2(np.array([camera.zoom, camera.zoom], dtype=np.float32))

        self._grid_mesh.draw()

        if self._mesh:
            self._shader.use()
            self._u_proj.set_mat4x4(camera.proj_as_numpy())
            self._mesh.draw_instanced()

        glEnable(GL_DEPTH_TEST)

    def delete(self) -> None:
        if self._mesh:
            self._mesh.delete()
            self._mesh = None
        self._grid_mesh.delete()

    @property
    def track_info(self) -> dict[int, tuple[str, bool, tuple[float, float, float, float]]]:
        info = {}
        for i in range(len(self._tracks)):
            name = self._track_names.get(i, f"Track {i}")
            info[i] = (name, i in self._visible_tracks, self._track_colors.get(i, (1, 1, 1, 1)))
        return info
