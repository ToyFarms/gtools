import argparse
import contextlib
import inspect
import io
import os
import re
import struct
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from gtools import setting

from gtools.core.buffer import Buffer
os.environ["DONT_LOAD_ITEM"] = "1"
from gtools.core.growtopia.items_dat import Item
del os.environ["DONT_LOAD_ITEM"]
from gtools.core.utils import get_home

BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"

_SECRET = b"PBG892FXX982ABC*"
_SECRET_LEN = len(_SECRET)
_SECRET_TILED = _SECRET * ((4096 + _SECRET_LEN) // _SECRET_LEN + 2)


def _decrypt(s: bytes, item_id: int) -> bytes:
    n = len(s)
    if n == 0:
        return b""

    off = item_id % _SECRET_LEN
    key = _SECRET_TILED[off : off + n]
    return (int.from_bytes(s, "big") ^ int.from_bytes(key, "big")).to_bytes(n, "big")


@dataclass(slots=True)
class SubItem(Item):
    _start: int = 0
    _known_end: int = 0


def parse_known_fields(s: Buffer, version: int) -> SubItem:
    start = s.rpos
    item = SubItem.deserialize(s, version)
    item._start = start
    item._known_end = s.rpos

    return item


with open("items.dat", "rb") as f:
    version = struct.unpack("<H", f.read(2))[0]


_NONPRINTABLE = bytes(c for c in range(256) if not (0x20 <= c <= 0x7E or c in (0x09, 0x0A, 0x0D)))


def _is_printable_ascii(b: bytes, min_len: int = 0, max_len: int = 96, strict: bool = True, threshold: float = 0.9) -> bool:
    n = len(b)
    if not (min_len <= n <= max_len):
        return False

    if n == 0:
        return True

    printable = len(b.translate(None, _NONPRINTABLE))

    if strict:
        return printable == n

    return (printable / n) >= threshold


_ITEM_HDR_STRUCT = struct.Struct("<IHBB")
_U16_STRUCT = struct.Struct("<H")


def looks_like_item_start(data: bytes, offset: int, permissive: bool = False) -> tuple[bool, dict]:
    try:
        hdr_end = offset + 8
        if hdr_end + 2 > len(data):
            return False, {}
        cand_id, _flags, item_type, material = _ITEM_HDR_STRUCT.unpack_from(data, offset)
        pos = hdr_end

        name_min, name_max = (3, 96) if not permissive else (1, 160)
        tex_min, tex_max = (8, 64) if not permissive else (1, 128)

        name_len = _U16_STRUCT.unpack_from(data, pos)[0]
        if not (name_min <= name_len <= name_max) or pos + 2 + name_len > len(data):
            return False, {}
        pos += 2
        name_raw = data[pos : pos + name_len]
        pos += name_len
        name_dec = _decrypt(name_raw, cand_id)
        if not _is_printable_ascii(name_dec, min_len=name_min, max_len=name_max, strict=not permissive):
            return False, {}

        if pos + 2 > len(data):
            return False, {}
        tex_len = _U16_STRUCT.unpack_from(data, pos)[0]
        if not (tex_min <= tex_len <= tex_max) or pos + 2 + tex_len > len(data):
            return False, {}
        pos += 2
        tex_raw = data[pos : pos + tex_len]
        if not _is_printable_ascii(tex_raw, min_len=tex_min, max_len=tex_max, strict=not permissive):
            return False, {}

        return True, {"id": cand_id, "item_type": item_type, "material": material, "name": name_dec, "texture_file": tex_raw, "permissive": permissive}
    except (struct.error, IndexError):
        return False, {}


def find_next_item_offset(data: bytes, s: Buffer, known_end: int, version: int, window: int = 4096, lookahead: int = 1, items_remaining_after: int = 10**9) -> int | None:
    limit = min(len(data), known_end + window)

    for permissive in (False, True):
        for offset in range(known_end, limit):
            ok, _info = looks_like_item_start(data, offset, permissive=permissive)
            if not ok:
                continue
            if lookahead <= 0 or items_remaining_after <= 0:
                return offset - known_end

            s.rpos = offset
            try:
                known2 = parse_known_fields(s, version)
            except (struct.error, IndexError):
                continue
            next_gap = find_next_item_offset(data, s, known2._known_end, version, window=window, lookahead=lookahead - 1, items_remaining_after=items_remaining_after - 1)
            if next_gap is not None:
                return offset - known_end
    return None


@dataclass
class ScanResult:
    version: int
    count: int
    gaps: list[int]
    last_item_tail: int
    final_pos: int
    file_len: int
    items_meta: list[SubItem] = field(default_factory=list)
    data: bytes = b""

    @property
    def clean(self) -> bool:
        return self.final_pos == self.file_len


def _bootstrap_mode_gap(data: bytes, s: Buffer, count: int, parse_version: int, window: int, sample: int = 300) -> int | None:
    start_pos = s.rpos
    cursor = s.rpos
    gaps: list[int] = []
    n = min(sample, count - 1)
    for i in range(n):
        s.rpos = cursor
        known = parse_known_fields(s, parse_version)
        known_end = known._known_end
        gap = find_next_item_offset(data, s, known_end, parse_version, window=window, lookahead=0)
        if gap is None:
            break
        gaps.append(gap)
        cursor = known_end + gap

    s.rpos = start_pos
    if not gaps:
        return None

    return Counter(gaps).most_common(1)[0][0]


def scan_file(path: Path, schema_version_cap: int = version, window: int = 4096) -> ScanResult:
    data = path.read_bytes()
    s = Buffer(data)
    version = s.read_u16()
    count = s.read_u32()

    parse_version = min(version, schema_version_cap)

    mode_gap = _bootstrap_mode_gap(data, s, count, parse_version, window)

    gaps: list[int] = []
    items_meta: list[SubItem] = []
    cursor = s.rpos
    last_tail = 0

    for i in range(count):
        s.rpos = cursor
        known = parse_known_fields(s, parse_version)
        known_end = known._known_end
        items_meta.append(known)

        if i == count - 1:
            last_tail = len(data) - known_end
            cursor = len(data)
            break

        gap = None
        if mode_gap is not None and known_end + mode_gap <= len(data):
            ok, _ = looks_like_item_start(data, known_end + mode_gap)
            if ok:
                gap = mode_gap

        if gap is None:
            gap = find_next_item_offset(data, s, known_end, parse_version, window=window, items_remaining_after=count - i - 2)

        if gap is None:
            for retry_window in (window * 2, window * 4):
                gap = find_next_item_offset(data, s, known_end, parse_version, window=retry_window, items_remaining_after=count - i - 2)
                if gap is not None:
                    break

        if gap is None:
            break

        gaps.append(gap)
        cursor = known_end + gap

    return ScanResult(
        version=version,
        count=count,
        gaps=gaps,
        last_item_tail=last_tail,
        final_pos=cursor,
        file_len=len(data),
        items_meta=items_meta,
        data=data,
    )


def analyze_gaps(gaps: list[int]) -> str:
    counter = Counter(gaps)
    unique_gaps = set(gaps)

    if unique_gaps == {0}:
        return f"{DIM}No new bytes, schema already matches this file.{RESET}"

    if len(unique_gaps) == 1:
        gap = unique_gaps.pop()
        type_guess = {1: "u8", 2: "u16", 4: "u32/float", 8: "u64/double"}.get(gap, f"{gap} raw bytes")
        return f"{BOLD}Fixed-size diff:{RESET} +{gap}B/item (likely {type_guess})"

    return f"{BOLD}Variable-size diff{RESET}, gap sizes: {dict(sorted(counter.items()))}"


def _try_lpstr(tail: bytes, pos: int, item_id: int, decrypt: bool, permissive: bool) -> tuple[int, dict] | None:
    if pos + 2 > len(tail):
        return None

    ln = struct.unpack_from("<H", tail, pos)[0]
    if pos + 2 + ln > len(tail):
        return None

    raw = tail[pos + 2 : pos + 2 + ln]
    val = _decrypt(raw, item_id) if decrypt else raw
    if not _is_printable_ascii(val, min_len=0, max_len=4096, strict=not permissive, threshold=0.85):
        return None

    return pos + 2 + ln, {"len": ln, "raw": raw, "value": val, "decrypted": decrypt}


def _try_scalar(tail: bytes, pos: int, size: int) -> tuple[int, dict] | None:
    if pos + size > len(tail):
        return None
    raw = tail[pos : pos + size]
    return pos + size, {"raw": raw}


FIXED_SIZE_CANDIDATES = [1, 2, 3, 4, 6, 8, 9, 12, 16, 20, 24, 32]
MAX_DEPTH_CAP = 20
SAMPLE_SIZE = 200
REPORT_ACCEPT = 1.00
NODE_BUDGET_PER_ITEM = 4000


def _enumerate_full_parses(tail: bytes, item_id: int, max_depth: int, node_budget: int = NODE_BUDGET_PER_ITEM, max_paths: int = 6) -> list[list[dict]]:
    results: list[list[dict]] = []
    budget = [node_budget]

    def rec(pos: int, depth: int, path: list[dict]):
        if len(results) >= max_paths or budget[0] <= 0:
            return

        budget[0] -= 1
        if pos == len(tail):
            results.append(list(path))
            return

        if depth >= max_depth:
            return

        results_before = len(results)
        for decrypt in (True, False):
            r = _try_lpstr(tail, pos, item_id, decrypt, permissive=True)
            if r:
                newpos, info = r
                path.append({"type": "lpstr", "encrypted": decrypt, **info})
                rec(newpos, depth + 1, path)
                path.pop()
                if len(results) >= max_paths or budget[0] <= 0:
                    return

        remaining = len(tail) - pos
        for size in FIXED_SIZE_CANDIDATES:
            if size > remaining:
                continue

            r = _try_scalar(tail, pos, size)
            if r:
                newpos, info = r
                path.append({"type": "fixed", "size": size, **info})
                rec(newpos, depth + 1, path)
                path.pop()
                if len(results) >= max_paths or budget[0] <= 0:
                    return

        if len(results) == results_before and depth == max_depth - 1 and remaining > 0 and remaining not in FIXED_SIZE_CANDIDATES:
            r = _try_scalar(tail, pos, remaining)
            if r:
                newpos, info = r
                path.append({"type": "fixed", "size": remaining, **info})
                rec(newpos, depth + 1, path)
                path.pop()

    rec(0, 0, [])
    return results


def _shape_signature(path: list[dict]) -> tuple:
    sig = []
    for tok in path:
        if tok["type"] == "lpstr":
            sig.append(("lpstr", tok["encrypted"]))
        else:
            sig.append(("fixed", tok["size"]))

    return tuple(sig)


def _verify_shape(sig: tuple, items_meta: list[SubItem], gaps: list[int], data: bytes) -> dict:
    pairs = [(m, g) for m, g in zip(items_meta, gaps) if g > 0]
    total = len(pairs)
    hits = 0
    field_fixed_values: list[Counter] = [Counter() for tok in sig if tok[0] == "fixed"]
    field_lpstr_lens: list[list[int]] = [[] for tok in sig if tok[0] == "lpstr"]
    misses_sample = []

    for meta, g in pairs:
        known_end = meta._known_end
        tail = data[known_end : known_end + g]
        item_id = meta.id
        pos = 0
        ok = True
        fixed_idx = 0
        lpstr_idx = 0
        pending_fixed = []
        pending_lpstr = []
        for tok in sig:
            if tok[0] == "lpstr":
                r = _try_lpstr(tail, pos, item_id, tok[1], permissive=True)
                if not r:
                    ok = False
                    break
                pos, info = r
                pending_lpstr.append((lpstr_idx, info["len"]))
                lpstr_idx += 1
            else:
                size = tok[1]
                r = _try_scalar(tail, pos, size)
                if not r:
                    ok = False
                    break
                pos, info = r
                pending_fixed.append((fixed_idx, info["raw"]))
                fixed_idx += 1

        if ok and pos == len(tail):
            hits += 1
            for idx, raw in pending_fixed:
                field_fixed_values[idx][raw] += 1
            for idx, ln in pending_lpstr:
                field_lpstr_lens[idx].append(ln)
        else:
            if len(misses_sample) < 5:
                misses_sample.append((meta.id, g, tail))

    return {
        "sig": sig,
        "hits": hits,
        "total": total,
        "coverage": (hits / total) if total else 0.0,
        "field_fixed_values": field_fixed_values,
        "field_lpstr_lens": field_lpstr_lens,
        "misses_sample": misses_sample,
    }


def _describe_shape(v: dict) -> None:
    merged = _merge_shape_fields(v)
    for i, r in enumerate(merged, start=1):
        if r["kind"] == "lpstr":
            enc = "encrypted" if r["encrypted"] else "raw"
            lens = r["lens"]
            span = f"{min(lens)}-{max(lens)}B" if lens else "?"
            print(f"  {CYAN}field {i}{RESET}: string ({enc}), {span}")
        else:
            if r["is_const"]:
                print(f"  {CYAN}field {i}{RESET}: {r['size']}B constant {r['const_val']!r}")
            else:
                counter = r["counter"]
                total_seen = sum(counter.values())
                top_val, top_count = counter.most_common(1)[0]
                ratio = top_count / total_seen if total_seen else 0
                print(f"  {CYAN}field {i}{RESET}: {r['size']}B variable ({len(counter)} values, dominant {top_val!r} @ {ratio*100:.0f}%)")


def _merge_shape_fields(v: dict) -> list[dict]:
    resolved = []
    fixed_idx = 0
    lpstr_idx = 0
    for tok in v["sig"]:
        if tok[0] == "lpstr":
            lens = v["field_lpstr_lens"][lpstr_idx]
            lpstr_idx += 1
            resolved.append({"kind": "lpstr", "encrypted": tok[1], "lens": lens})
        else:
            size = tok[1]
            counter = v["field_fixed_values"][fixed_idx]
            fixed_idx += 1
            is_const = len(counter) == 1 and sum(counter.values()) > 0
            const_val = counter.most_common(1)[0][0] if counter else b""
            resolved.append({"kind": "fixed", "size": size, "counter": counter, "is_const": is_const, "const_val": const_val})

    merged = []
    for r in resolved:
        if r["kind"] == "fixed" and r["is_const"] and merged and merged[-1]["kind"] == "fixed" and merged[-1]["is_const"]:
            merged[-1]["size"] += r["size"]
            merged[-1]["const_val"] += r["const_val"]
        else:
            merged.append(dict(r))

    return merged


def _next_unk_index(start_after: int = 0) -> int:
    src = inspect.getsource(parse_known_fields)
    used = [int(m) for m in re.findall(r'"unk(\d+)"', src)]
    return max(used + [start_after]) + 1


def generate_patch_code(v: dict, new_version: int, start_after: int = 0) -> str:
    merged = _merge_shape_fields(v)
    next_idx = _next_unk_index(start_after)
    lines = [f"if version >= {new_version}:"]

    for f in merged:
        name = f"unk{next_idx}"
        next_idx += 1
        if f["kind"] == "lpstr":
            comment = ""
            if f["encrypted"]:
                comment = "  # id-XOR encrypted, decrypt with _decrypt(raw, item.id)"
            lens = f["lens"]
            if lens and max(lens) == 0:
                comment += ("  # " if not comment else " ") + "(always empty in sample, verify)"
            lines.append(f"    item.{name} = s.read_pascal_bytes(){comment}")
        else:
            size = f["size"]
            if f["is_const"]:
                const_comment = f"  # constant: {f['const_val']!r}"
            else:
                const_comment = "  # NOT constant, likely a per-item scalar (u8/u16/u32?)"
            lines.append(f"    item.{name} = s.read_bytes({size}){const_comment}")

    return "\n".join(lines)


def explore_and_weigh(data: bytes, items_meta: list[SubItem], gaps: list[int]) -> dict | None:
    unique_gaps = set(gaps)
    pairs_all = [(m, g) for m, g in zip(items_meta, gaps) if g > 0]

    if unique_gaps == {0} or not pairs_all:
        print(f"{DIM}No gaps to analyze.{RESET}")
        return None

    pairs_sorted = sorted(pairs_all, key=lambda mg: mg[1])
    if len(pairs_sorted) > SAMPLE_SIZE:
        step = len(pairs_sorted) / SAMPLE_SIZE
        sample = [pairs_sorted[int(i * step)] for i in range(SAMPLE_SIZE)]
    else:
        sample = pairs_sorted

    best_overall = None

    for depth in range(1, MAX_DEPTH_CAP + 1):
        shape_votes: Counter = Counter()
        for meta, g in sample:
            known_end = meta._known_end
            tail = data[known_end : known_end + g]
            paths = _enumerate_full_parses(tail, meta.id, max_depth=depth)
            seen_here = set()
            for p in paths:
                sig = _shape_signature(p)
                if sig in seen_here:
                    continue
                seen_here.add(sig)
                shape_votes[sig] += 1

        if not shape_votes:
            continue

        top_candidates = shape_votes.most_common(5)
        verified = [_verify_shape(sig, items_meta, gaps, data) for sig, _votes in top_candidates]
        verified.sort(key=lambda v: v["coverage"], reverse=True)
        best_at_depth = verified[0]

        if best_overall is None or best_at_depth["coverage"] > best_overall["coverage"]:
            best_overall = best_at_depth
            best_overall["depth"] = depth

        if best_at_depth["hits"] == best_at_depth["total"]:
            break

    if best_overall is None:
        print(f"{RED}No matching shape found{RESET} (searched to depth {MAX_DEPTH_CAP}). Raw samples:")
        for meta, g in pairs_all[:5]:
            tail = data[meta._known_end : meta._known_end + g]
            print(f"  id={meta.id:<6} gap={g:<4} tail={tail!r}")
        return None

    cov = best_overall["coverage"]
    cov_color = GREEN if cov == 1.0 else YELLOW
    print(
        f"{BOLD}Shape found{RESET} (depth {best_overall['depth']}, {len(best_overall['sig'])} field(s)): "
        f"{cov_color}{cov*100:.1f}% coverage{RESET} ({best_overall['hits']}/{best_overall['total']})"
    )
    if cov < REPORT_ACCEPT:
        print(f"{YELLOW}Not 100%, may be a conditional field or unsupported token type. Treat as a lead, not confirmed.{RESET}")

    _describe_shape(best_overall)

    if best_overall["misses_sample"]:
        print(f"{YELLOW}Unmatched examples:{RESET}")
        for iid, g, tail in best_overall["misses_sample"][:3]:
            print(f"  id={iid:<6} gap={g:<4} tail={tail!r}")

    return best_overall


def _peek_version(path: Path) -> int:
    with open(path, "rb") as f:
        raw = f.read(2)

    return struct.unpack("<H", raw)[0]


def run_pair(baseline: Path, target: Path, window: int, unk_start: int = 0) -> dict:
    log = io.StringIO()
    result = {
        "old_v": None,
        "new_v": None,
        "baseline": baseline.name,
        "target": target.name,
        "status": "ok",
        "baseline_clean": None,
        "target_clean": None,
        "boundaries_matched": 0,
        "boundaries_total": 0,
        "coverage": None,
        "fields": 0,
        "patch_code": None,
        "warnings": [],
        "log": "",
        "next_unk": unk_start,
    }

    with contextlib.redirect_stdout(log):
        base_scan = scan_file(baseline, window=window)
        result["old_v"] = base_scan.version
        result["baseline_clean"] = base_scan.clean
        if set(base_scan.gaps) not in ({0}, set()):
            msg = "anchor logic found non-zero gaps on baseline (unexpected)"
            print(f"{RED}! {msg}{RESET}")
            result["warnings"].append(msg)

        target_scan = scan_file(target, schema_version_cap=base_scan.version, window=window)
        result["new_v"] = target_scan.version
        result["target_clean"] = target_scan.clean
        result["boundaries_total"] = target_scan.count - 1
        result["boundaries_matched"] = len(target_scan.gaps)

        print(
            f"{BOLD}v{base_scan.version} -> v{target_scan.version}{RESET}  "
            f"boundaries {len(target_scan.gaps)}/{target_scan.count - 1}" + ("" if target_scan.clean else f" {YELLOW}(lost anchor early){RESET}")
        )

        if not target_scan.clean:
            msg = f"only matched {len(target_scan.gaps)}/{target_scan.count - 1} boundaries (try increasing --window)"
            result["warnings"].append(msg)

        if not target_scan.gaps:
            result["status"] = "no_boundaries"
            result["warnings"].append("no item boundaries could be analyzed")
            print(f"{RED}No boundaries analyzed.{RESET}")
            result["log"] = log.getvalue()
            return result

        print(analyze_gaps(target_scan.gaps))
        best_shape = explore_and_weigh(target_scan.data, target_scan.items_meta, target_scan.gaps)

        new_v = target_scan.version
        if best_shape is not None:
            patch = generate_patch_code(best_shape, new_v, start_after=unk_start)
            result["coverage"] = best_shape["coverage"]
            result["fields"] = len(best_shape["sig"])
            result["patch_code"] = patch
            used = [int(m) for m in re.findall(r"unk(\d+)", patch)]
            result["next_unk"] = max(used, default=unk_start) + 1 if used else unk_start
            if best_shape["coverage"] < REPORT_ACCEPT:
                warn = f"only {best_shape['coverage']*100:.1f}% matched, verify before trusting"
                result["warnings"].append(warn)
                result["status"] = "low_coverage"
            print(f"\n{BOLD}Patch:{RESET}\n{patch}")
        else:
            result["status"] = "no_shape_found"
            result["warnings"].append("no consistent shape found")

    result["log"] = log.getvalue()
    return result


def print_summary(results: list[dict]) -> None:
    print(f"\n{BOLD}SUMMARY{RESET} ({len(results)} step(s))")

    status_style = {
        "ok": (GREEN, "OK"),
        "low_coverage": (YELLOW, "PARTIAL"),
        "no_shape_found": (RED, "NO SHAPE"),
        "no_boundaries": (RED, "FAILED"),
    }

    for r in results:
        color, label = status_style.get(r["status"], (RESET, r["status"]))
        print(f"\n{color}[{label}]{RESET} v{r['old_v']} -> v{r['new_v']}  ({r['baseline']} -> {r['target']})")

        if r["status"] == "no_boundaries":
            for w in r["warnings"]:
                print(f"  {RED}!{RESET} {w}")
            continue

        matched, total = r["boundaries_matched"], r["boundaries_total"]
        anchor_note = "" if r["target_clean"] else f" {YELLOW}(anchor lost early){RESET}"
        print(f"  boundaries: {matched}/{total}{anchor_note}")
        if r["coverage"] is not None:
            cov_color = GREEN if r["coverage"] == 1.0 else YELLOW
            print(f"  shape: {r['fields']} field(s), {cov_color}{r['coverage']*100:.1f}% coverage{RESET}")
        for w in r["warnings"]:
            print(f"  {YELLOW}!{RESET} {w}")
        if r["patch_code"]:
            print(f"  {DIM}patch:{RESET}")
            for line in r["patch_code"].splitlines():
                print(f"    {line}")

    ok_count = sum(1 for r in results if r["status"] == "ok")
    print(f"\n{ok_count}/{len(results)} step(s) fully resolved.")
    problems = [r for r in results if r["status"] != "ok"]
    if problems:
        print(f"{YELLOW}Needs attention:{RESET}")
        for r in problems:
            _, label = status_style.get(r["status"], (RESET, r["status"]))
            print(f"  - v{r['old_v']} -> v{r['new_v']}: {label}")

    patched = [r for r in results if r["patch_code"]]
    if patched:
        oldest, newest = results[0]["old_v"], results[-1]["new_v"]
        print(f"\n{BOLD}COMBINED PATCH{RESET} (v{oldest} -> v{newest})")
        for r in patched:
            for line in r["patch_code"].splitlines():
                print(line)
        if len(patched) < len(results):
            print(f"{YELLOW}Note: step(s) with no shape found are excluded above.{RESET}")


_ITEMS_DAT_CANDIDATES: list[Path] = [
    get_home() / "AppData/Local/Growtopia/cache/items.dat",
    Path(os.getenv("ITEMS", "items.dat")),
    setting.appdir / "resources/items.dat",
    setting.gt_path / "cache/items.dat",
]


def get_latest_item_dat() -> Path:
    for path in _ITEMS_DAT_CANDIDATES:
        if not path.is_file() or path.stat().st_size == 0:
            continue

        return path

    raise FileNotFoundError("no valid items.dat found. checked: " + ", ".join(str(p) for p in _ITEMS_DAT_CANDIDATES))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", type=Path, nargs="*")
    ap.add_argument("--window", type=int, default=8192, help="Max bytes to scan ahead for the next item anchor (auto-doubled up to 4x on misses)")
    ap.add_argument("--verbose", action="store_true", help="Also print the full step-by-step narration for every version pair, not just the final summary")
    args = ap.parse_args()

    if len(args.files) < 2:
        args.files = [
            Path("items.dat"),
            get_latest_item_dat(),
        ]

    by_version: dict[int, Path] = {}
    for p in args.files:
        v = _peek_version(p)
        if v in by_version:
            print(f"{DIM}Skipping {p.name} (duplicate version {v}).{RESET}")
            continue
        by_version[v] = p

    unique_versions = sorted(by_version)
    if len(unique_versions) < 2:
        print(f"Only {len(unique_versions)} unique version(s) found, nothing to diff.")
        return

    print(f"{BOLD}Versions:{RESET} {unique_versions}")

    results = []
    unk_next = 0
    for old_v, new_v in zip(unique_versions, unique_versions[1:]):
        baseline, target = by_version[old_v], by_version[new_v]
        r = run_pair(baseline, target, args.window, unk_start=unk_next)
        results.append(r)
        unk_next = r["next_unk"]
        if args.verbose:
            print(f"\n{DIM}--- v{old_v} -> v{new_v} ---{RESET}")
            print(r["log"])

    print_summary(results)


if __name__ == "__main__":
    main()
