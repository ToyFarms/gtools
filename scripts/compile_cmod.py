from collections import defaultdict
from enum import StrEnum, auto
import hashlib
import itertools
import json
import re
import shlex
import sqlite3
import subprocess
import sys
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
import platform
from typing import Callable

import click
from scripts.utils import executable_exists

_R, _B, _D, _RE, _GR, _YE = "\x1b[0m", "\x1b[1m", "\x1b[2m", "\x1b[31m", "\x1b[32m", "\x1b[33m"
_print_lock = threading.Lock()


def _flush(lines: list[str]) -> None:
    with _print_lock:
        sys.stdout.write("\n".join(lines) + "\n\n")
        sys.stdout.flush()


class Platform(StrEnum):
    WINDOWS = auto()
    LINUX = auto()
    MAC = auto()
    UNKNOWN = auto()


_OS_ALIASES: dict[str, Platform] = {
    alias: key
    for key, aliases in {
        Platform.MAC: ("darwin", "macos", "mac", "osx"),
        Platform.LINUX: ("linux",),
        Platform.WINDOWS: ("windows", "win32", "cygwin", "msys"),
    }.items()
    for alias in aliases
}


def get_platform(system: str | None = None) -> Platform:
    s = (system or platform.system()).lower()
    return _OS_ALIASES.get(s, Platform.UNKNOWN)


class Compiler(ABC):
    def __init__(self, canonical_name: str) -> None:
        self.canonical_name = canonical_name

    @property
    @abstractmethod
    def executable(self) -> str: ...

    @abstractmethod
    def supported_targets(self) -> list[Platform]: ...

    @abstractmethod
    def build_command(self, srcs: list[str], out: str, target_system: Platform | None = None, extra_flags: list[str] | None = None) -> list[str]: ...

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.canonical_name!r})"


class GccClangCompiler(Compiler):
    _EXECUTABLES: dict[str, str] = {
        "clang": "clang",
        "gcc": "gcc",
        "cc": "cc",
    }

    def __init__(self, canonical_name: str) -> None:
        super().__init__(canonical_name)
        self._exe = self._EXECUTABLES.get(canonical_name, canonical_name)

    @property
    def executable(self) -> str:
        return self._exe

    def supported_targets(self) -> list[Platform]:
        return [get_platform()]

    def build_command(self, srcs: list[str], out: str, target_system: Platform | None = None, extra_flags: list[str] | None = None) -> list[str]:
        lib_flag = "-dynamiclib" if target_system == Platform.MAC else "-shared"
        return [self.executable, lib_flag, "-fPIC", *(extra_flags or []), "-o", out, *srcs]


class MinGWCompiler(Compiler):
    _EXECUTABLES: dict[str, str] = {
        "mingw-w64-x86_64": "x86_64-w64-mingw32-gcc",
        "mingw-w64-i686": "i686-w64-mingw32-gcc",
    }

    def __init__(self, canonical_name: str) -> None:
        super().__init__(canonical_name)
        self._exe = self._EXECUTABLES.get(canonical_name, canonical_name)

    @property
    def executable(self) -> str:
        return self._exe

    def supported_targets(self) -> list[Platform]:
        return [Platform.WINDOWS]

    def build_command(self, srcs: list[str], out: str, target_system: Platform | None = None, extra_flags: list[str] | None = None) -> list[str]:
        return [self.executable, "-shared", "-fPIC", *(extra_flags or []), "-o", out, *srcs]


class CrossGccCompiler(Compiler):
    _EXECUTABLES: dict[str, str] = {
        "aarch64-linux-gnu": "aarch64-linux-gnu-gcc",
        "arm-linux-gnueabihf": "arm-linux-gnueabihf-gcc",
    }

    def __init__(self, canonical_name: str) -> None:
        super().__init__(canonical_name)
        self._exe = self._EXECUTABLES.get(canonical_name, canonical_name)

    @property
    def executable(self) -> str:
        return self._exe

    def supported_targets(self) -> list[Platform]:
        return [Platform.LINUX]

    def build_command(self, srcs: list[str], out: str, target_system: Platform | None = None, extra_flags: list[str] | None = None) -> list[str]:
        return [self.executable, "-shared", "-fPIC", *(extra_flags or []), "-o", out, *srcs]


class MsvcCompiler(Compiler):
    def __init__(self) -> None:
        super().__init__("msvc")

    @property
    def executable(self) -> str:
        return "cl"

    def supported_targets(self) -> list[Platform]:
        return [Platform.WINDOWS]

    def build_command(self, srcs: list[str], out: str, target_system: Platform | None = None, extra_flags: list[str] | None = None) -> list[str]:
        if target_system != Platform.WINDOWS:
            raise RuntimeError(f"MSVC cannot target {target_system or platform.system()}")

        return ["cl", "/nologo", "/LD", *(extra_flags or []), *srcs, "/link", f"/OUT:{out}"]


