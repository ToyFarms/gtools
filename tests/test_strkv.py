import pytest

from gtools.core.growtopia.strkv import StrKV
from tests import verify


def test_empty_initialization() -> None:
    kv = StrKV()
    assert len(kv.data) == 0
    assert kv.delim == "|"
    verify(repr(kv))


def test_initialization_with_data() -> None:
    data = [[b"key1", b"val1"], [b"key2", b"val2"]]
    kv = StrKV(data)
    assert len(kv.data) == 2
    verify(repr(kv))


def test_custom_delimiter() -> None:
    kv = StrKV(delim=",")
    assert kv.delim == ","
    verify(kv.delim)


def test_index_lookup_built_correctly() -> None:
    data = [[b"key1", b"val1"], [b"key2", b"val2"], [b"key3", b"val3"]]
    kv = StrKV(data)
    assert kv._index_lookup[b"key1"] == 0
    assert kv._index_lookup[b"key2"] == 1
    assert kv._index_lookup[b"key3"] == 2


def test_getitem_by_int_index() -> None:
    kv = StrKV([[b"key1", b"val1", b"val2"], [b"key2", b"val3"]])
    result = kv[0]
    assert result == [b"key1", b"val1", b"val2"]
    verify([r.decode() for r in result])


def test_getitem_by_bytes_key() -> None:
    kv = StrKV([[b"key1", b"val1"], [b"key2", b"val2"]])
    result = kv[b"key2"]
    assert result == [b"key2", b"val2"]
    verify([r.decode() for r in result])


def test_getitem_by_str_key() -> None:
    kv = StrKV([[b"key1", b"val1"], [b"key2", b"val2"]])
    result = kv["key1"]
    assert result == [b"key1", b"val1"]
    verify([r.decode() for r in result])


def test_getitem_tuple_bytes_key_int_col() -> None:
    kv = StrKV([[b"key1", b"val1", b"val2"], [b"key2", b"val3", b"val4"]])
    result = kv[b"key1", 2]
    assert result == b"val2"
    verify(result.decode())


def test_getitem_tuple_str_key_int_col() -> None:
    kv = StrKV([[b"key1", b"val1", b"val2"]])
    result = kv["key1", 1]
    assert result == b"val1"
    verify(result.decode())


def test_getitem_tuple_int_index_int_col() -> None:
    kv = StrKV([[b"key1", b"val1", b"val2"]])
    result = kv[0, 2]
    assert result == b"val2"
    verify(result.decode())


def test_getitem_tuple_with_slice() -> None:
    kv = StrKV([[b"key1", b"val1", b"val2", b"val3"]])
    result = kv["key1", 1:3]
    assert result == [b"val1", b"val2"]
    verify([r.decode() for r in result])


def test_getitem_negative_index() -> None:
    kv = StrKV([[b"key1", b"val1"], [b"key2", b"val2"]])
    result = kv[-1]
    assert result == [b"key2", b"val2"]
    verify([r.decode() for r in result])


def test_getitem_nonexistent_key_raises() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    with pytest.raises(KeyError):
        _ = kv[b"nonexistent"]


def test_getitem_out_of_range_raises() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    with pytest.raises(IndexError):
        _ = kv[10]


def test_setitem_by_int_index() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    kv[0] = ["key2", "val2"]
    assert kv.data[0] == [b"key2", b"val2"]
    verify(repr(kv))


def test_setitem_by_bytes_key() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    kv[b"key1"] = ["key1", "newval"]
    assert kv.data[0][1] == b"newval"
    verify(repr(kv))


def test_setitem_by_str_key() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    kv["key1"] = ["key1", "updated"]
    assert kv.data[0][1] == b"updated"
    verify(repr(kv))


def test_setitem_tuple_updates_cell() -> None:
    kv = StrKV([[b"key1", b"val1", b"val2"]])
    kv["key1", 2] = "newval"
    assert kv.data[0][2] == b"newval"
    verify(repr(kv))


def test_setitem_tuple_with_int_index() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    kv[0, 1] = "changed"
    assert kv.data[0][1] == b"changed"
    verify(repr(kv))


def test_setitem_with_int_value() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    kv["key1", 1] = 42
    assert kv.data[0][1] == b"42"
    verify(repr(kv))


def test_setitem_with_bytes_value() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    kv["key1", 1] = b"bytes_value"
    assert kv.data[0][1] == b"bytes_value"
    verify(repr(kv))


