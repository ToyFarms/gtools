from enum import IntEnum
import io
import logging
from pathlib import Path
import zlib
from dataclasses import dataclass, field
import numpy as np
import numpy.typing as npt
from PIL import Image
import moderngl as mgl

from gtools.core.buffer import Buffer

C_RTFILE_TEXTURE_HEADER = b"RTTXTR"
C_RTFILE_PACKAGE_LATEST_VERSION = 0
C_RTFILE_PACKAGE_HEADER = b"RTPACK"
C_RTFILE_PACKAGE_HEADER_BYTE_SIZE = 6


class RTCompression(IntEnum):
    NONE = 0
    ZLIB = 1


@dataclass(slots=True)
class RTFileHeader:
    file_type_id: bytes = b""  # 6
    version: int = 0  # u8
    _reserved: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer) -> "RTFileHeader":
        header = cls()
        header.file_type_id = s.read_bytes(C_RTFILE_PACKAGE_HEADER_BYTE_SIZE)
        header.version = s.read_u8()
        header._reserved = s.read_u8()

        return header


@dataclass(slots=True)
class RTPackHeader:
    file_header: RTFileHeader = field(default_factory=RTFileHeader)
    compressed_size: int = 0
    decompressed_size: int = 0
    compression_type: RTCompression = RTCompression.NONE
    _reserved2: bytes = b""  # 15

    @classmethod
    def deserialize(cls, s: Buffer) -> "RTPackHeader":
        header = cls()
        header.file_header = RTFileHeader.deserialize(s)
        header.compressed_size = s.read_u32()
        header.decompressed_size = s.read_u32()
        header.compression_type = RTCompression(s.read_u8())
        header._reserved2 = s.read_bytes(15)

        return header


class RTFormat(IntEnum):
    RT_FORMAT_EMBEDDED_FILE = 0
    GL_UNSIGNED_BYTE = 0x1401
    GL_UNSIGNED_SHORT_4_4_4_4 = 0x8033
    GL_UNSIGNED_SHORT_5_6_5 = 0x8363
    GL_COMPRESSED_RGB_PVRTC_4BPPV1_IMG = 0x8C00
    GL_COMPRESSED_RGB_PVRTC_2BPPV1_IMG = 0x8C01
    GL_COMPRESSED_RGBA_PVRTC_4BPPV1_IMG = 0x8C02
    GL_COMPRESSED_RGBA_PVRTC_2BPPV1_IMG = 0x8C03

    def is_pvrtc(self) -> bool:
        return self.value in (
            RTFormat.GL_COMPRESSED_RGB_PVRTC_4BPPV1_IMG,
            RTFormat.GL_COMPRESSED_RGB_PVRTC_2BPPV1_IMG,
            RTFormat.GL_COMPRESSED_RGBA_PVRTC_4BPPV1_IMG,
            RTFormat.GL_COMPRESSED_RGBA_PVRTC_2BPPV1_IMG,
        )


@dataclass(slots=True)
class RTTexHeader:
    file_type_id: bytes = b""
    version: int = 0
    _reserved: bytes = b""  # 1
    height: int = 0
    width: int = 0
    format: RTFormat = RTFormat.GL_UNSIGNED_BYTE
    original_height: int = 0
    original_width: int = 0
    uses_alpha: int = 0
    already_compressed: int = 0
    _reserved_flags: bytes = b""  # 2
    mip_map_count: int = 0
    _reserved3: bytes = b""  # 64

    @classmethod
    def deserialize(cls, s: Buffer) -> "RTTexHeader":
        tex_header = cls()
        tex_header.file_type_id = s.read_bytes(6)
        tex_header.version = s.read_u8()
        tex_header._reserved = s.read_bytes(1)
        tex_header.height = s.read_i32()
        tex_header.width = s.read_i32()
        tex_header.format = RTFormat(s.read_u32())
        tex_header.original_height = s.read_i32()
        tex_header.original_width = s.read_i32()
        tex_header.uses_alpha = s.read_u8()
        tex_header.already_compressed = s.read_u8()
        tex_header._reserved_flags = s.read_bytes(2)
        tex_header.mip_map_count = s.read_i32()
        tex_header._reserved3 = s.read_bytes(64)

        return tex_header


