"""The hook ISA: Python-side instruction builder.

Mirrors ``gtools/hooks/isa_core.h`` byte for byte (16-byte instructions,
little-endian); ``tests/test_hook_isa.py`` asserts the encoding against the C
interpreter and the assembler against the disassembler.

Register conventions (preloaded by the runtime before the program runs):

- ``R0``..``R11`` are the program's working registers (``R0`` carries helper
  results and the skip return value),
- ``R12`` = scratch size in bytes,
- ``R13`` = pointer to the hook's scratch buffer,
- ``R14`` = pointer to the hook's runtime block (``state[]`` / ``data[]``,
  writable at run time from Python),
- ``R15`` = pointer to the saved game context (registers of the hooked call).

A program must end with ``ret()`` (call the original) or ``action(skip=True)``
(return ``R0`` instead of the original).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

INSN = struct.Struct("<HBBIQ")  # op, dst, src, aux(int32 as u32), imm(u64) = 16 bytes

ISA_VERSION = 1
ISA_INSN_SIZE = INSN.size
assert ISA_INSN_SIZE == 16

MAX_INSNS = 512
MAX_STEPS = 100_000
REGS = 16
MEMCMP_MAX = 256
MEMCPY_MAX = 4096
EMIT_MAX = 4096
SLEEP_US_MAX = 100_000


class Op:
    NOP = 0
    MOVI = 1
    MOV = 2
    ADD = 3
    SUB = 4
    AND = 5
    OR = 6
    XOR = 7
    SHL = 8
    SHR = 9
    CMP = 10
    JMP = 11
    JEQ = 12
    JNE = 13
    JLT = 14
    JLE = 15
    JGT = 16
    JGE = 17
    JLTU = 18
    JGTU = 19
    LDR8 = 20
    LDR16 = 21
    LDR32 = 22
    LDR64 = 23
    LDRS8 = 24
    LDRS16 = 25
    LDRS32 = 26
    STR8 = 27
    STR16 = 28
    STR32 = 29
    STR64 = 30
    CALLH = 31
    ACTION = 32
    RET = 33
    HLT = 34


OP_NAMES = {
    value: name for name, value in vars(Op).items() if not name.startswith("_") and isinstance(value, int)
}
OP_NAMES[Op.RET] = "RET"
OP_NAMES[Op.HLT] = "HLT"


class Helper:
    MEMCMP = 0
    EMIT = 1
    NOW_MS = 2
    SLEEP_US = 3
    CALL = 4
    DATA_PTR = 5
    MEMCPY = 6


HELPER_NAMES = {
    value: name.lower() for name, value in vars(Helper).items() if not name.startswith("_") and isinstance(value, int)
}
HELPER_NAMES[Helper.MEMCMP] = "memcmp"
HELPER_NAMES[Helper.EMIT] = "emit"
HELPER_NAMES[Helper.NOW_MS] = "now_ms"
HELPER_NAMES[Helper.SLEEP_US] = "sleep_us"
HELPER_NAMES[Helper.CALL] = "call"
HELPER_NAMES[Helper.DATA_PTR] = "data_ptr"
HELPER_NAMES[Helper.MEMCPY] = "memcpy"

HELPER_COUNT = len(HELPER_NAMES)

# working registers
R0, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11 = range(12)
# preloaded registers
R12, R13, R14, R15 = 12, 13, 14, 15
SCRATCH_SIZE, SCRATCH, RUNTIME, CTX = R12, R13, R14, R15

# runtime block offsets are protocol constants; isa.py only exposes the
# convention, payload.py owns the numeric layout.

_WIDTH_OPCODE = {
    (8, False): Op.LDR8,
    (16, False): Op.LDR16,
    (32, False): Op.LDR32,
    (64, False): Op.LDR64,
    (8, True): Op.LDRS8,
    (16, True): Op.LDRS16,
    (32, True): Op.LDRS32,
}


@dataclass(frozen=True)
class Label:
    name: str


class Program:
    """Records ISA instructions; ``assemble()`` produces the wire bytes."""

    def __init__(self) -> None:
        self._insns: list[tuple] = []
        self._label_index: dict[str, int] = {}
        self._pending: list[tuple[int, str]] = []

    # -- recording ---------------------------------------------------------

    def _emit(self, op: int, dst: int = 0, src: int = 0, aux: int = 0, imm=0) -> None:
        if isinstance(imm, Label):
            self._pending.append((len(self._insns), imm.name))
            imm = 0
        if not 0 <= dst < REGS or not 0 <= src < REGS:
            raise ValueError(f"register out of range in {OP_NAMES.get(op, op)}")
        if not -2**31 <= aux < 2**31:
            raise ValueError(f"aux offset out of int32 range in {OP_NAMES.get(op, op)}")
        if not -2**63 <= imm < 2**64:
            raise ValueError(f"immediate out of range in {OP_NAMES.get(op, op)}")
        self._insns.append((op, dst, src, aux, int(imm) & 0xFFFFFFFFFFFFFFFF))

    def label(self, name: str) -> str:
        if name in self._label_index:
            raise ValueError(f"label {name!r} already defined")
        self._label_index[name] = len(self._insns)
        return name

    # -- arithmetic --------------------------------------------------------

    def nop(self) -> None:
        self._emit(Op.NOP)

    def movi(self, dst: int, imm: int) -> None:
        self._emit(Op.MOVI, dst=dst, imm=imm)

    def mov(self, dst: int, src: int) -> None:
        self._emit(Op.MOV, dst=dst, src=src)

    def add(self, dst: int, src: int) -> None:
        self._emit(Op.ADD, dst=dst, src=src)

    def sub(self, dst: int, src: int) -> None:
        self._emit(Op.SUB, dst=dst, src=src)

    def and_(self, dst: int, src: int) -> None:
        self._emit(Op.AND, dst=dst, src=src)

    def or_(self, dst: int, src: int) -> None:
        self._emit(Op.OR, dst=dst, src=src)

    def xor(self, dst: int, src: int) -> None:
        self._emit(Op.XOR, dst=dst, src=src)

    def shl(self, dst: int, src: int) -> None:
        self._emit(Op.SHL, dst=dst, src=src)

    def shr(self, dst: int, src: int) -> None:
        self._emit(Op.SHR, dst=dst, src=src)

    def cmp(self, dst: int, src: int) -> None:
        self._emit(Op.CMP, dst=dst, src=src)

    def addi(self, dst: int, imm: int) -> None:
        """dst += imm (r0 is the temp: nothing may be live in r0 across this)."""
        self._emit(Op.MOVI, dst=R0, imm=imm)
        self._emit(Op.ADD, dst=dst, src=R0)

    def cmpi(self, dst: int, imm: int) -> None:
        """compare dst with an immediate (uses r0 as the temp: never
        ``cmpi(r0, ...)``)."""
        self._emit(Op.MOVI, dst=R0, imm=imm)
        self._emit(Op.CMP, dst=dst, src=R0)

    def cmpz(self, dst: int, temp: int) -> None:
        """compare dst against zero; ``temp`` is clobbered and must differ
        from ``dst`` (never ``cmpz(r0, ...)``, r0 is the cmpi temp too)."""
        self._emit(Op.MOVI, dst=temp, imm=0)
        self._emit(Op.CMP, dst=dst, src=temp)

    def jz(self, label: str) -> None:
        self.jeq(label)

    def jnz(self, label: str) -> None:
        self.jne(label)

    # -- control flow ------------------------------------------------------

    def _jump(self, op: int, label: str) -> None:
        self._emit(op, imm=Label(label))

    def jmp(self, label: str) -> None:
        self._jump(Op.JMP, label)

    def jeq(self, label: str) -> None:
        self._jump(Op.JEQ, label)

    def jne(self, label: str) -> None:
        self._jump(Op.JNE, label)

    def jlt(self, label: str) -> None:
        self._jump(Op.JLT, label)

    def jle(self, label: str) -> None:
        self._jump(Op.JLE, label)

    def jgt(self, label: str) -> None:
        self._jump(Op.JGT, label)

    def jge(self, label: str) -> None:
        self._jump(Op.JGE, label)

    def jltu(self, label: str) -> None:
        self._jump(Op.JLTU, label)

    def jgtu(self, label: str) -> None:
        self._jump(Op.JGTU, label)

    # -- memory ------------------------------------------------------------

    def ldr(self, dst: int, base: int, offset: int = 0, width: int = 64, signed: bool = False) -> None:
        try:
            op = _WIDTH_OPCODE[(width, signed)]
        except KeyError:
            raise ValueError(f"unsupported load width {width} (signed={signed})") from None
        self._emit(op, dst=dst, src=base, aux=offset)

    def str_(self, base: int, offset: int, src: int, width: int = 64) -> None:
        op = {8: Op.STR8, 16: Op.STR16, 32: Op.STR32, 64: Op.STR64}[width]
        self._emit(op, dst=base, src=src, aux=offset)

    # -- helpers / actions -------------------------------------------------

    def callh(self, helper_id: int, *, a1: int | None = None, a2: int | None = None, a3: int | None = None, a4: int | None = None) -> None:
        """Call a helper. Arguments land in r1..r4; the result lands in r0.

        The argument moves are ordered (and cycled through r0 when needed) so
        that a source living in r1..r4 is read before that register is
        overwritten by another argument move.
        """
        if not 0 <= helper_id < HELPER_COUNT:
            raise ValueError(f"unknown helper id {helper_id}")
        moves = [(slot, value) for slot, value in ((1, a1), (2, a2), (3, a3), (4, a4)) if value is not None]
        pending = list(enumerate(moves))
        while pending:
            progressed = False
            for item in list(pending):
                index, (slot, src) = item
                # safe to emit when no other pending move still READS this dst
                if any(other_src == slot for other_index, (_, other_src) in pending if other_index != index):
                    continue
                self.mov(slot, src)
                pending.remove(item)
                progressed = True
                break
            if not pending:
                break
            if not progressed:
                # register cycle: break one edge through r0 (r0 is free before
                # a call -- the helper result lands there anyway)
                _, (slot, src) = pending.pop(0)
                self.mov(0, src)
                self.mov(slot, 0)
        self._emit(Op.CALLH, aux=helper_id)

    def action(self, skip: bool) -> None:
        """End the program: pass to the original, or return R0 instead."""
        self._emit(Op.ACTION, imm=1 if skip else 0)

    def ret(self) -> None:
        self._emit(Op.RET)

    # -- assembly ----------------------------------------------------------

    def __len__(self) -> int:
        return len(self._insns)

    def _resolve(self) -> list[tuple]:
        resolved = []
        fixups = dict(self._pending)
        for index, insn in enumerate(self._insns):
            op, dst, src, aux, imm = insn
            if index in fixups:
                name = fixups[index]
                if name not in self._label_index:
                    raise ValueError(f"label {name!r} is never defined")
                imm = self._label_index[name]
            resolved.append((op, dst, src, aux, imm))
        return resolved

    def assemble(self) -> bytes:
        out = bytearray()
        for op, dst, src, aux, imm in self._resolve():
            out += INSN.pack(op, dst, src, aux & 0xFFFFFFFF, imm)
        errors = self.validate(assembled=out)
        if errors:
            raise ValueError("invalid program: " + "; ".join(errors))
        return bytes(out)

    def validate(self, assembled: bytes | None = None) -> list[str]:
        errors: list[str] = []
        data = assembled if assembled is not None else b"".join(INSN.pack(*insn) for insn in self._resolve())
        count = len(data) // ISA_INSN_SIZE
        if len(data) % ISA_INSN_SIZE:
            errors.append("program length is not a multiple of 16")
        if count == 0:
            errors.append("empty program")
        if count > MAX_INSNS:
            errors.append(f"program has {count} instructions, max is {MAX_INSNS}")
        if not errors:
            insns = [INSN.unpack_from(data, i * ISA_INSN_SIZE) for i in range(count)]
            for index, (op, dst, src, aux, imm) in enumerate(insns):
                if op not in OP_NAMES:
                    errors.append(f"insn {index}: unknown opcode {op}")
                    continue
                if dst >= REGS or src >= REGS:
                    errors.append(f"insn {index}: register out of range")
                if Op.JMP <= op <= Op.JGTU:
                    if not 0 <= imm < count:
                        errors.append(f"insn {index}: jump target {imm} out of range")
                if op == Op.CALLH and not 0 <= aux < HELPER_COUNT:
                    errors.append(f"insn {index}: unknown helper {aux}")
            last = insns[-1][0] if insns else None
            if last not in (Op.RET, Op.HLT, Op.ACTION):
                errors.append("program does not end with RET/ACTION")
        return errors

    # -- disassembly -------------------------------------------------------

    def disassemble(self, assembled: bytes | None = None) -> str:
        data = assembled if assembled is not None else self.assemble()
        lines = []
        count = len(data) // ISA_INSN_SIZE
        for index in range(count):
            op, dst, src, aux, imm = INSN.unpack_from(data, index * ISA_INSN_SIZE)
            name = OP_NAMES.get(op, f"op{op}")
            reg = lambda r: f"r{r}"  # noqa: E731
            if op == Op.MOVI:
                text = f"{reg(dst)} = {imm:#x}" if abs(imm) > 9 else f"{reg(dst)} = {imm}"
            elif op == Op.MOV:
                text = f"{reg(dst)} = {reg(src)}"
            elif Op.ADD <= op <= Op.SHR:
                sym = {Op.ADD: "+", Op.SUB: "-", Op.AND: "&", Op.OR: "|", Op.XOR: "^", Op.SHL: "<<", Op.SHR: ">>"}[op]
                text = f"{reg(dst)} {sym}= {reg(src)}"
            elif op == Op.CMP:
                text = f"flags({reg(dst)} - {reg(src)})"
            elif Op.JMP <= op <= Op.JGTU:
                cond = {Op.JMP: "", Op.JEQ: "eq", Op.JNE: "!eq", Op.JLT: "lt", Op.JLE: "le", Op.JGT: "gt",
                        Op.JGE: "ge", Op.JLTU: "ltu", Op.JGTU: "gtu"}[op]
                text = f"-> {imm}{cond}"
            elif op in (Op.LDR8, Op.LDR16, Op.LDR32, Op.LDR64, Op.LDRS8, Op.LDRS16, Op.LDRS32):
                sizes = {Op.LDR8: 1, Op.LDR16: 2, Op.LDR32: 4, Op.LDR64: 8, Op.LDRS8: 1, Op.LDRS16: 2, Op.LDRS32: 4}
                sign = "s" if op >= Op.LDRS8 else "u"
                text = f"{reg(dst)} = {sign}{sizes[op]*8}: [{reg(src)}{aux:+#x}]"
            elif op in (Op.STR8, Op.STR16, Op.STR32, Op.STR64):
                sizes = {Op.STR8: 1, Op.STR16: 2, Op.STR32: 4, Op.STR64: 8}
                text = f"{sizes[op]*8}: [{reg(dst)}{aux:+#x}] = {reg(src)}"
            elif op == Op.CALLH:
                text = f"{HELPER_NAMES.get(aux, aux)}() -> r0"
            elif op == Op.ACTION:
                text = "skip -> r0" if imm else "pass"
            elif op in (Op.RET, Op.HLT):
                text = "end"
            else:
                text = "?"
            lines.append(f"{index:4d}: {name:7} {text}")
        return "\n".join(lines)


def assemble(program: Program) -> bytes:
    return program.assemble()
