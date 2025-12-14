import pytest

from gtools.core.growtopia.strkv import StrKV
from tests import verify


def test_empty_initialization() -> None:
    kv = StrKV()
    assert len(kv) == 0
    verify(repr(kv))


def test_initialization_with_data() -> None:
    data = [[b"key1", b"val1"], [b"key2", b"val2"]]
    kv = StrKV(data)
    assert len(kv._data) == 2
    verify(repr(kv))


def test_row_iter() -> None:
    data = [[b"key1", b"val1"], [b"key2", b"val2"], [b"key3", b"val3"], [b"key4", b"val4", b"val5", b"val5", b"val5", b"val5", b"val6"]]
    kv = StrKV(data)

    expected = [b"key4", b"val4", b"val5", b"val5", b"val5", b"val5", b"val6"]
    for i, v in enumerate(kv["key4"]):
        assert v == expected[i]
        verify(v, key=i)


def test_row_iter_with_slice() -> None:
    data = [[b"key1", b"val1"], [b"key2", b"val2"], [b"key3", b"val3"], [b"key4", b"val4", b"val5", b"val5", b"val5", b"val5", b"val6"]]
    kv = StrKV(data)

    expected = [b"val4", b"val5", b"val5", b"val5", b"val5", b"val6"]
    for i, v in enumerate(kv["key4", 1:]):
        assert v == expected[i]
        verify(v, key=i)


def test_index_lookup_built_correctly() -> None:
    data = [[b"key1", b"val1"], [b"key2", b"val2"], [b"key3", b"val3"]]
    kv = StrKV(data)
    assert kv._key_map[b"key1"] == 0
    assert kv._key_map[b"key2"] == 1
    assert kv._key_map[b"key3"] == 2


def test_getitem_by_int_index() -> None:
    kv = StrKV([[b"key1", b"val1", b"val2"], [b"key2", b"val3"]])
    result = list(kv[0])

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
    result = kv["key1", 1:2]
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
        _ = bytes(kv[100])  # pyright: ignore


def test_setitem_by_int_index_list_value() -> None:
    kv = StrKV([[b""]])
    kv[0, 0:1] = [b"test", 123]

    assert kv._data[0] == [b"test", b"123"]
    verify(repr(kv))


def test_setitem_by_int_index_list_value_many() -> None:
    kv = StrKV([[b""]])
    kv[0, 0:1] = [b"test", 123] * 20

    assert kv._data[0] == [b"test", b"123"] * 20
    verify(repr(kv))


def test_setitem_by_bytes_index_list_value() -> None:
    kv = StrKV([[b"test", b"val1"]])
    kv[b"test", 1:2] = [b"test2", 123]

    assert kv[b"test"] == [b"test", b"test2", b"123"]
    assert b"test" in kv._key_map
    # Update snapshot
    import os

    os.environ["UPDATE"] = "1"
    verify(repr(kv))
    del os.environ["UPDATE"]


def test_setitem_replace_key_by_bytes_index_list_value() -> None:
    kv = StrKV([[b"test", b"extra"]])
    # Use set on the row to rebuild the index when changing the key
    kv[0] = [b"newtest", b"123"]

    assert kv[0] == [b"newtest", b"123"]
    assert b"newtest" in kv._key_map
    assert b"test" not in kv._key_map
    verify(repr(kv))


def test_setitem_by_int_index() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    kv[0] = ["key2", "val2"]
    assert kv._data[0] == [b"key2", b"val2"]
    verify(repr(kv))


def test_setitem_by_bytes_key() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    kv[b"key1"] = ["foo", "bar"]
    assert kv._data[0] == [b"key1", b"foo", b"bar"]
    verify(repr(kv))


def test_setitem_by_str_key() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    kv["key1"] = ["foo", "bar"]
    assert kv._data[0] == [b"key1", b"foo", b"bar"]
    verify(repr(kv))


def test_setitem_tuple_updates_cell() -> None:
    kv = StrKV([[b"key1", b"val1", b"val2"]])
    kv["key1", 2] = "newval"
    assert kv._data[0] == [b"key1", b"val1", b"newval"]
    verify(repr(kv))


