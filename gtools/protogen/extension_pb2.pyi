import growtopia_pb2 as _growtopia_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Capability(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    CAPABILITY_UNSPECIFIED: _ClassVar[Capability]
    CAPABILITY_MODIFY: _ClassVar[Capability]
    CAPABILITY_CANCEL: _ClassVar[Capability]
    CAPABILITY_LISTEN: _ClassVar[Capability]
CAPABILITY_UNSPECIFIED: Capability
CAPABILITY_MODIFY: Capability
CAPABILITY_CANCEL: Capability
CAPABILITY_LISTEN: Capability

class Packet(_message.Message):
    __slots__ = ()
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        TYPE_UNSPECIFIED: _ClassVar[Packet.Type]
        TYPE_HANDSHAKE: _ClassVar[Packet.Type]
        TYPE_CAPABILITY_REQUEST: _ClassVar[Packet.Type]
        TYPE_CAPABILITY_RESPONSE: _ClassVar[Packet.Type]
        TYPE_DISCONNECT: _ClassVar[Packet.Type]
        TYPE_EVENT: _ClassVar[Packet.Type]
        TYPE_FORWARD: _ClassVar[Packet.Type]
        TYPE_CANCEL: _ClassVar[Packet.Type]
    TYPE_UNSPECIFIED: Packet.Type
    TYPE_HANDSHAKE: Packet.Type
    TYPE_CAPABILITY_REQUEST: Packet.Type
    TYPE_CAPABILITY_RESPONSE: Packet.Type
    TYPE_DISCONNECT: Packet.Type
    TYPE_EVENT: Packet.Type
    TYPE_FORWARD: Packet.Type
    TYPE_CANCEL: Packet.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    HANDSHAKE_FIELD_NUMBER: _ClassVar[int]
    CAPABILITY_REQUEST_FIELD_NUMBER: _ClassVar[int]
    CAPABILITY_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    DISCONNECT_FIELD_NUMBER: _ClassVar[int]
    EVENT_FIELD_NUMBER: _ClassVar[int]
    FORWARD_FIELD_NUMBER: _ClassVar[int]
    CANCEL_FIELD_NUMBER: _ClassVar[int]
    type: Packet.Type
    handshake: Handshake
    capability_request: CapabilityRequest
    capability_response: CapabilityResponse
    disconnect: Disconnect
    event: Event
    forward: Forward
    cancel: Cancel
    def __init__(self, type: _Optional[_Union[Packet.Type, str]] = ..., handshake: _Optional[_Union[Handshake, _Mapping]] = ..., capability_request: _Optional[_Union[CapabilityRequest, _Mapping]] = ..., capability_response: _Optional[_Union[CapabilityResponse, _Mapping]] = ..., disconnect: _Optional[_Union[Disconnect, _Mapping]] = ..., event: _Optional[_Union[Event, _Mapping]] = ..., forward: _Optional[_Union[Forward, _Mapping]] = ..., cancel: _Optional[_Union[Cancel, _Mapping]] = ...) -> None: ...

class Handshake(_message.Message):
    __slots__ = ()
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class CapabilityRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CapabilityResponse(_message.Message):
    __slots__ = ()
    CAPABILITY_FIELD_NUMBER: _ClassVar[int]
    INTEREST_FIELD_NUMBER: _ClassVar[int]
    capability: _containers.RepeatedScalarFieldContainer[Capability]
    interest: _containers.RepeatedCompositeFieldContainer[_growtopia_pb2.Interest]
    def __init__(self, capability: _Optional[_Iterable[_Union[Capability, str]]] = ..., interest: _Optional[_Iterable[_Union[_growtopia_pb2.Interest, _Mapping]]] = ...) -> None: ...

class Disconnect(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Event(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Forward(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Cancel(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
