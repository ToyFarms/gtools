"""Python mirror of ``gtools/hooks/hook_protocol.h`` (ABI v4).

Every constant and struct here must match the C header field for field;
``tests/test_hook_abi.py`` compiles the header and compares offsets, and
``tests/test_hook_payload.py`` round-trips the wire format. This module is the
single source of truth for the *Python* side; the C header is the single
source of truth for the C side.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

PROTOCOL_VERSION = 4
PROTOCOL_MAGIC = 0x4B485447  # "GTHK"
PAYLOAD_MAGIC = 0x50544847  # "GTHP"

PIPE_NAME = r"\\.\pipe\gtools_hook"
AGENT_MUTEX = r"Global\gtools_hook_agent"
PID_MUTEX_PREFIX = r"Global\gtools_hook_pid_"
LOCK_MUTEX_PREFIX = r"Global\gtools_hook_lock_"

HOOK_MAX = 32
KEY_MAX = 32
MODULE_MAX = 16
SYMBOL_MAX = 40
PATTERN_MAX = 4
PATTERN_BYTES = 64
PROGRAM_MAX = 8192
DATA_MAX = 1024
STATE_SLOTS = 8
EVENT_SLOTS = 128
EVENT_MAX = 768
PAYLOAD_MAX = 512 * 1024
VARARGS_VARIANTS = 8
ENTRY_PATCH_BYTES = 14

# HookKind
KIND_ISA = 0
KIND_FAST = 1
KIND_VARARGS = 2

# HookFastOp
FAST_NONE = 0
FAST_DROP = 1
FAST_PACE = 2
FAST_RETURN = 3

# HookSource
SRC_PATTERN = 0
SRC_EXPORT = 1
SRC_RVA = 2

# HookEntryStatus
STATUS_MISSING = 0
STATUS_READY = 1
STATUS_PATCHED = 2

# HookSlotState
SLOT_EMPTY = 0
SLOT_CLAIMED = 1
SLOT_READY = 2

HOOK_INDEX_SYSTEM = 0xFFFFFFFF

# --- struct formats ---------------------------------------------------------

PATTERN = struct.Struct("<I64s64s")
assert PATTERN.size == 132

_DESCRIPTOR_HEAD = struct.Struct("<32s12I")  # key + 12 uint32 fields
_DESCRIPTOR_TAIL = struct.Struct("<16s40sQQII")
DESCRIPTOR_SIZE = _DESCRIPTOR_HEAD.size + PATTERN_MAX * PATTERN.size + _DESCRIPTOR_TAIL.size
assert DESCRIPTOR_SIZE == 688

RUNTIME = struct.Struct("<32siiiiQQQQQ8Q1024s")
assert RUNTIME.size == 1176

EVENT_SLOT = struct.Struct("<iiIIII768s")
assert EVENT_SLOT.size == 792

HANDSHAKE_ENTRY = struct.Struct("<32sIIQQ")
assert HANDSHAKE_ENTRY.size == 56

PAYLOAD_HEAD = struct.Struct("<8I32s")
assert PAYLOAD_HEAD.size == 64

BLOB_SIZE = PROGRAM_MAX + DATA_MAX
PAYLOAD_SIZE = PAYLOAD_HEAD.size + HOOK_MAX * DESCRIPTOR_SIZE + HOOK_MAX * BLOB_SIZE
assert PAYLOAD_SIZE == 316992

# --- shared control block offsets (mirror struct ShimShared) ----------------

SHIM_OFF_MAGIC = 0
SHIM_OFF_VERSION = 4
SHIM_OFF_READY = 8
SHIM_OFF_PAYLOAD_REVISION = 12
SHIM_OFF_PAYLOAD_CRC = 16
SHIM_OFF_DESCRIPTOR_COUNT = 20
SHIM_OFF_PID = 24
SHIM_OFF_IMAGE_BASE = 32
SHIM_OFF_IMAGE_SIZE = 40
SHIM_OFF_DLL_BASE = 48
SHIM_OFF_BOOT_TICK = 56
SHIM_OFF_EVENT_TICKET = 64
SHIM_OFF_RUNTIME = 72
SHIM_OFF_EVENTS = SHIM_OFF_RUNTIME + HOOK_MAX * RUNTIME.size  # 37704
SHIM_OFF_PAYLOAD = SHIM_OFF_EVENTS + EVENT_SLOTS * EVENT_SLOT.size  # 139080
SHIM_SIZE = SHIM_OFF_PAYLOAD + PAYLOAD_MAX
assert SHIM_SIZE == 663368

# --- HookRuntime field offsets (used by programs and the asm stub) ----------

RT_OFF_KEY = 0
RT_OFF_ENABLED = 32
RT_OFF_STATUS = 36
RT_OFF_SELF_INDEX = 40
RT_OFF_HITS = 48
RT_OFF_FAULTS = 56
RT_OFF_TARGET = 64
RT_OFF_TRAMPOLINE = 72
RT_OFF_DETOUR = 80
RT_OFF_STATE = 88
RT_OFF_DATA = 152
RT_STRIDE = RUNTIME.size

RT_STATE_OFFSET = lambda slot: RT_OFF_STATE + 8 * slot  # noqa: E731

# --- HookCtx field offsets (programs read game registers via r15) -----------

CTX_OFF_GPR = 0            # uint64 gpr[16]: rax rcx rdx rbx rsp rbp rsi rdi r8..r15
CTX_OFF_XMM = 128          # uint64 xmm[12]: xmm0..xmm5, two u64 each
CTX_OFF_ENTRY_RIP = 224
CTX_OFF_ENTRY_RSP = 232
CTX_OFF_RUNTIME_PTR = 240
CTX_OFF_HOOK_INDEX = 248
CTX_OFF_ACTION = 252
CTX_OFF_RET_VALUE = 256
CTX_OFF_VM = 264
CTX_OFF_SCRATCH = 400
CTX_FRAME_SIZE = 4496
assert CTX_FRAME_SIZE % 16 == 0

CTX_GPR = lambda reg: CTX_OFF_GPR + 8 * reg  # noqa: E731

# --- events -----------------------------------------------------------------

EVENT_LOG = 0  # shim/system diagnostics (text)


@dataclass
class Pattern:
    """A signature variant: hex string with ``??`` wildcards."""

    signature: str

    def compile(self) -> tuple[bytes, bytes]:
        values = bytearray()
        mask = bytearray()
        tokens = self.signature.replace(",", " ").split()
        if not tokens:
            raise ValueError("empty signature")
        for token in tokens:
            if token == "??":
                values.append(0)
                mask.append(0)
                continue
            if len(token) != 2 or not all(c in "0123456789abcdefABCDEF" for c in token):
                raise ValueError(f"bad signature token {token!r}")
            values.append(int(token, 16))
            mask.append(0xFF)
        if len(values) > PATTERN_BYTES:
            raise ValueError(f"signature longer than {PATTERN_BYTES} bytes")
        return bytes(values), bytes(mask)

    def pack(self) -> bytes:
        values, mask = self.compile()
        return PATTERN.pack(len(values), values.ljust(PATTERN_BYTES, b"\0"), mask.ljust(PATTERN_BYTES, b"\0"))


@dataclass
class Descriptor:
    key: str
    kind: int = KIND_ISA
    source: int = SRC_PATTERN
    stolen_bytes: int = ENTRY_PATCH_BYTES
    fast_op: int = FAST_NONE
    fast_slot: int = 0
    varargs_variant: int = 0
    event_kind: int = 0
    scratch_bytes: int = 0
    program: bytes = b""
    data: bytes = b""
    patterns: list[Pattern] = field(default_factory=list)
    module: str = ""
    symbol: str = ""
    rva: int = 0
    target_hint: int = 0
    flags: int = 0

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.key or len(self.key.encode()) >= KEY_MAX:
            errors.append(f"key {self.key!r} must be 1..{KEY_MAX - 1} bytes")
        if self.stolen_bytes < ENTRY_PATCH_BYTES:
            errors.append(f"{self.key}: stolen bytes must be >= {ENTRY_PATCH_BYTES}")
        if len(self.program) > PROGRAM_MAX:
            errors.append(f"{self.key}: program exceeds {PROGRAM_MAX} bytes")
        if len(self.program) % 16:
            errors.append(f"{self.key}: program must be a multiple of 16 bytes")
        if len(self.data) > DATA_MAX:
            errors.append(f"{self.key}: data exceeds {DATA_MAX} bytes")
        if len(self.patterns) > PATTERN_MAX:
            errors.append(f"{self.key}: more than {PATTERN_MAX} pattern variants")
        if self.scratch_bytes > 4096:
            errors.append(f"{self.key}: scratch exceeds 4096 bytes")
        if self.kind == KIND_VARARGS and not 0 <= self.varargs_variant < VARARGS_VARIANTS:
            errors.append(f"{self.key}: varargs variant out of range")
        if self.kind == KIND_FAST and self.fast_op not in (FAST_NONE, FAST_DROP, FAST_PACE, FAST_RETURN):
            errors.append(f"{self.key}: unknown fast op {self.fast_op}")
        if self.source == SRC_PATTERN and not self.patterns:
            errors.append(f"{self.key}: pattern source needs at least one signature")
        if self.source == SRC_EXPORT and not (self.module and self.symbol):
            errors.append(f"{self.key}: export source needs module and symbol")
        if len(self.module.encode()) >= MODULE_MAX or len(self.symbol.encode()) >= SYMBOL_MAX:
            errors.append(f"{self.key}: module/symbol name too long")
        return errors

    def pack(self, blob_offset: int) -> bytes:
        head = _DESCRIPTOR_HEAD.pack(
            self.key.encode(),
            self.kind,
            self.source,
            self.stolen_bytes,
            self.fast_op,
            self.fast_slot,
            self.varargs_variant,
            self.event_kind,
            self.scratch_bytes,
            blob_offset,
            len(self.program),
            len(self.data),
            len(self.patterns),
        )
        pattern_bytes = b"".join(pattern.pack() for pattern in self.patterns)
        pattern_bytes += PATTERN.pack(0, b"\0" * PATTERN_BYTES, b"\0" * PATTERN_BYTES) * (PATTERN_MAX - len(self.patterns))
        tail = _DESCRIPTOR_TAIL.pack(
            self.module.encode(),
            self.symbol.encode(),
            self.rva,
            self.target_hint,
            self.flags,
            0,
        )
        return head + pattern_bytes + tail


@dataclass
class Payload:
    """The install payload: descriptors + program/data blobs."""

    descriptors: list[Descriptor] = field(default_factory=list)
    start_delay_ms: int = 2500
    allow_any_module: bool = False
    target_process: str = "Growtopia.exe"

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.descriptors:
            errors.append("payload has no hooks")
        if len(self.descriptors) > HOOK_MAX:
            errors.append(f"payload has more than {HOOK_MAX} hooks")
        keys = [d.key for d in self.descriptors]
        if len(set(keys)) != len(keys):
            errors.append("duplicate hook keys")
        for descriptor in self.descriptors:
            errors.extend(descriptor.validate())
        if len(self.target_process.encode()) >= KEY_MAX:
            errors.append("target process name too long")
        return errors

    def pack(self) -> bytes:
        errors = self.validate()
        if errors:
            raise ValueError("invalid payload: " + "; ".join(errors))

        blobs = bytearray()
        descriptors = bytearray()
        for descriptor in self.descriptors:
            # each hook owns one fixed-size blob slot; the program starts at 0
            blobs += descriptor.program.ljust(PROGRAM_MAX, b"\0")
            blobs += descriptor.data.ljust(DATA_MAX, b"\0")
            descriptors += descriptor.pack(0)
        descriptors += bytes(DESCRIPTOR_SIZE * (HOOK_MAX - len(self.descriptors)))
        blobs += bytes(BLOB_SIZE * (HOOK_MAX - len(self.descriptors)))

        head = PAYLOAD_HEAD.pack(
            PAYLOAD_MAGIC,
            PROTOCOL_VERSION,
            len(self.descriptors),
            self.start_delay_ms,
            1 if self.allow_any_module else 0,
            0,
            PAYLOAD_SIZE,
            0,
            self.target_process.encode(),
        )
        blob_bytes = bytes(blobs)
        assert len(descriptors) + len(blob_bytes) + PAYLOAD_HEAD.size == PAYLOAD_SIZE
        return head + bytes(descriptors) + blob_bytes

    @staticmethod
    def crc(data: bytes) -> int:
        return zlib.crc32(data) & 0xFFFFFFFF


def unpack_payload(data: bytes) -> Payload:
    """Parse a payload back into a Payload (tests and diagnostics)."""
    if len(data) != PAYLOAD_SIZE:
        raise ValueError(f"payload size {len(data)} != {PAYLOAD_SIZE}")
    magic, version, count, start_delay, allow_any, _r0, payload_bytes, _r1, target = PAYLOAD_HEAD.unpack_from(data, 0)
    if magic != PAYLOAD_MAGIC:
        raise ValueError("bad payload magic")
    if version != PROTOCOL_VERSION:
        raise ValueError(f"payload version {version} != {PROTOCOL_VERSION}")
    if payload_bytes != PAYLOAD_SIZE:
        raise ValueError("payload size field mismatch")
    if count > HOOK_MAX:
        raise ValueError(f"descriptor count {count} > {HOOK_MAX}")

    payload = Payload(start_delay_ms=start_delay, allow_any_module=bool(allow_any),
                      target_process=target.rstrip(b"\0").decode())
    for index in range(count):
        base = PAYLOAD_HEAD.size + index * DESCRIPTOR_SIZE
        raw = data[base:base + DESCRIPTOR_SIZE]
        (key, kind, source, stolen, fast_op, fast_slot, variant, event_kind, scratch,
         program_offset, program_length, data_length, pattern_count) = _DESCRIPTOR_HEAD.unpack_from(raw, 0)
        module, symbol, rva, target_hint, flags, _reserved = _DESCRIPTOR_TAIL.unpack_from(
            raw, _DESCRIPTOR_HEAD.size + PATTERN_MAX * PATTERN.size)
        patterns = []
        for p in range(min(pattern_count, PATTERN_MAX)):
            length, values, mask = PATTERN.unpack_from(raw, _DESCRIPTOR_HEAD.size + p * PATTERN.size)
            signature = " ".join(
                "??" if not mask[i] else f"{values[i]:02X}" for i in range(length)
            )
            patterns.append(Pattern(signature))
        blob_base = SHIM_OFF_PAYLOAD * 0 + PAYLOAD_HEAD.size + HOOK_MAX * DESCRIPTOR_SIZE + index * BLOB_SIZE
        program = data[blob_base + program_offset:blob_base + program_offset + program_length]
        blob_data = data[blob_base + PROGRAM_MAX:blob_base + PROGRAM_MAX + data_length]
        payload.descriptors.append(Descriptor(
            key=key.rstrip(b"\0").decode(),
            kind=kind,
            source=source,
            stolen_bytes=stolen,
            fast_op=fast_op,
            fast_slot=fast_slot,
            varargs_variant=variant,
            event_kind=event_kind,
            scratch_bytes=scratch,
            program=program,
            data=blob_data,
            patterns=patterns,
            module=module.rstrip(b"\0").decode(),
            symbol=symbol.rstrip(b"\0").decode(),
            rva=rva,
            target_hint=target_hint,
            flags=flags,
        ))
    return payload