class CompilerRegistry:
    _PROBES: list[tuple[str, str, type[Compiler]]] = [
        ("clang", "clang", GccClangCompiler),
        ("gcc", "gcc", GccClangCompiler),
        ("cc", "cc", GccClangCompiler),
        ("x86_64-w64-mingw32-gcc", "mingw-w64-x86_64", MinGWCompiler),
        ("i686-w64-mingw32-gcc", "mingw-w64-i686", MinGWCompiler),
        ("aarch64-linux-gnu-gcc", "aarch64-linux-gnu", CrossGccCompiler),
        ("arm-linux-gnueabihf-gcc", "arm-linux-gnueabihf", CrossGccCompiler),
        ("cl", "msvc", MsvcCompiler),
    ]

    def __init__(self) -> None:
        self._compilers: dict[str, Compiler] = {}
        self._probe()

    def _probe(self) -> None:
        for probe, canon, factory in self._PROBES:
            if executable_exists(probe):
                compiler = MsvcCompiler() if factory is MsvcCompiler else factory(canon)
                self._compilers[canon] = compiler

    @property
    def available(self) -> list[Compiler]:
        return list(self._compilers.values())

    def get(self, canonical_name: str) -> Compiler | None:
        return self._compilers.get(canonical_name)

    def targets_map(self) -> dict[Platform, list[Compiler]]:
        result: defaultdict[Platform, list[Compiler]] = defaultdict(list)
        for compiler in self.available:
            for target in compiler.supported_targets():
                result[target].append(compiler)

        return result


class FlagParser:
    _PATTERN = re.compile(r"//\s*BUILD_FLAGS\[([^\]]+)\]:\s*(.+)")
    _LINES_TO_SCAN = 20

    _GROUP: dict[str, str] = {
        **{c: "mingw" for c in ("mingw-w64-x86_64", "mingw-w64-i686")},
        **{c: "gcc" for c in ("aarch64-linux-gnu", "arm-linux-gnueabihf")},
    }

    def collect(self, src_files: list[Path], compiler: Compiler, target_system: Platform | None = None) -> list[str]:
        keys = {compiler.canonical_name.lower(), self._group_key(compiler.canonical_name)}
        target_key = get_platform(target_system)
        all_flags: list[str] = []
        for src in src_files:
            parsed = self._parse_file(src)
            for key in keys:
                for os_filter, flags_str in parsed.get(key, []):
                    if os_filter is None or target_key in os_filter:
                        all_flags.extend(shlex.split(self._expand_shell(flags_str)))
        return all_flags

    def _group_key(self, canon: str) -> str:
        return self._GROUP.get(canon.lower(), canon.lower())

    def _parse_file(self, filepath: Path) -> dict[str, list[tuple[set[Platform] | None, str]]]:
        result: defaultdict[str, list[tuple[set[Platform] | None, str]]] = defaultdict(list)
        try:
            with open(filepath, encoding="utf-8") as f:
                for line in itertools.islice(f, self._LINES_TO_SCAN):
                    if m := self._PATTERN.match(line.strip()):
                        for sel in self._split_selector_list(m.group(1).strip()):
                            name, os_filter = self._parse_selector(sel)
                            if name:
                                result[name].append((os_filter, m.group(2).strip()))
        except Exception as exc:
            print(f"warning: failed to parse flags from {filepath}: {exc}", file=sys.stderr)

        return result

    @staticmethod
    def _split_selector_list(spec: str) -> list[str]:
        items, buf, depth = [], [], 0
        for ch in spec:
            if ch == "," and depth == 0:
                if token := "".join(buf).strip():
                    items.append(token)
                buf = []
            else:
                depth += ch == "("
                depth -= ch == ")" and depth > 0
                buf.append(ch)
        if token := "".join(buf).strip():
            items.append(token)

        return items

    @staticmethod
    def _parse_selector(selector: str) -> tuple[str, set[Platform] | None]:
        m = re.fullmatch(r"([A-Za-z0-9_.+-]+)(?:\(([^)]+)\))?", selector.strip())
        if not m:
            return selector.lower(), None
        name, os_part = m.group(1).strip().lower(), m.group(2)
        if not os_part:
            return name, None

        return name, {get_platform(p.strip()) for p in re.split(r"[|/]+", os_part) if p.strip()}

    @staticmethod
    def _expand_shell(s: str) -> str:
        result, i = [], 0
        while i < len(s):
            if s[i] == "$" and i + 1 < len(s) and s[i + 1] == "(":
                depth, j = 1, i + 2
                while j < len(s) and depth > 0:
                    depth += s[j] == "("
                    depth -= s[j] == ")"
                    j += 1
                if depth != 0:
                    result.append(s[i])
                    i += 1
                    continue
                cmd = s[i + 2 : j - 1]
                try:
                    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                    if proc.returncode == 0:
                        result.append(proc.stdout.strip())
                    else:
                        msg = f"warning: shell substitution $({cmd}) exited {proc.returncode}"
                        if proc.stderr.strip():
                            msg += f": {proc.stderr.strip()}"
                        print(msg, file=sys.stderr)
                        result.append(s[i:j])
                except Exception as exc:
                    print(f"warning: shell substitution $({cmd}) error: {exc}", file=sys.stderr)
                    result.append(s[i:j])
                i = j
            else:
                result.append(s[i])
                i += 1
        return "".join(result)


