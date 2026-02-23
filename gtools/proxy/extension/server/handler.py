import logging
from google.protobuf.message import Message
import xxhash
from gtools.core.growtopia.packet import NetType, PreparedPacket, TankPacket, TankType
from gtools.core.growtopia.variant import Variant
from gtools.protogen.extension_pb2 import DIRECTION_UNSPECIFIED, Interest, InterestType
from gtools.proxy.extension.server.binop_eval import TANK_INTEREST, eval_strkv, eval_tank, eval_variant

NETPACKET_TO_INTEREST_TYPE: dict[NetType, InterestType] = {
    NetType.SERVER_HELLO: InterestType.INTEREST_SERVER_HELLO,
    NetType.GENERIC_TEXT: InterestType.INTEREST_GENERIC_TEXT,
    NetType.GAME_MESSAGE: InterestType.INTEREST_GAME_MESSAGE,
    NetType.TANK_PACKET: InterestType.INTEREST_TANK_PACKET,
    NetType.ERROR: InterestType.INTEREST_ERROR,
    NetType.TRACK: InterestType.INTEREST_TRACK,
    NetType.CLIENT_LOG_REQUEST: InterestType.INTEREST_CLIENT_LOG_REQUEST,
    NetType.CLIENT_LOG_RESPONSE: InterestType.INTEREST_CLIENT_LOG_RESPONSE,
}

TANKPACKET_TO_INTEREST_TYPE: dict[TankType, InterestType] = {
    TankType.STATE: InterestType.INTEREST_STATE,
    TankType.CALL_FUNCTION: InterestType.INTEREST_CALL_FUNCTION,
    TankType.UPDATE_STATUS: InterestType.INTEREST_UPDATE_STATUS,
    TankType.TILE_CHANGE_REQUEST: InterestType.INTEREST_TILE_CHANGE_REQUEST,
    TankType.SEND_MAP_DATA: InterestType.INTEREST_SEND_MAP_DATA,
    TankType.SEND_TILE_UPDATE_DATA: InterestType.INTEREST_SEND_TILE_UPDATE_DATA,
    TankType.SEND_TILE_UPDATE_DATA_MULTIPLE: InterestType.INTEREST_SEND_TILE_UPDATE_DATA_MULTIPLE,
    TankType.TILE_ACTIVATE_REQUEST: InterestType.INTEREST_TILE_ACTIVATE_REQUEST,
    TankType.TILE_APPLY_DAMAGE: InterestType.INTEREST_TILE_APPLY_DAMAGE,
    TankType.SEND_INVENTORY_STATE: InterestType.INTEREST_SEND_INVENTORY_STATE,
    TankType.ITEM_ACTIVATE_REQUEST: InterestType.INTEREST_ITEM_ACTIVATE_REQUEST,
    TankType.ITEM_ACTIVATE_OBJECT_REQUEST: InterestType.INTEREST_ITEM_ACTIVATE_OBJECT_REQUEST,
    TankType.SEND_TILE_TREE_STATE: InterestType.INTEREST_SEND_TILE_TREE_STATE,
    TankType.MODIFY_ITEM_INVENTORY: InterestType.INTEREST_MODIFY_ITEM_INVENTORY,
    TankType.ITEM_CHANGE_OBJECT: InterestType.INTEREST_ITEM_CHANGE_OBJECT,
    TankType.SEND_LOCK: InterestType.INTEREST_SEND_LOCK,
    TankType.SEND_ITEM_DATABASE_DATA: InterestType.INTEREST_SEND_ITEM_DATABASE_DATA,
    TankType.SEND_PARTICLE_EFFECT: InterestType.INTEREST_SEND_PARTICLE_EFFECT,
    TankType.SET_ICON_STATE: InterestType.INTEREST_SET_ICON_STATE,
    TankType.ITEM_EFFECT: InterestType.INTEREST_ITEM_EFFECT,
    TankType.SET_CHARACTER_STATE: InterestType.INTEREST_SET_CHARACTER_STATE,
    TankType.PING_REPLY: InterestType.INTEREST_PING_REPLY,
    TankType.PING_REQUEST: InterestType.INTEREST_PING_REQUEST,
    TankType.GOT_PUNCHED: InterestType.INTEREST_GOT_PUNCHED,
    TankType.APP_CHECK_RESPONSE: InterestType.INTEREST_APP_CHECK_RESPONSE,
    TankType.APP_INTEGRITY_FAIL: InterestType.INTEREST_APP_INTEGRITY_FAIL,
    TankType.DISCONNECT: InterestType.INTEREST_DISCONNECT,
    TankType.BATTLE_JOIN: InterestType.INTEREST_BATTLE_JOIN,
    TankType.BATTLE_EVENT: InterestType.INTEREST_BATTLE_EVENT,
    TankType.USE_DOOR: InterestType.INTEREST_USE_DOOR,
    TankType.SEND_PARENTAL: InterestType.INTEREST_SEND_PARENTAL,
    TankType.GONE_FISHIN: InterestType.INTEREST_GONE_FISHIN,
    TankType.STEAM: InterestType.INTEREST_STEAM,
    TankType.PET_BATTLE: InterestType.INTEREST_PET_BATTLE,
    TankType.NPC: InterestType.INTEREST_NPC,
    TankType.SPECIAL: InterestType.INTEREST_SPECIAL,
    TankType.SEND_PARTICLE_EFFECT_V2: InterestType.INTEREST_SEND_PARTICLE_EFFECT_V2,
    TankType.ACTIVATE_ARROW_TO_ITEM: InterestType.INTEREST_ACTIVATE_ARROW_TO_ITEM,
    TankType.SELECT_TILE_INDEX: InterestType.INTEREST_SELECT_TILE_INDEX,
    TankType.SEND_PLAYER_TRIBUTE_DATA: InterestType.INTEREST_SEND_PLAYER_TRIBUTE_DATA,
    TankType.FTUE_SET_ITEM_TO_QUICK_INVENTORY: InterestType.INTEREST_FTUE_SET_ITEM_TO_QUICK_INVENTORY,
    TankType.PVE_NPC: InterestType.INTEREST_PVE_NPC,
    TankType.PVP_CARD_BATTLE: InterestType.INTEREST_PVP_CARD_BATTLE,
    TankType.PVE_APPLY_PLAYER_DAMAGE: InterestType.INTEREST_PVE_APPLY_PLAYER_DAMAGE,
    TankType.PVE_NPC_POSITION_UPDATE: InterestType.INTEREST_PVE_NPC_POSITION_UPDATE,
    TankType.SET_EXTRA_MODS: InterestType.INTEREST_SET_EXTRA_MODS,
    TankType.ON_STEP_TILE_MOD: InterestType.INTEREST_ON_STEP_TILE_MOD,
}


