from google.protobuf import any_pb2 as _any_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Op(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    OP_UNSPECIFIED: _ClassVar[Op]
    OP_EQ: _ClassVar[Op]
    OP_EQ_EPS: _ClassVar[Op]
    OP_NEQ: _ClassVar[Op]
    OP_GT: _ClassVar[Op]
    OP_GTE: _ClassVar[Op]
    OP_LT: _ClassVar[Op]
    OP_LTE: _ClassVar[Op]
    OP_BIT_TEST: _ClassVar[Op]
OP_UNSPECIFIED: Op
OP_EQ: Op
OP_EQ_EPS: Op
OP_NEQ: Op
OP_GT: Op
OP_GTE: Op
OP_LT: Op
OP_LTE: Op
OP_BIT_TEST: Op

class BinOp(_message.Message):
    __slots__ = ()
    LVALUE_FIELD_NUMBER: _ClassVar[int]
    OP_FIELD_NUMBER: _ClassVar[int]
    U32_FIELD_NUMBER: _ClassVar[int]
    I32_FIELD_NUMBER: _ClassVar[int]
    FLT_FIELD_NUMBER: _ClassVar[int]
    STR_FIELD_NUMBER: _ClassVar[int]
    BUF_FIELD_NUMBER: _ClassVar[int]
    lvalue: _any_pb2.Any
    op: Op
    u32: int
    i32: int
    flt: float
    str: str
    buf: bytes
    def __init__(self, lvalue: _Optional[_Union[_any_pb2.Any, _Mapping]] = ..., op: _Optional[_Union[Op, str]] = ..., u32: _Optional[int] = ..., i32: _Optional[int] = ..., flt: _Optional[float] = ..., str: _Optional[str] = ..., buf: _Optional[bytes] = ...) -> None: ...
