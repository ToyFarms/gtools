from __future__ import annotations
import typing as t
from collections.abc import Sequence, Iterable
from typing import overload, Any, Union, Generic, TypeVar
from dataclasses import dataclass
import copy
import bisect

# Type variables for generic typing
T = TypeVar('T')
BytesConvertible = Union[str, bytes, int, float, bool]

class _Empty:
    """Sentinel for empty cells."""
    __slots__ = ()
    
    def __bytes__(self) -> bytes:
        return b''
    
    def __str__(self) -> str:
        return ''
    
    def __repr__(self) -> str:
        return '<EMPTY>'
    
    def __bool__(self) -> bool:
        return False

EMPTY = _Empty()

@dataclass(slots=True)
class _Cell:
    """Internal cell representation for efficient storage."""
    value: bytes
    
    def to_bytes(self) -> bytes:
        return self.value
    
    @classmethod
    def from_value(cls, value: BytesConvertible) -> _Cell:
        if isinstance(value, bytes):
            return cls(value)
        elif isinstance(value, str):
            return cls(value.encode('utf-8'))
        else:
            return cls(str(value).encode('utf-8'))

class _Row:
    """Internal row representation for efficient operations."""
    __slots__ = ('cells', '_key_cache')
    
    def __init__(self, cells: list[_Cell] | None = None):
        self.cells = cells if cells is not None else []
        self._key_cache: bytes | None = None
    
    @property
    def key(self) -> bytes:
        if not self.cells:
            return b''
        if self._key_cache is None:
            self._key_cache = self.cells[0].value
        return self._key_cache
    
    def __len__(self) -> int:
        return len(self.cells)
    
    def to_bytes(self) -> bytes:
        return b'|'.join(cell.to_bytes() for cell in self.cells)
    
    def copy(self) -> _Row:
        return _Row([_Cell(cell.value) for cell in self.cells])
    
    def extend(self, values: Iterable[BytesConvertible]) -> None:
        for value in values:
            self.cells.append(_Cell.from_value(value))
        self._key_cache = None
    
    def insert(self, index: int, value: BytesConvertible) -> None:
        self.cells.insert(index, _Cell.from_value(value))
        self._key_cache = None
    
    def remove(self, index: int) -> None:
        if 0 <= index < len(self.cells):
            del self.cells[index]
            self._key_cache = None
    
    def slice(self, start: int | None = None, stop: int | None = None, step: int | None = None) -> list[bytes]:
        return [cell.value for cell in self.cells[start:stop:step]]
    
    def replace_slice(self, start: int, stop: int, values: list[_Cell]) -> None:
        """Efficient slice replacement."""
        del self.cells[start:stop]
        for i, cell in enumerate(values):
            self.cells.insert(start + i, cell)
        self._key_cache = None