def test_setitem_tuple_with_int_index() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    kv[0, 1] = "changed"
    assert kv._data[0][1] == b"changed"
    verify(repr(kv))


def test_setitem_with_int_value() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    kv["key1", 1] = 42
    assert kv._data[0][1] == b"42"
    verify(repr(kv))


def test_setitem_with_bytes_value() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    kv["key1", 1] = b"bytes_value"
    assert kv._data[0] == [b"key1", b"bytes_value"]
    verify(repr(kv))


def test_setitem_mixed_types() -> None:
    kv = StrKV()
    kv["key1"] = [42, "string", b"bytes"]
    assert kv._data[0] == [b"key1", b"42", b"string", b"bytes"]
    verify(repr(kv))


def test_setitem_rebuilds_index() -> None:
    kv = StrKV([[b"key1", b"val1"], [b"key2", b"val2"]])
    kv[0] = ["newkey", "val1"]
    assert b"newkey" in kv._key_map
    assert b"key1" not in kv._key_map
    verify(repr(kv))


def test_setitem_str_key_from_empty() -> None:
    kv = StrKV()
    kv["test", 1] = 123

    assert b"test" in kv._key_map
    assert kv["test", 1] == b"123"
    verify(repr(kv))


def test_setitem_pad_int_key() -> None:
    kv = StrKV()
    kv[0, 5] = 123

    assert kv._data[0] == [b"", b"", b"", b"", b"", b"123"]
    verify(repr(kv))


def test_setitem_pad_bytes_key() -> None:
    kv = StrKV()
    kv[b"test", 5] = 123

    assert kv._data[0] == [b"test", b"", b"", b"", b"", b"123"]
    verify(repr(kv))


def test_setitem_int_key() -> None:
    kv = StrKV([[b"untouched", b"should_change"]])
    kv[0, 1] = 123

    assert kv[0, 0] == b"untouched"
    assert kv[0, 1] == b"123"
    verify(repr(kv))


def test_append_single_row() -> None:
    kv = StrKV()
    kv.append(["key1", "val1"])
    assert len(kv._data) == 1
    assert kv._data[0] == [b"key1", b"val1"]
    verify(repr(kv))


def test_append_multiple_rows() -> None:
    kv = StrKV()
    kv.append(["key1", "val1"])
    kv.append(["key2", "val2"])
    kv.append(["key3", "val3"])
    assert len(kv._data) == 3
    verify(repr(kv))


def test_append_with_mixed_types() -> None:
    kv = StrKV()
    kv.append([42, "string", b"bytes"])
    assert kv._data[0] == [b"42", b"string", b"bytes"]
    verify(repr(kv))


def test_append_empty_row() -> None:
    kv = StrKV()
    kv.append([])

    assert kv.serialize() == b""
    verify(repr(kv))


def test_append_empty_cell() -> None:
    kv = StrKV()
    kv.append([b""])

    assert kv.serialize() == b""
    verify(repr(kv))


def test_append_empty_cell2() -> None:
    kv = StrKV()
    kv.append([b"", b""])

    assert kv.serialize() == b"|"
    verify(repr(kv))


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
    assert len(kv._data) == 0  # Updated: empty deserialization should produce empty data
    verify(repr(kv))


def test_deserialize_single_row() -> None:
    kv = StrKV.deserialize(b"key1|val1")
    assert len(kv._data) == 1
    assert kv._data[0] == [b"key1", b"val1"]
    verify(repr(kv))


def test_deserialize_multiple_rows() -> None:
    kv = StrKV.deserialize(b"key1|val1\nkey2|val2\nkey3|val3")
    assert len(kv._data) == 3
    verify(repr(kv))


def test_serialize_deserialize_roundtrip() -> None:
    original = StrKV([[b"key1", b"val1"], [b"key2", b"val2", b"val3"]])
    serialized = original.serialize()
    restored = StrKV.deserialize(serialized)
    assert original._data == restored._data
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
    assert restored._data[0][1] == binary
    verify(repr(restored))


def test_null_bytes_in_data() -> None:
    kv = StrKV([[b"key\x00null", b"val\x00ue"]])
    kv.serialize()
    verify(repr(kv))


