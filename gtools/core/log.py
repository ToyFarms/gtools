import binascii
import logging
import sys
import os
from pathlib import Path
from datetime import datetime
import platform
import socket
import getpass
import shutil
import atexit
import traceback
import subprocess

try:
    import resource
except Exception:
    resource = None


class ColorFormatter(logging.Formatter):
    RESET = "\x1b[0m"

    NAME_COLOR = "\x1b[90m"
    FILE_COLOR = "\x1b[38;5;250m"
    LINE_COLOR = "\x1b[38;5;222m"

    LEVEL_COLORS = {
        logging.DEBUG: "\x1b[36m",
        logging.INFO: "\x1b[32m",
        logging.WARNING: "\x1b[33m",
        logging.ERROR: "\x1b[31m",
        logging.CRITICAL: "\x1b[35m",
    }

    def format(self, record: logging.LogRecord) -> str:
        record.asctime_colored = f"\x1b[90m{self.formatTime(record, self.datefmt)}{self.RESET}"
        level_color = self.LEVEL_COLORS.get(record.levelno, "")
        record.levelname_colored = f"{level_color}{record.levelname:<8}{self.RESET}"
        record.name_colored = f"{self.NAME_COLOR}{record.name}{self.RESET}"
        record.filename_colored = f"{self.FILE_COLOR}{record.filename}{self.RESET}"
        record.lineno_colored = f"{self.LINE_COLOR}{record.lineno}{self.RESET}"

        return super().format(record)


def _get_memory_usage_kb() -> int | None:
    try:
        if resource is None:
            return None
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if platform.system() == "Darwin":
            return int(usage / 1024)
        else:
            return int(usage)
    except Exception:
        return None


def _get_peak_memory_kb() -> int | None:
    """Get peak memory usage."""
    try:
        if resource is None:
            return None
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if platform.system() == "Darwin":
            return int(usage / 1024)
        else:
            return int(usage)
    except Exception:
        return None


def _get_disk_usage(path: str = ".") -> dict[str, int] | None:
    try:
        du = shutil.disk_usage(path)
        return {"total": du.total, "used": du.used, "free": du.free}
    except Exception:
        return None


def _get_git_info() -> dict[str, str | None]:
    """Get git repository information if available."""
    info = {}
    try:
        info["branch"] = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        info["branch"] = None

    try:
        info["commit"] = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        info["commit"] = None

    try:
        info["dirty"] = "yes" if subprocess.call(["git", "diff", "--quiet"], stderr=subprocess.DEVNULL) != 0 else "no"
    except Exception:
        info["dirty"] = None

    return info