@dataclass(slots=True)
class RTTexMip:
    height: int = 0
    width: int = 0
    data_size: int = 0
    mip_level: int = 0
    _reserved: bytes = b""  # 8
    pixels: npt.NDArray[np.uint8] = field(default_factory=lambda: np.empty((0,), dtype=np.uint8))

    @classmethod
    def deserialize(cls, s: Buffer, header: RTTexHeader) -> "RTTexMip":
        mip = cls()
        mip.height = s.read_i32()
        mip.width = s.read_i32()
        mip.data_size = s.read_i32()
        mip.mip_level = s.read_i32()
        mip._reserved = s.read_bytes(8)

        raw = s.read_bytes(mip.data_size)

        if header.format == RTFormat.GL_UNSIGNED_BYTE:
            expected_size = header.width * header.height * 4
            if mip.data_size != expected_size:
                raise ValueError(f"mip data size mismatch for level {mip.mip_level}: " f"header says {mip.data_size} bytes but expected {expected_size}")

            arr = np.frombuffer(raw, dtype=np.uint8)
            arr = np.ascontiguousarray(arr.reshape((header.height, header.width, 4))[::-1, :, :])
        elif header.format == RTFormat.RT_FORMAT_EMBEDDED_FILE:
            arr = np.asarray(Image.open(io.BytesIO(raw)).convert("RGBA"), dtype=np.uint8)
            arr = np.ascontiguousarray(arr)
        elif header.format == RTFormat.GL_UNSIGNED_SHORT_5_6_5:
            u16 = np.frombuffer(raw, dtype=np.uint16).reshape(header.height, header.width)
            rgba = np.zeros((header.height, header.width, 4), dtype=np.uint8)
            rgba[:, :, 0] = ((u16 >> 11) & 0x1F) * 255 // 31
            rgba[:, :, 1] = ((u16 >> 5) & 0x3F) * 255 // 63
            rgba[:, :, 2] = (u16 & 0x1F) * 255 // 31
            rgba[:, :, 3] = 255
            arr = rgba
        elif header.format == RTFormat.GL_UNSIGNED_SHORT_4_4_4_4:
            u16 = np.frombuffer(raw, dtype=np.uint16).reshape(header.height, header.width)
            rgba = np.zeros((header.height, header.width, 4), dtype=np.uint8)
            rgba[:, :, 0] = ((u16 >> 12) & 0xF) * 255 // 15
            rgba[:, :, 1] = ((u16 >> 8) & 0xF) * 255 // 15
            rgba[:, :, 2] = ((u16 >> 4) & 0xF) * 255 // 15
            rgba[:, :, 3] = (u16 & 0xF) * 255 // 15
            arr = rgba
        else:
            # pvrtc format, leave interpretation to the gpu
            arr = np.frombuffer(raw, dtype=np.uint8)

        mip.pixels = arr

        return mip


