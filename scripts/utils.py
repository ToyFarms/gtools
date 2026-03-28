import os
import shutil
import subprocess
import sys
from typing import Protocol, Sequence
import numpy as np


class SupportsStr(Protocol):
    def __str__(self) -> str: ...


def call(cmd: Sequence[SupportsStr]) -> None:
    c = list(map(str, cmd))
    print(f"+ {' '.join(c)}")
    ret = subprocess.run(c, stdout=sys.stdout, stderr=sys.stderr)
    if ret.returncode != 0:
        print(f"\x1b[31mnon-zero return code\x1b[0m ({ret.returncode}) return code: {ret!r}")


def capture_stdout(cmd: list[SupportsStr]) -> str:
    c = list(map(str, cmd))
    print(f"+ {' '.join(c)}")
    ret = subprocess.run(c, capture_output=True)
    if ret.returncode != 0:
        print(f"\x1b[31mnon-zero return code\x1b[0m ({ret.returncode}) return code: {ret!r}")

    return ret.stdout.decode()


def capture_stderr(cmd: list[SupportsStr]) -> str:
    c = list(map(str, cmd))
    print(f"+ {' '.join(c)}")
    ret = subprocess.run(c, capture_output=True)
    if ret.returncode != 0:
        print(f"\x1b[31mnon-zero return code\x1b[0m ({ret.returncode}) return code: {ret!r}")

    return ret.stderr.decode()


def executable_exists(name: str) -> bool:
    path = shutil.which(name)
    return path is not None and os.access(path, os.X_OK)


def _blend_rgba_over_bg(rgba: np.ndarray, bg=(0, 0, 0)) -> np.ndarray:
    rgba = rgba.astype(np.float32)
    rgb = rgba[..., :3]
    a = rgba[..., 3:4] / 255.0
    bg = np.array(bg, dtype=np.float32)
    out = rgb * a + bg * (1.0 - a)

    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def image_show_ansi(img: np.ndarray, bg=(0, 0, 0), file=sys.stdout) -> None:
    if img.ndim != 3 or img.shape[-1] != 4:
        raise ValueError("expected an array of shape (H, W, 4)")

    h, w, _ = img.shape

    rgb = _blend_rgba_over_bg(img, bg=bg)

    if h % 2 == 1:
        pad = np.full((1, w, 3), np.array(bg, dtype=np.uint8), dtype=np.uint8)
        rgb = np.concatenate([rgb, pad], axis=0)
        h += 1

    for y in range(0, h, 2):
        top = rgb[y]
        bottom = rgb[y + 1]

        parts = []
        for x in range(w):
            tr, tg, tb = top[x]
            br, bg_, bb = bottom[x]
            parts.append(f"\x1b[38;2;{tr};{tg};{tb}m" f"\x1b[48;2;{br};{bg_};{bb}m▀")
        parts.append("\x1b[0m")
        file.write("".join(parts) + "\n")