def _get_env_vars() -> dict[str, str]:
    """Get relevant environment variables for debugging."""
    relevant_keys = ["PATH", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_DEFAULT_ENV", "HOME", "USER", "SHELL", "TERM", "LANG", "LC_ALL", "DEBUG", "ENV", "ENVIRONMENT", "LOG_LEVEL"]
    env = {}
    for key in relevant_keys:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _get_system_info(name: str, log_file: str | Path, start_ts: datetime, id: str) -> dict:
    info = {}
    info["session_start"] = start_ts.isoformat(sep=" ", timespec="seconds")
    info["id"] = id
    info["logger_name"] = name
    info["log_file"] = str(log_file)
    info["pid"] = os.getpid()
    info["ppid"] = os.getppid() if hasattr(os, "getppid") else None
    info["user"] = getpass.getuser()
    info["hostname"] = socket.gethostname()
    info["cwd"] = os.getcwd()
    info["argv"] = sys.argv
    info["python_version"] = platform.python_version()
    info["python_executable"] = sys.executable
    info["platform"] = platform.platform()
    info["platform_machine"] = platform.machine()
    info["platform_processor"] = platform.processor()
    info["cpu_count"] = os.cpu_count()

    in_venv = getattr(sys, "base_prefix", None) != getattr(sys, "prefix", None)
    info["virtualenv"] = os.environ.get("VIRTUAL_ENV") or ("yes" if in_venv else "no")

    info["disk"] = _get_disk_usage(info["cwd"])
    info["memory_kb_start"] = _get_memory_usage_kb()

    git_info = _get_git_info()
    if any(git_info.values()):
        info["git_branch"] = git_info["branch"]
        info["git_commit"] = git_info["commit"]
        info["git_dirty"] = git_info["dirty"]

    info["env_vars"] = _get_env_vars()

    try:
        if hasattr(os, "listdir") and os.path.exists(f"/proc/{os.getpid()}/fd"):
            info["open_fds"] = len(os.listdir(f"/proc/{os.getpid()}/fd"))
    except Exception:
        pass

    return info


def _format_info_block(info: dict) -> str:
    lines = []
    lines.append("=" * 80)
    lines.append("SESSION START")
    lines.append("=" * 80)

    lines.append(f"Timestamp:     {info['session_start']}")
    lines.append(f"Logger:        {info['logger_name']}")
    lines.append(f"Log File:      {info['log_file']}")
    lines.append("")

    lines.append("Process Information:")
    lines.append(f"  PID:         {info['pid']}")
    if info.get("ppid"):
        lines.append(f"  PPID:        {info['ppid']}")
    lines.append(f"  User:        {info['user']}")
    lines.append(f"  Hostname:    {info['hostname']}")
    lines.append(f"  CWD:         {info['cwd']}")
    if info.get("open_fds"):
        lines.append(f"  Open FDs:    {info['open_fds']}")
    lines.append("")

    lines.append("Command:")
    lines.append(f"  {' '.join(info['argv'])}")
    lines.append("")

    lines.append("Python Environment:")
    lines.append(f"  Version:     {info['python_version']}")
    lines.append(f"  Executable:  {info['python_executable']}")
    lines.append(f"  Virtual Env: {info['virtualenv']}")
    lines.append("")

    lines.append("System:")
    lines.append(f"  Platform:    {info['platform']}")
    lines.append(f"  Machine:     {info.get('platform_machine', 'N/A')}")
    lines.append(f"  Processor:   {info.get('platform_processor', 'N/A')}")
    lines.append(f"  CPU Count:   {info['cpu_count']}")
    lines.append("")

    lines.append("Resources at Start:")
    if info.get("memory_kb_start") is not None:
        mem_mb = info["memory_kb_start"] / 1024
        lines.append(f"  Memory:      {mem_mb:.2f} MB ({info['memory_kb_start']:,} KB)")
    if info.get("disk"):
        d = info["disk"]
        total_gb = d["total"] / (1024**3)
        used_gb = d["used"] / (1024**3)
        free_gb = d["free"] / (1024**3)
        used_pct = (d["used"] / d["total"]) * 100
        lines.append(f"  Disk Total:  {total_gb:.2f} GB")
        lines.append(f"  Disk Used:   {used_gb:.2f} GB ({used_pct:.1f}%)")
        lines.append(f"  Disk Free:   {free_gb:.2f} GB")
    lines.append("")

    if info.get("git_branch") or info.get("git_commit"):
        lines.append("Git Repository:")
        if info.get("git_branch"):
            lines.append(f"  Branch:      {info['git_branch']}")
        if info.get("git_commit"):
            lines.append(f"  Commit:      {info['git_commit']}")
        if info.get("git_dirty"):
            lines.append(f"  Dirty:       {info['git_dirty']}")
        lines.append("")

    if info.get("env_vars"):
        lines.append("Environment Variables:")
        for key, value in sorted(info["env_vars"].items()):
            lines.append(f"  {key}: {value}")
        lines.append("")

    lines.append("=" * 80)
    return "\n".join(lines)


def _format_end_block(start_ts: datetime, end_ts: datetime, id: str, final_mem_kb, peak_mem_kb, disk, exception_info=None) -> str:
    duration = end_ts - start_ts
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append(f"SESSION END ({id})")
    lines.append("=" * 80)
    lines.append(f"End Time:      {end_ts.isoformat(sep=' ', timespec='seconds')}")
    lines.append(f"Duration:      {duration.total_seconds():.2f} seconds ({duration})")
    lines.append("")

    lines.append("Resources at End:")
    if final_mem_kb is not None:
        mem_mb = final_mem_kb / 1024
        lines.append(f"  Memory:      {mem_mb:.2f} MB ({final_mem_kb:,} KB)")
    if peak_mem_kb is not None:
        peak_mb = peak_mem_kb / 1024
        lines.append(f"  Peak Memory: {peak_mb:.2f} MB ({peak_mem_kb:,} KB)")

    if disk:
        d = disk
        used_gb = d["used"] / (1024**3)
        free_gb = d["free"] / (1024**3)
        used_pct = (d["used"] / d["total"]) * 100
        lines.append(f"  Disk Used:   {used_gb:.2f} GB ({used_pct:.1f}%)")
        lines.append(f"  Disk Free:   {free_gb:.2f} GB")

    if exception_info:
        lines.append("")
        lines.append("UNHANDLED EXCEPTION:")
        lines.append(f"  Type:        {exception_info['type']}")
        lines.append(f"  Message:     {exception_info['message']}")
        lines.append("")
        lines.append("Traceback:")
        for line in exception_info["traceback"]:
            lines.append(f"  {line}")

    lines.append("=" * 80)
    return "\n".join(lines)


def setup_logger(name: str = "app", log_dir: str | Path = "logs", level: int = logging.INFO) -> logging.Logger:
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if getattr(root_logger, "_session_logger_configured", False):
        return logging.getLogger(name)

    root_logger.handlers.clear()

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    start_ts = datetime.now()
    date_str = start_ts.strftime("%Y%m%d")
    log_file = Path(log_dir) / f"{date_str}_{name}.log"

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = ColorFormatter(
        "%(asctime_colored)s [%(levelname_colored)s] %(name_colored)s %(filename_colored)s:%(lineno_colored)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(console_formatter)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s %(filename)s:%(lineno)d: %(message)s",
        datefmt="%H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    id = binascii.hexlify(os.urandom(16)).decode()
    sys_info = _get_system_info(name, str(log_file), start_ts, id)
    info_block = _format_info_block(sys_info)
    file_handler.stream.write(info_block + "\n\n")
    file_handler.flush()

    root_logger._session_start_ts = start_ts  # type: ignore
    root_logger._session_id = id  # type: ignore
    root_logger._session_log_file = str(log_file)  # type: ignore
    root_logger._session_file_handler = file_handler  # type: ignore
    root_logger._session_logger_configured = True  # type: ignore
    root_logger._session_exception_info = None  # type: ignore

    def _log_session_end():
        if getattr(root_logger, "_session_end_logged", False):
            return
        end_ts = datetime.now()
        final_mem = _get_memory_usage_kb()
        peak_mem = _get_peak_memory_kb()
        disk = _get_disk_usage(".")
        exception_info = getattr(root_logger, "_session_exception_info", None)  # type: ignore

        end_block = _format_end_block(
            root_logger._session_start_ts,  # type: ignore
            end_ts,
            getattr(root_logger, "_session_id", ""),
            final_mem,
            peak_mem,
            disk,
            exception_info,
        )

        file_handler.stream.write("\n" + end_block + "\n")
        file_handler.flush()
        root_logger._session_end_logged = True  # type: ignore

    atexit.register(_log_session_end)

    orig_excepthook = sys.excepthook

    def _excepthook(exc_type, exc_value, exc_traceback):
        root_logger._session_exception_info = {  # type: ignore
            "type": exc_type.__name__,
            "message": str(exc_value),
            "traceback": traceback.format_exception(exc_type, exc_value, exc_traceback),
        }

        root_logger.critical("UNHANDLED EXCEPTION", exc_info=(exc_type, exc_value, exc_traceback))

        _log_session_end()

        try:
            orig_excepthook(exc_type, exc_value, exc_traceback)
        except Exception:
            pass

    sys.excepthook = _excepthook

    return logging.getLogger(name)
