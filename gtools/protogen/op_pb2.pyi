from google.protobuf import any_pb2 as _any_pb2
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Mapping as _Mapping, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor
OP_BIT_TEST: Op
OP_CONTAINS: Op
OP_ENDSWITH: Op
OP_EQ: Op
OP_EQ_EPS: Op
OP_GT: Op
OP_GTE: Op
OP_LIKE: Op
OP_LT: Op
OP_LTE: Op
OP_NEQ: Op
OP_STARTSWITH: Op
OP_UNSPECIFIED: Op

class BinOp(_message.Message):
    __slots__ = ["buf", "flt", "i32", "lvalue", "op", "str", "u32", "vec2", "vec3"]
    BUF_FIELD_NUMBER: _ClassVar[int]
    FLT_FIELD_NUMBER: _ClassVar[int]
    I32_FIELD_NUMBER: _ClassVar[int]
    LVALUE_FIELD_NUMBER: _ClassVar[int]
    OP_FIELD_NUMBER: _ClassVar[int]
    STR_FIELD_NUMBER: _ClassVar[int]
    U32_FIELD_NUMBER: _ClassVar[int]
    VEC2_FIELD_NUMBER: _ClassVar[int]
    VEC3_FIELD_NUMBER: _ClassVar[int]
    buf: bytes
    flt: float
    i32: int
    lvalue: _any_pb2.Any
    op: Op
    str: str
    u32: int
    vec2: Vec2
    vec3: Vec3
    def __init__(self, lvalue: _Optional[_Union[_any_pb2.Any, _Mapping]] = ..., op: _Optional[_Union[Op, str]] = ..., u32: _Optional[int] = ..., i32: _Optional[int] = ..., flt: _Optional[float] = ..., str: _Optional[str] = ..., buf: _Optional[bytes] = ..., vec2: _Optional[_Union[Vec2, _Mapping]] = ..., vec3: _Optional[_Union[Vec3, _Mapping]] = ...) -> None: ...

class Vec2(_message.Message):
    __slots__ = ["x", "y"]
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    x: float
    y: float
    def __init__(self, x: _Optional[float] = ..., y: _Optional[float] = ...) -> None: ...

class Vec3(_message.Message):
    __slots__ = ["x", "y", "z"]
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    Z_FIELD_NUMBER: _ClassVar[int]
    x: float
    y: float
    z: float
    def __init__(self, x: _Optional[float] = ..., y: _Optional[float] = ..., z: _Optional[float] = ...) -> None: ...

class Op(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []
