#!/usr/bin/env python3
"""Split the IDC script's ``items.tsv`` into data-focused exports.

Input:  items.tsv written by scripts/export_ida_data.idc
Output (in --out, default export/ida_data):

    data_items.tsv     all non-code items (same columns as items.tsv)
    data_items.jsonl   the same rows as JSON objects
    data_named.tsv     non-code items that have a name
    data_strings.jsonl non-code string literals (full values)
    stats.json         counts by segment / type / name / string
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time

FIELDS = [
    "addr",
    "size",
    "code",
    "segment",
    "name",
    "type",
    "comment",
    "rcomment",
    "string",
    "hex",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tsv", help="items.tsv from the IDC script")
    parser.add_argument("--out", default="export/ida_data")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    started = time.time()

    total = code = data = named_data = str_count = 0
    by_segment: collections.Counter = collections.Counter()
    by_type: collections.Counter = collections.Counter()
    type_hist: collections.Counter = collections.Counter()

    paths = {
        "items": os.path.join(args.out, "data_items.tsv"),
        "jsonl": os.path.join(args.out, "data_items.jsonl"),
        "named": os.path.join(args.out, "data_named.tsv"),
        "strings": os.path.join(args.out, "data_strings.jsonl"),
    }
    with open(args.tsv, encoding="utf-8", errors="replace") as fh, open(
        paths["items"], "w", encoding="utf-8"
    ) as f_items, open(paths["jsonl"], "w", encoding="utf-8") as f_json, open(
        paths["named"], "w", encoding="utf-8"
    ) as f_named, open(
        paths["strings"], "w", encoding="utf-8"
    ) as f_str:
        header = fh.readline()
        f_items.write(header)
        f_named.write(header)
        for line in fh:
            total += 1
            parts = line.rstrip("\n").split("\t")
            if len(parts) < len(FIELDS):
                continue
            row = dict(zip(FIELDS, parts))
            if row["code"] == "1":
                code += 1
                continue
            data += 1
            by_segment[row["segment"]] += 1
            t = row["type"] or "(none)"
            type_hist[t] += 1
            by_type[t.split("(")[0].strip() or "(none)"] += 1
            if row["name"]:
                named_data += 1
                f_named.write(line)
            if row["string"]:
                str_count += 1
                f_str.write(json.dumps(row, ensure_ascii=False) + "\n")
            f_items.write(line)
            f_json.write(json.dumps(row, ensure_ascii=False) + "\n")

    stats = {
        "source": os.path.abspath(args.tsv),
        "rows_total": total,
        "code_items": code,
        "data_items": data,
        "named_data_items": named_data,
        "string_items": str_count,
        "by_segment": dict(by_segment),
        "top_types": dict(type_hist.most_common(30)),
        "elapsed_s": round(time.time() - started, 1),
    }
    with open(os.path.join(args.out, "stats.json"), "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=1)

    print(
        f"rows={total:,} code={code:,} data={data:,} named_data={named_data:,} "
        f"strings={str_count:,} in {stats['elapsed_s']}s"
    )
    for name in ("by_segment", "top_types"):
        print(name + ":")
        for key, value in stats[name].items():
            print(f"  {key}: {value:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
