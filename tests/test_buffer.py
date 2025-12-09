import pytest

from gtools.core.buffer import Buffer
from tests import verify


def test_init_empty() -> None:
    buf = Buffer()
    assert len(buf) == 0
    assert buf.rpos == 0
    assert buf.wpos == 0
    assert buf.endian == "<"
    verify(buf.serialize())


def test_init_with_data() -> None:
    data = b"\x01\x02\x03\x04"
    buf = Buffer(data)
    assert len(buf) == 4
    assert buf.rpos == 0
    assert buf.wpos == 4
    verify(buf.serialize())


def test_init_with_bytearray() -> None:
    data = bytearray([0x10, 0x20, 0x30])
    buf = Buffer(data)
    assert len(buf) == 3
    verify(buf.serialize())


def test_init_invalid_endian() -> None:
    with pytest.raises(ValueError, match="endian must be"):
        Buffer(endian="@")


def test_endian_little() -> None:
    buf = Buffer(endian="<")
    buf.write_u16(0x1234)
    assert buf.serialize() == b"\x34\x12"
    verify(buf.serialize())


def test_endian_big() -> None:
    buf = Buffer(endian=">")
    buf.write_u16(0x1234)
    assert buf.serialize() == b"\x12\x34"
    verify(buf.serialize())


def test_endian_native() -> None:
    buf = Buffer(endian="=")
    buf.write_u16(0x1234)
    verify(buf.serialize())


def test_write_u8() -> None:
    buf = Buffer()
    buf.write_u8(0xFF)
    assert buf.serialize() == b"\xff"
    verify(buf.serialize())


def test_write_i8_positive() -> None:
    buf = Buffer()
    buf.write_i8(127)
    assert buf.serialize() == b"\x7f"
    verify(buf.serialize())


def test_write_i8_negative() -> None:
    buf = Buffer()
    buf.write_i8(-1)
    assert buf.serialize() == b"\xff"
    verify(buf.serialize())


def test_write_u16() -> None:
    buf = Buffer()
    buf.write_u16(0x1234)
    verify(buf.serialize())


def test_write_i16() -> None:
    buf = Buffer()
    buf.write_i16(-1000)
    verify(buf.serialize())


def test_write_u32() -> None:
    buf = Buffer()
    buf.write_u32(0x12345678)
    verify(buf.serialize())


def test_write_i32() -> None:
    buf = Buffer()
    buf.write_i32(-123456)
    verify(buf.serialize())


def test_write_u64() -> None:
    buf = Buffer()
    buf.write_u64(0x123456789ABCDEF0)
    verify(buf.serialize())


def test_write_i64() -> None:
    buf = Buffer()
    buf.write_i64(-9876543210)
    verify(buf.serialize())


def test_write_f32() -> None:
    buf = Buffer()
    buf.write_f32(3.14159)
    verify(buf.serialize())


def test_write_f64() -> None:
    buf = Buffer()
    buf.write_f64(3.141592653589793)
    verify(buf.serialize())


def test_write_bool_true() -> None:
    buf = Buffer()
    buf.write_bool(True)
    assert buf.serialize() == b"\x01"
    verify(buf.serialize())


def test_write_bool_false() -> None:
    buf = Buffer()
    buf.write_bool(False)
    assert buf.serialize() == b"\x00"
    verify(buf.serialize())


def test_read_u8() -> None:
    buf = Buffer(b"\xff")
    val = buf.read_u8()
    assert val == 255
    verify(str(val))


def test_read_i8_positive() -> None:
    buf = Buffer(b"\x7f")
    val = buf.read_i8()
    assert val == 127
    verify(str(val))


def test_read_i8_negative() -> None:
    buf = Buffer(b"\xff")
    val = buf.read_i8()
    assert val == -1
    verify(str(val))


def test_read_u16() -> None:
    buf = Buffer(b"\x34\x12")
    val = buf.read_u16()
    assert val == 0x1234
    verify(str(val))


def test_read_i16() -> None:
    buf = Buffer(b"\x18\xfc")
    val = buf.read_i16()
    assert val == -1000
    verify(str(val))


def test_read_u32() -> None:
    buf = Buffer(b"\x78\x56\x34\x12")
    val = buf.read_u32()
    assert val == 0x12345678
    verify(str(val))


def test_read_i32() -> None:
    buf = Buffer(b"\xc0\x1d\xfe\xff")
    val = buf.read_i32()
    assert val == -123456
    verify(str(val))


def test_read_u64() -> None:
    buf = Buffer(b"\xf0\xde\xbc\x9a\x78\x56\x34\x12")
    val = buf.read_u64()
    assert val == 0x123456789ABCDEF0
    verify(str(val))