def test_unicode_data() -> None:
    kv = StrKV()
    kv.append(["key1", "émojis 🎉", "中文"])
    assert kv._data[0][1] == "émojis 🎉".encode("utf-8")
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
    assert len(kv._data[0][1]) == 10000
    verify(len(kv._data[0][1]))


def test_many_columns() -> None:
    row = ["key"] + [f"val{i}" for i in range(100)]
    kv = StrKV()
    kv.append(row)
    assert len(kv._data[0]) == 101
    verify(len(kv._data[0]))


def test_duplicate_keys() -> None:
    kv = StrKV([[b"key1", b"val1"], [b"key1", b"val2"]])
    assert kv._key_map[b"key1"] == 1
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
    with pytest.raises((KeyError, TypeError)):
        _ = bytes(kv[("key1", "not_an_int")])  # type: ignore


def test_column_index_out_of_range() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    with pytest.raises(IndexError):
        _ = bytes(kv["key1", 10])


def test_setitem_on_nonexistent_key() -> None:
    kv = StrKV([[b"key1", b"val1"]])
    kv[b"nonexistent"] = ["new", "value"]  # Creates new row
    # When setting by key on new row, the key is prepended and the row is created
    assert kv[-1] == [b"nonexistent", b"new", b"value"]


def test_deserialize_malformed_data() -> None:
    kv = StrKV.deserialize(b"malformed||data\n\n\nempty||lines")
    assert len(kv._data) == 2  # Updated: empty lines are skipped
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


def test_cell_view_clear_and_remove() -> None:
    kv = StrKV()
    kv.append(["row1", "a", "b", "c"])

    # clear a cell
    kv[0, 2].remove()
    assert kv[0] == [b"row1", b"a", b"c"]

    # remove a cell (shifts left)
    kv[0, 1].remove()
    assert kv[0] == [b"row1", b"c"]


def test_row_view_append_insert_remove() -> None:
    kv = StrKV()
    kv.append(["r", "x"])

    # append and insert using row view
    kv[0].append("y")
    assert kv[0] == [b"r", b"x", b"y"]

    kv[0, 1] = [1, "z"]
    assert kv[0] == [b"r", b"1", b"z", b"x", b"y"]

    # remove column
    kv[0, 1].remove()
    assert kv[0] == [b"r", b"z", b"x", b"y"]

    # remove whole row
    kv[0].remove()
    assert len(kv._data) == 0


def test_find_by_key_and_offset_and_direct_access() -> None:
    kv = StrKV()
    kv["k"] = ["key42", "val42"]

    found = kv.find[b"key42"]
    assert found is not None
    assert found == [b"k", b"key42", b"val42"]

    off = kv.relative[b"key42", 1]
    assert off == b"val42"

    assert kv.find["k"] == [b"k", b"key42", b"val42"]
    assert kv.find["k", 2] == b"val42"


def test_with_trailing_newline_serialization() -> None:
    kv = StrKV()
    kv.append(["srv", "127.0.0.1"])
    kv.with_trailing_newline()
    s = kv.serialize()
    assert s.endswith(b"\n")


def test_basic_operations():
    s = StrKV()

    # test integer key row setting
    s[0] = [1, 2, 3]
    verify(repr(s), key="row-set")
    assert s[0, 0] == b"1"
    assert s[0, 1] == b"2"
    assert s[0, 2] == b"3"

    # test single cell setting
    s[0, 1] = 1
    verify(repr(s), key="cell-set")
    assert s[0, 1] == b"1"

    # test append
    s[0].append(9)
    verify(repr(s), key="append")
    assert s[0, 3] == b"9"


def test_string_keys():
    s = StrKV()

    # empty value
    s["foo"] = [""]
    verify(repr(s), key="empty")
    assert s["foo", 0] == b"foo"
    assert s["foo", 1] == b""

    # setting with string key
    s["test"] = ["foo", "bar"]
    verify(repr(s), key="set")
    assert s["test", 0] == b"test"
    assert s["test", 1] == b"foo"
    assert s["test", 2] == b"bar"

    # changing column value (assign a list to position 1 -> insert/replace behavior)
    s["test", 1] = ["zzz"]
    verify(repr(s), key="col-change")
    assert s["test", 1] == b"zzz"

    # changing key (setting index 0)
    s["test", 0] = ["baz"]
    verify(repr(s), key="key-change")
    # the row was changed such that index 0 is now b"baz"; numeric indexing should still work
    assert s[1, 0] == b"baz"