def test_setitem_mixed_types() -> None:
    kv = StrKV()
    kv.append(["key1", "val1"])
    kv["key1"] = [42, "string", b"bytes"]
    assert kv.data[0] == [b"42", b"string", b"bytes"]
    verify(repr(kv))


def test_setitem_rebuilds_index() -> None:
    kv = StrKV([[b"key1", b"val1"], [b"key2", b"val2"]])
    kv[0] = ["newkey", "val1"]
    assert b"newkey" in kv._index_lookup
    assert b"key1" not in kv._index_lookup
    verify(repr(kv))


def test_append_single_row() -> None:
    kv = StrKV()
    kv.append(["key1", "val1"])
    assert len(kv.data) == 1
    assert kv.data[0] == [b"key1", b"val1"]
    verify(repr(kv))


def test_append_multiple_rows() -> None:
    kv = StrKV()
    kv.append(["key1", "val1"])
    kv.append(["key2", "val2"])
    kv.append(["key3", "val3"])
    assert len(kv.data) == 3
    verify(repr(kv))


def test_append_with_mixed_types() -> None:
    kv = StrKV()
    kv.append([42, "string", b"bytes"])
    assert kv.data[0] == [b"42", b"string", b"bytes"]
    verify(repr(kv))


def test_append_updates_index() -> None:
    kv = StrKV()
    kv.append(["key1", "val1"])
    kv.append(["key2", "val2"])
    assert b"key1" in kv._index_lookup
    assert b"key2" in kv._index_lookup
    assert kv._index_lookup[b"key2"] == 1


def test_append_empty_row() -> None:
    kv = StrKV()
    with pytest.raises(ValueError):
        kv.append([])


def test_serialize_empty() -> None:
    kv = StrKV()
    result = kv.serialize()
    assert result == b""
    verify(result.decode() if result else "")


def test_serialize_single_row() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    result = kv.serialize()
    assert result == b"key1|val1"
    verify(result.decode())


def test_serialize_multiple_rows() -> None:
    kv = StrKV([[b"key1", b"val1"], [b"key2", b"val2"]])
    result = kv.serialize()
    assert result == b"key1|val1\nkey2|val2"
    verify(result.decode())


def test_serialize_multiple_columns() -> None:
    kv = StrKV([[b"key1", b"val1", b"val2", b"val3"]])
    result = kv.serialize()
    assert result == b"key1|val1|val2|val3"
    verify(result.decode())


def test_deserialize_empty() -> None:
    kv = StrKV.deserialize(b"")
    assert len(kv.data) == 1
    assert kv.data[0] == [b""]
    verify(repr(kv))


def test_deserialize_single_row() -> None:
    kv = StrKV.deserialize(b"key1|val1")
    assert len(kv.data) == 1
    assert kv.data[0] == [b"key1", b"val1"]
    verify(repr(kv))


def test_deserialize_multiple_rows() -> None:
    kv = StrKV.deserialize(b"key1|val1\nkey2|val2\nkey3|val3")
    assert len(kv.data) == 3
    verify(repr(kv))


def test_serialize_deserialize_roundtrip() -> None:
    original = StrKV([[b"key1", b"val1"], [b"key2", b"val2", b"val3"]])
    serialized = original.serialize()
    restored = StrKV.deserialize(serialized)
    assert original.data == restored.data
    verify(repr(restored))


def test_binary_data_in_values() -> None:
    kv = StrKV()
    kv.append([b"key1", b"\x00\x01\x02\xff"])
    kv.serialize()
    verify(repr(kv))


def test_binary_data_roundtrip() -> None:
    binary = b"\x00\x01\x02\xff\xfe"
    kv = StrKV([[b"key1", binary]])
    serialized = kv.serialize()
    restored = StrKV.deserialize(serialized)
    assert restored.data[0][1] == binary
    verify(repr(restored))


def test_null_bytes_in_data() -> None:
    kv = StrKV([[b"key\x00null", b"val\x00ue"]])
    kv.serialize()
    verify(repr(kv))


def test_unicode_data() -> None:
    kv = StrKV()
    kv.append(["key1", "émojis 🎉", "中文"])
    assert kv.data[0][1] == "émojis 🎉".encode("utf-8")
    verify(repr(kv))


def test_mixed_binary_and_text() -> None:
    kv = StrKV([[b"key1", b"normal", b"\xff\xfe", b"text"]])
    verify(repr(kv))


