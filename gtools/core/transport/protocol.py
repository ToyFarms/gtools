from typing import Protocol


class Transport[Send, Recv](Protocol):
    def __init__(self) -> None:
        pass

    def send(self, payload: Send) -> None: ...
    def recv(self) -> Recv: ...
