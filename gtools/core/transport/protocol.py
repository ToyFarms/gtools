from enum import Enum, auto
from typing import Protocol


class Event(Enum):
    NONE = auto()
    CONNECTED = auto()
    DISCONNECTED = auto()


class Transport[Send, Recv](Protocol):
    def __init__(self) -> None:
        pass

    def send(self, payload: Send) -> None: ...
    def recv(self) -> Recv: ...
    def recv_event(self) -> Event: ...
