from pathlib import Path
import zlib
from dataclasses import dataclass
from PIL import Image

from gtools.core.buffer import Buffer


C_RTFILE_TEXTURE_HEADER = b"RTTXTR"
C_RTFILE_PACKAGE_LATEST_VERSION = 0
C_RTFILE_PACKAGE_HEADER = b"RTPACK"
C_RTFILE_PACKAGE_HEADER_BYTE_SIZE = len(C_RTFILE_PACKAGE_HEADER)


@dataclass(slots=True)
class RtPackHeader:
    file_type_id: bytes = b""
    version: int = 0
    _reserved: bytes = b""  # 1
    compressed_size: int = 0
    decompressed_size: int = 0
    compression_type: int = 0
    _reserved2: bytes = b""  # 15

    @classmethod
    def deserialize(cls, s: Buffer) -> "RtPackHeader":
        header = cls()
        header.file_type_id = s.read_bytes(C_RTFILE_PACKAGE_HEADER_BYTE_SIZE)
        header.version = s.read_u8()
        header._reserved = s.read_bytes(1)
        header.compressed_size = s.read_u32()
        header.decompressed_size = s.read_u32()
        header.compression_type = s.read_u8()
        header._reserved2 = s.read_bytes(15)
        return header


@dataclass(slots=True)
class RtTexHeader:
    file_type_id: bytes = b""
    version: int = 0
    _reserved: bytes = b""  # 1
    height: int = 0
    width: int = 0
    format: int = 0
    original_height: int = 0
    original_width: int = 0
    uses_alpha: int = 0
    already_compressed: int = 0
    _reserved_flags: bytes = b""  # 2
    mip_map_count: int = 0
    _reserved3: bytes = b""  # 64

    @classmethod
    def deserialize(cls, s: Buffer) -> "RtTexHeader":
        tex_header = cls()
        tex_header.file_type_id = s.read_bytes(6)
        tex_header.version = s.read_u8()
        tex_header._reserved = s.read_bytes(1)
        tex_header.height = s.read_i32()
        tex_header.width = s.read_i32()
        tex_header.format = s.read_i32()
        tex_header.original_height = s.read_i32()
        tex_header.original_width = s.read_i32()
        tex_header.uses_alpha = s.read_u8()
        tex_header.already_compressed = s.read_u8()
        tex_header._reserved_flags = s.read_bytes(2)
        tex_header.mip_map_count = s.read_i32()
        tex_header._reserved3 = s.read_bytes(64)
        return tex_header


@dataclass(slots=True)
class RtTexMipHeader:
    height: int = 0
    width: int = 0
    data_size: int = 0
    mip_level: int = 0
    _reserved: bytes = b""  # 8

    @classmethod
    def deserialize(cls, s: Buffer) -> "RtTexMipHeader":
        mip_header = cls()
        mip_header.height = s.read_i32()
        mip_header.width = s.read_i32()
        mip_header.data_size = s.read_i32()
        mip_header.mip_level = s.read_i32()
        mip_header._reserved = s.read_bytes(8)
        return mip_header


def get_image_buffer(path: str) -> Image.Image | None:
    with open(path, "rb") as f:
        data = f.read()

    if data.startswith(C_RTFILE_PACKAGE_HEADER):
        s = Buffer(data)
        pack_header = RtPackHeader.deserialize(s)

        if pack_header.version != C_RTFILE_PACKAGE_LATEST_VERSION:
            raise ValueError(f"unsupported package version: {pack_header.version}")

        payload = s.read_bytes(-1)
        if pack_header.compression_type == 1:
            decompressed = zlib.decompress(payload)
        else:
            decompressed = payload

        if decompressed.startswith(C_RTFILE_TEXTURE_HEADER):
            ts = Buffer(decompressed)
            tex_header = RtTexHeader.deserialize(ts)

            for _ in range(tex_header.mip_map_count):
                RtTexMipHeader.deserialize(ts)

            pixel_count = tex_header.width * tex_header.height * 4
            pixel_data = ts.read_bytes(pixel_count)

            img = Image.frombytes("RGBA", (tex_header.width, tex_header.height), pixel_data)
            img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            img = img.rotate(180)
            return img.convert("RGBA")

    return None


class RtTexManager:
    _cache: dict[str, Image.Image] = {}

    def get(self, file: str | Path, x: int, y: int, w: int, h: int) -> Image.Image:
        file = str(file)
        crop = None if (x < 0 or y < 0) else (x, y, x + w, y + h)

        cached = RtTexManager._cache.get(file)
        if cached:
            return cached.crop(crop)

        img = get_image_buffer(file)
        if not img:
            raise ValueError("failed to get texture")
        RtTexManager._cache[file] = img

        return img.crop(crop)
