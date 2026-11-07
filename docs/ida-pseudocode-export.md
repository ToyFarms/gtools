# Exporting all IDA pseudocode

Bulk export of every function's Hex-Rays pseudocode from the Growtopia IDB
through the [ida-free-mcp](https://github.com/0xshlomil/ida-free-mcp) plugin.

- Script: `scripts/export_ida_pseudocode.py`
- Output: `export/ida_pseudocode/` (git-ignored; ~22 k `.c` files + index)
- IDB: `Z:\gt\Growtopia.exe.i64\Growtopia.exe.i64`
- IDA: Free 9.2.25 (Windows), plugin `ida-pro-mcp` 1.1.3
- Functions: **22,298** (median size 140 bytes)

## TL;DR

```sh
cd /home/andra/dev/gtools

# Full export (≤16 KB functions; giants are skipped)
.venv/bin/python scripts/export_ida_pseudocode.py

# Test / resume-friendly subset
.venv/bin/python scripts/export_ida_pseudocode.py --limit 20 --out /tmp/test

# Retry only the failures from a previous run
.venv/bin/python scripts/export_ida_pseudocode.py --retry-failures
```

The exporter is resumable: a function whose `.c` file exists is skipped.
Each file is written atomically (`.tmp` + rename), so an interrupted run never
leaves a truncated function behind.

## Why the MCP route is reliable (and where it used to fail)

### 1. The ~2 s widget poll vs. the cold-start decompile

`decompile` in ida-free-mcp does the following (source:
`src/tools/decompiler.cpp`):

1. activate `IDA View-A`, `jumpto(function)`;
2. close every `Pseudocode-A … Pseudocode-Z` widget;
3. run the F5 action `hx:GenPseudo`;
4. poll for a `Pseudocode-*` widget for **40 × 50 ms ≈ 2 s**, then fail with
   `No pseudocode widget for this function after decompilation`.

IDA Free's decompiler is GUI/cloud based (`plugins/hexcx64.dll`); the first
decompile after an idle period consistently takes **≈2.3–2.7 s**. The plugin
therefore gives up just before the widget is ready, returns an error, and
leaves `IDA View-A` focused. The decompilation itself completes asynchronously
and is cached, so an immediate retry reads it in **0.03–0.1 s**.

Measured on this IDB:

| Situation | Time | Result |
|---|---|---|
| First decompile after idle | ~2.3–2.7 s | error `No pseudocode widget…` |
| Immediate retry | 0.03–0.1 s | success (cached) |
| Continuous warm loop, fresh functions | ~0.4–0.6 s | success first try |
| Larger 4–8 KB function | 0.8–4.1 s | success first try |

The exporter retries with backoff (`0.25, 0.5, 1, 2, 4, 8 s`), so the cold
start is a non-event.

### 2. Keyboard focus: `hx:GenPseudo` is context-sensitive

F5 only works when the **disassembly view has keyboard focus**. The plugin
calls `activate_widget(find_widget("IDA View-A"), true)`, but after it has
closed a pseudocode tab (or when another dock such as *Local Types*, the
*Strings* view or the CLI line edit has focus), that does not always restore
focus to the `IDAView` control. The action is then disabled and the tool
returns in 0.01 s with:

```
Decompiler action failed (hx:GenPseudo)
```

Repeated calls can leave IDA stuck in that state. The manual cure documented
in `AGENTS.md` is: click the IDA window and press **Tab**. Programmatically,
selecting the `IDA View-A` tab item through Windows UI Automation restores
keyboard focus to the `IDAView` and F5 works again (verified: 0.62 s helper,
then first-try decompiles).

`scripts/export_ida_pseudocode.py` therefore includes a UIA focus helper
(`focus_ida_view`, Windows/WSL only, via `powershell.exe`):

- run once at startup;
- proactively every 250 functions (`--focus-every`);
- immediately after `Decompiler action failed`, or on the second consecutive
  widget error.

Disable it with `--no-focus-helper` if running outside Windows/WSL.

### 3. Giant functions can freeze IDA

Decompiling `sub_1402E5B40` (**0xF9520 = 1,021,216 bytes** of code) kept IDA
unresponsive for minutes (working set 4.4 GB) and had to be killed. The size
guard skips functions above **16 KB** by default — only **15 of 22,298**
functions (0.07 %) are affected:

```
0x1401024f0 sub_1401024F0              0x992c
0x14011a070 handlePunchDisplayEffect…  0x10dbc
0x14015aaf0 initRenderObjectGeneric    0x7734
0x1402c8f00 sub_1402C8F00              0x458c
0x1402cd860 sub_1402CD860              0x107cc
0x1402de050 sub_1402DE050              0x60ee
0x1402e5b40 sub_1402E5B40              0xf9520   <-- froze IDA
0x1403df350 spawnParticleActual        0x4330
0x1403f6560 handleServerAction         0x508d
0x140469070 generalButtonCreate        0x49d0
0x14051b7f0 sub_14051B7F0              0x15e59
0x1405787d0 sub_1405787D0              0x907c
0x1405baf70 sub_1405BAF70              0x415a
0x140693a60 sub_140693A60              0x6704
0x1407b4bb0 sub_1407B4BB0              0x636c
```

They are recorded in `skipped_large.jsonl`. A later pass can attempt them one
at a time with `--max-size 0 --allow-large`, while watching IDA; the exporter
waits for IDA to become responsive again after a timeout (`--ida-recovery-wait`).

## Output layout

```
export/ida_pseudocode/
  functions/
    0x140001000_sub_140001000.c     # one file per function, verbatim pseudocode
    0x140001020_sub_140001020.c
    …
  index.jsonl                       # addr/name/size/file/lines/chars/sha256/elapsed
  failures.jsonl                    # functions that failed after all retries
  skipped_large.jsonl               # functions above --max-size
  functions.json                    # full function list read from the IDB
  manifest.json                     # run metadata and summary
```

Each `.c` file starts with a small comment header:

```c
// addr: 0x140001000
// name: sub_140001000
// size: 0x20 (32 bytes)
// lines: 5
// exported: 2026-11-07T04:31:31+00:00
// source: Growtopia.exe.i64

int sub_140001000()
{
  sub_1400D2380(&unk_140B495C0);
  return atexit(sub_140888260);
}
```

## Options

| Option | Default | Meaning |
|---|---|---|
| `--url` | `http://127.0.0.1:13337/mcp` | MCP endpoint |
| `--out` | `export/ida_pseudocode` | output directory |
| `--limit N` | 0 (all) | export at most N not-yet-done functions |
| `--max-size N` | `0x4000` | skip functions larger than N bytes (0 = no limit) |
| `--allow-large` | off | attempt functions above `--max-size` |
| `--attempts N` | 6 | decompile attempts per function |
| `--read-timeout S` | 90 | HTTP read timeout per call |
| `--ida-recovery-wait S` | 300 | how long to wait for a stuck IDA after a timeout |
| `--focus-every N` | 250 | proactive UIA refocus interval (0 = only on failures) |
| `--no-focus-helper` | off | disable the Windows UIA helper |
| `--retry-failures` | off | only retry addresses in `failures.jsonl` |
| `--progress-every N` | 25 | progress line interval |
| `--source NAME` | `Growtopia.exe.i64` | label in file headers |
| `--dry-run` | off | show planned work and exit |

## If the plugin is fixed later

The proper plugin-side fix is small and does **not** require the Hex-Rays SDK:

1. Run the F5 trigger in one `execute_on_main_thread` callback, then return to
   the HTTP worker thread.
2. Poll for the pseudocode widget with **separate** short
   `execute_on_main_thread` callbacks (e.g. every 50–100 ms, up to ~50 s),
   sleeping on the worker thread in between. This yields to IDA's event loop,
   which is required for the asynchronously generated widget to appear —
   a longer `qsleep` loop inside the single callback cannot see it.
3. Make focus robust: find the widget whose `get_widget_type()` is
   `BWN_DISASM` instead of relying on the title `IDA View-A`, and/or call the
   Tab action (`hx:TogglePseudocode`) instead of F5.

The exporter already compensates on the client side, so a plugin rebuild is
optional. Keeping the client-side retries also protects against cloud
hiccups and short network stalls.
