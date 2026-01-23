import os
import shutil
import subprocess
import sys
from typing import Protocol, Sequence


class SupportsStr(Protocol):
    def __str__(self) -> str: ...


def call(cmd: Sequence[SupportsStr]) -> None:
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
