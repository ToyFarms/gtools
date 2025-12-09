import struct
import pytest
from gtools.core.growtopia.variant import Kind, Variant
from tests import verify


def test_empty_variant() -> None:
    v = Variant()
    assert len(v) == 0
    verify(repr(v))


def test_variant_with_initial_values() -> None:
    v = Variant([Variant.vfloat(3.14), Variant.vstr(b"hello"), Variant.vuint(42)])
    assert len(v) == 3
    verify(repr(v))


def test_vfloat_default() -> None:
    v = Variant.vfloat()
    assert v.value == 0.0
    assert v.kind == Kind.FLOAT
    verify(repr(v))


def test_vfloat_with_value() -> None:
    v = Variant.vfloat(3.14159)
    assert v.value == 3.14159
    verify(repr(v))


def test_vstr_default() -> None:
    v = Variant.vstr()
    assert v.value == b""
    assert v.kind == Kind.STRING
    verify(repr(v))


def test_vstr_with_value() -> None:
    v = Variant.vstr(b"Hello, World!")
    assert v.value == b"Hello, World!"
    verify(repr(v))


def test_vvec2_default() -> None:
    v = Variant.vvec2()
    assert v.value == (0.0, 0.0)
    assert v.kind == Kind.VEC2
    verify(repr(v))


def test_vvec2_with_value() -> None:
    v = Variant.vvec2((1.5, 2.5))
    assert v.value == (1.5, 2.5)
    verify(repr(v))


def test_vvec3_default() -> None:
    v = Variant.vvec3()
    assert v.value == (0.0, 0.0, 0.0)
    assert v.kind == Kind.VEC3
    verify(repr(v))


def test_vvec3_with_value() -> None:
    v = Variant.vvec3((1.0, 2.0, 3.0))
    assert v.value == (1.0, 2.0, 3.0)
    verify(repr(v))


def test_vuint_default() -> None:
    v = Variant.vuint()
    assert v.value == 0
    assert v.kind == Kind.UNSIGNED
    verify(repr(v))


def test_vuint_with_value() -> None:
    v = Variant.vuint(12345)
    assert v.value == 12345
    verify(repr(v))


def test_vint_default() -> None:
    v = Variant.vint()
    assert v.value == 0
    assert v.kind == Kind.SIGNED
    verify(repr(v))


def test_vint_with_value() -> None:
    v = Variant.vint(-12345)
    assert v.value == -12345
    verify(repr(v))


def test_append_single_value() -> None:
    v = Variant()
    v.append(Variant.vfloat(1.5))
    assert len(v) == 1
    assert v[0].value == 1.5
    verify(repr(v))


def test_append_multiple_values() -> None:
    v = Variant()
    v.append(Variant.vfloat(1.5))
    v.append(Variant.vstr(b"test"))
    v.append(Variant.vuint(100))
    assert len(v) == 3
    verify(repr(v))


def test_pop_last() -> None:
    v = Variant([Variant.vfloat(1.0), Variant.vstr(b"hello"), Variant.vuint(42)])
    popped = v.pop()
    assert isinstance(popped, Variant.vuint)
    assert popped.value == 42
    assert len(v) == 2
    verify(repr(v))


def test_pop_specific_index() -> None:
    v = Variant([Variant.vfloat(1.0), Variant.vstr(b"hello"), Variant.vuint(42)])
    popped = v.pop(1)
    assert isinstance(popped, Variant.vstr)
    assert popped.value == b"hello"
    assert len(v) == 2
    verify(repr(v))


def test_pop_empty_variant() -> None:
    v = Variant()
    with pytest.raises(IndexError):
        v.pop()


def test_getitem_valid_index() -> None:
    v = Variant([Variant.vfloat(1.0), Variant.vstr(b"test")])
    assert v[0].value == 1.0
    assert v[1].value == b"test"


def test_getitem_negative_index() -> None:
    v = Variant([Variant.vfloat(1.0), Variant.vstr(b"test")])
    assert v[-1].value == b"test"
    assert v[-2].value == 1.0


def test_getitem_out_of_range() -> None:
    v = Variant([Variant.vfloat(1.0)])
    with pytest.raises(IndexError):
        _ = v[5]


def test_setitem_valid_index() -> None:
    v = Variant([Variant.vfloat(1.0)])
    v[0] = Variant.vstr(b"replaced")
    assert v[0].value == b"replaced"
    verify(repr(v))


def test_setitem_out_of_range() -> None:
    v = Variant([Variant.vfloat(1.0)])
    with pytest.raises(IndexError):
        v[5] = Variant.vstr(b"test")


def test_as_float_single_element() -> None:
    v = Variant([Variant.vfloat(3.14)])
    assert v.as_float[0] == 3.14


