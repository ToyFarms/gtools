from enum import Enum, IntEnum, IntFlag
import logging
import struct
import time
from typing import Literal, cast

from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.variant import Variant
from gtools.core.protocol import Serializable
from gtools.protogen.extension_pb2 import Direction, PendingPacket
from thirdparty.enet.bindings import ENetPacketFlag


class NetType(IntEnum):
    UNKNOWN = 0
    SERVER_HELLO = 1
    GENERIC_TEXT = 2
    GAME_MESSAGE = 3
    TANK_PACKET = 4
    ERROR = 5
    TRACK = 6
    CLIENT_LOG_REQUEST = 7
    CLIENT_LOG_RESPONSE = 8


class TankType(IntEnum):
    STATE = 0
    CALL_FUNCTION = 1
    UPDATE_STATUS = 2
    TILE_CHANGE_REQUEST = 3
    SEND_MAP_DATA = 4
    SEND_TILE_UPDATE_DATA = 5
    SEND_TILE_UPDATE_DATA_MULTIPLE = 6
    TILE_ACTIVATE_REQUEST = 7
    TILE_APPLY_DAMAGE = 8
    SEND_INVENTORY_STATE = 9
    ITEM_ACTIVATE_REQUEST = 10
    ITEM_ACTIVATE_OBJECT_REQUEST = 11
    SEND_TILE_TREE_STATE = 12
    MODIFY_ITEM_INVENTORY = 13
    ITEM_CHANGE_OBJECT = 14
    SEND_LOCK = 15
    SEND_ITEM_DATABASE_DATA = 16
    SEND_PARTICLE_EFFECT = 17
    SET_ICON_STATE = 18
    ITEM_EFFECT = 19
    SET_CHARACTER_STATE = 20
    PING_REPLY = 21
    PING_REQUEST = 22
    GOT_PUNCHED = 23
    APP_CHECK_RESPONSE = 24
    APP_INTEGRITY_FAIL = 25
    DISCONNECT = 26
    BATTLE_JOIN = 27
    BATTLE_EVENT = 28
    USE_DOOR = 29
    SEND_PARENTAL = 30
    GONE_FISHIN = 31
    STEAM = 32
    PET_BATTLE = 33
    NPC = 34
    SPECIAL = 35
    SEND_PARTICLE_EFFECT_V2 = 36
    ACTIVATE_ARROW_TO_ITEM = 37
    SELECT_TILE_INDEX = 38
    SEND_PLAYER_TRIBUTE_DATA = 39
    FTUE_SET_ITEM_TO_QUICK_INVENTORY = 40
    PVE_NPC = 41
    PVP_CARD_BATTLE = 42
    PVE_APPLY_PLAYER_DAMAGE = 43
    PVE_NPC_POSITION_UPDATE = 44
    SET_EXTRA_MODS = 45
    ON_STEP_TILE_MOD = 46


class TankFlags(IntFlag):
    NONE = 0
    WALK = 1 << 0
    UNK2 = 1 << 1
    SPAWN_RELATED = 1 << 2
    EXTENDED = 1 << 3
    FACING_LEFT = 1 << 4
    STANDING = 1 << 5
    FIRE_DAMAGE = 1 << 6
    JUMP = 1 << 7
    GOT_KILLED = 1 << 8
    PUNCH = 1 << 9
    PLACE = 1 << 10
    TILE_CHANGE = 1 << 11
    GOT_PUNCHED = 1 << 12
    RESPAWN = 1 << 13
    OBJECT_COLLECT = 1 << 14
    TRAMPOLINE = 1 << 15
    DAMAGE = 1 << 16
    SLIDE = 1 << 17
    PARASOL = 1 << 18
    UNK_GRAVITY_RELATED = 1 << 19
    SWIM = 1 << 20
    WALL_HANG = 1 << 21
    POWER_UP_PUNCH_START = 1 << 22
    POWER_UP_PUNCH_END = 1 << 23
    UNK_TILE_CHANGE = 1 << 24
    HAY_CART_RELATED = 1 << 25
    ACID_RELATED_DAMAGE = 1 << 26
    UNK3 = 1 << 27
    ACID_DAMAGE = 1 << 28


