"""The built-in hook programs, executed against the fake ISA host.

This validates the net/response rewrite and the net/post capture end to end:
fake client structures are written into the host's flat memory, the assembled
ISA program runs against them, and the rewritten body + emitted events are
asserted.
"""

import ctypes
import struct
import subprocess
import shutil
import sys
from pathlib import Path

import pytest

from gtools.hooks import isa, payload, programs, registry
from gtools.hooks.isa import Program

REPO = Path(__file__).resolve().parent.parent
HOST_SRC = REPO / "tests" / "hook_isa_host.c"
GCC = shutil.which("gcc") or shutil.which("clang")

pytestmark = pytest.mark.skipif(GCC is None, reason="no C compiler for the ISA host")

MEM_BASE = 0x100000
CTX = MEM_BASE + 0x3000
RT = MEM_BASE + 0x2000
SCRATCH = CTX + payload.CTX_OFF_SCRATCH
RESPONSE = MEM_BASE + 0x4000
BODY = MEM_BASE + 0x5000
DICT = MEM_BASE + 0x6000
SENTINEL = MEM_BASE + 0x6080
NODE1 = MEM_BASE + 0x6100
NODE2 = MEM_BASE + 0x6180

PASS, SKIP = 0, 1


class Host:
    """Same loader as test_hook_isa.py, kept independent on purpose."""

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

    def run(self, program: Program):
        code = program.assemble()
        regs = [0] * isa.REGS
        regs[isa.R12] = 4096
        regs[isa.R13] = SCRATCH
        regs[isa.R14] = RT
        regs[isa.R15] = CTX
        values = (ctypes.c_uint64 * isa.REGS)(*regs)
        result = self.lib.host_run(self.handle, code, len(code), values, isa.MAX_STEPS)
        return int(result)

    def emit(self, index: int):
        kind = ctypes.c_uint32()
        buf = (ctypes.c_ubyte * 512)()
        size = self.lib.host_emit_at(self.handle, index, ctypes.byref(kind), buf, 512)
        assert size >= 0
        return kind.value, bytes(buf[:size])

    @property
    def emit_count(self) -> int:
        return int(self.lib.host_emit_count(self.handle))


_LIB_CACHE: dict[str, ctypes.CDLL] = {}


def _library() -> ctypes.CDLL:
    if "lib" in _LIB_CACHE:
        return _LIB_CACHE["lib"]
    out = REPO / ".tmp_isa_host.so"
    subprocess.run([GCC, "-O1", "-g", "-shared", "-fPIC", "-I", str(REPO / "gtools" / "hooks"),
                    "-o", str(out), str(HOST_SRC)], check=True, capture_output=True, text=True)
    lib = ctypes.CDLL(str(out))
    lib.host_create.restype = ctypes.c_void_p
    handle = ctypes.c_void_p
    ubyte_p = ctypes.POINTER(ctypes.c_ubyte)
    lib.host_destroy.argtypes = [handle]
    lib.host_poke.argtypes = [handle, ctypes.c_uint64, ubyte_p, ctypes.c_uint32]
    lib.host_peek.argtypes = [handle, ctypes.c_uint64, ubyte_p, ctypes.c_uint32]
    lib.host_run.restype = ctypes.c_int
    lib.host_run.argtypes = [handle, ctypes.c_char_p, ctypes.c_uint32,
                             ctypes.POINTER(ctypes.c_uint64), ctypes.c_uint32]
    lib.host_emit_count.argtypes = [handle]
    lib.host_emit_count.restype = ctypes.c_uint32
    lib.host_emit_at.argtypes = [handle, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ubyte_p, ctypes.c_uint32]
    _LIB_CACHE["lib"] = lib
    return lib


@pytest.fixture()
def host():
    h = Host()
    yield h
    h.close()


def write_gpr(host: Host, reg: int, value: int) -> None:
    host.poke(CTX + payload.CTX_GPR(reg), struct.pack("<Q", value))


def write_runtime_data(host: Host, blob: bytes) -> None:
    host.poke(RT + payload.RT_OFF_DATA, blob)


def build_response(host: Host, body: str, *, status: int = 200, capacity: int = 4096, response: int | None = None) -> int:
    response = response if response is not None else RESPONSE
    body_bytes = body.encode()
    host.poke(response + programs.RESPONSE_STATUS_OFFSET, struct.pack("<I", status))
    host.poke(response + programs.RESPONSE_BODY_OFFSET + programs.SSO_BUFFER_OFFSET, struct.pack("<Q", BODY))
    host.poke(response + programs.RESPONSE_BODY_OFFSET + programs.SSO_SIZE_OFFSET, struct.pack("<Q", len(body_bytes)))
    host.poke(response + programs.RESPONSE_BODY_OFFSET + programs.SSO_CAPACITY_OFFSET, struct.pack("<Q", capacity))
    host.poke(BODY, body_bytes)
    return response


def sso_inline(text: bytes, capacity: int = 0xF) -> bytes:
    block = bytearray(32)
    block[: len(text)] = text
    struct.pack_into("<Q", block, programs.SSO_SIZE_OFFSET, len(text))
    struct.pack_into("<Q", block, programs.SSO_CAPACITY_OFFSET, capacity)
    return bytes(block)


