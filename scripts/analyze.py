import re
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import IO
import click


@click.command()
def analyze() -> None:
    # TODO: fk this, is shouldve just dump the raw traffic instead of parsing the logs
    def analyze_file(file: Path, out: IO[str]) -> None:
        __pattern = re.compile(
            r"""
            (?P<name>\b[a-zA-Z_]\w*)(?==) |
            (?P<num>(?<!\w)[+-]?\d+(?:\.\d+)?\b) |
            (?P<str>(?<=\=)[^|,=\s][^|,]*)(?=[|,]|$) |
            (?P<pipe>\|) |
            (?P<comma>,) |
            (?P<client>\bclient\b) |
            (?P<server>\bserver\b)
            """,
            re.VERBOSE,
        )

        def highlight(s: str) -> str:
            def repl(m):
                if m.group("name"):
                    return f"\x1b[38;2;90;115;115m{m.group(0)}\x1b[0m"

                if m.group("num"):
                    return f"\x1b[38;2;255;200;120m{m.group(0)}\x1b[0m"

                if m.group("str"):
                    return f"\x1b[38;2;135;175;175m{m.group(0)}\x1b[0m"

                if m.group("pipe"):
                    return f"\x1b[38;2;100;100;100m|\x1b[0m"

                if m.group("comma"):
                    return f"\x1b[38;2;130;130;130m,\x1b[0m"

                if m.group("client"):
                    return f"\x1b[38;2;220;90;90mclient\x1b[0m"

                if m.group("server"):
                    return f"\x1b[38;2;90;220;120mserver\x1b[0m"

                return m.group(0)

            return __pattern.sub(repl, s)

        lines = file.read_text().splitlines()
        packets = []
        patt = r".*proxy proxy\.py.* \[T\+([\d\.]*)] from gt (server|client)"

        for i, line in enumerate(lines):
            match = re.findall(patt, line)
            if not match:
                continue

            next_index = None

            for j in range(i + 1, len(lines)):
                if re.findall(patt, lines[j]):
                    next_index = j
                    break

            if next_index is not None:
                packets.append((match[0][0], lines[i:next_index]))
            else:
                packets.append((match[0][0], lines[i:]))

        def find_index[T](iterable: list[T], predicate: Callable[[T], bool]) -> int | None:
            for i, item in enumerate(iterable):
                if predicate(item):
                    return i

        ref: list[tuple[str, list[str], int, str]] = []
        abs_time = 0

        for pkt_num, (time, pkt) in enumerate(packets):
            src = re.findall(r"from gt (server|client)", pkt[0])[0]
            pkt_repr_start = find_index(pkt, lambda x: "packet=NetPacket" in x)
            net_type = re.findall(r".*NetPacket\[(.*)\]", pkt[pkt_repr_start])[0]  # pyright: ignore
            pkt_repr_end = find_index(pkt, lambda x: "from=" in x)

            if pkt_repr_start and pkt_repr_end:
                pkt_repr = "".join(pkt[pkt_repr_start : pkt_repr_end + 1])
                keys = [
                    "type",
                    "object_type",
                    "jump_count",
                    "animation_type",
                    "net_id",
                    "target_net_id",
                    "flags",
                    "float_var",
                    "value",
                    "vector_x",
                    "vector_y",
                    "vector_x2",
                    "vector_y2",
                    "particle_rotation",
                    "int_x",
                    "int_y",
                    "extended_len",
                    "extended_data",
                ]
                pattern = rf"({'|'.join(map(re.escape, keys))})=([^,]*),"
                values = re.findall(pattern, pkt_repr)
                for i in range(len(values) - 1, -1, -1):
                    k, v = values[i]
                    if k == "type":
                        values[i] = (k, v.removeprefix("<TankType.").removesuffix(">"))
                        continue
                    elif k == "flags":
                        values[i] = (k, v.removeprefix("<TankFlags.").removesuffix(">"))
                        continue

                    if v == "0" or v == "0.0" or v == "b''" or v == 'b""' or ": 0" in v:
                        values.remove((k, v))

                hash = hex(zlib.crc32(f"{pkt_num}{time}{pkt}".encode()))[2:].rjust(8, "0")
                pkt_repr = ", ".join(f"{k}={v}" for k, v in values)
                repr = highlight(f"{hash} [T+{time:<7} / {abs_time:<7.3f}] {pkt_num:2d}) from {src} ({net_type}) {pkt_repr}\n")
                abs_time += float(time)

                out.write(repr)
                ref.append((hash, pkt, pkt_num, repr))

        out.write("\n" * 10)
        for hash, pkt, pkt_num, repr in ref:
            out.write(f"{pkt_num:2d}) {repr}{'\n'.join(pkt)}\n\n")

        out.flush()

    for file in list(Path("analyze").glob("*.txt")):
        # if "punch2" not in file.name:
        #     continue

        out_file = file.with_suffix(".out")
        with open(out_file, "w") as out:
            analyze_file(file, out)

        print(f"{out_file}")
