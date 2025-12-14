from typing import Literal, cast, overload
from gtools.core.buffer import Buffer
from dataclasses import dataclass
from enum import IntEnum


class Kind(IntEnum):
    FLOAT = 1
    STRING = 2
    VEC2 = 3
    VEC3 = 4
    UNSIGNED = 5
    SIGNED = 9


class Variant:
    @dataclass(frozen=True)
    class vfloat:
        value: float = 0.0
        kind: Literal[Kind.FLOAT] = Kind.FLOAT

        def __repr__(self) -> str:
            return f"Variant.vfloat({self.value})"

    @dataclass(frozen=True)
    class vstr:
        value: bytes = b""
        kind: Literal[Kind.STRING] = Kind.STRING

        def __repr__(self) -> str:
            return f"Variant.vstr({self.value!r})"

    @dataclass(frozen=True)
    class vvec2:
        value: tuple[float, float] = (0.0, 0.0)
        kind: Literal[Kind.VEC2] = Kind.VEC2

        def __repr__(self) -> str:
            x, y = self.value
            return f"Variant.vvec2({x}, {y})"

    @dataclass(frozen=True)
    class vvec3:
        value: tuple[float, float, float] = (0.0, 0.0, 0.0)
        kind: Literal[Kind.VEC3] = Kind.VEC3

        def __repr__(self) -> str:
            x, y, z = self.value
            return f"Variant.vvec3({x}, {y}, {z})"

    @dataclass(frozen=True)
    class vuint:
        value: int = 0
        kind: Literal[Kind.UNSIGNED] = Kind.UNSIGNED

        def __repr__(self) -> str:
            return f"Variant.vuint({self.value})"

    @dataclass(frozen=True)
    class vint:
        value: int = 0
        kind: Literal[Kind.SIGNED] = Kind.SIGNED

        def __repr__(self) -> str:
            return f"Variant.vint({self.value})"

    Type = vfloat | vstr | vvec2 | vvec3 | vuint | vint

    def __init__(self, values: list[Type] | None = None) -> None:
        self._values: list[Variant.Type] = values if values else []

    def __len__(self) -> int:
        return len(self._values)

    class _View[T]:
        def __init__(self, variant: "Variant", kind: Kind) -> None:
            self._variant = variant
            self._kind = kind

        def __len__(self) -> int:
            return len(self._variant)

        def _check_kind(self, v: "Variant.Type", idx: int | None = None) -> None:
            if v.kind != self._kind:
                if idx is None:
                    raise TypeError(f"element kind {v.kind!r} != expected {self._kind!r}")
                raise TypeError(f"element at index {idx} is {v.kind!r}, expected {self._kind!r}")

        @overload
        def __getitem__(self, idx: int) -> T: ...
        @overload
        def __getitem__(self, idx: slice) -> list[T]: ...

        def __getitem__(self, idx: object) -> object:
            vals = self._variant._values
            if isinstance(idx, slice):
                out: list[T] = []
                for v in vals[idx]:
                    self._check_kind(v)
                    out.append(cast(T, v.value))
                return out
            elif isinstance(idx, int):
                v = vals[idx]
                self._check_kind(v, idx)
                return cast(T, v.value)
            else:
                raise TypeError(f"invalid index: {idx}")

    @property
    def as_float(self) -> "Variant._View[float]":
        return Variant._View(self, Kind.FLOAT)

    @property
    def as_string(self) -> "Variant._View[bytes]":
        return Variant._View(self, Kind.STRING)

    @property
    def as_vec2(self) -> "Variant._View[tuple[float, float]]":
        return Variant._View(self, Kind.VEC2)

    @property
    def as_vec3(self) -> "Variant._View[tuple[float, float, float]]":
        return Variant._View(self, Kind.VEC3)

    @property
    def as_uint(self) -> "Variant._View[int]":
        return Variant._View(self, Kind.UNSIGNED)

    @property
    def as_int(self) -> "Variant._View[int]":
        return Variant._View(self, Kind.SIGNED)

    def __getitem__(self, idx: int) -> "Variant.Type":
        return self._values[idx]

    def __setitem__(self, idx: int, value: "Variant.Type") -> None:
        self._values[idx] = value

    def append(self, v: "Variant.Type") -> None:
        self._values.append(v)

    def pop(self, idx: int = -1) -> "Variant.Type":
        return self._values.pop(idx)

    def serialize(self) -> bytes:
        s = Buffer(endian="<")
        s.write_u8(len(self._values))

        for index, v in enumerate(self._values):
            s.write_u8(index & 0xFF)
            s.write_u8(v.kind)

            if v.kind == Kind.FLOAT:
                s.write_f32(v.value)
            elif v.kind == Kind.STRING:
                s.write_pascal_bytes(v.value, "I")
            elif v.kind == Kind.VEC2:
                x, y = v.value
                s.write_f32(x)
                s.write_f32(y)
            elif v.kind == Kind.VEC3:
                x, y, z = v.value
                s.write_f32(x)
                s.write_f32(y)
                s.write_f32(z)
            elif v.kind == Kind.UNSIGNED:
                s.write_u32(v.value)
            elif v.kind == Kind.SIGNED:
                s.write_i32(v.value)
            else:
                raise ValueError("invalid Kind")

        return s.serialize()

    @classmethod
    def deserialize(cls, data: bytes) -> "Variant":
        s = Buffer(data, endian="<")
        count = s.read_u8()
        out: list[Variant.Type] = []
        for _ in range(count):
            _ = s.read_u8()
            kind = Kind(s.read_u8())

            if kind == Kind.FLOAT:
                out.append(Variant.vfloat(value=s.read_f32()))
            elif kind == Kind.STRING:
                out.append(Variant.vstr(value=s.read_pascal_bytes("I")))
            elif kind == Kind.VEC2:
                out.append(Variant.vvec2(value=(s.read_f32(), s.read_f32())))
            elif kind == Kind.VEC3:
                out.append(Variant.vvec3(value=(s.read_f32(), s.read_f32(), s.read_f32())))
            elif kind == Kind.UNSIGNED:
                out.append(Variant.vuint(value=s.read_u32()))
            elif kind == Kind.SIGNED:
                out.append(Variant.vint(value=s.read_i32()))

        return cls(out)

    @staticmethod
    # TODO: this is incorrect
    def get(data: bytes, idx: int) -> "Variant.Type":
        s = Buffer(data, endian="<")
        count = s.read_u8()
        for i in range(count):
            _ = s.read_u8()
            kind = Kind(s.read_u8())

            if i == idx:
                if kind == Kind.FLOAT:
                    return Variant.vfloat(value=s.read_f32())
                elif kind == Kind.STRING:
                    return Variant.vstr(value=s.read_pascal_bytes("I"))
                elif kind == Kind.VEC2:
                    return Variant.vvec2(value=(s.read_f32(), s.read_f32()))
                elif kind == Kind.VEC3:
                    return Variant.vvec3(value=(s.read_f32(), s.read_f32(), s.read_f32()))
                elif kind == Kind.UNSIGNED:
                    return Variant.vuint(value=s.read_u32())
                elif kind == Kind.SIGNED:
                    return Variant.vint(value=s.read_i32())

        raise ValueError(f"invalid index: {idx} (len={count})")

    def __repr__(self) -> str:
        vals = ", ".join(repr(v) for v in self._values)
        return f"Variant([{vals}])"


if __name__ == "__main__":
    var = Variant()
    var.append(Variant.vstr(b"Test"))
    var.append(Variant.vfloat(1.23))

    a = var.serialize()
    print(a)

    print(Variant.deserialize(a))

    print(var.as_float[1])
    print(var.as_string[0])
