from collections import deque
from typing import Optional
import numpy as np
import sounddevice as sd
import soundfile as sf
import soxr

TARGET_SR = 48_000
CHANNELS = 2

_MIN_DB = -60.0

def _perceptual_to_linear(gain: float) -> float:
    if gain <= 0.0:
        return 0.0

    db = _MIN_DB * (1.0 - gain)
    return 10.0 ** (db / 20.0)


def _normalise_channels(data: np.ndarray) -> np.ndarray:
    if data.ndim == 1:
        data = np.stack([data, data], axis=1)
    elif data.shape[1] == 1:
        data = np.repeat(data, CHANNELS, axis=1)
    elif data.shape[1] > CHANNELS:
        data = data[:, :CHANNELS]
    return data.astype(np.float32)


def _resample(data: np.ndarray, from_sr: int) -> np.ndarray:
    if from_sr == TARGET_SR:
        return data
    return soxr.resample(data, from_sr, TARGET_SR, quality="HQ")


class Sound:
    def __init__(self, data: np.ndarray, sample_rate: int = TARGET_SR) -> None:
        normalised = _normalise_channels(data)
        resampled = _resample(normalised, sample_rate)
        resampled.flags.writeable = False

        self.data = resampled

    @classmethod
    def from_file(cls, path: str) -> "Sound":
        data, sample_rate = sf.read(path, dtype="float32", always_2d=True)
        return cls(data, sample_rate=sample_rate)

    def get_handle(self, gain: float) -> "_PlaybackHandle":
        return _PlaybackHandle(self, gain)


class _PlaybackHandle:
    __slots__ = ("_sound", "_pos", "gain")

    def __init__(self, sound: Sound, gain: float) -> None:
        self._sound = sound
        self._pos = 0
        self.gain = gain

    @property
    def is_done(self) -> bool:
        return self._pos >= len(self._sound.data)

    def read(self, n: int) -> np.ndarray:
        chunk = self._sound.data[self._pos : self._pos + n]
        self._pos += len(chunk)

        # i don't know if they convert it to linear or not
        # return chunk * _perceptual_to_linear(self.gain)
        return chunk * self.gain


class AudioMixer:
    def __init__(self, *, blocksize: int = 512, latency: str = "low", device: Optional[int | str] = None) -> None:
        self._pending: deque[_PlaybackHandle] = deque()
        self._streams: list[_PlaybackHandle] = []
        self.stream = sd.OutputStream(
            samplerate=TARGET_SR,
            channels=CHANNELS,
            dtype="float32",
            blocksize=blocksize,
            latency=latency,
            device=device,
            callback=self._callback,
        )
        self.master_gain = 1.0
        self.stream.start()

    def play(self, sound: Sound, gain: float = 1.0) -> None:
        self._pending.appendleft(sound.get_handle(gain))

    def stop(self) -> None:
        self.stream.stop()
        self.stream.close()

    def _callback(
        self,
        outdata: np.ndarray,
        frames: int,
        time,
        status: sd.CallbackFlags,
    ) -> None:
        _ = time, status

        try:
            while True:
                self._streams.append(self._pending.pop())
        except IndexError:
            pass

        mixed = np.zeros((frames, CHANNELS), dtype=np.float32)
        survivors: list[_PlaybackHandle] = []

        for s in self._streams:
            chunk = s.read(frames)
            n = len(chunk)
            if n:
                mixed[:n] += chunk
            if not s.is_done:
                survivors.append(s)

        self._streams = survivors

        np.tanh(mixed, out=mixed)
        outdata[:] = mixed * _perceptual_to_linear(self.master_gain)
