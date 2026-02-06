from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class State(_message.Message):
    __slots__ = ()
    WORLD_FIELD_NUMBER: _ClassVar[int]
    ME_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    INVENTORY_FIELD_NUMBER: _ClassVar[int]
    world: World
    me: Me
    status: int
    inventory: Inventory
    def __init__(self, world: _Optional[_Union[World, _Mapping]] = ..., me: _Optional[_Union[Me, _Mapping]] = ..., status: _Optional[int] = ..., inventory: _Optional[_Union[Inventory, _Mapping]] = ...) -> None: ...

class Inventory(_message.Message):
    __slots__ = ()
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    items: _containers.RepeatedCompositeFieldContainer[Item]
    def __init__(self, items: _Optional[_Iterable[_Union[Item, _Mapping]]] = ...) -> None: ...

class CharacterState(_message.Message):
    __slots__ = ()
    NET_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_RANGE_FIELD_NUMBER: _ClassVar[int]
    PUNCH_RANGE_FIELD_NUMBER: _ClassVar[int]
    FLAGS_FIELD_NUMBER: _ClassVar[int]
    GRAVITY_FIELD_NUMBER: _ClassVar[int]
    VELOCITY_FIELD_NUMBER: _ClassVar[int]
    ACCELERATION_FIELD_NUMBER: _ClassVar[int]
    VELOCITY_IN_WATER_FIELD_NUMBER: _ClassVar[int]
    JUMP_STRENGTH_FIELD_NUMBER: _ClassVar[int]
    net_id: int
    build_range: int
    punch_range: int
    flags: int
    gravity: float
    velocity: float
    acceleration: float
    velocity_in_water: float
    jump_strength: float
    def __init__(self, net_id: _Optional[int] = ..., build_range: _Optional[int] = ..., punch_range: _Optional[int] = ..., flags: _Optional[int] = ..., gravity: _Optional[float] = ..., velocity: _Optional[float] = ..., acceleration: _Optional[float] = ..., velocity_in_water: _Optional[float] = ..., jump_strength: _Optional[float] = ...) -> None: ...

class Me(_message.Message):
    __slots__ = ()
    NET_ID_FIELD_NUMBER: _ClassVar[int]
    BUILD_RANGE_FIELD_NUMBER: _ClassVar[int]
    PUNCH_RANGE_FIELD_NUMBER: _ClassVar[int]
    POS_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    CHARACTER_FIELD_NUMBER: _ClassVar[int]
    SERVER_PING_FIELD_NUMBER: _ClassVar[int]
    CLIENT_PING_FIELD_NUMBER: _ClassVar[int]
    TIME_SINCE_LOGIN_FIELD_NUMBER: _ClassVar[int]
    TIME_IN_WORLD_FIELD_NUMBER: _ClassVar[int]
    net_id: int
    build_range: int
    punch_range: int
    pos: Vec2F
    state: int
    character: CharacterState
    server_ping: int
    client_ping: int
    time_since_login: float
    time_in_world: float
    def __init__(self, net_id: _Optional[int] = ..., build_range: _Optional[int] = ..., punch_range: _Optional[int] = ..., pos: _Optional[_Union[Vec2F, _Mapping]] = ..., state: _Optional[int] = ..., character: _Optional[_Union[CharacterState, _Mapping]] = ..., server_ping: _Optional[int] = ..., client_ping: _Optional[int] = ..., time_since_login: _Optional[float] = ..., time_in_world: _Optional[float] = ...) -> None: ...

class Item(_message.Message):
    __slots__ = ()
    ID_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    FLAGS_FIELD_NUMBER: _ClassVar[int]
    id: int
    amount: int
    flags: int
    def __init__(self, id: _Optional[int] = ..., amount: _Optional[int] = ..., flags: _Optional[int] = ...) -> None: ...

class Vec2I(_message.Message):
    __slots__ = ()
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    x: int
    y: int
    def __init__(self, x: _Optional[int] = ..., y: _Optional[int] = ...) -> None: ...

class Vec4I(_message.Message):
    __slots__ = ()
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    W_FIELD_NUMBER: _ClassVar[int]
    H_FIELD_NUMBER: _ClassVar[int]
    x: int
    y: int
    w: int
    h: int
    def __init__(self, x: _Optional[int] = ..., y: _Optional[int] = ..., w: _Optional[int] = ..., h: _Optional[int] = ...) -> None: ...

class Vec2F(_message.Message):
    __slots__ = ()
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    x: float
    y: float
    def __init__(self, x: _Optional[float] = ..., y: _Optional[float] = ...) -> None: ...

