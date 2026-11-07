#!/usr/bin/env python3
"""Dump IDA metadata (types, data section, strings, names, raw bytes).

Run this **inside IDA** with the target IDB open:

    File -> Script file...  (Alt+F7)  and select this file
or in IDA's Python console:

    exec(open(r"C:\\Users\\andra\\ida_export\\export_ida_data.py").read())

Outputs land in OUT_DIR (default ``C:\\Users\\andra\\ida_export\\out``):

    segments.json    segment table (name/class/start/end/size/perm)
    items.jsonl      every item head (code + data) with name/type/comments
    names.jsonl      every name (address -> name)
    strings.jsonl    every string literal
    types.jsonl      every local type (name, declaration, kind)
    types.h          the same declarations as a C header
    imports.json     imports with IAT addresses
    entries.json     entry points
    raw/<nn>_<seg>.bin + raw/index.json    raw bytes per segment
    summary.json, run.log

The script is read-only: it never modifies the database.
"""

from __future__ import annotations

import json
import os
import time
import traceback

# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------

OUT_DIR = r"C:\Users\andra\ida_export\out"

MAX_INLINE_BYTES = 256  # embed full bytes_hex up to this size per item
PREVIEW_BYTES = 32      # bytes_hex preview for larger items
RAW_CHUNK = 1 << 20     # 1 MB chunks when dumping segment bytes

# ---------------------------------------------------------------------------
# IDA imports (kept in one place so failures are easy to report)
# ---------------------------------------------------------------------------

import idaapi  # noqa: E402
import idautils  # noqa: E402
import idc  # noqa: E402

try:
    import ida_bytes
except ImportError:  # pragma: no cover
    ida_bytes = None
try:
    import ida_segment
except ImportError:  # pragma: no cover
    ida_segment = None
try:
    import ida_name
except ImportError:  # pragma: no cover
    ida_name = None
try:
    import ida_typeinf
except ImportError:  # pragma: no cover
    ida_typeinf = None
try:
    import ida_nalt
except ImportError:  # pragma: no cover
    ida_nalt = None

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

log_fh = None


def log(msg: str) -> None:
    global log_fh
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line)
    if log_fh is None:
        try:
            os.makedirs(OUT_DIR, exist_ok=True)
            log_fh = open(os.path.join(OUT_DIR, "run.log"), "w", encoding="utf-8")
        except OSError:
            log_fh = False  # type: ignore[assignment]
    if log_fh:
        try:
            log_fh.write(line + "\n")
            log_fh.flush()
        except OSError:
            pass


def _first_call(*candidates):
    """Call the first available function, returning its result (or None)."""
    for fn in candidates:
        if fn is None:
            continue
        try:
            return fn()
        except Exception:
            continue
    return None


def get_full_flags(ea: int) -> int:
    if ida_bytes is not None:
        try:
            return ida_bytes.get_full_flags(ea)
        except Exception:
            pass
    try:
        return idc.get_full_flags(ea)
    except Exception:
        return 0


def get_item_size(ea: int) -> int:
    if ida_bytes is not None:
        try:
            return ida_bytes.get_item_size(ea)
        except Exception:
            pass
    try:
        return idc.get_item_size(ea)
    except Exception:
        return 0


def get_name(ea: int) -> str:
    for holder, attr in ((ida_name, "get_name"), (idc, "get_name")):
        fn = getattr(holder, attr, None) if holder is not None else None
        if fn is None:
            continue
        try:
            name = fn(ea)
            if name:
                return str(name)
        except Exception:
            continue
    return ""


def get_type(ea: int) -> str:
    for holder, attr in ((ida_bytes, "get_type"), (idc, "get_type")):
        fn = getattr(holder, attr, None) if holder is not None else None
        if fn is None:
            continue
        try:
            t = fn(ea)
            if t:
                return str(t)
        except Exception:
            continue
    return ""


def get_cmt(ea: int, repeatable: bool) -> str:
    if ida_bytes is not None:
        try:
            c = ida_bytes.get_cmt(ea, repeatable)
            if c:
                return str(c)
        except Exception:
            pass
    try:
        c = idc.get_cmt(ea, repeatable)
        if c:
            return str(c)
    except Exception:
        pass
    return ""


def read_bytes(ea: int, size: int):
    for holder, attr in ((ida_bytes, "get_bytes"), (idc, "get_bytes")):
        fn = getattr(holder, attr, None) if holder is not None else None
        if fn is None:
            continue
        try:
            data = fn(ea, size)
            if data is not None:
                return bytes(data)
        except Exception:
            continue
    return None


def is_code(flags: int) -> bool:
    if ida_bytes is not None:
        try:
            return bool(ida_bytes.is_code(flags))
        except Exception:
            pass
    try:
        return bool(idc.is_code(flags))
    except Exception:
        return False


def is_head(flags: int) -> bool:
    if ida_bytes is not None:
        try:
            return bool(ida_bytes.is_head(flags))
        except Exception:
            pass
    try:
        return bool(idc.is_head(flags))
    except Exception:
        return False


def is_strlit(flags: int) -> bool:
    if ida_bytes is not None:
        try:
            return bool(ida_bytes.is_strlit(flags))
        except Exception:
            pass
    try:
        return bool(idc.is_strlit(flags))
    except Exception:
        return False


def hex_preview(data, limit: int) -> str:
    if not data:
        return ""
    return " ".join(f"{b:02x}" for b in data[:limit])


def idb_path() -> str:
    try:
        return str(idc.get_idb_path())
    except Exception:
        pass
    if ida_nalt is not None:
        try:
            return str(ida_nalt.get_path(ida_nalt.PATH_TYPE_IDB) or "")
        except Exception:
            pass
    return "?"


def write_json(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)


def write_jsonl(path: str, rows) -> int:
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


# ---------------------------------------------------------------------------
# segments
# ---------------------------------------------------------------------------


def segment_info(ea: int):
    """Return (start, end, name, seg_class, perm) for the segment at ea."""
    seg = None
    if ida_segment is not None:
        try:
            seg = ida_segment.getseg(ea)
        except Exception:
            seg = None
    if seg is not None:
        start = int(getattr(seg, "start_ea", ea))
        end = int(getattr(seg, "end_ea", ea))
        name = str(getattr(seg, "name", "") or "")
        perm = int(getattr(seg, "perm", 0) or 0)
        seg_class = ""
        try:
            if ida_segment is not None:
                seg_class = str(ida_segment.get_segm_class(seg) or "")
        except Exception:
            pass
        return start, end, name, seg_class, perm
    # fallback to idc
    try:
        start = int(idc.get_segm_start(ea))
        end = int(idc.get_segm_end(ea))
        name = str(idc.get_segm_name(ea) or "")
        return start, end, name, "", 0
    except Exception:
        return ea, ea, "", "", 0


def export_segments():
    segs = []
    seg_list = []
    for start in idautils.Segments():
        s, e, name, seg_class, perm = segment_info(start)
        seg_list.append((s, e, name, seg_class, perm))
    seg_list.sort()
    for s, e, name, seg_class, perm in seg_list:
        segs.append(
            {
                "name": name,
                "class": seg_class,
                "start": hex(s),
                "end": hex(e),
                "size": e - s,
                "perm": perm,
            }
        )
    write_json(os.path.join(OUT_DIR, "segments.json"), segs)
    log(f"segments: {len(segs)} -> segments.json")
    return seg_list


# ---------------------------------------------------------------------------
# items (code + data)
# ---------------------------------------------------------------------------


def export_items(seg_list):
    path = os.path.join(OUT_DIR, "items.jsonl")
    count = 0
    code_count = 0
    data_count = 0
    with open(path, "w", encoding="utf-8") as fh:
        for s, e, seg_name, _cls, _perm in seg_list:
            for ea in idautils.Heads(s, e):
                if not is_head(get_full_flags(ea)):
                    continue
                flags = get_full_flags(ea)
                size = get_item_size(ea)
                if size <= 0:
                    continue
                code = is_code(flags)
                row = {
                    "addr": hex(ea),
                    "end": hex(ea + size),
                    "size": size,
                    "seg": seg_name,
                    "code": code,
                    "name": get_name(ea),
                    "type": get_type(ea),
                    "cmt": get_cmt(ea, False),
                    "rcmt": get_cmt(ea, True),
                }
                if not code:
                    # data items get bytes; raw/ has the full segment dump
                    take = min(size, MAX_INLINE_BYTES)
                    data = read_bytes(ea, take)
                    row["bytes_hex"] = hex_preview(data, take)
                    if size > MAX_INLINE_BYTES:
                        row["preview_hex"] = hex_preview(data, PREVIEW_BYTES)
                    if is_strlit(flags):
                        slen = -1
                        stype = getattr(idc, "STRTYPE_C", 0)
                        contents = None
                        if ida_bytes is not None:
                            try:
                                contents = ida_bytes.get_strlit_contents(ea, slen, stype)
                            except Exception:
                                contents = None
                        if contents is None:
                            try:
                                contents = idc.get_strlit_contents(ea, slen, stype)
                            except Exception:
                                contents = None
                        if contents is not None:
                            if isinstance(contents, bytes):
                                try:
                                    contents = contents.decode("utf-8", "replace")
                                except Exception:
                                    contents = contents.decode("latin-1", "replace")
                            row["string"] = str(contents)
                    data_count += 1
                else:
                    code_count += 1
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                count += 1
    log(f"items: {count} ({code_count} code, {data_count} data) -> items.jsonl")
    return count


# ---------------------------------------------------------------------------
# names / strings
# ---------------------------------------------------------------------------


def export_names():
    path = os.path.join(OUT_DIR, "names.jsonl")
    count = 0
    with open(path, "w", encoding="utf-8") as fh:
        for ea, name in idautils.Names():
            if not name:
                continue
            fh.write(json.dumps({"addr": hex(ea), "name": str(name)}, ensure_ascii=False) + "\n")
            count += 1
    log(f"names: {count} -> names.jsonl")
    return count


def export_strings():
    path = os.path.join(OUT_DIR, "strings.jsonl")
    count = 0
    try:
        strings = idautils.Strings()
    except Exception as exc:
        log(f"strings: failed to enumerate: {exc}")
        return 0
    with open(path, "w", encoding="utf-8") as fh:
        for s in strings:
            try:
                ea = int(s.ea)
                value = s.str
                if isinstance(value, bytes):
                    value = value.decode("utf-8", "replace")
                fh.write(
                    json.dumps(
                        {
                            "addr": hex(ea),
                            "length": int(getattr(s, "length", 0) or 0),
                            "type": int(getattr(s, "type", 0) or 0),
                            "value": str(value),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                count += 1
            except Exception:
                continue
    log(f"strings: {count} -> strings.jsonl")
    return count


# ---------------------------------------------------------------------------
# types
# ---------------------------------------------------------------------------


def export_types():
    if ida_typeinf is None:
        log("types: ida_typeinf unavailable, skipped")
        return 0
    jsonl_path = os.path.join(OUT_DIR, "types.jsonl")
    header_path = os.path.join(OUT_DIR, "types.h")
    try:
        til = ida_typeinf.get_idati()
    except Exception as exc:
        log(f"types: get_idati failed: {exc}")
        return 0
    limit = 0
    try:
        limit = int(til.get_ordinal_count())
    except Exception:
        try:
            limit = int(ida_typeinf.get_ordinal_limit(til))
        except Exception:
            limit = 0
    pr_multi = getattr(ida_typeinf, "PRTYPE_MULTI", 0)
    pr_type = getattr(ida_typeinf, "PRTYPE_TYPE", 0)
    pr_semi = getattr(ida_typeinf, "PRTYPE_SEMI", 0)
    count = 0
    errors = 0
    with open(jsonl_path, "w", encoding="utf-8") as fj, open(header_path, "w", encoding="utf-8") as fh:
        fh.write("/* IDA local types dump */\n\n")
        for ordinal in range(1, limit):
            try:
                tif = ida_typeinf.tinfo_t()
                if not tif.get_numbered_type(til, ordinal):
                    continue
                name = ""
                try:
                    name = str(tif.get_type_name() or "")
                except Exception:
                    name = ""
                decl = ""
                try:
                    decl = str(tif._print(None, pr_multi | pr_type | pr_semi) or "")
                except Exception:
                    decl = ""
                decl = decl.replace("\x01", " ").strip()
                kind = "other"
                for check, label in (
                    ("is_udt", "struct"),
                    ("is_enum", "enum"),
                    ("is_func", "func"),
                    ("is_typedef", "typedef"),
                    ("is_array", "array"),
                    ("is_ptr", "ptr"),
                ):
                    try:
                        if getattr(tif, check)():
                            kind = label
                            break
                    except Exception:
                        continue
                fj.write(
                    json.dumps(
                        {"ordinal": ordinal, "name": name, "kind": kind, "decl": decl},
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                if decl:
                    fh.write(f"/* {name or 'type_%d' % ordinal} ({kind}) */\n{decl}\n\n")
                count += 1
            except Exception:
                errors += 1
                continue
    log(f"types: {count} exported ({errors} skipped) -> types.jsonl / types.h")
    return count


# ---------------------------------------------------------------------------
# imports / entries
# ---------------------------------------------------------------------------


def export_imports():
    if ida_nalt is None:
        log("imports: ida_nalt unavailable, skipped")
        return 0
    rows = []
    try:
        nmod = int(ida_nalt.get_import_module_qty())
    except Exception as exc:
        log(f"imports: get_import_module_qty failed: {exc}")
        return 0
    for i in range(nmod):
        module = ""
        try:
            module = str(ida_nalt.get_import_module_name(i) or "")
        except Exception:
            module = ""

        def cb(ea, name, ordinal, module=module):
            rows.append(
                {
                    "addr": hex(int(ea)),
                    "name": str(name or ""),
                    "ordinal": int(ordinal or 0),
                    "module": module,
                }
            )
            return True

        try:
            ida_nalt.enum_import_names(i, cb)
        except Exception as exc:
            log(f"imports: module {i} ({module}) failed: {exc}")
    write_json(os.path.join(OUT_DIR, "imports.json"), rows)
    log(f"imports: {len(rows)} -> imports.json")
    return len(rows)


def export_entries():
    rows = []
    try:
        for entry in idautils.Entries():
            # (index, ordinal, ea, name)
            idx, ordinal, ea, name = entry
            rows.append(
                {
                    "index": int(idx),
                    "ordinal": int(ordinal),
                    "addr": hex(int(ea)),
                    "name": str(name or ""),
                }
            )
    except Exception as exc:
        log(f"entries: enumeration failed: {exc}")
    write_json(os.path.join(OUT_DIR, "entries.json"), rows)
    log(f"entries: {len(rows)} -> entries.json")
    return len(rows)


# ---------------------------------------------------------------------------
# raw segment bytes
# ---------------------------------------------------------------------------


def export_raw(seg_list):
    raw_dir = os.path.join(OUT_DIR, "raw")
    os.makedirs(raw_dir, exist_ok=True)
    index = []
    for i, (s, e, name, seg_class, _perm) in enumerate(seg_list):
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name) or f"seg{i}"
        fname = f"{i:02d}_{safe}.bin"
        fpath = os.path.join(raw_dir, fname)
        written = 0
        try:
            with open(fpath, "wb") as fh:
                ea = s
                empty = True
                while ea < e:
                    chunk = read_bytes(ea, min(RAW_CHUNK, e - ea))
                    if not chunk:
                        break
                    fh.write(chunk)
                    written += len(chunk)
                    empty = False
                    ea += len(chunk)
            if written == 0:
                try:
                    os.remove(fpath)
                except OSError:
                    pass
                fname = ""
        except OSError as exc:
            log(f"raw: {name} failed: {exc}")
            fname = ""
        index.append(
            {
                "seg": name,
                "class": seg_class,
                "start": hex(s),
                "end": hex(e),
                "size": e - s,
                "file": fname,
                "written": written,
            }
        )
    write_json(os.path.join(raw_dir, "index.json"), index)
    total = sum(x["written"] for x in index)
    log(f"raw: {total} bytes across {sum(1 for x in index if x['file'])} segments -> raw/")
    return total


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> None:
    started = time.time()
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
    except OSError as exc:
        print(f"FATAL: cannot create {OUT_DIR}: {exc}")
        return
    log(f"export start; idb={idb_path()}")
    results = {}
    seg_list = export_segments()
    try:
        results["items"] = export_items(seg_list)
    except Exception:
        log("items: FAILED\n" + traceback.format_exc())
    try:
        results["names"] = export_names()
    except Exception:
        log("names: FAILED\n" + traceback.format_exc())
    try:
        results["strings"] = export_strings()
    except Exception:
        log("strings: FAILED\n" + traceback.format_exc())
    try:
        results["types"] = export_types()
    except Exception:
        log("types: FAILED\n" + traceback.format_exc())
    try:
        results["imports"] = export_imports()
    except Exception:
        log("imports: FAILED\n" + traceback.format_exc())
    try:
        results["entries"] = export_entries()
    except Exception:
        log("entries: FAILED\n" + traceback.format_exc())
    try:
        results["raw_bytes"] = export_raw(seg_list)
    except Exception:
        log("raw: FAILED\n" + traceback.format_exc())
    write_json(
        os.path.join(OUT_DIR, "summary.json"),
        {
            "idb": idb_path(),
            "out_dir": OUT_DIR,
            "elapsed_s": round(time.time() - started, 1),
            "segments": len(seg_list),
            **results,
        },
    )
    log(f"done in {time.time() - started:.1f}s -> {OUT_DIR}")


if __name__ == "__main__":
    main()
