from pathlib import Path
import platform
import os
import sys
import shlex
import re
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


def parse_compiler_flags_from_file(filepath: Path) -> dict[str, list[str]]:
    """
    // BUILD_FLAGS[gcc]: -O2 -Wall
    // BUILD_FLAGS[clang]: -O3 -Weverything
    // BUILD_FLAGS[msvc]: /O2 /W4
    // BUILD_FLAGS[gcc, clang]: -fPIC
    """
    flags: dict[str, list[str]] = {}
    pattern = re.compile(r"//\s*BUILD_FLAGS\[([^\]]+)\]:\s*(.+)")

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                if line_num > 20:
                    break

                match = pattern.match(line.strip())
                if match:
                    compilers_str = match.group(1).strip()
                    flags_str = match.group(2).strip()
                    flag_list = shlex.split(flags_str)

                    compiler_names = [c.strip() for c in compilers_str.split(",")]
                    for compiler_name in compiler_names:
                        if compiler_name:
                            flags.setdefault(compiler_name, []).extend(flag_list)
    except Exception as exc:
        click.echo(f"warning: failed to parse flags from {filepath}: {exc}", err=True)

    return flags


def normalize_compiler_name(canon: str) -> str:
    low = canon.lower()
    if low.startswith("mingw"):
        return "mingw"
    if low in ("aarch64-linux-gnu", "arm-linux-gnueabihf"):
        return "gcc"
    return low


def collect_compiler_flags(src_files: list[Path], compiler_id: str) -> list[str]:
    all_flags: list[str] = []
    normalized = normalize_compiler_name(compiler_id)

    for src_file in src_files:
        file_flags = parse_compiler_flags_from_file(src_file)

        if compiler_id in file_flags:
            all_flags.extend(file_flags[compiler_id])
        elif normalized in file_flags:
            all_flags.extend(file_flags[normalized])

    return all_flags


def build_command_for_gcc_clang(
    cc: str,
    srcs: list[str],
    out: str,
    target_canon: str | None = None,
    target_system: str | None = None,
    extra_flags: list[str] | None = None,
) -> list[str]:
    cc_lower = cc.lower()
    is_mingw = "mingw" in cc_lower or (target_canon or "").startswith("mingw-w64") or (target_system == "Windows")
    system = target_system or platform.system()

    args: list[str] = [cc]

    if system == "Darwin" and not is_mingw:
        args += ["-dynamiclib", "-fPIC"]
    else:
        args += ["-shared", "-fPIC"]

    if extra_flags:
        args += extra_flags

    args += ["-o", out]
    args += srcs

    return args


def build_command_for_msvc(srcs: list[str], out: str, extra_flags: list[str] | None = None) -> list[str]:
    args: list[str] = ["cl", "/nologo", "/LD"]

    if extra_flags:
        args += extra_flags

    args += srcs
    args += [f"/Fe:{out}"]

    return args


def compile_in_directory(compiler_id: str, src_dir: Path, target_system: str | None = None) -> tuple[bool, str]:
    srcs = sorted([str(p.name) for p in src_dir.glob("*.c")])
    if not srcs:
        return False, "no C source files found"

    src_paths = [src_dir / s for s in srcs]
    extra_flags = collect_compiler_flags(src_paths, compiler_id)

    if extra_flags:
        click.echo(f"  found custom flags for {compiler_id}: {shlex.join(extra_flags)}")

    out_name = make_output_name(src_dir, system=target_system)
    out_path = src_dir / out_name
    cc_exe = guess_compiler_executable(compiler_id)

    if compiler_id == "msvc":
        if (target_system or platform.system()) != "Windows":
            return False, f"msvc cannot target {target_system}"
        cmd = build_command_for_msvc(srcs, out_name, extra_flags=extra_flags)
    else:
        cmd = build_command_for_gcc_clang(cc_exe, srcs, out_name, target_canon=compiler_id, target_system=target_system, extra_flags=extra_flags)

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
