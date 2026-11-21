"""The portable ISA core (gtools/hooks/isa_core.h) driven from Python.

Builds tests/hook_isa_host.c into a shared library and exercises the
interpreter through ctypes; the programs are assembled with the Python builder
(gtools/hooks/isa.py), so every test also cross-checks the Python encoding
against the C interpreter.
"""

import ctypes
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from gtools.hooks import isa
from gtools.hooks.isa import Op, Program, R0, R1, R2, R3, R4, R13, R14, R15

REPO = Path(__file__).resolve().parent.parent
HOST_SRC = REPO / "tests" / "hook_isa_host.c"
GCC = shutil.which("gcc") or shutil.which("clang")

pytestmark = pytest.mark.skipif(GCC is None, reason="no C compiler for the ISA host")

MEM_BASE = 0x100000
DATA_BASE = 0x200000

PASS, SKIP, FAULT, STEPLIMIT, BADPROGRAM = 0, 1, 2, 3, 4


class Host:
    def __init__(self) -> None:
        lib = _library()
        self.lib = lib
        self.handle = lib.host_create()

    def close(self):
        self.lib.host_destroy(self.handle)

    def poke(self, addr: int, data: bytes) -> None:
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        assert self.lib.host_poke(self.handle, addr, buf, len(data))

    def peek(self, addr: int, size: int) -> bytes:
        buf = (ctypes.c_ubyte * size)()
        assert self.lib.host_peek(self.handle, addr, buf, size)
        return bytes(buf)

    def run(self, program: Program | bytes, regs: list[int] | None = None, max_steps: int = isa.MAX_STEPS):
        code = program if isinstance(program, bytes) else program.assemble()
        values = (ctypes.c_uint64 * isa.REGS)(*([0] * isa.REGS if regs is None else regs))
        result = self.lib.host_run(self.handle, code, len(code), values, max_steps)
        return result, list(values)

    def verify(self, data: bytes):
        err = ctypes.create_string_buffer(256)
        ok = self.lib.host_verify(data, len(data), err, 256)
        return bool(ok), err.value.decode()

    def emit(self, index: int):
        kind = ctypes.c_uint32()
        buf = (ctypes.c_ubyte * 512)()
        size = self.lib.host_emit_at(self.handle, index, ctypes.byref(kind), buf, 512)
        assert size >= 0
        return kind.value, bytes(buf[:size])

    def protect(self, base: int, size: int) -> None:
        self.lib.host_protect(self.handle, base, size)


_LIB_CACHE: dict[str, ctypes.CDLL] = {}


