# TODO: rename to types
from typing import Protocol, runtime_checkable


@runtime_checkable
class ConvertibleToInt(Protocol):
    def __int__(self) -> int: ...


@runtime_checkable
class ConvertibleToFloat(Protocol):
    def __float__(self) -> float: ...


@runtime_checkable
class ConvertibleToComplex(Protocol):
    def __complex__(self) -> complex: ...


@runtime_checkable
class ConvertibleToBool(Protocol):
    def __bool__(self) -> bool: ...


@runtime_checkable
class ConvertibleToStr(Protocol):
    def __str__(self) -> str: ...


@runtime_checkable
class ConvertibleToBytes(Protocol):
    def __bytes__(self) -> bytes: ...


@runtime_checkable
class SupportsLenAndGet[T](Protocol):
    def __len__(self) -> int: ...
    def __getitem__(self, index: int) -> T: ...


@runtime_checkable
class Vec2Like[T](Protocol):
    def __len__(self) -> int: ...
    def __getitem__(self, index: int) -> T: ...

    x: T
    y: T


@runtime_checkable
class Vec3Like[T](Protocol):
    def __len__(self) -> int: ...
    def __getitem__(self, index: int) -> T: ...

    x: T
    y: T
    z: T
