#!/usr/bin/env python3
"""Fetch the IDB's data-segment bytes over the IDA MCP ``get_bytes`` tool.

The MCP server truncates large tool results; when that happens the full JSON
is downloaded from the returned ``_download_url`` and parsed here.  Segment
ranges come from ``export/ida_data/segments.tsv`` (written by the IDC script).

Usage:
    .venv/bin/python scripts/fetch_ida_data_bytes.py [--url URL] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests

DEFAULT_URL = "http://127.0.0.1:13337/mcp"
DEFAULT_OUT = "export/ida_data/raw"
DEFAULT_CHUNK = 4096  # the plugin truncates get_bytes output above ~4 KiB

# Data segments (everything except .text) from segments.tsv.
SEGMENTS = [
    ("idata", 0x1408B2000, 0x1408B2DA8),
    ("rdata", 0x1408B2DA8, 0x140B18000),
    ("data", 0x140B18000, 0x140D1F000),
    ("pdata", 0x140D1F000, 0x140D77000),
    ("tls", 0x140D77000, 0x140D78000),
    ("gfids", 0x140D78000, 0x140D79000),
    ("_RDATA", 0x140D79000, 0x140D7A000),
]


def load_segments(path: str):
    """Load name/start/end rows from segments.tsv (skip .text)."""
    rows = []
    with open(path, encoding="utf-8") as fh:
        header = fh.readline()
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 4:
                continue
            name, start, end = parts[0], int(parts[1], 0), int(parts[2], 0)
            if name == ".text":
                continue
            rows.append((name.lstrip("."), start, end))
    return rows


class Mcp:
    def __init__(self, url: str):
        self.url = url
        self.calls = 0

    def call(self, name: str, arguments: dict, timeout: float = 300.0):
        self.calls += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self.calls,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        resp = requests.post(
            self.url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        result = resp.json().get("result", {})
        # Large results are offloaded; download the full JSON directly.
        if isinstance(result, dict) and result.get("_download_url"):
            url = result["_download_url"].replace("0.0.0.0", "127.0.0.1")
            full = requests.get(url, timeout=timeout)
            full.raise_for_status()
            result = full.json()
        if isinstance(result, dict):
            structured = result.get("structuredContent")
            if structured is not None:
                if isinstance(structured, dict) and isinstance(
                    structured.get("result"), (list, dict)
                ):
                    return structured["result"]
                return structured
            if isinstance(result.get("result"), (list, dict)):
                return result["result"]
            for part in result.get("content", []):
                if part.get("type") == "text":
                    try:
                        return json.loads(part["text"])
                    except json.JSONDecodeError:
                        return part["text"]
        return result


def hex_to_bytes(text: str) -> bytes:
    return bytes(int(tok, 16) for tok in text.split())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--chunk", type=lambda s: int(s, 0), default=DEFAULT_CHUNK)
    parser.add_argument(
        "--segments",
        default="export/ida_data/segments.tsv",
        help="segments.tsv produced by the IDC script",
    )
    args = parser.parse_args()

    segments = load_segments(args.segments) if os.path.exists(args.segments) else SEGMENTS
    os.makedirs(args.out, exist_ok=True)
    client = Mcp(args.url)

    started = time.time()
    index = []
    for name, start, end in segments:
        size = end - start
        path = os.path.join(args.out, f"{name}.bin")
        written = 0
        zeros = 0
        readable = True
        note = ""
        with open(path, "wb") as fh:
            off = 0
            while off < size:
                n = min(args.chunk, size - off)
                data = client.call(
                    "get_bytes", {"regions": [{"addr": hex(start + off), "size": n}]}
                )
                item = data[0] if isinstance(data, list) and data else None
                raw = b""
                if isinstance(item, dict) and item.get("data"):
                    raw = hex_to_bytes(item["data"])
                if not raw:
                    # Unreadable segment (e.g. .idata in this IDB) or a hole:
                    # skip the whole segment when it fails at the start,
                    # zero-fill mid-segment holes.
                    if off == 0:
                        readable = False
                        note = str((item or {}).get("error") or "empty read")
                        break
                    raw = b"\x00" * n
                    zeros += n
                fh.write(raw)
                written += len(raw)
                off += len(raw)
        if not readable:
            try:
                os.remove(path)
            except OSError:
                pass
        index.append(
            {
                "name": name,
                "start": hex(start),
                "end": hex(end),
                "size": size,
                "file": os.path.basename(path) if readable else "",
                "written": written,
                "zero_filled": zeros,
                "readable": readable,
                "note": note,
            }
        )
        state = f"{written:>9,d} bytes" if readable else f"unreadable ({note})"
        print(f"{name:8s} {state:>9s} / {size:>9,d} -> {os.path.basename(path) if readable else '-'}", flush=True)

    with open(os.path.join(args.out, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=1)
    total = sum(row["written"] for row in index)
    print(f"done: {total:,d} bytes in {time.time() - started:.1f}s ({client.calls} MCP calls)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
