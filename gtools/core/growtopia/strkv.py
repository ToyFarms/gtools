"""

strkv is a 2d table, all data is stored as bytes internally,
but accepts any value convertible to string (encoding it as bytes)
each row is separated by newline, each cell is separated by pipe
no escaping separator needed

s = StrKV()
s[0] = [1, 2, 3] # setting row (1|2|3)
s[0, 1] = 1 # setting column (1|1|3)
s[0].append(9) # append to row (1|1|3|9)

s["foo"] = [""]  # empty (foo|)

s["test"] = ["foo", "bar"]  # setting a value (test|foo|bar)
s["test", 1] = ["zzz"]  # setting column with key (test|zzz|bar)
s["test", 0] = ["baz"]  # changing key (baz|zzz|bar)
s["baz"].append(100)  # append using key (baz|zzz|bar|100)
s["baz"].extend([200, 300])  # extend (baz|zzz|bar|100|200|300)
s["baz", 1:2]  # get the first through second index (inclusive) ([b"zzz", b"bar"])
s["baz", 1:] = ["replaced"]  # replace range (baz|replaced)

s["baz", 1].remove()  # remove cell (baz)
s["baz", 3] = "foo"  # set cell outside range (baz|||foo)
s["baz", 0].remove()  # remove key, its now unindexable using key, only numeric index (|||foo)

s.find["foo"]  # find the first cell that is foo (|||foo)
s.find["foo"].append("bar")  # append (|||foo|bar)
"bar" in s.find  # check in any cell (True)
s.find["foo", -1] = "baz"  # replace (|||foo|baz)
"bar" in s.find  # False
s.find["foo", 0:3].remove()  # remove empty cell, simultaneously making the key foo (foo|baz)
"foo" in s  # check if key exists (True)
s["foo"].remove()  # remove the row completely ()
"foo" in s  # False

s["list"] = ["key", "1", "key2", "2", "key3", "3"] # (key|1|key2|2|key3|3)
s.relative["key3", 0]  # this returns "key3"
s.relative["key3", 1]  # this returns "3"
s.relative["key3", -1]  # this returns "2"

s.relative["key3", -1] = "prev"  # set (key1|1|key2|prev|key3|3)
s.relative["key3", 1] = "next"  # set (key1|1|key2|prev|key3|next)

# interpretation:

when setting using int as the key, the key will be the 0th index of the value (or the value itself if the value is not a sequence)
when setting using str/bytes as the key, it will interpret that key as the actual key, so it will be [key, *values]

the second argument of the subscript is a number or a slice
in case of number, it will specify the column number, it its way past the available column, fill it with empty
in case of slice, it will replace every cell selected with a new list/value, length doesnt matter, it will adjust the adjacent cell to push back/fill

find will allow to find row based on known key in non-0th index
relative will allow operation relative to any cell

for all operation. the value can be a single, or multiple value (sequence), the behavior is dependend on the operation, for example:
s["foo", 1] = [1, 2, 3] # insert the list [1, 2, 3] at index 1
whereas s["foo", 1:] = [1, 2, 3] # replace index 1 to the end with the list [1, 2, 3]

another example would be:
s[0] = 1  # set the 0th-row's key to the value 1
s[0] = [1, 2, 3]  # replace the 0th-row's entirely with [1, 2, 3]

# foo|bar|baz
s["foo"] = 1  # replace all values with 1, becomes (foo|1)
# foo|bar|baz
s["foo"] = [1]  # replace all values including key with 1, becomes (1)

# foo|bar|baz
s["foo", 0] = 1  # replace key with 1, becomes (1|bar|baz)
# foo|bar|baz
s["foo", 0] = [1, 2]  # insert the list [1, 2] at index 0, becomes (1|2|foo|bar|baz)

# foo|bar|baz
s["foo", 0:1] = 1  # replace the 0 to 1 (inclusive) index with 1, becomes (1|baz)
# foo|bar|baz
s["foo", 0:1] = [1, 2, 3]  # replace the 0 to 1 (inclusive) index with the list [1, 2, 3], becomes (1|2|3|baz)

# real world usage

data = b"set_default_color|`o\nadd_label_with_icon|big|`wDrop Sign``|left|20|\nadd_textbox|How many to drop?|left|\nadd_text_input|count||3|5|\nembed_data|itemID|20\nend_dialog|drop_item|Cancel|OK|\n"
data_in = StrKV.deserialize(data)

res = StrKV()
res["action"] = "dialog_return"
res["dialog_name"] = "drop_item"
res["itemID"] = [data_in.relative["itemID", 1], ""]
res["count"] = data_in.relative["count", 2]

res.serialize()  # b"action|dialog_return\ndialog_name|drop_item\nitemID|20|\ncount|3\n"

"""

