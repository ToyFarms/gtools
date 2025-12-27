from abc import ABC, abstractmethod
from pyglm import glm
from google.protobuf.any_pb2 import Any
from typing import Any as TAny
from gtools.core.convertible import ConvertibleToBytes, ConvertibleToFloat, ConvertibleToInt, ConvertibleToStr, SupportsLenAndGet, Vec2Like, Vec3Like
from gtools.core.growtopia.create import console_message, particle
from gtools.core.growtopia.packet import PreparedPacket
from gtools.core.limits import INT32_MAX
from gtools.protogen.extension_pb2 import BLOCKING_MODE_BLOCK, DIRECTION_CLIENT_TO_SERVER, DIRECTION_SERVER_TO_CLIENT, INTEREST_GENERIC_TEXT, Interest, InterestGenericText
from gtools.protogen.op_pb2 import OP_EQ, OP_STARTSWITH, BinOp, Op
from gtools.protogen.strkv_pb2 import Clause, FindCol, FindRow, Query
from gtools.protogen.tank_pb2 import Field, FieldValue
from gtools.protogen.variant_pb2 import VariantClause, VariantQuery
from thirdparty.enet.bindings import ENetPacketFlag


class BinOpSelector:
    def __init__(self, lvalue: Any) -> None:
        self.lvalue = lvalue

    def _guess_type(self, other: TAny) -> "ExtensionUtility.Type":
        if isinstance(other, ExtensionUtility.Type):
            return other
        elif isinstance(other, int):
            if other < 0:
                return ExtensionUtility.int(other)
            elif other > INT32_MAX:
                return ExtensionUtility.uint(other)
            else:
                return ExtensionUtility.int(other)
        elif isinstance(other, float):
            return ExtensionUtility.float(other)
        elif isinstance(other, glm.vec2):
            return ExtensionUtility.vec2(other)
        elif isinstance(other, glm.vec3):
            return ExtensionUtility.vec3(other)
        elif isinstance(other, SupportsLenAndGet) and len(other) >= 2 and isinstance(other[0], float):
            if len(other) == 2:
                return ExtensionUtility.vec2(glm.vec2(other))
            elif len(other) == 3:
                return ExtensionUtility.vec3(glm.vec3(other))
            else:
                raise ValueError(f"vec with {len(other)} components not supported")
        elif isinstance(other, bytes):
            return ExtensionUtility.bytes(other)
        elif isinstance(other, str):
            return ExtensionUtility.str(other)
        else:
            raise ValueError(f"value not handled {other}")

    def _binop(self, other: "ExtensionUtility.Type | TAny", op: Op) -> BinOp:
        if not isinstance(other, ExtensionUtility.Type):
            other = self._guess_type(other)

        return BinOp(
            lvalue=self.lvalue,
            op=op,
            **other.make(),
        )

    def __eq__(self, other: "ExtensionUtility.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_EQ)

    def __ne__(self, other: "ExtensionUtility.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_NEQ)

    def __gt__(self, other: "ExtensionUtility.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_GT)

    def __ge__(self, other: "ExtensionUtility.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_GTE)

    def __lt__(self, other: "ExtensionUtility.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_LT)

    def __le__(self, other: "ExtensionUtility.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_LTE)

    def contains(self, other: "ExtensionUtility.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_CONTAINS)

    def eq_eps(self, other: "ExtensionUtility.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_EQ_EPS)

    def bit_test(self, other: "ExtensionUtility.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_BIT_TEST)

    def startswith(self, other: "ExtensionUtility.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_STARTSWITH)

    def endswith(self, other: "ExtensionUtility.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_ENDSWITH)

    def like(self, other: "ExtensionUtility.Type | TAny") -> BinOp:
        return self._binop(other, Op.OP_LIKE)


def any(obj: object) -> Any:
    ret = Any()
    ret.Pack(obj)

    return ret


class VariantProxy:
    def __getitem__(self, index: int) -> BinOpSelector:
        return BinOpSelector(any(VariantClause(v=index)))


class ExtensionUtility(ABC):
    @abstractmethod
    def push(self, pkt: PreparedPacket) -> None: ...

    @property
    def variant(self) -> VariantProxy:
        return VariantProxy()

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

    def console_log(self, msg: str) -> None:
        self.push(PreparedPacket(console_message(msg), DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))

    def send_particle(self, id: int, f: int = 0, f2: int = 0, *, abs: glm.vec2 | None = None, tile: glm.ivec2 | None = None) -> None:
        pos = abs if abs else tile * 32 + 16 if tile else None
        pos = abs if abs else (tile[0] * 32.0 + 16, tile[1] * 32.0 + 16) if tile else None
        if not pos:
            return

        self.push(PreparedPacket(particle(id, pos[0], pos[1], f, f2), DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))

    # TODO: improve command
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

    class Type:
        x: TAny
        name: str

        def make(self) -> dict[str, TAny]:
            return {self.name: self.x}

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
