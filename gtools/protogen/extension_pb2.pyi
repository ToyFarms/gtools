import op_pb2 as _op_pb2
import growtopia_pb2 as _growtopia_pb2
import state_pb2 as _state_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class InterestType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    INTEREST_UNSPECIFIED: _ClassVar[InterestType]
    INTEREST_PEER_CONNECT: _ClassVar[InterestType]
    INTEREST_PEER_DISCONNECT: _ClassVar[InterestType]
    INTEREST_SERVER_HELLO: _ClassVar[InterestType]
    INTEREST_GENERIC_TEXT: _ClassVar[InterestType]
    INTEREST_GAME_MESSAGE: _ClassVar[InterestType]
    INTEREST_TANK_PACKET: _ClassVar[InterestType]
    INTEREST_ERROR: _ClassVar[InterestType]
    INTEREST_TRACK: _ClassVar[InterestType]
    INTEREST_CLIENT_LOG_REQUEST: _ClassVar[InterestType]
    INTEREST_CLIENT_LOG_RESPONSE: _ClassVar[InterestType]
    INTEREST_STATE: _ClassVar[InterestType]
    INTEREST_CALL_FUNCTION: _ClassVar[InterestType]
    INTEREST_UPDATE_STATUS: _ClassVar[InterestType]
    INTEREST_TILE_CHANGE_REQUEST: _ClassVar[InterestType]
    INTEREST_SEND_MAP_DATA: _ClassVar[InterestType]
    INTEREST_SEND_TILE_UPDATE_DATA: _ClassVar[InterestType]
    INTEREST_SEND_TILE_UPDATE_DATA_MULTIPLE: _ClassVar[InterestType]
    INTEREST_TILE_ACTIVATE_REQUEST: _ClassVar[InterestType]
    INTEREST_TILE_APPLY_DAMAGE: _ClassVar[InterestType]
    INTEREST_SEND_INVENTORY_STATE: _ClassVar[InterestType]
    INTEREST_ITEM_ACTIVATE_REQUEST: _ClassVar[InterestType]
    INTEREST_ITEM_ACTIVATE_OBJECT_REQUEST: _ClassVar[InterestType]
    INTEREST_SEND_TILE_TREE_STATE: _ClassVar[InterestType]
    INTEREST_MODIFY_ITEM_INVENTORY: _ClassVar[InterestType]
    INTEREST_ITEM_CHANGE_OBJECT: _ClassVar[InterestType]
    INTEREST_SEND_LOCK: _ClassVar[InterestType]
    INTEREST_SEND_ITEM_DATABASE_DATA: _ClassVar[InterestType]
    INTEREST_SEND_PARTICLE_EFFECT: _ClassVar[InterestType]
    INTEREST_SET_ICON_STATE: _ClassVar[InterestType]
    INTEREST_ITEM_EFFECT: _ClassVar[InterestType]
    INTEREST_SET_CHARACTER_STATE: _ClassVar[InterestType]
    INTEREST_PING_REPLY: _ClassVar[InterestType]
    INTEREST_PING_REQUEST: _ClassVar[InterestType]
    INTEREST_GOT_PUNCHED: _ClassVar[InterestType]
    INTEREST_APP_CHECK_RESPONSE: _ClassVar[InterestType]
    INTEREST_APP_INTEGRITY_FAIL: _ClassVar[InterestType]
    INTEREST_DISCONNECT: _ClassVar[InterestType]
    INTEREST_BATTLE_JOIN: _ClassVar[InterestType]
    INTEREST_BATTLE_EVENT: _ClassVar[InterestType]
    INTEREST_USE_DOOR: _ClassVar[InterestType]
    INTEREST_SEND_PARENTAL: _ClassVar[InterestType]
    INTEREST_GONE_FISHIN: _ClassVar[InterestType]
    INTEREST_STEAM: _ClassVar[InterestType]
    INTEREST_PET_BATTLE: _ClassVar[InterestType]
    INTEREST_NPC: _ClassVar[InterestType]
    INTEREST_SPECIAL: _ClassVar[InterestType]
    INTEREST_SEND_PARTICLE_EFFECT_V2: _ClassVar[InterestType]
    INTEREST_ACTIVATE_ARROW_TO_ITEM: _ClassVar[InterestType]
    INTEREST_SELECT_TILE_INDEX: _ClassVar[InterestType]
    INTEREST_SEND_PLAYER_TRIBUTE_DATA: _ClassVar[InterestType]
    INTEREST_FTUE_SET_ITEM_TO_QUICK_INVENTORY: _ClassVar[InterestType]
    INTEREST_PVE_NPC: _ClassVar[InterestType]
    INTEREST_PVP_CARD_BATTLE: _ClassVar[InterestType]
    INTEREST_PVE_APPLY_PLAYER_DAMAGE: _ClassVar[InterestType]
    INTEREST_PVE_NPC_POSITION_UPDATE: _ClassVar[InterestType]
    INTEREST_SET_EXTRA_MODS: _ClassVar[InterestType]
    INTEREST_ON_STEP_TILE_MOD: _ClassVar[InterestType]
    INTEREST_STATE_UPDATE: _ClassVar[InterestType]

