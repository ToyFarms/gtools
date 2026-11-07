#!/usr/bin/env python3
"""Export IDA Free function pseudocode to local files through the ida-free-mcp server.

The MCP ``decompile`` tool drives IDA Free's GUI decompiler (F5) and reads the
pseudocode widget.  The first decompile after an idle period can take longer
than the plugin's internal ~2 s poll window, so a call may fail with
``No pseudocode widget for this function after decompilation`` even though the
decompilation is already on its way.  A retry a moment later reads it from the
cache and succeeds.  This exporter retries every function and checkpoints its
progress, so the export can be interrupted and resumed safely.

Usage:
    .venv/bin/python scripts/export_ida_pseudocode.py
    .venv/bin/python scripts/export_ida_pseudocode.py --limit 20 --out /tmp/test
    .venv/bin/python scripts/export_ida_pseudocode.py --max-size 0 --allow-large

Output layout (``--out``, default ``export/ida_pseudocode``):
    functions/0x140001000_sub_140001000.c   one file per function
    index.jsonl                             one JSON line per exported function
    failures.jsonl                          functions that failed after retries
    skipped_large.jsonl                     functions larger than --max-size
    functions.json                          full function list read from the IDB
    manifest.json                           run metadata / summary
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

DEFAULT_URL = "http://127.0.0.1:13337/mcp"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "export" / "ida_pseudocode"
POWERSHELL_EXE = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"

# Retry schedule for transient decompile errors (cold start, tiny races).
RETRY_DELAYS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0)

# Tool-level timeout on the plugin side for decompile is 60 s.  Use a little
# more on the HTTP side so the server's own error is delivered to us.
DEFAULT_READ_TIMEOUT = 90.0

# A 1 MB function stalled IDA Free's cloud decompiler for minutes and froze
# the whole process.  Functions above this size are skipped by default and can
# be attempted later with --max-size 0 --allow-large (one at a time, watch IDA).
DEFAULT_MAX_SIZE = 0x4000

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.@$+-]+")

_stop_requested = False


# ──────────────────────────────────────────────────────────────────────
# MCP client
# ──────────────────────────────────────────────────────────────────────


class McpError(RuntimeError):
    """A JSON-RPC or tool-level error."""


class ToolError(McpError):
    """The tool returned ok=false / isError=true."""


class McpClient:
    """Minimal stateless JSON-RPC client for the ida-free-mcp HTTP endpoint."""

    def __init__(self, url: str, read_timeout: float = DEFAULT_READ_TIMEOUT):
        self.url = url
        self.read_timeout = read_timeout
        self.session = requests.Session()
        # Retries are handled explicitly by the caller; fail fast on transport
        # errors so a hung request cannot silently double our work.
        adapter = requests.adapters.HTTPAdapter(max_retries=0)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self._next_id = 0
        self.server_info: dict[str, Any] = {}

    # -- low level ---------------------------------------------------

    @staticmethod
    def _parse_sse(text: str) -> dict[str, Any]:
        """Extract the last JSON-RPC response object from an SSE body."""
        blobs: list[str] = []
        current: list[str] = []
        for line in text.splitlines():
            if line.startswith("data:"):
                current.append(line[5:].lstrip())
            elif not line.strip():
                if current:
                    blobs.append("\n".join(current))
                    current = []
        if current:
            blobs.append("\n".join(current))
        for blob in reversed(blobs):
            try:
                obj = json.loads(blob)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and ("result" in obj or "error" in obj):
                return obj
        raise McpError("no JSON-RPC response found in SSE stream")

    def _post(
        self, payload: dict[str, Any], timeout: float | None = None
    ) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        try:
            resp = self.session.post(
                self.url,
                json=payload,
                headers=headers,
                timeout=(5.0, timeout if timeout is not None else self.read_timeout),
            )
        except requests.RequestException as exc:
            raise McpError(f"HTTP request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise McpError(f"HTTP {resp.status_code}: {resp.text[:500]}")
        ctype = resp.headers.get("Content-Type", "")
        if "text/event-stream" in ctype:
            return self._parse_sse(resp.text)
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise McpError(f"invalid JSON response: {resp.text[:500]}") from exc

    def request(
        self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> Any:
        self._next_id += 1
        body = self._post(
            {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params or {}},
            timeout=timeout,
        )
        if "error" in body:
            err = body["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            raise McpError(f"JSON-RPC error: {message}")
        return body.get("result")

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        # Notifications have no id; the server may still reply with 202/empty.
        self._post({"jsonrpc": "2.0", "method": method, "params": params or {}}, timeout=10.0)

    # -- MCP ---------------------------------------------------------

    def initialize(self) -> dict[str, Any]:
        result = self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "ida-pseudocode-export", "version": "1.0"},
            },
            timeout=15.0,
        )
        self.server_info = (result or {}).get("serverInfo", {})
        try:
            self.notify("notifications/initialized")
        except McpError:
            pass
        return result or {}

    def call_tool(
        self, name: str, arguments: dict[str, Any], *, timeout: float | None = None
    ) -> Any:
        result = self.request(
            "tools/call",
            {"name": name, "arguments": arguments},
            timeout=timeout,
        )
        if not isinstance(result, dict):
            raise McpError(f"malformed tools/call result: {result!r}")

        if result.get("isError"):
            text = _content_text(result) or "tool returned isError"
            raise ToolError(text)

        text = _content_text(result)
        data: Any
        if text is not None:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                raise McpError(f"tool content is not JSON: {text[:300]}") from exc
        else:
            data = result.get("structuredContent")

        # Large tool outputs may arrive truncated in structuredContent while
        # the content text above is complete.  If a future server truncates
        # both, follow the download URL and load the full JSON.
        if isinstance(data, dict) and data.get("_output_truncated"):
            url = data.get("_download_url")
            if url:
                url = url.replace("0.0.0.0", "127.0.0.1").replace("localhost", "127.0.0.1")
                try:
                    full = self.session.get(url, timeout=(5.0, 120.0))
                    full.raise_for_status()
                    data = full.json()
                except (requests.RequestException, ValueError) as exc:
                    raise McpError(f"failed to fetch offloaded output: {exc}") from exc
        return data


def _content_text(result: dict[str, Any]) -> str | None:
    for part in result.get("content", []) or []:
        if isinstance(part, dict) and part.get("type") == "text":
            text = part.get("text")
            if isinstance(text, str):
                return text
    return None


# ──────────────────────────────────────────────────────────────────────
# Export helpers
# ──────────────────────────────────────────────────────────────────────


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_name(name: str, limit: int = 80) -> str:
    cleaned = _SAFE_NAME_RE.sub("_", name or "").strip("_")
    return (cleaned[:limit] or "unnamed")


def func_filename(addr: str, name: str) -> str:
    return f"{addr}_{safe_name(name)}.c"


def atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
        fh.flush()


def load_existing(out_dir: Path) -> set[str]:
    """Addresses whose output file already exists (resume support)."""
    done: set[str] = set()
    funcs_dir = out_dir / "functions"
    if not funcs_dir.is_dir():
        return done
    for path in funcs_dir.glob("*.c"):
        addr = path.name.split("_", 1)[0]
        if addr.startswith("0x"):
            done.add(addr)
    return done


def fetch_functions(client: McpClient) -> list[dict[str, Any]]:
    """Return the full function list (addr/name/size) from the IDB."""
    data = client.call_tool("list_funcs", {"queries": {"offset": 0, "count": 0}}, timeout=180.0)

    pages: list[Any]
    if isinstance(data, list):
        pages = data
    elif isinstance(data, dict):
        pages = [data]
    else:
        raise McpError(f"unexpected list_funcs result: {type(data).__name__}")

    funcs: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_page(page: Any) -> int | None:
        if not isinstance(page, dict) or "data" not in page:
            raise McpError(f"unexpected list_funcs page: {page!r}")
        for item in page["data"]:
            addr = item.get("addr")
            if isinstance(addr, str) and addr not in seen:
                seen.add(addr)
                funcs.append(item)
        return page.get("next_offset")

    next_offset = None
    for page in pages:
        next_offset = add_page(page)
    # Defensive pagination fallback if count=0 ever stops returning everything.
    while next_offset is not None:
        more = client.call_tool(
            "list_funcs",
            {"queries": {"offset": next_offset, "count": 5000}},
            timeout=180.0,
        )
        more_pages = more if isinstance(more, list) else [more]
        for page in more_pages:
            next_offset = add_page(page)

    funcs.sort(key=lambda f: int(str(f["addr"]), 16))
    return funcs


# UIA helper: give keyboard focus back to the disassembly view.
#
# The MCP decompile tool activates "IDA View-A" before running F5, but in some
# states (after a failed decompile closed the pseudocode tab, or when another
# dock such as Local Types has keyboard focus) the F5 action is disabled and
# every decompile fails with "Decompiler action failed (hx:GenPseudo)".  The
# documented manual cure is to click IDA and press Tab; programmatically,
# selecting the IDA View-A tab item via UI Automation restores the keyboard
# focus to the IDAView control and makes F5 work again.
_FOCUS_PS = r"""
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
try {
  $proc = Get-Process ida -ErrorAction Stop | Select-Object -First 1
} catch { exit 2 }
$root = [System.Windows.Automation.AutomationElement]::FromHandle($proc.MainWindowHandle)
if (-not $root) { exit 3 }
$tabs = $root.FindAll(
  [System.Windows.Automation.TreeScope]::Descendants,
  [System.Windows.Automation.PropertyCondition]::new(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Tab))