def test_read_i64() -> None:
    buf = Buffer(b"\x36\x24\x8a\xb6\xfd\xff\xff\xff")
    val = buf.read_i64()
    assert val == -9822395338
    verify(str(val))


def test_read_f32() -> None:
    buf = Buffer()
    buf.write_f32(3.14159)
    buf.seek_read(0)
    val = buf.read_f32()
    assert abs(val - 3.14159) < 0.0001
    verify(str(val))


def test_read_f64() -> None:
    buf = Buffer()
    buf.write_f64(3.141592653589793)
    buf.seek_read(0)
    val = buf.read_f64()
    assert abs(val - 3.141592653589793) < 1e-10
    verify(str(val))


def test_read_bool() -> None:
    buf = Buffer(b"\x01\x00")
    assert buf.read_bool() is True
    assert buf.read_bool() is False
    verify("True, False")


def test_read_eof() -> None:
    buf = Buffer(b"\x01")
    buf.read_u8()
    with pytest.raises(EOFError, match="Attempt to read"):
        buf.read_u8()


def test_read_partial_eof() -> None:
    buf = Buffer(b"\x01\x02")
    with pytest.raises(EOFError):
        buf.read_u32()


def test_write_bytes() -> None:
    buf = Buffer()
    buf.write_bytes(b"\x01\x02\x03")
    assert buf.serialize() == b"\x01\x02\x03"
    verify(buf.serialize())


def test_write_bytes_bytearray() -> None:
    buf = Buffer()
    buf.write_bytes(bytearray([0x0A, 0x0B, 0x0C]))
    assert buf.serialize() == b"\x0a\x0b\x0c"
    verify(buf.serialize())


def test_read_bytes() -> None:
    buf = Buffer(b"\x01\x02\x03\x04\x05")
    data = buf.read_bytes(3)
    assert data == b"\x01\x02\x03"
    assert buf.rpos == 3
    verify(repr(data))


def test_read_bytes_eof() -> None:
    buf = Buffer(b"\x01\x02")
    with pytest.raises(EOFError):
        buf.read_bytes(5)


def test_peek() -> None:
    buf = Buffer(b"\x01\x02\x03\x04")
    data = buf.peek(2)
    assert data == b"\x01\x02"
    assert buf.rpos == 0
    verify(repr(data))


def test_peek_beyond_end() -> None:
    buf = Buffer(b"\x01\x02")
    data = buf.peek(10)
    assert data == b"\x01\x02"
    verify(repr(data))


def test_read_cstring() -> None:
    buf = Buffer(b"hello\x00world")
    s = buf.read_cstring()
    assert s == b"hello"
    assert buf.rpos == 6
    verify(repr(s))


def test_read_cstring_not_terminated() -> None:
    buf = Buffer(b"hello")
    with pytest.raises(EOFError, match="C-string not terminated"):
        buf.read_cstring()


def test_read_cstring_empty() -> None:
    buf = Buffer(b"\x00data")
    s = buf.read_cstring()
    assert s == b""
    verify(repr(s))


def test_write_cstring_str() -> None:
    buf = Buffer()
    buf.write_cstring("hello")
    assert buf.serialize() == b"hello\x00"
    verify(buf.serialize())


def test_write_cstring_bytes() -> None:
    buf = Buffer()
    buf.write_cstring(b"world")
    assert buf.serialize() == b"world\x00"
    verify(buf.serialize())


def test_read_string() -> None:
    buf = Buffer(b"hello")
    s = buf.read_string(5)
    assert s == "hello"
    verify(repr(s))


def test_read_string_utf8() -> None:
    buf = Buffer("こんにちは".encode("utf-8"))
    s = buf.read_string(15, "utf-8")
    assert s == "こんにちは"
    verify(repr(s))


def test_write_string() -> None:
    buf = Buffer()
    buf.write_string("test")
    assert buf.serialize() == b"test"
    verify(buf.serialize())


def test_write_string_utf8() -> None:
    buf = Buffer()
    buf.write_string("こんにちは", "utf-8")
    verify(buf.serialize())


def test_read_pascal_string() -> None:
    buf = Buffer(b"\x05hello")
    s = buf.read_pascal_string()
    assert s == "hello"
    verify(repr(s))


def test_read_pascal_string_u16_prefix() -> None:
    buf = Buffer(b"\x05\x00hello")
    s = buf.read_pascal_string(prefix_fmt="H")
    assert s == "hello"
    verify(repr(s))


def test_write_pascal_string() -> None:
    buf = Buffer()
    buf.write_pascal_string("test")
    assert buf.serialize() == b"\x04test"
    verify(buf.serialize())


