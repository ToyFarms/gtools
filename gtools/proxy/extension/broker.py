from bisect import insort
from collections import defaultdict, deque
import itertools
import logging
import random
import threading
import time
from typing import Any, Callable, Iterator, cast
import zmq
import xxhash

from gtools.core.growtopia.packet import NetPacket, NetType, TankPacket, TankType
from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.variant import Variant
from gtools.flags import PERF, TRACE
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_UNSPECIFIED,
    INTEREST_UNSPECIFIED,
    CapabilityRequest,
    Direction,
    Packet,
    Interest,
    InterestType,
    PendingPacket,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
)
from gtools.protogen.op_pb2 import Op
from gtools.protogen.strkv_pb2 import FindCol, FindRow, Query
from gtools.protogen.tank_pb2 import Field
from gtools.proxy.extension.common import Waitable
from thirdparty.enet.bindings import ENetPacketFlag


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

    return h.intdigest()


# extension represent the extension as a whole
# client represent the extension as a function/endpoint (a single interest)
class Extension:
    def __init__(self, id: bytes, interest: list[Interest]) -> None:
        self.id = id
        self.interest = interest

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


class ExtensionManager:
    logger = logging.getLogger("extension_mgr")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._extensions: dict[bytes, Extension] = {}
        self._interest_map: defaultdict[InterestType, list[Client]] = defaultdict(list)

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
    }

    def get_interested_extension(self, interest_type: InterestType, pkt: NetPacket, raw: bytes, direction: Direction) -> Iterator[Client]:
        for client in self._interest_map[interest_type]:
            interest = client.interest

            matches: list[bool] = []

            if f := client.interest.WhichOneof("payload"):
                matches.append(getattr(interest, f) is not None)

            if interest.direction != DIRECTION_UNSPECIFIED:
                matches.append(interest.direction == direction)

            matched = True
            match interest.interest:
                case InterestType.INTEREST_PEER_CONNECT:
                    raise NotImplementedError("INTEREST_PEER_CONNECT")
                case InterestType.INTEREST_PEER_DISCONNECT:
                    raise NotImplementedError("INTEREST_PEER_DISCONNECT")
                case InterestType.INTEREST_SERVER_HELLO:
                    raise NotImplementedError("INTEREST_SERVER_HELLO")
                case InterestType.INTEREST_GENERIC_TEXT:
                    for clause in interest.generic_text.where:
                        should_break = False
                        lvalue = Query()
                        if not clause.lvalue.Unpack(lvalue):
                            raise TypeError("strkv lvalue expects a query type")

                        for find in lvalue.where:
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
                            if find.HasField("col"):
                                col = _GET_COL[find.row.method, find.col.method](pkt.generic_text, getattr(find.row, find.row.WhichOneof("m")), find.col.index)
                                if not self._OP_EVALUATE[clause.op](col, getattr(clause, clause.WhichOneof("rvalue"))):
                                    matched = False
                                    should_break = True
                                    break
                            else:
                                row = _GET_ROW[find.row.method](pkt.generic_text, getattr(find.row, find.row.WhichOneof("m")))
                                if not self._OP_EVALUATE[clause.op](row, getattr(clause, clause.WhichOneof("rvalue"))):
                                    matched = False
                                    should_break = True
                                    break

                        if should_break:
                            break
                case InterestType.INTEREST_GAME_MESSAGE:
                    if interest.game_message.action:
                        matched = interest.game_message.action == pkt.game_message["action", 1]
                case InterestType.INTEREST_TANK_PACKET:
                    for clause in interest.tank_packet.where:
                        lvalue = Field()
                        if not clause.lvalue.Unpack(lvalue):
                            raise TypeError("tank lvalue expects a field type")

                        if not self._OP_EVALUATE[clause.op](self._TANK_FIELD_ACCESSOR[lvalue](pkt.tank), getattr(clause, clause.WhichOneof("rvalue"))):
                            matched = False
                            break

                case InterestType.INTEREST_ERROR:
                    raise NotImplementedError("INTEREST_ERROR")
                case InterestType.INTEREST_TRACK:
                    raise NotImplementedError("INTEREST_TRACK")
                case InterestType.INTEREST_CLIENT_LOG_REQUEST:
                    raise NotImplementedError("INTEREST_CLIENT_LOG_REQUEST")
                case InterestType.INTEREST_CLIENT_LOG_RESPONSE:
                    raise NotImplementedError("INTEREST_CLIENT_LOG_RESPONSE")

            if pkt.type == NetType.TANK_PACKET and interest.interest != InterestType.INTEREST_TANK_PACKET:
                match interest.interest:
                    case InterestType.INTEREST_STATE:
                        raise NotImplementedError("INTEREST_STATE")
                    case InterestType.INTEREST_CALL_FUNCTION:
                        if interest.call_function.fn_name:
                            matched = interest.call_function.fn_name == Variant.get(pkt.tank.extended_data, 0).value
                    case InterestType.INTEREST_UPDATE_STATUS:
                        raise NotImplementedError("INTEREST_UPDATE_STATUS")
                    case InterestType.INTEREST_TILE_CHANGE_REQUEST:
                        raise NotImplementedError("INTEREST_TILE_CHANGE_REQUEST")
                    case InterestType.INTEREST_SEND_MAP_DATA:
                        raise NotImplementedError("INTEREST_SEND_MAP_DATA")
                    case InterestType.INTEREST_SEND_TILE_UPDATE_DATA:
                        raise NotImplementedError("INTEREST_SEND_TILE_UPDATE_DATA")
                    case InterestType.INTEREST_SEND_TILE_UPDATE_DATA_MULTIPLE:
                        raise NotImplementedError("INTEREST_SEND_TILE_UPDATE_DATA_MULTIPLE")
                    case InterestType.INTEREST_TILE_ACTIVATE_REQUEST:
                        raise NotImplementedError("INTEREST_TILE_ACTIVATE_REQUEST")
                    case InterestType.INTEREST_TILE_APPLY_DAMAGE:
                        raise NotImplementedError("INTEREST_TILE_APPLY_DAMAGE")
                    case InterestType.INTEREST_SEND_INVENTORY_STATE:
                        raise NotImplementedError("INTEREST_SEND_INVENTORY_STATE")
                    case InterestType.INTEREST_ITEM_ACTIVATE_REQUEST:
                        raise NotImplementedError("INTEREST_ITEM_ACTIVATE_REQUEST")
                    case InterestType.INTEREST_ITEM_ACTIVATE_OBJECT_REQUEST:
                        raise NotImplementedError("INTEREST_ITEM_ACTIVATE_OBJECT_REQUEST")
                    case InterestType.INTEREST_SEND_TILE_TREE_STATE:
                        raise NotImplementedError("INTEREST_SEND_TILE_TREE_STATE")
                    case InterestType.INTEREST_MODIFY_ITEM_INVENTORY:
                        raise NotImplementedError("INTEREST_MODIFY_ITEM_INVENTORY")
                    case InterestType.INTEREST_ITEM_CHANGE_OBJECT:
                        raise NotImplementedError("INTEREST_ITEM_CHANGE_OBJECT")
                    case InterestType.INTEREST_SEND_LOCK:
                        raise NotImplementedError("INTEREST_SEND_LOCK")
                    case InterestType.INTEREST_SEND_ITEM_DATABASE_DATA:
                        raise NotImplementedError("INTEREST_SEND_ITEM_DATABASE_DATA")
                    case InterestType.INTEREST_SEND_PARTICLE_EFFECT:
                        raise NotImplementedError("INTEREST_SEND_PARTICLE_EFFECT")
                    case InterestType.INTEREST_SET_ICON_STATE:
                        raise NotImplementedError("INTEREST_SET_ICON_STATE")
                    case InterestType.INTEREST_ITEM_EFFECT:
                        raise NotImplementedError("INTEREST_ITEM_EFFECT")
                    case InterestType.INTEREST_SET_CHARACTER_STATE:
                        raise NotImplementedError("INTEREST_SET_CHARACTER_STATE")
                    case InterestType.INTEREST_PING_REPLY:
                        raise NotImplementedError("INTEREST_PING_REPLY")
                    case InterestType.INTEREST_PING_REQUEST:
                        raise NotImplementedError("INTEREST_PING_REQUEST")
                    case InterestType.INTEREST_GOT_PUNCHED:
                        raise NotImplementedError("INTEREST_GOT_PUNCHED")
                    case InterestType.INTEREST_APP_CHECK_RESPONSE:
                        raise NotImplementedError("INTEREST_APP_CHECK_RESPONSE")
                    case InterestType.INTEREST_APP_INTEGRITY_FAIL:
                        raise NotImplementedError("INTEREST_APP_INTEGRITY_FAIL")
                    case InterestType.INTEREST_DISCONNECT:
                        raise NotImplementedError("INTEREST_DISCONNECT")
                    case InterestType.INTEREST_BATTLE_JOIN:
                        raise NotImplementedError("INTEREST_BATTLE_JOIN")
                    case InterestType.INTEREST_BATTLE_EVENT:
                        raise NotImplementedError("INTEREST_BATTLE_EVENT")
                    case InterestType.INTEREST_USE_DOOR:
                        raise NotImplementedError("INTEREST_USE_DOOR")
                    case InterestType.INTEREST_SEND_PARENTAL:
                        raise NotImplementedError("INTEREST_SEND_PARENTAL")
                    case InterestType.INTEREST_GONE_FISHIN:
                        raise NotImplementedError("INTEREST_GONE_FISHIN")
                    case InterestType.INTEREST_STEAM:
                        raise NotImplementedError("INTEREST_STEAM")
                    case InterestType.INTEREST_PET_BATTLE:
                        raise NotImplementedError("INTEREST_PET_BATTLE")
                    case InterestType.INTEREST_NPC:
                        raise NotImplementedError("INTEREST_NPC")
                    case InterestType.INTEREST_SPECIAL:
                        raise NotImplementedError("INTEREST_SPECIAL")
                    case InterestType.INTEREST_SEND_PARTICLE_EFFECT_V2:
                        raise NotImplementedError("INTEREST_SEND_PARTICLE_EFFECT_V2")
                    case InterestType.INTEREST_ACTIVATE_ARROW_TO_ITEM:
                        raise NotImplementedError("INTEREST_ACTIVATE_ARROW_TO_ITEM")
                    case InterestType.INTEREST_SELECT_TILE_INDEX:
                        raise NotImplementedError("INTEREST_SELECT_TILE_INDEX")
                    case InterestType.INTEREST_SEND_PLAYER_TRIBUTE_DATA:
                        raise NotImplementedError("INTEREST_SEND_PLAYER_TRIBUTE_DATA")
                    case InterestType.INTEREST_FTUE_SET_ITEM_TO_QUICK_INVENTORY:
                        raise NotImplementedError("INTEREST_FTUE_SET_ITEM_TO_QUICK_INVENTORY")
                    case InterestType.INTEREST_PVE_NPC:
                        raise NotImplementedError("INTEREST_PVE_NPC")
                    case InterestType.INTEREST_PVP_CARD_BATTLE:
                        raise NotImplementedError("INTEREST_PVP_CARD_BATTLE")
                    case InterestType.INTEREST_PVE_APPLY_PLAYER_DAMAGE:
                        raise NotImplementedError("INTEREST_PVE_APPLY_PLAYER_DAMAGE")
                    case InterestType.INTEREST_PVE_NPC_POSITION_UPDATE:
                        raise NotImplementedError("INTEREST_PVE_NPC_POSITION_UPDATE")
                    case InterestType.INTEREST_SET_EXTRA_MODS:
                        raise NotImplementedError("INTEREST_SET_EXTRA_MODS")
                    case InterestType.INTEREST_ON_STEP_TILE_MOD:
                        raise NotImplementedError("INTEREST_ON_STEP_TILE_MOD")
                    case InterestType.INTEREST_UNSPECIFIED:
                        raise NotImplementedError("INTEREST_UNSPECIFIED")
            matches.append(matched)

            if all(matches):
                yield client

    def get_extension(self, id: bytes) -> Extension:
        return self._extensions[id]

    def get_all_extension(self) -> list[Extension]:
        return list(self._extensions.values())


