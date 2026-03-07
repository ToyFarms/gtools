from collections import deque
from typing import Optional
import numpy as np
import sounddevice as sd
import soundfile as sf
import soxr

TARGET_SR = 48_000
CHANNELS = 2


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

    def get_handle(self) -> "_PlaybackHandle":
        return _PlaybackHandle(self)


class _PlaybackHandle:
    __slots__ = ("_sound", "_pos")

    def __init__(self, sound: Sound) -> None:
        self._sound = sound
        self._pos: int = 0

    @property
    def is_done(self) -> bool:
        return self._pos >= len(self._sound.data)

    def read(self, n: int) -> np.ndarray:
        chunk = self._sound.data[self._pos : self._pos + n]
        self._pos += len(chunk)
        return chunk


class AudioMixer:
    def __init__(self, *, blocksize: int = 0, latency: str = "low", device: Optional[int | str] = None) -> None:
        self._pending: deque[_PlaybackHandle] = deque()
        self._streams: list[_PlaybackHandle] = []
        self.stream = sd.OutputStream(
            samplerate=TARGET_SR,
            channels=CHANNELS,
            dtype="float32",
            blocksize=512,
            latency=latency,
            device=device,
            callback=self._callback,
        )
        self.stream.start()

    def play(self, sound: Sound) -> None:
        self._pending.appendleft(sound.get_handle())

    def stop(self) -> None:
        self.stream.stop()
        self.stream.close()

    def __enter__(self) -> "AudioMixer":
        return self

    def __exit__(self, *_) -> None:
        self.stop()

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
        outdata[:] = mixed
