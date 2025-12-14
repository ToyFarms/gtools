import argparse
import itertools
import os
from pathlib import Path
from pprint import pprint
import shutil
import subprocess
import sys
from typing import Protocol


class SupportsStr(Protocol):
    def __str__(self) -> str: ...


def call(cmd: list[SupportsStr]) -> None:
    c = list(map(str, cmd))
    print(f"+ {' '.join(c)}")
    ret = subprocess.run(c, stdout=sys.stdout, stderr=sys.stderr)
    if ret.returncode != 0:
        print(f"return code: {ret}")


def capture_stdout(cmd: list[SupportsStr]) -> str:
    c = list(map(str, cmd))
    print(f"+ {' '.join(c)}")
    ret = subprocess.run(c, capture_output=True)
    if ret.returncode != 0:
        print(f"return code: {ret}")

    return ret.stdout.decode()


def capture_stderr(cmd: list[SupportsStr]) -> str:
    c = list(map(str, cmd))
    print(f"+ {' '.join(c)}")
    ret = subprocess.run(c, capture_output=True)
    if ret.returncode != 0:
        print(f"return code: {ret}")

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


if __name__ == "__main__":
    main()