class PacketCallback:
    def __init__(
        self,
        send_to_server: Callable[[bytes], Any] | None = None,
        send_to_client: Callable[[bytes], Any] | None = None,
        any: Callable[[bytes], Any] | None = None,
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
    def __init__(self, callback: PacketCallback, current: PendingPacket) -> None:
        self.current = current
        self.callback = callback


class Broker:
    logger = logging.getLogger("broker")

    def __init__(self, addr: str = "tcp://127.0.0.1:6712") -> None:
        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.ROUTER)
        self._socket.setsockopt(zmq.LINGER, 0)
        self._socket.bind(addr)

        self._extension_mgr = ExtensionManager()
        self._pending_chain: dict[bytes, PendingChain] = {}
        self._pending_packet: dict[bytes, _PendingPacket] = {}

        self._stop_event = threading.Event()
        self._worker_thread_id: threading.Thread | None = None
        self.extension_len: Waitable[int] = Waitable(0)

    def _recv(self) -> tuple[bytes, Packet | None]:
        if self._stop_event.is_set():
            return b"", None

        try:
            events = self._socket.poll(100, zmq.POLLIN)

            if events == 0:
                return b"", None

            id, data = self._socket.recv_multipart(zmq.NOBLOCK)
        except zmq.error.Again:
            return b"", None
        except zmq.error.ZMQError as e:
            if self._stop_event.is_set():
                return b"", None
            self.logger.debug(f"Recv error: {e}")
            return b"", None

        pkt = Packet()
        pkt.ParseFromString(data)

        self.logger.debug(f"\x1b[31m<<--\x1b[0m recv    \x1b[31m<<\x1b[0m{pkt!r}\x1b[31m<<\x1b[0m")

        return id, pkt

    def broadcast(self, pkt: Packet) -> None:
        for ext in self._extension_mgr.get_all_extension():
            try:
                self._send(ext.id, pkt)
            except Exception as e:
                self.logger.error(f"failed to send packet to {ext.id}: {e}")
                continue

    def _send(self, extension: bytes, pkt: Packet) -> None:
        if self._stop_event.is_set():
            return

        self.logger.debug(f"   send \x1b[32m-->>\x1b[0m target={extension}: \x1b[32m>>\x1b[0m{pkt!r}\x1b[32m>>\x1b[0m")
        try:
            if self._socket.poll(100, zmq.POLLOUT):
                self._socket.send_multipart((extension, pkt.SerializeToString()))
        except zmq.error.ZMQError as e:
            if not self._stop_event.is_set():
                self.logger.debug(f"Send error: {e}")

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

    def _get_interested_extension(self, pkt: NetPacket, raw: bytes, direction: Direction) -> Iterator[Client]:
        # TODO: handle "super" packet, basically like netpacket shuold match any kind of packet
        interest_type = self._PACKET_TO_INTEREST_TYPE[pkt.type]
        interest_type2: list[Client] = []
        if pkt.type == NetType.TANK_PACKET:
            interest_type2.extend(
                self._extension_mgr.get_interested_extension(
                    self._PACKET_TO_INTEREST_TYPE2[pkt.tank.type],
                    pkt,
                    raw,
                    direction,
                )
            )

        for client in itertools.chain(
            self._extension_mgr.get_interested_extension(interest_type, pkt, raw, direction),
            interest_type2,
        ):
            yield client

    def _build_chain(
        self,
        pkt: NetPacket,
        raw: bytes,
        direction: Direction,
        out: deque[Client],
        pred: Callable[[Extension, Interest], bool] | None = None,
    ) -> None:
        for client in self._get_interested_extension(pkt, raw, direction):
            if client.interest.blocking_mode == BLOCKING_MODE_BLOCK:
                if pred and pred(client.ext, client.interest):
                    if TRACE:
                        print(f"interested for {pkt}:\n\t{client.ext.id}\n\t{repr(client.interest).replace('\n', '\n\t')}")
                    out.append(client)

    def _utob(self, i: int) -> bytes:
        return i.to_bytes((i.bit_length() + 7) // 8)

    # TODO: i didnt think zmq had all the stuff behind the scene before i implemented them myself.
    # might want to utilize that instead for performance

    # TODO: change this parameter to use PreparedPacket
    def process_event(self, pkt: NetPacket, raw: bytes, direction: Direction, flags: ENetPacketFlag, callback: PacketCallback | None = None) -> tuple[PendingPacket, bool] | None:
        start = time.perf_counter_ns()
        chain: deque[Client] = deque()
        for client in self._get_interested_extension(pkt, raw, direction):
            if client.interest.blocking_mode == BLOCKING_MODE_SEND_AND_FORGET:
                pkt_id = random.randbytes(16)
                pending_pkt = PendingPacket(
                    op=PendingPacket.OP_FORWARD,
                    packet_id=pkt_id,
                    buf=raw,
                    direction=direction,
                    packet_flags=int(flags),
                    rtt_ns=self._utob(time.perf_counter_ns()),
                    interest_id=client.interest.id,
                )
                self._send(
                    client.ext.id,
                    Packet(type=Packet.TYPE_PENDING_PACKET, pending_packet=pending_pkt),
                )
                if callback:
                    self._pending_packet[pkt_id] = _PendingPacket(
                        callback,
                        pending_pkt,
                    )
            else:
                chain.append(client)

        if chain:
            chain_id = random.randbytes(16)
            pending_pkt = PendingPacket(
                op=PendingPacket.OP_FORWARD,
                packet_id=chain_id,
                buf=raw,
                direction=direction,
                packet_flags=int(flags),
                rtt_ns=self._utob(time.perf_counter_ns()),
                interest_id=chain[0].interest.id,
            )

            pending = PendingChain(chain_id, chain, pending_pkt)
            pending.processed_chain[chain[0].ext.id] = hash_interest(chain[0].interest)
            self._pending_chain[chain_id] = pending
            self._send(
                chain[0].ext.id,
                Packet(type=Packet.TYPE_PENDING_PACKET, pending_packet=pending_pkt),
            )

            if PERF:
                self.logger.debug(f"broker processing: {(time.perf_counter_ns() - start) / 1e6}us")
            self._pending_chain[chain_id].finished_event.wait()
            finished = self._pending_chain.pop(chain_id)
            finished.current.rtt_ns = self._utob(time.perf_counter_ns() - int.from_bytes(finished.current.rtt_ns))
            return finished.current, finished.cancelled

    def start(self, block: bool = False) -> None:
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

        if self._worker_thread_id and self._worker_thread_id.is_alive():
            self._worker_thread_id.join(timeout=2.0)
            self.logger.debug("worker thread exited")

        try:
            self.logger.debug("closing zmq context")
            # self._context.term()
            self._context.destroy(linger=0)
        except Exception as e:
            self.logger.debug(f"context term error: {e}")

        self.logger.debug("broker has stopped")

    def _forward(self, chain: PendingChain, new_packet: PendingPacket) -> None:
        chain.current = new_packet
        chain.chain.clear()
        self._build_chain(
            NetPacket.deserialize(new_packet.buf),
            new_packet.buf,
            new_packet.direction,
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
        pending.current = new_packet
        if pending.current.direction == DIRECTION_CLIENT_TO_SERVER and pending.callback.send_to_server:
            pending.callback.send_to_server(pending.current.buf)
        elif pending.current.direction == DIRECTION_SERVER_TO_CLIENT and pending.callback.send_to_client:
            pending.callback.send_to_client(pending.current.buf)

        if pending.callback.any:
            pending.callback.any(pending.current.buf)

        del self._pending_packet[pending.current.packet_id]

    def _handle_packet(self, pkt: PendingPacket) -> None:
        if (chain := self._pending_chain.get(pkt.packet_id)) is not None:
            match pkt.op:
                case PendingPacket.OP_FINISH:
                    chain.current = pkt
                    chain.finished_event.set()
                case PendingPacket.OP_CANCEL:
                    chain.current.hit_count = pkt.hit_count
                    chain.cancelled = True
                    chain.finished_event.set()
                case PendingPacket.OP_FORWARD:
                    self._forward(chain, pkt)
                case PendingPacket.OP_PASS:
                    chain.current.hit_count = pkt.hit_count
                    self._forward(chain, chain.current)
                    pass
                case _:
                    raise ValueError(f"invalid op: {pkt.op}")
        elif (pending := self._pending_packet.pop(pkt.packet_id, None)) is not None:
            match pkt.op:
                case PendingPacket.OP_FINISH:
                    self._finish(pending, pkt)
                case PendingPacket.OP_CANCEL:
                    pending.current.hit_count = pkt.hit_count
                case PendingPacket.OP_FORWARD:
                    self._finish(pending, pkt)
                case PendingPacket.OP_PASS:
                    pending.current.hit_count = pkt.hit_count
                    self._finish(pending, pending.current)
                case _:
                    raise ValueError(f"invalid op: {pkt.op}")
        else:
            raise ValueError("invalid packet state")

    def _worker_thread(self) -> None:
        try:
            while not self._stop_event.is_set():
                id, pkt = self._recv()
                if pkt is None:
                    if self._stop_event.is_set():
                        break
                    continue

                match pkt.type:
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
                        self.extension_len.set(self.extension_len.get() + 1)
                    case Packet.TYPE_DISCONNECT:
                        self._extension_mgr.remove_extension(id)
                    case Packet.TYPE_PENDING_PACKET:
                        if TRACE:
                            print(f"recv from {id}: {pkt}")
                            print(
                                f"STATE (ext={len(self._extension_mgr._extensions)}, pending_chain={len(self._pending_chain)}, pending_packet={len(self._pending_packet)}):\n"
                                f"\tchain={self._pending_chain}\n",
                                f"\tpacket={self._pending_packet}\n",
                            )
                        self._handle_packet(pkt.pending_packet)
        except (KeyboardInterrupt, InterruptedError):
            pass
        except zmq.error.ZMQError as e:
            if not self._stop_event.is_set():
                self.logger.debug(f"ZMQ error in main loop: {e}")
        finally:
            self.logger.debug("worker thread exiting")
