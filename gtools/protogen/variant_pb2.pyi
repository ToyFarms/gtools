from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class VariantClause(_message.Message):
    __slots__ = ()
    V_FIELD_NUMBER: _ClassVar[int]
    v: int
    def __init__(self, v: _Optional[int] = ...) -> None: ...

class VariantQuery(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[VariantClause]
    def __init__(self, where: _Optional[_Iterable[_Union[VariantClause, _Mapping]]] = ...) -> None: ...
