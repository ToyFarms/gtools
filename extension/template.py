from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    INTEREST_STATE,
    INTEREST_STATE_UPDATE,
    Interest,
    InterestState,
    PendingPacket,
)
from gtools.proxy.extension.sdk import Extension, dispatch
from gtools.proxy.extension.sdk_utils import helper


s = helper()


class FOO(Extension):
    def __init__(self) -> None:
        super().__init__(name="FOO", interest=[Interest(interest=INTEREST_STATE_UPDATE)])

    @dispatch(
        Interest(
            interest=INTEREST_STATE,
            state=InterestState(where=[]),
            direction=DIRECTION_CLIENT_TO_SERVER,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        ),
    )
    def on_something(self, event: PendingPacket) -> PendingPacket | None:
        pass

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    FOO().standalone()
