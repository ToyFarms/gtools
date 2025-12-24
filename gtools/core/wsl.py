from functools import cache
import os
from pathlib import Path
import subprocess


def is_running_wsl() -> bool:
    _check = lambda x: "microsoft" in x or "wsl1" in x or "wsl2" in x
    try:
        return _check(os.uname().release.lower())
    except:
        pass

    try:
        with open("/proc/version", "r") as f:
            return _check(f.read().lower())
    except:
        pass

    try:
        with open("/proc/sys/kernel/osrelease", "r") as f:
            return _check(f.read().lower())
    except:
        pass

    return False


@cache
def windows_home() -> Path:
    if is_running_wsl():
        wsl_cmd = subprocess.run(
            ["wslpath", "-au", r"C:\Windows\System32\cmd.exe"],
            capture_output=True,
            text=True,
        )
        cmd_path = wsl_cmd.stdout.strip()

        win_home_proc = subprocess.run(
            [cmd_path, "/c", "echo %USERPROFILE%"],
            capture_output=True,
            text=True,
        )
        win_home = win_home_proc.stdout.strip()

        abs_proc = subprocess.run(
            ["wslpath", "-au", win_home],
            capture_output=True,
            text=True,
        )
        abs_path = abs_proc.stdout.strip()

        return Path(abs_path)
    else:
        return Path.home()
