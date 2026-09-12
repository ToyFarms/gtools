import atexit
import pickle
import threading
import time
from pathlib import Path
from typing import Any, ClassVar

from gtools import setting

_MISSING = object()


class _PersistMarker:
    __slots__ = ("default",)

    def __init__(self, default: Any) -> None:
        self.default = default


def persist[T](default: T) -> T:
    return _PersistMarker(default)  # type: ignore[return-value]


class PersistentStore:
    def __init__(self, path: Path, min_interval: float = 0.1) -> None:
        self.path = path
        self.min_interval = min_interval

        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self._dirty = False
        self._last_write = 0.0

        if self.path.exists():
            try:
                with self.path.open("rb") as f:
                    self._data = pickle.load(f)
            except (pickle.UnpicklingError, EOFError, OSError):
                self._data = {}

        atexit.register(self.flush)

    def has(self, key: str) -> bool:
        with self._lock:
            return key in self._data

    def get(self, key: str, default: Any = _MISSING) -> Any:
        with self._lock:
            if key in self._data:
                return self._data[key]
        if default is _MISSING:
            raise KeyError(key)
        return default

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._dirty = True

            now = time.monotonic()
            if now - self._last_write >= self.min_interval:
                self._write_locked()

    def _write_locked(self) -> None:
        """Must be called while holding self._lock."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("wb") as f:
            pickle.dump(self._data, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(self.path)
        self._dirty = False
        self._last_write = time.monotonic()

    def flush(self) -> None:
        with self._lock:
            if self._dirty:
                self._write_locked()


class PersistentMixin:
    _persist_min_interval: float = 0.1
    _persist_store: ClassVar[PersistentStore]
    _persisted_keys: ClassVar[set[str]]

    def __setattr__(self, name: str, value: Any) -> None:
        if isinstance(value, _PersistMarker):
            store = self.__dict__.get("_persist_store")
            if store is None:
                namespace = getattr(self, "name", None) or type(self).__name__
                store = PersistentStore(
                    setting.appdir / f"extension_data/{namespace}.pkl",
                    min_interval=self._persist_min_interval,
                )
                object.__setattr__(self, "_persist_store", store)
                object.__setattr__(self, "_persisted_keys", set())

            if store.has(name):
                real_value = store.get(name)
            else:
                real_value = value.default
                store.set(name, real_value)

            self._persisted_keys.add(name)
            object.__setattr__(self, name, real_value)
            return

        object.__setattr__(self, name, value)

        persisted_keys = self.__dict__.get("_persisted_keys")
        if persisted_keys and name in persisted_keys:
            self._persist_store.set(name, value)

    def flush_persistence(self) -> None:
        store = self.__dict__.get("_persist_store")
        if store is not None:
            store.flush()
