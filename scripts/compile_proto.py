from pathlib import Path
import click

from scripts.utils import call, executable_exists


@click.command()
def compile_proto() -> None:
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
    pyi_out = Path("gtools/protogen")
    pyi_out.mkdir(exist_ok=True)
    ts_out = Path("extension/gtools-gui/protogen")
    ts_out.mkdir(exist_ok=True)

    files = list(src.glob("*.proto"))
    print(f"sources: ")
    for file in files:
        print(f"    - {file}")

    call(["protoc", "-I", src, "--python_out", pyi_out, "--pyi_out", pyi_out, *files])
    if fix_import:
        call(["fix-protobuf-imports", pyi_out])

    if not executable_exists("protoc-gen-ts_proto"):
        print("\x1b[33mWARNING\x1b[0m protoc-gen-ts_proto not found (npm install -g ts-proto)")
        print("skipping typescript generation")
        return

    call(
        [
            "protoc",
            "-I",
            src,
            f"--ts_proto_out={ts_out}",
            *files,
        ]
    )
