"""Hook registry: hooks are declared in Python, compiled to a payload.

A ``Hook`` is pure data until the framework connects to a live shim; the
runtime methods (``set_enabled``/``set_state``/``set_data``) then translate to
generic pipe commands. Nothing here knows what any hook is *for*.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Callable

from gtools.hooks import payload
from gtools.hooks.isa import Program

REGISTRY: dict[str, "Hook"] = {}
_control = None  # set by hook.py once a control connection is live


def set_control(control) -> None:
    global _control
    _control = control


def get_control():
    return _control


@dataclass(frozen=True)
class FastOp:
    """Native fast action executed by the shim without the interpreter."""

    op: int
    slot: int = 0


def Drop(slot: int = 0) -> FastOp:
    return FastOp(payload.FAST_DROP, slot)


def Pace(slot: int = 0) -> FastOp:
    return FastOp(payload.FAST_PACE, slot)


def Return(slot: int = 0) -> FastOp:
    return FastOp(payload.FAST_RETURN, slot)


@dataclass
class Hook:
    key: str
    patterns: list[str] = field(default_factory=list)
    export: tuple[str, str] | None = None
    rva: int | None = None
    stolen: int = payload.ENTRY_PATCH_BYTES
    fast: FastOp | None = None
    varargs_variant: int | None = None
    event_kind: int = 0
    scratch: int = 0
    program: bytes | None = None
    data: bytes = b""
    initial_state: dict[int, int] = field(default_factory=dict)
    initial_enabled: bool = False
    note: str = ""  # free-form annotation surfaced in dumps only

    # -- build --------------------------------------------------------------

    def kind(self) -> int:
        if self.fast is not None:
            return payload.KIND_FAST
        if self.varargs_variant is not None:
            return payload.KIND_VARARGS
        return payload.KIND_ISA

    def source(self) -> int:
        if self.export is not None:
            return payload.SRC_EXPORT
        if self.rva is not None:
            return payload.SRC_RVA
        return payload.SRC_PATTERN

    def descriptor(self) -> payload.Descriptor:
        module, symbol = self.export if self.export else ("", "")
        return payload.Descriptor(
            key=self.key,
            kind=self.kind(),
            source=self.source(),
            stolen_bytes=self.stolen,
            fast_op=self.fast.op if self.fast else payload.FAST_NONE,
            fast_slot=self.fast.slot if self.fast else 0,
            varargs_variant=self.varargs_variant or 0,
            event_kind=self.event_kind,
            scratch_bytes=self.scratch,
            program=self.program or b"",
            data=self.data,
            patterns=[payload.Pattern(signature) for signature in self.patterns],
            module=module,
            symbol=symbol,
            rva=self.rva or 0,
        )

    # -- live control -------------------------------------------------------

    def _require_control(self):
        if _control is None:
            raise RuntimeError(f"no live hook control connection for {self.key!r}")
        return _control

    def set_enabled(self, on: bool) -> None:
        self._require_control().enable(self.key, bool(on))

    @property
    def enabled(self) -> bool | None:
        if _control is None:
            return None
        status = _control.status()
        return status.get(f"enabled_{self.key}") == "1"

    def set_state(self, slot: int, value: int) -> None:
        if not 0 <= slot < payload.STATE_SLOTS:
            raise ValueError(f"state slot {slot} out of range")
        self._require_control().state(self.key, slot, int(value))

    def state(self, slot: int = 0) -> int:
        if not 0 <= slot < payload.STATE_SLOTS:
            raise ValueError(f"state slot {slot} out of range")
        if _control is None:
            return 0
        status = _control.status()
        try:
            return int(status.get(f"state_{self.key}_{slot}", "0"))
        except ValueError:
            return 0

    def set_data(self, blob: bytes, offset: int = 0) -> None:
        if offset + len(blob) > payload.DATA_MAX:
            raise ValueError("data blob exceeds the per-hook data cap")
        self._require_control().data(self.key, offset, blob)

    def __repr__(self) -> str:
        return f"Hook({self.key!r}, kind={self.kind()}, enabled={self.initial_enabled})"


def register(
    key: str,
    *,
    patterns: list[str] | tuple[str, ...] = (),
    export: tuple[str, str] | None = None,
    rva: int | None = None,
    stolen: int = payload.ENTRY_PATCH_BYTES,
    fast: FastOp | None = None,
    varargs_variant: int | None = None,
    event_kind: int = 0,
    scratch: int = 0,
    program: bytes | Program | Callable[[Program], None] | None = None,
    data: bytes = b"",
    initial_state: dict[int, int] | None = None,
    initial_enabled: bool = False,
    note: str = "",
) -> Hook:
    """Create and register a hook. ``program`` may be assembled bytes, a
    ``Program``, or a builder function receiving a fresh ``Program``."""
    if key in REGISTRY:
        raise ValueError(f"hook {key!r} is already registered")

    if callable(program) and not isinstance(program, (bytes, Program)):
        builder = Program()
        program(builder)
        program = builder
    if isinstance(program, Program):
        program = program.assemble()

    hook = Hook(
        key=key,
        patterns=list(patterns),
        export=export,
        rva=rva,
        stolen=stolen,
        fast=fast,
        varargs_variant=varargs_variant,
        event_kind=event_kind,
        scratch=scratch,
        program=program,
        data=data,
        initial_state=dict(initial_state or {}),
        initial_enabled=initial_enabled,
        note=note,
    )
    errors = hook.descriptor().validate()
    if errors:
        raise ValueError(f"invalid hook {key!r}: " + "; ".join(errors))
    REGISTRY[key] = hook
    return hook


def hook(key: str, **kwargs):
    """Decorator form of :func:`register`; the wrapped function builds the ISA
    program (``def handler(p: Program)``)."""

    def decorator(builder: Callable[[Program], None]) -> Hook:
        if "program" in kwargs:
            raise ValueError("the decorated function is the program builder")
        return register(key, program=builder, **kwargs)

    return decorator


def get(key: str) -> Hook:
    return REGISTRY[key]


def all_hooks() -> list[Hook]:
    return list(REGISTRY.values())


def build_payload(
    *,
    start_delay_ms: int = 2500,
    allow_any_module: bool = False,
    target_process: str = "Growtopia.exe",
) -> payload.Payload:
    """Compile the registry into an install payload."""
    result = payload.Payload(
        start_delay_ms=start_delay_ms,
        allow_any_module=allow_any_module,
        target_process=target_process,
    )
    for hook in all_hooks():
        result.descriptors.append(hook.descriptor())
    return result


def dump() -> str:
    """Human-readable dump of the registry (for logs and debugging)."""
    lines = []
    for hook in all_hooks():
        source = hook.export or (f"rva {hook.rva:#x}" if hook.rva is not None else f"{len(hook.patterns)} pattern(s)")
        extra = ""
        if hook.kind() == payload.KIND_ISA and hook.program:
            extra = f", program {len(hook.program)}B/{len(hook.program) // 16} insns"
        elif hook.kind() == payload.KIND_FAST:
            extra = f", fast op {hook.fast.op} slot {hook.fast.slot}"
        elif hook.kind() == payload.KIND_VARARGS:
            extra = f", varargs variant {hook.varargs_variant}"
        lines.append(f"{hook.key:24} {source}{extra} {' '.join(hook.patterns)}")
    return "\n".join(lines)


# varargs variant allocation helper for the log-style hooks
_next_varargs_variant = 0


def next_varargs_variant() -> int:
    global _next_varargs_variant
    variant = _next_varargs_variant
    _next_varargs_variant += 1
    if variant >= payload.VARARGS_VARIANTS:
        raise ValueError("no free varargs variant")
    return variant


def pack_state(value: int) -> bytes:
    return struct.pack("<Q", value)
