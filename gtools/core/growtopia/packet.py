from dataclasses import dataclass
from enum import IntEnum, IntFlag
import logging
import time
from typing import Callable, ClassVar, Literal, Protocol, cast

from gtools import setting
from gtools.core.buffer import Buffer
from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.variant import Variant
from gtools.core.convertible import ConvertibleToFloat, ConvertibleToInt
from gtools.protogen.extension_pb2 import Direction, PendingPacket
from thirdparty.enet.bindings import ENetPacketFlag

Mode = Literal["strict", "relaxed"]


class BufferSerializable(Protocol):
    @classmethod
    def deserialize(cls, s: Buffer) -> "BufferSerializable": ...
    def serialize_into(self, s: Buffer) -> None: ...

    def serialize(self) -> bytes:
        b = Buffer()
        self.serialize_into(b)
        return b.serialize()


class Packet(BufferSerializable): ...


class PacketWithMode(Packet):
    def serialize_into(self, s: Buffer, mode: Mode = "relaxed") -> None: ...
    def serialize(self, mode: Mode = "relaxed") -> bytes:
        b = Buffer()
        self.serialize_into(b, mode)
        return b.serialize()


class NetWorldPacket(BufferSerializable): ...


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

    # see docs/02_packet
    NETWORLD_SNAPSHOT = 9
    NETWORLD_DELTA = 10
    NETWORLD_STATE = 11

    @classmethod
    def _missing_(cls, value: int) -> "NetType":
        obj = int.__new__(cls, value)
        obj._name_ = f"UNKNOWN_{value}"
        obj._value_ = value
        return obj


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
    FLYING = 1 << 1
    RESET_VISUAL_STATE = 1 << 2
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
    DOUBLE_JUMPED = 1 << 26
    UNK3 = 1 << 27
    ACID_DAMAGE = 1 << 28


class PlayerFrameFlags(IntFlag):
    NONE = 0
    LEFT = 1
    RIGHT = 2
    JUMP = 4
    LEFT_RIGHT = LEFT | RIGHT
    LEFT_JUMP = LEFT | JUMP
    RIGHT_JUMP = RIGHT | JUMP


_NET_TYPES: dict[int, NetType] = {m.value: m for m in NetType}
_TANK_TYPES: dict[int, TankType] = {m.value: m for m in TankType}


