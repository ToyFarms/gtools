import asyncio
import base64
import json
from queue import Queue
import websockets

from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_UNSPECIFIED,
    INTEREST_STATE,
    INTEREST_STATE_UPDATE,
    Interest,
    PendingPacket,
)
from gtools.proxy.extension.sdk import Extension, dispatch
from gtools.proxy.extension.sdk_utils import helper

s = helper()

shared = Queue[PendingPacket]()


class Relay(Extension):
    def __init__(self) -> None:
        super().__init__(name="relay", interest=[Interest(interest=INTEREST_STATE_UPDATE)])

    @dispatch(
        Interest(
            interest=INTEREST_STATE,
            direction=DIRECTION_UNSPECIFIED,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        ),
    )
    def relay(self, event: PendingPacket) -> PendingPacket | None:
        print(event)
        shared.put(event)

    def destroy(self) -> None:
        pass


async def handler(websocket: websockets.ServerConnection):
    loop = asyncio.get_running_loop()
    while True:
        event = await loop.run_in_executor(None, shared.get)
        await websocket.send(event.SerializeToString())


async def main():
    async with websockets.serve(handler, "127.0.0.1", 8000):
        await asyncio.Future()


if __name__ == "__main__":
    Relay().start(block=False)
    asyncio.run(main())