class StrKV:
    """Efficient string-key-value table storage."""
    
    __slots__ = ('_rows', '_key_index', '_data_index', '_dirty')
    
    def __init__(self) -> None:
        self._rows: list[_Row] = []
        self._key_index: dict[bytes, int] = {}  # key -> row index
        self._data_index: dict[bytes, list[int]] = {}  # value -> list of row indices
        self._dirty: bool = False  # Flag for index rebuild
    
    def _ensure_index(self) -> None:
        """Rebuild indexes if dirty."""
        if not self._dirty:
            return
        
        self._key_index.clear()
        self._data_index.clear()
        
        for idx, row in enumerate(self._rows):
            if row.cells:
                key = row.key
                self._key_index[key] = idx
                
                for cell in row.cells:
                    value = cell.value
                    if value not in self._data_index:
                        self._data_index[value] = []
                    self._data_index[value].append(idx)
        
        self._dirty = False
    
    def _to_bytes(self, value: BytesConvertible) -> bytes:
        """Convert any value to bytes."""
        if isinstance(value, bytes):
            return value
        elif isinstance(value, str):
            return value.encode('utf-8')
        elif isinstance(value, _Empty):
            return b''
        else:
            return str(value).encode('utf-8')
    
    def _to_cell(self, value: BytesConvertible) -> _Cell:
        """Convert to internal cell representation."""
        return _Cell(self._to_bytes(value))
    
    def _get_row_index(self, key: BytesConvertible | int) -> int:
        """Get row index from key (bytes/str) or index (int)."""
        if isinstance(key, int):
            if key < 0:
                key = len(self._rows) + key
            if 0 <= key < len(self._rows):
                return key
            raise IndexError(f"Row index {key} out of range")
        
        # For bytes/string keys
        self._ensure_index()
        key_bytes = self._to_bytes(key)
        if key_bytes in self._key_index:
            return self._key_index[key_bytes]
        raise KeyError(f"Key {key!r} not found")
    
    def _get_cell_value(self, row_idx: int, col_idx: int) -> bytes:
        """Get cell value with bounds checking."""
        row = self._rows[row_idx]
        if 0 <= col_idx < len(row.cells):
            return row.cells[col_idx].value
        return b''
    
    # Overloaded getitem
    @overload
    def __getitem__(self, key: int) -> _RowProxy: ...
    
    @overload
    def __getitem__(self, key: BytesConvertible) -> _RowProxy: ...
    
    @overload
    def __getitem__(self, key: tuple[BytesConvertible | int, int]) -> bytes: ...
    
    @overload
    def __getitem__(self, key: tuple[BytesConvertible | int, slice]) -> list[bytes]: ...
    
    def __getitem__(self, key: Any) -> Any:
        """Get row, cell, or slice."""
        if isinstance(key, tuple):
            # Get cell or slice
            row_key, col_key = key
            row_idx = self._get_row_index(row_key)
            row = self._rows[row_idx]
            
            if isinstance(col_key, int):
                # Single cell
                return self._get_cell_value(row_idx, col_key)
            else:
                # Slice
                start, stop, step = col_key.indices(len(row.cells))
                return row.slice(start, stop, step)
        
        # Get entire row
        row_idx = self._get_row_index(key)
        return _RowProxy(self, row_idx)
    
    # Overloaded setitem
    @overload
    def __setitem__(self, key: int, value: BytesConvertible | Sequence[BytesConvertible]) -> None: ...
    
    @overload
    def __setitem__(self, key: BytesConvertible, value: BytesConvertible | Sequence[BytesConvertible]) -> None: ...
    
    @overload
    def __setitem__(self, key: tuple[BytesConvertible | int, int], value: BytesConvertible | Sequence[BytesConvertible]) -> None: ...
    
    @overload
    def __setitem__(self, key: tuple[BytesConvertible | int, slice], value: BytesConvertible | Sequence[BytesConvertible]) -> None: ...
    
    def __setitem__(self, key: Any, value: Any) -> None:
        """Set row, cell, or slice."""
        self._dirty = True
        
        if isinstance(key, tuple):
            # Set cell or slice
            row_key, col_key = key
            row_idx = self._get_row_index(row_key)
            row = self._rows[row_idx]
            
            if isinstance(col_key, int):
                # Single cell
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    # Insert list at position
                    cells = [self._to_cell(v) for v in value]
                    # Remove existing cell if needed
                    if 0 <= col_key < len(row.cells):
                        row.remove(col_key)
                    for i, cell in enumerate(cells):
                        row.insert(col_key + i, cell.value)
                else:
                    # Set single value
                    cell = self._to_cell(value)
                    if col_key < 0:
                        col_key = len(row.cells) + col_key + 1
                    
                    if col_key < 0:
                        col_key = 0
                    
                    # Extend row with empty cells if needed
                    while len(row.cells) <= col_key:
                        row.cells.append(_Cell(b''))
                    
                    row.cells[col_key] = cell
            else:
                # Slice - inclusive
                start = col_key.start if col_key.start is not None else 0
                stop = col_key.stop if col_key.stop is not None else len(row.cells)
                
                # Convert to exclusive stop
                if stop != -1:
                    stop += 1
                
                # Handle negative indices
                if start < 0:
                    start = len(row.cells) + start
                if stop < 0:
                    stop = len(row.cells) + stop + 1
                
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                    cells = [self._to_cell(v) for v in value]
                else:
                    cells = [self._to_cell(value)]
                
                row.replace_slice(start, stop, cells)
        else:
            # Set entire row
            row_idx = self._get_row_index(key)
            
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                # Replace entire row with sequence
                cells = [self._to_cell(v) for v in value]
                self._rows[row_idx] = _Row(cells)
            else:
                # Single value - replace all cells with this value
                cell = self._to_cell(value)
                self._rows[row_idx] = _Row([cell])
    
    def __delitem__(self, key: BytesConvertible | int | tuple[BytesConvertible | int, int]) -> None:
        """Delete row or cell."""
        self._dirty = True
        
        if isinstance(key, tuple):
            # Delete cell
            row_key, col_idx = key
            row_idx = self._get_row_index(row_key)
            row = self._rows[row_idx]
            
            if 0 <= col_idx < len(row.cells):
                row.remove(col_idx)
        else:
            # Delete entire row
            row_idx = self._get_row_index(key)
            del self._rows[row_idx]
    
    def __contains__(self, key: BytesConvertible | int) -> bool:
        """Check if key exists."""
        try:
            self._get_row_index(key)
            return True
        except (KeyError, IndexError):
            return False
    
    def __len__(self) -> int:
        return len(self._rows)
    
    def append(self, key: BytesConvertible | None = None, values: Sequence[BytesConvertible] | None = None) -> None:
        """Append a new row."""
        self._dirty = True
        
        if key is None and values is None:
            self._rows.append(_Row())
        elif values is None:
            self._rows.append(_Row([self._to_cell(key)]))
        else:
            cells = [self._to_cell(key)] + [self._to_cell(v) for v in values]
            self._rows.append(_Row(cells))
    
    @property
    def find(self) -> FindProxy:
        return FindProxy(self)
    
    @property
    def relative(self) -> RelativeProxy:
        return RelativeProxy(self)
    
    def serialize(self) -> bytes:
        """Serialize entire table to bytes."""
        lines = []
        for row in self._rows:
            lines.append(row.to_bytes())
        return b'\n'.join(lines)
    
    @classmethod
    def deserialize(cls, data: bytes) -> StrKV:
        """Deserialize from bytes."""
        instance = cls()
        if not data.strip():
            return instance
        
        for line in data.strip().split(b'\n'):
            if line:
                cells = line.split(b'|')
                row_cells = [_Cell(cell) for cell in cells]
                instance._rows.append(_Row(row_cells))
        
        instance._dirty = True
        return instance

