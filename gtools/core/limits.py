import sys
import struct
import decimal
from typing import Literal, cast, TypedDict

try:
    import numpy as _np  # pyright: ignore

    _HAS_NUMPY = True
except Exception:
    _HAS_NUMPY = False


def signed_int_limits(bits: int) -> tuple[int, int]:
    if bits <= 0:
        raise ValueError("bits must be > 0")
    mx = 2 ** (bits - 1) - 1
    mn = -(2 ** (bits - 1))
    return mn, mx


def unsigned_int_limits(bits: int) -> tuple[int, int]:
    if bits <= 0:
        raise ValueError("bits must be > 0")
    mx = 2**bits - 1
    return 0, mx


CHAR_BIT = 8
INT8_MIN, INT8_MAX = signed_int_limits(8)
UINT8_MIN, UINT8_MAX = unsigned_int_limits(8)
INT16_MIN, INT16_MAX = signed_int_limits(16)
UINT16_MIN, UINT16_MAX = unsigned_int_limits(16)
INT32_MIN, INT32_MAX = signed_int_limits(32)
UINT32_MIN, UINT32_MAX = unsigned_int_limits(32)
INT64_MIN, INT64_MAX = signed_int_limits(64)
UINT64_MIN, UINT64_MAX = unsigned_int_limits(64)

PY_INT_BOUNDED = False


CTypesLimits = TypedDict(
    "CTypesLimits",
    {
        "signed_char": tuple[int, int],
        "unsigned_char": tuple[int, int],
        "short": tuple[int, int],
        "unsigned_short": tuple[int, int],
        "int": tuple[int, int],
        "unsigned_int": tuple[int, int],
        "long": tuple[int, int],
        "unsigned_long": tuple[int, int],
        "long_long": tuple[int, int],
        "unsigned_long_long": tuple[int, int],
        "size_t": tuple[int, int],
        "ssize_t": tuple[int, int],
        "pointer_bits": int,
    },
)


class Float32Info(TypedDict):
    max: float
    min_pos_normal: float
    min_pos_subnormal: float
    eps: float
    mantissa_bits: int
    exponent_bits: int


class Float64Info(TypedDict):
    max: float
    min_pos_normal: float
    min_pos_subnormal: float
    eps: float
    mantissa_bits: int
    exponent_bits: int


class NumpyIntegerLimits(TypedDict):
    min: int
    max: int


class NumpyFloatLimits(TypedDict):
    max: float
    min_pos: float
    eps: float


Rounding = Literal[
    "ROUND_DOWN",
    "ROUND_HALF_UP",
    "ROUND_HALF_EVEN",
    "ROUND_CEILING",
    "ROUND_FLOOR",
    "ROUND_UP",
    "ROUND_HALF_DOWN",
    "ROUND_05UP",
]


class DecimalLimits(TypedDict):
    prec: int
    Emax: int
    Emin: int
    rounding: Rounding


def ctypes_type_limits() -> CTypesLimits:
    import ctypes

    mapping: CTypesLimits = {
        "signed_char": (0, 0),
        "unsigned_char": (0, 0),
        "short": (0, 0),
        "unsigned_short": (0, 0),
        "int": (0, 0),
        "unsigned_int": (0, 0),
        "long": (0, 0),
        "unsigned_long": (0, 0),
        "long_long": (0, 0),
        "unsigned_long_long": (0, 0),
        "size_t": (0, 0),
        "ssize_t": (0, 0),
        "pointer_bits": 0,
    }

    candidates = [
        ("signed_char", ctypes.c_byte, True),
        ("unsigned_char", ctypes.c_ubyte, False),
        ("short", ctypes.c_short, True),
        ("unsigned_short", ctypes.c_ushort, False),
        ("int", ctypes.c_int, True),
        ("unsigned_int", ctypes.c_uint, False),
        ("long", ctypes.c_long, True),
        ("unsigned_long", ctypes.c_ulong, False),
        ("long_long", ctypes.c_longlong, True),
        ("unsigned_long_long", ctypes.c_ulonglong, False),
        ("size_t", ctypes.c_size_t, False),
        ("ssize_t", ctypes.c_ssize_t, True),
    ]

    for name, ctype, signed in candidates:
        bits = ctypes.sizeof(ctype) * 8
        if signed:
            mapping[name] = signed_int_limits(bits)
        else:
            mapping[name] = unsigned_int_limits(bits)

    ptr_bits = ctypes.sizeof(ctypes.c_void_p) * 8
    mapping["pointer_bits"] = ptr_bits

    return mapping


_STRUCT_INT_FORMATS = {
    "b": 8,
    "B": 8,
    "h": 16,
    "H": 16,
    "i": struct.calcsize("i") * 8,
    "I": struct.calcsize("I") * 8,
    "l": struct.calcsize("l") * 8,
    "L": struct.calcsize("L") * 8,
    "q": 64,
    "Q": 64,
}


