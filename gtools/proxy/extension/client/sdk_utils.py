# TODO: ditch this whole shit
from abc import ABC, abstractmethod
import itertools
import logging
from pyglm import glm
from google.protobuf.any_pb2 import Any
from typing import Any as TAny, Callable, overload
from gtools.core.convertible import ConvertibleToBytes, ConvertibleToFloat, ConvertibleToInt, ConvertibleToStr, SupportsLenAndGet, Vec2Like, Vec3Like
from gtools.core.growtopia.create import console_message, particle, play_sfx
from gtools.core.growtopia.packet import NetPacket, PreparedPacket, TankFlags
from gtools.core.growtopia.strkv import KeyType
from gtools.core.limits import INT32_MAX
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    INTEREST_GENERIC_TEXT,
    Interest,
    InterestGenericText,
    PendingPacket,
)
from gtools.protogen.op_pb2 import OP_EQ, OP_STARTSWITH, BinOp, Op
from gtools.protogen.strkv_pb2 import Clause, FindCol, FindRow, Query
from gtools.protogen.tank_pb2 import Field, FieldValue
from gtools.protogen.variant_pb2 import VariantClause
from gtools.proxy.state import State
from pyglm.glm import ivec2, ivec4, vec2, vec4

from thirdparty.enet.bindings import ENetPacketFlag