class _RowProxy:
    """Proxy for row operations."""
    
    __slots__ = ('_parent', '_row_idx')
    
    def __init__(self, parent: StrKV, row_idx: int):
        self._parent = parent
        self._row_idx = row_idx
    
    def __getitem__(self, key: int | slice) -> Any:
        """Get cell or slice from this row."""
        if isinstance(key, slice):
            return self._parent._rows[self._row_idx].slice(key.start, key.stop, key.step)
        return self._parent._get_cell_value(self._row_idx, key)
    
    def __setitem__(self, key: int | slice, value: Any) -> None:
        """Set cell or slice in this row."""
        self._parent._dirty = True
        row = self._parent._rows[self._row_idx]
        
        if isinstance(key, slice):
            start = key.start if key.start is not None else 0
            stop = key.stop if key.stop is not None else len(row.cells)
            
            if stop != -1:
                stop += 1
            
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                cells = [self._parent._to_cell(v) for v in value]
            else:
                cells = [self._parent._to_cell(value)]
            
            row.replace_slice(start, stop, cells)
        else:
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                cells = [self._parent._to_cell(v) for v in value]
                # Insert list at position
                if 0 <= key < len(row.cells):
                    row.remove(key)
                for i, cell in enumerate(cells):
                    row.insert(key + i, cell.value)
            else:
                cell = self._parent._to_cell(value)
                if key < 0:
                    key = len(row.cells) + key + 1
                
                if key < 0:
                    key = 0
                
                while len(row.cells) <= key:
                    row.cells.append(_Cell(b''))
                
                row.cells[key] = cell
    
    def append(self, value: BytesConvertible) -> None:
        """Append value to row."""
        self._parent._dirty = True
        row = self._parent._rows[self._row_idx]
        row.cells.append(self._parent._to_cell(value))
    
    def extend(self, values: Iterable[BytesConvertible]) -> None:
        """Extend row with multiple values."""
        self._parent._dirty = True
        row = self._parent._rows[self._row_idx]
        row.extend(values)
    
    def remove(self, col_idx: int | None = None) -> None:
        """Remove cell or entire row."""
        self._parent._dirty = True
        
        if col_idx is None:
            # Remove entire row
            del self._parent._rows[self._row_idx]
        else:
            # Remove cell
            row = self._parent._rows[self._row_idx]
            if 0 <= col_idx < len(row.cells):
                row.remove(col_idx)

