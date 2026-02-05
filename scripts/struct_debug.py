import click
import struct, re

from gtools.core.growtopia.packet import TankPacket


@click.command
@click.argument("data")
@click.option("-t", "--tank", is_flag=True)
def struct_debug(data: str, tank: bool) -> None:
    buf = data.encode().decode("unicode_escape").encode("latin1")
    if not tank:
        buf = buf[4:]
    pretty_struct_colored_bytes(TankPacket._Struct, buf)


_PALETTE = [
    "\x1b[38;5;82m",  # green
    "\x1b[38;5;201m",  # pink
    "\x1b[38;5;45m",  # cyan
    "\x1b[38;5;208m",  # orange
    "\x1b[38;5;226m",  # yellow
    "\x1b[38;5;75m",  # blue
    "\x1b[38;5;160m",  # red
    "\x1b[2m",  # dim
]
_RESET = "\x1b[0m"

_regex = re.compile(r"(\d*)([xcbB\?\-hHiIlLqQnNfdspP])")


def _parse_format(fmt: str):
    prefix = fmt[0] if fmt and fmt[0] in "@=<>!" else ""
    rest = fmt[1:] if prefix else fmt
    tokens = []
    for m in _regex.finditer(rest):
        count_str, ch = m.groups()
        count = int(count_str) if count_str else 1
        tokens.append((count, ch))
    items = []
    for count, ch in tokens:
        if ch in ("s", "p"):
            token_fmt = f"{count}{ch}"
            size = struct.calcsize((prefix + token_fmt) if prefix else token_fmt)
            items.append((token_fmt, ch, size))
        elif ch == "x":
            for i in range(count):
                items.append(("x", "x", 1))
        else:
            single_fmt = ch
            per_size = struct.calcsize((prefix + single_fmt) if prefix else single_fmt)
            for i in range(count):
                items.append((single_fmt, ch, per_size))
    return prefix, items


def _is_printable(b: int):
    return 32 <= b < 127


def _byte_piece_repr(b: int):
    if b == 0x5C:
        return "\\\\"
    if b == 0x27:
        return "\\'"
    if _is_printable(b):
        return chr(b)
    return f"\\x{b:02x}"