@dataclass(slots=True)
class RTTex:
    header: RTTexHeader
    pack_header: RTPackHeader | None = None
    mips: list[RTTexMip] = field(default_factory=list)

    logger = logging.getLogger("rttex")

    @property
    def width(self) -> int:
        return self.header.width

    @property
    def height(self) -> int:
        return self.header.height

    @property
    def format(self) -> RTFormat:
        return self.header.format

    @classmethod
    def from_file(cls, path: str | Path) -> "RTTex":
        with open(path, "rb") as f:
            data = f.read()
        return cls.from_bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> "RTTex":
        source_buf = Buffer(data)
        pack_header = None
        payload: bytes

        if data.startswith(C_RTFILE_PACKAGE_HEADER):
            pack_header = RTPackHeader.deserialize(source_buf)

            if pack_header.file_header.version != C_RTFILE_PACKAGE_LATEST_VERSION:
                raise ValueError(f"unsupported package version: {pack_header.file_header.version}")

            payload = source_buf.read_bytes(-1)
            if pack_header.compression_type == RTCompression.ZLIB:
                try:
                    payload = zlib.decompress(payload)
                except zlib.error as exc:
                    raise ValueError("failed to decompress zlib payload") from exc
        elif data.startswith(C_RTFILE_TEXTURE_HEADER):
            payload = data
            source_buf = Buffer(payload)
        else:
            raise ValueError("input does not appear to be an RTPACK or RTTXTR blob")

        if not payload.startswith(C_RTFILE_TEXTURE_HEADER):
            raise ValueError("payload does not start with RTTXTR header")

        s = Buffer(payload)
        tex_header = RTTexHeader.deserialize(s)

        tex = cls(header=tex_header, pack_header=pack_header)
        for _ in range(tex_header.mip_map_count):
            tex.mips.append(RTTexMip.deserialize(s, tex_header))

        return tex

    def get_mip(self, level: int = 0) -> RTTexMip:
        if level < 0 or level >= len(self.mips):
            raise IndexError("mip level out of range")

        return self.mips[level]

    def crop(self, x: int, y: int, w: int = 32, h: int = 32, *, flip_x: bool = False, level: int = 0) -> npt.NDArray[np.uint8]:
        mip = self.get_mip(level)
        if x < 0 or y < 0 or x + w > mip.width or y + h > mip.height:
            raise ValueError(f"crop ({x},{y},{w},{h}) out of bounds for mip {level} ({mip.width}x{mip.height})")

        cropped = mip.pixels[y : y + h, x : x + w, :]
        if flip_x:
            cropped = cropped[:, ::-1, :]
        return np.ascontiguousarray(cropped)

    def to_pil(self, level: int = 0) -> Image.Image:
        return Image.fromarray(self.get_mip(level).pixels, mode="RGBA")

    def save_png(self, out_path: str, level: int = 0) -> None:
        pil = self.to_pil(level)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        pil.save(out_path, format="PNG")

    def gl_upload(self) -> mgl.Texture:
        ctx = mgl.get_context()

        if not self.mips:
            raise ValueError("invalid or unloaded texture")

        base = self.mips[0]

        if self.format.is_pvrtc():
            self.logger.warning("pvrtc format is not supported")
            tex = ctx.texture(
                (base.width, base.height),
                4,
                data=base.pixels,
                internal_format=self.format.value,
            )
        else:
            tex = ctx.texture(
                (base.width, base.height),
                4,
                data=base.pixels,
                dtype="u1",
            )

        for mip in self.mips[1:]:
            tex.write(mip.pixels.tobytes(), level=mip.mip_level)

        if len(self.mips) == 1:
            tex.build_mipmaps()

        return tex

    def __repr__(self) -> str:
        return f"<RTTex v{self.header.version} {self.width}x{self.height} format={self.format.name} mips={len(self.mips)}>"


# TODO: need to change this
class RTTexManager:
    _atlas_cache: dict[str, npt.NDArray[np.uint8]] = {}
    _tex_cache: dict[tuple[str, int, int, int, int, bool], npt.NDArray[np.uint8]] = {}

    def get(
        self,
        file: str | Path,
        x: int,
        y: int,
        w: int,
        h: int,
        flip_x: bool = False,
    ) -> npt.NDArray[np.uint8]:
        file = str(file)

        key = (file, x, y, w, h, flip_x)
        if key in self._tex_cache:
            return self._tex_cache[key]

        cached = RTTexManager._atlas_cache.get(file)
        if cached is None:
            rtex = RTTex.from_file(file)
            if not rtex.mips:
                raise ValueError("texture has no mip levels")

            cached = rtex.get_mip(0).pixels
            RTTexManager._atlas_cache[file] = cached

        if x < 0 or y < 0 or x + w > cached.shape[1] or y + h > cached.shape[0]:
            raise ValueError(f"crop ({x},{y},{w},{h}) out of bounds for texture {file} " f"({cached.shape[1]}x{cached.shape[0]})")

        cropped = cached[y : y + h, x : x + w, :]

        if flip_x:
            cropped = cropped[:, ::-1, :]

        cropped = np.ascontiguousarray(cropped)
        self._tex_cache[key] = cropped
        return cropped


if __name__ == "__main__":
    from PIL import Image
    from sys import argv

    RTTex.from_file(argv[1]).to_pil().show()
