from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Clause(_message.Message):
    __slots__ = ["col", "row"]
    COL_FIELD_NUMBER: _ClassVar[int]
    ROW_FIELD_NUMBER: _ClassVar[int]
    col: FindCol
    row: FindRow
    def __init__(self, row: _Optional[_Union[FindRow, _Mapping]] = ..., col: _Optional[_Union[FindCol, _Mapping]] = ...) -> None: ...

class FindCol(_message.Message):
    __slots__ = ["index", "method"]
    class Method(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    ABSOLUTE: FindCol.Method
    INDEX_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    RELATIVE: FindCol.Method
    UNSPECIFIED: FindCol.Method
    index: int
    method: FindCol.Method
    def __init__(self, method: _Optional[_Union[FindCol.Method, str]] = ..., index: _Optional[int] = ...) -> None: ...

class FindRow(_message.Message):
    __slots__ = ["index", "key", "method"]
    class Method(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    INDEX: FindRow.Method
    INDEX_FIELD_NUMBER: _ClassVar[int]
    KEY: FindRow.Method
    KEY_ANY: FindRow.Method
    KEY_FIELD_NUMBER: _ClassVar[int]
    METHOD_FIELD_NUMBER: _ClassVar[int]
    UNSPECIFIED: FindRow.Method
    index: int
    key: bytes
    method: FindRow.Method
    def __init__(self, method: _Optional[_Union[FindRow.Method, str]] = ..., key: _Optional[bytes] = ..., index: _Optional[int] = ...) -> None: ...

class Query(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[Clause]
    def __init__(self, where: _Optional[_Iterable[_Union[Clause, _Mapping]]] = ...) -> None: ...