class TankPacket(PacketWithMode):
    logger = logging.getLogger("tank_packet")

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
        extended_data: bytes | None = b"",
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
        # do not check if extended_data is None, otherwise check for mismatch
        if extended_data is not None and extended_len != 0 and extended_len != len(extended_data):
            self.logger.warning(f"extended_len ({extended_len}) supplied does not match extended_data actual length ({len(extended_data)}, {extended_data[:100]})")
        elif extended_data is None:
            extended_data = b""
        self._extended_data = extended_data
        if extended_len == 0 and extended_data:
            self.flags |= TankFlags.EXTENDED
            self.extended_len = len(extended_data)
        else:
            self.extended_len = extended_len

    @property
    def extended_data(self) -> bytes:
        return self._extended_data

    @extended_data.setter
    def extended_data(self, data: bytes) -> None:
        self._extended_data = data
        self.extended_len = len(data)

    @classmethod
    def deserialize(cls, s: Buffer | bytes, mode: Mode = "relaxed") -> "TankPacket":
        s = s if isinstance(s, Buffer) else Buffer(s)
        t = cls()
        type_id = s.read_u8()
        t.type = _TANK_TYPES.get(type_id) or TankType(type_id)
        t.object_type = s.read_u8()
        t.jump_count = s.read_u8()
        t.animation_type = s.read_u8()
        t.net_id = s.read_i32()
        t.target_net_id = s.read_i32()
        t.flags = TankFlags(s.read_u32())
        t.float_var = s.read_f32()
        t.value = s.read_u32()
        t.vector_x = s.read_f32()
        t.vector_y = s.read_f32()
        t.vector_x2 = s.read_f32()
        t.vector_y2 = s.read_f32()
        t.particle_rotation = s.read_f32()
        t.int_x = s.read_i32()
        t.int_y = s.read_i32()
        t.extended_len = s.read_u32()
        extended_data = s.read_bytes(-1)
        t._extended_data = extended_data

        # sometimes the length advertised is outright wrong
        if t.extended_len != len(extended_data):
            msg = f"extended data size does not match (advertised: {t.extended_len}, actual: {len(extended_data)}): {t}, extended={extended_data[:100]}"
            if mode == "strict":
                raise ValueError(msg)
            cls.logger.warning(msg)

        # sometimes the extended flag is not set even when there is extended data
        if extended_data and t.flags & TankFlags.EXTENDED == 0:
            msg = f"packet has extended data but the flag is not set: {t}, extended={extended_data[:100]}"
            if mode == "strict":
                raise ValueError(msg)
            cls.logger.warning(msg)

        return t

    def serialize_into(self, s: Buffer, mode: Mode = "relaxed") -> None:
        ext = self._extended_data
        if ext and self.flags & TankFlags.EXTENDED == 0:
            msg = "has extended data, but the flags is not set"
            if mode == "strict":
                raise ValueError(msg)
            self.logger.warning(msg)

        s.write_u8(self.type)
        s.write_u8(self.object_type)
        s.write_u8(self.jump_count)
        s.write_u8(self.animation_type)
        s.write_i32(self.net_id)
        s.write_i32(self.target_net_id)
        s.write_u32(self.flags)
        s.write_f32(self.float_var)
        s.write_u32(self.value)
        s.write_f32(self.vector_x)
        s.write_f32(self.vector_y)
        s.write_f32(self.vector_x2)
        s.write_f32(self.vector_y2)
        s.write_f32(self.particle_rotation)
        s.write_i32(self.int_x)
        s.write_i32(self.int_y)
        s.write_u32(self.extended_len)
        if ext:
            s.write_bytes(ext)

    def __repr__(self) -> str:
        extra = ""
        if self.type == TankType.CALL_FUNCTION:
            extra = f", __extra=Call({Variant.deserialize(self.extended_data)})"

        return f"TankPacket(type={self.type!r}, object_type={self.object_type}, jump_count={self.jump_count}, animation_type={self.animation_type}, net_id={self.net_id}, target_net_id={self.target_net_id}, flags={self.flags!r}, float_var={self.float_var}, value={self.value}, vector_x={self.vector_x}, vector_y={self.vector_y}, vector_x2={self.vector_x2}, vector_y2={self.vector_y2}, particle_rotation={self.particle_rotation}, int_x={self.int_x}, int_y={self.int_y}, extended_len={self.extended_len}, extended_data={self.extended_data}{extra})"

    def compact_repr(self) -> str:
        if self.type == TankType.CALL_FUNCTION:
            return f"Call({Variant.deserialize(self.extended_data).compact_repr()})"

        def filter_default_value(x: object) -> bool:
            if isinstance(x, str):
                return x != ""
            elif isinstance(x, bytes):
                return x != b""
            elif isinstance(x, int):
                return x != 0
            elif isinstance(x, float):
                return x != 0.0
            elif isinstance(x, ConvertibleToInt):
                return int(x) != 0
            elif isinstance(x, ConvertibleToFloat):
                return float(x) != 0

            return True

        fields = {"type": self.type.name} | dict(
            filter(
                lambda x: filter_default_value(x[1]),
                [
                    ("object_type", self.object_type),
                    ("jump_count", self.jump_count),
                    ("animation_type", self.animation_type),
                    ("net_id", self.net_id),
                    ("target_net_id", self.target_net_id),
                    ("flags", repr(self.flags) if self.flags != 0 else 0),
                    ("float_var", self.float_var),
                    ("value", self.value),
                    ("vector_x", self.vector_x),
                    ("vector_y", self.vector_y),
                    ("vector_x2", self.vector_x2),
                    ("vector_y2", self.vector_y2),
                    ("particle_rotation", self.particle_rotation),
                    ("int_x", self.int_x),
                    ("int_y", self.int_y),
                    ("extended_len", self.extended_len),
                    ("extended_data", self.extended_data[:50] + (b"..." if len(self.extended_data) > 50 else b"")),
                ],
            )
        )

        return f"TankPacket({', '.join(f'{k}={v}' for k, v in fields.items())})"


