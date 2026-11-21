"""The built-in hooks, defined entirely in Python.

Each hook is a pattern (or export) plus either an ISA program or a native fast
op. The C side only sees opaque descriptors; the client layout constants, the
rewrite rules and the capture formats live here. Importing this module
registers the hooks; ``registry.build_payload()`` serializes them.

Program data blobs are Python-owned memory inside the hook runtime block,
rewritable at run time from the pipe (``Hook.set_data``).
"""

from __future__ import annotations

import struct

from gtools.hooks import isa, payload, registry
from gtools.hooks.isa import Program
from gtools.hooks.registry import Drop, Pace, register

# ---------------------------------------------------------------------------
# client layout (reverse engineered; Python-only knowledge)
# ---------------------------------------------------------------------------

RESPONSE_STATUS_OFFSET = 0xE0  # u32 http status in the response object
RESPONSE_BODY_OFFSET = 0x60  # SSO {char* buffer; u64 pad; u64 size; u64 capacity}
SSO_BUFFER_OFFSET = 0
SSO_SIZE_OFFSET = 16
SSO_CAPACITY_OFFSET = 24
SSO_INLINE_MAX = 0xF  # capacity > 15 -> heap buffer, else inline

DICT_SENTINEL_OFFSET = 0x08  # xhash: dict -> sentinel
DICT_NODE_NEXT_OFFSET = 0x00  # node -> next
DICT_NODE_KEY_OFFSET = 0x10  # node -> key SSO
DICT_NODE_VALUE_OFFSET = 0x30  # node -> value SSO

MAX_BODY = 4096  # bail out of rewrites larger than this

# ---------------------------------------------------------------------------
# event kinds (Python-defined; C never interprets them)
# ---------------------------------------------------------------------------

EVENT_TEXT = 1  # varargs log line
EVENT_RESPONSE_SERVER = 11  # original "server|..." line
EVENT_RESPONSE_PORT = 12  # original "port|..." line
EVENT_POST_CAPTURE = 13  # "version=..\nprotocol=..\nplatform=.."

# ---------------------------------------------------------------------------
# net/response data blob layout (rewritten at run time by apply_hook_settings)
# ---------------------------------------------------------------------------

RESP_HOST_LEN = 0x000  # u32
RESP_HOST = 0x004  # 128 bytes
RESP_PORT_LEN = 0x084  # u32
RESP_PORT = 0x088  # 12 bytes
RESP_CONST_SERVER = 0x100  # b"server|"
RESP_CONST_PORT = 0x110  # b"port|"

# ---------------------------------------------------------------------------
# net/post data blob layout
# ---------------------------------------------------------------------------

POST_PREFIX = {key: 0x100 + i * 0x10 for i, key in enumerate(("version", "protocol", "platform"))}
POST_KEY = {key: 0x140 + i * 0x10 for i, key in enumerate(("version", "protocol", "platform"))}

# ---------------------------------------------------------------------------
# program scratch layout (inside ctx.scratch, 4096 bytes)
# ---------------------------------------------------------------------------

SCRATCH_POS = 0x700
SCRATCH_LINELEN = 0x708
SCRATCH_OUT = 0x800
SCRATCH_OUT_CAP = 2048

# client signatures (5.6x+); the prologue decoder overrides the stolen length
PAT_LOG_PRINTF = (
    "48 89 4C 24 08 48 89 54 24 10 4C 89 44 24 18 4C 89 4C 24 20 53 57 B8 88 10 00 00 "
    "E8 ?? ?? ?? ?? 48 2B E0 48 8B 05 ?? ?? ?? ?? 48 33 C4 48 89 84 24 70 10 00 00 48 8B D9 33 D2 48 8D 4C 24 70 41"
)
PAT_LOG_RAW = (
    "48 89 4C 24 08 48 89 54 24 10 4C 89 44 24 18 4C 89 4C 24 20 53 57 B8 68 28 00 00 "
    "E8 ?? ?? ?? ?? 48 2B E0 48 8B 05 ?? ?? ?? ?? 48 33 C4 48 89 84 24 50 28 00 00 48 8B D9 33 D2 48 8D 4C 24 40 41"
)
PAT_RESPONSE = (
    "40 55 56 48 83 EC 28 81 BA ?? ?? ?? ?? C8 00 00 00 48 8B EA 48 8B 41 08 48 8B F1 75 1D "
    "C7 80 ?? ?? ?? ?? 00 00 00 00"
)
PAT_POST = (
    "40 55 53 56 57 41 54 41 55 41 56 41 57 48 8D AC 24 48 FD FF FF 48 81 EC B8 03 00 00 "
    "48 8B 05 ?? ?? ?? ?? 48 33 C4 48 89 85 A0 02 00 00 4C 89 4C 24 40 45 8B E0 4C 8B FA 4C 8B E9"
)
PAT_FRAME = "48 89 5C 24 08 48 89 6C 24 18 48 89 74 24 20 57 41 54 41 55 41 56 41 57 48 83 EC 20 48 8B B9 E0 03 00 00"
PAT_SUBMIT = "40 53 57 48 83 EC 28 80 B9 E1 01 00 00 00 41 0F B7 D9"