class Player(_message.Message):
    __slots__ = ()
    SPAWN_FIELD_NUMBER: _ClassVar[int]
    NETID_FIELD_NUMBER: _ClassVar[int]
    USERID_FIELD_NUMBER: _ClassVar[int]
    EID_FIELD_NUMBER: _ClassVar[int]
    IP_FIELD_NUMBER: _ClassVar[int]
    COLRECT_FIELD_NUMBER: _ClassVar[int]
    POSXY_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    TITLEICON_FIELD_NUMBER: _ClassVar[int]
    COUNTRY_FIELD_NUMBER: _ClassVar[int]
    INVIS_FIELD_NUMBER: _ClassVar[int]
    MSTATE_FIELD_NUMBER: _ClassVar[int]
    SMSTATE_FIELD_NUMBER: _ClassVar[int]
    ONLINEID_FIELD_NUMBER: _ClassVar[int]
    FLAGS_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    spawn: bytes
    netID: int
    userID: int
    eid: bytes
    ip: bytes
    colrect: Vec4I
    posXY: Vec2F
    name: bytes
    titleIcon: bytes
    country: bytes
    invis: int
    mstate: int
    smstate: int
    onlineID: bytes
    flags: int
    state: CharacterState
    def __init__(self, spawn: _Optional[bytes] = ..., netID: _Optional[int] = ..., userID: _Optional[int] = ..., eid: _Optional[bytes] = ..., ip: _Optional[bytes] = ..., colrect: _Optional[_Union[Vec4I, _Mapping]] = ..., posXY: _Optional[_Union[Vec2F, _Mapping]] = ..., name: _Optional[bytes] = ..., titleIcon: _Optional[bytes] = ..., country: _Optional[bytes] = ..., invis: _Optional[int] = ..., mstate: _Optional[int] = ..., smstate: _Optional[int] = ..., onlineID: _Optional[bytes] = ..., flags: _Optional[int] = ..., state: _Optional[_Union[CharacterState, _Mapping]] = ...) -> None: ...

class DroppedItem(_message.Message):
    __slots__ = ()
    ID_FIELD_NUMBER: _ClassVar[int]
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    AMOUNT_FIELD_NUMBER: _ClassVar[int]
    FLAGS_FIELD_NUMBER: _ClassVar[int]
    UID_FIELD_NUMBER: _ClassVar[int]
    id: int
    x: float
    y: float
    amount: int
    flags: int
    uid: int
    def __init__(self, id: _Optional[int] = ..., x: _Optional[float] = ..., y: _Optional[float] = ..., amount: _Optional[int] = ..., flags: _Optional[int] = ..., uid: _Optional[int] = ...) -> None: ...

class Dropped(_message.Message):
    __slots__ = ()
    NB_ITEMS_FIELD_NUMBER: _ClassVar[int]
    LAST_UID_FIELD_NUMBER: _ClassVar[int]
    ITEMS_FIELD_NUMBER: _ClassVar[int]
    nb_items: int
    last_uid: int
    items: _containers.RepeatedCompositeFieldContainer[DroppedItem]
    def __init__(self, nb_items: _Optional[int] = ..., last_uid: _Optional[int] = ..., items: _Optional[_Iterable[_Union[DroppedItem, _Mapping]]] = ...) -> None: ...

class Tile(_message.Message):
    __slots__ = ()
    FG_ID_FIELD_NUMBER: _ClassVar[int]
    BG_ID_FIELD_NUMBER: _ClassVar[int]
    PARENT_BLOCK_INDEX_FIELD_NUMBER: _ClassVar[int]
    FLAGS_FIELD_NUMBER: _ClassVar[int]
    EXTRA_FIELD_NUMBER: _ClassVar[int]
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    LOCK_BLOCK_INDEX_FIELD_NUMBER: _ClassVar[int]
    JSON_DATA_FIELD_NUMBER: _ClassVar[int]
    fg_id: int
    bg_id: int
    parent_block_index: int
    flags: int
    extra: bytes
    x: int
    y: int
    lock_block_index: int
    json_data: bytes
    def __init__(self, fg_id: _Optional[int] = ..., bg_id: _Optional[int] = ..., parent_block_index: _Optional[int] = ..., flags: _Optional[int] = ..., extra: _Optional[bytes] = ..., x: _Optional[int] = ..., y: _Optional[int] = ..., lock_block_index: _Optional[int] = ..., json_data: _Optional[bytes] = ...) -> None: ...

class WorldInner(_message.Message):
    __slots__ = ()
    NAME_FIELD_NUMBER: _ClassVar[int]
    WIDTH_FIELD_NUMBER: _ClassVar[int]
    HEIGHT_FIELD_NUMBER: _ClassVar[int]
    NB_TILES_FIELD_NUMBER: _ClassVar[int]
    TILES_FIELD_NUMBER: _ClassVar[int]
    DROPPED_FIELD_NUMBER: _ClassVar[int]
    GARBAGE_START_FIELD_NUMBER: _ClassVar[int]
    name: bytes
    width: int
    height: int
    nb_tiles: int
    tiles: _containers.RepeatedCompositeFieldContainer[Tile]
    dropped: Dropped
    garbage_start: int
    def __init__(self, name: _Optional[bytes] = ..., width: _Optional[int] = ..., height: _Optional[int] = ..., nb_tiles: _Optional[int] = ..., tiles: _Optional[_Iterable[_Union[Tile, _Mapping]]] = ..., dropped: _Optional[_Union[Dropped, _Mapping]] = ..., garbage_start: _Optional[int] = ...) -> None: ...

class World(_message.Message):
    __slots__ = ()
    INNER_FIELD_NUMBER: _ClassVar[int]
    PLAYER_FIELD_NUMBER: _ClassVar[int]
    inner: WorldInner
    player: _containers.RepeatedCompositeFieldContainer[Player]
    def __init__(self, inner: _Optional[_Union[WorldInner, _Mapping]] = ..., player: _Optional[_Iterable[_Union[Player, _Mapping]]] = ...) -> None: ...
