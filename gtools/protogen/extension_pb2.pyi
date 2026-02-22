import op_pb2 as _op_pb2
import growtopia_pb2 as _growtopia_pb2
import state_pb2 as _state_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Mapping as _Mapping, Optional as _Optional, Union as _Union

BLOCKING_MODE_BLOCK: BlockingMode
BLOCKING_MODE_ONESHOT: BlockingMode
BLOCKING_MODE_ONESHOT_AND_CANCEL: BlockingMode
BLOCKING_MODE_SEND_AND_CANCEL: BlockingMode
BLOCKING_MODE_SEND_AND_FORGET: BlockingMode
BLOCKING_MODE_UNSPECIFIED: BlockingMode
DESCRIPTOR: _descriptor.FileDescriptor
DIRECTION_CLIENT_TO_SERVER: Direction
DIRECTION_SERVER_TO_CLIENT: Direction
DIRECTION_UNSPECIFIED: Direction
INTEREST_ACTIVATE_ARROW_TO_ITEM: InterestType
INTEREST_APP_CHECK_RESPONSE: InterestType
INTEREST_APP_INTEGRITY_FAIL: InterestType
INTEREST_BATTLE_EVENT: InterestType
INTEREST_BATTLE_JOIN: InterestType
INTEREST_CALL_FUNCTION: InterestType
INTEREST_CLIENT_LOG_REQUEST: InterestType
INTEREST_CLIENT_LOG_RESPONSE: InterestType
INTEREST_DISCONNECT: InterestType
INTEREST_ERROR: InterestType
INTEREST_FTUE_SET_ITEM_TO_QUICK_INVENTORY: InterestType
INTEREST_GAME_MESSAGE: InterestType
INTEREST_GENERIC_TEXT: InterestType
INTEREST_GONE_FISHIN: InterestType
INTEREST_GOT_PUNCHED: InterestType
INTEREST_ITEM_ACTIVATE_OBJECT_REQUEST: InterestType
INTEREST_ITEM_ACTIVATE_REQUEST: InterestType
INTEREST_ITEM_CHANGE_OBJECT: InterestType
INTEREST_ITEM_EFFECT: InterestType
INTEREST_MODIFY_ITEM_INVENTORY: InterestType
INTEREST_NPC: InterestType
INTEREST_ON_STEP_TILE_MOD: InterestType
INTEREST_PEER_CONNECT: InterestType
INTEREST_PEER_DISCONNECT: InterestType
INTEREST_PET_BATTLE: InterestType
INTEREST_PING_REPLY: InterestType
INTEREST_PING_REQUEST: InterestType
INTEREST_PVE_APPLY_PLAYER_DAMAGE: InterestType
INTEREST_PVE_NPC: InterestType
INTEREST_PVE_NPC_POSITION_UPDATE: InterestType
INTEREST_PVP_CARD_BATTLE: InterestType
INTEREST_SELECT_TILE_INDEX: InterestType
INTEREST_SEND_INVENTORY_STATE: InterestType
INTEREST_SEND_ITEM_DATABASE_DATA: InterestType
INTEREST_SEND_LOCK: InterestType
INTEREST_SEND_MAP_DATA: InterestType
INTEREST_SEND_PARENTAL: InterestType
INTEREST_SEND_PARTICLE_EFFECT: InterestType
INTEREST_SEND_PARTICLE_EFFECT_V2: InterestType
INTEREST_SEND_PLAYER_TRIBUTE_DATA: InterestType
INTEREST_SEND_TILE_TREE_STATE: InterestType
INTEREST_SEND_TILE_UPDATE_DATA: InterestType
INTEREST_SEND_TILE_UPDATE_DATA_MULTIPLE: InterestType
INTEREST_SERVER_HELLO: InterestType
INTEREST_SET_CHARACTER_STATE: InterestType
INTEREST_SET_EXTRA_MODS: InterestType
INTEREST_SET_ICON_STATE: InterestType
INTEREST_SPECIAL: InterestType
INTEREST_STATE: InterestType
INTEREST_STATE_UPDATE: InterestType
INTEREST_STEAM: InterestType
INTEREST_TANK_PACKET: InterestType
INTEREST_TILE_ACTIVATE_REQUEST: InterestType
INTEREST_TILE_APPLY_DAMAGE: InterestType
INTEREST_TILE_CHANGE_REQUEST: InterestType
INTEREST_TRACK: InterestType
INTEREST_UNSPECIFIED: InterestType
INTEREST_UPDATE_STATUS: InterestType
INTEREST_USE_DOOR: InterestType