def test_as_float_multiple_elements() -> None:
    v = Variant([Variant.vfloat(1.0), Variant.vfloat(2.0), Variant.vfloat(3.0)])
    assert v.as_float[0] == 1.0
    assert v.as_float[1] == 2.0
    assert v.as_float[2] == 3.0


def test_as_float_slice() -> None:
    v = Variant([Variant.vfloat(1.0), Variant.vfloat(2.0), Variant.vfloat(3.0)])
    result = v.as_float[0:2]
    assert result == [1.0, 2.0]


def test_as_float_wrong_kind() -> None:
    v = Variant([Variant.vstr(b"not a float")])
    with pytest.raises(TypeError, match="element at index 0 is"):
        _ = v.as_float[0]


def test_as_float_mixed_types_slice() -> None:
    v = Variant([Variant.vfloat(1.0), Variant.vstr(b"string"), Variant.vfloat(2.0)])
    with pytest.raises(TypeError, match="element kind"):
        _ = v.as_float[0:3]


def test_as_string_single_element() -> None:
    v = Variant([Variant.vstr(b"hello")])
    assert v.as_string[0] == b"hello"


def test_as_string_slice() -> None:
    v = Variant([Variant.vstr(b"one"), Variant.vstr(b"two"), Variant.vstr(b"three")])
    result = v.as_string[0:2]
    assert result == [b"one", b"two"]


def test_as_string_wrong_kind() -> None:
    v = Variant([Variant.vfloat(3.14)])
    with pytest.raises(TypeError):
        _ = v.as_string[0]


def test_as_vec2_single_element() -> None:
    v = Variant([Variant.vvec2((1.5, 2.5))])
    assert v.as_vec2[0] == (1.5, 2.5)


def test_as_vec2_slice() -> None:
    v = Variant([Variant.vvec2((1.0, 2.0)), Variant.vvec2((3.0, 4.0))])
    result = v.as_vec2[:]
    assert result == [(1.0, 2.0), (3.0, 4.0)]


def test_as_vec2_wrong_kind() -> None:
    v = Variant([Variant.vvec3((1.0, 2.0, 3.0))])
    with pytest.raises(TypeError):
        _ = v.as_vec2[0]


def test_as_vec3_single_element() -> None:
    v = Variant([Variant.vvec3((1.0, 2.0, 3.0))])
    assert v.as_vec3[0] == (1.0, 2.0, 3.0)


def test_as_vec3_slice() -> None:
    v = Variant([Variant.vvec3((1.0, 2.0, 3.0)), Variant.vvec3((4.0, 5.0, 6.0))])
    result = v.as_vec3[0:2]
    assert result == [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]


def test_as_uint_single_element() -> None:
    v = Variant([Variant.vuint(12345)])
    assert v.as_uint[0] == 12345


def test_as_uint_slice() -> None:
    v = Variant([Variant.vuint(10), Variant.vuint(20), Variant.vuint(30)])
    result = v.as_uint[:]
    assert result == [10, 20, 30]


def test_as_uint_wrong_kind() -> None:
    v = Variant([Variant.vint(-5)])
    with pytest.raises(TypeError):
        _ = v.as_uint[0]


def test_as_int_single_element() -> None:
    v = Variant([Variant.vint(-12345)])
    assert v.as_int[0] == -12345


def test_as_int_slice() -> None:
    v = Variant([Variant.vint(-10), Variant.vint(0), Variant.vint(10)])
    result = v.as_int[:]
    assert result == [-10, 0, 10]


def test_view_invalid_index_type() -> None:
    v = Variant([Variant.vfloat(1.0)])
    with pytest.raises(TypeError, match="invalid index"):
        _ = v.as_float["invalid"]  # pyright: ignore


def test_view_len() -> None:
    v = Variant([Variant.vfloat(1.0), Variant.vfloat(2.0)])
    assert len(v.as_float) == 2


def test_serialize_empty() -> None:
    v = Variant()
    data = v.serialize()
    assert len(data) == 1
    assert data[0] == 0
    verify(data.hex())


def test_serialize_single_float() -> None:
    v = Variant([Variant.vfloat(3.14)])
    data = v.serialize()
    verify(data.hex())


def test_serialize_single_string() -> None:
    v = Variant([Variant.vstr(b"hello")])
    data = v.serialize()
    verify(data.hex())


def test_serialize_single_vec2() -> None:
    v = Variant([Variant.vvec2((1.5, 2.5))])
    data = v.serialize()
    verify(data.hex())


def test_serialize_single_vec3() -> None:
    v = Variant([Variant.vvec3((1.0, 2.0, 3.0))])
    data = v.serialize()
    verify(data.hex())


def test_serialize_single_uint() -> None:
    v = Variant([Variant.vuint(12345)])
    data = v.serialize()
    verify(data.hex())