def struct_format_limits(fmt: str) -> tuple[int, int]:
    if fmt in ("f", "d"):
        raise ValueError("Use float_limits for 'f' or 'd' formats")
    if fmt not in _STRUCT_INT_FORMATS:
        raise ValueError(f"Unknown/unsupported struct format: {fmt!r}")
    bits = _STRUCT_INT_FORMATS[fmt]
    if fmt.isupper():
        return unsigned_int_limits(bits)
    else:
        return signed_int_limits(bits)


# IEEE-754 constants for float32
FLOAT32_MANTISSA_BITS = 23
FLOAT32_EXPONENT_BITS = 8
FLOAT32_EXPONENT_BIAS = 127
FLOAT32_MAX = (2 - 2**-FLOAT32_MANTISSA_BITS) * 2 ** (2 ** (FLOAT32_EXPONENT_BITS - 1) - 1 - FLOAT32_EXPONENT_BIAS)
FLOAT32_MAX = (2 - 2**-FLOAT32_MANTISSA_BITS) * 2**127
FLOAT32_MIN_POS_NORMAL = 2**-126
FLOAT32_MIN_POS_SUBNORMAL = 2**-149
FLOAT32_EPS = 2**-FLOAT32_MANTISSA_BITS


# python float uses C doubles
FLOAT64_INFO = sys.float_info
FLOAT64_MAX = FLOAT64_INFO.max
FLOAT64_MIN_POS_NORMAL = FLOAT64_INFO.min
# smallest positive subnormal for IEEE-754 double is 2**-1074
FLOAT64_MIN_POS_SUBNORMAL = 2**-1074
FLOAT64_EPS = FLOAT64_INFO.epsilon


def float32_limits() -> Float32Info:
    return {
        "max": FLOAT32_MAX,
        "min_pos_normal": FLOAT32_MIN_POS_NORMAL,
        "min_pos_subnormal": FLOAT32_MIN_POS_SUBNORMAL,
        "eps": FLOAT32_EPS,
        "mantissa_bits": FLOAT32_MANTISSA_BITS,
        "exponent_bits": FLOAT32_EXPONENT_BITS,
    }


def float64_limits() -> Float64Info:
    return {
        "max": FLOAT64_MAX,
        "min_pos_normal": FLOAT64_MIN_POS_NORMAL,
        "min_pos_subnormal": FLOAT64_MIN_POS_SUBNORMAL,
        "eps": FLOAT64_EPS,
        "mantissa_bits": FLOAT64_INFO.mant_dig - 1,
        "exponent_bits": 11,
    }


def numpy_limits() -> dict[str, NumpyIntegerLimits | NumpyFloatLimits]:
    if not _HAS_NUMPY:
        raise RuntimeError("numpy is not available")
    out: dict[str, NumpyIntegerLimits | NumpyFloatLimits] = {}
    for dtype in (
        "float16",
        "float32",
        "float64",
        "float128",
        "int8",
        "int16",
        "int32",
        "int64",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
    ):
        try:
            npdtype = getattr(_np, dtype)
        except AttributeError:
            continue
        if _np.issubdtype(npdtype, _np.integer):
            val = _np.iinfo(npdtype)
            out[dtype] = {"min": int(val.min), "max": int(val.max)}
        else:
            val = _np.finfo(npdtype)
            out[dtype] = {"max": float(val.max), "min_pos": float(val.tiny), "eps": float(val.eps)}
    return out


def decimal_limits(context: decimal.Context | None = None) -> DecimalLimits:
    ctx = context or decimal.getcontext()
    return {
        "prec": ctx.prec,
        "Emax": ctx.Emax,
        "Emin": ctx.Emin,
        "rounding": cast(Rounding, ctx.rounding),
    }


def pointer_size_bits() -> int:
    return struct.calcsize("P") * 8


def max_container_index() -> int:
    return sys.maxsize


def recursion_limit() -> int:
    return sys.getrecursionlimit()


DBL_MAX = FLOAT64_MAX
DBL_MIN = FLOAT64_MIN_POS_NORMAL
DBL_EPSILON = FLOAT64_EPS
FLT_MAX = FLOAT32_MAX
FLT_MIN = FLOAT32_MIN_POS_NORMAL
FLT_EPSILON = FLOAT32_EPS


def int_limits(bits: int, signed: bool = True) -> tuple[int, int]:
    return signed_int_limits(bits) if signed else unsigned_int_limits(bits)


if __name__ == "__main__":
    import json

    summary = {
        "platform": platform_info if (platform_info := getattr(sys, "platform", None)) else sys.platform,
        "pointer_bits": pointer_size_bits(),
        "python_int_unbounded": not PY_INT_BOUNDED,
        "sys_maxsize": sys.maxsize,
        "recursion_limit": recursion_limit(),
        "c_limits": ctypes_type_limits(),
        "float32": float32_limits(),
        "float64": float64_limits(),
        "decimal": decimal_limits(),
    }

    if _HAS_NUMPY:
        try:
            summary["numpy"] = numpy_limits()
        except Exception as e:
            summary["numpy_error"] = str(e)

    print(json.dumps(summary, indent=2, default=str))