class BinOpSelector:
    def __init__(self, lvalue: Any, hint: Callable[["helper.Type | TAny"], "helper.Type"] | None = None) -> None:
        self.lvalue = lvalue
        self.hint = hint

    def _guess_type(self, other: TAny) -> "helper.Type":
        if isinstance(other, helper.Type):
            return other
        elif isinstance(other, int):
            if other < 0:
                return helper.int(other)
            elif other > INT32_MAX:
                return helper.uint(other)
            else:
                return helper.int(other)
        elif isinstance(other, float):
            return helper.float(other)
        elif isinstance(other, glm.vec2):
            return helper.vec2(other)
        elif isinstance(other, glm.vec3):
            return helper.vec3(other)
        elif isinstance(other, SupportsLenAndGet) and len(other) >= 2 and isinstance(other[0], float):
            if len(other) == 2:
                return helper.vec2(glm.vec2(other))
            elif len(other) == 3:
                return helper.vec3(glm.vec3(other))
            else:
                raise ValueError(f"vec with {len(other)} components not supported")
        elif isinstance(other, bytes):
            return helper.bytes(other)
        elif isinstance(other, str):
            return helper.str(other)
        else:
            raise ValueError(f"value not handled {other}")

    def _binop(self, other: "helper.Type | TAny", op: Op) -> BinOp:
        if self.hint:
            other = self.hint(other)
        else:
            if not isinstance(other, helper.Type):
                other = self._guess_type(other)

        return BinOp(
            lvalue=self.lvalue,
            op=op,
            **other.make(),
        )

    def __eq__(self, other: "helper.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_EQ)

    def __ne__(self, other: "helper.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_NEQ)

    def __gt__(self, other: "helper.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_GT)

    def __ge__(self, other: "helper.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_GTE)

    def __lt__(self, other: "helper.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_LT)

    def __le__(self, other: "helper.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_LTE)

    def contains(self, other: "helper.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_CONTAINS)

    def eq_eps(self, other: "helper.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_EQ_EPS)

    def bit_test(self, other: "helper.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_BIT_TEST)

    def startswith(self, other: "helper.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_STARTSWITH)

    def endswith(self, other: "helper.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_ENDSWITH)

    def like(self, other: "helper.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_LIKE)

    def divides_by(self, other: "helper.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_DIVIDES_BY)

    def not_divides_by(self, other: "helper.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_NOT_DIVIDES_BY)


def any(obj: object) -> Any:
    ret = Any()
    ret.Pack(obj)

    return ret


class VariantProxy:
    def __getitem__(self, index: int) -> BinOpSelector:
        return BinOpSelector(any(VariantClause(v=index)))


class StrKVProxy:
    def __init__(self) -> None:
        self.row_method = FindRow.KEY
        self.col_method = FindCol.ABSOLUTE

    @property
    def relative(self) -> "StrKVProxy":
        self.col_method = FindCol.RELATIVE
        return self

    @property
    def find(self) -> "StrKVProxy":
        self.row_method = FindRow.KEY_ANY
        return self

    @overload
    def __getitem__(self, key: KeyType) -> BinOpSelector: ...
    @overload
    def __getitem__(self, key: tuple[KeyType, int]) -> BinOpSelector: ...
    def __getitem__(self, key: KeyType | tuple[KeyType, int]) -> BinOpSelector:
        if isinstance(key, tuple):
            r, c = key
        else:
            r, c = key, None

        if isinstance(r, bytes):
            row = FindRow(method=self.row_method, key=r)
        elif isinstance(r, str):
            row = FindRow(method=self.row_method, key=r.encode())
        else:  # int
            row = FindRow(method=FindRow.INDEX, index=r)

        col = None
        if c:
            col = FindCol(method=self.col_method, index=c)

        def to_bytes(other: "helper.Type | TAny") -> "helper.bytes":
            if not isinstance(other, helper.Type):
                if isinstance(other, bytes):
                    return helper.bytes(other)
                else:
                    return helper.bytes(str(other).encode())

            if isinstance(other, helper.bytes):
                return other
            else:
                return helper.bytes(str(other.x).encode())

        return BinOpSelector(any(Query(where=[Clause(row=row, col=col)])), hint=to_bytes)


class helper:
    logger = logging.getLogger("ext_dispatch_helper")

    def __init__(self) -> None:
        self._counter = itertools.count()

    @property
    def variant(self) -> VariantProxy:
        return VariantProxy()

    @property
    def strkv(self) -> StrKVProxy:
        return StrKVProxy()

    @property
    def tank_type(self) -> BinOpSelector:
        return BinOpSelector(any(FieldValue(v=Field.TANK_FIELD_TYPE)))

    @property
    def tank_object_type(self) -> BinOpSelector:
        return BinOpSelector(any(FieldValue(v=Field.TANK_FIELD_OBJECT_TYPE)))

    @property
    def tank_jump_count(self) -> BinOpSelector:
        return BinOpSelector(any(FieldValue(v=Field.TANK_FIELD_JUMP_COUNT)))

    @property
    def tank_animation_type(self) -> BinOpSelector:
        return BinOpSelector(any(FieldValue(v=Field.TANK_FIELD_ANIMATION_TYPE)))

    @property
    def tank_net_id(self) -> BinOpSelector:
        return BinOpSelector(any(FieldValue(v=Field.TANK_FIELD_NET_ID)))

    @property
    def tank_target_net_id(self) -> BinOpSelector:
        return BinOpSelector(any(FieldValue(v=Field.TANK_FIELD_TARGET_NET_ID)))

    @property
    def tank_flags(self) -> BinOpSelector:
        return BinOpSelector(any(FieldValue(v=Field.TANK_FIELD_FLAGS)))

    @property
    def tank_float_var(self) -> BinOpSelector:
        return BinOpSelector(any(FieldValue(v=Field.TANK_FIELD_FLOAT_VAR)))

    @property
    def tank_value(self) -> BinOpSelector:
        return BinOpSelector(any(FieldValue(v=Field.TANK_FIELD_VALUE)))

    @property
    def tank_vector_x(self) -> BinOpSelector:
        return BinOpSelector(any(FieldValue(v=Field.TANK_FIELD_VECTOR_X)))

    @property
    def tank_vector_y(self) -> BinOpSelector:
        return BinOpSelector(any(FieldValue(v=Field.TANK_FIELD_VECTOR_Y)))

    @property
    def tank_vector_x2(self) -> BinOpSelector:
        return BinOpSelector(any(FieldValue(v=Field.TANK_FIELD_VECTOR_X2)))

    @property
    def tank_vector_y2(self) -> BinOpSelector:
        return BinOpSelector(any(FieldValue(v=Field.TANK_FIELD_VECTOR_Y2)))

    @property
    def tank_particle_rotation(self) -> BinOpSelector:
        return BinOpSelector(any(FieldValue(v=Field.TANK_FIELD_PARTICLE_ROTATION)))

    @property
    def tank_int_x(self) -> BinOpSelector:
        return BinOpSelector(any(FieldValue(v=Field.TANK_FIELD_INT_X)))

    @property
    def tank_int_y(self) -> BinOpSelector:
        return BinOpSelector(any(FieldValue(v=Field.TANK_FIELD_INT_Y)))

    def _register_command(self, id: int, prefix: bytes) -> None:
        if not hasattr(self, "_command_reg"):
            self._command_reg = {}

        self._command_reg[id] = prefix

    def command_toggle(self, cmd: str | bytes, id: int) -> Interest:
        """match all text"""
        cmd = cmd.encode() if isinstance(cmd, str) else cmd
        return Interest(
            interest=INTEREST_GENERIC_TEXT,
            generic_text=InterestGenericText(
                where=[
                    BinOp(
                        lvalue=any(Query(where=[Clause(row=FindRow(method=FindRow.KEY_ANY, key=b"text"), col=FindCol(method=FindCol.RELATIVE, index=1))])),
                        op=OP_EQ,
                        buf=cmd,
                    )
                ]
            ),
            blocking_mode=BLOCKING_MODE_BLOCK,
            direction=DIRECTION_CLIENT_TO_SERVER,
            id=id,
        )

    def command(self, cmd: str | bytes, id: int) -> Interest:
        """match startswith"""
        cmd = cmd.encode() if isinstance(cmd, str) else cmd
        self._register_command(id, cmd)
        return Interest(
            interest=INTEREST_GENERIC_TEXT,
            generic_text=InterestGenericText(
                where=[
                    BinOp(
                        lvalue=any(Query(where=[Clause(row=FindRow(method=FindRow.KEY_ANY, key=b"text"), col=FindCol(method=FindCol.RELATIVE, index=1))])),
                        op=OP_STARTSWITH,
                        buf=cmd,
                    )
                ]
            ),
            blocking_mode=BLOCKING_MODE_BLOCK,
            direction=DIRECTION_CLIENT_TO_SERVER,
            id=id,
        )

    def parse_command(self, event: PendingPacket) -> str:
        if event.interest_id not in self._command_reg:
            self.logger.error(f"command not registered for {event}")
            return ""

        return NetPacket.deserialize(event.buf).generic_text.relative[b"text", 1].removeprefix(self._command_reg[event.interest_id]).decode().strip()

    class Type:
        x: TAny
        name: str

        def make(self) -> dict[str, TAny]:
            return {self.name: self.x}

    @property
    def auto(self) -> int:
        return next(self._counter)

    # ====================== NOTE: this needs to be in the end as to not shadow the builtin types  ======================
    class uint(Type):
        def __init__(self, x: ConvertibleToInt) -> None:
            self.x = int(x)
            self.name = "u32"

    class int(Type):
        def __init__(self, x: ConvertibleToInt) -> None:
            self.x = int(x)
            self.name = "i32"

    class float(Type):
        def __init__(self, x: ConvertibleToFloat) -> None:
            self.x = float(x)
            self.name = "flt"

    class str(Type):
        def __init__(self, x: ConvertibleToStr) -> None:
            self.x = str(x)
            self.name = "str"

    class bytes(Type):
        def __init__(self, x: ConvertibleToBytes) -> None:
            self.x = bytes(x)
            self.name = "buf"

    class vec2(Type):
        def __init__(self, x: Vec2Like[float]) -> None:
            self.x = glm.vec2(x)
            self.name = "vec2"

    class vec3(Type):
        def __init__(self, x: Vec3Like[float]) -> None:
            self.x = glm.vec3(x)
            self.name = "vec3"

    # ====================== NOTE: this needs to be in the end as to not shadow the builtin types  ======================


# NOTE: this will not be redefined even when imported multiple times
s = helper()


class ExtensionUtility(ABC):
    @abstractmethod
    def push(self, pkt: PreparedPacket) -> None: ...

    state: State
    logger = logging.getLogger("ext_utils")

    def console_log(self, msg: str) -> None:
        self.push(PreparedPacket(console_message(msg), DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))

    def play_sound(self, path: str) -> None:
        self.push(PreparedPacket(play_sfx(path), DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))

    def send_particle(self, id: int, alternate: int = 0, *, abs: glm.vec2 | None = None, tile: glm.ivec2 | None = None) -> None:
        pos = abs if abs else tile * 32 + 16 if tile else None
        if not pos:
            return

        self.push(PreparedPacket(particle(id, pos[0], pos[1], alternate), DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.NONE))

    def facing_left(self, *, abs: vec2 | None = None, tile: ivec2 | None = None) -> TankFlags:
        """``FACING_LEFT`` for a targeted tile/point -- the client's action rule.

        The tile-change reaction stamps the render target with the **tile centre**
        (``sub_14012ECC0``) and the render sync (``sub_140133A90``) writes
        ``avatar+0x61``: left iff the avatar's centre x is greater than the target
        x, right otherwise. No target keeps the current flag.
        """
        if abs:
            target = abs
        elif tile:
            target = vec2(tile) * 32 + 16
        else:
            return self.state.me.flags & TankFlags.FACING_LEFT

        colrect = self._colrect()
        centre_x = self.state.me.pos.x + colrect.z / 2
        return TankFlags.FACING_LEFT if centre_x > target.x else TankFlags.NONE

    def _colrect(self) -> vec4:
        """The local avatar's collision rect as ``(x, y, width, height)``."""
        if self.state.world and (player := self.state.world.get_player(self.state.me.net_id)):
            if player.colrect.z > 0 and player.colrect.w > 0:
                return player.colrect

        return vec4(0, 0, 20, 30)  # nothing known yet -- the local avatar's default hitbox

    def in_range(self, p2: ivec2, punch: bool) -> bool:
        """``HandleTouch``'s reach gate: the collision rect expanded by
        ``(range + 2) * 32`` px (``CharacterState`` already carries the ``+2``) must
        sweep the tile -- ``WorldView::collectGridTilesInRect`` semantics."""
        reach = self.state.me.state.punch_range if punch else self.state.me.state.build_range

        colrect = self._colrect()
        left = self.state.me.pos.x - reach * 32
        right = self.state.me.pos.x + colrect.z + reach * 32
        top = self.state.me.pos.y - reach * 32
        bottom = self.state.me.pos.y + colrect.w + reach * 32

        # collectGridTilesInRect sweeps floor(min / 32) .. floor((max - 1) / 32)
        return left // 32 <= p2.x <= (right - 1) // 32 and top // 32 <= p2.y <= (bottom - 1) // 32
