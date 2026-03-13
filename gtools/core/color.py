from PIL import Image
import numpy as np


def _srgb_to_linear_01(c: np.ndarray) -> np.ndarray:
    a = 0.055
    low_mask = c <= 0.04045
    out = np.empty_like(c)
    out[low_mask] = c[low_mask] / 12.92
    out[~low_mask] = ((c[~low_mask] + a) / (1.0 + a)) ** 2.4
    return out


def _linear_to_srgb_01(c: np.ndarray) -> np.ndarray:
    a = 0.055
    low_mask = c <= 0.0031308
    out = np.empty_like(c)
    out[low_mask] = c[low_mask] * 12.92
    out[~low_mask] = (1.0 + a) * (c[~low_mask] ** (1.0 / 2.4)) - a
    return out


def color_matrix_filter(image: np.ndarray, matrix: np.ndarray, linear: bool = False) -> np.ndarray:
    image = np.asarray(image)
    if image.ndim != 3 or image.shape[2] != 4:
        raise ValueError(f"image must be shape (H, W, 4), got {image.shape}")

    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.shape != (4, 5):
        raise ValueError(f"matrix must be shape (4, 5), got {matrix.shape}")

    h, w, _ = image.shape
    n = h * w

    flat = image.reshape(n, 4)

    working = np.empty((n, 4), dtype=np.float32)
    rgb = flat[:, :3].astype(np.float32) / 255.0
    if linear:
        rgb = _srgb_to_linear_01(rgb)
    working[:, :3] = rgb
    working[:, 3] = flat[:, 3].astype(np.float32) / 255.0

    weights = matrix[:, :4]
    bias = matrix[:, 4]

    result = working.dot(weights.T)
    result += bias

    np.clip(result, 0.0, 1.0, out=result)

    if linear:
        result[:, :3] = _linear_to_srgb_01(result[:, :3])

    out = np.rint(result * 255.0).astype(np.uint8)
    return out.reshape(h, w, 4)


def color_tint(image: np.ndarray, color: np.ndarray) -> np.ndarray:
    tint = color[:3].astype(np.float32) / 255.0
    result = image.astype(np.float32)
    result[..., :3] *= tint
    return np.clip(result, 0, 255).round().astype(np.uint8)


def color_mix(
    color_a: np.ndarray,
    color_b: np.ndarray,
    mix_factor: float,
) -> np.ndarray:
    mixed = np.round(color_a[:3] * mix_factor + color_b[:3] * (1 - mix_factor)).astype(np.uint8)
    return np.append(mixed, 255).astype(np.uint8)


def composite(top: np.ndarray, bottom: np.ndarray, dx=0, dy=0) -> np.ndarray:
    top_im = Image.fromarray(top, mode="RGBA")
    bot_im = Image.fromarray(bottom, mode="RGBA")

    canvas = Image.new("RGBA", top_im.size, (0, 0, 0, 0))
    canvas.paste(bot_im, (dx, dy), bot_im)
    result = Image.alpha_composite(canvas, top_im)
    return np.array(result)
