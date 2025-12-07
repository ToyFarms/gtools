from __future__ import annotations

import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import time
from typing import Callable, Protocol


class Event(Protocol):
    def send(self, channel: str = "default") -> None: ...
    def send_and_wait(self, channel: str = "default") -> None: ...


@dataclass
class _Handler[E]:
    func: Callable[[str, E], None]
    channel: str | None
    event_type: type[E]


class EventBus:
    def __init__(self, max_workers: int = 10):
        self._handlers: dict[type, list[_Handler]] = defaultdict(list)
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def register[E](
        self, event_type: type[E], channel: str | None = None
    ) -> Callable[[Callable[[str, E], None]], Callable[[str, E], None]]:
        def decorator(func: Callable[[str, E], None]) -> Callable[[str, E], None]:
            with self._lock:
                self._handlers[event_type].append(
                    _Handler(func=func, channel=channel, event_type=event_type)
                )
            return func

        return decorator

    def emit(self, event: object, channel: str, wait: bool = False) -> None:
        event_type = type(event)

        with self._lock:
            handlers = [
                h
                for h in self._handlers.get(event_type, [])
                if h.channel is None or h.channel == channel
            ]

        if not handlers:
            return

        if wait:
            for handler in handlers:
                handler.func(channel, event)
        else:
            for handler in handlers:
                self._executor.submit(handler.func, channel, event)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)


_bus = EventBus()


def listen[E](
    event_type: type[E], channel: str | None = None
) -> Callable[[Callable[[str, E], None]], Callable[[str, E], None]]:
    return _bus.register(event_type, channel)


class EventMixin:
    def send(self, channel: str = "default") -> None:
        _bus.emit(self, channel, wait=False)

    def send_and_wait(self, channel: str = "default") -> None:
        _bus.emit(self, channel, wait=True)


def shutdown_event_bus() -> None:
    _bus.shutdown()


if __name__ == "__main__":
    @dataclass
    class SomeEvent(EventMixin):
        value: int

    @listen(SomeEvent)
    def on_change_global(channel: str, event: SomeEvent) -> None:
        print(f"Global: {channel} - {event.value}")

    def on_change_specific(channel: str, event: SomeEvent) -> None:
        print(f"Specific: {channel} - {event.value}")
        time.sleep(1)

    listen(SomeEvent, channel="specific")(on_change_specific)

    SomeEvent(value=1).send_and_wait(channel="specific")
    SomeEvent(value=2).send()
    SomeEvent(value=3).send_and_wait()
    print("done")
