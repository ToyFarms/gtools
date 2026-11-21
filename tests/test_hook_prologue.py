"""The x86-64 prologue length decoder (gtools/hooks/hook_prologue.h).

Every accepted byte sequence below is a whole-instruction prefix whose stolen
bytes can be relocated into a trampoline; every rejected one would corrupt the
game if patched over (rip-relative, relative branch, unknown encoding).
"""

import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
HOST_SRC = REPO / "tests" / "hook_prologue_host.c"
CC = shutil.which("gcc") or shutil.which("clang")

pytestmark = pytest.mark.skipif(CC is None, reason="no C compiler for the prologue host")


@pytest.fixture(scope="module")
def lib():
    out = REPO / ".tmp_prologue_host.so"
    subprocess.run([CC, "-O1", "-shared", "-fPIC", "-I", str(REPO / "gtools" / "hooks"),
                    "-o", str(out), str(HOST_SRC)], check=True, capture_output=True)
    lib = ctypes.CDLL(str(out))
    lib.host_insn_length.restype = ctypes.c_uint64
    lib.host_insn_length.argtypes = [ctypes.c_char_p, ctypes.c_uint64]
    lib.host_prologue_length.restype = ctypes.c_uint64
    lib.host_prologue_length.argtypes = [ctypes.c_char_p, ctypes.c_uint64, ctypes.c_uint64]
    return lib


import ctypes  # noqa: E402


def insn(lib, hexbytes: str) -> int:
    data = bytes.fromhex(hexbytes.replace(" ", ""))
    return int(lib.host_insn_length(data, len(data)))  # exact: truncation is detectable


def prologue(lib, hexbytes: str, min_bytes: int) -> int:
    data = bytes.fromhex(hexbytes.replace(" ", ""))
    return int(lib.host_prologue_length(data, len(data), min_bytes))


# -- accepted, with exact lengths ------------------------------------------

ACCEPT = [
    ("48 89 5C 24 08", 5),              # mov [rsp+8], rbx
    ("48 89 6C 24 18", 5),
    ("48 89 74 24 20", 5),
    ("48 8B B9 E0 03 00 00", 7),        # mov rdi, [rcx+0x3E0]
    ("57", 1),                          # push rdi
    ("41 54", 2),                       # push r12 (rex)
    ("40 53", 2),                       # push rbx (rex)
    ("48 83 EC 20", 4),                 # sub rsp, 0x20
    ("48 81 EC B8 03 00 00", 7),        # sub rsp, 0x3B8
    ("48 B8 88 77 66 55 44 33 22 11", 10),  # mov rax, imm64
    ("B8 88 10 00 00", 5),              # mov eax, imm32
    ("68 88 10 00 00", 5),              # push imm32
    ("6A 08", 2),                       # push imm8
    ("C7 44 24 08 88 10 00 00", 8),     # mov dword [rsp+8], imm32
    ("48 C7 C0 88 10 00 00", 7),        # mov rax, imm32 (sign extended)
    ("4C 8D 44 24 20", 5),              # lea r8, [rsp+0x20]
    ("4C 8B DC", 3),                    # mov r11, rsp
    ("9C", 1),                          # pushfq
    ("0F 28 44 24 20", 5),              # movaps xmm0, [rsp+0x20]
    ("66 0F 7F 44 24 20", 6),           # movdqa [rsp+0x20], xmm0
    ("F2 0F 10 44 24 20", 6),           # movsd xmm0, [rsp+0x20]
    ("48 8B 41 08", 4),                 # mov rax, [rcx+8]
    ("0F B7 D9", 3),                    # movzx edx, cx
    ("41 0F B7 D9", 4),                 # movzx edx, r9w
]


@pytest.mark.parametrize("hexbytes,expected", ACCEPT)
def test_accepts_with_length(lib, hexbytes, expected):
    assert insn(lib, hexbytes) == expected


# -- rejected ---------------------------------------------------------------