class CapabilityRequest(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class CapabilityResponse(_message.Message):
    __slots__ = ["interest"]
    INTEREST_FIELD_NUMBER: _ClassVar[int]
    interest: _containers.RepeatedCompositeFieldContainer[Interest]
    def __init__(self, interest: _Optional[_Iterable[_Union[Interest, _Mapping]]] = ...) -> None: ...

class Connected(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class Disconnect(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class DisconnectAck(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class Handshake(_message.Message):
    __slots__ = ["name"]
    NAME_FIELD_NUMBER: _ClassVar[int]
    name: str
    def __init__(self, name: _Optional[str] = ...) -> None: ...

class HandshakeAck(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class HeartBeat(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class Interest(_message.Message):
    __slots__ = ["activate_arrow_to_item", "app_check_response", "app_integrity_fail", "battle_event", "battle_join", "blocking_mode", "call_function", "client_log_request", "client_log_response", "direction", "disconnect", "error", "ftue_set_item_to_quick_inventory", "game_message", "generic_text", "gone_fishin", "got_punched", "id", "interest", "item_activate_object_request", "item_activate_request", "item_change_object", "item_effect", "modify_item_inventory", "npc", "on_step_tile_mod", "peer_connect", "peer_disconnect", "pet_battle", "ping_reply", "ping_request", "priority", "pve_apply_player_damage", "pve_npc", "pve_npc_position_update", "pvp_card_battle", "select_tile_index", "send_inventory_state", "send_item_database_data", "send_lock", "send_map_data", "send_parental", "send_particle_effect", "send_particle_effect_v2", "send_player_tribute_data", "send_tile_tree_state", "send_tile_update_data", "send_tile_update_data_multiple", "server_hello", "set_character_state", "set_extra_mods", "set_icon_state", "special", "state", "steam", "tank_packet", "tile_activate_request", "tile_apply_damage", "tile_change_request", "track", "update_status", "use_door"]
    ACTIVATE_ARROW_TO_ITEM_FIELD_NUMBER: _ClassVar[int]
    APP_CHECK_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    APP_INTEGRITY_FAIL_FIELD_NUMBER: _ClassVar[int]
    BATTLE_EVENT_FIELD_NUMBER: _ClassVar[int]
    BATTLE_JOIN_FIELD_NUMBER: _ClassVar[int]
    BLOCKING_MODE_FIELD_NUMBER: _ClassVar[int]
    CALL_FUNCTION_FIELD_NUMBER: _ClassVar[int]
    CLIENT_LOG_REQUEST_FIELD_NUMBER: _ClassVar[int]
    CLIENT_LOG_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    DISCONNECT_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    FTUE_SET_ITEM_TO_QUICK_INVENTORY_FIELD_NUMBER: _ClassVar[int]
    GAME_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    GENERIC_TEXT_FIELD_NUMBER: _ClassVar[int]
    GONE_FISHIN_FIELD_NUMBER: _ClassVar[int]
    GOT_PUNCHED_FIELD_NUMBER: _ClassVar[int]
    ID_FIELD_NUMBER: _ClassVar[int]
    INTEREST_FIELD_NUMBER: _ClassVar[int]
    ITEM_ACTIVATE_OBJECT_REQUEST_FIELD_NUMBER: _ClassVar[int]
    ITEM_ACTIVATE_REQUEST_FIELD_NUMBER: _ClassVar[int]
    ITEM_CHANGE_OBJECT_FIELD_NUMBER: _ClassVar[int]
    ITEM_EFFECT_FIELD_NUMBER: _ClassVar[int]
    MODIFY_ITEM_INVENTORY_FIELD_NUMBER: _ClassVar[int]
    NPC_FIELD_NUMBER: _ClassVar[int]
    ON_STEP_TILE_MOD_FIELD_NUMBER: _ClassVar[int]
    PEER_CONNECT_FIELD_NUMBER: _ClassVar[int]
    PEER_DISCONNECT_FIELD_NUMBER: _ClassVar[int]
    PET_BATTLE_FIELD_NUMBER: _ClassVar[int]
    PING_REPLY_FIELD_NUMBER: _ClassVar[int]
    PING_REQUEST_FIELD_NUMBER: _ClassVar[int]
    PRIORITY_FIELD_NUMBER: _ClassVar[int]
    PVE_APPLY_PLAYER_DAMAGE_FIELD_NUMBER: _ClassVar[int]
    PVE_NPC_FIELD_NUMBER: _ClassVar[int]
    PVE_NPC_POSITION_UPDATE_FIELD_NUMBER: _ClassVar[int]
    PVP_CARD_BATTLE_FIELD_NUMBER: _ClassVar[int]
    SELECT_TILE_INDEX_FIELD_NUMBER: _ClassVar[int]
    SEND_INVENTORY_STATE_FIELD_NUMBER: _ClassVar[int]
    SEND_ITEM_DATABASE_DATA_FIELD_NUMBER: _ClassVar[int]
    SEND_LOCK_FIELD_NUMBER: _ClassVar[int]
    SEND_MAP_DATA_FIELD_NUMBER: _ClassVar[int]
    SEND_PARENTAL_FIELD_NUMBER: _ClassVar[int]
    SEND_PARTICLE_EFFECT_FIELD_NUMBER: _ClassVar[int]
    SEND_PARTICLE_EFFECT_V2_FIELD_NUMBER: _ClassVar[int]
    SEND_PLAYER_TRIBUTE_DATA_FIELD_NUMBER: _ClassVar[int]
    SEND_TILE_TREE_STATE_FIELD_NUMBER: _ClassVar[int]
    SEND_TILE_UPDATE_DATA_FIELD_NUMBER: _ClassVar[int]
    SEND_TILE_UPDATE_DATA_MULTIPLE_FIELD_NUMBER: _ClassVar[int]
    SERVER_HELLO_FIELD_NUMBER: _ClassVar[int]
    SET_CHARACTER_STATE_FIELD_NUMBER: _ClassVar[int]
    SET_EXTRA_MODS_FIELD_NUMBER: _ClassVar[int]
    SET_ICON_STATE_FIELD_NUMBER: _ClassVar[int]
    SPECIAL_FIELD_NUMBER: _ClassVar[int]
    STATE_FIELD_NUMBER: _ClassVar[int]
    STEAM_FIELD_NUMBER: _ClassVar[int]
    TANK_PACKET_FIELD_NUMBER: _ClassVar[int]
    TILE_ACTIVATE_REQUEST_FIELD_NUMBER: _ClassVar[int]
    TILE_APPLY_DAMAGE_FIELD_NUMBER: _ClassVar[int]
    TILE_CHANGE_REQUEST_FIELD_NUMBER: _ClassVar[int]
    TRACK_FIELD_NUMBER: _ClassVar[int]
    UPDATE_STATUS_FIELD_NUMBER: _ClassVar[int]
    USE_DOOR_FIELD_NUMBER: _ClassVar[int]
    activate_arrow_to_item: InterestActivateArrowToItem
    app_check_response: InterestAppCheckResponse
    app_integrity_fail: InterestAppIntegrityFail
    battle_event: InterestBattleEvent
    battle_join: InterestBattleJoin
    blocking_mode: BlockingMode
    call_function: InterestCallFunction
    client_log_request: InterestClientLogRequest
    client_log_response: InterestClientLogResponse
    direction: Direction
    disconnect: InterestDisconnect
    error: InterestError
    ftue_set_item_to_quick_inventory: InterestFtueSetItemToQuickInventory
    game_message: InterestGameMessage
    generic_text: InterestGenericText
    gone_fishin: InterestGoneFishin
    got_punched: InterestGotPunched
    id: int
    interest: InterestType
    item_activate_object_request: InterestItemActivateObjectRequest
    item_activate_request: InterestItemActivateRequest
    item_change_object: InterestItemChangeObject
    item_effect: InterestItemEffect
    modify_item_inventory: InterestModifyItemInventory
    npc: InterestNpc
    on_step_tile_mod: InterestOnStepTileMod
    peer_connect: InterestPeerConnect
    peer_disconnect: InterestPeerDisconnect
    pet_battle: InterestPetBattle
    ping_reply: InterestPingReply
    ping_request: InterestPingRequest
    priority: int
    pve_apply_player_damage: InterestPveApplyPlayerDamage
    pve_npc: InterestPveNpc
    pve_npc_position_update: InterestPveNpcPositionUpdate
    pvp_card_battle: InterestPvpCardBattle
    select_tile_index: InterestSelectTileIndex
    send_inventory_state: InterestSendInventoryState
    send_item_database_data: InterestSendItemDatabaseData
    send_lock: InterestSendLock
    send_map_data: InterestSendMapData
    send_parental: InterestSendParental
    send_particle_effect: InterestSendParticleEffect
    send_particle_effect_v2: InterestSendParticleEffectV2
    send_player_tribute_data: InterestSendPlayerTributeData
    send_tile_tree_state: InterestSendTileTreeState
    send_tile_update_data: InterestSendTileUpdateData
    send_tile_update_data_multiple: InterestSendTileUpdateDataMultiple
    server_hello: InterestServerHello
    set_character_state: InterestSetCharacterState
    set_extra_mods: InterestSetExtraMods
    set_icon_state: InterestSetIconState
    special: InterestSpecial
    state: InterestState
    steam: InterestSteam
    tank_packet: InterestTankPacket
    tile_activate_request: InterestTileActivateRequest
    tile_apply_damage: InterestTileApplyDamage
    tile_change_request: InterestTileChangeRequest
    track: InterestTrack
    update_status: InterestUpdateStatus
    use_door: InterestUseDoor
    def __init__(self, interest: _Optional[_Union[InterestType, str]] = ..., priority: _Optional[int] = ..., blocking_mode: _Optional[_Union[BlockingMode, str]] = ..., direction: _Optional[_Union[Direction, str]] = ..., id: _Optional[int] = ..., peer_connect: _Optional[_Union[InterestPeerConnect, _Mapping]] = ..., peer_disconnect: _Optional[_Union[InterestPeerDisconnect, _Mapping]] = ..., server_hello: _Optional[_Union[InterestServerHello, _Mapping]] = ..., generic_text: _Optional[_Union[InterestGenericText, _Mapping]] = ..., game_message: _Optional[_Union[InterestGameMessage, _Mapping]] = ..., tank_packet: _Optional[_Union[InterestTankPacket, _Mapping]] = ..., error: _Optional[_Union[InterestError, _Mapping]] = ..., track: _Optional[_Union[InterestTrack, _Mapping]] = ..., client_log_request: _Optional[_Union[InterestClientLogRequest, _Mapping]] = ..., client_log_response: _Optional[_Union[InterestClientLogResponse, _Mapping]] = ..., state: _Optional[_Union[InterestState, _Mapping]] = ..., call_function: _Optional[_Union[InterestCallFunction, _Mapping]] = ..., update_status: _Optional[_Union[InterestUpdateStatus, _Mapping]] = ..., tile_change_request: _Optional[_Union[InterestTileChangeRequest, _Mapping]] = ..., send_map_data: _Optional[_Union[InterestSendMapData, _Mapping]] = ..., send_tile_update_data: _Optional[_Union[InterestSendTileUpdateData, _Mapping]] = ..., send_tile_update_data_multiple: _Optional[_Union[InterestSendTileUpdateDataMultiple, _Mapping]] = ..., tile_activate_request: _Optional[_Union[InterestTileActivateRequest, _Mapping]] = ..., tile_apply_damage: _Optional[_Union[InterestTileApplyDamage, _Mapping]] = ..., send_inventory_state: _Optional[_Union[InterestSendInventoryState, _Mapping]] = ..., item_activate_request: _Optional[_Union[InterestItemActivateRequest, _Mapping]] = ..., item_activate_object_request: _Optional[_Union[InterestItemActivateObjectRequest, _Mapping]] = ..., send_tile_tree_state: _Optional[_Union[InterestSendTileTreeState, _Mapping]] = ..., modify_item_inventory: _Optional[_Union[InterestModifyItemInventory, _Mapping]] = ..., item_change_object: _Optional[_Union[InterestItemChangeObject, _Mapping]] = ..., send_lock: _Optional[_Union[InterestSendLock, _Mapping]] = ..., send_item_database_data: _Optional[_Union[InterestSendItemDatabaseData, _Mapping]] = ..., send_particle_effect: _Optional[_Union[InterestSendParticleEffect, _Mapping]] = ..., set_icon_state: _Optional[_Union[InterestSetIconState, _Mapping]] = ..., item_effect: _Optional[_Union[InterestItemEffect, _Mapping]] = ..., set_character_state: _Optional[_Union[InterestSetCharacterState, _Mapping]] = ..., ping_reply: _Optional[_Union[InterestPingReply, _Mapping]] = ..., ping_request: _Optional[_Union[InterestPingRequest, _Mapping]] = ..., got_punched: _Optional[_Union[InterestGotPunched, _Mapping]] = ..., app_check_response: _Optional[_Union[InterestAppCheckResponse, _Mapping]] = ..., app_integrity_fail: _Optional[_Union[InterestAppIntegrityFail, _Mapping]] = ..., disconnect: _Optional[_Union[InterestDisconnect, _Mapping]] = ..., battle_join: _Optional[_Union[InterestBattleJoin, _Mapping]] = ..., battle_event: _Optional[_Union[InterestBattleEvent, _Mapping]] = ..., use_door: _Optional[_Union[InterestUseDoor, _Mapping]] = ..., send_parental: _Optional[_Union[InterestSendParental, _Mapping]] = ..., gone_fishin: _Optional[_Union[InterestGoneFishin, _Mapping]] = ..., steam: _Optional[_Union[InterestSteam, _Mapping]] = ..., pet_battle: _Optional[_Union[InterestPetBattle, _Mapping]] = ..., npc: _Optional[_Union[InterestNpc, _Mapping]] = ..., special: _Optional[_Union[InterestSpecial, _Mapping]] = ..., send_particle_effect_v2: _Optional[_Union[InterestSendParticleEffectV2, _Mapping]] = ..., activate_arrow_to_item: _Optional[_Union[InterestActivateArrowToItem, _Mapping]] = ..., select_tile_index: _Optional[_Union[InterestSelectTileIndex, _Mapping]] = ..., send_player_tribute_data: _Optional[_Union[InterestSendPlayerTributeData, _Mapping]] = ..., ftue_set_item_to_quick_inventory: _Optional[_Union[InterestFtueSetItemToQuickInventory, _Mapping]] = ..., pve_npc: _Optional[_Union[InterestPveNpc, _Mapping]] = ..., pvp_card_battle: _Optional[_Union[InterestPvpCardBattle, _Mapping]] = ..., pve_apply_player_damage: _Optional[_Union[InterestPveApplyPlayerDamage, _Mapping]] = ..., pve_npc_position_update: _Optional[_Union[InterestPveNpcPositionUpdate, _Mapping]] = ..., set_extra_mods: _Optional[_Union[InterestSetExtraMods, _Mapping]] = ..., on_step_tile_mod: _Optional[_Union[InterestOnStepTileMod, _Mapping]] = ...) -> None: ...

class InterestActivateArrowToItem(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestAppCheckResponse(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestAppIntegrityFail(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestBattleEvent(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestBattleJoin(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestCallFunction(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestClientLogRequest(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class InterestClientLogResponse(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class InterestDisconnect(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestError(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class InterestFtueSetItemToQuickInventory(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestGameMessage(_message.Message):
    __slots__ = ["action"]
    ACTION_FIELD_NUMBER: _ClassVar[int]
    action: bytes
    def __init__(self, action: _Optional[bytes] = ...) -> None: ...

class InterestGenericText(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestGoneFishin(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestGotPunched(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestItemActivateObjectRequest(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestItemActivateRequest(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestItemChangeObject(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestItemEffect(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestModifyItemInventory(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestMy(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class InterestNpc(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestOnStepTileMod(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestOtherPlayer(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class InterestPeerConnect(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class InterestPeerDisconnect(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class InterestPetBattle(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestPingReply(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestPingRequest(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestPveApplyPlayerDamage(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestPveNpc(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestPveNpcPositionUpdate(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestPvpCardBattle(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSelectTileIndex(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendInventoryState(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendItemDatabaseData(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendLock(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendMapData(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendParental(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendParticleEffect(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendParticleEffectV2(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendPlayerTributeData(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendTileTreeState(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendTileUpdateData(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSendTileUpdateDataMultiple(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestServerHello(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class InterestSetCharacterState(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSetExtraMods(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSetIconState(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSpecial(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestState(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestSteam(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestTankPacket(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestTileActivateRequest(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestTileApplyDamage(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestTileChangeRequest(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestTrack(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class InterestUpdateStatus(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestUseDoor(_message.Message):
    __slots__ = ["where"]
    WHERE_FIELD_NUMBER: _ClassVar[int]
    where: _containers.RepeatedCompositeFieldContainer[_op_pb2.BinOp]
    def __init__(self, where: _Optional[_Iterable[_Union[_op_pb2.BinOp, _Mapping]]] = ...) -> None: ...

class InterestWorld(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class Packet(_message.Message):
    __slots__ = ["capability_request", "capability_response", "connected", "disconnect", "disconnect_ack", "handshake", "handshake_ack", "heart_beat", "pending_packet", "push_packet", "state_request", "state_response", "state_update", "type"]
    class Type(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    CAPABILITY_REQUEST_FIELD_NUMBER: _ClassVar[int]
    CAPABILITY_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    CONNECTED_FIELD_NUMBER: _ClassVar[int]
    DISCONNECT_ACK_FIELD_NUMBER: _ClassVar[int]
    DISCONNECT_FIELD_NUMBER: _ClassVar[int]
    HANDSHAKE_ACK_FIELD_NUMBER: _ClassVar[int]
    HANDSHAKE_FIELD_NUMBER: _ClassVar[int]
    HEART_BEAT_FIELD_NUMBER: _ClassVar[int]
    PENDING_PACKET_FIELD_NUMBER: _ClassVar[int]
    PUSH_PACKET_FIELD_NUMBER: _ClassVar[int]
    STATE_REQUEST_FIELD_NUMBER: _ClassVar[int]
    STATE_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    STATE_UPDATE_FIELD_NUMBER: _ClassVar[int]
    TYPE_CAPABILITY_REQUEST: Packet.Type
    TYPE_CAPABILITY_RESPONSE: Packet.Type
    TYPE_CONNECTED: Packet.Type
    TYPE_DISCONNECT: Packet.Type
    TYPE_DISCONNECT_ACK: Packet.Type
    TYPE_FIELD_NUMBER: _ClassVar[int]
    TYPE_HANDSHAKE: Packet.Type
    TYPE_HANDSHAKE_ACK: Packet.Type
    TYPE_HEARTBEAT: Packet.Type
    TYPE_PENDING_PACKET: Packet.Type
    TYPE_PUSH_PACKET: Packet.Type
    TYPE_STATE_REQUEST: Packet.Type
    TYPE_STATE_RESPONSE: Packet.Type
    TYPE_STATE_UPDATE: Packet.Type
    TYPE_UNSPECIFIED: Packet.Type
    capability_request: CapabilityRequest
    capability_response: CapabilityResponse
    connected: Connected
    disconnect: Disconnect
    disconnect_ack: DisconnectAck
    handshake: Handshake
    handshake_ack: HandshakeAck
    heart_beat: HeartBeat
    pending_packet: PendingPacket
    push_packet: PendingPacket
    state_request: StateRequest
    state_response: StateResponse
    state_update: _state_pb2.StateUpdate
    type: Packet.Type
    def __init__(self, type: _Optional[_Union[Packet.Type, str]] = ..., handshake: _Optional[_Union[Handshake, _Mapping]] = ..., handshake_ack: _Optional[_Union[HandshakeAck, _Mapping]] = ..., capability_request: _Optional[_Union[CapabilityRequest, _Mapping]] = ..., capability_response: _Optional[_Union[CapabilityResponse, _Mapping]] = ..., disconnect: _Optional[_Union[Disconnect, _Mapping]] = ..., disconnect_ack: _Optional[_Union[DisconnectAck, _Mapping]] = ..., connected: _Optional[_Union[Connected, _Mapping]] = ..., pending_packet: _Optional[_Union[PendingPacket, _Mapping]] = ..., state_request: _Optional[_Union[StateRequest, _Mapping]] = ..., state_response: _Optional[_Union[StateResponse, _Mapping]] = ..., state_update: _Optional[_Union[_state_pb2.StateUpdate, _Mapping]] = ..., push_packet: _Optional[_Union[PendingPacket, _Mapping]] = ..., heart_beat: _Optional[_Union[HeartBeat, _Mapping]] = ...) -> None: ...

class PendingPacket(_message.Message):
    __slots__ = ["_hit_count", "_op", "_packet_id", "_rtt_ns", "buf", "direction", "interest_id", "packet_flags"]
    class Op(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = []
    BUF_FIELD_NUMBER: _ClassVar[int]
    DIRECTION_FIELD_NUMBER: _ClassVar[int]
    INTEREST_ID_FIELD_NUMBER: _ClassVar[int]
    OP_CANCEL: PendingPacket.Op
    OP_FINISH: PendingPacket.Op
    OP_FORWARD: PendingPacket.Op
    OP_PASS: PendingPacket.Op
    OP_UNSPECIFIED: PendingPacket.Op
    PACKET_FLAGS_FIELD_NUMBER: _ClassVar[int]
    _HIT_COUNT_FIELD_NUMBER: _ClassVar[int]
    _OP_FIELD_NUMBER: _ClassVar[int]
    _PACKET_ID_FIELD_NUMBER: _ClassVar[int]
    _RTT_NS_FIELD_NUMBER: _ClassVar[int]
    _hit_count: int
    _op: PendingPacket.Op
    _packet_id: bytes
    _rtt_ns: int
    buf: bytes
    direction: Direction
    interest_id: int
    packet_flags: int
    def __init__(self, buf: _Optional[bytes] = ..., packet_flags: _Optional[int] = ..., interest_id: _Optional[int] = ..., direction: _Optional[_Union[Direction, str]] = ..., _op: _Optional[_Union[PendingPacket.Op, str]] = ..., _packet_id: _Optional[bytes] = ..., _hit_count: _Optional[int] = ..., _rtt_ns: _Optional[int] = ...) -> None: ...

class StateRequest(_message.Message):
    __slots__ = []
    def __init__(self) -> None: ...

class StateResponse(_message.Message):
    __slots__ = ["state"]
    STATE_FIELD_NUMBER: _ClassVar[int]
    state: _growtopia_pb2.State
    def __init__(self, state: _Optional[_Union[_growtopia_pb2.State, _Mapping]] = ...) -> None: ...

class InterestType(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []

class Direction(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []

class BlockingMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = []
