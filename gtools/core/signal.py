import threading
from typing import Callable
from contextlib import contextmanager


class Signal[T]:
    def __init__(self, initial_value: T) -> None:
        self._value: T = initial_value
        self._condition = threading.Condition(threading.RLock())
        self._is_derived = False
        self._derive_fn: Callable[[], T] | None = None
        self._dependencies: tuple[Signal, ...] = ()
        self._dependents: list[Signal] = []

    @classmethod
    def derive(cls, derive_fn: Callable[[], T], *dependencies: "Signal") -> "Signal[T]":
        if not dependencies:
            raise ValueError("derived signal must have at least one dependency")

        initial = derive_fn()
        signal = cls(initial)
        signal._is_derived = True
        signal._derive_fn = derive_fn
        signal._dependencies = dependencies

        for dep in dependencies:
            dep._add_dependent(signal)

        return signal

    def _add_dependent(self, dependent: "Signal") -> None:
        with self._condition:
            if dependent not in self._dependents:
                self._dependents.append(dependent)

    def _derive(self) -> None:
        if not self._is_derived or self._derive_fn is None:
            return

        with self._condition:
            old_value = self._value
            new_value = self._derive_fn()

            if new_value != old_value:
                self._value = new_value
                self._condition.notify_all()

                for dependent in self._dependents:
                    dependent._derive()

    def get(self) -> T:
        with self._condition:
            return self._value

    def set(self, value: T) -> None:
        if self._is_derived:
            raise ValueError("cannot set value of derived signal")

        with self._condition:
            self._value = value
            self._condition.notify_all()

            for dependent in self._dependents:
                dependent._derive()

    def update(self, fn: Callable[[T], T]) -> None:
        if self._is_derived:
            raise ValueError("cannot update value of derived signal")

        with self._condition:
            self._value = fn(self._value)
            self._condition.notify_all()

            for dependent in self._dependents:
                dependent._derive()

    def wait_until(self, predicate: Callable[[T], bool], timeout: float | None = None) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: predicate(self._value), timeout)

    def wait_value(self, target: T, timeout: float | None = None) -> bool:
        return self.wait_until(lambda x: x == target, timeout)

    def wait_true(self, timeout: float | None = None) -> bool:
        return self.wait_until(lambda x: bool(x), timeout)

    def wait_false(self, timeout: float | None = None) -> bool:
        return self.wait_until(lambda x: not bool(x), timeout)

    @contextmanager
    def batch_update(self):
        if self._is_derived:
            raise ValueError("cannot batch update derived signal")

        with self._condition:
            yield
            self._condition.notify_all()
            for dependent in self._dependents:
                dependent._derive()

    @property
    def is_derived(self) -> bool:
        return self._is_derived

    def __repr__(self) -> str:
        kind = "derived" if self._is_derived else "mutable"
        return f"Signal[{kind}]({self._value!r})"

    def __bool__(self) -> bool:
        return bool(self.get())