class EmptyPacket(Packet):
    @classmethod
    def deserialize(cls, s: Buffer) -> "EmptyPacket":
        return cls()

    def serialize_into(self, s: Buffer) -> None:
        pass

    def __repr__(self) -> str:
        return "<Empty>"


class UnknownPacket(Packet):
    def __init__(self, data: bytes) -> None:
        self.data = data

    @classmethod
    def deserialize(cls, s: Buffer) -> "UnknownPacket":
        return cls(s.read_bytes(-1))

    def serialize_into(self, s: Buffer) -> None:
        s.write_bytes(self.data)

    def __repr__(self) -> str:
        return f"{self.data!r}"


@dataclass(slots=True)
class NetWorldObjectUpdate(NetWorldPacket):
    SIZE: ClassVar[int] = 8

    net_id: int = 0  # u8
    state: int = 0  # u8
    x: int = 0  # u16
    y: int = 0  # u16
    effect_id: int = 0  # u8
    progress: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer) -> "NetWorldObjectUpdate":
        t = cls()
        t.net_id = s.read_u8()
        t.state = s.read_u8()
        t.x = s.read_u16()
        t.y = s.read_u16()
        t.effect_id = s.read_u8()
        t.progress = s.read_u8()

        return t

    def serialize_into(self, s: Buffer) -> None:
        s.write_u8(self.net_id)
        s.write_u8(self.state)
        s.write_u16(self.x)
        s.write_u16(self.y)
        s.write_u8(self.effect_id)
        s.write_u8(self.progress)


@dataclass(slots=True, repr=False)
class PlayerSnapshot(BufferSerializable):
    SIZE: ClassVar[int] = 24

    net_id: int = 0  # u8
    unknown_1: int = 0  # u8
    unknown_2: int = 0  # u8
    action_cooldown: int = 0  # u8
    player_frame: int = 0  # u32
    flags: TankFlags = TankFlags.NONE  # u32
    unknown_u16: int = 0  # u16
    x: int = 0  # u16
    y: int = 0  # u16
    velocity_x: int = 0  # i16
    velocity_y: int = 0  # i16
    jump_hold_time: int = 0  # u8
    jump_count: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer) -> "PlayerSnapshot":
        t = cls()
        t.net_id = s.read_u8()
        t.unknown_1 = s.read_u8()
        t.unknown_2 = s.read_u8()
        t.action_cooldown = s.read_u8()
        t.player_frame = s.read_u32()
        t.flags = TankFlags(s.read_u32())
        t.unknown_u16 = s.read_u16()
        t.x = s.read_u16()
        t.y = s.read_u16()
        t.velocity_x = s.read_i16()
        t.velocity_y = s.read_i16()
        t.jump_hold_time = s.read_u8()
        t.jump_count = s.read_u8()

        return t

    def serialize_into(self, s: Buffer) -> None:
        s.write_u8(self.net_id)
        s.write_u8(self.unknown_1)
        s.write_u8(self.unknown_2)
        s.write_u8(self.action_cooldown)
        s.write_u32(self.player_frame)
        s.write_u32(self.flags)
        s.write_u16(self.unknown_u16)
        s.write_u16(self.x)
        s.write_u16(self.y)
        s.write_i16(self.velocity_x)
        s.write_i16(self.velocity_y)
        s.write_u8(self.jump_hold_time)
        s.write_u8(self.jump_count)

    def __repr__(self) -> str:
        return (
            f"PlayerSnapshot(net_id={self.net_id}, unknown=({self.unknown_1},{self.unknown_2}), "
            f"action_cooldown={self.action_cooldown}, player_frame={self.player_frame}, flags={self.flags!r}, "
            f"unknown_u16={self.unknown_u16}, x={self.x}, y={self.y}, "
            f"velocity_x={self.velocity_x}, velocity_y={self.velocity_y}, "
            f"jump_hold_time={self.jump_hold_time}, jump_count={self.jump_count})"
        )