$found = $false
foreach ($t in $tabs) {
  $items = $t.FindAll(
    [System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.PropertyCondition]::new(
      [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
      [System.Windows.Automation.ControlType]::TabItem))
  foreach ($it in $items) {
    if ($it.Current.Name -like '*IDA View-*') {
      try {
        $p = $it.GetCurrentPattern(
          [System.Windows.Automation.SelectionItemPattern]::Pattern)
        $p.Select()
        $found = $true
      } catch {}
    }
  }
}
if ($found) { Start-Sleep -Milliseconds 300; exit 0 }
exit 1
"""


def focus_ida_view(timeout: float = 20.0) -> bool:
    """Restore keyboard focus to IDA's disassembly view (Windows/WSL only)."""
    if not os.path.exists(POWERSHELL_EXE):
        return False
    encoded = base64.b64encode(_FOCUS_PS.encode("utf-16-le")).decode("ascii")
    try:
        proc = subprocess.run(
            [
                POWERSHELL_EXE,
                "-NoProfile",
                "-NonInteractive",
                "-EncodedCommand",
                encoded,
            ],
            timeout=timeout,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  focus helper failed: {exc}")
        return False
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        print(f"  focus helper exit {proc.returncode}: {detail[:200]}")
        return False
    return True


def wait_for_ida(client: McpClient, max_wait_s: float, probe_addr: str) -> bool:
    """Wait until the IDA main thread answers a cheap tool call again."""
    deadline = time.monotonic() + max_wait_s
    started = time.monotonic()
    while time.monotonic() < deadline:
        try:
            client.call_tool("lookup_funcs", {"queries": probe_addr}, timeout=15.0)
            if time.monotonic() - started > 1.0:
                print("  IDA is responsive again; resuming.")
            return True
        except (McpError, requests.RequestException):
            if _stop_requested:
                return False
            time.sleep(5.0)
    return False


def decompile_with_retry(
    client: McpClient,
    addr: str,
    *,
    attempts: int,
    request_timeout: float,
    probe_addr: str,
    ida_recovery_s: float,
    focus_cb: Any = None,
) -> tuple[dict[str, Any], float]:
    """Decompile one address, retrying cold-start/transient failures."""
    last_error = "unknown error"
    started = time.monotonic()
    for attempt in range(attempts):
        if _stop_requested:
            raise McpError("interrupted")
        try:
            data = client.call_tool("decompile", {"addr": addr}, timeout=request_timeout)
        except ToolError as exc:
            last_error = str(exc)
        except McpError as exc:
            last_error = str(exc)
            # An HTTP timeout can mean IDA is still chewing on a huge
            # function.  Give it a chance to answer again before retrying,
            # otherwise every subsequent call would time out too.
            if "timed out" in last_error.lower() or "HTTP request failed" in last_error:
                if not wait_for_ida(client, ida_recovery_s, probe_addr):
                    raise McpError(
                        f"IDA did not recover after {ida_recovery_s:.0f}s "
                        f"({last_error})"
                    ) from exc
        else:
            if isinstance(data, dict) and data.get("ok") and isinstance(data.get("pseudocode"), str):
                return data, time.monotonic() - started
            if isinstance(data, dict):
                last_error = str(data.get("error") or "ok=false")
            else:
                last_error = f"unexpected result: {data!r}"

        # Do not burn retries on a missing function; retry everything else.
        if "No function at" in last_error or "Failed to parse address" in last_error:
            break

        # A cold start usually cures itself on the next call.  A missing focus
        # ("Decompiler action failed", or repeated widget misses) needs the
        # disassembly view to be focused again; the plugin's activate_widget
        # does not always manage that after it has closed a pseudocode tab.
        if focus_cb is not None and (
            attempt >= 1 or "Decompiler action failed" in last_error
        ):
            if focus_cb():
                print("  refocused IDA View-A")
        delay = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
        if attempt + 1 < attempts:
            time.sleep(delay)
    raise ToolError(last_error)


def format_pseudocode_file(
    addr: str, name: str, size: str, result: dict[str, Any], source: str
) -> str:
    pseudocode = result["pseudocode"].rstrip("\n")
    return (
        f"// addr: {addr}\n"
        f"// name: {name}\n"
        f"// size: {size} ({_size_bytes(size)} bytes)\n"
        f"// lines: {result.get('lines', 0)}\n"
        f"// exported: {utc_now()}\n"
        f"// source: {source}\n"
        f"\n"
        f"{pseudocode}\n"
    )


def _size_bytes(size: str) -> int:
    try:
        return int(size, 16)
    except (TypeError, ValueError):
        return 0


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export all IDA function pseudocode to local files via ida-free-mcp.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="MCP endpoint URL")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output directory")
    parser.add_argument("--limit", type=int, default=0, help="Export at most N functions (0 = all)")
    parser.add_argument(
        "--max-size",
        type=lambda v: int(v, 0),
        default=DEFAULT_MAX_SIZE,
        help="Skip functions larger than this many bytes (0 = no limit)",
    )
    parser.add_argument(
        "--allow-large",
        action="store_true",
        help="Attempt functions above --max-size (may freeze IDA for minutes)",
    )
    parser.add_argument("--attempts", type=int, default=6, help="Decompile attempts per function")
    parser.add_argument(
        "--read-timeout",
        type=float,
        default=DEFAULT_READ_TIMEOUT,
        help="HTTP read timeout per tool call (seconds)",
    )
    parser.add_argument(
        "--ida-recovery-wait",
        type=float,
        default=300.0,
        help="How long to wait for IDA after a timeout before aborting (seconds)",
    )
    parser.add_argument(
        "--no-focus-helper",
        action="store_true",
        help="Disable the Windows UIA helper that refocuses IDA View-A on failures",
    )
    parser.add_argument(
        "--focus-every",
        type=int,
        default=250,
        help="Proactively refocus IDA View-A every N functions (0 = only on failures)",
    )
    parser.add_argument(
        "--progress-every", type=int, default=25, help="Progress line interval (functions)"
    )
    parser.add_argument(
        "--retry-failures",
        action="store_true",
        help="Only retry addresses present in failures.jsonl",
    )
    parser.add_argument("--source", default="Growtopia.exe.i64", help="Source label for headers")
    parser.add_argument("--dry-run", action="store_true", help="List planned work and exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    global _stop_requested

    args = parse_args(argv)
    out_dir: Path = args.out
    funcs_dir = out_dir / "functions"
    index_path = out_dir / "index.jsonl"
    failures_path = out_dir / "failures.jsonl"
    skipped_path = out_dir / "skipped_large.jsonl"
    manifest_path = out_dir / "manifest.json"

    def _handle_sigint(signum: int, frame: Any) -> None:
        global _stop_requested
        if _stop_requested:
            raise KeyboardInterrupt
        _stop_requested = True
        print("\nInterrupt received; finishing the current function, then stopping...")

    signal.signal(signal.SIGINT, _handle_sigint)

    client = McpClient(args.url, read_timeout=args.read_timeout)
    try:
        client.initialize()
    except McpError as exc:
        print(f"error: cannot reach the IDA MCP server at {args.url}: {exc}", file=sys.stderr)
        return 2

    print(f"IDA MCP server: {client.server_info.get('name', '?')} {client.server_info.get('version', '?')}")
    try:
        all_funcs = fetch_functions(client)
    except McpError as exc:
        print(f"error: failed to enumerate functions: {exc}", file=sys.stderr)
        return 2
    print(f"functions in IDB: {len(all_funcs):,}")

    if not all_funcs:
        print("error: the IDB reported no functions", file=sys.stderr)
        return 2

    # The probe address is used to test whether IDA's main thread is free.
    probe_addr = all_funcs[0]["addr"]

    focus_cb = None if args.no_focus_helper else focus_ida_view
    if focus_cb is not None:
        if focus_cb():
            print("focused IDA View-A")
        else:
            print(
                "warning: could not focus IDA View-A (helper unavailable?); "
                "continuing, will retry on failures"
            )

    # Resume support: final files are written atomically, so existence = done.
    done = load_existing(out_dir)
    if done:
        print(f"resume: {len(done):,} functions already exported")

    if args.retry_failures and failures_path.exists():
        wanted: set[str] = set()
        for line in failures_path.read_text(encoding="utf-8").splitlines():
            try:
                wanted.add(json.loads(line)["addr"])
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        pending = [f for f in all_funcs if f["addr"] in wanted]
        print(f"retry-failures: {len(pending):,} addresses from {failures_path.name}")
    else:
        pending = [f for f in all_funcs if f["addr"] not in done]

    eligible: list[dict[str, Any]] = []
    skipped_large: list[dict[str, Any]] = []
    for f in pending:
        size = _size_bytes(f.get("size", "0x0"))
        if args.max_size and size > args.max_size and not args.allow_large:
            skipped_large.append(
                {
                    "addr": f["addr"],
                    "name": f.get("name", ""),
                    "size": f.get("size", "0x0"),
                    "reason": f"size > {args.max_size:#x}",
                }
            )
            continue
        eligible.append(f)

    selected = eligible[: args.limit] if args.limit else eligible

    if args.dry_run:
        print(f"would export {len(selected):,} functions")
        print(f"would skip (large) {len(skipped_large):,} functions")
        if skipped_large:
            for s in skipped_large[:10]:
                print(f"  {s['addr']} {s['name']} {s['size']}")
        return 0

    funcs_dir.mkdir(parents=True, exist_ok=True)
    if skipped_large:
        atomic_write_text(
            skipped_path,
            "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in skipped_large),
        )
        print(f"skipping {len(skipped_large):,} large functions (see {skipped_path.name})")

    # Persist the full function list for reference/reproducibility.
    atomic_write_text(
        out_dir / "functions.json",
        json.dumps(all_funcs, indent=1) + "\n",
    )

    total = len(selected)
    print(f"exporting {total:,} functions to {out_dir}")
    print(f"retry schedule: {RETRY_DELAYS[: args.attempts]}, HTTP timeout {args.read_timeout:.0f}s")

    started = time.monotonic()
    exported = 0
    failed: list[dict[str, Any]] = []
    total_lines = 0
    total_chars = 0

    for i, f in enumerate(selected, start=1):
        if _stop_requested:
            print("stopping before next function")
            break
        if (
            focus_cb is not None
            and args.focus_every
            and i > 1
            and (i - 1) % args.focus_every == 0
        ):
            focus_cb()
        addr = f["addr"]
        name = f.get("name", "")
        size = f.get("size", "0x0")
        dest = funcs_dir / func_filename(addr, name)
        try:
            result, elapsed = decompile_with_retry(
                client,
                addr,
                attempts=args.attempts,
                request_timeout=args.read_timeout,
                probe_addr=probe_addr,
                ida_recovery_s=args.ida_recovery_wait,
                focus_cb=focus_cb,
            )
        except KeyboardInterrupt:
            print("\ninterrupted")
            break
        except McpError as exc:
            error = str(exc)
            failed.append(
                {"addr": addr, "name": name, "size": size, "error": error, "at": utc_now()}
            )
            append_jsonl(failures_path, failed[-1])
            print(f"[{i}/{total}] FAILED {addr} {name}: {error}")
            continue

        text = format_pseudocode_file(addr, name, size, result, args.source)
        atomic_write_text(dest, text)
        pseudocode = result["pseudocode"]
        lines = int(result.get("lines", 0))
        entry = {
            "addr": addr,
            "name": name,
            "size": size,
            "file": str(dest.relative_to(out_dir)),
            "lines": lines,
            "chars": len(pseudocode),
            "sha256": sha256_text(pseudocode),
            "elapsed_s": round(elapsed, 3),
            "exported": utc_now(),
        }
        append_jsonl(index_path, entry)
        exported += 1
        total_lines += lines
        total_chars += len(pseudocode)

        if i % args.progress_every == 0 or i == total:
            wall = time.monotonic() - started
            rate = wall / i if i else 0.0
            eta = rate * (total - i)
            print(
                f"[{i}/{total}] {addr} {name} ({lines} lines) | "
                f"{rate:.2f}s/f | ETA {_fmt_duration(eta)} | "
                f"fails {len(failed)} | {total_chars/1e6:.1f} MB"
            )

    wall = time.monotonic() - started
    summary = {
        "started": utc_now(),
        "finished": utc_now(),
        "url": args.url,
        "out": str(out_dir),
        "server": client.server_info,
        "functions_total": len(all_funcs),
        "selected": len(selected),
        "exported_this_run": exported,
        "already_done": len(done),
        "failed": len(failed),
        "skipped_large": len(skipped_large),
        "elapsed_s": round(wall, 1),
        "avg_s_per_function": round(wall / exported, 3) if exported else None,
        "total_lines": total_lines,
        "total_chars": total_chars,
        "max_size": args.max_size,
        "allow_large": args.allow_large,
    }
    atomic_write_text(manifest_path, json.dumps(summary, indent=2) + "\n")

    print()
    print(f"exported: {exported:,} this run, {len(done) + exported:,} on disk")
    print(f"failed:   {len(failed):,} (see {failures_path.name})")
    print(f"skipped:  {len(skipped_large):,} large functions (see {skipped_path.name})")
    print(f"elapsed:  {_fmt_duration(wall)}")
    print(f"output:   {out_dir}")
    if failed:
        return 1
    return 0


def _fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


if __name__ == "__main__":
    sys.exit(main())
