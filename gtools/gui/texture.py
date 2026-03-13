import atexit
import logging
from pathlib import Path
from OpenGL.GL import (
    GL_CLAMP_TO_EDGE,
    GL_NEAREST,
    GL_RGBA,
    GL_RGBA8,
    GL_TEXTURE0,
    GL_TEXTURE_2D_ARRAY,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T,
    GL_UNPACK_ALIGNMENT,
    GL_UNSIGNED_BYTE,
    glActiveTexture,
    glBindTexture,
    glDeleteTextures,
    glGenTextures,
    glIsTexture,
    glPixelStorei,
    glTexImage3D,
    glTexParameteri,
    glTexSubImage3D,
)
from dataclasses import dataclass
from gtools.core.growtopia.rttex import RTTex

logger = logging.getLogger("gui-textures")

_DEFAULT_TEXTURE_KEY = "<__default_texture__>"
_DEFAULT_PIXEL_CACHE: dict[tuple[int, int], bytes] = {}
_DEFAULT_FALLBACK_SIZE = (1024, 1024)


def _make_default_pixels(width: int, height: int):
    tile = 8
    buf = bytearray(width * height * 4)
    for y in range(height):
        row_base = y * width * 4
        for x in range(width):
            sq = ((x // tile) + (y // tile)) % 2
            if sq == 0:
                r, g, b = 255, 0, 255
            else:
                r, g, b = 0, 0, 0
            i = row_base + x * 4
            buf[i] = r
            buf[i + 1] = g
            buf[i + 2] = b
            buf[i + 3] = 255
    return bytes(buf)


def _get_default_pixels(width: int, height: int) -> bytes:
    key = (width, height)
    if key not in _DEFAULT_PIXEL_CACHE:
        _DEFAULT_PIXEL_CACHE[key] = _make_default_pixels(width, height)
    return _DEFAULT_PIXEL_CACHE[key]


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

        if total_layers > self._allocated_layers:
            new_capacity = max(
                4,
                self._allocated_layers * 2 if self._allocated_layers else 4,
                total_layers,
            )

            logger.debug(f"growing TextureArray {self.width}x{self.height} from {self._allocated_layers} to {new_capacity} layers (used: {total_layers})")

            self._allocate(new_capacity)

            glBindTexture(GL_TEXTURE_2D_ARRAY, self.tex_id)

            for tex in self._resident:
                try:
                    data = RTTex.from_file(tex.key)
                    mip = data.get_mip(0)
                    pixels = mip.pixels
                except Exception:
                    logger.warning("failed to read resident texture '%s', fallback to default texture", tex.key)
                    pixels = _get_default_pixels(self.width, self.height)

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
                    pixels,
                )

        glBindTexture(GL_TEXTURE_2D_ARRAY, self.tex_id)

        for tex in self._staging:
            try:
                data = RTTex.from_file(tex.key)
                mip = data.get_mip(0)
                pixels = mip.pixels
            except Exception:
                logger.warning("failed to read staged texture '%s', fallback to default texture", tex.key)
                pixels = _get_default_pixels(self.width, self.height)

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
                pixels,
            )

        self._resident.extend(self._staging)
        self._staging.clear()

        glBindTexture(GL_TEXTURE_2D_ARRAY, 0)

    def bind(self, unit: int = 0) -> None:
        glActiveTexture(int(GL_TEXTURE0) + unit)
        glBindTexture(GL_TEXTURE_2D_ARRAY, self.tex_id)

    def delete(self) -> None:
        try:
            glDeleteTextures(1, [self.tex_id])
        except Exception:
            pass
        self._resident.clear()
        self._staging.clear()
        self._allocated_layers = 0