class CacheManager:
    CACHE_DIR = ".cmodcache"
    DB_NAME = "cache.db"

    def __init__(self, project_root: Path) -> None:
        cache_dir = project_root / self.CACHE_DIR
        cache_dir.mkdir(exist_ok=True)
        self._db_path = cache_dir / self.DB_NAME
        self._write_lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS build_cache (
                    cache_key TEXT PRIMARY KEY,
                    src_hashes TEXT NOT NULL,
                    extra_flags TEXT NOT NULL,
                    built_at REAL NOT NULL
                )
                """)

    @staticmethod
    def _make_key(compiler: "Compiler", out: str, target_system: "Platform | None") -> str:
        return f"{compiler.canonical_name}|{target_system or 'native'}|{out}"

    @staticmethod
    def _hash_sources(srcs: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for src in srcs:
            h = hashlib.sha256()
            try:
                with open(src, "rb") as fh:
                    for chunk in iter(lambda: fh.read(65_536), b""):
                        h.update(chunk)
                result[src] = h.hexdigest()
            except OSError:
                result[src] = ""

        return result

    def should_rebuild(self, compiler: "Compiler", srcs: list[str], out: str, target_system: "Platform | None" = None, extra_flags: list[str] | None = None) -> bool:
        if not Path(out).exists():
            return True

        key = self._make_key(compiler, out, target_system)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT src_hashes, extra_flags FROM build_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()

        if row is None:
            return True

        if json.loads(row[1]) != (extra_flags or []):
            return True

        return self._hash_sources(srcs) != json.loads(row[0])

    def update(self, compiler: "Compiler", srcs: list[str], out: str, target_system: "Platform | None" = None, extra_flags: list[str] | None = None) -> None:
        key = self._make_key(compiler, out, target_system)
        src_hashes = json.dumps(self._hash_sources(srcs))
        flags_json = json.dumps(extra_flags or [])
        with self._write_lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO build_cache (cache_key, src_hashes, extra_flags, built_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    src_hashes = excluded.src_hashes,
                    extra_flags = excluded.extra_flags,
                    built_at = excluded.built_at
                """,
                (key, src_hashes, flags_json, time.time()),
            )


@dataclass
class BuildResult:
    success: bool
    src_path: Path
    target_system: Platform
    error: str = ""


class BuildJob:
    def __init__(self, src_path: Path, target_system: Platform, compilers: list[Compiler], project_root: Path, flag_parser: FlagParser, cache_manager: CacheManager) -> None:
        self.src_path = src_path
        self.target_system = target_system
        self.compilers = compilers
        self.project_root = project_root
        self.flag_parser = flag_parser
        self.cache_manager = cache_manager

    def output_path(self) -> Path:
        base = self.src_path.stem
        normalized = get_platform(self.target_system)
        if normalized == "windows":
            name = f"{base}.dll"
        elif normalized == "macos":
            name = f"lib{base}.dylib"
        else:
            name = f"lib{base}.so"

        return self.src_path.parent / name

    def run(self, job_num: Callable[[], int], total: int, force: bool = False) -> BuildResult:
        out_path = self.output_path()
        src_rel = str(self.src_path.relative_to(self.project_root))
        out_rel = str(out_path.relative_to(self.project_root))
        w = len(str(total))
        indent = " " * (2 * w + 5)
        body: list[str] = []
        last_err = "no compilers attempted"
        success = False

        for compiler in self.compilers:
            extra_flags = self.flag_parser.collect([self.src_path], compiler, self.target_system)

            if not force and not self.cache_manager.should_rebuild(compiler, [src_rel], out_rel, self.target_system, extra_flags):
                body.append(f"{indent}{_GR}{_B}ok{_R}  {_D}(cached){_R}")
                last_err, success = "", True
                break

            try:
                cmd = compiler.build_command([src_rel], out_rel, self.target_system, extra_flags)
            except RuntimeError as exc:
                last_err = str(exc)
                body.append(f"{indent}{_RE}fail{_R}  {_YE}{compiler.canonical_name}{_R}  {last_err}")
                continue

            body.append(f"{indent}+ {_D}{shlex.join(cmd)}{_R}")

            try:
                ret = subprocess.run(cmd, text=True, capture_output=True)
            except Exception as exc:
                last_err = str(exc)
                body.append(f"{indent}{_RE}fail{_R}  {_YE}{compiler.canonical_name}{_R}  {last_err}")
                continue

            if ret.returncode != 0:
                last_err = f"compiler exited with code {ret.returncode}"
                body.append(f"{indent}{_RE}fail{_R}  {_YE}{compiler.canonical_name}{_R}  {last_err}")
                for label, text in (("stdout", ret.stdout), ("stderr", ret.stderr)):
                    if text:
                        body.append(f"{indent}{_D}{label}{_R}  {text.rstrip()}")
                continue

            if not out_path.exists():
                last_err = f"{out_path.name} was not produced"
                body.append(f"{indent}{_RE}fail{_R}  {last_err}")
                continue

            self.cache_manager.update(compiler, [src_rel], out_rel, self.target_system, extra_flags)
            body.append(f"{indent}{_GR}{_B}ok{_R}")
            last_err, success = "", True
            break

        header = f"{_D}[{_R}{job_num():>{w}}/{total}{_D}]{_R}  " f"{_D}{self.target_system}{_R}  " f"{_B}{src_rel}{_R}{_D}: {_R}{out_path.name}"
        _flush([header, *body])
        return BuildResult(success, self.src_path, self.target_system, last_err)


class BuildManager:
    SOURCE_ROOT = "gtools"

    def __init__(self, workers: int, rebuild: bool) -> None:
        self.workers = workers
        self.rebuild = rebuild
        self.project_root = Path.cwd()
        self.src_root = self.project_root / self.SOURCE_ROOT
        self.registry = CompilerRegistry()
        self.flag_parser = FlagParser()
        self.cache_manager = CacheManager(self.project_root)

    def run(self) -> None:
        self._validate()

        compilers = self.registry.available
        print(f"compilers  {' '.join(c.canonical_name for c in compilers)}")

        targets_map = self.registry.targets_map()
        print(f"targets    {' '.join(sorted(targets_map.keys()))}")

        all_src = sorted(self.src_root.rglob("*.c"))
        if not all_src:
            print("no .c files found")
            sys.exit(0)

        jobs = self._create_jobs(all_src, targets_map)
        total = len(jobs)
        print(f"jobs       {total}  {_D}(workers={self.workers}){_R}\n")

        failed = self._execute(jobs)

        if failed:
            print(
                f"{_RE}build failed{_R}  {_D}{len(failed)}/{total} job(s){_R}",
                file=sys.stderr,
            )
            for result in failed:
                print(
                    f"  {_B}{result.src_path.relative_to(self.project_root)}{_R}" f"  {_D}{result.target_system}{_R}  {result.error}",
                    file=sys.stderr,
                )
            sys.exit(3)

        print(f"{_GR}{_B}done{_R}  {_D}{total}/{total} job(s){_R}")

    def _validate(self) -> None:
        if not self.src_root.exists() or not self.src_root.is_dir():
            print(f"{_RE}error{_R}  {self.SOURCE_ROOT}/ not found", file=sys.stderr)
            sys.exit(1)
        if not self.registry.available:
            print(
                f"{_RE}error{_R}  no supported C compiler on PATH (gcc, clang, MSVC)",
                file=sys.stderr,
            )
            sys.exit(2)

    def _create_jobs(self, src_files: list[Path], targets_map: dict[Platform, list[Compiler]]) -> list[BuildJob]:
        return [BuildJob(src, target, comp_list, self.project_root, self.flag_parser, self.cache_manager) for src in src_files for target, comp_list in sorted(targets_map.items())]

    def _execute(self, jobs: list[BuildJob]) -> list[BuildResult]:
        total = len(jobs)
        counter = itertools.count(1)
        counter_lock = threading.Lock()
        failed: list[BuildResult] = []

        def get_num() -> int:
            with counter_lock:
                return next(counter)

        def _run(job: BuildJob) -> BuildResult:
            return job.run(get_num, total, self.rebuild)

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = {pool.submit(_run, job) for job in jobs}
            for future in as_completed(futures):
                result = future.result()
                if not result.success:
                    failed.append(result)

        return failed


@click.command()
@click.option("-j", "workers", default=4, show_default=True, help="num of workers")
@click.option("-B", "rebuild", default=False, show_default=True, help="force rebuild", is_flag=True)
def compile_cmod(workers: int, rebuild: bool) -> None:
    b = BuildManager(workers=workers, rebuild=rebuild)
    b.run()