# -- net/response ----------------------------------------------------------


def test_response_rewrite_replaces_server_and_port(host):
    build_response(host, "type|1\nserver|real.example.com\nport|8281\npid|123\n")
    write_runtime_data(host, programs.response_data("127.0.0.1", 16999))
    write_gpr(host, 2, RESPONSE)

    result = host.run(programs.response_rewrite_program())
    assert result == PASS

    expected = b"type|1\nserver|127.0.0.1\nport|16999\npid|123\n"
    size = struct.unpack("<Q", host.peek(RESPONSE + programs.RESPONSE_BODY_OFFSET + programs.SSO_SIZE_OFFSET, 8))[0]
    assert size == len(expected)
    assert host.peek(BODY, size) == expected

    assert host.emit_count == 2
    kind0, text0 = host.emit(0)
    kind1, text1 = host.emit(1)
    assert (kind0, text0) == (programs.EVENT_RESPONSE_SERVER, b"server|real.example.com")
    assert (kind1, text1) == (programs.EVENT_RESPONSE_PORT, b"port|8281")


def build_inline_response(host, body: str, capacity: int) -> None:
    """An inline SSO keeps its text inside the struct at response+0x60."""
    host.poke(RESPONSE + programs.RESPONSE_STATUS_OFFSET, struct.pack("<I", 200))
    text = body.encode()
    sso = bytearray(32)
    sso[: len(text)] = text
    struct.pack_into("<Q", sso, programs.SSO_SIZE_OFFSET, len(text))
    struct.pack_into("<Q", sso, programs.SSO_CAPACITY_OFFSET, capacity)
    host.poke(RESPONSE + programs.RESPONSE_BODY_OFFSET, bytes(sso))


def test_response_rewrite_inline_sso(host):
    # rewritten "server|127.0.0.1\n" (17) + NUL does not fit 16 inline bytes: bail
    build_inline_response(host, "server|a\n", capacity=15)
    write_runtime_data(host, programs.response_data("127.0.0.1", 16999))
    write_gpr(host, 2, RESPONSE)

    result = host.run(programs.response_rewrite_program())
    assert result == PASS
    size = struct.unpack("<Q", host.peek(RESPONSE + programs.RESPONSE_BODY_OFFSET + programs.SSO_SIZE_OFFSET, 8))[0]
    assert size == 9
    assert host.peek(RESPONSE + programs.RESPONSE_BODY_OFFSET, 9) == b"server|a\n"


def test_response_rewrite_inline_sso_fits(host):
    # tiny proxy name so the rewrite fits the inline SSO
    build_inline_response(host, "server|x\n", capacity=13)
    write_runtime_data(host, programs.response_data("p", 1))
    write_gpr(host, 2, RESPONSE)

    result = host.run(programs.response_rewrite_program())
    assert result == PASS
    size = struct.unpack("<Q", host.peek(RESPONSE + programs.RESPONSE_BODY_OFFSET + programs.SSO_SIZE_OFFSET, 8))[0]
    assert size == 9
    assert host.peek(RESPONSE + programs.RESPONSE_BODY_OFFSET, 9) == b"server|p\n"


def test_response_ignores_non_200(host):
    build_response(host, "server|real\n", status=404)
    write_runtime_data(host, programs.response_data("127.0.0.1", 16999))
    write_gpr(host, 2, RESPONSE)
    assert host.run(programs.response_rewrite_program()) == PASS
    assert host.emit_count == 0
    assert host.peek(BODY, 12) == b"server|real\n"


def test_response_ignores_null_response(host):
    write_runtime_data(host, programs.response_data("127.0.0.1", 16999))
    write_gpr(host, 2, 0)
    assert host.run(programs.response_rewrite_program()) == PASS
    assert host.emit_count == 0


def test_response_ignores_huge_body(host):
    build_response(host, "x" * 4096)
    write_runtime_data(host, programs.response_data("127.0.0.1", 16999))
    write_gpr(host, 2, RESPONSE)
    assert host.run(programs.response_rewrite_program()) == PASS
    assert host.emit_count == 0


# -- net/post --------------------------------------------------------------


def test_post_capture(host):
    host.poke(DICT + programs.DICT_SENTINEL_OFFSET, struct.pack("<Q", SENTINEL))
    host.poke(SENTINEL, struct.pack("<Q", NODE1))
    host.poke(NODE1, struct.pack("<Q", NODE2))
    host.poke(NODE2, struct.pack("<Q", SENTINEL))

    node1 = bytearray(64)
    node1[programs.DICT_NODE_NEXT_OFFSET:programs.DICT_NODE_NEXT_OFFSET + 8] = struct.pack("<Q", NODE2)
    node1[programs.DICT_NODE_KEY_OFFSET:programs.DICT_NODE_KEY_OFFSET + 32] = sso_inline(b"version")
    node1[programs.DICT_NODE_VALUE_OFFSET:programs.DICT_NODE_VALUE_OFFSET + 32] = sso_inline(b"3.21.11")
    host.poke(NODE1, bytes(node1))

    node2 = bytearray(64)
    node2[programs.DICT_NODE_NEXT_OFFSET:programs.DICT_NODE_NEXT_OFFSET + 8] = struct.pack("<Q", SENTINEL)
    node2[programs.DICT_NODE_KEY_OFFSET:programs.DICT_NODE_KEY_OFFSET + 32] = sso_inline(b"protocol")
    node2[programs.DICT_NODE_VALUE_OFFSET:programs.DICT_NODE_VALUE_OFFSET + 32] = sso_inline(b"328")
    host.poke(NODE2, bytes(node2))

    write_runtime_data(host, programs.post_data())
    write_gpr(host, 9, DICT)

    result = host.run(programs.post_capture_program())
    assert result == PASS
    assert host.emit_count == 1
    kind, text = host.emit(0)
    assert kind == programs.EVENT_POST_CAPTURE
    assert text == b"version=3.21.11\nprotocol=328\n"