class FindProxy:
    """Proxy for find operations."""
    
    __slots__ = ('_parent',)
    
    def __init__(self, parent: StrKV):
        self._parent = parent
    
    def __getitem__(self, key: BytesConvertible | tuple[BytesConvertible, int]) -> _RowProxy:
        """Find row containing value and return proxy."""
        if isinstance(key, tuple):
            value, col_idx = key
            value_bytes = self._parent._to_bytes(value)
            
            # Build index if needed
            self._parent._ensure_index()
            
            if value_bytes in self._parent._data_index:
                for row_idx in self._parent._data_index[value_bytes]:
                    row = self._parent._rows[row_idx]
                    if 0 <= col_idx < len(row.cells) and row.cells[col_idx].value == value_bytes:
                        return _RowProxy(self._parent, row_idx)
            
            raise KeyError(f"Value {value!r} not found at column {col_idx}")
        else:
            # Find first occurrence in any cell
            value_bytes = self._parent._to_bytes(key)
            
            self._parent._ensure_index()
            
            if value_bytes in self._parent._data_index:
                return _RowProxy(self._parent, self._parent._data_index[value_bytes][0])
            
            raise KeyError(f"Value {key!r} not found in any cell")
    
    def __setitem__(self, key: tuple[BytesConvertible, int], value: BytesConvertible) -> None:
        """Set value in found row."""
        row_proxy = self[key]
        row_proxy[-1] = value
    
    def __contains__(self, value: BytesConvertible) -> bool:
        """Check if value exists in any cell."""
        value_bytes = self._parent._to_bytes(value)
        self._parent._ensure_index()
        return value_bytes in self._parent._data_index

class RelativeProxy:
    """Proxy for relative operations."""
    
    __slots__ = ('_parent',)
    
    def __init__(self, parent: StrKV):
        self._parent = parent
    
    def __getitem__(self, key: tuple[BytesConvertible, int]) -> bytes:
        """Get value relative to found cell."""
        value, offset = key
        value_bytes = self._parent._to_bytes(value)
        
        # Find the cell
        self._parent._ensure_index()
        
        if value_bytes not in self._parent._data_index:
            raise KeyError(f"Value {value!r} not found")
        
        for row_idx in self._parent._data_index[value_bytes]:
            row = self._parent._rows[row_idx]
            for col_idx, cell in enumerate(row.cells):
                if cell.value == value_bytes:
                    target_col = col_idx + offset
                    if 0 <= target_col < len(row.cells):
                        return row.cells[target_col].value
                    return b''
        
        raise KeyError(f"Value {value!r} not found")
    
    def __setitem__(self, key: tuple[BytesConvertible, int], value: BytesConvertible) -> None:
        """Set value relative to found cell."""
        val, offset = key
        val_bytes = self._parent._to_bytes(val)
        new_value = self._parent._to_bytes(value)
        
        self._parent._dirty = True
        
        # Find the cell
        self._parent._ensure_index()
        
        if val_bytes not in self._parent._data_index:
            raise KeyError(f"Value {val!r} not found")
        
        for row_idx in self._parent._data_index[val_bytes]:
            row = self._parent._rows[row_idx]
            for col_idx, cell in enumerate(row.cells):
                if cell.value == val_bytes:
                    target_col = col_idx + offset
                    if target_col < 0:
                        target_col = 0
                    
                    while len(row.cells) <= target_col:
                        row.cells.append(_Cell(b''))
                    
                    row.cells[target_col] = _Cell(new_value)
                    return
        
        raise KeyError(f"Value {val!r} not found")
