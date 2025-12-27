# TODO: make a directory scripts/ keep stuff separated out there so its not so cluttered
import argparse
from collections import defaultdict
from functools import cache
import itertools
import os
from pathlib import Path
from pprint import pprint
import re
import shutil
import subprocess
import sys
from typing import IO, Callable, Protocol
import zlib

try:
    from gtools.core.growtopia.items_dat import Item, item_database
    from gtools.core.growtopia.packet import NetPacket
except ImportError:
    pass


class SupportsStr(Protocol):
    def __str__(self) -> str: ...


def call(cmd: list[SupportsStr]) -> None:
    c = list(map(str, cmd))
    print(f"+ {' '.join(c)}")
    ret = subprocess.run(c, stdout=sys.stdout, stderr=sys.stderr)
    if ret.returncode != 0:
        print(f"\x1b[31mnon-zero return code\x1b[0m ({ret.returncode}) return code: {ret!r}")


def capture_stdout(cmd: list[SupportsStr]) -> str:
    c = list(map(str, cmd))
    print(f"+ {' '.join(c)}")
    ret = subprocess.run(c, capture_output=True)
    if ret.returncode != 0:
        print(f"\x1b[31mnon-zero return code\x1b[0m ({ret.returncode}) return code: {ret!r}")

    return ret.stdout.decode()


def capture_stderr(cmd: list[SupportsStr]) -> str:
    c = list(map(str, cmd))
    print(f"+ {' '.join(c)}")
    ret = subprocess.run(c, capture_output=True)
    if ret.returncode != 0:
        print(f"\x1b[31mnon-zero return code\x1b[0m ({ret.returncode}) return code: {ret!r}")

    return ret.stderr.decode()


def executable_exists(name: str) -> bool:
    path = shutil.which(name)
    return path is not None and os.access(path, os.X_OK)


