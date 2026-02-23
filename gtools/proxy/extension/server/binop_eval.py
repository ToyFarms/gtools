import logging
import re
from typing import Any, Callable, cast

from google.protobuf.internal.containers import RepeatedCompositeFieldContainer
from gtools.core.growtopia.packet import NetType, TankPacket, TankType
from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.variant import Variant
from gtools.protogen.extension_pb2 import InterestType
from gtools.protogen.op_pb2 import BinOp, Op
from gtools.protogen.strkv_pb2 import FindCol, FindRow, Query
from gtools.protogen.tank_pb2 import Field, FieldValue
from gtools.protogen.variant_pb2 import VariantClause

TANK_INTEREST = {
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

logger = logging.getLogger("matcher")


def eval_strkv(kv: StrKV, where: RepeatedCompositeFieldContainer[BinOp]) -> bool:
    try:
        for clause in where:
            lvalue = Query()
            if not clause.lvalue.Unpack(lvalue):
                raise TypeError("strkv lvalue expects a query type")

            for find in lvalue.where:
                if find.HasField("col"):
                    try:
                        col = _GET_COL[find.row.method, find.col.method](kv, getattr(find.row, find.row.WhichOneof("m")), find.col.index)
                    except KeyError:
                        return False
                    if not _OP_EVALUATE[clause.op](col, getattr(clause, clause.WhichOneof("rvalue"))):
                        return False
                else:
                    try:
                        row = _GET_ROW[find.row.method](kv, getattr(find.row, find.row.WhichOneof("m")))
                    except KeyError:
                        return False
                    if not _OP_EVALUATE[clause.op](row, getattr(clause, clause.WhichOneof("rvalue"))):
                        return False
    except Exception as e:
        logger.warning(f"failed matching strkv clause with exception: {e}")
        return False

    return True


def eval_tank(tank: TankPacket, where: RepeatedCompositeFieldContainer[BinOp]) -> bool:
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


def eval_variant(variant: Variant, where: RepeatedCompositeFieldContainer[BinOp]) -> bool:
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
