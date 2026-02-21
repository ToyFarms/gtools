from abc import ABC, abstractmethod
from dataclasses import dataclass
import queue


@dataclass(slots=True)
class TouchContactEvent:
    contact_id: int
    norm_x: float  # normalized [0.0, 1.0] relative to logical range
    norm_y: float  # normalized [0.0, 1.0] relative to logical range
    x: int  # mapped to virtual screen pixels
    y: int  # mapped to virtual screen pixels
    tip_active: bool
    timestamp: float


class TouchRouterBase(ABC):
    def __init__(self, window) -> None:
        self._window = window
        self._queue: queue.SimpleQueue[TouchContactEvent] = queue.SimpleQueue()

    def poll(self) -> list[TouchContactEvent]:
        events: list[TouchContactEvent] = []
        while not self._queue.empty():
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return events

    @abstractmethod
    def install(self) -> None: ...
    @abstractmethod
    def uninstall(self) -> None: ...
