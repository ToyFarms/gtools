"""Inject the hook payload into the running game and read the shim state.

Windows, stdlib only. Unlike scripts/hook_smoke.py this does not need the
agent: it injects a specific pid (``--pid``, useful when an elevated copy of
the game is also running) and then polls the shim's exported control block
directly for resolved entries and events.

    powershell> python scripts\\hook_game_check.py --pid 1234 [--seconds 20]
"""

import argparse
import binascii
import ctypes
import os
import struct
import subprocess
import sys
import time
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DLL_DIR = REPO / "gtools" / "hooks"


def _stub_import() -> None:
    for name, path in (
        ("gtools", REPO / "gtools"),
        ("gtools.core", REPO / "gtools" / "core"),
        ("gtools.hooks", REPO / "gtools" / "hooks"),
    ):
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        module.__package__ = name
        sys.modules[name] = module
    import gtools.hooks.programs as programs  # noqa: F401
    import gtools.hooks.registry as registry  # noqa: F401


_stub_import()

from gtools.hooks import isa, payload, registry  # noqa: E402
from gtools.hooks.isa import Program  # noqa: E402
from gtools.hooks.payload import Descriptor, Payload, SHIM_OFF_EVENTS, SHIM_OFF_MAGIC, SHIM_OFF_PAYLOAD_REVISION, SHIM_OFF_READY, SHIM_OFF_RUNTIME  # noqa: E402

PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_QUERY_INFORMATION = 0x0400
AGENT_MUTEX = r"Global\gtools_hook_agent"


def self_rva(dll_path: Path) -> int:
    """RVA of the g_self export (parsed from the DLL on disk)."""
    import gtools.hooks.payload as _p  # noqa: F401  (keeps the stub imports hot)

    data = dll_path.read_bytes()
    e = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, e + 6)[0]
    optsz = struct.unpack_from("<H", data, e + 20)[0]
    opt = e + 24
    exp_rva, _ = struct.unpack_from("<II", data, opt + 112)
    sections = []
    for i in range(nsec):
        off = opt + optsz + i * 40
        vs, va, rs, ra = struct.unpack_from("<IIII", data, off + 8)
        sections.append((va, max(vs, rs), ra))
    end = data.index(b"\0", opt + optsz + nsec * 40)

    def rva2off(rva):
        for va, size, ra in sections:
            if va <= rva < va + size:
                return ra + (rva - va)
        return None

    eo = rva2off(exp_rva)
    nf, nn = struct.unpack_from("<II", data, eo + 20)
    af, an, ao = struct.unpack_from("<III", data, eo + 28)
    names = rva2off(an)
    funcs = rva2off(af)
    ords = rva2off(ao)
    for i in range(nn):
        no = struct.unpack_from("<I", data, names + i * 4)[0]
        name = data[rva2off(no):data.index(b"\0", rva2off(no))]
        if name == b"g_self":
            ordinal = struct.unpack_from("<H", data, ords + i * 2)[0]
            return struct.unpack_from("<I", data, funcs + ordinal * 4)[0]
    raise RuntimeError("hook.dll has no g_self export")


class Game:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k = self.kernel32
        k.OpenProcess.restype = ctypes.c_void_p
        k.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        k.ReadProcessMemory.argtypes = [
            ctypes.c_void_p, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
        ]
        self.handle = k.OpenProcess(PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_QUERY_INFORMATION, False, pid)
        if not self.handle:
            raise RuntimeError(f"cannot open pid {pid} (err={ctypes.get_last_error()})")

    def read(self, address: int, size: int) -> bytes:
        buf = (ctypes.c_ubyte * size)()
        got = ctypes.c_size_t()
        if not self.kernel32.ReadProcessMemory(self.handle, ctypes.c_uint64(address), buf, size, ctypes.byref(got)):
            return b""
        return bytes(buf[: got.value])

    def module_base(self, name: str) -> int:
        class MODULEENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.c_uint32), ("th32ModuleID", ctypes.c_uint32),
                ("th32ProcessID", ctypes.c_uint32), ("GlblcntUsage", ctypes.c_uint32),
                ("ProccntUsage", ctypes.c_uint32), ("modBaseAddr", ctypes.POINTER(ctypes.c_ubyte)),
                ("modBaseSize", ctypes.c_uint32), ("hModule", ctypes.c_void_p),
                ("szModule", ctypes.c_wchar * 256), ("szExePath", ctypes.c_wchar * 260),
            ]

        k = self.kernel32
        k.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
        k.Module32FirstW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        k.Module32NextW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        snapshot = k.CreateToolhelp32Snapshot(0x8 | 0x10, self.pid)
        base = 0
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        if k.Module32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                if entry.szModule.lower() == name.lower():
                    base = ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value or 0
                    break
                if not k.Module32NextW(snapshot, ctypes.byref(entry)):
                    break
        k.CloseHandle(snapshot)
        return base