def _library() -> ctypes.CDLL:
    if "lib" in _LIB_CACHE:
        return _LIB_CACHE["lib"]
    out = REPO / ".tmp_isa_host.so"
    cmd = [GCC, "-O1", "-g", "-shared", "-fPIC", "-I", str(REPO / "gtools" / "hooks"),
           "-o", str(out), str(HOST_SRC)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    lib = ctypes.CDLL(str(out))
    lib.host_create.restype = ctypes.c_void_p
    handle = ctypes.c_void_p
    lib.host_destroy.argtypes = [handle]
    ubyte_p = ctypes.POINTER(ctypes.c_ubyte)
    lib.host_poke.argtypes = [handle, ctypes.c_uint64, ubyte_p, ctypes.c_uint32]
    lib.host_poke.restype = ctypes.c_int
    lib.host_peek.argtypes = [handle, ctypes.c_uint64, ubyte_p, ctypes.c_uint32]
    lib.host_peek.restype = ctypes.c_int
    lib.host_protect.argtypes = [handle, ctypes.c_uint64, ctypes.c_uint64]
    lib.host_write_faults.argtypes = [handle]
    lib.host_write_faults.restype = ctypes.c_uint32
    lib.host_run.restype = ctypes.c_int
    lib.host_run.argtypes = [handle, ctypes.c_char_p, ctypes.c_uint32,
                             ctypes.POINTER(ctypes.c_uint64), ctypes.c_uint32]
    lib.host_verify.argtypes = [ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32]
    lib.host_verify.restype = ctypes.c_int
    lib.host_emit_count.argtypes = [handle]
    lib.host_emit_count.restype = ctypes.c_uint32
    lib.host_emit_at.argtypes = [handle, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                 ubyte_p, ctypes.c_uint32]
    lib.host_emit_at.restype = ctypes.c_int
    lib.host_set_call_result.argtypes = [handle, ctypes.c_uint64]
    lib.host_call_count.argtypes = [handle]
    lib.host_call_count.restype = ctypes.c_uint32
    lib.host_last_call_fn.argtypes = [handle]
    lib.host_last_call_fn.restype = ctypes.c_uint64
    lib.host_sleep_count.argtypes = [handle]
    lib.host_sleep_count.restype = ctypes.c_uint32
    _LIB_CACHE["lib"] = lib
    return lib


@pytest.fixture()
def host():
    h = Host()
    yield h
    h.close()


def preload(**overrides) -> list[int]:
    regs = [0] * isa.REGS
    regs[isa.R12] = 4096
    regs[isa.R13] = MEM_BASE + 0x1000
    regs[isa.R14] = MEM_BASE + 0x2000
    regs[isa.R15] = MEM_BASE + 0x3000
    for reg, value in overrides.items():
        regs[int(reg)] = value
    return regs


def test_encoding_matches_c_struct():
    assert isa.INSN.size == 16
    packed = isa.INSN.pack(Op.MOVI, 3, 0, 0xFFFFFFF0, 0x1234)
    assert struct.unpack_from("<H", packed, 0)[0] == Op.MOVI
    assert packed[2] == 3 and packed[3] == 0
    assert struct.unpack_from("<i", packed, 4)[0] == -16
    assert struct.unpack_from("<Q", packed, 8)[0] == 0x1234
    # the builder stores negative aux/immediates two's complement
    p = Program()
    p.ldr(R0, R1, offset=-16, width=64)
    p.movi(R2, -1)
    p.ret()
    data = p.assemble()
    assert struct.unpack_from("<i", data, 4)[0] == -16
    assert struct.unpack_from("<Q", data, 8 + 16)[0] == 0xFFFFFFFFFFFFFFFF


def test_arithmetic_and_branches(host):
    # sum 1..5 in a loop: 15
    p = Program()
    p.movi(R0, 0)
    p.movi(R1, 1)
    p.movi(R2, 5)
    p.label("loop")
    p.add(R0, R1)
    p.movi(R3, 1)
    p.add(R1, R3)
    p.cmp(R1, R2)
    p.jle("loop")
    p.ret()
    result, regs = host.run(p)
    assert result == PASS
    assert regs[R0] == 15


def test_unsigned_and_signed_branches(host):
    p = Program()
    p.movi(R1, -1)  # 0xFFFF...
    p.movi(R2, 1)
    p.cmp(R1, R2)
    p.jlt("signed")
    p.jmp("bad")
    p.label("signed")
    p.cmp(R1, R2)
    p.jltu("bad")
    p.movi(R0, 42)
    p.ret()
    p.label("bad")
    p.movi(R0, 0)
    p.ret()
    result, regs = host.run(p)
    assert result == PASS
    assert regs[R0] == 42


def test_load_widths_and_sign_extension(host):
    p = Program()
    p.mov(R1, R15)
    p.ldr(R0, R1, 0x10, width=8)
    p.ldr(R2, R1, 0x10, width=8, signed=True)
    p.ldr(R3, R1, 0x12, width=16, signed=True)
    p.ldr(R4, R1, 0x14, width=32)
    p.ret()
    host.poke(MEM_BASE + 0x3010, bytes([0xFF, 0x00, 0xFE, 0xFF, 0x78, 0x56, 0x34, 0x12]))
    result, regs = host.run(p, regs=preload())
    assert result == PASS
    assert regs[R0] == 0xFF
    assert regs[R2] == 0xFFFFFFFFFFFFFFFF  # sign-extended -1
    assert regs[R3] == 0xFFFFFFFFFFFFFFFE  # -2
    assert regs[R4] == 0x12345678


def raw(program: Program) -> bytes:
    """Assemble without the terminator check (for step-limit tests)."""
    return b"".join(isa.INSN.pack(*insn) for insn in program._resolve())


def test_store_roundtrip(host):
    p = Program()
    p.movi(R1, 0x1122334455667788)
    p.mov(R2, R13)
    p.str_(R2, 0, R1, width=64)
    p.str_(R2, 8, R1, width=32)
    p.str_(R2, 12, R1, width=16)
    p.str_(R2, 14, R1, width=8)
    p.ret()
    result, _ = host.run(p, regs=preload())
    assert result == PASS
    assert host.peek(MEM_BASE + 0x1000, 16) == bytes.fromhex("8877665544332211" + "8877665588778800")


def test_store_is_rejected_for_protected_range(host):
    p = Program()
    p.mov(R2, R15)
    p.movi(R1, 0xFF)
    p.str_(R2, 0, R1, width=8)
    p.movi(R0, 7)
    p.ret()
    ctx_base = MEM_BASE + 0x3000
    host.protect(ctx_base, 0x100)
    result, regs = host.run(p, regs=preload())
    assert result == FAULT
    assert host.lib.host_write_faults(host.handle) == 1


def test_memcmp_helper(host):
    p = Program()
    p.movi(R1, MEM_BASE)
    p.movi(R2, MEM_BASE + 0x40)
    p.movi(R3, 7)
    p.callh(isa.Helper.MEMCMP)
    p.ret()
    host.poke(MEM_BASE, b"server|")
    host.poke(MEM_BASE + 0x40, b"server|")
    result, regs = host.run(p)
    assert result == PASS and regs[R0] == 0

    host.poke(MEM_BASE + 0x40, b"serverA")
    result, regs = host.run(p)
    assert result == PASS and regs[R0] == 1  # a > b ('|' > 'A')

    host.poke(MEM_BASE, b"server0")
    result, regs = host.run(p)
    assert result == PASS and regs[R0] == 2  # a < b ('0' < 'A')


def test_memcpy_helper(host):
    p = Program()
    p.movi(R1, MEM_BASE + 0x80)
    p.movi(R2, MEM_BASE)
    p.movi(R3, 7)
    p.callh(isa.Helper.MEMCPY)
    p.ret()
    host.poke(MEM_BASE, b"server|")
    result, regs = host.run(p)
    assert result == PASS
    assert regs[R0] == 7
    assert host.peek(MEM_BASE + 0x80, 7) == b"server|"


def test_emit_helper(host):
    p = Program()
    p.movi(R1, 7)  # kind
    p.movi(R2, MEM_BASE)
    p.movi(R3, 7)
    p.callh(isa.Helper.EMIT)
    p.ret()
    host.poke(MEM_BASE, b"payload")
    result, regs = host.run(p)
    assert result == PASS and regs[R0] == 1
    kind, data = host.emit(0)
    assert kind == 7 and data == b"payload"


def test_data_ptr_and_call(host):
    p = Program()
    p.callh(isa.Helper.DATA_PTR)
    p.mov(R1, R0)
    p.movi(R2, 0xDEAD)
    p.callh(isa.Helper.CALL, a1=R1, a2=R2)
    p.ret()
    host.lib.host_set_call_result(host.handle, 0xBEEF)
    result, regs = host.run(p)
    assert result == PASS
    assert regs[R0] == 0xBEEF
    assert regs[R1] == DATA_BASE
    assert host.lib.host_call_count(host.handle) == 1
    assert host.lib.host_last_call_fn(host.handle) == DATA_BASE


def test_fault_on_bad_read(host):
    p = Program()
    p.movi(R1, 0xDEADBEEF)
    p.ldr(R0, R1, 0, width=64)
    p.movi(R0, 1)
    p.ret()
    result, _ = host.run(p)
    assert result == FAULT


def test_step_limit(host):
    p = Program()
    p.label("loop")
    p.jmp("loop")
    result, _ = host.run(raw(p), max_steps=100)
    assert result == STEPLIMIT


def test_action_skip_returns_r0(host):
    p = Program()
    p.movi(R0, 1234)
    p.action(skip=True)
    result, regs = host.run(p)
    assert result == SKIP and regs[R0] == 1234

    p2 = Program()
    p2.movi(R0, 99)
    p2.action(skip=False)
    result, _ = host.run(p2)
    assert result == PASS


def test_program_must_terminate():
    p = Program()
    p.movi(R0, 1)
    data = b"".join(isa.INSN.pack(*insn) for insn in p._resolve())
    errors = Program().validate(assembled=data)
    assert errors and "RET" in errors[0]


def test_verifier_rejects_bad_programs(host):
    def raw(*insns):
        return b"".join(isa.INSN.pack(*insn) for insn in insns)

    ret = (Op.RET, 0, 0, 0, 0)
    bad_opcode = (999, 0, 0, 0, 0)
    bad_jump = (Op.JMP, 0, 0, 0, 99)
    bad_helper = (Op.CALLH, 0, 0, 99, 0)

    ok, err = host.verify(raw(bad_opcode, ret))
    assert not ok and "opcode" in err

    ok, err = host.verify(raw(ret, bad_jump))
    assert not ok and "jump target" in err

    ok, err = host.verify(raw(bad_helper, ret))
    assert not ok and "helper" in err

    ok, err = host.verify(raw(ret))
    assert ok


def test_python_builder_rejects_bad_labels():
    p = Program()
    p.jmp("nowhere")
    p.ret()
    with pytest.raises(ValueError, match="never defined"):
        p.assemble()


def test_backward_and_forward_jumps(host):
    p = Program()
    p.jmp("forward")
    p.label("back")
    p.movi(R0, 5)
    p.ret()
    p.label("forward")
    p.jmp("back")
    result, regs = host.run(raw(p))
    assert result == PASS and regs[R0] == 5


def test_disassembly_roundtrip():
    p = Program()
    p.movi(R1, MEM_BASE)
    p.ldr(R0, R1, 4, width=32)
    p.cmp(R0, R1)
    p.jeq("done")
    p.callh(isa.Helper.EMIT)
    p.label("done")
    p.ret()
    text = p.disassemble()
    assert "MOVI" in text and "r1 = 0x100000" in text
    assert "u32: [r1+0x4]" in text
    assert "-> 5eq" in text
    assert "memcmp" not in text and "emit() -> r0" in text


def test_addi_and_movi_overflow_guard():
    p = Program()
    with pytest.raises(ValueError):
        p.movi(R0, 2**64)
    with pytest.raises(ValueError):
        p.ldr(R0, R1, offset=2**31, width=64)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
