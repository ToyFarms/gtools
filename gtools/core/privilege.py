import os
import sys
import subprocess
import platform
from enum import Enum


class ElevationStatus(Enum):
    SUCCESS = "success"
    ALREADY_ELEVATED = "already_elevated"
    REJECTED = "rejected"
    ERROR = "error"
    NOT_SUPPORTED = "not_supported"


class ElevationResult:
    def __init__(self, status: ElevationStatus, message: str = "", exc: Exception | None = None):
        self.status = status
        self.message = message
        self.exc = exc
        self.is_success = status in (ElevationStatus.SUCCESS, ElevationStatus.ALREADY_ELEVATED)

    def __repr__(self):
        if self.exc:
            return f"{self.message}: {self.exc}"
        else:
            return f"{self.message}"


def is_elevated() -> bool:
    system = platform.system()

    try:
        if system == "Windows":
            import ctypes

            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        else:
            return os.geteuid() == 0
    except Exception:
        return False


def elevate_process(restart: bool = True, kill: bool = True) -> ElevationResult:
    if is_elevated():
        return ElevationResult(ElevationStatus.ALREADY_ELEVATED, "process is already running with elevated privileges")

    system = platform.system()

    try:
        if system == "Windows":
            return _elevate_windows(restart, kill)
        elif system == "Darwin":
            return _elevate_macos(restart, kill)
        elif system == "Linux":
            return _elevate_linux(restart, kill)
        else:
            return ElevationResult(ElevationStatus.NOT_SUPPORTED, f"platform '{system}' is not supported for elevation")

    except Exception as e:
        return ElevationResult(ElevationStatus.ERROR, f"unexpected error during elevation: {str(e)}", e)


def _elevate_windows(restart: bool, kill: bool) -> ElevationResult:
    try:
        import ctypes

        if restart:
            script = sys.executable
            params = " ".join([f'"{arg}"' for arg in sys.argv])

            ret = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                script,
                params,
                None,
                1,  # SW_SHOWNORMAL
            )

            # ShellExecuteW returns > 32 on success
            if ret > 32:
                if kill:
                    sys.exit(0)
                return ElevationResult(ElevationStatus.SUCCESS)
            elif ret == 5:  # ERROR_ACCESS_DENIED
                return ElevationResult(ElevationStatus.REJECTED, "user declined UAC prompt or access was denied")
            else:
                return ElevationResult(ElevationStatus.ERROR, f"ShellExecuteW failed with return code: {ret}")
        else:
            return ElevationResult(ElevationStatus.SUCCESS)

    except ImportError:
        return ElevationResult(ElevationStatus.ERROR, "ctypes module not available on Windows", ImportError("ctypes required for Windows elevation"))
    except Exception as e:
        return ElevationResult(ElevationStatus.ERROR, f"windows elevation failed: {str(e)}", e)


def _elevate_macos(restart: bool, kill: bool) -> ElevationResult:
    try:
        if restart:
            script = os.path.abspath(sys.argv[0])
            args = sys.argv[1:]

            cmd = f"{sys.executable} {script}"
            if args:
                cmd += " " + " ".join([f'"{arg}"' for arg in args])

            applescript = f'do shell script "{cmd}" with administrator privileges'

            result = subprocess.run(["osascript", "-e", applescript], capture_output=True, text=True)

            if result.returncode == 0:
                if kill:
                    sys.exit(0)
                return ElevationResult(ElevationStatus.SUCCESS)
            elif result.returncode == 1:
                return ElevationResult(ElevationStatus.REJECTED, "user cancelled authentication dialog")
            else:
                return ElevationResult(ElevationStatus.ERROR, f"osascript failed: {result.stderr}")
        else:
            return ElevationResult(ElevationStatus.SUCCESS)

    except FileNotFoundError:
        return ElevationResult(ElevationStatus.ERROR, "osascript not found. Is this running on macOS?", FileNotFoundError("osascript command not found"))
    except Exception as e:
        return ElevationResult(ElevationStatus.ERROR, f"macOS elevation failed: {str(e)}", e)


def _elevate_linux(restart: bool, kill: bool) -> ElevationResult:
    try:
        if restart:
            script = os.path.abspath(sys.argv[0])
            args = [sys.executable, script] + sys.argv[1:]

            elevation_commands = ["pkexec", "sudo", "gksu", "kdesudo"]

            for cmd in elevation_commands:
                if _command_exists(cmd):
                    try:
                        if cmd == "sudo":
                            full_cmd = [cmd] + args
                        else:
                            full_cmd = [cmd] + args

                        result = subprocess.run(full_cmd, capture_output=True, text=True)

                        if result.returncode == 0:
                            if kill:
                                sys.exit(0)
                            return ElevationResult(ElevationStatus.SUCCESS)
                        elif result.returncode == 126 or result.returncode == 127:
                            return ElevationResult(ElevationStatus.REJECTED, f"authentication cancelled or failed with {cmd}")
                        else:
                            continue

                    except Exception:
                        continue

            return ElevationResult(ElevationStatus.ERROR, "no suitable elevation command found (tried: pkexec, sudo, gksu, kdesudo)")
        else:
            return ElevationResult(ElevationStatus.SUCCESS)

    except Exception as e:
        return ElevationResult(ElevationStatus.ERROR, f"linux elevation failed: {str(e)}", e)


def _command_exists(command: str) -> bool:
    try:
        subprocess.run(["which", command], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