@dataclass(slots=True)
class NetWorldRenderObject(NetWorldPacket):
    SIZE: ClassVar[int] = 12

    object_type: int = 0  # u8
    item_id: int = 0  # u8
    x: int = 0  # u16
    y: int = 0  # u16
    target_x: int = 0  # u16
    target_y: int = 0  # u16
    effect_variant: int = 0  # u8
    owner_net_id: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer) -> "NetWorldRenderObject":
        t = cls()
        t.object_type = s.read_u8()
        t.item_id = s.read_u8()
        t.x = s.read_u16()
        t.y = s.read_u16()
        t.target_x = s.read_u16()
        t.target_y = s.read_u16()
        t.effect_variant = s.read_u8()
        t.owner_net_id = s.read_u8()

        return t

    def serialize_into(self, s: Buffer) -> None:
        s.write_u8(self.object_type)
        s.write_u8(self.item_id)
        s.write_u16(self.x)
        s.write_u16(self.y)
        s.write_u16(self.target_x)
        s.write_u16(self.target_y)
        s.write_u8(self.effect_variant)
        s.write_u8(self.owner_net_id)


@dataclass(slots=True)
class NetWorldObject(NetWorldPacket):
    SIZE: ClassVar[int] = 8

    net_id: int = 0  # u8
    object_type: int = 0  # u8
    item_id: int = 0  # u8
    reserved: int = 0  # u8
    x: int = 0  # u16
    y: int = 0  # u16

    @classmethod
    def deserialize(cls, s: Buffer) -> "NetWorldObject":
        t = cls()
        t.net_id = s.read_u8()
        t.object_type = s.read_u8()
        t.item_id = s.read_u8()
        t.reserved = s.read_u8()
        t.x = s.read_u16()
        t.y = s.read_u16()

        return t

    def serialize_into(self, s: Buffer) -> None:
        s.write_u8(self.net_id)
        s.write_u8(self.object_type)
        s.write_u8(self.item_id)
        s.write_u8(self.reserved)
        s.write_u16(self.x)
        s.write_u16(self.y)


class NetWorldDeletedNetID(NetWorldPacket):
    SIZE: ClassVar[int] = 4

    net_id: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer) -> "NetWorldDeletedNetID":
        t = cls()
        t.net_id = s.read_u32()

        return t

    def serialize_into(self, s: Buffer) -> None:
        s.write_u32(self.net_id)


@dataclass(slots=True)
class NetWorldAbility(NetWorldPacket):
    SIZE: ClassVar[int] = 3

    net_id: int = 0  # u8
    ability_id: int = 0  # u8
    value: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer) -> "NetWorldAbility":
        t = cls()
        t.net_id = s.read_u8()
        t.ability_id = s.read_u8()
        t.value = s.read_u8()

        return t

    def serialize_into(self, s: Buffer) -> None:
        s.write_u8(self.net_id)
        s.write_u8(self.ability_id)
        s.write_u8(self.value)


@dataclass(slots=True)
class NetWorldMovePlayer(NetWorldPacket):
    SIZE: ClassVar[int] = 6

    net_id: int = 0  # u8
    reserved: int = 0  # u8
    x: int = 0  # u16
    y: int = 0  # u16

    @classmethod
    def deserialize(cls, s: Buffer) -> "NetWorldMovePlayer":
        t = cls()
        t.net_id = s.read_u8()
        t.reserved = s.read_u8()
        t.x = s.read_u16()
        t.y = s.read_u16()

        return t

    def serialize_into(self, s: Buffer) -> None:
        s.write_u8(self.net_id)
        s.write_u8(self.reserved)
        s.write_u16(self.x)
        s.write_u16(self.y)


@dataclass(slots=True, repr=False)
class PlayerFrameCounter(Packet):
    SIZE: ClassVar[int] = 8

    frame: int = 0  # u32
    flags: PlayerFrameFlags = PlayerFrameFlags.NONE  # u8
    padding: bytes = b"\x00\x00\x00"

    @classmethod
    def deserialize(cls, s: Buffer) -> "PlayerFrameCounter":
        t = cls()
        t.frame = s.read_u32()
        t.flags = PlayerFrameFlags(s.read_u8())
        t.padding = s.read_bytes(3)

        return t

    def serialize_into(self, s: Buffer) -> None:
        s.write_u32(self.frame)
        s.write_u8(self.flags)
        s.write_bytes(self.padding)

    def __repr__(self) -> str:
        return f"PlayerFrameCounter(frame={self.frame}, flags={self.flags!r})"


