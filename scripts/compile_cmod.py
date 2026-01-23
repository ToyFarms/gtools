from pathlib import Path
import platform
import os
import sys
import shlex

import click

from scripts.utils import call, executable_exists


COMPILER_PROBES: list[tuple[str, str]] = [
    ("clang", "clang"),
    ("gcc", "gcc"),
    ("cc", "cc"),
    # mingw-w64 cross-compilers
    ("x86_64-w64-mingw32-gcc", "mingw-w64-x86_64"),
    ("i686-w64-mingw32-gcc", "mingw-w64-i686"),
    # linux for arm
    ("aarch64-linux-gnu-gcc", "aarch64-linux-gnu"),
    ("arm-linux-gnueabihf-gcc", "arm-linux-gnueabihf"),
    # MSVC
    ("cl", "msvc"),
]


def detect_available_compilers() -> list[str]:
    found: list[str] = []
    for probe, canon in COMPILER_PROBES:
        if executable_exists(probe):
            found.append(canon)
    return found


def guess_compiler_executable(canon: str) -> str:
    for probe, canon_id in COMPILER_PROBES:
        if canon_id == canon:
            return probe
    return canon


def compiler_supported_targets(canon: str) -> list[str]:
    low = canon.lower()
    if low.startswith("mingw"):
        return ["Windows"]
    if low in ("aarch64-linux-gnu", "arm-linux-gnueabihf"):
        return ["Linux"]
    if low == "msvc":
        return ["Windows"]
    if low in ("clang", "gcc", "cc"):
        return [platform.system()]

    return [platform.system()]


def make_output_name(src_dir: Path, system: str | None = None) -> str:
    c_files = list(src_dir.glob("*.c"))
    if len(c_files) == 1:
        base = c_files[0].stem
    else:
        base = src_dir.name or "lib"

    system = system or platform.system()
    if system == "Windows":
        return f"{base}.dll"
    elif system == "Darwin":
        return f"lib{base}.dylib"
    else:
        return f"lib{base}.so"


def build_command_for_gcc_clang(cc: str, srcs: list[str], out: str, target_canon: str | None = None, target_system: str | None = None) -> list[str]:
    cc_lower = cc.lower()
    is_mingw = "mingw" in cc_lower or (target_canon or "").startswith("mingw-w64") or (target_system == "Windows")
    system = target_system or platform.system()

    args: list[str] = [cc]
    if system == "Darwin" and not is_mingw:
        args += ["-dynamiclib", "-fPIC"]
    else:
        args += ["-shared", "-fPIC"]

    args += ["-o", out]
    args += srcs

    return args


def build_command_for_msvc(srcs: list[str], out: str) -> list[str]:
    args: list[str] = ["cl", "/nologo", "/LD"]
    args += srcs
    args += [f"/Fe:{out}"]
    return args


def compile_in_directory(compiler_id: str, src_dir: Path, target_system: str | None = None) -> tuple[bool, str]:
    srcs = sorted([str(p.name) for p in src_dir.glob("*.c")])
    if not srcs:
        return False, "no C source files found"

    out_name = make_output_name(src_dir, system=target_system)
    out_path = src_dir / out_name

    cc_exe = guess_compiler_executable(compiler_id)

    if compiler_id == "msvc":
        if (target_system or platform.system()) != "Windows":
            return False, f"msvc cannot target {target_system}"
        cmd = build_command_for_msvc(srcs, out_name)
    else:
        cmd = build_command_for_gcc_clang(cc_exe, srcs, out_name, target_canon=compiler_id, target_system=target_system)

    old_cwd = Path.cwd()
    try:
        os.chdir(src_dir)
        click.echo(f"compiling for target={target_system or platform.system()} in {src_dir} with {cc_exe!s}: {shlex.join(cmd)}")
        try:
            call(cmd)
        except Exception as exc:
            return False, f"compiler failed: {exc}"
    finally:
        os.chdir(old_cwd)

    if out_path.exists():
        return True, f"created {out_path}"
    else:
        return False, f"compiler did not produce expected output {out_path}"


@click.command()
def compile_cmod() -> None:
    click.echo("compiling c module")

    ROOT = "gtools"
    project_root = Path.cwd()
    src_root = project_root / ROOT
    if not src_root.exists() or not src_root.is_dir():
        click.echo(f"{ROOT}/ directory not found", err=True)
        sys.exit(1)

    compilers = detect_available_compilers()
    if not compilers:
        click.echo("no supported C compiler found on PATH. please install gcc/clang or MSVC", err=True)
        sys.exit(2)

    click.echo(f"detected compilers: {compilers}")

    targets_map: dict[str, list[str]] = {}
    for comp in compilers:
        for t in compiler_supported_targets(comp):
            targets_map.setdefault(t, []).append(comp)

    click.echo(f"available target systems from installed compilers: {sorted(targets_map.keys())}")

    dirs_with_c: dict[Path, list[Path]] = {}
    for c_path in src_root.rglob("*.c"):
        parent = c_path.parent
        dirs_with_c.setdefault(parent, []).append(c_path)

    if not dirs_with_c:
        click.echo("no .c files found")
        sys.exit(0)

    failed: list[tuple[Path, str, str]] = []

    for src_dir, files in sorted(dirs_with_c.items()):
        click.echo(f"\npreparing to compile {len(files)} file(s) in {src_dir}")

        for target_system, comp_list in sorted(targets_map.items()):
            click.echo(f"  -> target: {target_system} (compilers: {comp_list})")
            compiled_for_target = False
            last_err = ""
            for comp in comp_list:
                click.echo(f"    trying compiler: {comp}")
                success, msg = compile_in_directory(comp, src_dir, target_system=target_system)
                if success:
                    click.echo(f"    success: {msg}")
                    compiled_for_target = True
                    break
                else:
                    click.echo(f"    failed with {comp}: {msg}")
                    last_err = msg
            if not compiled_for_target:
                failed.append((src_dir, target_system, last_err))

    if failed:
        click.echo("\nsome targets failed to compile:", err=True)
        for d, target, err in failed:
            click.echo(f" - {d} (target={target}): {err}", err=True)
        sys.exit(3)

    click.echo("\nall compilation tasks finished successfully.")