def main() -> None:
    parser = argparse.ArgumentParser()

    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("compile-proto")

    test_cov = sub.add_parser("test")
    test_cov.add_argument("-r", help="run http server", action="store_true")

    sub.add_parser("clean-test")
    sub.add_parser("analyze")

    parse = sub.add_parser("parse")
    parse.add_argument("buf", nargs="*")

    item = sub.add_parser("item")
    item.add_argument("id", type=int)

    search = sub.add_parser("search")
    search.add_argument("name")
    search.add_argument("-n", type=int, default=20)

    recipe = sub.add_parser("recipe")
    recipe.add_argument("id", type=int)
    recipe.add_argument("-n", type=int, default=1)

    args = parser.parse_args()

    if args.cmd == "compile-proto":
        print("compiling protobuf")

        if not executable_exists("protoc"):
            print("you need a protobuf compiler (protoc)")
            return

        fix_import = True
        if not executable_exists("fix-protobuf-imports"):
            print("\x1b[33mWARNING\x1b[0m fix-protobuf-imports is not installed (pip install fix-protobuf-imports)")
            print("continuing without it.. if you came across an import error relating to protobuf, this is the cause")
            fix_import = False

        src = Path("gtools/proto")
        out = Path("gtools/protogen")
        out.mkdir(exist_ok=True)

        files = list(src.glob("*.proto"))
        print(f"sources: ")
        for file in files:
            print(f"    - {file}")

        call(["protoc", "-I", src, "--python_out", out, "--pyi_out", out, *files])
        if fix_import:
            call(["fix-protobuf-imports", out])
    elif args.cmd == "test":
        if not executable_exists("coverage"):
            print("coverage.py is required (pip install coverage)")
            return

        if not executable_exists("pytest"):
            print("pytest is required (pip install pytest)")
            return

        if "--forked" not in capture_stdout(["pytest", "--help"]):
            print("pytest-forked is required (pip install pytest-forked)")
            return

        call(["coverage", "run", "-m", "pytest", "--forked", "-vv"])
        call(["coverage", "html"])
        call(["coverage", "report", "-m"])

        report = Path("htmlcov")
        if not report.exists():
            print("unexpected, htmlcov/ should exists after running `coverage html`")
            return

        if args.r:
            port = 9576
            print(f"go to http://localhost:{port} for the coverage report")
            os.chdir(report)
            try:
                call([sys.executable, "-m", "http.server", port])
            except (KeyboardInterrupt, InterruptedError):
                pass
    elif args.cmd == "clean-test":
        snapshots = Path("tests/snapshots")
        out = list(itertools.chain(snapshots.glob("*.out"), snapshots.glob("*.snap")))
        pprint(out)
        print(f"\x1b[31mREMOVING \x1b[4;1m{len(out)}\x1b[0m files from {snapshots}!, are you sure? ", end="")

        if input("(y/N) ").lower() == "y":
            shutil.rmtree(snapshots)
    elif args.cmd == "analyze":

        # TODO: fk this, is shouldve just dump the raw traffic instead of parsing the logs
        def analyze(file: Path, out: IO[str]) -> None:
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

            for pkt_num, (time, pkt) in enumerate(packets):
                src = pkt[0].split(" ")[0]
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
                    if pkt_num % 2 == 0:
                        repr = highlight(f"{hash} [T+{time:<7}] {pkt_num:2d}) from {src} ({net_type}) {pkt_repr}\n")
                    else:
                        repr = highlight(f"{hash} [T+{time:<7}] {pkt_num:2d}) from {src} ({net_type}) {pkt_repr}\n")

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
                analyze(file, out)

            print(f"{out_file}")
    elif args.cmd == "parse":
        buf: str = " ".join(args.buf)
        buf = buf.removeprefix("DEBUG:proxy:b").removeprefix("b").removeprefix('"').removeprefix("'").removesuffix("'").removesuffix('"')
        b = buf.encode().decode("unicode_escape").encode("latin1")

        pprint(NetPacket.deserialize(b))
    elif args.cmd == "item":
        print(item_database.get(args.id))
    elif args.cmd == "search":
        trim = lambda x, n=60: x if len(x) <= n else f"{x[:n]}..."
        for i, ent in reversed(list(enumerate(item_database.search(args.name, n=args.n), 1))):
            if i % 5 == 0:
                print(f"\x1b[2m{i:<6} {ent.id:<10} {ent.name.decode():<30} {trim(ent.info.decode()):<80} {ent.item_type.name}\x1b[0m")
            else:
                print(f"{i:<5} {ent.id:<10} {ent.name.decode():<30} {trim(ent.info.decode()):<80} {ent.item_type.name}")

    elif args.cmd == "recipe":

        class SpliceNode:
            def __init__(self, item: Item):
                self.item = item
                self.left: SpliceNode | None = None
                self.right: SpliceNode | None = None

        def print_crafting_tree(
            node: SpliceNode | None,
            prefix: str = "",
            is_left: bool = True,
            depth: int = 1,
        ):
            if node is None:
                return

            item = node.item
            name = item.name.decode().removesuffix(" Seed")
            name_len = len(name)

            connector = ""
            if prefix:
                connector = "└─ " if is_left else "├─ "

            print(f"{prefix}{connector} ({depth}) {name}")

            spacer = " " * (name_len // 2 - 1)
            next_prefix = prefix + ("│  " if not is_left else "   ") + spacer

            if node.right:
                print_crafting_tree(
                    node.right,
                    next_prefix,
                    is_left=False,
                    depth=depth + 1,
                )

            if node.left:
                print_crafting_tree(
                    node.left,
                    next_prefix,
                    is_left=True,
                    depth=depth + 1,
                )

        @cache
        def build_crafting_tree(item_id: int) -> SpliceNode:
            item = item_database.get(item_id)
            node = SpliceNode(item)
            left_id, right_id = item.ingredients

            if left_id != 0:
                node.left = build_crafting_tree(left_id)

            if right_id != 0:
                node.right = build_crafting_tree(right_id)

            return node

        @cache
        def count_nodes(node: SpliceNode | None) -> int:
            if node is None:
                return 0
            return 1 + count_nodes(node.left) + count_nodes(node.right)

        @cache
        def calc_cost(node: SpliceNode | None, depth: int = 1) -> None:
            if node is None:
                return

            mats_by_layer[depth][node.item.name] += 1
            calc_cost(node.left, depth + 1)
            calc_cost(node.right, depth + 1)

        tree = build_crafting_tree(args.id)

        def walk(node: SpliceNode, raw_mats: defaultdict[bytes, int], steps: defaultdict[bytes, int]) -> None:
            if node.left is None and node.right is None:
                raw_mats[node.item.name] += 1

            walk(node.left, raw_mats, steps) if node.left else None
            walk(node.right, raw_mats, steps) if node.right else None

            steps[node.item.name] += 1

        tree = build_crafting_tree(args.id)

        raw_mats = defaultdict(int)
        steps = defaultdict(int)
        walk(tree, raw_mats, steps)

        print("-" * 50, "fun fact", "-" * 50)
        print()
        most_nodes = sorted(
            [(f"({i}) {item_database.get(i).name.decode()}", count_nodes(build_crafting_tree(i))) for i in range(len(item_database.items()))],
            key=lambda x: x[1],
            reverse=True,
        )[:20]
        print("most amount of nodes (splice step)")
        pprint(most_nodes)
        print()

        @cache
        def count_raw_mats(node: SpliceNode) -> int:
            raw_mats = defaultdict(int)
            no = defaultdict(int)
            walk(node, raw_mats, no)

            return len(raw_mats)

        most_raw_mats = sorted(
            [(f"({i}) {item_database.get(i).name.decode()}", count_raw_mats(build_crafting_tree(i))) for i in range(len(item_database.items()))],
            key=lambda x: x[1],
            reverse=True,
        )[:20]
        print("most raw material")
        pprint(most_raw_mats)
        print()
        print("-" * 50, "fun fact", "-" * 50)

        mats_by_layer: dict[int, dict[bytes, int]] = defaultdict(lambda: defaultdict(int))

        print_crafting_tree(tree)
        print(f"\nraw materials (for {args.n} {tree.item.name.decode()}, assuming 1:1 ratio):")
        for name, n in raw_mats.items():
            print(f"  {name.decode().removesuffix(' Seed'):20} ({n * args.n:_})")

        print("\nsteps:")
        max_len = 0
        step_lines = []
        for i, (name, n) in enumerate(filter(lambda x: x[0] not in raw_mats, steps.items()), 1):
            item = item_database.get_by_name(name)
            left_id, right_id = item.ingredients
            left = item_database.get(left_id).name.decode().removesuffix(" Seed") if left_id else ""
            right = item_database.get(right_id).name.decode().removesuffix(" Seed") if right_id else ""
            ing = f"{i:>3}) {left} + {right}" if left or right else "(no ingredients)"
            step_lines.append((ing, name.decode().removesuffix(" Seed"), n))
            max_len = max(max_len, len(ing))

        for i, (ing, out, n) in enumerate(step_lines):
            if i % 2 == 0:
                print(f"  {ing.ljust(max_len)}   {out} ({n * args.n:_})")
            else:
                print(f"  {ing.ljust(max_len, '.')}...{out} ({n * args.n:_})")


if __name__ == "__main__":
    main()