class PositionSyncPacket(Packet):
    MAX_OBJECT_UPDATES = 100
    MAX_PLAYERS = 100

    def __init__(self, timestamp: int = 0, object_updates: list[NetWorldObjectUpdate] | None = None, players: list[PlayerSnapshot] | None = None) -> None:
        self.timestamp = timestamp
        self.object_updates = object_updates if object_updates is not None else []
        self.players = players if players is not None else []

    @classmethod
    def deserialize(cls, s: Buffer) -> "PositionSyncPacket":
        if s.remaining() < 5:
            return cls()

        timestamp = s.read_u32()
        object_updates: list[NetWorldObjectUpdate] = []
        for _ in range(s.read_u8()):
            object_updates.append(NetWorldObjectUpdate.deserialize(s))

        players: list[PlayerSnapshot] = []
        if not s.eof():
            for _ in range(s.read_u8()):
                players.append(PlayerSnapshot.deserialize(s))

        return cls(timestamp=timestamp, object_updates=object_updates, players=players)

    def serialize_into(self, s: Buffer) -> None:
        if len(self.object_updates) > self.MAX_OBJECT_UPDATES:
            raise ValueError(f"too many object updates: {len(self.object_updates)}")
        if len(self.players) > self.MAX_PLAYERS:
            raise ValueError(f"too many players: {len(self.players)}")

        s.write_u32(self.timestamp)
        s.write_u8(len(self.object_updates))
        for update in self.object_updates:
            update.serialize_into(s)
        s.write_u8(len(self.players))
        for player in self.players:
            player.serialize_into(s)

    def __repr__(self) -> str:
        return f"PositionSyncPacket(timestamp={self.timestamp}, object_updates={len(self.object_updates)}, players={len(self.players)})"


