#!/usr/bin/env python3
"""Consistent single-function decompilation through the IDA MCP server.

The raw MCP ``decompile`` tool drives IDA Free's GUI (F5) and reads the
pseudocode widget, so it fails in known, avoidable ways.  This wrapper encodes
every recovery we have verified and applies the fix **automatically within the
same run**, so one command just works:

- cold start: the plugin polls for the widget for ~2 s, but the first decompile
  after idle can take ~2.5 s -- the call fails while the decompilation finishes
  in the background.  Retried with backoff.
- focus loss: F5 is context-sensitive; after a failed attempt IDA View-A can
  lose keyboard focus and the tool returns "Decompiler action failed
  (hx:GenPseudo)".  The UIA helper selects the IDA View-A tab item (this briefly
  activates the IDA window -- that is the verified cure) and the call is
  retried.  ``--no-steal`` keeps the helper from activating IDA (it then skips
  when IDA is in the background); ``--no-focus`` disables it entirely.
- call analysis: a persistent "No pseudocode widget" is often IDA's "call
  analysis failed".  The function is undefined/redefined (plain, anchored and
  full-range variants, stub-size guarded) and decompiled again.  ``--no-fix``
  disables this.
- stale type: output containing ``->?`` comes from a cached stale type.  The
  prototype is re-set (simple signature, then the real one from
  ``export_funcs``) and the function is decompiled again.  ``--no-fix``
  disables this.
- giant functions: an HTTP timeout can mean IDA is still decompiling -- the
  wrapper probes with ``lookup_funcs`` until the main thread answers, then
  retries instead of stacking timeouts.
- large output: the MCP server offloads replies above ~30 KB -- the shared
  client follows the download URL, so the full pseudocode is printed, never the
  1 KB preview.

Usage:
    .venv/bin/python scripts/decompile.py 0x140554c10
    .venv/bin/python scripts/decompile.py handleSetCharacterState
    .venv/bin/python scripts/decompile.py CanPassThroughTile --out /tmp/opencode/canpass.c
    .venv/bin/python scripts/decompile.py 0x140554c10 --json

Only stdout carries pseudocode (or JSON with ``--json``); progress notes go to
stderr, so ``scripts/decompile.py ADDR > file.c`` is clean.  Exit codes:
0 success, 1 decompile failure, 2 setup/resolution error.
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# Shared with the batch exporter: MCP client (with offload handling), retry
# loop, UIA focus helper and the undefine/redefine repair recipe.
import export_ida_pseudocode as ep  # noqa: E402

MCP_INSTANCE_DIR = Path("/mnt/c/Users/andra/.ida-mcp/instances")
SOURCE = "Growtopia.exe.i64"
STALE_MARKER = "->?"
# Only sub_1402E5B40 (0xf9520) is above this today; decompiling it freezes IDA
# Free for minutes, so it is refused unless --allow-large is passed.
MAX_AUTO_SIZE = 0x80000

_HEX_RE = re.compile(r"0[xX][0-9a-fA-F]+")
_DEC_RE = re.compile(r"\d+")


class RefusedError(RuntimeError):
    """The function is too large to attempt automatically."""


def log(message: str) -> None:
    print(message, file=sys.stderr)


# ──────────────────────────────────────────────────────────────────────
# Connection / resolution
# ──────────────────────────────────────────────────────────────────────


def candidate_urls(forced: str | None) -> list[str]:
    """MCP endpoints to try: forced URL, live instances (newest first), default."""
    urls: list[str] = []
    if forced:
        urls.append(forced)
    try:
        metas = sorted(
            glob.glob(str(MCP_INSTANCE_DIR / "*.json")),
            key=os.path.getmtime,
            reverse=True,
        )
    except OSError:
        metas = []
    for meta in metas:
        try:
            data = json.loads(Path(meta).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        port = data.get("port")
        if port:
            urls.append(f"http://127.0.0.1:{port}/mcp")
    urls.append(ep.DEFAULT_URL)
    # de-duplicate, keep order
    seen: set[str] = set()
    return [u for u in urls if not (u in seen or seen.add(u))]


def connect(forced: str | None) -> tuple[ep.McpClient, str]:
    last: Exception | None = None
    for url in candidate_urls(forced):
        client = ep.McpClient(url)
        try:
            client.initialize()
            return client, url
        except ep.McpError as exc:
            last = exc
    raise ep.McpError(f"cannot reach the IDA MCP server ({last})")


def resolve_one(client: ep.McpClient, query: str) -> dict[str, str]:
    """Resolve an address or function name to {addr, name, size}."""
    raw = query.strip()
    is_hex = bool(_HEX_RE.fullmatch(raw))
    is_dec = bool(_DEC_RE.fullmatch(raw))
    wanted_addr = hex(int(raw, 0)) if (is_hex or is_dec) else None

    lookup = client.call_tool("lookup_funcs", {"queries": wanted_addr or raw}, timeout=30.0)
    items: Any = lookup.get("result", lookup) if isinstance(lookup, dict) else lookup
    if not isinstance(items, list):
        items = [items]
    fns = [
        item["fn"]
        for item in items
        if isinstance(item, dict) and isinstance(item.get("fn"), dict)
    ]

    if wanted_addr is not None:
        for fn in fns:
            if hex(int(fn.get("addr", wanted_addr), 0)) == wanted_addr:
                return {
                    "addr": wanted_addr,
                    "name": fn.get("name") or "",
                    "size": fn.get("size") or "0x0",
                }
        raise ValueError(f"no function at {wanted_addr}")

    exact = [fn for fn in fns if fn.get("name") == raw]
    if not exact and len(fns) == 1:
        exact = fns
    if not exact:
        if fns:
            cand = ", ".join(f"{f.get('addr')} {f.get('name')}" for f in fns[:5])
            raise ValueError(f"{raw!r} is inexact or ambiguous; candidates: {cand}")
        raise ValueError(f"no function named {raw!r}")
    if len(exact) > 1:
        cand = ", ".join(f"{f.get('addr')} {f.get('name')}" for f in exact[:5])
        raise ValueError(f"{raw!r} matches several functions: {cand}")
    fn = exact[0]
    return {
        "addr": hex(int(fn["addr"], 0)),
        "name": fn.get("name") or "",
        "size": fn.get("size") or "0x0",
    }


# ──────────────────────────────────────────────────────────────────────
# Auto-fixes
# ──────────────────────────────────────────────────────────────────────


def _edit_ok(result: Any) -> bool:
    if isinstance(result, list):
        result = result[0] if result else None
    if isinstance(result, dict):
        return bool(result.get("ok", True)) and not result.get("error")
    return result is not None


def refresh_stale_type(client: ep.McpClient, addr: str, name: str) -> tuple[bool, str]:
    """Fix ``->?`` field accesses by invalidating the decompiler's cached type.

    Re-applies the function prototype as a placeholder and then back to the
    real one captured from ``export_funcs``.  The real signature is *validated
    first* (a no-op ``set_type``), so prototypes the MCP parser cannot handle
    -- e.g. unnamed ordinal parameter types such as ``#476 *ctx`` -- are
    skipped without touching the function at all.

    Returns ``(ok, detail)``: the restored prototype on success, or the reason
    the refresh was not attempted.
    """
    try:
        data = client.call_tool(
            "export_funcs", {"addrs": addr, "format": "prototypes"}, timeout=30.0
        )
    except ep.McpError as exc:
        return False, f"export_funcs failed: {exc}"

    functions = data.get("functions") if isinstance(data, dict) else data
    proto = ""
    proto_name = name
    if isinstance(functions, list):
        for entry in functions:
            if isinstance(entry, dict) and entry.get("prototype"):
                if entry.get("name") == name or not proto:
                    proto = str(entry["prototype"])
                    proto_name = str(entry.get("name") or name)
    if not proto or not proto_name:
        return False, "no prototype available"

    if proto_name in proto:
        real = proto
    elif "(" in proto:
        real = proto.replace("(", f" {proto_name}(", 1)
    else:
        return False, f"cannot derive a signature from {proto!r}"
    simple = f"void __fastcall {proto_name}(void *this)"
    if real == simple:
        return False, "the real signature is already the plain placeholder"

    def set_signature(signature: str) -> tuple[bool, str]:
        try:
            result = client.call_tool(
                "set_type",
                {"edits": [{"addr": addr, "signature": signature}]},
                timeout=30.0,
            )
        except ep.McpError as exc:
            return False, str(exc)
        if _edit_ok(result):
            return True, ""
        if isinstance(result, list) and result and isinstance(result[0], dict):
            return False, str(result[0].get("error") or result[0])
        return False, repr(result)

    # Validate the full round trip BEFORE changing anything: if the real
    # signature cannot be applied (ordinal types, unknown names, ...), skip the
    # refresh entirely instead of leaving the function half-modified.
    ok, error = set_signature(real)
    if not ok:
        return False, (
            f"the captured prototype cannot be re-applied ({error}); "
            "skipped, no changes made"
        )
    ok, error = set_signature(simple)
    if not ok:
        return False, f"set_type(placeholder) failed ({error}); function left untouched"
    ok, error = set_signature(real)
    if not ok:  # pre-checked minutes ago; one retry to cover a transient glitch
        ok, error = set_signature(real)
    if not ok:
        return False, (
            f"set_type(restore) failed ({error}) -- function left as the "
            f"placeholder; restore manually with: {real}"
        )
    return True, real


# ──────────────────────────────────────────────────────────────────────
# Decompile
# ──────────────────────────────────────────────────────────────────────


def decompile_one(
    client: ep.McpClient,
    fn: dict[str, str],
    args: argparse.Namespace,
    probe_addr: str,
) -> dict[str, Any]:
    addr, name, size = fn["addr"], fn["name"], fn["size"]
    size_int = ep._size_bytes(size)
    if size_int > MAX_AUTO_SIZE and not args.allow_large:
        raise RefusedError(
            f"{addr} {name} is {size_int:,} bytes; refusing to decompile because "
            f"functions this large ({name or 'the 1 MB monster'}) freeze IDA for "
            f"minutes -- pass --allow-large to attempt it anyway"
        )

    def focus_cb() -> str:
        result = ep.focus_ida_view(allow_steal=not args.no_steal)
        if result == "skipped" and args.no_steal and not args.no_focus:
            log("  (--no-steal is set; rerun without it to let the helper activate IDA)")
        return result

    def repair_cb() -> tuple[bool, str]:
        return ep.repair_function(client, addr, size_int)

    def run() -> tuple[dict[str, Any], float]:
        with contextlib.redirect_stdout(sys.stderr):
            return ep.decompile_with_retry(
                client,
                addr,
                attempts=6,
                request_timeout=ep.DEFAULT_READ_TIMEOUT,
                probe_addr=probe_addr,
                ida_recovery_s=300.0,
                focus_cb=None if args.no_focus else focus_cb,
                repair_cb=None if args.no_fix else repair_cb,
            )

    result, elapsed = run()
    pseudocode = result["pseudocode"]

    stale_fixed = False
    if STALE_MARKER in pseudocode and not args.no_fix:
        with contextlib.redirect_stdout(sys.stderr):
            ok, detail = refresh_stale_type(client, addr, name)
        if ok:
            log(f"  stale type: refreshed prototype to `{detail}`; re-decompiling")
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    refreshed, extra = run()
            except ep.McpError as exc:
                log(f"  stale type: re-decompile failed ({exc}); keeping the first output")
            else:
                elapsed += extra
                old_count = pseudocode.count(STALE_MARKER)
                new_count = refreshed["pseudocode"].count(STALE_MARKER)
                if new_count < old_count:
                    result, pseudocode = refreshed, refreshed["pseudocode"]
                if new_count == 0:
                    stale_fixed = True
                    log("  stale type: fixed")
                else:
                    log(f"  stale type: still present ({new_count} occurrence(s))")
        else:
            log(f"  stale type: could not refresh ({detail})")

    return {
        "addr": addr,
        "name": name,
        "size": size,
        "size_bytes": size_int,
        "lines": int(result.get("lines") or 0),
        "chars": len(pseudocode),
        "sha256": hashlib.sha256(pseudocode.encode("utf-8")).hexdigest(),
        "elapsed_s": round(elapsed, 3),
        "stale_type": STALE_MARKER in pseudocode,
        "stale_type_fixed": stale_fixed,
        "pseudocode": pseudocode if pseudocode.endswith("\n") else pseudocode + "\n",
        "file": None,
    }


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("queries", nargs="+", metavar="ADDR|NAME", help="function address or name")
    parser.add_argument("--json", action="store_true", help="emit a JSON array instead of pseudocode")
    parser.add_argument("--out", type=Path, metavar="PATH", help="write one query's output to PATH")
    parser.add_argument("--header", action="store_true", help="prepend the export-style // header")
    parser.add_argument("--url", default=None, help="force an MCP endpoint (default: auto-detect)")
    parser.add_argument(
        "--allow-large",
        action="store_true",
        help=f"attempt functions above {MAX_AUTO_SIZE:#x} bytes (may freeze IDA)",
    )
    parser.add_argument(
        "--no-fix",
        action="store_true",
        help="disable the automatic IDB fixes (undefine/redefine, stale-type refresh)",
    )
    parser.add_argument(
        "--no-focus",
        action="store_true",
        help="disable the UIA focus helper (cold-start retries still apply)",
    )
    parser.add_argument(
        "--no-steal",
        action="store_true",
        help="focus helper never activates the IDA window (skips when IDA is in the background)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        client, url = connect(args.url)
    except ep.McpError as exc:
        log(f"error: {exc}")
        return 2
    server = client.server_info or {}
    log(f"MCP {url} ({server.get('name', '?')} {server.get('version', '?')})")

    try:
        resolved = [resolve_one(client, query) for query in args.queries]
    except (ValueError, ep.McpError) as exc:
        log(f"error: {exc}")
        return 2
    if args.out is not None and len(resolved) > 1:
        log("error: --out takes exactly one ADDR|NAME")
        return 2

    probe_addr = resolved[0]["addr"]
    results: list[dict[str, Any]] = []
    failed = 0
    for fn in resolved:
        label = f"{fn['addr']} {fn['name']}".strip()
        try:
            entry = decompile_one(client, fn, args, probe_addr)
        except RefusedError as exc:
            log(f"error: {exc}")
            results.append({"addr": fn["addr"], "name": fn["name"], "error": str(exc)})
            failed += 1
            continue
        except ep.McpError as exc:
            error = str(exc)
            log(f"error: {label}: {error}")
            if "No pseudocode widget" in error:
                log(
                    "  hint: the usual cause is a wrong callee prototype breaking call "
                    "analysis (see the `Log` case in AGENTS.md), not the function itself"
                )
            results.append({"addr": fn["addr"], "name": fn["name"], "error": error})
            failed += 1
            continue

        text = entry["pseudocode"]
        if args.header:
            text = ep.format_pseudocode_file(
                fn["addr"],
                fn["name"],
                fn["size"],
                {"pseudocode": text, "lines": entry["lines"]},
                SOURCE,
            )
        if args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            ep.atomic_write_text(args.out, text)
            entry["file"] = str(args.out)
            entry["pseudocode"] = None
            log(f"wrote {args.out}")
        elif not args.json:
            if len(resolved) > 1 and not args.header:
                sys.stdout.write(f"// ===== {label} =====\n")
            sys.stdout.write(text)

        log(f"{label}: {entry['lines']} lines, {entry['chars']} chars, {entry['elapsed_s']}s")
        results.append(entry)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log("interrupted")
        sys.exit(130)
