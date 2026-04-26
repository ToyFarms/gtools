import struct

import numpy as np
from PIL import Image, ImageChops


def _srgb_to_linear_01(c: np.ndarray) -> np.ndarray:
    a = 0.055
    low = c <= 0.04045
    out = np.empty_like(c)
    out[low] = c[low] / 12.92
    out[~low] = ((c[~low] + a) / (1.0 + a)) ** 2.4
    return out


def _linear_to_srgb_01(c: np.ndarray) -> np.ndarray:
    a = 0.055
    low = c <= 0.0031308
    out = np.empty_like(c)
    out[low] = c[low] * 12.92
    out[~low] = (1.0 + a) * c[~low] ** (1.0 / 2.4) - a
    return out


_IDENTITY_4x5 = np.array(
    [[1, 0, 0, 0, 0], [0, 1, 0, 0, 0], [0, 0, 1, 0, 0], [0, 0, 0, 1, 0]],
    dtype=np.float32,
)


def color_matrix_filter[T: (np.ndarray, Image.Image)](image: T, matrix: np.ndarray, linear: bool = False) -> T:
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.shape != (4, 5):
        raise ValueError(f"matrix must be shape (4, 5), got {matrix.shape}")

    if not linear and np.array_equal(matrix, _IDENTITY_4x5):
        return image

    if isinstance(image, Image.Image):
        arr = np.asarray(image)
        if arr.ndim != 3 or arr.shape[2] != 4:
            raise ValueError(f"image must be RGBA, got {arr.shape}")

        h, w = arr.shape[:2]
        flat = arr.reshape(-1, 4).astype(np.float32) / 255.0

        if linear:
            flat[:, :3] = _srgb_to_linear_01(flat[:, :3])

        result = flat @ matrix[:, :4].T + matrix[:, 4]
        np.clip(result, 0.0, 1.0, out=result)

        if linear:
            result[:, :3] = _linear_to_srgb_01(result[:, :3])

        out_arr = np.rint(result * 255.0).astype(np.uint8).reshape(h, w, 4)
        return Image.fromarray(out_arr, "RGBA")

    arr = image
    if arr.ndim != 3 or arr.shape[2] != 4:
        raise ValueError(f"image must be RGBA, got {arr.shape}")

    h, w = arr.shape[:2]
    flat = arr.reshape(-1, 4).astype(np.float32) / 255.0

    if linear:
        flat[:, :3] = _srgb_to_linear_01(flat[:, :3])

    result = flat @ matrix[:, :4].T + matrix[:, 4]
    np.clip(result, 0.0, 1.0, out=result)

    if linear:
        result[:, :3] = _linear_to_srgb_01(result[:, :3])

    return np.rint(result * 255.0).astype(np.uint8).reshape(h, w, 4)


def color_tint[T: (np.ndarray, Image.Image)](image: T, color: np.ndarray) -> T:
    if isinstance(image, Image.Image):
        r, g, b, a = image.split()
        size = image.size

        r = ImageChops.multiply(r, Image.new("L", size, int(color[0])))
        g = ImageChops.multiply(g, Image.new("L", size, int(color[1])))
        b = ImageChops.multiply(b, Image.new("L", size, int(color[2])))

        return Image.merge("RGBA", (r, g, b, a))

    pil = Image.fromarray(np.asarray(image, dtype=np.uint8), "RGBA")

    r, g, b, a = pil.split()
    size = pil.size

    r = ImageChops.multiply(r, Image.new("L", size, int(color[0])))
    g = ImageChops.multiply(g, Image.new("L", size, int(color[1])))
    b = ImageChops.multiply(b, Image.new("L", size, int(color[2])))

    result = Image.merge("RGBA", (r, g, b, a))
    return np.asarray(result)


def color_mix(color_a: np.ndarray, color_b: np.ndarray, mix_factor: float) -> np.ndarray:
    mixed = np.round(color_a[:3] * mix_factor + color_b[:3] * (1.0 - mix_factor)).astype(np.uint8)
    return np.append(mixed, 255).astype(np.uint8)


def composite[T: (np.ndarray, Image.Image), U: (np.ndarray, Image.Image)](top: T, bottom: U, dx: int = 0, dy: int = 0) -> Image.Image:
    if isinstance(top, Image.Image):
        top_im = top
    else:
        top_im = Image.fromarray(np.asarray(top, dtype=np.uint8), "RGBA")

    if isinstance(bottom, Image.Image):
        bot_im = bottom
    else:
        bot_im = Image.fromarray(np.asarray(bottom, dtype=np.uint8), "RGBA")

    if dx == 0 and dy == 0:
        return Image.alpha_composite(bot_im, top_im)

    canvas = Image.new("RGBA", top_im.size, (0, 0, 0, 0))
    canvas.paste(bot_im, (dx, dy), bot_im)
    return Image.alpha_composite(canvas, top_im)


def composite_onto[T: (np.ndarray, Image.Image), U: (np.ndarray, Image.Image)](
    base: T,
    layer: U,
    dx: int = 0,
    dy: int = 0,
) -> Image.Image:
    if isinstance(base, Image.Image):
        base_im = base
    else:
        base_im = Image.fromarray(np.asarray(base, dtype=np.uint8), "RGBA")

    if isinstance(layer, Image.Image):
        layer_im = layer
    else:
        layer_im = Image.fromarray(np.asarray(layer, dtype=np.uint8), "RGBA")

    temp = Image.new("RGBA", base_im.size, (0, 0, 0, 0))
    temp.paste(layer_im, (dx, dy))
    return Image.alpha_composite(base_im, temp)


class Color:
    __slots__ = ("r", "g", "b", "a")

    def __init__(self, r: int = 0, g: int = 0, b: int = 0, a: int = 0) -> None:
        self.r = r
        self.g = g
        self.b = b
        self.a = a

    @classmethod
    def from_int_le(cls, x: int) -> "Color":
        return cls(x & 0xFF, (x >> 8) & 0xFF, (x >> 16) & 0xFF, (x >> 24) & 0xFF)

    @classmethod
    def from_int_be(cls, x: int) -> "Color":
        return cls((x >> 24) & 0xFF, (x >> 16) & 0xFF, (x >> 8) & 0xFF, x & 0xFF)

    def to_int_le(self) -> int:
        return (self.a << 24) | (self.b << 16) | (self.g << 8) | self.r

    def to_int_be(self) -> int:
        return (self.r << 24) | (self.g << 16) | (self.b << 8) | self.a

    def to_tuple(self) -> tuple[int, int, int, int]:
        return (self.r, self.g, self.b, self.a)


def pack_color(col: int) -> float:
    return struct.unpack("f", struct.pack("I", col))[0]