def status_text(status: int) -> str:
    return {payload.STATUS_MISSING: "missing", payload.STATUS_READY: "ready", payload.STATUS_PATCHED: "patched"}.get(
        status, f"?{status}"
    )


def dump_runtime(game: Game, self_address: int) -> dict:
    head = game.read(self_address, 64)
    if len(head) < 64 or struct.unpack_from("<i", head, 0)[0] != payload.PROTOCOL_MAGIC:
        return {}
    magic, version, ready, revision = struct.unpack_from("<iiii", head, 0)
    result = {"ready": ready, "payload_revision": revision}
    for index in range(payload.HOOK_MAX):
        block = game.read(self_address + SHIM_OFF_RUNTIME + index * payload.RT_STRIDE, payload.RT_STRIDE)
        if len(block) < payload.RT_STRIDE:
            break
        key = block[: payload.KEY_MAX].split(b"\0")[0].decode(errors="replace")
        if not key:
            break
        enabled, status = struct.unpack_from("<ii", block, payload.RT_OFF_ENABLED)
        hits, faults = struct.unpack_from("<QQ", block, payload.RT_OFF_HITS)
        state0 = struct.unpack_from("<Q", block, payload.RT_OFF_STATE)[0]
        result[key] = {"status": status_text(status), "enabled": enabled, "hits": hits, "faults": faults,
                       "state0": state0}
    return result