# TODO: have constructor for variant
class TankPacket(Serializable):
    logger = logging.getLogger("tank_packet")
    _FMT: str = "<BBBBIiIfIfffffiiI"

    def __init__(
        self,
        type: TankType | int = TankType.STATE,
        object_type: int = 0,
        jump_count: int = 0,
        animation_type: int = 0,
        net_id: int = 0,
        target_net_id: int = 0,
        flags: TankFlags | int = TankFlags.NONE,
        float_var: float = 0.0,
        value: int = 0,
        vector_x: float = 0.0,
        vector_y: float = 0.0,
        vector_x2: float = 0.0,
        vector_y2: float = 0.0,
        particle_rotation: float = 0.0,
        int_x: int = 0,
        int_y: int = 0,
        extended_len: int = 0,
        extended_data: bytes = b"",
    ) -> None:
        self.type = type if isinstance(type, TankType) else TankType(type)
        self.object_type = object_type
        self.jump_count = jump_count
        self.animation_type = animation_type
        self.net_id = net_id
        self.target_net_id = target_net_id
        self.flags = flags if isinstance(flags, TankFlags) else TankFlags(flags)
        self.float_var = float_var
        self.value = value
        self.vector_x = vector_x
        self.vector_y = vector_y
        self.vector_x2 = vector_x2
        self.vector_y2 = vector_y2
        self.particle_rotation = particle_rotation
        self.int_x = int_x
        self.int_y = int_y
        if extended_len != 0 and extended_len != len(extended_data):
            raise ValueError(f"extended_len ({extended_len}) supplied does not match extended_data actual length ({len(extended_data)}, {extended_data})")
        self._extended_data = extended_data
        self.extended_len = len(extended_data)

    @property
    def extended_data(self) -> bytes:
        return self._extended_data

    @extended_data.setter
    def extended_data(self, data: bytes) -> None:
        self._extended_data = data
        self.extended_len = len(data)

    def serialize(self) -> bytes:
        if self.extended_data and self.flags & TankFlags.EXTENDED == 0:
            raise RuntimeError("has extended data, but the flags is not set")

        buf = bytearray()
        buf.extend(
            struct.pack(
                TankPacket._FMT,
                self.type.value,
                self.object_type,
                self.jump_count,
                self.animation_type,
                self.net_id,
                self.target_net_id,
                self.flags,
                self.float_var,
                self.value,
                self.vector_x,
                self.vector_y,
                self.vector_x2,
                self.vector_y2,
                self.particle_rotation,
                self.int_x,
                self.int_y,
                len(self.extended_data),
            )
        )
        if self.extended_data:
            buf.extend(self.extended_data)

        return bytes(buf)

    @classmethod
    def deserialize(
        cls,
        data: bytes,
        mode: Literal["strict", "relaxed"] = "relaxed",
    ) -> "TankPacket":
        pkt_size = struct.calcsize(TankPacket._FMT)
        values = struct.unpack(TankPacket._FMT, data[:pkt_size])
        extended_data = b""
        if len(data) > pkt_size:
            extended_data = data[pkt_size:]

        extended_size = values[-1]
        if extended_size != len(extended_data):
            msg = f"extended data size does not match (in the packet: {extended_size}, actual: {len(extended_data)}): {values}"
            if mode == "strict":
                raise RuntimeError(msg)
            else:
                if len(extended_data) > extended_size:
                    cls.logger.debug(f"truncating extended data ({len(extended_data)} to {extended_size})")
                    extended_data = extended_data[:extended_size]

            cls.logger.warning(msg)

        return cls(*values, extended_data=extended_data)

    def __repr__(self) -> str:
        extra = ""
        if self.type == TankType.CALL_FUNCTION:
            extra = f", __extra=Call({Variant.deserialize(self.extended_data)})"

        return f"TankPacket(type={self.type!r}, object_type={self.object_type}, jump_count={self.jump_count}, animation_type={self.animation_type}, net_id={self.net_id}, target_net_id={self.target_net_id}, flags={self.flags!r}, float_var={self.float_var}, value={self.value}, vector_x={self.vector_x}, vector_y={self.vector_y}, vector_x2={self.vector_x2}, vector_y2={self.vector_y2}, particle_rotation={self.particle_rotation}, int_x={self.int_x}, int_y={self.int_y}, extended_len={self.extended_len}, extended_data={self.extended_data}{extra})"


class EmptyPacket(Serializable):
    def serialize(self) -> bytes:
        return b""

    def __repr__(self) -> str:
        return "<Empty>"


