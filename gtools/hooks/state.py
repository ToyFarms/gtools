"""The hook's own persistent state.

This is deliberately not a ``Setting``: the hook owns its state end to end
(defaults, persistence, and the mapping onto the runtime). Editing goes
through this module -- mutate :data:`state`, call :func:`save`, then push via
``apply_hook_state`` -- so no hot-reload detection is needed anywhere.
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from gtools.core.utils import get_home

STATE_FILE = get_home() / ".gtools" / "hook_state.json"

_LOCK = threading.RLock()
_state: HookState | None = None


@dataclass
class HookState:
    log_level: int = 1
    allow_any_module: bool = False
    low_power: bool = False
    low_power_fps: int = 0
    low_power_skip_draws: bool = False


def state_path() -> Path:
    return STATE_FILE


def load() -> HookState:
    """The current state, re-read from disk: multiple processes (the proxy and
    the gui) and the gui's editor all stay coherent without a watcher, and a
    push always carries what is actually persisted."""
    global _state
    with _LOCK:
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        known = {f.name for f in fields(HookState)}
        clean = {key: value for key, value in data.items() if key in known}
        _state = HookState(**clean)
        return _state


def save(state: HookState | None = None) -> None:
    """Persist ``state`` (or the last loaded one)."""
    global _state
    with _LOCK:
        _state = state if state is not None else (_state or load())
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(asdict(_state), indent=2), encoding="utf-8")
