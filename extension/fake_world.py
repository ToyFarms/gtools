from gtools.core.growtopia.packet import NetPacket, PreparedPacket
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    INTEREST_STATE,
    INTEREST_STATE_UPDATE,
    Interest,
    InterestState,
    PendingPacket,
)
from gtools.proxy.extension.client.sdk import Extension, dispatch
from gtools.proxy.extension.client.sdk_utils import helper


s = helper()


class FakeWorld(Extension):
    def __init__(self) -> None:
        super().__init__(name="FakeWorld", interest=[Interest(interest=INTEREST_STATE_UPDATE)])

    def on_connect(self) -> None:
        self.push(PreparedPacket(NetPacket))


if __name__ == "__main__":
    input("this will send fake world data to client, you sure?")
    FakeWorld().standalone()