class GLTexManager:
    def __init__(self) -> None:
        self._textures: dict[str, GLTex] = {}
        self._arrays: dict[tuple[int, int], TextureArray] = {}
        self._default_array: TextureArray | None = None
        self._default_tex: GLTex | None = None

    def _get_or_create_array(self, width: int, height: int) -> TextureArray:
        key = (width, height)

        if key not in self._arrays:
            self._arrays[key] = TextureArray(width, height)

        return self._arrays[key]

    def _ensure_default_texture(self) -> GLTex:
        if self._default_tex is not None:
            return self._default_tex

        dw, dh = _DEFAULT_FALLBACK_SIZE
        self._default_array = TextureArray(dw, dh)

        default_tex = self._default_array.stage(_DEFAULT_TEXTURE_KEY)
        self._textures[_DEFAULT_TEXTURE_KEY] = default_tex

        self._default_array._allocate(1)
        glBindTexture(GL_TEXTURE_2D_ARRAY, self._default_array.tex_id)
        pixels = _get_default_pixels(dw, dh)
        glTexSubImage3D(
            GL_TEXTURE_2D_ARRAY,
            0,
            0,
            0,
            default_tex.layer,
            dw,
            dh,
            1,
            GL_RGBA,
            GL_UNSIGNED_BYTE,
            pixels,
        )
        glBindTexture(GL_TEXTURE_2D_ARRAY, 0)

        self._default_tex = self._textures[_DEFAULT_TEXTURE_KEY]
        return self._default_tex

    def push_texture(self, file: str | Path) -> GLTex:
        key = str(file)

        if key in self._textures:
            return self._textures[key]

        try:
            header = RTTex.header_from_file(key)
        except Exception:
            logger.warning("failed to read header for '%s', fallback to default texture", key)
            default = self._ensure_default_texture()
            self._textures[key] = default
            return default

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

        if tex.key == _DEFAULT_TEXTURE_KEY or (self._default_tex and tex is self._default_tex):
            return

        if self._default_array is not None and array is self._default_array:
            return

        keys_referencing = [k for k, t in self._textures.items() if t.array is array]
        if keys_referencing:
            for k in keys_referencing:
                self._textures.pop(k, None)

            return

        array.delete()
        self._arrays.pop((array.width, array.height), None)

    def delete_all(self) -> None:
        for array in self._arrays.values():
            array.delete()

        self._arrays.clear()
        self._textures.clear()

        if self._default_array:
            try:
                self._default_array.delete()
            except Exception:
                pass
        self._default_array = None
        self._default_tex = None


_GLOBAL_TEX_MANAGER = GLTexManager()
atexit.register(lambda: _GLOBAL_TEX_MANAGER.delete_all())


def get_texture(file: str | Path, unit: int = 0, bind: bool = False) -> GLTex:
    key = str(file)

    try:
        tex = _GLOBAL_TEX_MANAGER._textures.get(key)
        if tex is None:
            tex = _GLOBAL_TEX_MANAGER.push_texture(file)
        else:
            tex_id_valid = bool(glIsTexture(int(tex.tex_id)))
            layer_in_range = tex.layer < tex.array._allocated_layers if tex.array else False

            if not tex_id_valid or not layer_in_range:
                logger.debug(f"recreating texture array for {key}: tex_id_valid={tex_id_valid}, layer_ok={layer_in_range}")
                if key in _GLOBAL_TEX_MANAGER._textures:
                    _GLOBAL_TEX_MANAGER.delete_texture(key)
                tex = _GLOBAL_TEX_MANAGER.push_texture(file)

        _GLOBAL_TEX_MANAGER.flush()

        tex = _GLOBAL_TEX_MANAGER._textures.get(key)
        if tex is None:
            logger.error("failed to obtain texture for %s after flush, fallback to default texture", key)
            _GLOBAL_TEX_MANAGER._ensure_default_texture()
            tex = _GLOBAL_TEX_MANAGER._textures.get(_DEFAULT_TEXTURE_KEY)
            if tex is None:
                raise RuntimeError(f"failed to obtain default texture for {key}")

        if bind:
            _GLOBAL_TEX_MANAGER.bind(tex, unit)

        return tex

    except Exception as exc:
        logger.exception("get_texture failed for %s: %s", key, exc)
        default = _GLOBAL_TEX_MANAGER._textures.get(_DEFAULT_TEXTURE_KEY)
        if default is None:
            _GLOBAL_TEX_MANAGER._ensure_default_texture()
            default = _GLOBAL_TEX_MANAGER._textures.get(_DEFAULT_TEXTURE_KEY)
        if default is None:
            raise RuntimeError(f"could not load texture '{key}' and could not create default: {exc}") from exc
        if bind:
            _GLOBAL_TEX_MANAGER.bind(default, unit)

        return default

def get_tex_manager() -> GLTexManager:
    return _GLOBAL_TEX_MANAGER
