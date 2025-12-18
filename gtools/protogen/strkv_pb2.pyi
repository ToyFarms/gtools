from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FindRow(_message.Message):
    __slots__ = ()
    class Method(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        UNSPECIFIED: _ClassVar[FindRow.Method]
        KEY: _ClassVar[FindRow.Method]
        KEY_ANY: _ClassVar[FindRow.Method]
        INDEX: _ClassVar[FindRow.Method]
    UNSPECIFIED: FindRow.Method
    KEY: FindRow.Method
    KEY_ANY: FindRow.Method
    INDEX: FindRow.Method
    METHOD_FIELD_NUMBER: _ClassVar[int]
    KEY_FIELD_NUMBER: _ClassVar[int]
    INDEX_FIELD_NUMBER: _ClassVar[int]
    method: FindRow.Method
    key: bytes
    index: int
    def __init__(self, method: _Optional[_Union[FindRow.Method, str]] = ..., key: _Optional[bytes] = ..., index: _Optional[int] = ...) -> None: ...

class FindCol(_message.Message):
    __slots__ = ()
    class Method(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        UNSPECIFIED: _ClassVar[FindCol.Method]
        ABSOLUTE: _ClassVar[FindCol.Method]
        RELATIVE: _ClassVar[FindCol.Method]
    UNSPECIFIED: FindCol.Method
    ABSOLUTE: FindCol.Method
    RELATIVE: FindCol.Method
    METHOD_FIELD_NUMBER: _ClassVar[int]
    INDEX_FIELD_NUMBER: _ClassVar[int]
    method: FindCol.Method
    index: int
    def __init__(self, method: _Optional[_Union[FindCol.Method, str]] = ..., index: _Optional[int] = ...) -> None: ...

class Clause(_message.Message):
    __slots__ = ()
    ROW_FIELD_NUMBER: _ClassVar[int]
    COL_FIELD_NUMBER: _ClassVar[int]
    row: FindRow
    col: FindCol
    def __init__(self, row: _Optional[_Union[FindRow, _Mapping]] = ..., col: _Optional[_Union[FindCol, _Mapping]] = ...) -> None: ...

class Query(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[Clause]
    def __init__(self, where: _Optional[_Iterable[_Union[Clause, _Mapping]]] = ...) -> None: ...