REJECT = [
    "48 8B 05 11 22 33 44",   # mov rax, [rip+0x22113311]  (rip-relative)
    "4C 8D 05 11 22 33 44",   # lea r8, [rip+...]          (rip-relative)
    "E8 11 22 33 44",         # call rel32
    "E9 11 22 33 44",         # jmp rel32
    "EB 11",                  # jmp rel8
    "74 11",                  # je rel8 -- a branch inside the stolen prefix would
    "75 1D",                  # jne rel8    jump to a wrong target from the trampoline
    "E3 11",                  # jrcxz rel8
    "0F 84 11 22 33 44",      # je rel32
    "FF 15 11 22 33 44",      # call [rip+...]
    "FF 25 11 22 33 44",      # jmp [rip+...]
    "FF D0",                  # call rax
    "FF E0",                  # jmp rax
    "0F 0B",                  # ud2
    "0F 38 30",               # three-byte opcode
    "0F 3A 0F",               # three-byte opcode
    "C4 E2 7D 18 44 24 20",   # VEX (evex prefix)
    "62 11 22 33",            # EVEX
    "81 C1 11 22 33",         # truncated imm32
    "48 89 5C",               # truncated modrm
    "D8 05 11 22 33 44",      # fadd [rip+...] (rip-relative via modrm)
]


@pytest.mark.parametrize("hexbytes", REJECT)
def test_rejects_unsafe(lib, hexbytes):
    assert insn(lib, hexbytes) == 0, hexbytes


def test_branch_inside_prologue_is_rejected(lib):
    # a branch inside the stolen prefix would jump to a wrong target once
    # relocated into the trampoline, so the walk must fail outright
    pat = "74 11 48 89 5C 24 08 48 89 6C 24 18 48 89 74 24 20 57"
    assert prologue(lib, pat, 14) == 0
    assert insn(lib, "74 11") == 0


# -- real prologues ---------------------------------------------------------

def test_render_frame_prologue_24(lib):
    pat = "48 89 5C 24 08 48 89 6C 24 18 48 89 74 24 20 57 41 54 41 55 41 56 41 57"
    # the walk stops at the first boundary >= 14: three movs (15 bytes)
    assert prologue(lib, pat, 14) == 15


def test_render_submit_prologue(lib):
    pat = "40 53 57 48 83 EC 28 80 B9 E1 01 00 00 00 41 0F B7 D9 45 8B C8"
    assert prologue(lib, pat, 14) == 14


def test_response_prologue(lib):
    pat = ("40 55 56 48 83 EC 28 81 BA 11 22 33 44 C8 00 00 00 48 8B EA 48 8B 41 08 48 8B F1 "
           "75 1D C7 80 11 22 33 44 00 00 00 00")
    assert prologue(lib, pat, 14) == 17


def test_http_post_prologue(lib):
    pat = ("40 55 53 56 57 41 54 41 55 41 56 41 57 48 8D AC 24 48 FD FF FF 48 81 EC B8 03 00 00 "
           "48 8B 05 11 22 33 44")
    # the walk stops at 21 bytes (lea) -- before the rip-relative load
    assert prologue(lib, pat, 14) == 21
    # a rip-relative load inside the first 14 bytes must reject outright
    rip_first = "48 8B 05 11 22 33 44 48 89 5C 24 08 48 89 6C 24 18 48 89 74 24 20"
    assert prologue(lib, rip_first, 14) == 0


def test_syscall_stub_prologue(lib):
    # ntdll-style stub: mov r10, rcx; mov eax, id; test [SharedUserData], 1
    assert prologue(lib, "4C 8B D1 B8 33 00 00 00 F6 04 25 08 03 FE 7F 01", 14) == 16


def test_log_printf_prologue(lib):
    pat = ("48 89 4C 24 08 48 89 54 24 10 4C 89 44 24 18 4C 89 4C 24 20 53 57 B8 88 10 00 00 "
           "E8 11 22 33 44")
    # the walk stops at 15 (three spilled movs); the call rel32 at 27 is never
    # reached, so it never lands inside the stolen bytes
    assert prologue(lib, pat, 14) == 15


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