CTX = isa.R15
RT = isa.R14
SCR = isa.R13
T1, T2, T3, T4 = isa.R1, isa.R2, isa.R3, isa.R4

RT_DATA = payload.RT_OFF_DATA  # runtime data blob offset


def _addi(p: Program, dst: int, imm: int) -> None:
    p.addi(dst, imm)


def response_rewrite_program() -> Program:
    """Rewrite ``server|``/``port|`` lines of the server_data body toward the
    proxy, emitting the captured originals. Data blob: see RESP_* offsets."""
    p = Program()
    resp, body, data, size, start, out, outlen = isa.R5, isa.R6, isa.R7, isa.R8, isa.R9, isa.R10, isa.R11

    p.ldr(resp, CTX, payload.CTX_GPR(2), width=64)  # rdx = response object
    p.cmpi(resp, 0)
    p.jz("done")
    p.ldr(T1, resp, RESPONSE_STATUS_OFFSET, width=32)
    p.cmpi(T1, 200)
    p.jnz("done")

    p.mov(body, resp)
    _addi(p, body, RESPONSE_BODY_OFFSET)
    p.ldr(T1, body, SSO_CAPACITY_OFFSET, width=64)
    p.cmpi(T1, SSO_INLINE_MAX)
    p.jle("inline_data")
    p.ldr(data, body, SSO_BUFFER_OFFSET, width=64)
    p.jmp("have_data")
    p.label("inline_data")
    p.mov(data, body)
    p.label("have_data")

    p.ldr(size, body, SSO_SIZE_OFFSET, width=64)
    p.cmpi(size, 0)
    p.jz("done")
    p.cmpi(size, MAX_BODY)
    p.jgt("done")

    p.mov(out, SCR)
    _addi(p, out, SCRATCH_OUT)
    p.movi(outlen, 0)
    p.movi(start, 0)

    # -- line loop ---------------------------------------------------------
    p.label("line_loop")
    p.cmp(start, size)
    p.jge("finish")
    p.str_(SCR, SCRATCH_POS, start, width=64)  # pos = lineStart

    p.label("scan")
    p.ldr(T1, SCR, SCRATCH_POS, width=64)  # pos
    p.mov(T2, data)
    p.add(T2, T1)
    p.ldr(T4, T2, 0, width=8)  # byte (T4: T1 must keep the pos)
    p.movi(T3, 10)  # '\n'
    p.cmp(T4, T3)
    p.jz("found")
    p.addi(T1, 1)
    p.str_(SCR, SCRATCH_POS, T1, width=64)
    p.cmp(T1, size)
    p.jlt("scan")

    p.label("found")
    p.ldr(T1, SCR, SCRATCH_POS, width=64)  # pos
    p.mov(T2, T1)
    p.sub(T2, start)  # lineLen
    p.str_(SCR, SCRATCH_LINELEN, T2, width=64)

    # server| line?
    p.mov(T1, data)
    p.add(T1, start)
    p.mov(T2, RT)
    _addi(p, T2, RT_DATA + RESP_CONST_SERVER)
    p.movi(T3, 7)
    p.callh(isa.Helper.MEMCMP, a1=T1, a2=T2, a3=T3)
    p.cmpz(isa.R0, T4)
    p.jnz("try_port")
    _emit_capture(p, EVENT_RESPONSE_SERVER, start_reg=start)
    _append_replacement(p, RESP_CONST_SERVER, 7, RESP_HOST_LEN, RESP_HOST, "server")
    p.jmp("next_line")

    p.label("try_port")
    p.mov(T1, data)
    p.add(T1, start)
    p.mov(T2, RT)
    _addi(p, T2, RT_DATA + RESP_CONST_PORT)
    p.movi(T3, 5)
    p.callh(isa.Helper.MEMCMP, a1=T1, a2=T2, a3=T3)
    p.cmpz(isa.R0, T4)
    p.jnz("copy_line")
    _emit_capture(p, EVENT_RESPONSE_PORT, start_reg=start)
    _append_replacement(p, RESP_CONST_PORT, 5, RESP_PORT_LEN, RESP_PORT, "port")
    p.jmp("next_line")

    p.label("copy_line")
    _append_line(p)

    p.label("next_line")
    p.ldr(T1, SCR, SCRATCH_POS, width=64)
    p.addi(T1, 1)
    p.mov(start, T1)
    p.jmp("line_loop")

    # -- write the rewrite back into the SSO -------------------------------
    p.label("finish")
    p.ldr(T1, body, SSO_CAPACITY_OFFSET, width=64)
    p.cmpi(T1, SSO_INLINE_MAX)
    p.jgt("heap_write")
    # inline SSO: needs outLen + 1 <= 16
    p.mov(T2, outlen)
    p.addi(T2, 1)
    p.cmpi(T2, 16)
    p.jgt("done")
    p.movi(T1, 0)
    p.str_(out, 0, T1, width=8)  # NUL terminator
    p.mov(T1, body)
    p.mov(T2, SCR)
    _addi(p, T2, SCRATCH_OUT)
    p.mov(T3, outlen)
    p.addi(T3, 1)
    p.callh(isa.Helper.MEMCPY, a1=T1, a2=T2, a3=T3)
    p.cmpz(isa.R0, T4)
    p.jz("done")
    p.str_(body, SSO_SIZE_OFFSET, outlen, width=64)
    p.jmp("done")

    p.label("heap_write")
    p.mov(T2, outlen)
    p.addi(T2, 1)
    p.cmp(T2, T1)  # outLen + 1 <= capacity
    p.jgt("done")
    p.movi(T3, 0)
    p.str_(out, 0, T3, width=8)
    p.ldr(T1, body, SSO_BUFFER_OFFSET, width=64)
    p.mov(T2, SCR)
    _addi(p, T2, SCRATCH_OUT)
    p.mov(T3, outlen)
    p.addi(T3, 1)
    p.callh(isa.Helper.MEMCPY, a1=T1, a2=T2, a3=T3)
    p.cmpz(isa.R0, T4)
    p.jz("done")
    p.str_(body, SSO_SIZE_OFFSET, outlen, width=64)

    p.label("done")
    p.ret()
    return p