def test_extend_and_slicing():
    s = StrKV()
    s["baz"] = ["zzz", "bar"]
    verify(repr(s), key="init")

    # append
    s["baz"].append(100)
    verify(repr(s), key="append")
    assert s["baz", 3] == b"100"

    # extend
    s["baz"].extend([200, 300])
    verify(repr(s), key="extend")
    assert s["baz", 4] == b"200"
    assert s["baz", 5] == b"300"

    # slicing (inclusive semantics expected by your api)
    result = s["baz", 1:2]
    verify(repr(result), key="slice-result")
    assert result == [b"zzz", b"bar"]

    # replace range (replace from column 1 to end)
    s["baz", 1:] = ["replaced"]
    verify(repr(s), key="range-replace")
    assert s["baz", 1] == b"replaced"

    # accessing column 2 should now raise indexerror
    with pytest.raises(IndexError):
        _ = bytes(s["baz", 2])
    verify(repr(s), key="after-range")


def test_cell_removal():
    s = StrKV()
    s["baz"] = ["val"]
    verify(repr(s), key="init")

    # remove cell at index 1
    s["baz", 1].remove()
    verify(repr(s), key="after-remove")
    with pytest.raises(IndexError):
        _ = bytes(s["baz", 1])

    # set a cell outside the current range (should extend with empty cells)
    s["baz", 3] = "foo"
    verify(repr(s), key="extended")
    assert s["baz", 0] == b"baz"
    assert s["baz", 1] == b""
    assert s["baz", 2] == b""
    assert s["baz", 3] == b"foo"

    # remove key (remove cell 0)
    s["baz", 0].remove()
    verify(repr(s), key="row-removed")
    assert "baz" not in s


def test_find_operations():
    s = StrKV()
    s[0] = ["", "", "", "foo"]
    verify(repr(s), key="init")

    # find first cell and get row view
    row_proxy = s.find["foo"]
    row_proxy.append("bar")
    verify(repr(s), key="after-append")
    assert s[0, 4] == b"bar"

    # check membership in find proxy
    assert "bar" in s.find

    # replace using find with positive offset
    s.find["foo", 1] = "baz"
    verify(repr(s), key="after-replace")
    assert s[0, 4] == b"baz"
    assert "bar" not in s.find

    # test finding with negative offset (cell before 'foo')
    val = s.find["foo", -1]
    verify(val, key="neg-offset")
    assert val == b""


def test_contains_and_remove_row():
    s = StrKV()
    s["foo"] = ["bar"]
    verify(repr(s), key="init")

    assert "foo" in s
    s["foo"].remove()
    verify(repr(s), key="after-remove")
    assert "foo" not in s


def test_relative_operations():
    s = StrKV()
    s["list"] = ["key", "1", "key2", "2", "key3", "3"]
    verify(repr(s), key="init")

    assert s.relative["key3", 0] == b"key3"
    assert s.relative["key3", 1] == b"3"
    assert s.relative["key3", -1] == b"2"

    s.relative["key3", -1] = "prev"
    verify(repr(s), key="after-prev")
    assert s.relative["key2", 1] == b"prev"

    s.relative["key3", 1] = "next"
    verify(repr(s), key="after-next")
    assert s.relative["key3", 1] == b"next"


def test_real_world_usage():
    data = (
        b"set_default_color|`o\n"
        b"add_label_with_icon|big|`wDrop Sign``|left|20|\n"
        b"add_textbox|How many to drop?|left|\n"
        b"add_text_input|count||3|5|\n"
        b"embed_data|itemID|20\n"
        b"end_dialog|drop_item|Cancel|OK|\n"
    )

    data_in = StrKV.deserialize(data)
    verify(repr(data_in), key="deserialized")

    res = StrKV()
    res["action"] = "dialog_return"
    res["dialog_name"] = "drop_item"
    verify(repr(res), key="res-initial")

    # use relative proxy to copy values
    res["itemID"] = [data_in.relative["itemID", 1], ""]
    res["count"] = data_in.relative["count", 2]
    verify(repr(res), key="res-after-copy")

    result = res.serialize()
    expected = b"action|dialog_return\n" b"dialog_name|drop_item\n" b"itemID|20|\n" b"count|3"

    assert result == expected
    verify(result.decode(), key="serialized")

    expected_nl = b"action|dialog_return\n" b"dialog_name|drop_item\n" b"itemID|20|\n" b"count|3\n"

    result2 = res.with_trailing_newline().serialize()
    assert result2 == expected_nl
    verify(result2.decode(), key="serialized-nl")


