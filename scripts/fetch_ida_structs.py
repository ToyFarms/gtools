#!/usr/bin/env python3
"""Export every UDT (struct/union) from the live IDB via the IDA MCP.

Uses ``search_structs`` to list all user-defined types and ``read_struct`` to
read each one's members, then writes:

    structs.jsonl   one JSON object per UDT (name, size, members, ...)
    structs.h       C-like struct/union definitions with offset comments
    structs_stats.json

This is a current snapshot of the type library, independent of the older
Growtopia.exe.h header.  Enums/typedefs are not covered by the MCP tools;
they come from the IDC type export (scripts/export_ida_types.idc).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

import requests

DEFAULT_URL = "http://127.0.0.1:13337/mcp"
DEFAULT_OUT = "export/ida_data"

ARRAY_RE = re.compile(r"^(?P<base>.+?)\[(?P<len>\d+)\]$")


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


def fmt_member(type_str: str, name: str, offset: int, size: int) -> str:
    name = name or f"field_{offset:X}"
    t = (type_str or "unsigned char").strip()
    if "(*)" in t:
        decl = t.replace("(*)", f"(*{name})")
    else:
        m = ARRAY_RE.match(t)
        if m:
            decl = f"{m.group('base')} {name}[{m.group('len')}]"
        else:
            decl = f"{t} {name}"
    return f"  {decl}; /* {offset:#x} size {size} */"


def write_header(path: str, rows: list) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("/*\n")
        fh.write(" * UDT snapshot from the live IDB (via IDA MCP search_structs/read_struct).\n")
        fh.write(" * Offsets/sizes are IDA's; enums and typedefs are not included here.\n")
        fh.write(" */\n\n")
        fh.write("#pragma pack(push, 1)\n\n")
        for row in rows:
            name = row.get("name") or f"anon_{row.get('ordinal', 0)}"
            kind = "union" if row.get("is_union") else "struct"
            fh.write(f"/* ordinal {row.get('ordinal')}, size {row.get('size', 0):#x} */\n")
            fh.write(f"{kind} {name}\n{{\n")
            for member in row.get("members", []):
                try:
                    offset = int(str(member.get("offset", "0x0")), 0)
                except ValueError:
                    offset = 0
                fh.write(
                    fmt_member(
                        member.get("type", ""),
                        member.get("name", ""),
                        offset,
                        int(member.get("size", 0) or 0),
                    )
                    + "\n"
                )
            fh.write("};\n\n")
        fh.write("#pragma pack(pop)\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=0, help="debug: stop after N structs")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    client = Mcp(args.url)
    started = time.time()

    listing = client.call("search_structs", {"filter": ""})
    if isinstance(listing, dict):
        listing = listing.get("data") or listing.get("result") or []
    structs = list(listing or [])
    if args.limit:
        structs = structs[: args.limit]
    print(f"structs: {len(structs)} UDTs", flush=True)

    rows = []
    errors = 0
    for i, entry in enumerate(structs, 1):
        name = entry.get("name") or ""
        try:
            reply = client.call("read_struct", {"queries": {"struct": name}})
            item = reply[0] if isinstance(reply, list) and reply else {}
            if not isinstance(item, dict) or item.get("error"):
                errors += 1
                continue
            row = {
                "name": name,
                "ordinal": entry.get("ordinal"),
                "size": entry.get("size"),
                "cardinality": entry.get("cardinality"),
                "is_union": entry.get("is_union"),
                "members": item.get("members", []),
            }
            # pick up any extra fields the tool returns (comments etc.)
            for key, value in item.items():
                if key not in ("members",) and value is not None:
                    row.setdefault(key, value)
            rows.append(row)
        except Exception as exc:  # noqa: BLE001
            errors += 1
            print(f"  [{i}/{len(structs)}] {name}: {exc}", flush=True)
        if i % 50 == 0:
            print(f"  [{i}/{len(structs)}] {name}", flush=True)

    with open(os.path.join(args.out, "structs.jsonl"), "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    write_header(os.path.join(args.out, "structs.h"), rows)
    with open(os.path.join(args.out, "structs_stats.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "udt_count": len(rows),
                "errors": errors,
                "elapsed_s": round(time.time() - started, 1),
                "mcp_calls": client.calls,
            },
            fh,
            indent=1,
        )
    print(
        f"done: {len(rows)} UDTs, {errors} errors in {time.time() - started:.1f}s "
        f"({client.calls} MCP calls)",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
