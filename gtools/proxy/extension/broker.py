from bisect import insort
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
import heapq
import itertools
import logging
from queue import Queue
import random
import re
import struct
import threading
import time
from traceback import print_exc
from typing import Any, Callable, Iterator, cast
from google.protobuf.internal.containers import RepeatedCompositeFieldContainer
from google.protobuf.message import Message
import zmq
import xxhash

from gtools.core.growtopia.packet import NetType, PreparedPacket, TankPacket, TankType
from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.variant import Variant
from gtools.core.network import increment_port
from gtools.core.signal import Signal
from gtools.core.transport.protocol import Event
from gtools.core.transport.zmq_transport import Pull, Router
from gtools.flags import BENCHMARK, PERF, TRACE
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    DIRECTION_UNSPECIFIED,
    BlockingMode,
    CapabilityRequest,
    Packet,
    Interest,
    InterestType,
    PendingPacket,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
)
from gtools.protogen.op_pb2 import BinOp, Op
from gtools.protogen.strkv_pb2 import FindCol, FindRow, Query
from gtools.protogen.tank_pb2 import Field, FieldValue
from gtools.protogen.variant_pb2 import VariantClause
from gtools.proxy.setting import setting


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


# TODO: rename blocking_mode to packet_mode


# extension represent the extension as a whole
# client represent the extension as a function/endpoint (a single interest)
class Extension:
    def __init__(self, id: bytes, interest: list[Interest]) -> None:
        self.id = id
        self.interest = interest
        self.last_heartbeat = 0.0

    def __repr__(self) -> str:
        return f"Extension(id={self.id}, interest({len(self.interest)})={list(map(hash_interest, self.interest))})"


class Client:
    def __init__(self, ext: Extension, interest: Interest) -> None:
        self.ext = ext
        self.interest = interest

    def __repr__(self) -> str:
        return f"Client(priority={self.interest.priority}, ext={self.ext!r}, interest={hash_interest(self.interest)})"

    def __eq__(self, value: object, /) -> bool:
        if not isinstance(value, Client):
            return False

        return self.ext == value.ext and self.interest == value.interest


_TANK_INTEREST = {
    InterestType.INTEREST_STATE,
    InterestType.INTEREST_CALL_FUNCTION,
    InterestType.INTEREST_UPDATE_STATUS,
    InterestType.INTEREST_TILE_CHANGE_REQUEST,
    InterestType.INTEREST_SEND_MAP_DATA,
    InterestType.INTEREST_SEND_TILE_UPDATE_DATA,
    InterestType.INTEREST_SEND_TILE_UPDATE_DATA_MULTIPLE,
    InterestType.INTEREST_TILE_ACTIVATE_REQUEST,
    InterestType.INTEREST_TILE_APPLY_DAMAGE,
    InterestType.INTEREST_SEND_INVENTORY_STATE,
    InterestType.INTEREST_ITEM_ACTIVATE_REQUEST,
    InterestType.INTEREST_ITEM_ACTIVATE_OBJECT_REQUEST,
    InterestType.INTEREST_SEND_TILE_TREE_STATE,
    InterestType.INTEREST_MODIFY_ITEM_INVENTORY,
    InterestType.INTEREST_ITEM_CHANGE_OBJECT,
    InterestType.INTEREST_SEND_LOCK,
    InterestType.INTEREST_SEND_ITEM_DATABASE_DATA,
    InterestType.INTEREST_SEND_PARTICLE_EFFECT,
    InterestType.INTEREST_SET_ICON_STATE,
    InterestType.INTEREST_ITEM_EFFECT,
    InterestType.INTEREST_SET_CHARACTER_STATE,
    InterestType.INTEREST_PING_REPLY,
    InterestType.INTEREST_PING_REQUEST,
    InterestType.INTEREST_GOT_PUNCHED,
    InterestType.INTEREST_APP_CHECK_RESPONSE,
    InterestType.INTEREST_APP_INTEGRITY_FAIL,
    InterestType.INTEREST_DISCONNECT,
    InterestType.INTEREST_BATTLE_JOIN,
    InterestType.INTEREST_BATTLE_EVENT,
    InterestType.INTEREST_USE_DOOR,
    InterestType.INTEREST_SEND_PARENTAL,
    InterestType.INTEREST_GONE_FISHIN,
    InterestType.INTEREST_STEAM,
    InterestType.INTEREST_PET_BATTLE,
    InterestType.INTEREST_NPC,
    InterestType.INTEREST_SPECIAL,
    InterestType.INTEREST_SEND_PARTICLE_EFFECT_V2,
    InterestType.INTEREST_ACTIVATE_ARROW_TO_ITEM,
    InterestType.INTEREST_SELECT_TILE_INDEX,
    InterestType.INTEREST_SEND_PLAYER_TRIBUTE_DATA,
    InterestType.INTEREST_FTUE_SET_ITEM_TO_QUICK_INVENTORY,
    InterestType.INTEREST_PVE_NPC,
    InterestType.INTEREST_PVP_CARD_BATTLE,
    InterestType.INTEREST_PVE_APPLY_PLAYER_DAMAGE,
    InterestType.INTEREST_PVE_NPC_POSITION_UPDATE,
    InterestType.INTEREST_SET_EXTRA_MODS,
    InterestType.INTEREST_ON_STEP_TILE_MOD,
}