import itertools
from typing import Any, Iterator, overload
from collections.abc import Iterable, Sequence


KeyType = int | str | bytes
ValueType = str | int | float | bytes | Sequence[str | int | float | bytes]


def _to_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def _to_bytes_list(value: ValueType) -> list[bytes]:
    if isinstance(value, (str, int, float, bytes)):
        return [_to_bytes(value)]
    return [_to_bytes(v) for v in value]


class _RowView:
    __slots__ = ("_parent", "_row_idx")

    def __init__(self, parent: "StrKV", row_idx: int) -> None:
        self._parent = parent
        self._row_idx = row_idx

    def append(self, value: Any) -> None:
        self._parent._data[self._row_idx].append(_to_bytes(value))

    def extend(self, values: Iterable[Any]) -> None:
        self._parent._data[self._row_idx].extend(_to_bytes(v) for v in values)

    def remove(self) -> None:
        # remove key mapping if exists
        row = self._parent._data[self._row_idx]
        key = row[0] if row else b""
        if key in self._parent._key_map:
            del self._parent._key_map[key]

        del self._parent._data[self._row_idx]
        self._parent._rebuild_key_map()

    def __iter__(self) -> Iterator[bytes]:
        return (x for x in self._parent._data[self._row_idx])

    def __eq__(self, other: Any, /) -> bool:
        return self._parent._data[self._row_idx] == other

    def __repr__(self) -> str:
        return f"RowView({self._parent._data[self._row_idx]!r})"

    def __getitem__(self, index: int | slice) -> "_CellView | list[bytes]":
        if isinstance(index, slice):
            return self._parent._data[self._row_idx][index]
        return _CellView(self._parent, self._row_idx, index)


class _CellView:
    __slots__ = ("_parent", "_row_idx", "_col_idx")

    def __init__(self, parent: "StrKV", row_idx: int, col_idx: int) -> None:
        self._parent = parent
        self._row_idx = row_idx
        self._col_idx = col_idx

    def remove(self) -> None:
        row = self._parent._data[self._row_idx]
        if 0 <= self._col_idx < len(row):
            # removing the key invalidates key map
            if self._col_idx == 0 and row[0] in self._parent._key_map:
                del self._parent._key_map[row[0]]
            del row[self._col_idx]

    def _get_value(self) -> bytes:
        return self._parent._data[self._row_idx][self._col_idx]

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, _CellView):
            return self._get_value() == other._get_value()
        if isinstance(other, bytes):
            return self._get_value() == other
        if isinstance(other, str):
            return self._get_value() == other.encode("utf-8")
        return self._get_value() == _to_bytes(other)

    def __bytes__(self) -> bytes:
        return self._get_value()

    def decode(self, encoding: str = "utf-8", errors: str = "strict") -> str:
        return self._get_value().decode(encoding, errors)

    def __repr__(self) -> str:
        return repr(self._get_value())