def test_post_skips_unlisted_keys(host):
    host.poke(DICT + programs.DICT_SENTINEL_OFFSET, struct.pack("<Q", SENTINEL))
    host.poke(SENTINEL, struct.pack("<Q", NODE1))
    node = bytearray(64)
    node[programs.DICT_NODE_NEXT_OFFSET:programs.DICT_NODE_NEXT_OFFSET + 8] = struct.pack("<Q", SENTINEL)
    node[programs.DICT_NODE_KEY_OFFSET:programs.DICT_NODE_KEY_OFFSET + 32] = sso_inline(b"auth")
    node[programs.DICT_NODE_VALUE_OFFSET:programs.DICT_NODE_VALUE_OFFSET + 32] = sso_inline(b"secret")
    host.poke(NODE1, bytes(node))
    write_runtime_data(host, programs.post_data())
    write_gpr(host, 9, DICT)

    assert host.run(programs.post_capture_program()) == PASS
    assert host.emit_count == 0


def test_post_handles_null_dict(host):
    write_runtime_data(host, programs.post_data())
    write_gpr(host, 9, 0)
    assert host.run(programs.post_capture_program()) == PASS
    assert host.emit_count == 0


def test_post_handles_heap_values(host):
    value = MEM_BASE + 0x7000
    host.poke(DICT + programs.DICT_SENTINEL_OFFSET, struct.pack("<Q", SENTINEL))
    host.poke(SENTINEL, struct.pack("<Q", NODE1))
    node = bytearray(64)
    node[programs.DICT_NODE_NEXT_OFFSET:programs.DICT_NODE_NEXT_OFFSET + 8] = struct.pack("<Q", SENTINEL)
    node[programs.DICT_NODE_KEY_OFFSET:programs.DICT_NODE_KEY_OFFSET + 32] = sso_inline(b"platform")
    node[programs.DICT_NODE_VALUE_OFFSET:programs.DICT_NODE_VALUE_OFFSET + 32] = sso_inline(b"")  # placeholder
    host.poke(NODE1, bytes(node))
    # heap SSO: buffer ptr, size, capacity > 15
    host.poke(NODE1 + programs.DICT_NODE_VALUE_OFFSET + programs.SSO_BUFFER_OFFSET, struct.pack("<Q", value))
    host.poke(NODE1 + programs.DICT_NODE_VALUE_OFFSET + programs.SSO_SIZE_OFFSET, struct.pack("<Q", 7))
    host.poke(NODE1 + programs.DICT_NODE_VALUE_OFFSET + programs.SSO_CAPACITY_OFFSET, struct.pack("<Q", 64))
    host.poke(value, b"windows")

    write_runtime_data(host, programs.post_data())
    write_gpr(host, 9, DICT)

    assert host.run(programs.post_capture_program()) == PASS
    kind, text = host.emit(0)
    assert (kind, text) == (programs.EVENT_POST_CAPTURE, b"platform=windows\n")


# -- payload integration ---------------------------------------------------


def test_registry_payload_contains_builtins():
    blob = registry.build_payload().pack()
    parsed = payload.unpack_payload(blob)
    keys = [d.key for d in parsed.descriptors]
    assert {"log/printf", "log/raw", "net/response", "net/post", "render/frame", "render/submit"} <= set(keys)
    response = next(d for d in parsed.descriptors if d.key == "net/response")
    assert response.program == programs.response_rewrite_program().assemble()
    assert response.data == programs.response_data()


def test_runtime_data_update_matches_blob(host):
    """The settings rewrite path pokes exactly the bytes the program reads."""
    blob = programs.response_data("proxy.local", 17000)
    write_runtime_data(host, blob)
    build_response(host, "server|real\nport|1\n")
    write_gpr(host, 2, RESPONSE)
    assert host.run(programs.response_rewrite_program()) == PASS
    size = struct.unpack("<Q", host.peek(RESPONSE + programs.RESPONSE_BODY_OFFSET + programs.SSO_SIZE_OFFSET, 8))[0]
    assert host.peek(BODY, size) == b"server|proxy.local\nport|17000\n"
    kind, text = host.emit(0)
    assert (kind, text) == (programs.EVENT_RESPONSE_SERVER, b"server|real")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