class NetWorldDeltaPacket(Packet):
    MAX_RENDER_OBJECTS = 100
    MAX_OBJECTS = 200
    MAX_DELETED_NET_IDS = 200
    MAX_ABILITIES = 100
    MAX_MOVED_PLAYERS = 100
    MAX_OBJECT_UPDATES = 100

    def __init__(
        self,
        timestamp: int = 0,
        render_objects: list[NetWorldRenderObject] | None = None,
        objects: list[NetWorldObject] | None = None,
        deleted_net_ids: list[NetWorldDeletedNetID] | None = None,
        abilities: list[NetWorldAbility] | None = None,
        moved_players: list[NetWorldMovePlayer] | None = None,
        object_updates: list[NetWorldObjectUpdate] | None = None,
        client_side: bool = False,
    ) -> None:
        self.timestamp = timestamp
        self.render_objects = render_objects if render_objects is not None else []
        self.objects = objects if objects is not None else []
        self.deleted_net_ids = deleted_net_ids if deleted_net_ids is not None else []
        self.abilities = abilities if abilities is not None else []
        self.moved_players = moved_players if moved_players is not None else []
        self.object_updates = object_updates if object_updates is not None else []
        self.client_side = client_side

    @classmethod
    def deserialize(cls, s: Buffer) -> "NetWorldDeltaPacket":
        if s.remaining() < 5:
            return cls()

        timestamp = s.read_u32()

        render_objects: list[NetWorldRenderObject] = []
        objects: list[NetWorldObject] = []
        deleted_net_ids: list[NetWorldDeletedNetID] = []
        abilities: list[NetWorldAbility] = []
        moved_players: list[NetWorldMovePlayer] = []
        object_updates: list[NetWorldObjectUpdate] = []

        for _ in range(s.read_u8()):
            render_objects.append(NetWorldRenderObject.deserialize(s))

        if not s.eof():
            for _ in range(s.read_u8()):
                objects.append(NetWorldObject.deserialize(s))

            for _ in range(s.read_u8()):
                deleted_net_ids.append(NetWorldDeletedNetID.deserialize(s))

            for _ in range(s.read_u8()):
                abilities.append(NetWorldAbility.deserialize(s))

            for _ in range(s.read_u8()):
                moved_players.append(NetWorldMovePlayer.deserialize(s))

            for _ in range(s.read_u8()):
                object_updates.append(NetWorldObjectUpdate.deserialize(s))

            client_side = False
        else:
            client_side = True

        return cls(
            timestamp=timestamp,
            render_objects=render_objects,
            objects=objects,
            deleted_net_ids=deleted_net_ids,
            abilities=abilities,
            moved_players=moved_players,
            object_updates=object_updates,
            client_side=client_side,
        )

    def serialize_into(self, s: Buffer) -> None:
        if len(self.render_objects) > self.MAX_RENDER_OBJECTS:
            raise ValueError(f"too many render_objects: {len(self.render_objects)}, max is {self.MAX_RENDER_OBJECTS}")

        if not self.client_side:
            if len(self.objects) > self.MAX_OBJECTS:
                raise ValueError(f"too many objects: {len(self.objects)}, max is {self.MAX_OBJECTS}")
            if len(self.deleted_net_ids) > self.MAX_DELETED_NET_IDS:
                raise ValueError(f"too many deleted_net_ids: {len(self.deleted_net_ids)}, max is {self.MAX_DELETED_NET_IDS}")
            if len(self.abilities) > self.MAX_ABILITIES:
                raise ValueError(f"too many abilities: {len(self.abilities)}, max is {self.MAX_ABILITIES}")
            if len(self.moved_players) > self.MAX_MOVED_PLAYERS:
                raise ValueError(f"too many moved_players: {len(self.moved_players)}, max is {self.MAX_MOVED_PLAYERS}")
            if len(self.object_updates) > self.MAX_OBJECT_UPDATES:
                raise ValueError(f"too many object_updates: {len(self.object_updates)}, max is {self.MAX_OBJECT_UPDATES}")

        s.write_u32(self.timestamp)

        s.write_u8(len(self.render_objects))
        for item in self.render_objects:
            item.serialize_into(s)

        if self.client_side:
            return

        s.write_u8(len(self.objects))
        for item in self.objects:
            item.serialize_into(s)

        s.write_u8(len(self.deleted_net_ids))
        for item in self.deleted_net_ids:
            item.serialize_into(s)

        s.write_u8(len(self.abilities))
        for item in self.abilities:
            item.serialize_into(s)

        s.write_u8(len(self.moved_players))
        for item in self.moved_players:
            item.serialize_into(s)

        s.write_u8(len(self.object_updates))
        for item in self.object_updates:
            item.serialize_into(s)

    def __repr__(self) -> str:
        return (
            f"NetWorldDeltaPacket(timestamp={self.timestamp}, "
            f"render_objects={len(self.render_objects)}, objects={len(self.objects)}, "
            f"deleted_net_ids={len(self.deleted_net_ids)}, abilities={len(self.abilities)}, "
            f"moved_players={len(self.moved_players)}, object_updates={len(self.object_updates)}, "
            f"client_side={self.client_side})"
        )


def _read_strkv(s: Buffer) -> StrKV:
    return StrKV.deserialize(s.read_bytes(-1))


_BODY_READERS: dict[NetType, Callable[[Buffer], Packet | StrKV]] = {
    NetType.SERVER_HELLO: EmptyPacket.deserialize,
    NetType.GAME_MESSAGE: _read_strkv,
    NetType.GENERIC_TEXT: _read_strkv,
    NetType.TRACK: _read_strkv,
    NetType.ERROR: EmptyPacket.deserialize,
    NetType.CLIENT_LOG_REQUEST: EmptyPacket.deserialize,
    NetType.CLIENT_LOG_RESPONSE: EmptyPacket.deserialize,
    NetType.NETWORLD_SNAPSHOT: PositionSyncPacket.deserialize,
    NetType.NETWORLD_DELTA: NetWorldDeltaPacket.deserialize,
    NetType.NETWORLD_STATE: PlayerFrameCounter.deserialize,
}


class NetPacket(BufferSerializable):
    def __init__(self, type: NetType, data: "BufferSerializable | StrKV") -> None:
        self.type = type
        self.data = data

    @classmethod
    def variant(
        cls,
        variant: Variant,
        type: TankType | int = TankType.CALL_FUNCTION,
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
    ) -> "NetPacket":
        return NetPacket(
            NetType.TANK_PACKET,
            TankPacket(
                type=type,
                object_type=object_type,
                jump_count=jump_count,
                animation_type=animation_type,
                net_id=net_id,
                target_net_id=target_net_id,
                flags=flags | TankFlags.EXTENDED,
                float_var=float_var,
                value=value,
                vector_x=vector_x,
                vector_y=vector_y,
                vector_x2=vector_x2,
                vector_y2=vector_y2,
                particle_rotation=particle_rotation,
                int_x=int_x,
                int_y=int_y,
                extended_data=variant.serialize(),
            ),
        )

    @classmethod
    def deserialize(cls, s: Buffer | bytes, mode: Mode = "relaxed") -> "NetPacket":
        s = s if isinstance(s, Buffer) else Buffer(s)
        raw_type = s.read_u32()
        type = _NET_TYPES.get(raw_type) or NetType(raw_type)

        if setting.anomaly_byte_compensation:
            s.truncate(max(s.rpos, len(s) - 1))

        if type is NetType.TANK_PACKET:
            body = TankPacket.deserialize(s, mode)
        else:
            body = _BODY_READERS.get(type, UnknownPacket.deserialize)(s)

        return cls(type, body)

    def serialize_into(self, s: Buffer) -> None:
        s.write_u32(self.type.value)

        body = self.data
        if isinstance(body, StrKV):
            s.write_bytes(body.serialize())
        else:
            body.serialize_into(s)

        if setting.anomaly_byte_compensation:
            s.write_u8(0)

    def __repr__(self) -> str:
        return f"NetPacket[{self.type.name}]({self.data})"

    def compact_repr(self) -> str:
        if callable(repr := getattr(self.data, "compact_repr", None)):
            return cast(str, repr())

        if isinstance(self.data, StrKV):
            return f"[{self.type.name}]{self.data}"
        else:
            return f"{self.data}"

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

    @property
    def position_sync(self) -> "PositionSyncPacket":
        if self.type is not NetType.NETWORLD_SNAPSHOT:
            raise TypeError("not a position sync packet")
        return cast(PositionSyncPacket, self.data)

    @property
    def networld_delta(self) -> "NetWorldDeltaPacket":
        if self.type is not NetType.NETWORLD_DELTA:
            raise TypeError("not a networld delta packet")
        return cast(NetWorldDeltaPacket, self.data)

    @property
    def player_frame_counter(self) -> "PlayerFrameCounter":
        if self.type is not NetType.NETWORLD_STATE:
            raise TypeError("not a player frame counter packet")
        return cast(PlayerFrameCounter, self.data)


class PreparedPacket:
    def __init__(self, packet: "NetPacket | Buffer | bytes", direction: Direction, flags: ENetPacketFlag) -> None:
        if isinstance(packet, NetPacket):
            self._packet = packet
            raw = Buffer()
            packet.serialize_into(raw)
            self._raw = raw
        else:
            self._raw = Buffer(packet)
            self._packet = NetPacket.deserialize(Buffer(self._raw.buffer))

        self.direction = direction
        self.flags = flags

    @property
    def as_net(self) -> NetPacket:
        return self._packet

    @property
    def as_raw(self) -> bytes:
        return self._raw.serialize()

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
        b"\x04\x00\x00\x00\x01\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x9b\x00\x00\x00\x02\x00\x02\x10\x00\x00\x00OnConsoleMessage\x01\x02~\x00\x00\x00CP:0_PL:1_OID:_CT:[SB]_ `5** from (`wuRalph`````5) in [```$EMBAGAMES```5] ** : ```$Looking for 3 letter world lmk what u got``\x00"
    ]

    n = 1_000_000
    start = time.perf_counter()
    for sample in samples:
        for _ in range(n):
            NetPacket.deserialize(Buffer(sample))

    elapsed = time.perf_counter() - start
    calls = n * len(samples)
    print(f"taking {elapsed}s {elapsed / calls * 1_000_000_000:.3f}ns / call")
