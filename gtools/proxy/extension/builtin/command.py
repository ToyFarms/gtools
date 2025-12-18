import logging
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    DIRECTION_CLIENT_TO_SERVER,
    INTEREST_GENERIC_TEXT,
    Interest,
    InterestGenericText,
    PendingPacket,
)
from gtools.proxy.extension.sdk import Extension
from gtools.core.growtopia.packet import NetPacket


class CommandExtension(Extension):
    def __init__(self) -> None:
        logging.basicConfig(level=logging.DEBUG)

        # TODO: how do extension interact with each other, especially for common operation like command
        # maybe some sort of special interest, but how will the protocol generalizes?
        # maybe extension can expose a set of function, then it can reuse infra from process
        # or maybe its not needed, well see
        super().__init__(
            name="command",
            interest=[
                Interest(
                    interest=INTEREST_GENERIC_TEXT,
                    blocking_mode=BLOCKING_MODE_BLOCK,
                    direction=DIRECTION_CLIENT_TO_SERVER,
                    generic_text=InterestGenericText(),
                ),
            ],
        )

    def process(self, event: PendingPacket) -> PendingPacket | None:
        pkt = NetPacket.deserialize(event.buf)
        print(pkt.generic_text)

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    CommandExtension().start(block=True)
