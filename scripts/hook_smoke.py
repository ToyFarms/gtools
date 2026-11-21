"""End-to-end smoke test for the v4 hook runtime (Windows, stdlib only).

Builds a one-hook payload that hooks ``SmokeTick`` in the tiny smoke target,
spawns the agent, injects, then verifies the whole pipeline:

  stub -> HookDispatch -> ISA program -> runtime state -> event ring -> pipe

Usage (from Windows):
    python scripts\\hook_smoke.py [--dll-dir DIR] [--target EXE] [--timeout S]

The script never imports the heavy gtools package: the hook modules are
loaded through a stub package so only the standard library is required.
"""

import argparse
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
DEFAULT_TARGET = REPO / "tests" / "hooks_dll" / "smoke.exe"
AGENT_MUTEX = r"Global\gtools_hook_agent"

TICK_EVENT_KIND = 42


def _stub_import() -> None:
    """Import the hook modules without running gtools/__init__ (watchdog & co)."""
    for name, path in (
        ("gtools", REPO / "gtools"),
        ("gtools.core", REPO / "gtools" / "core"),
        ("gtools.hooks", REPO / "gtools" / "hooks"),
    ):
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        module.__package__ = name
        sys.modules[name] = module
    import gtools.hooks.control as control  # noqa: F401
    import gtools.hooks.isa as isa  # noqa: F401
    import gtools.hooks.payload as payload  # noqa: F401


_stub_import()

from gtools.hooks import isa, payload  # noqa: E402
from gtools.hooks.control import HookControl  # noqa: E402
from gtools.hooks.isa import Program  # noqa: E402
from gtools.hooks.payload import Descriptor, Payload  # noqa: E402


def counter_program() -> Program:
    """state[0] += 1 and emit one 8-byte event per hit."""
    p = Program()
    p.ldr(isa.R0, isa.R14, payload.RT_OFF_STATE, width=64)
    p.addi(isa.R0, 1)
    p.str_(isa.R14, payload.RT_OFF_STATE, isa.R0, width=64)
    p.str_(isa.R13, 0, isa.R0, width=64)
    p.movi(isa.R1, TICK_EVENT_KIND)
    p.mov(isa.R2, isa.R13)
    p.movi(isa.R3, 8)
    p.callh(isa.Helper.EMIT, a1=isa.R1, a2=isa.R2, a3=isa.R3)
    p.ret()
    return p


