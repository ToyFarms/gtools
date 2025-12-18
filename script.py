import argparse
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

from gtools.core.growtopia.packet import NetPacket


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

            content = file.read_text()
            packets = re.split(r"^DEBUG:proxy:\[T\+(.*)\] from gt ", content, flags=re.MULTILINE)
            it = iter(packets[1:])
            packets = [(mark, block.strip().splitlines()) for mark, block in zip(it, it)]

            def find_index[T](iterable: list[T], predicate: Callable[[T], bool]) -> int | None:
                for i, item in enumerate(iterable):
                    if predicate(item):
                        return i

            ref: list[tuple[str, list[str], int, str]] = []

            for pkt_num, (time, pkt) in enumerate(packets):
                src = pkt[0].split(" ")[0]
                pkt_repr_start = find_index(pkt, lambda x: x.startswith("DEBUG:proxy:packet="))
                net_type = re.findall(r".*NetPacket\[(.*)\]", pkt[pkt_repr_start])[0]  # pyright: ignore
                pkt_repr_end = find_index(pkt, lambda x: "flags=" in x and "from=" in x)

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
            out_file = file.with_suffix(".out")
            with open(out_file, "w") as out:
                analyze(file, out)

            print(f"{out_file}")
    elif args.cmd == "parse":
        buf: str = " ".join(args.buf)
        buf = buf.removeprefix("DEBUG:proxy:b")
        b = buf.encode().decode("unicode_escape").encode("latin1")
        print(b)

        pprint(NetPacket.deserialize(b))



if __name__ == "__main__":
    main()
