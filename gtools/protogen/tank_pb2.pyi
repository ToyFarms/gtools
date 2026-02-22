from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor
TANK_FIELD_ANIMATION_TYPE: Field
TANK_FIELD_EXTENDED_LEN: Field
TANK_FIELD_FLAGS: Field
TANK_FIELD_FLOAT_VAR: Field
TANK_FIELD_INT_X: Field
TANK_FIELD_INT_Y: Field
TANK_FIELD_JUMP_COUNT: Field
TANK_FIELD_NET_ID: Field
TANK_FIELD_OBJECT_TYPE: Field
TANK_FIELD_PARTICLE_ROTATION: Field
TANK_FIELD_TARGET_NET_ID: Field
TANK_FIELD_TYPE: Field
TANK_FIELD_UNSPECIFIED: Field
TANK_FIELD_VALUE: Field
TANK_FIELD_VECTOR_X: Field
TANK_FIELD_VECTOR_X2: Field
TANK_FIELD_VECTOR_Y: Field
TANK_FIELD_VECTOR_Y2: Field

class FieldValue(_message.Message):
    __slots__ = ["v"]
    V_FIELD_NUMBER: _ClassVar[int]
    v: Field
    def __init__(self, v: _Optional[_Union[Field, str]] = ...) -> None: ...

class Field(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []
