import logging
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    DIRECTION_CLIENT_TO_SERVER,
    INTEREST_GENERIC_TEXT,
    Event,
    Interest,
    InterestGenericText,
    Packet,
)
from gtools.proxy.extension.sdk import Extension
from gtools.core.growtopia.packet import NetPacket


class CommandExtension(Extension):
    def __init__(self) -> None:
        logging.basicConfig(level=logging.DEBUG)

        super().__init__(
            name="command",
            interest=[
                Interest(
                    interest=INTEREST_GENERIC_TEXT,
                    blocking_mode=BLOCKING_MODE_BLOCK,
                    direction=DIRECTION_CLIENT_TO_SERVER,
                    generic_text=InterestGenericText(regex=rb".*"),
                ),
            ],
        )

    def process(self, event: Event) -> Packet | None:
        pkt = NetPacket.deserialize(event.buf)
        print(pkt.generic_text)

        return Packet(type=Packet.TYPE_FORWARD_NOT_MODIFIED)

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    CommandExtension().start(block=True)