def test_serialize_single_int() -> None:
    v = Variant([Variant.vint(-12345)])
    data = v.serialize()
    verify(data.hex())


def test_serialize_mixed_types() -> None:
    v = Variant([Variant.vfloat(3.14), Variant.vstr(b"test"), Variant.vvec2((1.0, 2.0)), Variant.vvec3((1.0, 2.0, 3.0)), Variant.vuint(100), Variant.vint(-50)])
    data = v.serialize()
    verify(data.hex())


def test_serialize_large_string() -> None:
    v = Variant([Variant.vstr(b"x" * 1000)])
    data = v.serialize()
    assert len(data) > 1000


def test_serialize_max_index_overflow() -> None:
    values: list[Variant.Type] = [Variant.vfloat(float(i)) for i in range(260)]
    v = Variant(values)
    with pytest.raises(struct.error):
        v.serialize()


def test_deserialize_empty() -> None:
    data = bytes([0])
    v = Variant.deserialize(data)
    assert len(v) == 0
    verify(repr(v))


def test_deserialize_single_float() -> None:
    original = Variant([Variant.vfloat(3.14)])
    data = original.serialize()
    restored = Variant.deserialize(data)
    assert len(restored) == 1
    assert abs(restored.as_float[0] - 3.14) < 0.001
    verify(repr(restored))


def test_deserialize_single_string() -> None:
    original = Variant([Variant.vstr(b"hello")])
    data = original.serialize()
    restored = Variant.deserialize(data)
    assert len(restored) == 1
    assert restored.as_string[0] == b"hello"
    verify(repr(restored))


def test_deserialize_mixed_types() -> None:
    original = Variant([Variant.vfloat(1.5), Variant.vstr(b"test"), Variant.vvec2((2.0, 3.0)), Variant.vvec3((4.0, 5.0, 6.0)), Variant.vuint(42), Variant.vint(-99)])
    data = original.serialize()
    restored = Variant.deserialize(data)
    assert len(restored) == 6
    verify(repr(restored))


def test_roundtrip_empty() -> None:
    v = Variant()
    data = v.serialize()
    restored = Variant.deserialize(data)
    assert len(restored) == 0


def test_roundtrip_all_types() -> None:
    original = Variant(
        [Variant.vfloat(3.14159), Variant.vstr(b"Hello, World!"), Variant.vvec2((1.1, 2.2)), Variant.vvec3((3.3, 4.4, 5.5)), Variant.vuint(999999), Variant.vint(-123456)]
    )
    data = original.serialize()
    restored = Variant.deserialize(data)

    assert len(restored) == 6
    assert abs(restored.as_float[0] - 3.14159) < 0.00001
    assert restored.as_string[1] == b"Hello, World!"
    assert restored.as_vec2[2] == pytest.approx((1.1, 2.2))
    assert restored.as_vec3[3] == pytest.approx((3.3, 4.4, 5.5))
    assert restored.as_uint[4] == 999999
    assert restored.as_int[5] == -123456


def test_empty_string_value() -> None:
    v = Variant([Variant.vstr(b"")])
    data = v.serialize()
    restored = Variant.deserialize(data)
    assert restored.as_string[0] == b""


def test_zero_values() -> None:
    v = Variant([Variant.vfloat(0.0), Variant.vuint(0), Variant.vint(0), Variant.vvec2((0.0, 0.0)), Variant.vvec3((0.0, 0.0, 0.0))])
    data = v.serialize()
    restored = Variant.deserialize(data)
    assert restored.as_float[0] == 0.0
    assert restored.as_uint[1] == 0
    assert restored.as_int[2] == 0


def test_negative_float() -> None:
    v = Variant([Variant.vfloat(-999.999)])
    data = v.serialize()
    restored = Variant.deserialize(data)
    assert restored.as_float[0] == pytest.approx(-999.999)


def test_large_unsigned_int() -> None:
    v = Variant([Variant.vuint(4294967295)])
    data = v.serialize()
    restored = Variant.deserialize(data)
    assert restored.as_uint[0] == 4294967295


def test_large_negative_int() -> None:
    v = Variant([Variant.vint(-2147483648)])
    data = v.serialize()
    restored = Variant.deserialize(data)
    assert restored.as_int[0] == -2147483648


def test_binary_string_with_nulls() -> None:
    v = Variant([Variant.vstr(b"\x00\x01\x02\xff")])
    data = v.serialize()
    restored = Variant.deserialize(data)
    assert restored.as_string[0] == b"\x00\x01\x02\xff"


def test_unicode_string_as_bytes() -> None:
    v = Variant([Variant.vstr("Hello 世界".encode("utf-8"))])
    data = v.serialize()
    restored = Variant.deserialize(data)
    assert restored.as_string[0].decode("utf-8") == "Hello 世界"


