import logging
from pathlib import Path
from OpenGL.GL import *  # pyright: ignore[reportWildcardImportFromLibrary]
from dataclasses import dataclass
from gtools.core.growtopia.rttex import RTTex

logger = logging.getLogger("gui-textures")


@dataclass(slots=True)
class GLTex:
    key: str
    width: int
    height: int
    layer: int
    array: "TextureArray"

    @property
    def tex_id(self) -> int:
        return self.array.tex_id

    def __hash__(self) -> int:
        return hash(self.key)


class TextureArray:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.tex_id = int(glGenTextures(1))

        self._resident: list[GLTex] = []
        self._staging: list[GLTex] = []

        self._allocated_layers = 0

    def _allocate(self, total_layers: int) -> None:
        glBindTexture(GL_TEXTURE_2D_ARRAY, self.tex_id)

        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)

        glTexImage3D(
            GL_TEXTURE_2D_ARRAY,
            0,
            GL_RGBA8,
            self.width,
            self.height,
            total_layers,
            0,
            GL_RGBA,
            GL_UNSIGNED_BYTE,
            None,
        )

        self._allocated_layers = total_layers
        glBindTexture(GL_TEXTURE_2D_ARRAY, 0)

    def stage(self, key: str) -> GLTex:
        layer = len(self._resident) + len(self._staging)
        tex = GLTex(key, self.width, self.height, layer, self)
        self._staging.append(tex)
        return tex

    def flush(self) -> None:
        if not self._staging:
            return

        total_layers = len(self._resident) + len(self._staging)

        if total_layers != self._allocated_layers:
            logger.debug(f"reallocating TextureArray {self.width}x{self.height} to {total_layers} layers " f"(previously {self._allocated_layers})")
            self._allocate(total_layers)

        logger.info(f"uploading {len(self._staging)} staged textures to GPU texture array " f"{self.width}x{self.height}")

        glBindTexture(GL_TEXTURE_2D_ARRAY, self.tex_id)

        for tex in self._staging:
            logger.debug(f"uploading texture key={tex.key} to layer={tex.layer} " f"(size={self.width}x{self.height})")
            data = RTTex.from_file(tex.key)
            mip = data.get_mip(0)

            glTexSubImage3D(
                GL_TEXTURE_2D_ARRAY,
                0,
                0,
                0,
                tex.layer,
                self.width,
                self.height,
                1,
                GL_RGBA,
                GL_UNSIGNED_BYTE,
                mip.pixels,
            )

        self._resident.extend(self._staging)
        self._staging.clear()

        glBindTexture(GL_TEXTURE_2D_ARRAY, 0)

    def bind(self, unit: int = 0) -> None:
        glActiveTexture(int(GL_TEXTURE0) + unit)
        glBindTexture(GL_TEXTURE_2D_ARRAY, self.tex_id)

    def delete(self) -> None:
        glDeleteTextures(1, [self.tex_id])
        self._resident.clear()
        self._staging.clear()
        self._allocated_layers = 0


class GLTexManager:
    def __init__(self) -> None:
        self._textures: dict[str, GLTex] = {}
        self._arrays: dict[tuple[int, int], TextureArray] = {}

    def _get_or_create_array(self, width: int, height: int) -> TextureArray:
        key = (width, height)

        if key not in self._arrays:
            self._arrays[key] = TextureArray(width, height)

        return self._arrays[key]

    def push_texture(self, file: str | Path) -> GLTex:
        key = str(file)

        if key in self._textures:
            return self._textures[key]

        header = RTTex.header_from_file(key)

        array = self._get_or_create_array(header.width, header.height)

        tex = array.stage(key)
        self._textures[key] = tex

        return tex

    def flush(self) -> None:
        for array in self._arrays.values():
            array.flush()

    def bind(self, tex: GLTex, unit: int = 0) -> None:
        tex.array.bind(unit)

    def delete_texture(self, key: str) -> None:
        if key not in self._textures:
            return

        tex = self._textures.pop(key)
        array = tex.array

        array.delete()

        self._arrays.pop((array.width, array.height), None)

        keys_to_remove = [k for k, t in self._textures.items() if t.array is array]

        for k in keys_to_remove:
            self._textures.pop(k)

    def delete_all(self) -> None:
        for array in self._arrays.values():
            array.delete()

        self._arrays.clear()
        self._textures.clear()
