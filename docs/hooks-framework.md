# Hook framework (v4)

The injected hook is a **feature-blind runtime**: everything that describes a
hook — patterns, handler programs, enable flags, state, data — is authored in
Python and shipped to the shim as data. Nothing in `gtools/hooks/*.c` names a
game feature; `grep -iE "server\||port\||proxy|lowPower" gtools/hooks/*.c`
must stay empty.

```
Python (payload + pipe)                agent (rundll32, watcher)            shim (hook.dll in the game)
registry.Hook ── hook_payload.bin ──>  inject + patch + drain event ring <──> g_self control block
HookControl: ENABLE/STATE/DATA  ─────────────────────────────────────────>  runtime (enabled/state/data)
events: EVENT hook <key> <kind> <hex> <──────────────────────────────────────  event ring (shared)
```

## Ownership

| Concern | C | Python |
|---|---|---|
| injection, watchdog, lifecycle, pipe | yes | starts it |
| patterns, variants, targets (pattern / export / rva) | scans | owns |
| prologue validation, trampoline, patch | yes | — |
| handler body (ISA program or native fast op) | interprets | authors |
| enable, numeric state, per-hook data blob | stores | writes |
| log filtering, capture interpretation, proxy events | — | yes |

## Files

| File | Role |
|---|---|
| `gtools/hooks/hook_protocol.h` | ABI v4: payload, descriptors, runtime, events, HookCtx (self-contained, stdint only) |
| `gtools/hooks/hook.c` | the shim: payload load, scan(+retry), trampolines, stub, dispatch, ISA, event ring |
| `gtools/hooks/hook_stub_x64.h` | GNU-asm register-preserving stub + per-hook thunks |
| `gtools/hooks/hook_prologue.h` | x86-64 instruction-length decoder for prologue validation |
| `gtools/hooks/isa_core.h` | portable ISA interpreter + verifier (no OS includes) |
| `gtools/hooks/injector.c` | payload delivery + cross-process patching |
| `gtools/hooks/agent.c` | watchdog, pipe server, event drain (generic) |
| `gtools/hooks/isa.py` | ISA opcodes, `Program` builder, assemble/disassemble/validate |
| `gtools/hooks/payload.py` | Python mirror of the ABI + payload (de)serializer |
| `gtools/hooks/registry.py` | `Hook`, `@hook`, fast ops, payload build |
| `gtools/hooks/programs.py` | the built-in hooks (all Python: log, net/response, net/post, fast frame/submit) |
| `gtools/hooks/events.py` | event decode + capture state + proxy event bridge |
| `gtools/hooks/control.py` | pipe client (STATUS/HOOKS/HANDSHAKE/ENABLE/STATE/DATA/LOGLEVEL) |
| `gtools/hooks/hook.py` | lifecycle: payload file, elevate+inject, attach, settings mapping |

## Hook kinds

- **`HOOK_KIND_ISA`** — register-preserving stub → `HookDispatch` → the ISA
  interpreter → `ACTION` (pass / skip with r0 as the return value). Cold-path
  hooks and RE probes. Every memory access is validated (`ReadProcessMemory`
  / `WriteProcessMemory` on the current process), so a bad pointer faults the
  hook, not the game.
- **`HOOK_KIND_FAST`** — native ops executed without the interpreter:
  `DROP` (skip when `state[fastSlot] != 0`), `PACE` (frame limiter reading the
  fps from `state[fastSlot]`), `RETURN`. For hot paths (frame/submit).
- **`HOOK_KIND_VARARGS`** — compiled printf-style detours (8 variants): format
  the call's varargs, emit the text, forward `("%s", line)` to the
  trampoline. The only way to render varargs.

## ISA

16-byte instructions: `op u16, dst u8, src u8, aux i32, imm u64`. Registers
`r0..r11` are the program's; the host preloads `r12`=scratch size, `r13`=
scratch pointer, `r14`=&runtime (state/data, agent-writable), `r15`=&ctx (the
saved game registers: `ctx.gpr[i]` at `ctx+8*i`). Helpers (append-only):
`memcmp`, `emit`, `now_ms`, `sleep_us`, `call(fn,a,b,c)`, `data_ptr`,
`memcpy`. Programs end with `RET` (pass) or `ACTION skip` (return r0).

Programs are authored with `isa.Program` (labels, typed loads/stores, helper
calls); `programs.py` builds the built-ins (e.g. the `net/response` line
rewrite walks the SSO body and substitutes `server|`/`port|` from the hook's
data blob). `Program.disassemble()` dumps the disassembly for debugging.

## The game register context

`HookCtx.gpr` = entry values of `rax rcx rdx rbx rsp rbp rsi rdi r8..r15`
(`rsp` = entry rsp, so stack args are at `entryRsp+0x28...`), `xmm[12]` =
xmm0..xmm5, `entryRip` = the return address. `gpr[10]/gpr[11]` are consumed by
the stub (r11 carries the runtime pointer from the thunk) and read as 0.
ISA hooks must target fixed-arity functions; variadic ones use `KIND_VARARGS`.

## Lifecycle

1. Python builds the payload from the registry → `gtools/hooks/hook_payload.bin`
   (beside the DLLs; the agent and injector read it there).
2. `ensure_hook()` spawns the agent (rundll32). The agent injects the game
   (first *openable* instance — an elevated copy does not block), which loads
   hook.dll, waits for the payload, decodes prologues, builds trampolines and
   publishes the entries; the injector patches and marks them PATCHED.
3. Python connects to the control pipe, maps settings onto hook state/data
   (`apply_hook_settings`), and consumes events.
4. `Hook.set_enabled/set_state/set_data` are runtime-only: the detour stays
   installed and disabled hooks pay one predictable branch before jumping to
   the trampoline.

## Verification

- `tests/test_hook_isa.py` — the C interpreter driven from Python (encoding
  cross-check, helpers, faults, step limit, verifier).
- `tests/test_hook_prologue.py` — the length decoder against known encodings.
- `tests/test_hook_abi.py` — compiles `hook_protocol.h` and compares every
  offset/constant against `payload.py`.
- `tests/test_hook_programs.py` — the response rewrite + post capture run
  against a fake-memory host.
- `scripts/hook_smoke.py` — end-to-end on Windows against a tiny target exe
  (`tests/hooks_dll/smoke_target.c`): agent auto-inject, ISA counter,
  enable/disable, event ring → pipe, varargs detour, handshake.
- `scripts/pattern_probe.py` — scans the live game image for the registered
  signatures (the on-disk exe is packed; only the unpacked image proves them).
- `scripts/hook_game_check.py` — injects a given pid and reads the shim's
  runtime + event ring directly.

## Debugging

- Shim diagnostics flow through the same ring (`EVENT log ...`).
- `LOGLEVEL 0|1|2` narrows the agent-forwarded shim logs.
- A failing ISA memory access bumps the hook's `faults_` counter and emits a
  rate-limited fault event; the hook fails open (pass-through).
- `pattern_probe.py` distinguishes missing/ambiguous/unique per variant —
  after a client update, fix the signature in `programs.py`, never in C.
