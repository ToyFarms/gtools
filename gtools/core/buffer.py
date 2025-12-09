import struct

BytesLike = bytes | bytearray


class Buffer:
    def __init__(self, data: BytesLike | None = None, endian: str = "<") -> None:
        if endian not in ("<", ">", "="):
            raise ValueError("endian must be '<', '>' or '='")

        self.buffer = bytearray(data) if data is not None else bytearray()
        self.rpos = 0
        self.wpos = len(self.buffer)
        self.endian = endian

    def serialize(self) -> bytes:
        return bytes(self.buffer)

    def _ensure_capacity(self, size: int) -> None:
        if size <= len(self.buffer):
            return
        self.buffer.extend(b"\x00" * (size - len(self.buffer)))

    def _read_raw(self, n: int) -> bytes:
        if self.rpos + n > len(self.buffer):
            raise EOFError(
                f"Attempt to read {n} bytes beyond end (rpos={self.rpos}, len={len(self.buffer)})"
            )

        data = bytes(self.buffer[self.rpos : self.rpos + n])
        self.rpos += n

        return data

    def _write_raw(self, b: BytesLike) -> None:
        end = self.wpos + len(b)
        self._ensure_capacity(end)
        self.buffer[self.wpos : end] = b
        self.wpos = end

    def read_fmt(self, fmt: str) -> int:
        full_fmt = self.endian + fmt
        size = struct.calcsize(full_fmt)
        raw = self._read_raw(size)
        vals = struct.unpack(full_fmt, raw)

        return vals[0]

    def write_fmt(self, fmt: str, *vals) -> None:
        full_fmt = self.endian + fmt
        packed = struct.pack(full_fmt, *vals)
        self._write_raw(packed)

    def read_u8(self) -> int:
        return self.read_fmt("B")

    def read_i8(self) -> int:
        return self.read_fmt("b")

    def read_u16(self) -> int:
        return self.read_fmt("H")

    def read_i16(self) -> int:
        return self.read_fmt("h")

    def read_u32(self) -> int:
        return self.read_fmt("I")

    def read_i32(self) -> int:
        return self.read_fmt("i")

    def read_u64(self) -> int:
        return self.read_fmt("Q")

    def read_i64(self) -> int:
        return self.read_fmt("q")

    def read_f32(self) -> int:
        return self.read_fmt("f")

    def read_f64(self) -> int:
        return self.read_fmt("d")

    def read_bool(self) -> int:
        return self.read_fmt("?")

    def write_u8(self, v: int) -> None:
        self.write_fmt("B", v)

    def write_i8(self, v: int) -> None:
        self.write_fmt("b", v)

    def write_u16(self, v: int) -> None:
        self.write_fmt("H", v)

    def write_i16(self, v: int) -> None:
        self.write_fmt("h", v)

    def write_u32(self, v: int) -> None:
        self.write_fmt("I", v)

    def write_i32(self, v: int) -> None:
        self.write_fmt("i", v)

    def write_u64(self, v: int) -> None:
        self.write_fmt("Q", v)

    def write_i64(self, v: int) -> None:
        self.write_fmt("q", v)

    def write_f32(self, v: float) -> None:
        self.write_fmt("f", v)

    def write_f64(self, v: float) -> None:
        self.write_fmt("d", v)

    def write_bool(self, v: bool) -> None:
        self.write_fmt("?", v)

    def read_bytes(self, n: int) -> bytes:
        return self._read_raw(n)

    def write_bytes(self, b: BytesLike) -> None:
        self._write_raw(bytes(b))

    def peek(self, n: int) -> bytes:
        end = min(self.rpos + n, len(self.buffer))
        return bytes(self.buffer[self.rpos : end])

    def read_cstring(self) -> bytes:
        start = self.rpos
        while self.rpos < len(self.buffer):
            if self.buffer[self.rpos] == 0:
                res = bytes(self.buffer[start : self.rpos])
                self.rpos += 1  # skip NUL
                return res

            self.rpos += 1

        raise EOFError("C-string not terminated before EOF")

    def write_cstring(self, s: str | bytes) -> None:
        b = s.encode() if isinstance(s, str) else s
        self._write_raw(b + b"\x00")

    def read_string(self, n: int, encoding: str = "utf-8") -> str:
        return self.read_bytes(n).decode(encoding)

    def write_string(self, s: str, encoding: str = "utf-8") -> None:
        self.write_bytes(s.encode(encoding))

    def read_pascal_string(self, prefix_fmt: str = "B", encoding: str = "utf-8") -> str:
        length = self.read_fmt(prefix_fmt)
        return self.read_string(length, encoding)

    def write_pascal_string(
        self, s: str, prefix_fmt: str = "B", encoding: str = "utf-8"
    ) -> None:
        b = s.encode(encoding)
        self.write_fmt(prefix_fmt, len(b))
        self.write_bytes(b)

    def read_pascal_bytes(self, prefix_fmt: str = "B") -> bytes:
        length = self.read_fmt(prefix_fmt)
        return self.read_bytes(length)

    def write_pascal_bytes(self, b: bytes, prefix_fmt: str = "B") -> None:
        self.write_fmt(prefix_fmt, len(b))
        self.write_bytes(b)

    def seek_read(self, offset: int, whence: int = 0):
        if whence == 0:
            new = offset
        elif whence == 1:
            new = self.rpos + offset
        elif whence == 2:
            new = len(self.buffer) + offset
        else:
            raise ValueError("invalid whence")
        if new < 0:
            raise ValueError("negative seek")
        self.rpos = new
        return self.rpos

    def seek_write(self, offset: int, whence: int = 0):
        if whence == 0:
            new = offset
        elif whence == 1:
            new = self.wpos + offset
        elif whence == 2:
            new = len(self.buffer) + offset
        else:
            raise ValueError("invalid whence")
        if new < 0:
            raise ValueError("negative seek")
        self.wpos = new
        return self.wpos

    def tell_read(self) -> int:
        return self.rpos

    def tell_write(self) -> int:
        return self.wpos

    def remaining(self) -> int:
        return max(0, len(self.buffer) - self.rpos)

    def getvalue(self) -> bytes:
        return bytes(self.buffer)

    def truncate(self, new_len: int | None = None):
        if new_len is None:
            new_len = self.wpos
        if new_len < 0:
            raise ValueError("negative length")
        del self.buffer[new_len:]

        if self.rpos > new_len:
            self.rpos = new_len
        if self.wpos > new_len:
            self.wpos = new_len

    def clear(self):
        self.buffer.clear()
        self.rpos = 0
        self.wpos = 0

    def __len__(self):
        return len(self.buffer)