_GET_ROW: dict[FindRow.Method, Callable[[StrKV, Any], list[bytes]]] = {
    FindRow.KEY: lambda strkv, k: list(strkv[k]),
    FindRow.KEY_ANY: lambda strkv, k: list(strkv.find[k]),
    FindRow.INDEX: lambda strkv, k: list(strkv[k]),
}
_GET_COL: dict[tuple[FindRow.Method, FindCol.Method], Callable[[StrKV, Any, Any], bytes]] = {
    (FindRow.KEY, FindCol.ABSOLUTE): lambda strkv, k1, k2: bytes(strkv[k1, k2]),
    (FindRow.KEY, FindCol.RELATIVE): lambda strkv, k1, k2: bytes(strkv.relative[k1, k2]),
    (FindRow.KEY_ANY, FindCol.ABSOLUTE): lambda strkv, k1, k2: cast(bytes, strkv.find[k1, k2]),
    (FindRow.KEY_ANY, FindCol.RELATIVE): lambda strkv, k1, k2: bytes(strkv.relative[k1, k2]),
    (FindRow.INDEX, FindCol.ABSOLUTE): lambda strkv, k1, k2: bytes(strkv[k1, k2]),
    (FindRow.INDEX, FindCol.RELATIVE): lambda strkv, k1, k2: bytes(strkv.relative[k1, k2]),
}

_TANK_FIELD_ACCESSOR: dict[Field, Callable[[TankPacket], object]] = {
    Field.TANK_FIELD_TYPE: lambda pkt: pkt.type,
    Field.TANK_FIELD_OBJECT_TYPE: lambda pkt: pkt.object_type,
    Field.TANK_FIELD_JUMP_COUNT: lambda pkt: pkt.jump_count,
    Field.TANK_FIELD_ANIMATION_TYPE: lambda pkt: pkt.animation_type,
    Field.TANK_FIELD_NET_ID: lambda pkt: pkt.net_id,
    Field.TANK_FIELD_TARGET_NET_ID: lambda pkt: pkt.target_net_id,
    Field.TANK_FIELD_FLAGS: lambda pkt: pkt.flags,
    Field.TANK_FIELD_FLOAT_VAR: lambda pkt: pkt.float_var,
    Field.TANK_FIELD_VALUE: lambda pkt: pkt.value,
    Field.TANK_FIELD_VECTOR_X: lambda pkt: pkt.vector_x,
    Field.TANK_FIELD_VECTOR_Y: lambda pkt: pkt.vector_y,
    Field.TANK_FIELD_VECTOR_X2: lambda pkt: pkt.vector_x2,
    Field.TANK_FIELD_VECTOR_Y2: lambda pkt: pkt.vector_y2,
    Field.TANK_FIELD_PARTICLE_ROTATION: lambda pkt: pkt.particle_rotation,
    Field.TANK_FIELD_INT_X: lambda pkt: pkt.int_x,
    Field.TANK_FIELD_INT_Y: lambda pkt: pkt.int_y,
    Field.TANK_FIELD_EXTENDED_LEN: lambda pkt: pkt.extended_len,
}

_OP_EVALUATE: dict[Op, Callable[[Any, Any], bool]] = {
    Op.OP_EQ: lambda lval, rval: lval == rval,
    Op.OP_EQ_EPS: lambda lval, rval: abs(lval - rval) < 0.01,
    Op.OP_NEQ: lambda lval, rval: lval != rval,
    Op.OP_GT: lambda lval, rval: lval > rval,
    Op.OP_GTE: lambda lval, rval: lval >= rval,
    Op.OP_LT: lambda lval, rval: lval < rval,
    Op.OP_LTE: lambda lval, rval: lval <= rval,
    Op.OP_BIT_TEST: lambda lval, rval: (lval & rval) == rval,
    Op.OP_LIKE: lambda lval, rval: bool(re.match(rval, lval)),
    Op.OP_STARTSWITH: lambda lval, rval: lval.startswith(rval),
    Op.OP_ENDSWITH: lambda lval, rval: lval.endswith(rval),
    Op.OP_CONTAINS: lambda lval, rval: rval in lval,
}