def hash_interest(interest: Interest) -> int:
    h = xxhash.xxh3_64()
    h.update(interest.interest.to_bytes())
    if interest.priority:
        h.update(interest.priority.to_bytes(signed=True))
    h.update(interest.blocking_mode.to_bytes())
    if interest.direction:
        h.update(interest.direction.to_bytes())
    if interest.id:
        h.update(interest.id.to_bytes())
    if payload := interest.WhichOneof("payload"):
        h.update(getattr(interest, payload).SerializeToString())

    return h.intdigest()


class Extension:
    def __init__(self, id: bytes, interest: list[Interest]) -> None:
        self.id = id
        self.interest = interest
        self.last_heartbeat = 0.0

    def __repr__(self) -> str:
        return f"Extension(id={self.id}, interest({len(self.interest)})={list(map(hash_interest, self.interest))})"


class ExtensionHandler:
    logger = logging.getLogger("extension-handler")

    def __init__(self, ext: Extension, interest: Interest) -> None:
        self.ext = ext
        self.interest = interest

    def _tank_interested(self, tank: TankPacket) -> bool:
        expected_interest = TANKPACKET_TO_INTEREST_TYPE.get(tank.type)
        if not expected_interest:
            return False

        if self.interest.interest != expected_interest:
            return False

        # top-level generic where clause
        if which := self.interest.WhichOneof("payload"):
            i: Message = getattr(self.interest, which)
            if (where := getattr(i, "where")) is not None:
                if not eval_tank(tank, where):
                    return False

        # more specific packet-specific clause
        match self.interest.interest:
            case InterestType.INTEREST_STATE:
                pass
            case InterestType.INTEREST_CALL_FUNCTION:
                if not eval_variant(Variant.deserialize(tank.extended_data), self.interest.call_function.variant):
                    return False
            case InterestType.INTEREST_UPDATE_STATUS:
                pass
            case InterestType.INTEREST_TILE_CHANGE_REQUEST:
                pass
            case InterestType.INTEREST_SEND_MAP_DATA:
                pass
            case InterestType.INTEREST_SEND_TILE_UPDATE_DATA:
                pass
            case InterestType.INTEREST_SEND_TILE_UPDATE_DATA_MULTIPLE:
                pass
            case InterestType.INTEREST_TILE_ACTIVATE_REQUEST:
                pass
            case InterestType.INTEREST_TILE_APPLY_DAMAGE:
                pass
            case InterestType.INTEREST_SEND_INVENTORY_STATE:
                pass
            case InterestType.INTEREST_ITEM_ACTIVATE_REQUEST:
                pass
            case InterestType.INTEREST_ITEM_ACTIVATE_OBJECT_REQUEST:
                pass
            case InterestType.INTEREST_SEND_TILE_TREE_STATE:
                pass
            case InterestType.INTEREST_MODIFY_ITEM_INVENTORY:
                pass
            case InterestType.INTEREST_ITEM_CHANGE_OBJECT:
                pass
            case InterestType.INTEREST_SEND_LOCK:
                pass
            case InterestType.INTEREST_SEND_ITEM_DATABASE_DATA:
                pass
            case InterestType.INTEREST_SEND_PARTICLE_EFFECT:
                pass
            case InterestType.INTEREST_SET_ICON_STATE:
                pass
            case InterestType.INTEREST_ITEM_EFFECT:
                pass
            case InterestType.INTEREST_SET_CHARACTER_STATE:
                pass
            case InterestType.INTEREST_PING_REPLY:
                pass
            case InterestType.INTEREST_PING_REQUEST:
                pass
            case InterestType.INTEREST_GOT_PUNCHED:
                pass
            case InterestType.INTEREST_APP_CHECK_RESPONSE:
                pass
            case InterestType.INTEREST_APP_INTEGRITY_FAIL:
                pass
            case InterestType.INTEREST_DISCONNECT:
                pass
            case InterestType.INTEREST_BATTLE_JOIN:
                pass
            case InterestType.INTEREST_BATTLE_EVENT:
                pass
            case InterestType.INTEREST_USE_DOOR:
                pass
            case InterestType.INTEREST_SEND_PARENTAL:
                pass
            case InterestType.INTEREST_GONE_FISHIN:
                pass
            case InterestType.INTEREST_STEAM:
                pass
            case InterestType.INTEREST_PET_BATTLE:
                pass
            case InterestType.INTEREST_NPC:
                pass
            case InterestType.INTEREST_SPECIAL:
                pass
            case InterestType.INTEREST_SEND_PARTICLE_EFFECT_V2:
                pass
            case InterestType.INTEREST_ACTIVATE_ARROW_TO_ITEM:
                pass
            case InterestType.INTEREST_SELECT_TILE_INDEX:
                pass
            case InterestType.INTEREST_SEND_PLAYER_TRIBUTE_DATA:
                pass
            case InterestType.INTEREST_FTUE_SET_ITEM_TO_QUICK_INVENTORY:
                pass
            case InterestType.INTEREST_PVE_NPC:
                pass
            case InterestType.INTEREST_PVP_CARD_BATTLE:
                pass
            case InterestType.INTEREST_PVE_APPLY_PLAYER_DAMAGE:
                pass
            case InterestType.INTEREST_PVE_NPC_POSITION_UPDATE:
                pass
            case InterestType.INTEREST_SET_EXTRA_MODS:
                pass
            case InterestType.INTEREST_ON_STEP_TILE_MOD:
                pass
            case InterestType.INTEREST_UNSPECIFIED:
                pass

        return True

    def interested(self, pkt: PreparedPacket) -> bool:
        # if the interest direction is unspecified, means it doesn't care about direction (match all)
        # if the prepared packet direction is unspecified, we only match extension with unspecified direction
        if self.interest.direction != DIRECTION_UNSPECIFIED:
            if self.interest.direction != pkt.direction:
                return False

        match self.interest.interest:
            # TODO: how do we handle peer connect/disconnect with PreparedPacket?
            case InterestType.INTEREST_PEER_CONNECT:
                self.logger.warning("INTEREST_PEER_CONNECT not implemented")
                return False
            case InterestType.INTEREST_PEER_DISCONNECT:
                self.logger.warning("INTEREST_PEER_CONNECT not implemented")
                return False
            case InterestType.INTEREST_SERVER_HELLO:
                if pkt.as_net.type != NetType.SERVER_HELLO:
                    return False
            case InterestType.INTEREST_GENERIC_TEXT:
                if pkt.as_net.type != NetType.GENERIC_TEXT:
                    return False

                if not eval_strkv(pkt.as_net.generic_text, self.interest.generic_text.where):
                    return False
            case InterestType.INTEREST_GAME_MESSAGE:
                if pkt.as_net.type != NetType.GAME_MESSAGE:
                    return False

                if not eval_strkv(pkt.as_net.game_message, self.interest.game_message.where):
                    return False
            case x if x == InterestType.INTEREST_TANK_PACKET or x in TANK_INTEREST:
                if pkt.as_net.type != NetType.TANK_PACKET:
                    return False

                if x == InterestType.INTEREST_TANK_PACKET:
                    if not eval_tank(pkt.as_net.tank, self.interest.tank_packet.where):
                        return False
                else:
                    # more specific tank packet matching
                    if not self._tank_interested(pkt.as_net.tank):
                        return False
            case InterestType.INTEREST_ERROR:
                if pkt.as_net.type != NetType.ERROR:
                    return False
            case InterestType.INTEREST_TRACK:
                if pkt.as_net.type != NetType.TRACK:
                    return False

                if not eval_strkv(pkt.as_net.track, self.interest.track.where):
                    return False
            case InterestType.INTEREST_CLIENT_LOG_REQUEST:
                if pkt.as_net.type != NetType.CLIENT_LOG_REQUEST:
                    return False
            case InterestType.INTEREST_CLIENT_LOG_RESPONSE:
                if pkt.as_net.type != NetType.CLIENT_LOG_RESPONSE:
                    return False

        return True

    def __repr__(self) -> str:
        return f"Client(priority={self.interest.priority}, ext={self.ext!r}, interest={hash_interest(self.interest)})"

    def __eq__(self, value: object, /) -> bool:
        if not isinstance(value, ExtensionHandler):
            return False

        return self.ext == value.ext and self.interest == value.interest
