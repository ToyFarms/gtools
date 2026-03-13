from pathlib import Path
import freetype
import numpy as np
from OpenGL.GL import (
    GL_RED,
    GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T,
    GL_CLAMP_TO_EDGE,
    GL_LINEAR,
    GL_UNPACK_ALIGNMENT,
    GL_UNSIGNED_BYTE,
    glBindTexture,
    glGenTextures,
    glPixelStorei,
    glTexImage2D,
    glTexParameteri,
    glTexSubImage2D,
)
from dataclasses import dataclass


@dataclass(slots=True)
class Character:
    texture_id: int
    size: tuple[int, int]
    bearing: tuple[int, int]
    advance: int
    tex_offset: tuple[float, float]
    tex_size: tuple[float, float]


class FontManager:
    def __init__(self, font_path: str | Path, size: int = 16) -> None:
        self.face = freetype.Face(str(font_path))
        self.face.set_pixel_sizes(0, size)
        self.chars: dict[str, Character] = {}
        self.atlas_tex = None
        self._load_ascii()

    def _load_ascii(self) -> None:
        chars_to_load = [chr(i) for i in range(32, 128)]

        max_h = 0
        total_w = 0
        glyphs = []
        for char in chars_to_load:
            self.face.load_char(char, freetype.FT_LOAD_RENDER)  # pyright: ignore[reportAttributeAccessIssue]
            bitmap = self.face.glyph.bitmap
            glyphs.append((char, bitmap.width, bitmap.rows, bitmap.buffer, self.face.glyph.bitmap_left, self.face.glyph.bitmap_top, self.face.glyph.advance.x))
            max_h = max(max_h, bitmap.rows)
            total_w += bitmap.width + 1

        atlas_w = total_w
        atlas_h = max_h

        self.atlas_tex = int(glGenTextures(1))
        glBindTexture(GL_TEXTURE_2D, self.atlas_tex)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)

        empty_data = np.zeros((atlas_h, atlas_w), dtype=np.uint8)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RED, atlas_w, atlas_h, 0, GL_RED, GL_UNSIGNED_BYTE, empty_data.tobytes())

        x_offset = 0
        for char, w, h, buffer, left, top, advance in glyphs:
            if w > 0 and h > 0:
                pixel_data = np.array(buffer, dtype=np.uint8).reshape(h, w)
                glTexSubImage2D(GL_TEXTURE_2D, 0, x_offset, 0, w, h, GL_RED, GL_UNSIGNED_BYTE, pixel_data.tobytes())

            self.chars[char] = Character(self.atlas_tex, (w, h), (left, top), advance, (x_offset / atlas_w, 0), (w / atlas_w, h / atlas_h))
            x_offset += w + 1

        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glBindTexture(GL_TEXTURE_2D, 0)

    def get_char(self, char: str) -> Character:
        return self.chars.get(char, self.chars[" "])
