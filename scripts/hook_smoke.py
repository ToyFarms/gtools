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
LOG_EVENT_KIND = 1


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
    p.movi(isa.R4, 1)
    p.add(isa.R0, isa.R4)  # addi uses r0 as its temp: never addi(r0)
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
            ),
            Descriptor(
                key="test/log",
                kind=payload.KIND_VARARGS,
                source=payload.SRC_EXPORT,
                module=target_name,
                symbol="SmokeLog",
                stolen_bytes=16,
                varargs_variant=0,
                event_kind=LOG_EVENT_KIND,
            ),
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
        print(f"    [debug] hooks: {ctl.hooks()}")
        backlog = []
        drain_events(ctl, backlog, 0.3)
        for name, text in backlog:
            print(f"    [agent] {text}")
        record(ctl.enable("test/log", True), "ENABLE test/log 1")

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
        ticks = [e for e in events if e[0] == "hook" and e[1].split(" ")[1:3] == ["test/export", str(TICK_EVENT_KIND)]]
        record(len(ticks) > 0, f"received {len(ticks)} tick events through the ring")

        # the varargs detour: SmokeLog fires 5 times on its own; the text must
        # arrive formatted through the compiled log detour without enabling
        def log_events() -> list:
            fresh = []
            drain_events(ctl, fresh, 0.5)
            events.extend(fresh)
            return [e for e in fresh if e[0] == "hook" and e[1].split(" ")[1:3] == ["test/log", str(LOG_EVENT_KIND)]]

        found = wait_for(lambda: log_events() or None, args.timeout, "varargs log events")
        text = bytes.fromhex(found[0][1].split(" ", 3)[3])
        record(text.startswith(b"tick "), f"varargs log text decoded: {text!r}")

        record(ctl.enable("test/export", False), "ENABLE test/export 0")
        time.sleep(0.5)  # let an in-flight hit (already past the enabled check) drain
        frozen = counter_value()
        time.sleep(1.0)
        record(counter_value() == frozen, f"counter frozen while disabled ({frozen})")

        record(ctl.enable("test/export", True), "ENABLE test/export 1 (again)")
        try:
            wait_for(lambda: counter_value() > frozen, args.timeout, "the counter to resume")
            record(True, "counter resumed after re-enable")
        except AssertionError:
            backlog = []
            drain_events(ctl, backlog, 0.5)
            for name, text in backlog:
                print(f"    [agent] {text}")
            print(f"    [debug] target exit code: {target_process.poll()!r}")
            raise

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
