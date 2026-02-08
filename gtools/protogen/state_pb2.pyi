import growtopia_pb2 as _growtopia_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class StateUpdateWhat(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    STATE_UNSPECIFIED: _ClassVar[StateUpdateWhat]
    STATE_PLAYER_UPDATE: _ClassVar[StateUpdateWhat]
    STATE_SET_MY_PLAYER: _ClassVar[StateUpdateWhat]
    STATE_SEND_INVENTORY: _ClassVar[StateUpdateWhat]
    STATE_MODIFY_INVENTORY: _ClassVar[StateUpdateWhat]
    STATE_ENTER_WORLD: _ClassVar[StateUpdateWhat]
    STATE_EXIT_WORLD: _ClassVar[StateUpdateWhat]
    STATE_PLAYER_JOIN: _ClassVar[StateUpdateWhat]
    STATE_PLAYER_LEAVE: _ClassVar[StateUpdateWhat]
    STATE_MODIFY_WORLD: _ClassVar[StateUpdateWhat]
    STATE_MODIFY_WORLD_BATCHED: _ClassVar[StateUpdateWhat]
    STATE_MODIFY_ITEM: _ClassVar[StateUpdateWhat]
    STATE_UPDATE_STATUS: _ClassVar[StateUpdateWhat]
    STATE_SET_CHARACTER_STATE: _ClassVar[StateUpdateWhat]
    STATE_SET_MY_TELEMETRY: _ClassVar[StateUpdateWhat]
    STATE_SEND_LOCK: _ClassVar[StateUpdateWhat]
    STATE_UPDATE_TREE_STATE: _ClassVar[StateUpdateWhat]
STATE_UNSPECIFIED: StateUpdateWhat
STATE_PLAYER_UPDATE: StateUpdateWhat
STATE_SET_MY_PLAYER: StateUpdateWhat
STATE_SEND_INVENTORY: StateUpdateWhat
STATE_MODIFY_INVENTORY: StateUpdateWhat
STATE_ENTER_WORLD: StateUpdateWhat
STATE_EXIT_WORLD: StateUpdateWhat
STATE_PLAYER_JOIN: StateUpdateWhat
STATE_PLAYER_LEAVE: StateUpdateWhat
STATE_MODIFY_WORLD: StateUpdateWhat
STATE_MODIFY_WORLD_BATCHED: StateUpdateWhat
STATE_MODIFY_ITEM: StateUpdateWhat
STATE_UPDATE_STATUS: StateUpdateWhat
STATE_SET_CHARACTER_STATE: StateUpdateWhat
STATE_SET_MY_TELEMETRY: StateUpdateWhat
STATE_SEND_LOCK: StateUpdateWhat
STATE_UPDATE_TREE_STATE: StateUpdateWhat

class StateUpdate(_message.Message):
    __slots__ = ()
    WHAT_FIELD_NUMBER: _ClassVar[int]
    PLAYER_UPDATE_FIELD_NUMBER: _ClassVar[int]
    SET_MY_PLAYER_FIELD_NUMBER: _ClassVar[int]
    SEND_INVENTORY_FIELD_NUMBER: _ClassVar[int]
    MODIFY_INVENTORY_FIELD_NUMBER: _ClassVar[int]
    ENTER_WORLD_FIELD_NUMBER: _ClassVar[int]
    PLAYER_JOIN_FIELD_NUMBER: _ClassVar[int]
    PLAYER_LEAVE_FIELD_NUMBER: _ClassVar[int]
    MODIFY_WORLD_FIELD_NUMBER: _ClassVar[int]
    MODIFY_WORLD_BATCHED_FIELD_NUMBER: _ClassVar[int]
    MODIFY_ITEM_FIELD_NUMBER: _ClassVar[int]
    UPDATE_STATUS_FIELD_NUMBER: _ClassVar[int]
    CHARACTER_STATE_FIELD_NUMBER: _ClassVar[int]
    SET_MY_TELEMETRY_FIELD_NUMBER: _ClassVar[int]
    SEND_LOCK_FIELD_NUMBER: _ClassVar[int]
    UPDATE_TREE_STATE_FIELD_NUMBER: _ClassVar[int]
    what: StateUpdateWhat
    player_update: PlayerUpdate
    set_my_player: int
    send_inventory: _growtopia_pb2.Inventory
    modify_inventory: ModifyInventory
    enter_world: EnterWorld
    player_join: _growtopia_pb2.Player
    player_leave: int
    modify_world: ModifyWorld
    modify_world_batched: ModifyWorldBatched
    modify_item: ModifyItem
    update_status: int
    character_state: _growtopia_pb2.CharacterState
    set_my_telemetry: SetMyTelemetry
    send_lock: SendLock
    update_tree_state: UpdateTreeState
    def __init__(self, what: _Optional[_Union[StateUpdateWhat, str]] = ..., player_update: _Optional[_Union[PlayerUpdate, _Mapping]] = ..., set_my_player: _Optional[int] = ..., send_inventory: _Optional[_Union[_growtopia_pb2.Inventory, _Mapping]] = ..., modify_inventory: _Optional[_Union[ModifyInventory, _Mapping]] = ..., enter_world: _Optional[_Union[EnterWorld, _Mapping]] = ..., player_join: _Optional[_Union[_growtopia_pb2.Player, _Mapping]] = ..., player_leave: _Optional[int] = ..., modify_world: _Optional[_Union[ModifyWorld, _Mapping]] = ..., modify_world_batched: _Optional[_Union[ModifyWorldBatched, _Mapping]] = ..., modify_item: _Optional[_Union[ModifyItem, _Mapping]] = ..., update_status: _Optional[int] = ..., character_state: _Optional[_Union[_growtopia_pb2.CharacterState, _Mapping]] = ..., set_my_telemetry: _Optional[_Union[SetMyTelemetry, _Mapping]] = ..., send_lock: _Optional[_Union[SendLock, _Mapping]] = ..., update_tree_state: _Optional[_Union[UpdateTreeState, _Mapping]] = ...) -> None: ...

class UpdateTreeState(_message.Message):
    __slots__ = ()
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    ITEM_ID_FIELD_NUMBER: _ClassVar[int]
    HARVEST_FIELD_NUMBER: _ClassVar[int]
    ADD_SPAWN_SEEDS_FLAG_FIELD_NUMBER: _ClassVar[int]
    ADD_SEEDLING_FLAG_FIELD_NUMBER: _ClassVar[int]
    x: int
    y: int
    item_id: int
    harvest: bool
    add_spawn_seeds_flag: bool
    add_seedling_flag: bool
    def __init__(self, x: _Optional[int] = ..., y: _Optional[int] = ..., item_id: _Optional[int] = ..., harvest: _Optional[bool] = ..., add_spawn_seeds_flag: _Optional[bool] = ..., add_seedling_flag: _Optional[bool] = ...) -> None: ...

class SendLock(_message.Message):
    __slots__ = ()
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    LOCK_OWNER_ID_FIELD_NUMBER: _ClassVar[int]
    LOCK_ITEM_ID_FIELD_NUMBER: _ClassVar[int]
    TILES_AFFECTED_FIELD_NUMBER: _ClassVar[int]
    x: int
    y: int
    lock_owner_id: int
    lock_item_id: int
    tiles_affected: _containers.RepeatedScalarFieldContainer[int]
    def __init__(self, x: _Optional[int] = ..., y: _Optional[int] = ..., lock_owner_id: _Optional[int] = ..., lock_item_id: _Optional[int] = ..., tiles_affected: _Optional[_Iterable[int]] = ...) -> None: ...

class ModifyWorld(_message.Message):
    __slots__ = ()
    class Op(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        OP_UNSPECIFIED: _ClassVar[ModifyWorld.Op]
        OP_REPLACE: _ClassVar[ModifyWorld.Op]
        OP_PLACE: _ClassVar[ModifyWorld.Op]
        OP_DESTROY: _ClassVar[ModifyWorld.Op]
        OP_UPDATE_EXTRA_DATA: _ClassVar[ModifyWorld.Op]
    OP_UNSPECIFIED: ModifyWorld.Op
    OP_REPLACE: ModifyWorld.Op
    OP_PLACE: ModifyWorld.Op
    OP_DESTROY: ModifyWorld.Op
    OP_UPDATE_EXTRA_DATA: ModifyWorld.Op
    OP_FIELD_NUMBER: _ClassVar[int]
    TILE_FIELD_NUMBER: _ClassVar[int]
    EXTRA_FIELD_NUMBER: _ClassVar[int]
    op: ModifyWorld.Op
    tile: _growtopia_pb2.Tile
    extra: bytes
    def __init__(self, op: _Optional[_Union[ModifyWorld.Op, str]] = ..., tile: _Optional[_Union[_growtopia_pb2.Tile, _Mapping]] = ..., extra: _Optional[bytes] = ...) -> None: ...

class ModifyWorldBatched(_message.Message):
    __slots__ = ()
    EVENTS_FIELD_NUMBER: _ClassVar[int]
    events: _containers.RepeatedCompositeFieldContainer[ModifyWorld]
    def __init__(self, events: _Optional[_Iterable[_Union[ModifyWorld, _Mapping]]] = ...) -> None: ...

class SetMyTelemetry(_message.Message):
    __slots__ = ()
    SERVER_PING_FIELD_NUMBER: _ClassVar[int]
    CLIENT_PING_FIELD_NUMBER: _ClassVar[int]
    TIME_SINCE_LOGIN_FIELD_NUMBER: _ClassVar[int]
    TIME_IN_WORLD_FIELD_NUMBER: _ClassVar[int]
    server_ping: int
    client_ping: int
    time_since_login: float
    time_in_world: float
    def __init__(self, server_ping: _Optional[int] = ..., client_ping: _Optional[int] = ..., time_since_login: _Optional[float] = ..., time_in_world: _Optional[float] = ...) -> None: ...

class ModifyItem(_message.Message):
    __slots__ = ()
    class Op(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        OP_UNSPECIFIED: _ClassVar[ModifyItem.Op]
        OP_CREATE: _ClassVar[ModifyItem.Op]
        OP_SET_AMOUNT: _ClassVar[ModifyItem.Op]
        OP_TAKE: _ClassVar[ModifyItem.Op]
    OP_UNSPECIFIED: ModifyItem.Op
    OP_CREATE: ModifyItem.Op
    OP_SET_AMOUNT: ModifyItem.Op
    OP_TAKE: ModifyItem.Op
    OP_FIELD_NUMBER: _ClassVar[int]
    ITEM_ID_FIELD_NUMBER: _ClassVar[int]
    UID_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    FLAGS_FIELD_NUMBER: _ClassVar[int]
    op: ModifyItem.Op
    item_id: int
    uid: int
    amount: int
    x: float
    y: float
    flags: int
    def __init__(self, op: _Optional[_Union[ModifyItem.Op, str]] = ..., item_id: _Optional[int] = ..., uid: _Optional[int] = ..., amount: _Optional[int] = ..., x: _Optional[float] = ..., y: _Optional[float] = ..., flags: _Optional[int] = ...) -> None: ...

class EnterWorld(_message.Message):
    __slots__ = ()
    ENTER_WORLD_FIELD_NUMBER: _ClassVar[int]
    DOOR_ID_FIELD_NUMBER: _ClassVar[int]
    enter_world: _growtopia_pb2.World
    door_id: bytes
    def __init__(self, enter_world: _Optional[_Union[_growtopia_pb2.World, _Mapping]] = ..., door_id: _Optional[bytes] = ...) -> None: ...

class ModifyInventory(_message.Message):
    __slots__ = ()
    ID_FIELD_NUMBER: _ClassVar[int]
    TO_ADD_FIELD_NUMBER: _ClassVar[int]
    id: int
    to_add: int
    def __init__(self, id: _Optional[int] = ..., to_add: _Optional[int] = ...) -> None: ...

class PlayerUpdate(_message.Message):
    __slots__ = ()
    NET_ID_FIELD_NUMBER: _ClassVar[int]
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    FLAGS_FIELD_NUMBER: _ClassVar[int]
    net_id: int
    x: float
    y: float
    flags: int
    def __init__(self, net_id: _Optional[int] = ..., x: _Optional[float] = ..., y: _Optional[float] = ..., flags: _Optional[int] = ...) -> None: ...