def _emit_capture(p: Program, kind: int, *, start_reg: int) -> None:
    """emit(kind, data+lineStart, lineLen) -- the original line, verbatim."""
    p.movi(T1, kind)
    p.mov(T2, isa.R7)  # data
    p.add(T2, start_reg)
    p.ldr(T3, SCR, SCRATCH_LINELEN, width=64)
    p.callh(isa.Helper.EMIT, a1=T1, a2=T2, a3=T3)


def _append_replacement(p: Program, const_offset: int, const_len: int, field_len_offset: int, field_offset: int,
                        tag: str) -> None:
    """append data[const] + data[field] + '\\n' into the scratch output."""
    out, outlen = isa.R10, isa.R11
    # capacity: outLen + constLen + fieldLen + 1 <= cap
    p.ldr(T1, RT, RT_DATA + field_len_offset, width=32)
    p.mov(T2, outlen)
    p.addi(T2, const_len + 1)
    p.add(T2, T1)
    p.cmpi(T2, SCRATCH_OUT_CAP)
    p.jgt("done")  # overflow: pass through unrewritten
    # copy the constant prefix ("server|" / "port|")
    p.mov(T1, RT)
    _addi(p, T1, RT_DATA + const_offset)
    p.movi(T3, const_len)
    p.callh(isa.Helper.MEMCPY, a1=out, a2=T1, a3=T3)
    p.add(out, isa.R0)
    p.add(outlen, isa.R0)
    # copy the replacement value (host / port text)
    p.ldr(T3, RT, RT_DATA + field_len_offset, width=32)
    p.mov(T1, RT)
    _addi(p, T1, RT_DATA + field_offset)
    p.callh(isa.Helper.MEMCPY, a1=out, a2=T1, a3=T3)
    p.add(out, isa.R0)
    p.add(outlen, isa.R0)
    # newline
    p.movi(T1, 10)
    p.str_(out, 0, T1, width=8)
    p.addi(out, 1)
    p.addi(outlen, 1)
    del tag


