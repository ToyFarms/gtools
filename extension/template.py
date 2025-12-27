from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    INTEREST_STATE,
    Interest,
    InterestState,
    PendingPacket,
)
from gtools.proxy.extension.sdk import Extension


class ________CHANGE_ME________(Extension):
    def __init__(self) -> None:
        super().__init__(
            name="________CHANGE_ME________",
            interest=[
                Interest(
                    interest=INTEREST_STATE,
                    state=InterestState(where=[]),
                    direction=DIRECTION_CLIENT_TO_SERVER,
                    blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
                    id=0,
                ),
            ],
        )

    def process(self, event: PendingPacket) -> PendingPacket | None:
        pass

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    ________CHANGE_ME________().standalone()