def test_special_float_values() -> None:
    import math

    v = Variant([Variant.vfloat(float("inf")), Variant.vfloat(float("-inf")), Variant.vfloat(float("nan"))])
    data = v.serialize()
    restored = Variant.deserialize(data)
    assert math.isinf(restored.as_float[0]) and restored.as_float[0] > 0
    assert math.isinf(restored.as_float[1]) and restored.as_float[1] < 0
    assert math.isnan(restored.as_float[2])


def test_very_large_vec_values() -> None:
    v = Variant([Variant.vvec2((1e30, -1e30)), Variant.vvec3((1e20, -1e20, 1e15))])
    data = v.serialize()
    restored = Variant.deserialize(data)

    assert restored.as_vec2[0][0] == pytest.approx(1e30, rel=1e-5)


def test_deserialize_truncated_data() -> None:
    data = bytes([1, 0, Kind.FLOAT])
    with pytest.raises(Exception):
        Variant.deserialize(data)


def test_deserialize_invalid_kind() -> None:
    data = bytes([1, 0, 99, 0, 0, 0, 0])
    with pytest.raises(ValueError):
        Variant.deserialize(data)


def test_deserialize_empty_data() -> None:
    with pytest.raises(Exception):
        Variant.deserialize(b"")


def test_deserialize_partial_string() -> None:
    v = Variant([Variant.vstr(b"hello")])
    data = bytearray(v.serialize())

    data = data[:-2]
    with pytest.raises(Exception):
        Variant.deserialize(bytes(data))


def test_vfloat_immutable() -> None:
    v = Variant.vfloat(3.14)
    with pytest.raises(Exception):
        v.value = 2.71  # pyright: ignore


def test_vstr_immutable() -> None:
    v = Variant.vstr(b"test")
    with pytest.raises(Exception):
        v.value = b"changed"  # pyright: ignore


def test_vvec2_immutable() -> None:
    v = Variant.vvec2((1.0, 2.0))
    with pytest.raises(Exception):
        v.value = (3.0, 4.0)  # pyright: ignore


def test_repr_empty() -> None:
    v = Variant()
    assert repr(v) == "Variant([])"


def test_repr_single_float() -> None:
    v = Variant([Variant.vfloat(3.14)])
    result = repr(v)
    assert "Variant.vfloat(3.14)" in result
    verify(result)


def test_repr_multiple_types() -> None:
    v = Variant([Variant.vfloat(1.0), Variant.vstr(b"test"), Variant.vuint(42)])
    result = repr(v)
    assert "Variant.vfloat(1.0)" in result
    assert "Variant.vstr(b'test')" in result
    assert "Variant.vuint(42)" in result
    verify(result)


def test_complex_workflow() -> None:
    v = Variant()

    v.append(Variant.vfloat(1.1))
    v.append(Variant.vstr(b"item1"))
    v.append(Variant.vvec2((2.0, 3.0)))
    v.append(Variant.vuint(100))

    v[1] = Variant.vstr(b"modified")

    v.pop(2)

    data = v.serialize()
    restored = Variant.deserialize(data)

    assert len(restored) == 3
    assert restored.as_float[0] == pytest.approx(1.1)
    assert restored.as_string[1] == b"modified"
    assert restored.as_uint[2] == 100
    verify(repr(restored))


def test_homogeneous_list_operations() -> None:
    v = Variant([Variant.vfloat(1.0), Variant.vfloat(2.0), Variant.vfloat(3.0), Variant.vfloat(4.0), Variant.vfloat(5.0)])

    subset = v.as_float[1:4]
    assert subset == [2.0, 3.0, 4.0]

    assert v.as_float[-1] == 5.0
    assert v.as_float[-2] == 4.0

    verify(repr(v))


def test_byte_format_structure() -> None:
    v = Variant([Variant.vfloat(1.0), Variant.vuint(42)])
    data = v.serialize()

    assert data[0] == 2

    assert data[1] == 0
    assert data[2] == Kind.FLOAT

    idx = 7
    assert data[idx] == 1
    assert data[idx + 1] == Kind.UNSIGNED

    verify(data.hex())


def test_255_elements() -> None:
    values: list[Variant.Type] = [Variant.vint(i) for i in range(255)]
    v = Variant(values)
    data = v.serialize()
    restored = Variant.deserialize(data)

    assert len(restored) == 255
    assert restored.as_int[0] == 0
    assert restored.as_int[254] == 254


def test_256_elements() -> None:
    values: list[Variant.Type] = [Variant.vint(i) for i in range(256)]
    v = Variant(values)

    with pytest.raises(struct.error):
        v.serialize()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