class _FindProxy:
    __slots__ = ("_parent",)

    def __init__(self, parent: "StrKV"):
        self._parent = parent

    def _find_cell(self, value: Any) -> tuple[int, int] | None:
        target = _to_bytes(value)
        for row_idx, row in enumerate(self._parent._data):
            for col_idx, cell in enumerate(row):
                if cell == target:
                    return row_idx, col_idx
        return None

    @overload
    def __getitem__(self, key: Any) -> _RowView: ...

    @overload
    def __getitem__(self, key: tuple[Any, int]) -> bytes: ...

    @overload
    def __getitem__(self, key: tuple[Any, slice]) -> list[bytes]: ...

    def __getitem__(self, key: Any | tuple[Any, int | slice]) -> _RowView | bytes | list[bytes]:
        if isinstance(key, tuple):
            value, index = key
            pos = self._find_cell(value)
            if pos is None:
                raise KeyError(f"value {value} not found")

            row_idx, col_idx = pos

            if isinstance(index, slice):
                start = col_idx if index.start is None else col_idx + index.start
                stop = None if index.stop is None else col_idx + index.stop + 1
                return self._parent._data[row_idx][start : stop : index.step]

            target_col = col_idx + index
            if not 0 <= target_col < len(self._parent._data[row_idx]):
                raise IndexError(f"column index {target_col} out of range")
            return self._parent._data[row_idx][target_col]

        pos = self._find_cell(key)
        if pos is None:
            raise KeyError(f"value {key} not found")
        return _RowView(self._parent, pos[0])

    @overload
    def __setitem__(self, key: tuple[Any, int], value: Any) -> None: ...

    @overload
    def __setitem__(self, key: tuple[Any, slice], value: Any) -> None: ...

    def __setitem__(self, key: object, value: Any) -> None:
        if not isinstance(key, tuple):
            raise TypeError("find setitem requires tuple (value, index)")

        search_value, index = key
        pos = self._find_cell(search_value)
        if pos is None:
            raise KeyError(f"value {search_value} not found")

        row_idx, col_idx = pos
        row = self._parent._data[row_idx]

        if isinstance(index, slice):
            start = col_idx if index.start is None else col_idx + index.start
            stop = None if index.stop is None else col_idx + index.stop + 1

            new_values = _to_bytes_list(value)

            if stop is None:
                del row[start:]
                row.extend(new_values)
            else:
                del row[start : stop : index.step]
                for i, v in enumerate(new_values):
                    row.insert(start + i, v)

            if start <= 0:
                self._parent._rebuild_key_map()
            return

        target_col = col_idx + index
        while len(row) <= target_col:
            row.append(b"")

        row[target_col] = _to_bytes(value)

    def __contains__(self, value: Any) -> bool:
        return self._find_cell(value) is not None


class _RelativeProxy:
    __slots__ = ("_parent",)

    def __init__(self, parent: "StrKV"):
        self._parent = parent

    def _find_cell(self, value: Any) -> tuple[int, int] | None:
        target = _to_bytes(value)
        for row_idx, row in enumerate(self._parent._data):
            for col_idx, cell in enumerate(row):
                if cell == target:
                    return row_idx, col_idx
        return None

    def __getitem__(self, key: object) -> bytes:
        if not isinstance(key, tuple):
            raise TypeError("relative access requires tuple (value, offset)")

        value, offset = key
        pos = self._find_cell(value)
        if pos is None:
            raise KeyError(f"value {value} not found")

        row_idx, col_idx = pos
        target_col = col_idx + offset

        if not 0 <= target_col < len(self._parent._data[row_idx]):
            raise IndexError(f"column index {target_col} out of range")

        return self._parent._data[row_idx][target_col]

    def __setitem__(self, key: object, value: Any) -> None:
        if not isinstance(key, tuple):
            raise TypeError("relative access requires tuple (value, offset)")

        search_value, offset = key
        pos = self._find_cell(search_value)
        if pos is None:
            raise KeyError(f"value {search_value} not found")

        row_idx, col_idx = pos
        target_col = col_idx + offset
        row = self._parent._data[row_idx]

        if len(row) <= target_col:
            row.extend(itertools.repeat(b"", target_col + 1 - len(row)))

        row[target_col] = _to_bytes(value)

        if target_col == 0:
            self._parent._rebuild_key_map()