def test_write_pascal_string_u16_prefix() -> None:
    buf = Buffer()
    buf.write_pascal_string("test", prefix_fmt="H")
    verify(buf.serialize())


def test_read_pascal_bytes() -> None:
    buf = Buffer(b"\x03\x01\x02\x03")
    data = buf.read_pascal_bytes()
    assert data == b"\x01\x02\x03"
    verify(repr(data))


def test_write_pascal_bytes() -> None:
    buf = Buffer()
    buf.write_pascal_bytes(b"\x0a\x0b\x0c")
    assert buf.serialize() == b"\x03\x0a\x0b\x0c"
    verify(buf.serialize())


def test_seek_read_absolute() -> None:
    buf = Buffer(b"\x01\x02\x03\x04")
    buf.seek_read(2, 0)
    assert buf.rpos == 2
    verify(str(buf.rpos))


def test_seek_read_relative() -> None:
    buf = Buffer(b"\x01\x02\x03\x04")
    buf.read_u8()
    buf.seek_read(1, 1)
    assert buf.rpos == 2
    verify(str(buf.rpos))


def test_seek_read_from_end() -> None:
    buf = Buffer(b"\x01\x02\x03\x04")
    buf.seek_read(-2, 2)
    assert buf.rpos == 2
    verify(str(buf.rpos))


def test_seek_read_invalid_whence() -> None:
    buf = Buffer(b"\x01\x02")
    with pytest.raises(ValueError, match="invalid whence"):
        buf.seek_read(0, 5)


def test_seek_read_negative() -> None:
    buf = Buffer(b"\x01\x02")
    with pytest.raises(ValueError, match="negative seek"):
        buf.seek_read(-1, 0)


def test_seek_write_absolute() -> None:
    buf = Buffer()
    buf.write_u32(0x12345678)
    buf.seek_write(2, 0)
    assert buf.wpos == 2
    verify(str(buf.wpos))


def test_seek_write_relative() -> None:
    buf = Buffer()
    buf.write_u16(0x1234)
    buf.seek_write(-1, 1)
    assert buf.wpos == 1
    verify(str(buf.wpos))


def test_seek_write_from_end() -> None:
    buf = Buffer(b"\x01\x02\x03\x04")
    buf.seek_write(-2, 2)
    assert buf.wpos == 2
    verify(str(buf.wpos))


def test_seek_write_invalid_whence() -> None:
    buf = Buffer()
    with pytest.raises(ValueError, match="invalid whence"):
        buf.seek_write(0, 3)


def test_seek_write_negative() -> None:
    buf = Buffer()
    with pytest.raises(ValueError, match="negative seek"):
        buf.seek_write(-5, 0)


def test_tell_read() -> None:
    buf = Buffer(b"\x01\x02\x03")
    buf.read_u8()
    assert buf.tell_read() == 1
    verify(str(buf.tell_read()))


def test_tell_write() -> None:
    buf = Buffer()
    buf.write_u16(0x1234)
    assert buf.tell_write() == 2
    verify(str(buf.tell_write()))


def test_remaining() -> None:
    buf = Buffer(b"\x01\x02\x03\x04\x05")
    buf.read_u8()
    buf.read_u8()
    assert buf.remaining() == 3
    verify(str(buf.remaining()))


def test_remaining_empty() -> None:
    buf = Buffer(b"\x01")
    buf.read_u8()
    assert buf.remaining() == 0
    verify(str(buf.remaining()))


def test_remaining_beyond_end() -> None:
    buf = Buffer(b"\x01\x02")
    buf.seek_read(10)
    assert buf.remaining() == 0
    verify(str(buf.remaining()))


def test_getvalue() -> None:
    buf = Buffer(b"\x01\x02\x03")
    assert buf.getvalue() == b"\x01\x02\x03"
    verify(repr(buf.getvalue()))


def test_truncate_default() -> None:
    buf = Buffer()
    buf.write_u32(0x12345678)
    buf.seek_write(2)
    buf.truncate()
    assert len(buf) == 2
    verify(buf.serialize())


def test_truncate_explicit() -> None:
    buf = Buffer(b"\x01\x02\x03\x04\x05")
    buf.truncate(3)
    assert len(buf) == 3
    assert buf.serialize() == b"\x01\x02\x03"
    verify(buf.serialize())


def test_truncate_adjusts_rpos() -> None:
    buf = Buffer(b"\x01\x02\x03\x04")
    buf.seek_read(3)
    buf.truncate(2)
    assert buf.rpos == 2
    verify(str(buf.rpos))