def pretty_struct_colored_bytes(s: struct.Struct, data: bytes, *, color: bool = True, show_legend: bool = True):
    prefix, items = _parse_format(s.format)
    segments = []
    offset = 0
    for idx, (token_fmt, typ, size) in enumerate(items):
        seg = {"idx": idx, "fmt": token_fmt, "type": typ, "size": size, "start": offset, "label": token_fmt}
        segments.append(seg)
        offset += size

    for i, seg in enumerate(segments):
        seg["color"] = _PALETTE[i % len(_PALETTE)] if color else ""
        seg["reset"] = _RESET if color else ""

    total_len = len(data)
    seg_index_of_byte: list[int | None] = [None] * total_len
    for si, seg in enumerate(segments):
        start = seg["start"]
        end = start + seg["size"]
        for i in range(start, min(end, total_len)):
            seg_index_of_byte[i] = si

    i = 0
    inner = ""
    while i < total_len:
        si = seg_index_of_byte[i]

        if si is None:
            piece = _byte_piece_repr(data[i])
            inner += piece
            i += 1
            continue

        j = i
        while j < total_len and seg_index_of_byte[j] == si:
            j += 1

        pieces = [_byte_piece_repr(b) for b in data[i:j]]
        seg = segments[si]
        if color:
            inner += seg["color"]
        inner += "".join(pieces)
        if color:
            inner += seg["reset"]
        i = j

    final = "b'" + inner + "'"
    print(final)
    print()

    if show_legend:
        print("legend:")
        used_types = {}
        for seg in segments:
            used_types.setdefault(seg["type"], []).append(seg)
        for t, segs in used_types.items():
            color_sample = segs[0]["color"] if color else ""
            reset = _RESET if color else ""
            print(f"  {color_sample}{t}{reset} -> {len(segs)} segment(s)")
        print()

    rows = []
    for seg in segments:
        st = seg["start"]
        sz = seg["size"]
        typ = seg["type"]
        token_fmt = seg["fmt"]

        seg_bytes = data[st : st + sz]
        hex_bytes = " ".join(f"{b:02X}" for b in seg_bytes)
        ascii_repr = "".join(chr(b) if _is_printable(b) else "." for b in seg_bytes)

        if len(seg_bytes) < sz:
            value = "<truncated>"
        else:
            try:
                if typ == "x":
                    value = "<pad>"
                else:
                    val = struct.unpack_from((prefix + token_fmt) if prefix else token_fmt, data, st)
                    if isinstance(val, tuple) and len(val) == 1:
                        val = val[0]
                    if isinstance(val, (bytes, bytearray)):
                        if all(_is_printable(b) for b in val):
                            value = repr(val.decode("ascii"))
                        else:
                            value = repr(val)
                    else:
                        value = repr(val)
            except Exception as e:
                value = f"<error: {e!r}>"

        data_plain = repr(seg_bytes)
        data_colored = f"{seg['color']}{data_plain}{seg['reset']}" if color else data_plain

        rows.append(
            {
                "offset": f"{st:04d}-{st+sz:04d}",
                "data_plain": data_plain,
                "data_colored": data_colored,
                "type": typ,
                "fmt": token_fmt,
                "value": value,
                "hex": hex_bytes,
                "ascii": ascii_repr,
            }
        )

    def truncate(s: str, mx: int):
        return s if len(s) <= mx else s[: mx - 3] + "..."

    max_value_w = 40
    max_data_w = 24
    max_hex_w = 48
    max_ascii_w = 24

    widths = {
        "offset": max(len("offset"), max((len(r["offset"]) for r in rows), default=0)),
        "data": max(len("data"), min(max((len(r["data_plain"]) for r in rows), default=0), max_data_w)),
        "type": max(len("type"), max((len(r["type"]) for r in rows), default=0)),
        "fmt": max(len("fmt"), max((len(r["fmt"]) for r in rows), default=0)),
        "value": max(len("value"), min(max((len(r["value"]) for r in rows), default=0), max_value_w)),
        "hex": max(len("hex"), min(max((len(r["hex"]) for r in rows), default=0), max_hex_w)),
        "ascii": max(len("ascii"), min(max((len(r["ascii"]) for r in rows), default=0), max_ascii_w)),
    }

    header = (
        f"  {'offset'.ljust(widths['offset'])}  "
        f"{'data'.ljust(widths['data'])}  "
        f"{'type'.ljust(widths['type'])}  "
        f"{'fmt'.ljust(widths['fmt'])}  "
        f"{'value'.ljust(widths['value'])}  "
        f"{'hex'.ljust(widths['hex'])}  "
        f"{'ascii'.ljust(widths['ascii'])}"
    )
    print("segments:")
    print(header)
    print("-" * len(header))

    for r in rows:
        value_display = truncate(r["value"], widths["value"])
        data_display = truncate(r["data_plain"], widths["data"])
        hex_display = truncate(r["hex"], widths["hex"])
        ascii_display = truncate(r["ascii"], widths["ascii"])

        if color:
            data_cell = r["data_colored"].ljust(widths["data"] + (len(r["data_colored"]) - len(r["data_plain"])))
        else:
            data_cell = data_display.ljust(widths["data"])

        line = (
            f"  {r['offset'].ljust(widths['offset'])}  "
            f"{data_cell}  "
            f"{r['type'].ljust(widths['type'])}  "
            f"{r['fmt'].ljust(widths['fmt'])}  "
            f"{value_display.ljust(widths['value'])}  "
            f"{hex_display.ljust(widths['hex'])}  "
            f"{ascii_display.ljust(widths['ascii'])}"
        )
        print(line)

    parsed = sum(seg["size"] for seg in segments)
    print()
    print(f"total bytes available: {total_len}, struct expects: {parsed}, remaining: {max(0, total_len - parsed)}")