_PACKET_TO_INTEREST_TYPE: dict[NetType | TankType, InterestType] = {
    NetType.SERVER_HELLO: InterestType.INTEREST_SERVER_HELLO,
    NetType.GENERIC_TEXT: InterestType.INTEREST_GENERIC_TEXT,
    NetType.GAME_MESSAGE: InterestType.INTEREST_GAME_MESSAGE,
    NetType.TANK_PACKET: InterestType.INTEREST_TANK_PACKET,
    NetType.ERROR: InterestType.INTEREST_ERROR,
    NetType.TRACK: InterestType.INTEREST_TRACK,
    NetType.CLIENT_LOG_REQUEST: InterestType.INTEREST_CLIENT_LOG_REQUEST,
    NetType.CLIENT_LOG_RESPONSE: InterestType.INTEREST_CLIENT_LOG_RESPONSE,
}
_PACKET_TO_INTEREST_TYPE2: dict[NetType | TankType, InterestType] = {
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


logger = logging.getLogger("matcher")


# TODO: create a common class
def match_strkv_clause(kv: StrKV, where: RepeatedCompositeFieldContainer[BinOp]) -> bool:
    try:
        for clause in where:
            lvalue = Query()
            if not clause.lvalue.Unpack(lvalue):
                raise TypeError("strkv lvalue expects a query type")

            for find in lvalue.where:
                if find.HasField("col"):
                    col = _GET_COL[find.row.method, find.col.method](kv, getattr(find.row, find.row.WhichOneof("m")), find.col.index)
                    if not _OP_EVALUATE[clause.op](col, getattr(clause, clause.WhichOneof("rvalue"))):
                        return False
                else:
                    row = _GET_ROW[find.row.method](kv, getattr(find.row, find.row.WhichOneof("m")))
                    if not _OP_EVALUATE[clause.op](row, getattr(clause, clause.WhichOneof("rvalue"))):
                        return False
    except Exception as e:
        logger.warning(f"failed matching clause with exception: {e}")
        return False

    return True


def match_tank_clause(tank: TankPacket, where: RepeatedCompositeFieldContainer[BinOp]) -> bool:
    try:
        for clause in where:
            lvalue = FieldValue()
            if not clause.lvalue.Unpack(lvalue):
                raise TypeError("tank lvalue expects a field type")

            if not _OP_EVALUATE[clause.op](_TANK_FIELD_ACCESSOR[lvalue.v](tank), getattr(clause, clause.WhichOneof("rvalue"))):
                return False
    except Exception as e:
        logger.warning(f"failed matching clause with exception: {e}")
        return False

    return True


def match_variant_clause(variant: Variant, where: RepeatedCompositeFieldContainer[BinOp]) -> bool:
    try:
        for clause in where:
            lvalue = VariantClause()
            if not clause.lvalue.Unpack(lvalue):
                raise TypeError("variant lvalue expects a field type")

            if not _OP_EVALUATE[clause.op](variant[lvalue.v].value, getattr(clause, clause.WhichOneof("rvalue"))):
                return False
    except Exception as e:
        logger.warning(f"failed matching clause with exception: {e}")
        return False

    return True


class ExtensionManager:
    logger = logging.getLogger("extension_mgr")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._extensions: dict[bytes, Extension] = {}
        self._interest_map: defaultdict[InterestType, list[Client]] = defaultdict(list)

    def im_fine(self, id: bytes) -> None:
        if id not in self._extensions:
            return

        self._extensions[id].last_heartbeat = time.time()

    def sweep(self) -> None:
        to_remove: set[bytes] = set()
        for id, ext in self._extensions.items():
            if time.time() - ext.last_heartbeat > 1:
                to_remove.add(id)

        [self.remove_extension(ext) for ext in to_remove]

    def add_extension(self, extension: Extension) -> None:
        with self._lock:
            if extension.id in self._extensions:
                self.logger.warning(f"extension {extension.id} already exists, overwriting")
            self._extensions[extension.id] = extension
            for interest in extension.interest:
                ent = self._interest_map[interest.interest]
                insort(ent, Client(extension, interest), key=lambda x: -x.interest.priority)

    def remove_extension(self, id: bytes) -> None:
        with self._lock:
            if id not in self._extensions:
                self.logger.warning(f"extension {id} does not exists to be removed")
                return

            extension = self._extensions[id]
            for interest in extension.interest:
                ent = self._interest_map[interest.interest]
                ent.remove(Client(extension, interest))

            del self._extensions[id]

    def get_interested_extension_any(self, interest_type: InterestType) -> Iterator[Client]:
        for client in self._interest_map[interest_type]:
            yield client

    def get_interested_extension(self, interest_type: InterestType, pkt: PreparedPacket) -> Iterator[Client]:
        for client in self._interest_map[interest_type]:
            interest = client.interest

            # if the interest direction is unspecified, means it doesn't care about direction (match all)
            # if the prepared packet direction is unspecified, we only match extension with unspecified direction
            if interest.direction != DIRECTION_UNSPECIFIED:
                if interest.direction != pkt.direction:
                    continue

                if TRACE:
                    print("\t\t[matcher] direction matched, continuing")

            match interest.interest:
                case InterestType.INTEREST_PEER_CONNECT:
                    raise NotImplementedError("INTEREST_PEER_CONNECT")
                case InterestType.INTEREST_PEER_DISCONNECT:
                    raise NotImplementedError("INTEREST_PEER_DISCONNECT")
                case InterestType.INTEREST_SERVER_HELLO:
                    raise NotImplementedError("INTEREST_SERVER_HELLO")
                case InterestType.INTEREST_GENERIC_TEXT:
                    if not match_strkv_clause(pkt.as_net.generic_text, interest.generic_text.where):
                        continue

                    if TRACE:
                        print("\t\t[matcher] generic text matched, continuing")
                case InterestType.INTEREST_GAME_MESSAGE:
                    if interest.game_message.action:
                        if interest.game_message.action != pkt.as_net.game_message["action", 1]:
                            continue

                    if TRACE:
                        print("\t\t[matcher] game message matched, continuing")
                case InterestType.INTEREST_TANK_PACKET:
                    if not match_tank_clause(pkt.as_net.tank, interest.tank_packet.where):
                        continue

                    if TRACE:
                        print("\t\t[matcher] tank packet matched, continuing")
                case InterestType.INTEREST_ERROR:
                    raise NotImplementedError("INTEREST_ERROR")
                case InterestType.INTEREST_TRACK:
                    raise NotImplementedError("INTEREST_TRACK")
                case InterestType.INTEREST_CLIENT_LOG_REQUEST:
                    raise NotImplementedError("INTEREST_CLIENT_LOG_REQUEST")
                case InterestType.INTEREST_CLIENT_LOG_RESPONSE:
                    raise NotImplementedError("INTEREST_CLIENT_LOG_RESPONSE")

            if interest.interest in _TANK_INTEREST:
                matched = True
                handled_further = {InterestType.INTEREST_CALL_FUNCTION}
                if interest.interest not in handled_further and (which := interest.WhichOneof("payload")):
                    # TODO: fix this, where contains and clauses, should be handled inside
                    i: Message = getattr(interest, which)
                    if (clauses := getattr(i, "where")) is not None:
                        if not match_tank_clause(pkt.as_net.tank, clauses):
                            continue

                        if TRACE:
                            print(f"\t\t[matcher] top-level tank clause for {InterestType.Name(interest.interest)} matched, continuing")

                        matched = bool(clauses)

                match interest.interest:
                    case InterestType.INTEREST_STATE:
                        pass
                    case InterestType.INTEREST_CALL_FUNCTION:
                        if not match_variant_clause(Variant.deserialize(pkt.as_net.tank.extended_data), interest.call_function.where):
                            matched = False
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

                if not matched:
                    continue

                if TRACE:
                    print("\t\t[matcher] tank matched, continuing")

            if TRACE:
                print(f"\t\t[matcher] all matched for extension {interest}")
            yield client

    def get_extension(self, id: bytes) -> Extension:
        return self._extensions[id]

    def get_all_extension(self) -> list[Extension]:
        return list(self._extensions.values())


class PacketCallback:
    def __init__(
        self,
        send_to_server: Callable[[PreparedPacket], Any] | None = None,
        send_to_client: Callable[[PreparedPacket], Any] | None = None,
        any: Callable[[PreparedPacket], Any] | None = None,
    ) -> None:
        self.send_to_server = send_to_server
        self.send_to_client = send_to_client
        self.any = any


class PendingChain:
    def __init__(self, id: bytes, chain: deque[Client], current: PendingPacket) -> None:
        self.id = id
        self.chain = chain
        self.processed_chain: dict[bytes, int] = {}  # ext_id: interest hash
        self.finished_event = threading.Event()
        self.current = current
        self.cancelled = False

    def __repr__(self) -> str:
        return f"PendingChain(size={len(self.chain)}, chain={self.chain}, processed={self.processed_chain}, pkt={self.current!r}), finished={self.finished_event.is_set()}"


class _PendingPacket:
    def __init__(self, callback: PacketCallback | None, current: PendingPacket) -> None:
        self.current = current
        self.callback = callback


class PacketScheduler:
    def __init__(self, out_queue: Queue[PreparedPacket | None] | Callable[[PreparedPacket | None], Any]) -> None:
        self._out_queue = out_queue

        self._heap: list[tuple[int, int, PendingPacket]] = []
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._seq = itertools.count()

        self._first_src_ts_ns: int | None = None
        self._playback_start_wall_ns: int | None = None

        self._stopped = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify_all()

        if self._thread.is_alive():
            self._thread.join()

    def _put(self, pending: PendingPacket) -> None:
        prepared = PreparedPacket.from_pending(pending)
        if callable(self._out_queue):
            self._out_queue(prepared)
        else:
            self._out_queue.put(prepared)

    def push(self, pkt: PendingPacket) -> None:
        if pkt._rtt_ns == 0:
            self._put(pkt)
            return

        seq = next(self._seq)
        with self._cond:
            heapq.heappush(self._heap, (pkt._rtt_ns, seq, pkt))
            self._cond.notify()

    def _run(self) -> None:
        while True:
            with self._cond:
                if self._stopped:
                    break

                if not self._heap:
                    self._cond.wait()
                    continue

                send_ts_ns, _, pkt = self._heap[0]

                if self._first_src_ts_ns is None:
                    heapq.heappop(self._heap)
                    self._first_src_ts_ns = send_ts_ns
                    self._playback_start_wall_ns = time.monotonic_ns()
                    packet_to_send = pkt
                else:
                    assert self._playback_start_wall_ns is not None and self._first_src_ts_ns is not None
                    target_wall_ns = self._playback_start_wall_ns + (send_ts_ns - self._first_src_ts_ns)
                    now_ns = time.monotonic_ns()
                    wait_ns = target_wall_ns - now_ns

                    if wait_ns > 0:
                        self._cond.wait(timeout=wait_ns / 1e9)
                        continue

                    heapq.heappop(self._heap)
                    packet_to_send = pkt

            try:
                self._put(packet_to_send)
            except Exception:
                pass


@dataclass
class BrokerFunction:
    reply: Callable[[Packet], None]
    send_to: Callable[[bytes, Packet], None]
    send_to_interested: Callable[[InterestType, Packet], None]


HandleFunction = Callable[[bytes, Packet, BrokerFunction], Any]


class Broker:
    logger = logging.getLogger("broker")

    def __init__(self, pull_queue: Queue[PreparedPacket | None] | Callable[[PreparedPacket | None], Any] | None = None, addr: str = setting.broker_addr) -> None:
        self._suppress_log = False

        self._context = zmq.Context()
        self._router = Router(self._context, addr)

        self._extension_mgr = ExtensionManager()
        self._pending_chain: dict[bytes, PendingChain] = {}
        self._pending_packet: dict[bytes, _PendingPacket] = {}

        self._stop_event = threading.Event()
        self._worker_thread_id: threading.Thread | None = None
        self.extension_len = Signal(0)

        self._pull_queue = pull_queue
        if self._pull_queue:
            self._scheduler = PacketScheduler(self._pull_queue)
        else:
            self._scheduler = None

        pull_addr = increment_port(addr)
        self._pull = Pull(self._context, pull_addr)
        self.logger.debug(f"starting pull thread on {pull_addr}")
        self._pull_thread_id = threading.Thread(target=self._pull_thread)
        self._pull_thread_id.start()
        self._handler: dict[Packet.Type, HandleFunction] = {}
        self._monitor_thread_id = threading.Thread(target=self._monitor_thread)

    def _monitor_thread(self) -> None:
        last_heartbeat = 0
        interval = 0.5

        try:
            while not self._stop_event:
                self._extension_mgr.sweep()

                now = time.time()
                if now - last_heartbeat > interval:
                    with self.suppressed_log():
                        self.broadcast(Packet(type=Packet.TYPE_HEARTBEAT))
                    last_heartbeat = now

                time.sleep(0.1)
        except Exception as e:
            self.logger.debug(f"monitor thread error: {e}")

    @contextmanager
    def suppressed_log(self) -> Iterator["Broker"]:
        orig = self._suppress_log
        try:
            self._suppress_log = True
            yield self
        finally:
            self._suppress_log = orig

    def _pull_one(self) -> bool:
        if self._stop_event.is_set():
            return False

        payload = self._pull.recv()
        if not payload:
            return False

        pkt = PendingPacket()
        pkt.ParseFromString(payload)

        if self._scheduler:
            self._scheduler.push(pkt)
        else:
            self.logger.warning(f"pull unhandled: {pkt}")

        # TODO: this thing gets in the middle of normal logging, same with push on sdk
        # if not self._suppress_log and self.logger.isEnabledFor(logging.DEBUG):
        #     pkt = PreparedPacket.from_pending(pkt)
        #     self.logger.debug(f"\x1b[34m<<--\x1b[0m pull    \x1b[34m<<\x1b[0m{pkt!r}\x1b[34m<<\x1b[0m")

        return True

    def _pull_thread(self) -> None:
        if BENCHMARK:
            _last = time.monotonic_ns()
            i = 0
            prev_i = 0
            elapsed_total = 0

            while not self._stop_event.is_set():
                if not self._pull_one():
                    break

                elapsed_total += time.monotonic_ns() - _last
                if elapsed_total >= 1e9:
                    print(f"packet rate: {i - prev_i} / s")
                    elapsed_total = 0
                    prev_i = i
                i += 1
                _last = time.monotonic_ns()
        else:
            while not self._stop_event.is_set():
                if not self._pull_one():
                    break

        self.logger.debug("pull thread exiting")

    def _recv(self) -> tuple[bytes, Packet | None]:
        if self._stop_event.is_set():
            return b"", None

        payload = self._router.recv()
        if payload is None:
            return b"", None

        id, data = payload
        pkt = Packet()
        pkt.ParseFromString(data)

        if not self._suppress_log and not pkt.type == Packet.TYPE_HEARTBEAT:
            self.logger.debug(f"\x1b[31m<<--\x1b[0m recv    \x1b[31m<<\x1b[0m{pkt!r}\x1b[31m<<\x1b[0m")

        return id, pkt

    def _send(self, extension: bytes, pkt: Packet) -> None:
        if self._stop_event.is_set():
            return

        self._router.send((extension, pkt.SerializeToString()))

    def broadcast(self, pkt: Packet) -> None:
        for ext in self._extension_mgr.get_all_extension():
            try:
                self._send(ext.id, pkt)
            except Exception as e:
                self.logger.error(f"failed to send packet to {ext.id}: {e}")
                continue

    def _get_interested_extension(self, pkt: PreparedPacket) -> Iterator[Client]:
        interest_type = _PACKET_TO_INTEREST_TYPE[pkt.as_net.type]
        interest_type2: list[Client] = []
        if pkt.as_net.type == NetType.TANK_PACKET:
            interest_type2.extend(
                self._extension_mgr.get_interested_extension(
                    _PACKET_TO_INTEREST_TYPE2[pkt.as_net.tank.type],
                    pkt,
                )
            )

        for client in itertools.chain(
            self._extension_mgr.get_interested_extension(interest_type, pkt),
            interest_type2,
        ):
            yield client

    def _build_chain(
        self,
        pkt: PreparedPacket,
        out: deque[Client],
        pred: Callable[[Extension, Interest], bool] | None = None,
    ) -> None:
        for client in self._get_interested_extension(pkt):
            if client.interest.blocking_mode == BLOCKING_MODE_BLOCK:
                if pred and pred(client.ext, client.interest):
                    if TRACE:
                        print(f"\t\tinterested for {pkt}:\n\t{client.ext.id}\n\t{repr(client.interest).replace('\n', '\n\t')}")
                    out.append(client)

    def _utob(self, i: int) -> bytes:
        return i.to_bytes((i.bit_length() + 7) // 8)

    # if it returns none, then either there is no extension, or no extension matched
    def process_event(self, pkt: PreparedPacket, callback: PacketCallback | None = None) -> tuple[PendingPacket, bool] | None:
        start = time.monotonic_ns()
        chain: deque[Client] = deque()
        for client in self._get_interested_extension(pkt):
            if TRACE:
                print(f"\t\tMATCHING CLIENT (MODE={BlockingMode.Name(client.interest.blocking_mode)}) FOR {pkt}: {client}")

            match client.interest.blocking_mode:
                case BlockingMode.BLOCKING_MODE_BLOCK:
                    chain.append(client)
                case BlockingMode.BLOCKING_MODE_SEND_AND_FORGET:
                    pkt_id = random.randbytes(16)
                    pending_pkt = PendingPacket(
                        _op=PendingPacket.OP_FORWARD,
                        _packet_id=pkt_id,
                        buf=pkt.as_raw,
                        direction=pkt.direction,
                        packet_flags=pkt.flags,
                        _rtt_ns=time.monotonic_ns(),
                        interest_id=client.interest.id,
                    )
                    self._send(
                        client.ext.id,
                        Packet(type=Packet.TYPE_PENDING_PACKET, pending_packet=pending_pkt),
                    )
                    self._pending_packet[pkt_id] = _PendingPacket(
                        callback,
                        pending_pkt,
                    )
                    if not callback:
                        self.logger.warning(f"no callback defined for {pkt}")
                case BlockingMode.BLOCKING_MODE_SEND_AND_CANCEL:
                    pkt_id = random.randbytes(16)
                    pending_pkt = PendingPacket(
                        _op=PendingPacket.OP_FORWARD,
                        _packet_id=pkt_id,
                        buf=pkt.as_raw,
                        direction=pkt.direction,
                        packet_flags=pkt.flags,
                        _rtt_ns=time.monotonic_ns(),
                        interest_id=client.interest.id,
                    )
                    self._send(
                        client.ext.id,
                        Packet(type=Packet.TYPE_PENDING_PACKET, pending_packet=pending_pkt),
                    )
                    self._pending_packet[pkt_id] = _PendingPacket(
                        callback,
                        pending_pkt,
                    )
                    if not callback:
                        self.logger.warning(f"no callback defined for {pkt}")

                    # since we dont use the packet if cancelled is true, this should be safe
                    return PendingPacket(), True
                case BlockingMode.BLOCKING_MODE_ONESHOT:
                    pending_pkt = PendingPacket(
                        _op=PendingPacket.OP_FORWARD,
                        buf=pkt.as_raw,
                        direction=pkt.direction,
                        packet_flags=pkt.flags,
                        interest_id=client.interest.id,
                    )
                    self._send(
                        client.ext.id,
                        Packet(type=Packet.TYPE_PENDING_PACKET, pending_packet=pending_pkt),
                    )
                case BlockingMode.BLOCKING_MODE_ONESHOT_AND_CANCEL:
                    pending_pkt = PendingPacket(
                        _op=PendingPacket.OP_FORWARD,
                        buf=pkt.as_raw,
                        direction=pkt.direction,
                        packet_flags=pkt.flags,
                        interest_id=client.interest.id,
                    )
                    self._send(
                        client.ext.id,
                        Packet(type=Packet.TYPE_PENDING_PACKET, pending_packet=pending_pkt),
                    )
                    return PendingPacket(), True

        if TRACE:
            print(
                f"\t\tSTATE PROCESS_EVENT NOBLOCK (ext={len(self._extension_mgr._extensions)}, pending_chain={len(self._pending_chain)}, pending_packet={len(self._pending_packet)}):\n"
                f"\tchain={self._pending_chain}\n",
                f"\tpacket={self._pending_packet}\n",
            )

        if chain:
            chain_id = random.randbytes(16)
            pending_pkt = PendingPacket(
                _op=PendingPacket.OP_FORWARD,
                _packet_id=chain_id,
                buf=pkt.as_raw,
                direction=pkt.direction,
                packet_flags=pkt.flags,
                _rtt_ns=time.monotonic_ns(),
                interest_id=chain[0].interest.id,
            )

            pending = PendingChain(chain_id, chain, pending_pkt)
            pending.processed_chain[chain[0].ext.id] = hash_interest(chain[0].interest)
            self._pending_chain[chain_id] = pending
            self._send(
                chain[0].ext.id,
                Packet(type=Packet.TYPE_PENDING_PACKET, pending_packet=pending_pkt),
            )

            if TRACE:
                print(
                    f"\t\tSTATE PROCESS_EVENT BLOCK (ext={len(self._extension_mgr._extensions)}, pending_chain={len(self._pending_chain)}, pending_packet={len(self._pending_packet)}):\n"
                    f"\tchain={self._pending_chain}\n",
                    f"\tpacket={self._pending_packet}\n",
                )

            if PERF:
                self.logger.debug(f"broker processing: {(time.monotonic_ns() - start) / 1e6}us")
            self._pending_chain[chain_id].finished_event.wait()
            finished = self._pending_chain.pop(chain_id)
            finished.current._rtt_ns = time.monotonic_ns() - finished.current._rtt_ns
            return finished.current, finished.cancelled

    # this version of process_event doesn't work with prepared packet, but with arbitrary packet, thus
    # it can only send block and doesn't chain
    def process_event_any(self, interest: InterestType, pkt: Packet) -> None:
        for client in self._extension_mgr.get_interested_extension_any(interest):
            self._send(client.ext.id, pkt)

    def start(self, block: bool = False) -> None:
        self._router.start(block=False)
        self._pull.start(block=False)
        if block:
            self._worker_thread()
        else:
            self._worker_thread_id = threading.Thread(target=lambda: self._worker_thread())
            self._worker_thread_id.start()

    def stop(self) -> None:
        if self._stop_event.is_set():
            return

        self.logger.debug("stopping extension...")

        self.broadcast(Packet(type=Packet.TYPE_DISCONNECT))
        self._stop_event.set()

        try:
            self.logger.debug("stopping router")
            self._router.stop()
        except Exception as e:
            self.logger.debug(f"router error: {e}")

        try:
            self.logger.debug("stopping pull")
            self._pull.stop()
        except Exception as e:
            self.logger.debug(f"pull error: {e}")

        if self._scheduler:
            self.logger.debug(f"stopping packet scheduler")
            self._scheduler.stop()

        if self._worker_thread_id and self._worker_thread_id.is_alive():
            self._worker_thread_id.join(timeout=2.0)
            self.logger.debug("worker thread exited")

        try:
            self.logger.debug("closing zmq context")
            self._context.destroy(linger=0)
        except Exception as e:
            self.logger.debug(f"context term error: {e}")

        if self._pull_thread_id and self._pull_thread_id.is_alive():
            self._pull_thread_id.join(timeout=2.0)
            self.logger.debug("pull thread exited")

        self.logger.debug("broker has stopped")

    def _forward(self, chain: PendingChain, new_packet: PendingPacket) -> None:
        chain.current = new_packet
        chain.chain.clear()
        self._build_chain(
            PreparedPacket.from_pending(new_packet),
            chain.chain,
            pred=lambda ext, interest: not bool(chain and (ext.id in chain.processed_chain and chain.processed_chain[ext.id] == hash_interest(interest))),
        )
        if len(chain.chain) == 0:
            chain.finished_event.set()
        else:
            next_client = chain.chain.popleft()
            new_packet.interest_id = next_client.interest.id
            chain.processed_chain[next_client.ext.id] = hash_interest(next_client.interest)
            self._send(
                next_client.ext.id,
                Packet(
                    type=Packet.TYPE_PENDING_PACKET,
                    pending_packet=new_packet,
                ),
            )

    def _finish(self, pending: _PendingPacket, new_packet: PendingPacket) -> None:
        if not pending.callback:
            return

        pending.current = new_packet
        if pending.current.direction == DIRECTION_CLIENT_TO_SERVER and pending.callback.send_to_server:
            pending.callback.send_to_server(PreparedPacket.from_pending(pending.current))
        elif pending.current.direction == DIRECTION_SERVER_TO_CLIENT and pending.callback.send_to_client:
            pending.callback.send_to_client(PreparedPacket.from_pending(pending.current))
        else:
            self.logger.warning(f"packet direction is unspecified: {pending}")

        if pending.callback.any:
            pending.callback.any(PreparedPacket.from_pending(pending.current))

    # TODO: don't have these if TRACE, create utils

    def _handle_packet(self, pkt: PendingPacket) -> None:
        assert pkt._packet_id, "invalid packet id"
        if (chain := self._pending_chain.get(pkt._packet_id)) is not None:
            if TRACE:
                print(f"\t\t\tPACKET {PendingPacket.Op.Name(pkt._op)} IS {chain.current}")
            match pkt._op:
                case PendingPacket.OP_FINISH:
                    chain.current = pkt
                    chain.finished_event.set()
                case PendingPacket.OP_CANCEL:
                    chain.current._hit_count = pkt._hit_count
                    chain.cancelled = True
                    chain.finished_event.set()
                case PendingPacket.OP_FORWARD:
                    self._forward(chain, pkt)
                case PendingPacket.OP_PASS:
                    chain.current._hit_count = pkt._hit_count
                    self._forward(chain, chain.current)
                    pass
                case _:
                    raise ValueError(f"invalid op: {pkt._op}")
        elif (pending := self._pending_packet.pop(pkt._packet_id, None)) is not None:
            if TRACE:
                print(f"\t\t\tPACKET {PendingPacket.Op.Name(pkt._op)} IS {pending.current}")
            match pkt._op:
                case PendingPacket.OP_FINISH:
                    self._finish(pending, pkt)
                case PendingPacket.OP_CANCEL:
                    pass
                case PendingPacket.OP_FORWARD:
                    self._finish(pending, pkt)
                case PendingPacket.OP_PASS:
                    pass
                case _:
                    raise ValueError(f"invalid op: {pkt._op}")
        else:
            raise ValueError(f"packet is not in any pending state: {pkt}")

    def _worker_thread(self) -> None:
        try:
            while not self._stop_event.is_set():
                id, pkt = self._recv()
                if pkt is None:
                    break

                match pkt.type:
                    case Packet.TYPE_HEARTBEAT:
                        self._extension_mgr.im_fine(id)
                    case Packet.TYPE_PUSH_PACKET:
                        if self._scheduler:
                            self._scheduler.push(pkt.push_packet)
                    case Packet.TYPE_HANDSHAKE:
                        self._send(id, Packet(type=Packet.TYPE_HANDSHAKE_ACK))
                        self._send(id, Packet(type=Packet.TYPE_CAPABILITY_REQUEST, capability_request=CapabilityRequest()))
                    case Packet.TYPE_CAPABILITY_RESPONSE:
                        self._extension_mgr.add_extension(
                            Extension(
                                id=id,
                                interest=list(pkt.capability_response.interest),
                            ),
                        )
                        self._send(id, Packet(type=Packet.TYPE_CONNECTED))
                        self.extension_len.update(lambda x: x + 1)
                    case Packet.TYPE_DISCONNECT:
                        self._extension_mgr.remove_extension(id)
                        self.extension_len.update(lambda x: x - 1)
                        self._send(id, Packet(type=Packet.TYPE_DISCONNECT_ACK))
                    case Packet.TYPE_PENDING_PACKET:
                        if TRACE:
                            print(f"\t\trecv from {id}: {pkt}")
                            print(
                                f"\t\tSTATE (ext={len(self._extension_mgr._extensions)}, pending_chain={len(self._pending_chain)}, pending_packet={len(self._pending_packet)}):\n"
                                f"\tchain={self._pending_chain}\n",
                                f"\tpacket={self._pending_packet}\n",
                            )
                        self._handle_packet(pkt.pending_packet)
                    case _:
                        if handler := self._handler.get(pkt.type):
                            if TRACE:
                                print(f"\t\t{Packet.Type.Name(pkt.type)} handled by external handler")

                            try:
                                handler(
                                    id,
                                    pkt,
                                    BrokerFunction(
                                        lambda pkt, id=id: self._send(id, pkt),
                                        self._send,
                                        self.process_event_any,
                                    ),
                                )
                            except Exception as e:
                                self.logger.error(f"error in handler: {e}")
                                print_exc()
        except (KeyboardInterrupt, InterruptedError):
            pass
        except zmq.error.ZMQError as e:
            if not self._stop_event.is_set():
                self.logger.debug(f"ZMQ error in main loop: {e}")
        finally:
            self.logger.debug("worker thread exiting")

    def set_handler(self, type: Packet.Type, handler: HandleFunction) -> None:
        self._handler[type] = handler
