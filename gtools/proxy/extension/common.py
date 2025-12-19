import threading
from typing import Callable


class Waitable[T]:
    def __init__(self, initial: T) -> None:
        self._value = initial
        self._cond = threading.Condition()

    def set(self, value: T) -> None:
        with self._cond:
            self._value = value
            self._cond.notify_all()

    def update(self, fn: Callable[[T], T]) -> None:
        with self._cond:
            self._value = fn(self._value)
            self._cond.notify_all()

    def get(self) -> T:
        with self._cond:
            return self._value

    def wait_for(
        self,
        predicate: Callable[[T], bool],
        timeout: float | None = None,
    ) -> T:
        with self._cond:
            self._cond.wait_for(lambda: predicate(self._value), timeout)
            return self._value

    def wait_true(self, timeout: float | None = None) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: bool(self._value), timeout)

    def wait_false(self, timeout: float | None = None) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: not bool(self._value), timeout)