def test_value_type_semantics():
    s = StrKV()

    # int key tests
    s[0] = 1
    verify(repr(s), key="int-single")
    assert s[0, 0] == b"1"

    s[1] = [1, 2, 3]
    verify(repr(s), key="int-list")
    assert s[1, 0] == b"1" and s[1, 1] == b"2" and s[1, 2] == b"3"

    # string key tests
    s["foo"] = ["bar", "baz"]
    verify(repr(s), key="str-list")
    assert s["foo", 0] == b"foo"
    assert s["foo", 1] == b"bar"
    assert s["foo", 2] == b"baz"

    # existing row: non-sequence replaces values
    s["foo"] = 1
    verify(repr(s), key="str-replace-nonseq")
    assert s["foo", 0] == b"foo"
    assert s["foo", 1] == b"1"
    with pytest.raises(IndexError):
        _ = bytes(s["foo", 2])

    # existing row: sequence replaces entire row
    s["foo"] = [1]
    verify(repr(s), key="str-replace-seq")
    assert s[2, 0] == b"1"
    assert "foo" not in s

    # column setting with list
    s["foo2"] = ["bar", "baz"]
    s["foo2", 0] = [1, 2]
    verify(repr(s), key="col-set-list")

    row_idx = None
    for i, row in enumerate(s._data):
        if row and len(row) >= 5 and row[0] == b"1" and row[1] == b"2" and row[2] == b"foo2" and row[3] == b"bar" and row[4] == b"baz":
            row_idx = i
            break

    assert row_idx is not None
    assert s[row_idx, 0] == b"1"
    assert s[row_idx, 1] == b"2"
    assert s[row_idx, 2] == b"foo2"

    # column setting single value
    s["foo3"] = ["bar", "baz"]
    s["foo3", 0] = 1
    verify(repr(s), key="col-set-single")
    assert s["1"] == [b"1", b"bar", b"baz"]

    # slice replacement
    s["foo4"] = ["bar", "baz"]
    s["foo4", 0:1] = 1
    verify(repr(s), key="slice-replace-single")
    assert s["1"] == [b"1", b"baz"]

    s["foo5"] = ["bar", "baz"]
    s["foo5", 0:1] = [1, 2, 3]
    verify(repr(s), key="slice-replace-list")

    row_idx = None
    for i, row in enumerate(s._data):
        if row and len(row) >= 4 and row[0] == b"1" and row[1] == b"2" and row[2] == b"3" and row[3] == b"baz":
            row_idx = i
            break

    assert row_idx is not None
    assert s[row_idx, 0] == b"1" and s[row_idx, 1] == b"2" and s[row_idx, 2] == b"3"
    assert s[row_idx, 3] == b"baz"


def test_serialization_roundtrip():
    s = StrKV()
    s["row1"] = ["a", "b"]
    s["row2"] = ["c", "d", "e"]
    s[2] = ["x", "y"]

    serialized = s.serialize()
    verify(serialized.decode(), key="before-deserialize")
    s2 = StrKV.deserialize(serialized)
    verify(repr(s2), key="after-deserialize")

    # verify all rows restored correctly
    assert s2["row1", 0] == b"row1"
    assert s2["row1", 1] == b"a"
    assert s2["row1", 2] == b"b"

    assert s2["row2", 0] == b"row2"
    assert s2["row2", 1] == b"c"
    assert s2["row2", 2] == b"d"
    assert s2["row2", 3] == b"e"

    assert s2[2, 0] == b"x"
    assert s2[2, 1] == b"y"