def test_empty_string_key() -> None:
    kv = StrKV([[b"", b"val1"]])
    result = kv[b""]
    assert result == [b"", b"val1"]
    verify(repr(kv))


def test_empty_string_value() -> None:
    kv = StrKV([[b"key1", b""]])
    assert kv["key1", 1] == b""
    verify(repr(kv))


def test_delimiter_in_data() -> None:
    kv = StrKV([[b"key|with|pipes", b"val|ue"]])
    serialized = kv.serialize()
    verify(serialized.decode())


def test_newline_in_data() -> None:
    kv = StrKV([[b"key\nwith\nnewlines", b"val\nue"]])
    kv.serialize()
    verify(repr(kv))


def test_very_long_value() -> None:
    long_val = "x" * 10000
    kv = StrKV()
    kv.append(["key1", long_val])
    assert len(kv.data[0][1]) == 10000
    verify(len(kv.data[0][1]))


def test_many_columns() -> None:
    row = ["key"] + [f"val{i}" for i in range(100)]
    kv = StrKV()
    kv.append(row)
    assert len(kv.data[0]) == 101
    verify(len(kv.data[0]))


def test_duplicate_keys() -> None:
    kv = StrKV([[b"key1", b"val1"], [b"key1", b"val2"]])
    assert kv._index_lookup[b"key1"] == 1
    assert kv[b"key1"] == [b"key1", b"val2"]
    verify(repr(kv))


def test_single_column_row() -> None:
    kv = StrKV([[b"lonely"]])
    result = kv[0]
    assert result == [b"lonely"]
    verify(repr(kv))


def test_whitespace_handling() -> None:
    kv = StrKV([[b"  key  ", b"  val  "]])
    assert kv[b"  key  "][1] == b"  val  "
    verify(repr(kv))


def test_repr_empty() -> None:
    kv = StrKV()
    result = repr(kv)
    assert result == "{}"
    verify(result)


def test_repr_single_row() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    result = repr(kv)
    verify(result)


def test_repr_multiple_rows() -> None:
    kv = StrKV([[b"key1", b"val1"], [b"key2", b"val2"]])
    result = repr(kv)
    verify(result)


def test_repr_with_binary_data() -> None:
    kv = StrKV([[b"key1", b"\xff\xfe\x00"]])
    result = repr(kv)
    assert "\\xff" in result or "\\xfe" in result
    verify(result)


def test_invalid_key_type_getitem() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    with pytest.raises((KeyError, TypeError, AttributeError)):
        _ = kv[None]  # type: ignore


def test_invalid_tuple_structure() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    with pytest.raises((IndexError, TypeError)):
        _ = kv[("key1", "not_an_int")]  # type: ignore


def test_column_index_out_of_range() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    with pytest.raises(IndexError):
        _ = kv["key1", 10]


def test_setitem_on_nonexistent_key() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    with pytest.raises(KeyError):
        kv[b"nonexistent"] = ["new", "value"]


def test_deserialize_malformed_data() -> None:
    kv = StrKV.deserialize(b"malformed||data\n\n\nempty||lines")
    assert len(kv.data) == 4
    verify(repr(kv))


def test_complex_workflow() -> None:
    kv = StrKV()
    kv.append(["user1", "alice", "admin"])
    kv.append(["user2", "bob", "user"])
    kv.append([3, "charlie", "guest"])

    kv["user2", 2] = "moderator"
    kv[2] = ["user3", "charlie", "guest"]

    serialized = kv.serialize()
    restored = StrKV.deserialize(serialized)

    assert restored["user2", 2] == b"moderator"
    assert restored[2, 0] == b"user3"
    verify(repr(restored))


def test_incremental_build() -> None:
    kv = StrKV()
    for i in range(10):
        kv.append([f"key{i}", f"value{i}", i])

    for i in range(0, 10, 2):
        kv[i, 2] = i * 10

    verify(repr(kv))


def test_all_type_conversions() -> None:
    kv = StrKV()
    kv.append([123, "string", b"bytes"])

    row = kv[0]
    cell1 = kv[0, 0]
    cell2 = kv[b"123", 1]
    cell3 = kv["123", 2]

    verify({"row": [c.decode() for c in row], "cell1": cell1.decode(), "cell2": cell2.decode(), "cell3": cell3.decode()})