def agent_running() -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenMutexA(0x00100000, False, AGENT_MUTEX.encode())
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def spawn_agent(dll_dir: Path) -> subprocess.Popen:
    rundll32 = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "rundll32.exe"
    creation = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
    process = subprocess.Popen(
        [str(rundll32), f"{dll_dir / 'agent.dll'},AgentMain"],
        creationflags=creation,
        cwd=str(dll_dir),
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if agent_running():
            return process
        time.sleep(0.05)
    raise RuntimeError("the agent did not come up (is another agent running?)")


def build_payload(dll_dir: Path, target_name: str) -> bytes:
    payload_obj = Payload(
        descriptors=[
            Descriptor(
                key="test/export",
                source=payload.SRC_EXPORT,
                module=target_name,
                symbol="SmokeTick",
                stolen_bytes=16,
                event_kind=TICK_EVENT_KIND,
                program=counter_program().assemble(),
            )
        ],
        start_delay_ms=0,
        target_process=target_name,
    )
    blob = payload_obj.pack()
    temporary = dll_dir / "hook_payload.tmp"
    temporary.write_bytes(blob)
    os.replace(temporary, dll_dir / "hook_payload.bin")
    return blob


def wait_for(predicate, timeout: float, description: str):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(0.1)
    raise AssertionError(f"timeout waiting for {description} (last={last!r})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dll-dir", type=Path, default=DEFAULT_DLL_DIR)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--keep", action="store_true", help="leave the target and agent running")
    args = parser.parse_args()

    dll_dir = args.dll_dir.resolve()
    target_exe = args.target.resolve()
    target_name = target_exe.name

    for name in ("hook.dll", "injector.dll", "agent.dll"):
        if not (dll_dir / name).exists():
            print(f"FAIL: missing {dll_dir / name}")
            return 2
    if not target_exe.exists():
        print(f"FAIL: missing {target_exe} (build it with x86_64-w64-mingw32-gcc)")
        return 2
    if agent_running():
        print("FAIL: another hook agent is already running (stop the proxy first)")
        return 2

    blob = build_payload(dll_dir, target_name)
    print(f"payload written: {len(blob)} bytes, target {target_name}")

    # kill leftovers from previous runs: the agent injects the first match
    subprocess.run(["taskkill", "/F", "/IM", target_name], capture_output=True)
    subprocess.run(["taskkill", "/F", "/IM", "rundll32.exe"], capture_output=True)
    time.sleep(0.3)
    target_process = subprocess.Popen([str(target_exe)], cwd=str(target_exe.parent))
    print(f"target pid: {target_process.pid}")
    agent_process = None
    ctl = HookControl(timeout=2.0)
    failures = []

    def record(condition: bool, description: str) -> None:
        mark = "ok  " if condition else "FAIL"
        print(f"  [{mark}] {description}")
        if not condition:
            failures.append(description)

    try:
        agent_process = spawn_agent(dll_dir)

        # let the agent watchdog perform the injection (that is its job); the
        # manual injector path is exercised by the real app instead
        started = time.monotonic()

        attempts = {"n": 0}

        def hooks_live() -> bool:
            attempts["n"] += 1
            if not ctl.connect(0.5):
                if attempts["n"] % 20 == 1:
                    print("    [debug] pipe connect failed")
                return False
            try:
                status = ctl.status()
            except Exception as exc:
                if attempts["n"] % 20 == 1:
                    print(f"    [debug] status failed: {exc!r}")
                return False
            live = status.get("hook_test_export") in ("ready", "patched")
            if attempts["n"] % 20 == 1:
                print(f"    [debug] attempt {attempts['n']}: keys={sorted(status)[:8]}")
            if live:
                print(f"    hook live after {time.monotonic() - started:.1f}s")
            return live

        try:
            wait_for(hooks_live, max(args.timeout, 30.0), "the agent to inject and report the hook")
            record(True, "agent injected and the shim reported the hook")
        except AssertionError as exc:
            failures.append(str(exc))
            backlog = []
            drain_events(ctl, backlog, 0.5)
            for name, text in backlog:
                print(f"    [agent] {text}")
            return finish(target_process, agent_process, ctl, failures, args.keep)
        backlog = []
        drain_events(ctl, backlog, 0.5)
        for name, text in backlog:
            print(f"    [agent] {text}")
        status = ctl.status()
        if "hook_test_export" not in status or status.get("hook_test_export") != "patched":
            print(f"    [debug] status: {status}")
            try:
                print(f"    [debug] hooks: {ctl.hooks()}")
            except Exception as exc:
                print(f"    [debug] hooks failed: {exc!r}")
        record(status.get("hook_test_export") == "patched", f"hook_test_export={status.get('hook_test_export')}")
        record(int(status.get("hits_test_export", "0")) == 0, "hits stay 0 while disabled")

        events = []
        record(ctl.enable("test/export", True), "ENABLE test/export 1")

        # verify the patch + thunk bytes in the live process
        handshake = ctl.handshake()
        entry = next((e for e in handshake.entries if e.key == "test/export"), None) if handshake else None
        if entry is not None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            process = kernel32.OpenProcess(0x0010 | 0x0400, False, handshake.process_id)  # VM_READ | QUERY_INFO

            def read_remote(address, size):
                buf = (ctypes.c_ubyte * size)()
                got = ctypes.c_size_t()
                ok = kernel32.ReadProcessMemory(process, ctypes.c_void_p(address), buf, size, ctypes.byref(got))
                return bytes(buf[:got.value]) if ok else None

            patch_bytes = read_remote(entry.target, 14)
            print(f"    [debug] patch @ {entry.target:#x}: {patch_bytes.hex(' ') if patch_bytes else None}")
            if patch_bytes and patch_bytes[:2] == b"\xff\x25":
                detour = struct.unpack("<Q", patch_bytes[6:14])[0]
                thunk = read_remote(detour, 32)
                print(f"    [debug] thunk @ {detour:#x}: {thunk.hex(' ') if thunk else None}")
                if thunk and thunk[:2] == b"\x49\xbb":
                    runtime_addr = struct.unpack("<Q", thunk[2:10])[0]
                    print(f"    [debug] thunk runtime ptr: {runtime_addr:#x} (expect dllbase+72)")
                    enabled_bytes = read_remote(runtime_addr + 32, 4)
                    print(f"    [debug] runtime.enabled = {struct.unpack('<i', enabled_bytes)[0] if enabled_bytes else None}")
                    stub = read_remote(detour - 235, 240)
                    if stub:
                        marker_at = stub.find(bytes.fromhex("8877665544332211"))
                        print(f"    [debug] stub len={len(stub)} raw marker at offset {marker_at}")
                        call_site = stub.find(bytes.fromhex("ffd0"))
                        print(f"    [debug] call rax at offset {call_site}, preceding bytes: {stub[call_site-10:call_site+2].hex(' ') if call_site > 0 else None}")
                    # where is the main thread stuck?
                    class CONTEXT(ctypes.Structure):
                        _fields_ = [
                            ("P1Home", ctypes.c_uint64), ("P2Home", ctypes.c_uint64),
                            ("P3Home", ctypes.c_uint64), ("P4Home", ctypes.c_uint64),
                            ("P5Home", ctypes.c_uint64), ("P6Home", ctypes.c_uint64),
                            ("ContextFlags", ctypes.c_uint32), ("MxCsr", ctypes.c_uint32),
                            ("SegCs", ctypes.c_uint16), ("SegDs", ctypes.c_uint16),
                            ("SegEs", ctypes.c_uint16), ("SegFs", ctypes.c_uint16),
                            ("SegGs", ctypes.c_uint16), ("SegSs", ctypes.c_uint16),
                            ("EFlags", ctypes.c_uint32), ("Dr0", ctypes.c_uint64),
                            ("Dr1", ctypes.c_uint64), ("Dr2", ctypes.c_uint64),
                            ("Dr3", ctypes.c_uint64), ("Dr6", ctypes.c_uint64),
                            ("Dr7", ctypes.c_uint64), ("Rax", ctypes.c_uint64),
                            ("Rcx", ctypes.c_uint64), ("Rdx", ctypes.c_uint64),
                            ("Rbx", ctypes.c_uint64), ("Rsp", ctypes.c_uint64),
                            ("Rbp", ctypes.c_uint64), ("Rsi", ctypes.c_uint64),
                            ("Rdi", ctypes.c_uint64), ("R8", ctypes.c_uint64),
                            ("R9", ctypes.c_uint64), ("R10", ctypes.c_uint64),
                            ("R11", ctypes.c_uint64), ("R12", ctypes.c_uint64),
                            ("R13", ctypes.c_uint64), ("R14", ctypes.c_uint64),
                            ("R15", ctypes.c_uint64), ("Rip", ctypes.c_uint64),
                        ]

                    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
                    kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
                    kernel32.Thread32First.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                    kernel32.Thread32Next.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                    snapshot = kernel32.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD
                    import struct as _s

                    class THREADENTRY32(ctypes.Structure):
                        _fields_ = [
                            ("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32),
                            ("th32ThreadID", ctypes.c_uint32), ("th32OwnerProcessID", ctypes.c_uint32),
                            ("tpDeltaPri", ctypes.c_long), ("dwFlags", ctypes.c_uint32),
                        ]

                    entry32 = THREADENTRY32()
                    entry32.dwSize = ctypes.sizeof(entry32)
                    tid = None
                    print(f"    [debug] looking for threads of pid {handshake.process_id}")
                    if kernel32.Thread32First(snapshot, ctypes.byref(entry32)):
                        while True:
                            if entry32.th32OwnerProcessID == handshake.process_id:
                                tid = entry32.th32ThreadID
                                break
                            if not kernel32.Thread32Next(snapshot, ctypes.byref(entry32)):
                                break
                    if tid:
                        kernel32.OpenThread.restype = ctypes.c_void_p
                        kernel32.OpenThread.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
                        thread = kernel32.OpenThread(0x0008 | 0x0010, False, tid)  # GET_CONTEXT | QUERY_INFORMATION
                        kernel32.GetThreadContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                        context = CONTEXT()
                        context.ContextFlags = 0x00100000 | 0x2  # CONTEXT_CONTROL | CONTEXT_INTEGER
                        if kernel32.GetThreadContext(thread, ctypes.byref(context)):
                            print(f"    [debug] thread {tid} RIP={context.Rip:#x} RSP={context.Rsp:#x} RAX={context.Rax:#x}")
                            around = read_remote(context.Rip - 16, 48)
                            print(f"    [debug] code at RIP-16: {around.hex(' ') if around else None}")
                        else:
                            print(f"    [debug] GetThreadContext failed err={ctypes.get_last_error()}")
                    else:
                        print("    [debug] no thread found")
                    hits_bytes = read_remote(runtime_addr + 48, 8)
                    print(f"    [debug] runtime.hits = {struct.unpack('<Q', hits_bytes)[0] if hits_bytes else None}")
                    # the target's own tick counter: g_ticks at image_base + 0x2a030 (sec6 rva+0x30)
                    ticks_bytes = read_remote(handshake.image_base + 0x7030, 8)
                    ticks_before = struct.unpack("<Q", ticks_bytes)[0] if ticks_bytes else -1
                    time.sleep(1.0)
                    ticks_bytes = read_remote(handshake.image_base + 0x7030, 8)
                    ticks_after = struct.unpack("<Q", ticks_bytes)[0] if ticks_bytes else -1
                    print(f"    [debug] target g_ticks {ticks_before} -> {ticks_after} ({'running' if ticks_after > ticks_before else 'FROZEN'})")
                    stub = read_remote(detour - 235, 240)
                    if stub:
                        marker_at = stub.find(bytes.fromhex("8877665544332211"))
                        print(f"    [debug] stub len={len(stub)} raw marker at offset {marker_at}")
                        call_site = stub.find(bytes.fromhex("ffd0"))
                        print(f"    [debug] call rax at offset {call_site}, preceding bytes: {stub[call_site-10:call_site+2].hex(' ') if call_site > 0 else None}")
                    # where is the main thread stuck?
                    class CONTEXT(ctypes.Structure):
                        _fields_ = [
                            ("P1Home", ctypes.c_uint64), ("P2Home", ctypes.c_uint64),
                            ("P3Home", ctypes.c_uint64), ("P4Home", ctypes.c_uint64),
                            ("P5Home", ctypes.c_uint64), ("P6Home", ctypes.c_uint64),
                            ("ContextFlags", ctypes.c_uint32), ("MxCsr", ctypes.c_uint32),
                            ("SegCs", ctypes.c_uint16), ("SegDs", ctypes.c_uint16),
                            ("SegEs", ctypes.c_uint16), ("SegFs", ctypes.c_uint16),
                            ("SegGs", ctypes.c_uint16), ("SegSs", ctypes.c_uint16),
                            ("EFlags", ctypes.c_uint32), ("Dr0", ctypes.c_uint64),
                            ("Dr1", ctypes.c_uint64), ("Dr2", ctypes.c_uint64),
                            ("Dr3", ctypes.c_uint64), ("Dr6", ctypes.c_uint64),
                            ("Dr7", ctypes.c_uint64), ("Rax", ctypes.c_uint64),
                            ("Rcx", ctypes.c_uint64), ("Rdx", ctypes.c_uint64),
                            ("Rbx", ctypes.c_uint64), ("Rsp", ctypes.c_uint64),
                            ("Rbp", ctypes.c_uint64), ("Rsi", ctypes.c_uint64),
                            ("Rdi", ctypes.c_uint64), ("R8", ctypes.c_uint64),
                            ("R9", ctypes.c_uint64), ("R10", ctypes.c_uint64),
                            ("R11", ctypes.c_uint64), ("R12", ctypes.c_uint64),
                            ("R13", ctypes.c_uint64), ("R14", ctypes.c_uint64),
                            ("R15", ctypes.c_uint64), ("Rip", ctypes.c_uint64),
                        ]

                    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
                    kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
                    kernel32.Thread32First.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                    kernel32.Thread32Next.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                    snapshot = kernel32.CreateToolhelp32Snapshot(0x4, 0)  # TH32CS_SNAPTHREAD
                    import struct as _s

                    class THREADENTRY32(ctypes.Structure):
                        _fields_ = [
                            ("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32),
                            ("th32ThreadID", ctypes.c_uint32), ("th32OwnerProcessID", ctypes.c_uint32),
                            ("tpDeltaPri", ctypes.c_long), ("dwFlags", ctypes.c_uint32),
                        ]

                    entry32 = THREADENTRY32()
                    entry32.dwSize = ctypes.sizeof(entry32)
                    tid = None
                    print(f"    [debug] looking for threads of pid {handshake.process_id}")
                    if kernel32.Thread32First(snapshot, ctypes.byref(entry32)):
                        while True:
                            if entry32.th32OwnerProcessID == handshake.process_id:
                                tid = entry32.th32ThreadID
                                break
                            if not kernel32.Thread32Next(snapshot, ctypes.byref(entry32)):
                                break
                    if tid:
                        kernel32.OpenThread.restype = ctypes.c_void_p
                        kernel32.OpenThread.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
                        thread = kernel32.OpenThread(0x0008 | 0x0010, False, tid)  # GET_CONTEXT | QUERY_INFORMATION
                        kernel32.GetThreadContext.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                        context = CONTEXT()
                        context.ContextFlags = 0x00100000 | 0x2  # CONTEXT_CONTROL | CONTEXT_INTEGER
                        if kernel32.GetThreadContext(thread, ctypes.byref(context)):
                            print(f"    [debug] thread {tid} RIP={context.Rip:#x} RSP={context.Rsp:#x} RAX={context.Rax:#x}")
                            around = read_remote(context.Rip - 16, 48)
                            print(f"    [debug] code at RIP-16: {around.hex(' ') if around else None}")
                        else:
                            print(f"    [debug] GetThreadContext failed err={ctypes.get_last_error()}")
                    else:
                        print("    [debug] no thread found")

        def counter_value() -> int:
            fresh = ctl.status()
            try:
                return int(fresh.get("state_test_export_0", "0"))
            except ValueError:
                return 0

        def counter_with_diagnostics() -> int:
            fresh = ctl.status()
            hits = fresh.get("hits_test/export", fresh.get("hits_test_export", "?"))
            faults = fresh.get("faults_test/export", fresh.get("faults_test_export", "?"))
            enabled = fresh.get("enabled_test/export", fresh.get("enabled_test_export", "?"))
            print(f"    [debug] hits={hits} faults={faults} enabled={enabled} state={fresh.get('state_test_export_0')}")
            try:
                return int(fresh.get("state_test_export_0", "0"))
            except ValueError:
                return 0

        wait_for(counter_with_diagnostics, args.timeout, "the ISA counter to advance")
        record(True, "state_test_export_0 advanced while enabled")

        drain_events(ctl, events, 0.5)
        ticks = [e for e in events if e[0] == "hook" and TICK_EVENT_KIND in e[1]]
        record(len(ticks) > 0, f"received {len(ticks)} tick events through the ring")

        record(ctl.enable("test/export", False), "ENABLE test/export 0")
        frozen = counter_value()
        time.sleep(1.0)
        record(counter_value() == frozen, f"counter frozen while disabled ({frozen})")

        record(ctl.enable("test/export", True), "ENABLE test/export 1 (again)")
        wait_for(lambda: counter_value() > frozen, args.timeout, "the counter to resume")
        record(True, "counter resumed after re-enable")

        handshake = ctl.handshake()
        record(
            handshake is not None and any(e.key == "test/export" for e in handshake.entries),
            "handshake lists the hook entry",
        )
    except Exception as exc:  # noqa: BLE001
        failures.append(f"exception: {exc!r}")
    finally:
        return finish(target_process, agent_process, ctl, failures, args.keep)


def drain_events(ctl: HookControl, into: list, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            event = ctl.wait_event(timeout=0.2)
        except Exception:
            break
        if event is None:
            continue
        into.append((event.name, event.payload))


def finish(target_process, agent_process, ctl: HookControl, failures: list, keep: bool) -> int:
    try:
        if ctl.connected:
            ctl.close()
    except Exception:
        pass
    if not keep:
        if target_process is not None and target_process.poll() is None:
            target_process.kill()
        if agent_process is not None and agent_process.poll() is None:
            agent_process.kill()
    if failures:
        print(f"SMOKE FAIL: {len(failures)} failure(s)")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("SMOKE PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
