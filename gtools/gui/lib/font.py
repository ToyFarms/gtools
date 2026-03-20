from dataclasses import dataclass
from pathlib import Path

import freetype
import numpy as np
from scipy.ndimage import distance_transform_edt
from OpenGL.GL import (
    GL_CLAMP_TO_EDGE,
    GL_LINEAR,
    GL_R16,
    GL_RED,
    GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T,
    GL_UNPACK_ALIGNMENT,
    GL_UNSIGNED_SHORT,
    glBindTexture,
    glDeleteTextures,
    glGenTextures,
    glPixelStorei,
    glTexImage2D,
    glTexParameteri,
)


@dataclass(slots=True)
class Character:
    size: tuple[float, float]
    bearing: tuple[float, float]
    advance: float
    tex_offset: tuple[float, float]
    tex_size: tuple[float, float]


class FontManager:
    def __init__(
        self,
        font_path: str | Path,
        size: int = 16,
        sdf_pixel_range: float = 12.0,
        raster_scale: int = 4,
        atlas_min_size: int = 1024,
    ) -> None:
        self.font_path = Path(font_path)
        self.size = size
        self.raster_scale = max(1, int(raster_scale))
        self.atlas_min_size = max(64, int(atlas_min_size))
        self.face = freetype.Face(str(self.font_path))
        self.face.set_pixel_sizes(0, size * self.raster_scale)
        self.chars: dict[str, Character] = {}
        self.atlas_tex: int | None = None
        self._sdf_pixel_range_hi = float(sdf_pixel_range)
        self._sdf_pixel_range = self._sdf_pixel_range_hi / self.raster_scale
        self._load_ascii_sdf()

    def _to_sdf(self, alpha: np.ndarray, padding: int) -> np.ndarray:
        source = alpha.astype(np.float32) / 255.0
        padded = np.pad(source, padding, mode="constant", constant_values=0.0)
        inside = padded > 0.0
        dist_inside = distance_transform_edt(inside).astype(np.float32)  # pyright: ignore[reportAttributeAccessIssue]
        dist_outside = distance_transform_edt(~inside).astype(np.float32)  # pyright: ignore[reportAttributeAccessIssue]
        signed_distance = dist_inside - dist_outside
        normalized = np.clip(0.5 + signed_distance / (2.0 * self._sdf_pixel_range_hi), 0.0, 1.0)

        return (normalized * 65535.0).astype(np.uint16)

    def _unpack_mono_bitmap(self, buffer: bytes | bytearray | list[int], width: int, rows: int, pitch: int) -> np.ndarray:
        out = np.zeros((rows, width), dtype=np.uint8)
        raw = bytes(buffer) if isinstance(buffer, list) else bytes(buffer)
        byte_pitch = abs(pitch)
        for y in range(rows):
            row_start = y * byte_pitch
            row_end = row_start + byte_pitch
            row = np.frombuffer(raw[row_start:row_end], dtype=np.uint8)
            bits = np.unpackbits(row, bitorder="big")
            out[y, :] = bits[:width] * 255
        return out

    def _load_ascii_sdf(self) -> None:
        chars_to_load = [chr(i) for i in range(32, 127)]
        padding = int(np.ceil(self._sdf_pixel_range_hi)) + 1
        glyphs = []

        for char in chars_to_load:
            self.face.load_char(char, freetype.FT_LOAD_RENDER | freetype.FT_LOAD_MONOCHROME | freetype.FT_LOAD_TARGET_MONO)  # pyright: ignore[reportAttributeAccessIssue]
            bitmap = self.face.glyph.bitmap
            w = bitmap.width
            h = bitmap.rows
            if w > 0 and h > 0:
                alpha = self._unpack_mono_bitmap(bitmap.buffer, w, h, bitmap.pitch)
                sdf_bitmap = self._to_sdf(alpha, padding)
                packed_w = w + padding * 2
                packed_h = h + padding * 2
            else:
                sdf_bitmap = np.zeros((0, 0), dtype=np.uint16)
                packed_w = 0
                packed_h = 0

            glyphs.append((char, packed_w, packed_h, sdf_bitmap, self.face.glyph.bitmap_left, self.face.glyph.bitmap_top, self.face.glyph.advance.x))

        atlas_w = self.atlas_min_size
        max_glyph_w = max((g[1] for g in glyphs), default=1)
        atlas_w = max(atlas_w, max_glyph_w + 2)
        x_offset = 0
        y_offset = 0
        row_h = 0
        packed: list[tuple[str, int, int, np.ndarray, int, int, int, int, int]] = []
        for char, packed_w, packed_h, sdf_bitmap, left, top, advance in glyphs:
            if packed_w > 0 and x_offset + packed_w > atlas_w:
                x_offset = 0
                y_offset += row_h + 1
                row_h = 0
            packed.append((char, packed_w, packed_h, sdf_bitmap, left, top, advance, x_offset, y_offset))
            x_offset += packed_w + 1
            row_h = max(row_h, packed_h)
        atlas_h = max(self.atlas_min_size, y_offset + row_h + 1, 1)

        self.atlas_tex = int(glGenTextures(1))
        glBindTexture(GL_TEXTURE_2D, self.atlas_tex)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        atlas = np.zeros((atlas_h, atlas_w), dtype=np.uint16)

        for char, packed_w, packed_h, sdf_bitmap, left, top, advance, x_offset, y_offset in packed:
            if packed_w > 0 and packed_h > 0:
                atlas[y_offset : y_offset + packed_h, x_offset : x_offset + packed_w] = sdf_bitmap
                bearing_x = (left - padding) / self.raster_scale
                bearing_y = (top + padding) / self.raster_scale
                glyph_w = packed_w / self.raster_scale
                glyph_h = packed_h / self.raster_scale
            else:
                bearing_x = left / self.raster_scale
                bearing_y = top / self.raster_scale
                glyph_w = 0.0
                glyph_h = 0.0

            tex_offset = (x_offset / atlas_w, y_offset / atlas_h)
            tex_size = (packed_w / atlas_w, packed_h / atlas_h if atlas_h > 0 else 0.0)

            bearing_y = (top + padding) / self.raster_scale
            glyph_h = packed_h / self.raster_scale

            self.chars[char] = Character(
                (glyph_w, glyph_h),
                (bearing_x, bearing_y),
                (advance / 64.0) / self.raster_scale,
                tex_offset,
                tex_size,
            )

        glTexImage2D(GL_TEXTURE_2D, 0, GL_R16, atlas_w, atlas_h, 0, GL_RED, GL_UNSIGNED_SHORT, atlas.tobytes())

        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glBindTexture(GL_TEXTURE_2D, 0)

    @property
    def ascender(self) -> int:
        return int(round((self.face.size.ascender >> 6) / self.raster_scale))

    @property
    def descender(self) -> int:
        return int(round((self.face.size.descender >> 6) / self.raster_scale))

    @property
    def height(self) -> int:
        return int(round((self.face.size.height >> 6) / self.raster_scale))

    @property
    def sdf_pixel_range(self) -> float:
        return self._sdf_pixel_range

    def get_char(self, char: str) -> Character:
        return self.chars.get(char, self.chars[" "])

    def delete(self) -> None:
        if self.atlas_tex:
            glDeleteTextures(1, [self.atlas_tex])