def _append_line(p: Program) -> None:
    """append data[lineStart..lineEnd) + '\\n' verbatim."""
    out, outlen = isa.R10, isa.R11
    p.ldr(T1, SCR, SCRATCH_LINELEN, width=64)
    p.mov(T2, outlen)
    p.add(T2, T1)
    p.addi(T2, 1)
    p.cmpi(T2, SCRATCH_OUT_CAP)
    p.jgt("done")
    p.mov(T1, isa.R7)  # data
    p.add(T1, isa.R9)  # + lineStart
    p.ldr(T3, SCR, SCRATCH_LINELEN, width=64)
    p.callh(isa.Helper.MEMCPY, a1=out, a2=T1, a3=T3)
    p.add(out, isa.R0)
    p.add(outlen, isa.R0)
    p.movi(T1, 10)
    p.str_(out, 0, T1, width=8)
    p.addi(out, 1)
    p.addi(outlen, 1)


def post_capture_program() -> Program:
    """Walk the http post dictionary, emit ``key=value`` lines for the keys
    listed in ``POST_KEY``. Data blob: see POST_* offsets."""
    p = Program()
    node_dict, sentinel, node, out, outlen = isa.R5, isa.R6, isa.R7, isa.R8, isa.R9

    p.ldr(node_dict, CTX, payload.CTX_GPR(9), width=64)  # r9 = dictionary
    p.cmpi(node_dict, 0)
    p.jz("done")
    p.ldr(sentinel, node_dict, DICT_SENTINEL_OFFSET, width=64)
    p.cmpi(sentinel, 0)
    p.jz("done")
    p.ldr(node, sentinel, DICT_NODE_NEXT_OFFSET, width=64)
    p.cmpi(node, 0)
    p.jz("done")

    p.mov(out, SCR)
    _addi(p, out, SCRATCH_OUT)
    p.movi(outlen, 0)

    p.label("node_loop")
    p.cmp(node, sentinel)
    p.jz("emit")
    p.cmpi(node, 0)
    p.jz("emit")

    for index, key in enumerate(("version", "protocol", "platform")):
        key_len = len(key)
        skip = f"skip_{index}"
        # key SSO at node + 0x10
        p.mov(T4, node)
        _addi(p, T4, DICT_NODE_KEY_OFFSET)
        p.ldr(T1, T4, SSO_SIZE_OFFSET, width=64)
        p.cmpi(T1, key_len)
        p.jnz(skip)
        p.ldr(T2, T4, SSO_CAPACITY_OFFSET, width=64)
        p.cmpi(T2, SSO_INLINE_MAX)
        p.jle(f"key_inline_{index}")
        p.ldr(T2, T4, SSO_BUFFER_OFFSET, width=64)
        p.jmp(f"key_have_{index}")
        p.label(f"key_inline_{index}")
        p.mov(T2, T4)
        p.label(f"key_have_{index}")
        p.mov(T1, T2)  # keyData
        p.mov(T3, RT)
        _addi(p, T3, RT_DATA + POST_KEY[key])
        p.movi(T4, key_len)
        p.callh(isa.Helper.MEMCMP, a1=T1, a2=T3, a3=T4)
        p.cmpz(isa.R0, T2)
        p.jnz(skip)
        _append_pair(p, POST_PREFIX[key], len(key) + 1, DICT_NODE_VALUE_OFFSET, skip)
        p.label(skip)

    p.ldr(node, node, DICT_NODE_NEXT_OFFSET, width=64)
    p.jmp("node_loop")

    p.label("emit")
    p.cmpi(outlen, 0)
    p.jz("done")
    p.movi(T1, EVENT_POST_CAPTURE)
    p.mov(T2, SCR)
    _addi(p, T2, SCRATCH_OUT)
    p.mov(T3, outlen)
    p.callh(isa.Helper.EMIT, a1=T1, a2=T2, a3=T3)

    p.label("done")
    p.ret()
    return p


_PAIR_COUNTER = 0