class NetPacket(Serializable):
    def __init__(self, type: NetType, data: Serializable) -> None:
        self.type = type
        self.data = data

    def serialize(self) -> bytes:
        return struct.pack("<I", self.type.value) + self.data.serialize() + b"\x00"

    @classmethod
    def deserialize(cls, data: bytes, mode: Literal["strict", "relaxed"] = "relaxed") -> "NetPacket":
        type = NetType(struct.unpack("<I", data[:4])[0])

        pkt = data[4:-1]
        match type:
            case NetType.UNKNOWN:
                raise TypeError(f"got unknown type: {data}")
            case NetType.SERVER_HELLO:
                pkt = EmptyPacket()
            case NetType.TANK_PACKET:
                pkt = TankPacket.deserialize(pkt, mode)
            case NetType.GAME_MESSAGE | NetType.GENERIC_TEXT | NetType.TRACK:
                pkt = StrKV.deserialize(pkt)
            case NetType.ERROR | NetType.CLIENT_LOG_REQUEST | NetType.CLIENT_LOG_RESPONSE:
                pkt = EmptyPacket()

        return cls(type, pkt)

    def __repr__(self):
        return f"NetPacket[{self.type.name}]({self.data})"

    @property
    def tank(self) -> "TankPacket":
        if self.type is not NetType.TANK_PACKET:
            raise TypeError("not a tank packet")
        return cast(TankPacket, self.data)

    @property
    def game_message(self) -> "StrKV":
        if self.type is not NetType.GAME_MESSAGE:
            raise TypeError("not a game message packet")
        return cast(StrKV, self.data)

    @property
    def generic_text(self) -> "StrKV":
        if self.type is not NetType.GENERIC_TEXT:
            raise TypeError("not a generic text packet")
        return cast(StrKV, self.data)

    @property
    def track(self) -> "StrKV":
        if self.type is not NetType.TRACK:
            raise TypeError("not a track packet")
        return cast(StrKV, self.data)


class PreparedPacket:
    def __init__(self, packet: NetPacket | bytes, direction: Direction, flags: ENetPacketFlag) -> None:
        if isinstance(packet, NetPacket):
            self._packet = packet
            self._packet_raw = packet.serialize()
        else:
            self._packet = NetPacket.deserialize(packet)
            self._packet_raw = packet

        self.direction = direction
        self.flags = flags

    @property
    def as_net(self) -> NetPacket:
        return self._packet

    @property
    def as_raw(self) -> bytes:
        return self._packet_raw

    @classmethod
    def from_pending(cls, pending: PendingPacket) -> "PreparedPacket":
        return cls(
            packet=pending.buf,
            direction=pending.direction,
            flags=ENetPacketFlag(pending.packet_flags),
        )

    def to_pending(self) -> PendingPacket:
        return PendingPacket(
            buf=self.as_raw,
            direction=self.direction,
            packet_flags=self.flags,
        )

    def __repr__(self) -> str:
        return f"PreparedPacket(packet={self.as_net}, direction={self.direction}, flags={self.flags})"


if __name__ == "__main__":
    samples = [
        # "02000000616374696f6e7c696e7075740a7c746578747c61776a6961776a69646f61d5",
        # "02000000616374696f6e7c696e7075740a7c746578747c647700",
        # "02000000616374696f6e7c696e7075740a7c746578747c776401",
        # "02000000616374696f6e7c696e7075740a7c746578747c643a",
        # "02000000616374696f6e7c696e7075740a7c746578747c61b0",
        # "03000000616374696f6e7c717569745f746f5f6578697400",
        # "02000000616374696f6e7c696e7075740a7c746578747c746573737373737373737373737373737373737373737300",
        # "02000000616374696f6e7c696e7075740a7c746578747c424f4f524f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f2120",
        # "0400000001000000ffffffff000000000800000000000000ffffffff00000000000000000000000000000000000000000000000000000000a6010000020002070000004f6e537061776e010292010000737061776e7c6176617461720a6e657449447c3139330a7573657249447c3231303836373737350a6569647c3231303836373737357c434a5a6e70797966376b30433048546136644f447951594f744739547050747273566376532f50357650633d7c50793164474c49507a3842323853327a4f7a433265673d3d0a69707c6b577632614c3968454531334e6862736f77776274344b6e68586872634f6456577a6a4f3843596a7439493d0a636f6c726563747c307c307c32307c33300a706f7358597c3631347c3133300a6e616d657c6077796a67736d66726a60600a7469746c6549636f6e7c7b22506c61796572576f726c644944223a3139332c225772656e6368437573746f6d697a6174696f6e223a7b225772656e6368466f726567726f756e6443616e526f74617465223a66616c73652c225772656e6368466f726567726f756e644944223a2d312c225772656e636849636f6e4944223a2d317d7d0a636f756e7472797c75730a696e7669737c300a6d73746174657c300a736d73746174657c300a6f6e6c696e6549447c0a00",
        # "03000000616374696f6e7c7175697400",
        b"\x04\x00\x00\x00\x00\x00\x00\x00@\x00\x00\x00\x00\x00\x00\x00 \x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x008E\x00\x00!C\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    ]

    n = 1_000_000
    start = time.perf_counter()
    for sample in samples:
        for _ in range(n):
            NetPacket.deserialize(sample)

    elapsed = time.perf_counter() - start
    print(f"taking {elapsed}s {elapsed / n * 1000000000:.3f}ns / call")
