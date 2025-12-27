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
import threading
import types
import reprlib

try:
    import resource
except Exception:
    resource = None

try:
    import psutil  # type: ignore
except Exception:
    psutil = None

try:
    import importlib.metadata as importlib_metadata  # type: ignore
except Exception:
    importlib_metadata = None

LAST_LOG_CAPACITY = 200
MAX_LOCAL_REPR = 1024
MAX_MODULES_LIST = 400


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


class LastNLogHandler(logging.Handler):
    def __init__(self, capacity: int = LAST_LOG_CAPACITY):
        super().__init__()
        self.capacity = int(capacity)
        self._records: list[str] = []
        self.setLevel(logging.DEBUG)
        self._fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s %(filename)s:%(lineno)d: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            s = self._fmt.format(record)
            self._records.append(s)
            if len(self._records) > self.capacity:
                del self._records[: len(self._records) - self.capacity]
        except Exception:
            try:
                self._records.append(f"<failed to format record {record}>")
            except Exception:
                pass

    def get_records(self) -> list[str]:
        return list(self._records)


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
    relevant_keys = ["PATH", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_DEFAULT_ENV", "HOME", "USER", "SHELL", "TERM", "LANG", "LC_ALL", "DEBUG", "ENV", "ENVIRONMENT", "LOG_LEVEL"]
    env = {}
    for key in relevant_keys:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _safe_repr(value, max_len=MAX_LOCAL_REPR):
    try:
        r = reprlib.Repr()
        r.maxstring = max_len
        r.maxother = max_len
        rep = r.repr(value)
        if len(rep) > max_len:
            return rep[:max_len] + "..."
        return rep
    except Exception:
        try:
            return f"<unrepresentable {type(value).__name__}>"
        except Exception:
            return "<unrepresentable>"


def _gather_modules(limit=MAX_MODULES_LIST):
    modules = []
    for i, (name, mod) in enumerate(sorted(sys.modules.items())):
        if i >= limit:
            modules.append(f"... plus {len(sys.modules) - limit} more modules")
            break
        try:
            ver = None
            path = None
            if isinstance(mod, types.ModuleType):
                path = getattr(mod, "__file__", None)
                ver = getattr(mod, "__version__", None)
                if ver is None and importlib_metadata is not None:
                    try:
                        ver = importlib_metadata.version(name)
                    except Exception:
                        ver = None
            modules.append(f"{name} {ver or ''} {path or ''}".strip())
        except Exception:
            modules.append(f"{name} <failed to inspect>")
    return modules


def _gather_psutil_info(pid=None):
    if psutil is None:
        return None
    try:
        p = psutil.Process(pid or os.getpid())
        info = {
            "cmdline": p.cmdline(),
            "cwd": p.cwd(),
            "exe": getattr(p, "exe", lambda: None)(),
            "uids": getattr(p, "uids", lambda: None)(),
            "gids": getattr(p, "gids", lambda: None)(),
            "num_threads": p.num_threads(),
            "threads": [t._asdict() if hasattr(t, "_asdict") else str(t) for t in p.threads()],
            "open_files": [f.path for f in p.open_files()],
            "connections": [dict(fd=c.fd, laddr=getattr(c, "laddr", None), raddr=getattr(c, "raddr", None), status=getattr(c, "status", None)) for c in p.net_connections(kind="inet")],
            "num_fds": getattr(p, "num_fds", lambda: None)(),
            "memory_info": getattr(p, "memory_info", lambda: None)()._asdict() if hasattr(getattr(p, "memory_info", None)(), "_asdict") else str(getattr(p, "memory_info", lambda: None)()),  # type: ignore
            "cpu_percent": p.cpu_percent(interval=0.0),
        }
        return info
    except Exception:
        return None


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
    lines.append(f"SESSION START {info['id']}")
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


def _format_exception_block(
    start_ts: datetime, end_ts: datetime, id: str, final_mem_kb, peak_mem_kb, disk, exception_info=None, recent_logs=None, all_threads=None, modules=None, psutil_info=None
) -> str:
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

    if psutil_info:
        try:
            lines.append("")
            lines.append("psutil Process Info:")
            for k, v in psutil_info.items():
                lines.append(f"  {k}: {v}")
        except Exception:
            pass

    if recent_logs:
        lines.append("")
        lines.append("Recent Log Records (most recent last):")
        for l in recent_logs[-LAST_LOG_CAPACITY:]:
            lines.append(f"  {l}")

    if modules:
        lines.append("")
        lines.append("Loaded Modules:")
        for m in modules:
            lines.append(f"  {m}")

    if all_threads:
        lines.append("")
        lines.append("All Threads (stack traces):")
        for tname, stack_lines in all_threads.items():
            lines.append(f"Thread: {tname}")
            for sl in stack_lines:
                lines.append(f"  {sl}")
            lines.append("")

    if exception_info:
        lines.append("")
        lines.append("UNHANDLED EXCEPTION:")
        lines.append(f"  Type:        {exception_info.get('type')}")
        lines.append(f"  Message:     {exception_info.get('message')}")
        lines.append("")
        lines.append("Traceback (most recent call last):")
        for line in exception_info.get("traceback", []):
            lines.append(f"  {line.rstrip()}")
        if exception_info.get("frame_locals"):
            lines.append("")
            lines.append("Locals in top frames:")
            for frame_desc, locals_map in exception_info["frame_locals"].items():
                lines.append(f"Frame: {frame_desc}")
                for k, v in locals_map.items():
                    lines.append(f"  {k}: {v}")
                lines.append("")
    lines.append("=" * 80)
    return "\n".join(lines)


def _collect_exception_context(exc_type, exc_value, exc_tb, logger) -> dict:
    """Collect enhanced exception context: locals, thread stacks, modules, psutil info, recent logs."""
    ctx = {}
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
    ctx["traceback"] = tb_lines
    ctx["type"] = getattr(exc_type, "__name__", str(exc_type))
    ctx["message"] = str(exc_value)

    frame_locals = {}
    try:
        tb = exc_tb
        depth = 0
        while tb and depth < 5:
            frame = tb.tb_frame
            lineno = tb.tb_lineno
            code = frame.f_code
            frame_desc = f"{code.co_filename}:{code.co_name}:{lineno}"
            locals_snapshot = {}
            try:
                for k, v in frame.f_locals.items():
                    try:
                        locals_snapshot[k] = _safe_repr(v)
                    except Exception:
                        locals_snapshot[k] = "<unrepresentable>"
                frame_locals[frame_desc] = locals_snapshot
            except Exception:
                frame_locals[frame_desc] = {"<error>": "<could not obtain locals>"}
            tb = tb.tb_next
            depth += 1
    except Exception:
        frame_locals["<error>"] = {"<error>": "<collecting locals failed>"}

    ctx["frame_locals"] = frame_locals

    threads_stacks = {}
    try:
        current_frames = sys._current_frames()
        for tid, frame in current_frames.items():
            try:
                tname = None
                for t in threading.enumerate():
                    if getattr(t, "ident", None) == tid:
                        tname = f"{t.name} (ident={tid})"
                        break
                if tname is None:
                    tname = f"unknown (ident={tid})"
                stack_lines = traceback.format_stack(frame)
                threads_stacks[tname] = [sl.rstrip() for sl in stack_lines]
            except Exception:
                threads_stacks[f"thread_{tid}"] = ["<failed to format thread stack>"]
    except Exception:
        threads_stacks["<error>"] = ["<could not collect thread stacks>"]

    ctx["all_threads"] = threads_stacks

    try:
        ctx["modules"] = _gather_modules()
    except Exception:
        ctx["modules"] = ["<failed to gather modules>"]

    try:
        ctx["psutil_info"] = _gather_psutil_info()
    except Exception:
        ctx["psutil_info"] = None

    try:
        recent = None
        if hasattr(logger, "_last_log_handler") and getattr(logger, "_last_log_handler") is not None:
            recent = logger._last_log_handler.get_records()
        else:
            root = logging.getLogger()
            for h in getattr(root, "handlers", []):
                if isinstance(h, LastNLogHandler):
                    recent = h.get_records()
                    break
        ctx["recent_logs"] = recent
    except Exception:
        ctx["recent_logs"] = None

    return ctx


def setup_logger(name: str = "app", log_dir: str | Path = "logs", level: int = logging.INFO) -> logging.Logger:
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if getattr(root_logger, "_session_logger_configured", False):
        return logging.getLogger(name)

    root_logger.handlers.clear()

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    start_ts = datetime.now()
    date_str = start_ts.strftime("%Y%m%d_%H%M%S")
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
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)

    lastn_handler = LastNLogHandler(capacity=LAST_LOG_CAPACITY)
    lastn_handler.setLevel(logging.DEBUG)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(lastn_handler)

    id = binascii.hexlify(os.urandom(16)).decode()
    sys_info = _get_system_info(name, str(log_file), start_ts, id)
    info_block = _format_info_block(sys_info)
    try:
        file_handler.stream.write(info_block + "\n\n")
        file_handler.flush()
    except Exception:
        try:
            console_handler.stream.write(info_block + "\n\n")
            console_handler.flush()
        except Exception:
            pass

    root_logger._session_start_ts = start_ts  # type: ignore
    root_logger._session_id = id  # type: ignore
    root_logger._session_log_file = str(log_file)  # type: ignore
    root_logger._session_file_handler = file_handler  # type: ignore
    root_logger._session_logger_configured = True  # type: ignore
    root_logger._session_exception_info = None  # type: ignore
    root_logger._last_log_handler = lastn_handler  # type: ignore

    def _log_session_end():
        if getattr(root_logger, "_session_end_logged", False):
            return
        end_ts = datetime.now()
        final_mem = _get_memory_usage_kb()
        peak_mem = _get_peak_memory_kb()
        disk = _get_disk_usage(".")
        exception_info = getattr(root_logger, "_session_exception_info", None)  # type: ignore

        recent = None
        try:
            recent = root_logger._last_log_handler.get_records()  # type: ignore
        except Exception:
            recent = None

        all_threads = None
        modules = None
        psutil_info = None
        if exception_info and isinstance(exception_info, dict):
            all_threads = exception_info.get("all_threads")
            modules = exception_info.get("modules")
            psutil_info = exception_info.get("psutil_info")
        else:
            try:
                cf = {}
                current_frames = sys._current_frames()
                for tid, frame in current_frames.items():
                    try:
                        tname = None
                        for t in threading.enumerate():
                            if getattr(t, "ident", None) == tid:
                                tname = f"{t.name} (ident={tid})"
                                break
                        if tname is None:
                            tname = f"unknown (ident={tid})"
                        stack_lines = traceback.format_stack(frame)
                        cf[tname] = [sl.rstrip() for sl in stack_lines]
                    except Exception:
                        cf[f"thread_{tid}"] = ["<failed to format thread stack>"]
                all_threads = cf
            except Exception:
                all_threads = None
            try:
                modules = _gather_modules()
            except Exception:
                modules = None
            try:
                psutil_info = _gather_psutil_info()
            except Exception:
                psutil_info = None

        end_block = _format_exception_block(
            root_logger._session_start_ts,  # type: ignore
            end_ts,
            getattr(root_logger, "_session_id", ""),
            final_mem,
            peak_mem,
            disk,
            exception_info=exception_info,
            recent_logs=recent,
            all_threads=all_threads,
            modules=modules,
            psutil_info=psutil_info,
        )

        try:
            file_handler.stream.write("\n" + end_block + "\n")
            file_handler.flush()
        except Exception:
            try:
                console_handler.stream.write("\n" + end_block + "\n")
                console_handler.flush()
            except Exception:
                pass
        root_logger._session_end_logged = True  # type: ignore

    atexit.register(_log_session_end)

    orig_excepthook = sys.excepthook

    def _excepthook(exc_type, exc_value, exc_traceback):
        try:
            enriched = _collect_exception_context(exc_type, exc_value, exc_traceback, root_logger)
            root_logger._session_exception_info = enriched  # type: ignore
            root_logger.critical("UNHANDLED EXCEPTION OCCURRED — writing full context to log file.", exc_info=(exc_type, exc_value, exc_traceback))
            end_ts = datetime.now()
            final_mem = _get_memory_usage_kb()
            peak_mem = _get_peak_memory_kb()
            disk = _get_disk_usage(".")
            recent = enriched.get("recent_logs")
            all_threads = enriched.get("all_threads")
            modules = enriched.get("modules")
            psutil_info = enriched.get("psutil_info")
            end_block = _format_exception_block(
                root_logger._session_start_ts,  # type: ignore
                end_ts,
                getattr(root_logger, "_session_id", ""),
                final_mem,
                peak_mem,
                disk,
                exception_info=enriched,
                recent_logs=recent,
                all_threads=all_threads,
                modules=modules,
                psutil_info=psutil_info,
            )
            try:
                file_handler.stream.write("\n" + end_block + "\n")
                file_handler.flush()
            except Exception:
                try:
                    console_handler.stream.write("\n" + end_block + "\n")
                    console_handler.flush()
                except Exception:
                    pass
        except Exception:
            try:
                logging.getLogger(name).exception("Failed while collecting exception context", exc_info=True)
            except Exception:
                pass

        try:
            orig_excepthook(exc_type, exc_value, exc_traceback)
        except Exception:
            pass

    sys.excepthook = _excepthook

    return logging.getLogger(name)