def test_truncate_adjusts_wpos() -> None:
    buf = Buffer(b"\x01\x02\x03\x04")
    buf.seek_write(3)
    buf.truncate(2)
    assert buf.wpos == 2
    verify(str(buf.wpos))


def test_truncate_negative() -> None:
    buf = Buffer(b"\x01\x02")
    with pytest.raises(ValueError, match="negative length"):
        buf.truncate(-1)


def test_clear() -> None:
    buf = Buffer(b"\x01\x02\x03")
    buf.read_u8()
    buf.clear()
    assert len(buf) == 0
    assert buf.rpos == 0
    assert buf.wpos == 0
    verify(buf.serialize())


def test_len() -> None:
    buf = Buffer(b"\x01\x02\x03\x04")
    assert len(buf) == 4
    verify(str(len(buf)))


def test_multiple_writes() -> None:
    buf = Buffer()
    buf.write_u8(0x01)
    buf.write_u16(0x0203)
    buf.write_u32(0x04050607)
    verify(buf.serialize())


def test_multiple_reads() -> None:
    buf = Buffer(b"\x01\x02\x03\x04\x05\x06\x07")
    v1 = buf.read_u8()
    v2 = buf.read_u16()
    v3 = buf.read_u32()
    assert v1 == 0x01
    assert v2 == 0x0302
    assert v3 == 0x07060504
    verify(f"{v1}, {v2}, {v3}")


def test_interleaved_read_write() -> None:
    buf = Buffer()
    buf.write_u8(0x01)
    buf.write_u8(0x02)
    buf.seek_read(0)
    v1 = buf.read_u8()
    buf.write_u8(0x03)
    buf.seek_read(1)
    v2 = buf.read_u8()
    verify(f"{v1}, {v2}, {buf.serialize()}")


def test_overwrite_data() -> None:
    buf = Buffer()
    buf.write_u32(0xFFFFFFFF)
    buf.seek_write(0)
    buf.write_u32(0x12345678)
    assert buf.serialize() == b"\x78\x56\x34\x12"
    verify(buf.serialize())


def test_write_beyond_buffer() -> None:
    buf = Buffer(b"\x01\x02")
    buf.seek_write(5)
    buf.write_u8(0xFF)
    assert len(buf) == 6
    assert buf.buffer[2:5] == b"\x00\x00\x00"
    verify(buf.serialize())


def test_read_fmt_multiple_values() -> None:
    buf = Buffer(b"\x01\x02\x03\x04")
    val = buf.read_fmt("I")
    verify(str(val))


def test_write_fmt_multiple_values() -> None:
    buf = Buffer()
    buf.write_fmt("HH", 0x1234, 0x5678)
    verify(buf.serialize())


def test_edge_case_zero_length_read() -> None:
    buf = Buffer(b"\x01\x02\x03")
    data = buf.read_bytes(0)
    assert data == b""
    assert buf.rpos == 0
    verify(repr(data))


def test_edge_case_zero_length_write() -> None:
    buf = Buffer()
    buf.write_bytes(b"")
    assert len(buf) == 0
    verify(buf.serialize())


def test_boundary_u8_max() -> None:
    buf = Buffer()
    buf.write_u8(255)
    buf.seek_read(0)
    assert buf.read_u8() == 255
    verify("255")


def test_boundary_i8_min_max() -> None:
    buf = Buffer()
    buf.write_i8(-128)
    buf.write_i8(127)
    buf.seek_read(0)
    assert buf.read_i8() == -128
    assert buf.read_i8() == 127
    verify("-128, 127")


def test_boundary_u64_max() -> None:
    buf = Buffer()
    buf.write_u64(0xFFFFFFFFFFFFFFFF)
    buf.seek_read(0)
    assert buf.read_u64() == 0xFFFFFFFFFFFFFFFF
    verify(str(0xFFFFFFFFFFFFFFFF))


def test_state_corruption_read_past_write() -> None:
    buf = Buffer()
    buf.write_u8(0x01)
    buf.seek_read(0)
    buf.read_u8()
    with pytest.raises(EOFError):
        buf.read_u8()


def test_complex_scenario() -> None:
    buf = Buffer()
    buf.write_pascal_string("header")
    buf.write_u32(12345)
    buf.write_cstring("metadata")
    buf.write_bool(True)

    buf.seek_read(0)
    header = buf.read_pascal_string()
    num = buf.read_u32()
    meta = buf.read_cstring()
    flag = buf.read_bool()

    assert header == "header"
    assert num == 12345
    assert meta == b"metadata"
    assert flag is True
    verify(f"{header}, {num}, {meta}, {flag}")
