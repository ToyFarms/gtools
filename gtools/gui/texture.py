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

            from OpenGL.GL import glCopyImageSubData

            new_tex_id = int(glGenTextures(1))
            old_tex_id = self.tex_id
            old_allocated = self._allocated_layers

            self.tex_id = new_tex_id
            self._allocate(new_capacity)

            if old_tex_id != 0 and old_allocated > 0:
                glCopyImageSubData(
                    old_tex_id,
                    GL_TEXTURE_2D_ARRAY,
                    0,
                    0,
                    0,
                    0,
                    new_tex_id,
                    GL_TEXTURE_2D_ARRAY,
                    0,
                    0,
                    0,
                    0,
                    self.width,
                    self.height,
                    old_allocated,
                )
                glDeleteTextures(1, [old_tex_id])

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
    _instance: "GLTexManager | None" = None

    def __new__(cls) -> "GLTexManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._textures: dict[str, GLTex] = {}
        self._arrays: dict[tuple[int, int], TextureArray] = {}
        self._default_array: TextureArray | None = None
        self._default_tex: GLTex | None = None
        self._initialized = True

    @property
    def texture_count(self) -> int:
        return len(self._textures)

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

    def load_texture(self, file: str | Path) -> GLTex:
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
            logger.debug(f"delete texture '{key}' not found, skipping")
            return

        tex = self._textures.pop(key)
        array = tex.array

        if tex.key == _DEFAULT_TEXTURE_KEY or (self._default_tex and tex is self._default_tex):
            return

        if self._default_array is not None and array is self._default_array:
            logger.debug(f"texture '{key}' belongs to the default array, skipping deletion")
            return

        logger.debug(f"deleting texture '{key}' (layer={tex.layer}, array={array.width}x{array.height})")

        keys_referencing = [k for k, t in self._textures.items() if t.array is array]
        for k in keys_referencing:
            logger.debug(f"evicting co-resident texture '{k}' from array {array.width}x{array.height}")
            self._textures.pop(k, None)

        if len(keys_referencing) <= 1:
            logger.debug(f"delete_texture: destroying TextureArray {array.width}x{array.height} (tex_id={array.tex_id})")
            array.delete()
            self._arrays.pop((array.width, array.height), None)

    def delete_all(self) -> None:
        texture_count = len(self._textures)
        array_count = len(self._arrays)
        logger.debug(f"releasing {texture_count} texture(s) across {array_count} array(s)")

        for (w, h), array in self._arrays.items():
            logger.debug(f"destroying TextureArray {w}x{h} (tex_id={array.tex_id})")
            array.delete()

        self._arrays.clear()
        self._textures.clear()

        if self._default_array:
            logger.debug(f"destroying default TextureArray (tex_id={self._default_array.tex_id})")
            try:
                self._default_array.delete()
            except Exception:
                logger.warning("failed to delete default TextureArray", exc_info=True)
        self._default_array = None
        self._default_tex = None
def get_texture(file: str | Path, unit: int = 0, bind: bool = False) -> GLTex:
    key = str(file)
    manager = GLTexManager()

    try:
        tex = manager._textures.get(key)
        if tex is None:
            tex = manager.load_texture(file)
        else:
            tex_id_valid = bool(glIsTexture(int(tex.tex_id)))
            layer_in_range = tex.layer < tex.array._allocated_layers if tex.array else False

            if not tex_id_valid or not layer_in_range:
                logger.debug(f"recreating texture array for {key}: tex_id_valid={tex_id_valid}, layer_ok={layer_in_range}")
                if key in manager._textures:
                    manager.delete_texture(key)
                tex = manager.load_texture(file)

        manager.flush()

        tex = manager._textures.get(key)
        if tex is None:
            logger.error(f"failed to obtain texture for {key} after flush, fallback to default texture")
            manager._ensure_default_texture()
            tex = manager._textures.get(_DEFAULT_TEXTURE_KEY)
            if tex is None:
                raise RuntimeError(f"failed to obtain default texture for {key}")

        if bind:
            manager.bind(tex, unit)

        return tex

    except Exception as exc:
        logger.exception(f"get_texture failed for {key}: {exc}")
        default = manager._textures.get(_DEFAULT_TEXTURE_KEY)
        if default is None:
            manager._ensure_default_texture()
            default = manager._textures.get(_DEFAULT_TEXTURE_KEY)
        if default is None:
            raise RuntimeError(f"could not load texture '{key}' and could not create default: {exc}") from exc
        if bind:
            manager.bind(default, unit)

        return default
