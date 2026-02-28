import numpy as np


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    c = c.astype(np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c: np.ndarray) -> np.ndarray:
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * (c ** (1.0 / 2.4)) - 0.055)


def color_matrix_filter(image: np.ndarray, matrix: np.ndarray, linear: bool = False) -> np.ndarray:
    if image.ndim != 3 or image.shape[2] != 4:
        raise ValueError(f"image must be shape (H, W, 4), got {image.shape}")

    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.shape != (4, 5):
        raise ValueError(f"matrix must be shape (4, 5), got {matrix.shape}")

    h, w, _ = image.shape
    flat = image.reshape(-1, 4)

    working = np.empty((h * w, 4), dtype=np.float64)

    if linear:
        working[:, :3] = srgb_to_linear(flat[:, :3])
    else:
        working[:, :3] = flat[:, :3].astype(np.float64) / 255.0

    working[:, 3] = flat[:, 3].astype(np.float64) / 255.0

    ones = np.ones((working.shape[0], 1), dtype=np.float64)
    augmented = np.concatenate([working, ones], axis=1)
    result = augmented @ matrix.T
    result = np.clip(result, 0.0, 1.0)

    out = np.empty_like(result)

    if linear:
        out[:, :3] = linear_to_srgb(result[:, :3])
    else:
        out[:, :3] = result[:, :3]

    out[:, 3] = result[:, 3]

    return (out * 255.0).round().astype(np.uint8).reshape(h, w, 4)