def drain_events(game: Game, self_address: int, consumed: int) -> tuple[int, list[tuple[str, int, bytes]]]:
    ticket = struct.unpack("<Q", game.read(self_address + 64, 8))[0]
    events = []
    ring = game.read(self_address + SHIM_OFF_EVENTS, payload.EVENT_SLOTS * payload.EVENT_SLOT.size)
    if len(ring) < payload.EVENT_SLOTS * payload.EVENT_SLOT.size:
        return consumed, events
    while consumed < ticket:
        index = consumed % payload.EVENT_SLOTS
        slot = ring[index * payload.EVENT_SLOT.size:(index + 1) * payload.EVENT_SLOT.size]
        state, sequence, _thread, hook_index, kind, size = struct.unpack_from("<iiIIII", slot, 0)
        if sequence == consumed and state == payload.SLOT_READY:
            data = slot[24:24 + min(size, payload.EVENT_MAX)]
            key = f"hook{hook_index}" if hook_index != payload.HOOK_INDEX_SYSTEM else "system"
            events.append((key, kind, data))
        consumed += 1
    return consumed, events


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--dll-dir", type=Path, default=DEFAULT_DLL_DIR)
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument("--enable", default="", help="comma separated hook keys to enable")
    parser.add_argument("--state", default="", help="key=value pairs written into state slot 0")
    args = parser.parse_args()

    dll_dir = args.dll_dir.resolve()
    for name in ("hook.dll", "injector.dll", "agent.dll"):
        if not (dll_dir / name).exists():
            print(f"missing {dll_dir / name}")
            return 2

    # write the payload from the registry (same build the app uses)
    blob = registry.build_payload(target_process="Growtopia.exe").pack()
    temporary = dll_dir / "hook_payload.tmp"
    temporary.write_bytes(blob)
    os.replace(temporary, dll_dir / "hook_payload.bin")
    print(f"payload written ({len(blob)} bytes)")

    subprocess.run(["taskkill", "/F", "/IM", "rundll32.exe"], capture_output=True)

    game = Game(args.pid)
    base = game.module_base("hook.dll")
    if base:
        print("hook.dll already loaded (re-inject skipped)")
    else:
        injector = ctypes.CDLL(str(dll_dir / "injector.dll"))
        injector.inject.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        injector.inject.restype = ctypes.c_int
        injector.last_error.restype = ctypes.c_char_p
        rc = injector.inject(str(args.pid).encode(), os.fsencode(str(dll_dir / "hook.dll")))
        error = (injector.last_error() or b"?").decode(errors="replace")
        print(f"inject(pid={args.pid}) -> {rc}: {error}")
        if rc != 0:
            return 1
        base = game.module_base("hook.dll")
        if not base:
            print("hook.dll did not load")
            return 1

    self_address = base + self_rva(dll_dir / "hook.dll")
    print(f"g_self at {self_address:#x}")

    keys = [key for key in args.enable.split(",") if key]
    if keys:
        def write_enabled(key: str, on: bool) -> bool:
            for index in range(payload.HOOK_MAX):
                block = game.read(self_address + SHIM_OFF_RUNTIME + index * payload.RT_STRIDE, payload.KEY_MAX)
                name = block.split(b"\0")[0].decode(errors="replace")
                if name == key:
                    value = struct.pack("<i", 1 if on else 0)
                    address = self_address + SHIM_OFF_RUNTIME + index * payload.RT_STRIDE + payload.RT_OFF_ENABLED
                    buf = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
                    got = ctypes.c_size_t()
                    return bool(game.kernel32.WriteProcessMemory(
                        game.handle, ctypes.c_uint64(address), buf, len(value), ctypes.byref(got)))
            return False

        k32 = game.kernel32
        k32.WriteProcessMemory.argtypes = [
            ctypes.c_void_p, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
        ]
        for key in keys:
            print(f"  ENABLE {key}: {write_enabled(key, True)}")

        def write_state(key: str, slot: int, value: int) -> bool:
            for index in range(payload.HOOK_MAX):
                block = game.read(self_address + SHIM_OFF_RUNTIME + index * payload.RT_STRIDE, payload.KEY_MAX)
                name = block.split(b"\0")[0].decode(errors="replace")
                if name == key:
                    value_bytes = struct.pack("<Q", value)
                    address = self_address + SHIM_OFF_RUNTIME + index * payload.RT_STRIDE + payload.RT_OFF_STATE + slot * 8
                    buf = (ctypes.c_ubyte * len(value_bytes)).from_buffer_copy(value_bytes)
                    got = ctypes.c_size_t()
                    return bool(game.kernel32.WriteProcessMemory(
                        game.handle, ctypes.c_uint64(address), buf, len(value_bytes), ctypes.byref(got)))
            return False

        if args.state:
            for pair in args.state.split(","):
                key, _, value = pair.partition("=")
                print(f"  STATE {key}[0]={value}: {write_state(key, 0, int(value))}")

    deadline = time.monotonic() + args.seconds
    consumed = 0
    seen_logs = 0
    last = {}
    while time.monotonic() < deadline:
        last = dump_runtime(game, self_address)
        if last and any(v.get("status") == "patched" for k, v in last.items() if isinstance(v, dict)):
            consumed, events = drain_events(game, self_address, consumed)
            for key, kind, data in events:
                if key == "system":
                    continue  # shim diagnostics
                if kind == 1:  # EVENT_TEXT: game log line
                    seen_logs += 1
                    if seen_logs <= 5:
                        print(f"    [game] {data.decode('utf-8', 'replace')}")
                else:
                    print(f"    [event] {key} kind={kind} {data[:48]!r}")
        time.sleep(0.2)

    print("runtime:")
    for key, value in last.items():
        if isinstance(value, dict):
            print(f"  {key:16} {value}")
        else:
            print(f"  {key:16} {value}")
    print(f"game log events seen: {seen_logs}")
    return 0 if seen_logs > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