class Direction(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    DIRECTION_UNSPECIFIED: _ClassVar[Direction]
    DIRECTION_CLIENT_TO_SERVER: _ClassVar[Direction]
    DIRECTION_SERVER_TO_CLIENT: _ClassVar[Direction]

class BlockingMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    BLOCKING_MODE_UNSPECIFIED: _ClassVar[BlockingMode]
    BLOCKING_MODE_BLOCK: _ClassVar[BlockingMode]
    BLOCKING_MODE_SEND_AND_FORGET: _ClassVar[BlockingMode]
    BLOCKING_MODE_SEND_AND_CANCEL: _ClassVar[BlockingMode]
    BLOCKING_MODE_ONESHOT: _ClassVar[BlockingMode]
    BLOCKING_MODE_ONESHOT_AND_CANCEL: _ClassVar[BlockingMode]
INTEREST_UNSPECIFIED: InterestType
INTEREST_PEER_CONNECT: InterestType
INTEREST_PEER_DISCONNECT: InterestType
INTEREST_SERVER_HELLO: InterestType
INTEREST_GENERIC_TEXT: InterestType
INTEREST_GAME_MESSAGE: InterestType
INTEREST_TANK_PACKET: InterestType
INTEREST_ERROR: InterestType
INTEREST_TRACK: InterestType
INTEREST_CLIENT_LOG_REQUEST: InterestType
INTEREST_CLIENT_LOG_RESPONSE: InterestType
INTEREST_STATE: InterestType
INTEREST_CALL_FUNCTION: InterestType
INTEREST_UPDATE_STATUS: InterestType
INTEREST_TILE_CHANGE_REQUEST: InterestType
INTEREST_SEND_MAP_DATA: InterestType
INTEREST_SEND_TILE_UPDATE_DATA: InterestType
INTEREST_SEND_TILE_UPDATE_DATA_MULTIPLE: InterestType
INTEREST_TILE_ACTIVATE_REQUEST: InterestType
INTEREST_TILE_APPLY_DAMAGE: InterestType
INTEREST_SEND_INVENTORY_STATE: InterestType
INTEREST_ITEM_ACTIVATE_REQUEST: InterestType
INTEREST_ITEM_ACTIVATE_OBJECT_REQUEST: InterestType
INTEREST_SEND_TILE_TREE_STATE: InterestType
INTEREST_MODIFY_ITEM_INVENTORY: InterestType
INTEREST_ITEM_CHANGE_OBJECT: InterestType
INTEREST_SEND_LOCK: InterestType
INTEREST_SEND_ITEM_DATABASE_DATA: InterestType
INTEREST_SEND_PARTICLE_EFFECT: InterestType
INTEREST_SET_ICON_STATE: InterestType
INTEREST_ITEM_EFFECT: InterestType
INTEREST_SET_CHARACTER_STATE: InterestType
INTEREST_PING_REPLY: InterestType
INTEREST_PING_REQUEST: InterestType
INTEREST_GOT_PUNCHED: InterestType
INTEREST_APP_CHECK_RESPONSE: InterestType
INTEREST_APP_INTEGRITY_FAIL: InterestType
INTEREST_DISCONNECT: InterestType
INTEREST_BATTLE_JOIN: InterestType
INTEREST_BATTLE_EVENT: InterestType
INTEREST_USE_DOOR: InterestType
INTEREST_SEND_PARENTAL: InterestType
INTEREST_GONE_FISHIN: InterestType
INTEREST_STEAM: InterestType
INTEREST_PET_BATTLE: InterestType
INTEREST_NPC: InterestType
INTEREST_SPECIAL: InterestType
INTEREST_SEND_PARTICLE_EFFECT_V2: InterestType
INTEREST_ACTIVATE_ARROW_TO_ITEM: InterestType
INTEREST_SELECT_TILE_INDEX: InterestType
INTEREST_SEND_PLAYER_TRIBUTE_DATA: InterestType
INTEREST_FTUE_SET_ITEM_TO_QUICK_INVENTORY: InterestType
INTEREST_PVE_NPC: InterestType
INTEREST_PVP_CARD_BATTLE: InterestType
INTEREST_PVE_APPLY_PLAYER_DAMAGE: InterestType
INTEREST_PVE_NPC_POSITION_UPDATE: InterestType
INTEREST_SET_EXTRA_MODS: InterestType
INTEREST_ON_STEP_TILE_MOD: InterestType
INTEREST_STATE_UPDATE: InterestType
DIRECTION_UNSPECIFIED: Direction
DIRECTION_CLIENT_TO_SERVER: Direction
DIRECTION_SERVER_TO_CLIENT: Direction
BLOCKING_MODE_UNSPECIFIED: BlockingMode
BLOCKING_MODE_BLOCK: BlockingMode
BLOCKING_MODE_SEND_AND_FORGET: BlockingMode
BLOCKING_MODE_SEND_AND_CANCEL: BlockingMode
BLOCKING_MODE_ONESHOT: BlockingMode
BLOCKING_MODE_ONESHOT_AND_CANCEL: BlockingMode

class Packet(_message.Message):
    __slots__ = ()
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        TYPE_UNSPECIFIED: _ClassVar[Packet.Type]
        TYPE_HANDSHAKE: _ClassVar[Packet.Type]
        TYPE_HANDSHAKE_ACK: _ClassVar[Packet.Type]
        TYPE_CAPABILITY_REQUEST: _ClassVar[Packet.Type]
        TYPE_CAPABILITY_RESPONSE: _ClassVar[Packet.Type]
        TYPE_DISCONNECT: _ClassVar[Packet.Type]
        TYPE_DISCONNECT_ACK: _ClassVar[Packet.Type]
        TYPE_CONNECTED: _ClassVar[Packet.Type]
        TYPE_PENDING_PACKET: _ClassVar[Packet.Type]
        TYPE_STATE_REQUEST: _ClassVar[Packet.Type]
        TYPE_STATE_RESPONSE: _ClassVar[Packet.Type]
        TYPE_STATE_UPDATE: _ClassVar[Packet.Type]
        TYPE_PUSH_PACKET: _ClassVar[Packet.Type]
        TYPE_HEARTBEAT: _ClassVar[Packet.Type]
    TYPE_UNSPECIFIED: Packet.Type
    TYPE_HANDSHAKE: Packet.Type
    TYPE_HANDSHAKE_ACK: Packet.Type
    TYPE_CAPABILITY_REQUEST: Packet.Type
    TYPE_CAPABILITY_RESPONSE: Packet.Type
    TYPE_DISCONNECT: Packet.Type
    TYPE_DISCONNECT_ACK: Packet.Type
    TYPE_CONNECTED: Packet.Type
    TYPE_PENDING_PACKET: Packet.Type
    TYPE_STATE_REQUEST: Packet.Type
    TYPE_STATE_RESPONSE: Packet.Type
    TYPE_STATE_UPDATE: Packet.Type
    TYPE_PUSH_PACKET: Packet.Type
    TYPE_HEARTBEAT: Packet.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    HANDSHAKE_FIELD_NUMBER: _ClassVar[int]
    HANDSHAKE_ACK_FIELD_NUMBER: _ClassVar[int]
    CAPABILITY_REQUEST_FIELD_NUMBER: _ClassVar[int]
    CAPABILITY_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    DISCONNECT_FIELD_NUMBER: _ClassVar[int]
    DISCONNECT_ACK_FIELD_NUMBER: _ClassVar[int]
    CONNECTED_FIELD_NUMBER: _ClassVar[int]
    PENDING_PACKET_FIELD_NUMBER: _ClassVar[int]
    STATE_REQUEST_FIELD_NUMBER: _ClassVar[int]
    STATE_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    STATE_UPDATE_FIELD_NUMBER: _ClassVar[int]
    PUSH_PACKET_FIELD_NUMBER: _ClassVar[int]
    HEART_BEAT_FIELD_NUMBER: _ClassVar[int]
    type: Packet.Type
    handshake: Handshake
    handshake_ack: HandshakeAck
    capability_request: CapabilityRequest
    capability_response: CapabilityResponse
    disconnect: Disconnect
    disconnect_ack: DisconnectAck
    connected: Connected
    pending_packet: PendingPacket
    state_request: StateRequest
    state_response: StateResponse
    state_update: _state_pb2.StateUpdate
    push_packet: PendingPacket
    heart_beat: HeartBeat
    def __init__(self, type: _Optional[_Union[Packet.Type, str]] = ..., handshake: _Optional[_Union[Handshake, _Mapping]] = ..., handshake_ack: _Optional[_Union[HandshakeAck, _Mapping]] = ..., capability_request: _Optional[_Union[CapabilityRequest, _Mapping]] = ..., capability_response: _Optional[_Union[CapabilityResponse, _Mapping]] = ..., disconnect: _Optional[_Union[Disconnect, _Mapping]] = ..., disconnect_ack: _Optional[_Union[DisconnectAck, _Mapping]] = ..., connected: _Optional[_Union[Connected, _Mapping]] = ..., pending_packet: _Optional[_Union[PendingPacket, _Mapping]] = ..., state_request: _Optional[_Union[StateRequest, _Mapping]] = ..., state_response: _Optional[_Union[StateResponse, _Mapping]] = ..., state_update: _Optional[_Union[_state_pb2.StateUpdate, _Mapping]] = ..., push_packet: _Optional[_Union[PendingPacket, _Mapping]] = ..., heart_beat: _Optional[_Union[HeartBeat, _Mapping]] = ...) -> None: ...

class HeartBeat(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class DisconnectAck(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Handshake(_message.Message):
    __slots__ = ()
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class HandshakeAck(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CapabilityRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CapabilityResponse(_message.Message):
    __slots__ = ()
    INTEREST_FIELD_NUMBER: _ClassVar[int]
    interest: _containers.RepeatedCompositeFieldContainer[Interest]
    def __init__(self, interest: _Optional[_Iterable[_Union[Interest, _Mapping]]] = ...) -> None: ...

class Disconnect(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class Connected(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class PendingPacket(_message.Message):
    __slots__ = ()
    class Op(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        OP_UNSPECIFIED: _ClassVar[PendingPacket.Op]
        OP_FINISH: _ClassVar[PendingPacket.Op]
        OP_CANCEL: _ClassVar[PendingPacket.Op]
        OP_FORWARD: _ClassVar[PendingPacket.Op]
        OP_PASS: _ClassVar[PendingPacket.Op]
    OP_UNSPECIFIED: PendingPacket.Op
    OP_FINISH: PendingPacket.Op
    OP_CANCEL: PendingPacket.Op
    OP_FORWARD: PendingPacket.Op
    OP_PASS: PendingPacket.Op
    BUF_FIELD_NUMBER: _ClassVar[int]
    PACKET_FLAGS_FIELD_NUMBER: _ClassVar[int]
    INTEREST_ID_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    _OP_FIELD_NUMBER: _ClassVar[int]
    _PACKET_ID_FIELD_NUMBER: _ClassVar[int]
    _HIT_COUNT_FIELD_NUMBER: _ClassVar[int]
    _RTT_NS_FIELD_NUMBER: _ClassVar[int]
    buf: bytes
    packet_flags: int
    interest_id: int
    direction: Direction
    _op: PendingPacket.Op
    _packet_id: bytes
    _hit_count: int
    _rtt_ns: int
    def __init__(self, buf: _Optional[bytes] = ..., packet_flags: _Optional[int] = ..., interest_id: _Optional[int] = ..., direction: _Optional[_Union[Direction, str]] = ..., _op: _Optional[_Union[PendingPacket.Op, str]] = ..., _packet_id: _Optional[bytes] = ..., _hit_count: _Optional[int] = ..., _rtt_ns: _Optional[int] = ...) -> None: ...

class StateRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class StateResponse(_message.Message):
    __slots__ = ()
    STATE_FIELD_NUMBER: _ClassVar[int]
    state: _growtopia_pb2.State
    def __init__(self, state: _Optional[_Union[_growtopia_pb2.State, _Mapping]] = ...) -> None: ...

class Interest(_message.Message):
    __slots__ = ()
    INTEREST_FIELD_NUMBER: _ClassVar[int]
    PRIORITY_FIELD_NUMBER: _ClassVar[int]
    BLOCKING_MODE_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    PEER_CONNECT_FIELD_NUMBER: _ClassVar[int]
    PEER_DISCONNECT_FIELD_NUMBER: _ClassVar[int]
    SERVER_HELLO_FIELD_NUMBER: _ClassVar[int]
    GENERIC_TEXT_FIELD_NUMBER: _ClassVar[int]
    GAME_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    TANK_PACKET_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    TRACK_FIELD_NUMBER: _ClassVar[int]
    CLIENT_LOG_REQUEST_FIELD_NUMBER: _ClassVar[int]
    CLIENT_LOG_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    CALL_FUNCTION_FIELD_NUMBER: _ClassVar[int]
    UPDATE_STATUS_FIELD_NUMBER: _ClassVar[int]
    TILE_CHANGE_REQUEST_FIELD_NUMBER: _ClassVar[int]
    SEND_MAP_DATA_FIELD_NUMBER: _ClassVar[int]
    SEND_TILE_UPDATE_DATA_FIELD_NUMBER: _ClassVar[int]
    SEND_TILE_UPDATE_DATA_MULTIPLE_FIELD_NUMBER: _ClassVar[int]
    TILE_ACTIVATE_REQUEST_FIELD_NUMBER: _ClassVar[int]
    TILE_APPLY_DAMAGE_FIELD_NUMBER: _ClassVar[int]
    SEND_INVENTORY_STATE_FIELD_NUMBER: _ClassVar[int]
    ITEM_ACTIVATE_REQUEST_FIELD_NUMBER: _ClassVar[int]
    ITEM_ACTIVATE_OBJECT_REQUEST_FIELD_NUMBER: _ClassVar[int]
    SEND_TILE_TREE_STATE_FIELD_NUMBER: _ClassVar[int]
    MODIFY_ITEM_INVENTORY_FIELD_NUMBER: _ClassVar[int]
    ITEM_CHANGE_OBJECT_FIELD_NUMBER: _ClassVar[int]
    SEND_LOCK_FIELD_NUMBER: _ClassVar[int]
    SEND_ITEM_DATABASE_DATA_FIELD_NUMBER: _ClassVar[int]
    SEND_PARTICLE_EFFECT_FIELD_NUMBER: _ClassVar[int]
    SET_ICON_STATE_FIELD_NUMBER: _ClassVar[int]
    ITEM_EFFECT_FIELD_NUMBER: _ClassVar[int]
    SET_CHARACTER_STATE_FIELD_NUMBER: _ClassVar[int]
    PING_REPLY_FIELD_NUMBER: _ClassVar[int]
    PING_REQUEST_FIELD_NUMBER: _ClassVar[int]
    GOT_PUNCHED_FIELD_NUMBER: _ClassVar[int]
    APP_CHECK_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    APP_INTEGRITY_FAIL_FIELD_NUMBER: _ClassVar[int]
    DISCONNECT_FIELD_NUMBER: _ClassVar[int]
    BATTLE_JOIN_FIELD_NUMBER: _ClassVar[int]
    BATTLE_EVENT_FIELD_NUMBER: _ClassVar[int]
    USE_DOOR_FIELD_NUMBER: _ClassVar[int]
    SEND_PARENTAL_FIELD_NUMBER: _ClassVar[int]
    GONE_FISHIN_FIELD_NUMBER: _ClassVar[int]
    STEAM_FIELD_NUMBER: _ClassVar[int]
    PET_BATTLE_FIELD_NUMBER: _ClassVar[int]
    NPC_FIELD_NUMBER: _ClassVar[int]
    SPECIAL_FIELD_NUMBER: _ClassVar[int]
    SEND_PARTICLE_EFFECT_V2_FIELD_NUMBER: _ClassVar[int]
    ACTIVATE_ARROW_TO_ITEM_FIELD_NUMBER: _ClassVar[int]
    SELECT_TILE_INDEX_FIELD_NUMBER: _ClassVar[int]
    SEND_PLAYER_TRIBUTE_DATA_FIELD_NUMBER: _ClassVar[int]
    FTUE_SET_ITEM_TO_QUICK_INVENTORY_FIELD_NUMBER: _ClassVar[int]
    PVE_NPC_FIELD_NUMBER: _ClassVar[int]
    PVP_CARD_BATTLE_FIELD_NUMBER: _ClassVar[int]
    PVE_APPLY_PLAYER_DAMAGE_FIELD_NUMBER: _ClassVar[int]
    PVE_NPC_POSITION_UPDATE_FIELD_NUMBER: _ClassVar[int]
    SET_EXTRA_MODS_FIELD_NUMBER: _ClassVar[int]
    ON_STEP_TILE_MOD_FIELD_NUMBER: _ClassVar[int]
    interest: InterestType
    priority: int
    blocking_mode: BlockingMode
    direction: Direction
    id: int
    peer_connect: InterestPeerConnect
    peer_disconnect: InterestPeerDisconnect
    server_hello: InterestServerHello
    generic_text: InterestGenericText
    game_message: InterestGameMessage
    tank_packet: InterestTankPacket
    error: InterestError
    track: InterestTrack
    client_log_request: InterestClientLogRequest
    client_log_response: InterestClientLogResponse
    state: InterestState
    call_function: InterestCallFunction
    update_status: InterestUpdateStatus
    tile_change_request: InterestTileChangeRequest
    send_map_data: InterestSendMapData
    send_tile_update_data: InterestSendTileUpdateData
    send_tile_update_data_multiple: InterestSendTileUpdateDataMultiple
    tile_activate_request: InterestTileActivateRequest
    tile_apply_damage: InterestTileApplyDamage
    send_inventory_state: InterestSendInventoryState
    item_activate_request: InterestItemActivateRequest
    item_activate_object_request: InterestItemActivateObjectRequest
    send_tile_tree_state: InterestSendTileTreeState
    modify_item_inventory: InterestModifyItemInventory
    item_change_object: InterestItemChangeObject
    send_lock: InterestSendLock
    send_item_database_data: InterestSendItemDatabaseData
    send_particle_effect: InterestSendParticleEffect
    set_icon_state: InterestSetIconState
    item_effect: InterestItemEffect
    set_character_state: InterestSetCharacterState
    ping_reply: InterestPingReply
    ping_request: InterestPingRequest
    got_punched: InterestGotPunched
    app_check_response: InterestAppCheckResponse
    app_integrity_fail: InterestAppIntegrityFail
    disconnect: InterestDisconnect
    battle_join: InterestBattleJoin
    battle_event: InterestBattleEvent
    use_door: InterestUseDoor
    send_parental: InterestSendParental
    gone_fishin: InterestGoneFishin
    steam: InterestSteam
    pet_battle: InterestPetBattle
    npc: InterestNpc
    special: InterestSpecial
    send_particle_effect_v2: InterestSendParticleEffectV2
    activate_arrow_to_item: InterestActivateArrowToItem
    select_tile_index: InterestSelectTileIndex
    send_player_tribute_data: InterestSendPlayerTributeData
    ftue_set_item_to_quick_inventory: InterestFtueSetItemToQuickInventory
    pve_npc: InterestPveNpc
    pvp_card_battle: InterestPvpCardBattle
    pve_apply_player_damage: InterestPveApplyPlayerDamage
    pve_npc_position_update: InterestPveNpcPositionUpdate
    set_extra_mods: InterestSetExtraMods
    on_step_tile_mod: InterestOnStepTileMod
    def __init__(self, interest: _Optional[_Union[InterestType, str]] = ..., priority: _Optional[int] = ..., blocking_mode: _Optional[_Union[BlockingMode, str]] = ..., direction: _Optional[_Union[Direction, str]] = ..., id: _Optional[int] = ..., peer_connect: _Optional[_Union[InterestPeerConnect, _Mapping]] = ..., peer_disconnect: _Optional[_Union[InterestPeerDisconnect, _Mapping]] = ..., server_hello: _Optional[_Union[InterestServerHello, _Mapping]] = ..., generic_text: _Optional[_Union[InterestGenericText, _Mapping]] = ..., game_message: _Optional[_Union[InterestGameMessage, _Mapping]] = ..., tank_packet: _Optional[_Union[InterestTankPacket, _Mapping]] = ..., error: _Optional[_Union[InterestError, _Mapping]] = ..., track: _Optional[_Union[InterestTrack, _Mapping]] = ..., client_log_request: _Optional[_Union[InterestClientLogRequest, _Mapping]] = ..., client_log_response: _Optional[_Union[InterestClientLogResponse, _Mapping]] = ..., state: _Optional[_Union[InterestState, _Mapping]] = ..., call_function: _Optional[_Union[InterestCallFunction, _Mapping]] = ..., update_status: _Optional[_Union[InterestUpdateStatus, _Mapping]] = ..., tile_change_request: _Optional[_Union[InterestTileChangeRequest, _Mapping]] = ..., send_map_data: _Optional[_Union[InterestSendMapData, _Mapping]] = ..., send_tile_update_data: _Optional[_Union[InterestSendTileUpdateData, _Mapping]] = ..., send_tile_update_data_multiple: _Optional[_Union[InterestSendTileUpdateDataMultiple, _Mapping]] = ..., tile_activate_request: _Optional[_Union[InterestTileActivateRequest, _Mapping]] = ..., tile_apply_damage: _Optional[_Union[InterestTileApplyDamage, _Mapping]] = ..., send_inventory_state: _Optional[_Union[InterestSendInventoryState, _Mapping]] = ..., item_activate_request: _Optional[_Union[InterestItemActivateRequest, _Mapping]] = ..., item_activate_object_request: _Optional[_Union[InterestItemActivateObjectRequest, _Mapping]] = ..., send_tile_tree_state: _Optional[_Union[InterestSendTileTreeState, _Mapping]] = ..., modify_item_inventory: _Optional[_Union[InterestModifyItemInventory, _Mapping]] = ..., item_change_object: _Optional[_Union[InterestItemChangeObject, _Mapping]] = ..., send_lock: _Optional[_Union[InterestSendLock, _Mapping]] = ..., send_item_database_data: _Optional[_Union[InterestSendItemDatabaseData, _Mapping]] = ..., send_particle_effect: _Optional[_Union[InterestSendParticleEffect, _Mapping]] = ..., set_icon_state: _Optional[_Union[InterestSetIconState, _Mapping]] = ..., item_effect: _Optional[_Union[InterestItemEffect, _Mapping]] = ..., set_character_state: _Optional[_Union[InterestSetCharacterState, _Mapping]] = ..., ping_reply: _Optional[_Union[InterestPingReply, _Mapping]] = ..., ping_request: _Optional[_Union[InterestPingRequest, _Mapping]] = ..., got_punched: _Optional[_Union[InterestGotPunched, _Mapping]] = ..., app_check_response: _Optional[_Union[InterestAppCheckResponse, _Mapping]] = ..., app_integrity_fail: _Optional[_Union[InterestAppIntegrityFail, _Mapping]] = ..., disconnect: _Optional[_Union[InterestDisconnect, _Mapping]] = ..., battle_join: _Optional[_Union[InterestBattleJoin, _Mapping]] = ..., battle_event: _Optional[_Union[InterestBattleEvent, _Mapping]] = ..., use_door: _Optional[_Union[InterestUseDoor, _Mapping]] = ..., send_parental: _Optional[_Union[InterestSendParental, _Mapping]] = ..., gone_fishin: _Optional[_Union[InterestGoneFishin, _Mapping]] = ..., steam: _Optional[_Union[InterestSteam, _Mapping]] = ..., pet_battle: _Optional[_Union[InterestPetBattle, _Mapping]] = ..., npc: _Optional[_Union[InterestNpc, _Mapping]] = ..., special: _Optional[_Union[InterestSpecial, _Mapping]] = ..., send_particle_effect_v2: _Optional[_Union[InterestSendParticleEffectV2, _Mapping]] = ..., activate_arrow_to_item: _Optional[_Union[InterestActivateArrowToItem, _Mapping]] = ..., select_tile_index: _Optional[_Union[InterestSelectTileIndex, _Mapping]] = ..., send_player_tribute_data: _Optional[_Union[InterestSendPlayerTributeData, _Mapping]] = ..., ftue_set_item_to_quick_inventory: _Optional[_Union[InterestFtueSetItemToQuickInventory, _Mapping]] = ..., pve_npc: _Optional[_Union[InterestPveNpc, _Mapping]] = ..., pvp_card_battle: _Optional[_Union[InterestPvpCardBattle, _Mapping]] = ..., pve_apply_player_damage: _Optional[_Union[InterestPveApplyPlayerDamage, _Mapping]] = ..., pve_npc_position_update: _Optional[_Union[InterestPveNpcPositionUpdate, _Mapping]] = ..., set_extra_mods: _Optional[_Union[InterestSetExtraMods, _Mapping]] = ..., on_step_tile_mod: _Optional[_Union[InterestOnStepTileMod, _Mapping]] = ...) -> None: ...

class InterestPeerConnect(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class InterestPeerDisconnect(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class InterestServerHello(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class InterestGenericText(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestGameMessage(_message.Message):
    __slots__ = ()
    ACTION_FIELD_NUMBER: _ClassVar[int]
    action: bytes
    def __init__(self, action: _Optional[bytes] = ...) -> None: ...

class InterestTankPacket(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestError(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class InterestTrack(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class InterestClientLogRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class InterestClientLogResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class InterestState(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestCallFunction(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestUpdateStatus(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestTileChangeRequest(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendMapData(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendTileUpdateData(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendTileUpdateDataMultiple(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestTileActivateRequest(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestTileApplyDamage(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendInventoryState(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestItemActivateRequest(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestItemActivateObjectRequest(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendTileTreeState(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestModifyItemInventory(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestItemChangeObject(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendLock(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendItemDatabaseData(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendParticleEffect(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSetIconState(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestItemEffect(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSetCharacterState(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestPingReply(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestPingRequest(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestGotPunched(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestAppCheckResponse(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestAppIntegrityFail(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestDisconnect(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestBattleJoin(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestBattleEvent(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestUseDoor(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendParental(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestGoneFishin(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSteam(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestPetBattle(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestNpc(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSpecial(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendParticleEffectV2(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestActivateArrowToItem(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSelectTileIndex(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendPlayerTributeData(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestFtueSetItemToQuickInventory(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestPveNpc(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestPvpCardBattle(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestPveApplyPlayerDamage(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestPveNpcPositionUpdate(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSetExtraMods(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestOnStepTileMod(_message.Message):
    __slots__ = ()
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestMy(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class InterestWorld(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class InterestOtherPlayer(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