class StrKV:
    __slots__ = ("_data", "_key_map", "find", "relative", "_trailing_nl")

    def __init__(self, data: list[list[bytes]] | None = None, trailing_nl: bool = False) -> None:
        self._data: list[list[bytes]]
        self._key_map: dict[bytes, int] = {}

        if data:
            self._data = data
            self._rebuild_key_map()
        else:
            self._data = []

        self.find = _FindProxy(self)
        self.relative = _RelativeProxy(self)
        self._trailing_nl = trailing_nl

    def _rebuild_key_map(self) -> None:
        self._key_map.clear()
        for idx, row in enumerate(self._data):
            if row:
                self._key_map[row[0]] = idx

    def _get_row_idx(self, key: KeyType) -> int:
        if isinstance(key, int):
            return key if key >= 0 else len(self._data) + key

        key_bytes = _to_bytes(key)
        if key_bytes in self._key_map:
            return self._key_map[key_bytes]

        raise KeyError(f"key {key} not found")

    def _ensure_row(self, key: KeyType) -> int:
        if isinstance(key, int):
            key = key if key >= 0 else len(self._data) + key
            while len(self._data) <= key:
                self._data.append([])
            return key

        key_bytes = _to_bytes(key)
        if key_bytes in self._key_map:
            return self._key_map[key_bytes]

        idx = len(self._data)
        self._data.append([key_bytes])
        self._key_map[key_bytes] = idx
        return idx

    @overload
    def __getitem__(self, key: KeyType) -> _RowView: ...

    @overload
    def __getitem__(self, key: tuple[KeyType, int]) -> _CellView: ...

    @overload
    def __getitem__(self, key: tuple[KeyType, slice]) -> list[bytes]: ...

    def __getitem__(self, key: KeyType | tuple[KeyType, int | slice]) -> _RowView | _CellView | list[bytes]:
        if isinstance(key, tuple):
            row_key, col_key = key
            row_idx = self._get_row_idx(row_key)

            if isinstance(col_key, slice):
                stop = None if col_key.stop is None else col_key.stop + 1
                return self._data[row_idx][col_key.start : stop : col_key.step]

            return _CellView(self, row_idx, col_key)

        return _RowView(self, self._get_row_idx(key))

    def __setitem__(self, key: KeyType | tuple[KeyType, int | slice], value: Any) -> None:
        if isinstance(key, tuple):
            row_key, col_key = key
            row_idx = self._ensure_row(row_key)
            row = self._data[row_idx]

            if isinstance(col_key, slice):
                start = 0 if col_key.start is None else col_key.start
                stop = None if col_key.stop is None else col_key.stop + 1

                new_values = _to_bytes_list(value)

                if stop is None:
                    del row[start:]
                    row.extend(new_values)
                else:
                    del row[start : stop : col_key.step]
                    for i, v in enumerate(new_values):
                        row.insert(start + i, v)

                if start <= 0:
                    self._rebuild_key_map()
                return

            if isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes)):
                for v in reversed(_to_bytes_list(value)):
                    row.insert(col_key, v)
            else:
                while len(row) <= col_key:
                    row.append(b"")
                row[col_key] = _to_bytes(value)

            if col_key == 0:
                self._rebuild_key_map()
            return

        if isinstance(key, int):
            row_idx = self._ensure_row(key)
            self._data[row_idx] = _to_bytes_list(value) if isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes)) else [_to_bytes(value)]
            if key == 0:
                self._rebuild_key_map()
            return

        key_bytes = _to_bytes(key)
        row_exists = key_bytes in self._key_map
        row_idx = self._ensure_row(key)

        if isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes)):
            if len(value) == 1 and row_exists:
                self._data[row_idx] = _to_bytes_list(value)
                self._rebuild_key_map()
            else:
                self._data[row_idx] = [key_bytes] + _to_bytes_list(value)
                self._key_map[key_bytes] = row_idx
        else:
            self._data[row_idx] = [key_bytes, _to_bytes(value)]
            self._key_map[key_bytes] = row_idx

    def append(self, row: Sequence[Any]) -> None:
        bs = _to_bytes_list(row)
        self._data.append(bs)
        if row:
            self._rebuild_key_map()

    def __contains__(self, key: KeyType) -> bool:
        return _to_bytes(key) in self._key_map

    def __len__(self) -> int:
        return len(self._data)

    @classmethod
    def deserialize(cls, data: bytes) -> "StrKV":
        if not data:
            return cls()

        if nl := data.endswith(b"\n"):
            data = data.rstrip(b"\n")

        _data: list[list[bytes]] = []
        for line in data.split(b"\n"):
            if line:
                _data.append(line.split(b"|"))

        return cls(_data).with_trailing_newline(nl)

    def with_trailing_newline(self, v: bool = True) -> "StrKV":
        self._trailing_nl = v
        return self

    def serialize(self) -> bytes:
        return b"\n".join(b"|".join(row) for row in self._data) + (b"\n" if self._trailing_nl else b"")

    def __repr__(self) -> str:
        return f"{{{'\\n'.join(f'{x}' for x in ('|'.join(cell.decode('utf-8', 'backslashreplace') for cell in row) for row in self._data))}}}"