def _append_pair(p: Program, prefix_offset: int, prefix_len: int, value_sso_offset: int, skip_label: str) -> None:
    """append data[prefix] + value-text + '\\n' for the current dict node."""
    out, outlen = isa.R8, isa.R9
    value_sso = T4
    p.mov(value_sso, isa.R7)  # node
    _addi(p, value_sso, value_sso_offset)
    p.ldr(T1, value_sso, SSO_SIZE_OFFSET, width=64)  # value size
    p.mov(T2, outlen)
    p.addi(T2, prefix_len + 1)
    p.add(T2, T1)
    p.cmpi(T2, SCRATCH_OUT_CAP)
    p.jgt(skip_label)  # would overflow: skip this key
    # prefix
    p.mov(T1, RT)
    _addi(p, T1, RT_DATA + prefix_offset)
    p.movi(T3, prefix_len)
    p.callh(isa.Helper.MEMCPY, a1=out, a2=T1, a3=T3)
    p.add(out, isa.R0)
    p.add(outlen, isa.R0)
    # value text
    p.ldr(T2, value_sso, SSO_CAPACITY_OFFSET, width=64)
    global _PAIR_COUNTER
    _PAIR_COUNTER += 1
    tag = _PAIR_COUNTER
    p.cmpi(T2, SSO_INLINE_MAX)
    p.jle(f"value_inline_{tag}")
    p.ldr(T2, value_sso, SSO_BUFFER_OFFSET, width=64)
    p.jmp(f"value_have_{tag}")
    p.label(f"value_inline_{tag}")
    p.mov(T2, value_sso)
    p.label(f"value_have_{tag}")
    p.mov(T1, out)
    p.ldr(T3, value_sso, SSO_SIZE_OFFSET, width=64)
    p.callh(isa.Helper.MEMCPY, a1=T1, a2=T2, a3=T3)
    p.add(out, isa.R0)
    p.add(outlen, isa.R0)
    # newline
    p.movi(T1, 10)
    p.str_(out, 0, T1, width=8)
    p.addi(out, 1)
    p.addi(outlen, 1)


# ---------------------------------------------------------------------------
# data blob builders
# ---------------------------------------------------------------------------


def response_data(host: str = "127.0.0.1", port: int = 16999) -> bytes:
    blob = bytearray(payload.DATA_MAX)
    host_bytes = host.encode()[:128]
    port_bytes = str(int(port)).encode()[:12]
    struct.pack_into("<I", blob, RESP_HOST_LEN, len(host_bytes))
    blob[RESP_HOST:RESP_HOST + len(host_bytes)] = host_bytes
    struct.pack_into("<I", blob, RESP_PORT_LEN, len(port_bytes))
    blob[RESP_PORT:RESP_PORT + len(port_bytes)] = port_bytes
    blob[RESP_CONST_SERVER:RESP_CONST_SERVER + 7] = b"server|"
    blob[RESP_CONST_PORT:RESP_CONST_PORT + 5] = b"port|"
    return bytes(blob)


def post_data() -> bytes:
    blob = bytearray(payload.DATA_MAX)
    for key in ("version", "protocol", "platform"):
        prefix = f"{key}=".encode()
        blob[POST_PREFIX[key]:POST_PREFIX[key] + len(prefix)] = prefix
        blob[POST_KEY[key]:POST_KEY[key] + len(key)] = key.encode()
    return bytes(blob)


# ---------------------------------------------------------------------------
# registrations
# ---------------------------------------------------------------------------


def register_builtin_hooks() -> None:
    """Idempotent registration of every built-in hook."""
    if "log/printf" in registry.REGISTRY:
        return

    register(
        "log/printf",
        patterns=[PAT_LOG_PRINTF],
        stolen=27,
        varargs_variant=0,
        event_kind=EVENT_TEXT,
        note="GameLog_Printf",
    )
    register(
        "log/raw",
        patterns=[PAT_LOG_RAW],
        stolen=27,
        varargs_variant=1,
        event_kind=EVENT_TEXT,
        note="GameLog_Raw",
    )
    register(
        "net/response",
        patterns=[PAT_RESPONSE],
        stolen=17,
        program=response_rewrite_program(),
        data=response_data(),
        initial_enabled=True,  # the login POST fires before Python can toggle
        note="OnServerDataResponse rewrite",
    )
    register(
        "net/post",
        patterns=[PAT_POST],
        stolen=21,
        program=post_capture_program(),
        data=post_data(),
        initial_enabled=True,
        note="HttpClient_Post capture",
    )
    register(
        "render/frame",
        patterns=[PAT_FRAME],
        stolen=24,
        fast=Pace(slot=0),
        note="bgfx::frame pacing",
    )
    register(
        "render/submit",
        patterns=[PAT_SUBMIT],
        stolen=14,
        fast=Drop(slot=0),
        note="Encoder::submit skip",
    )


register_builtin_hooks()


# smoke-test hook: no game dependency, used by scripts/hook_smoke.py
def register_export_test_hook(symbol: str = "Sleep", module: str = "kernel32") -> registry.Hook:
    """A counter hook on an exported API: state[0] counts hits while enabled."""
    p = Program()
    p.ldr(isa.R0, RT, payload.RT_OFF_STATE, width=64)
    p.addi(isa.R0, 1)
    p.str_(RT, payload.RT_OFF_STATE, isa.R0, width=64)
    p.ret()
    return register(
        "test/export",
        export=(module, symbol),
        stolen=16,
        program=p,
        note=f"{module}!{symbol} hit counter",
    )
