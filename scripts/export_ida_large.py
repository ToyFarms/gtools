#!/usr/bin/env python3
"""Export the functions skipped by the size guard (giants), smallest first.

Pseudocode is attempted with generous timeouts and retries; the shared MCP
client follows the server's offload URL so the full pseudocode is written
(never the truncated preview).  Functions whose pseudocode still fails get a
full disassembly listing instead (paginated, 50k instructions per call).

The 1 MB ``sub_1402E5B40`` is known to freeze IDA for minutes (4.4 GB RSS) and
is therefore ASM-only by default; pass ``--include-monster`` to attempt its
pseudocode as well (do that only after everything else is saved).

Usage:
    .venv/bin/python scripts/export_ida_large.py
    .venv/bin/python scripts/export_ida_large.py --include-monster
    .venv/bin/python scripts/export_ida_large.py --limit 5 --asm all
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# The exporter module lives next to this file; import its helpers so the file
# format, offload handling and index schema stay identical.
import export_ida_pseudocode as ep

MONSTER = "0x1402e5b40"


def load_skipped(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows.sort(key=lambda e: ep._size_bytes(e.get("size", "0x0")))
    return rows


def ida_process() -> dict | None:
    """Best-effort IDA process info from the MCP instance metadata."""
    import glob

    for meta in glob.glob("/mnt/c/Users/andra/.ida-mcp/instances/*.json"):
        try:
            with open(meta, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if str(data.get("port")) == "13337":
            return data
    return None


def try_pseudocode(client: ep.McpClient, addr: str, args) -> tuple[dict | None, str, float]:
    last_error = "unknown"
    focus_tried = False
    for attempt in range(1, args.attempts + 1):
        started = time.time()
        try:
            data = client.call_tool("decompile", {"addr": addr}, timeout=args.timeout)
        except ep.McpError as exc:
            elapsed = time.time() - started
            last_error = str(exc)
            print(f"    attempt {attempt}/{args.attempts}: {elapsed:6.1f}s error: {last_error[:110]}", flush=True)
        else:
            elapsed = time.time() - started
            if isinstance(data, dict) and data.get("ok") and isinstance(data.get("pseudocode"), str):
                return data, "", elapsed
            last_error = str(data.get("error") if isinstance(data, dict) else data)
            print(
                f"    attempt {attempt}/{args.attempts}: {elapsed:6.1f}s no widget: {last_error[:90]}",
                flush=True,
            )
            if "Decompiler action failed" in last_error and not focus_tried:
                focus_tried = True
                try:
                    result = ep.focus_ida_view(allow_steal=False)
                except Exception:  # noqa: BLE001
                    result = "failed"
                print(f"    focus helper: {result}", flush=True)
        if attempt < args.attempts:
            time.sleep(args.wait)
    return None, last_error, 0.0


def write_asm(client: ep.McpClient, addr: str, name: str, out_dir: Path, args) -> tuple[Path | None, int]:
    pages: list[str] = []
    offset = 0
    for page in range(1, args.asm_pages + 1):
        try:
            data = client.call_tool(
                "disasm",
                {"addr": addr, "max_instructions": 50000, "offset": offset},
                timeout=args.timeout,
            )
        except ep.McpError as exc:
            print(f"    asm page {page}: error {exc}", flush=True)
            break
        asm = data.get("asm") if isinstance(data, dict) else None
        lines = asm.get("lines") if isinstance(asm, dict) else None
        if not lines:
            break
        pages.append(lines)
        cursor = data.get("cursor") or {}
        if cursor.get("done") or cursor.get("next") is None:
            break
        offset = int(cursor["next"])
    if not pages:
        return None, 0
    path = out_dir / ep.func_filename(addr, name).replace(".c", ".asm")
    ep.atomic_write_text(path, "\n".join(pages))
    return path, len(pages)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=ep.DEFAULT_URL)
    parser.add_argument("--skipped", default="export/ida_pseudocode/skipped_large.jsonl")
    parser.add_argument("--out", default="export/ida_pseudocode")
    parser.add_argument("--source", default="Growtopia.exe.i64")
    parser.add_argument("--attempts", type=int, default=4)
    parser.add_argument(
        "--timeout",
        type=float,
        default=900.0,
        help="HTTP timeout per decompile/disasm call (seconds)",
    )
    parser.add_argument("--wait", type=float, default=15.0, help="seconds between attempts")
    parser.add_argument("--limit", type=int, default=0, help="only the first N functions")
    parser.add_argument(
        "--asm",
        choices=("none", "failed", "all"),
        default="failed",
        help="write assembly listings: never, only on failed pseudocode, or always",
    )
    parser.add_argument("--asm-pages", type=int, default=20, help="max 50k-instruction pages")
    parser.add_argument(
        "--include-monster",
        action="store_true",
        help="also try pseudocode for sub_1402E5B40 (can freeze IDA)",
    )
    parser.add_argument("--skip-done", action="store_true", default=True)
    args = parser.parse_args()

    out_dir = Path(args.out)
    funcs_dir = out_dir / "functions"
    large_dir = out_dir / "large"
    funcs_dir.mkdir(parents=True, exist_ok=True)
    large_dir.mkdir(parents=True, exist_ok=True)

    rows = load_skipped(Path(args.skipped))
    print(f"skipped giants: {len(rows)} (smallest first)", flush=True)

    info = ida_process()
    if info:
        print(f"IDA pid {info.get('pid')} on port {info.get('port')} ({info.get('idb_path')})", flush=True)

    client = ep.McpClient(args.url)
    try:
        client.initialize()
        print(f"MCP server: {client.server_info.get('name')} {client.server_info.get('version')}", flush=True)
    except ep.McpError as exc:
        print(f"warning: MCP initialize failed: {exc}", flush=True)

    index_path = large_dir / "index.jsonl"
    done = 0
    ok_count = 0
    for row in rows:
        addr = row["addr"]
        name = row.get("name") or ""
        size = row.get("size") or "0x0"
        size_int = ep._size_bytes(size)
        c_path = funcs_dir / ep.func_filename(addr, name)

        if args.limit and done >= args.limit:
            break
        if args.skip_done and c_path.exists():
            print(f"== {addr} {name} ({size}): already exported, skip", flush=True)
            continue

        monster = addr.lower() == MONSTER
        mode = "pseudocode"
        if monster and not args.include_monster:
            mode = "asm-only (monster)"

        print(f"== {addr} {name} ({size} = {size_int:,} bytes) [{mode}]", flush=True)
        started = time.time()
        entry: dict = {"addr": addr, "name": name, "size": size, "started": ep.utc_now()}

        result = None
        if not (monster and not args.include_monster):
            result, last_error, elapsed = try_pseudocode(client, addr, args)
            if result is not None:
                text = ep.format_pseudocode_file(addr, name, size, result, args.source)
                ep.atomic_write_text(c_path, text)
                chars = len(result.get("pseudocode") or "")
                print(
                    f"   pseudocode OK: {result.get('lines')} lines, {chars:,} chars, "
                    f"{elapsed:.1f}s -> {c_path.name}",
                    flush=True,
                )
                entry.update(
                    {
                        "file": f"functions/{c_path.name}",
                        "lines": result.get("lines"),
                        "chars": chars,
                        "pseudocode": True,
                        "elapsed_s": round(elapsed, 1),
                    }
                )
                ok_count += 1
            else:
                print(f"   pseudocode FAILED: {last_error[:120]}", flush=True)
                entry.update({"pseudocode": False, "error": last_error[:300]})
        else:
            entry.update({"pseudocode": False, "error": "monster: asm-only by default"})

        if (
            args.asm == "all"
            or (args.asm == "failed" and result is None)
            or (monster and not args.include_monster)
        ):
            asm_path, pages = write_asm(client, addr, name, large_dir, args)
            if asm_path:
                print(f"   asm OK: {pages} page(s) -> {asm_path.name}", flush=True)
                entry["asm_file"] = f"large/{asm_path.name}"
            else:
                print("   asm FAILED", flush=True)

        entry["finished"] = ep.utc_now()
        entry["wall_s"] = round(time.time() - started, 1)
        with open(index_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        done += 1

    print(f"done: {done} attempted, {ok_count} pseudocode files written", flush=True)
    print(f"index: {index_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
