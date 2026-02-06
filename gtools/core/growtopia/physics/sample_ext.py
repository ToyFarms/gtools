import time
from gtools.core.growtopia.packet import NetPacket
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    INTEREST_STATE,
    INTEREST_STATE_UPDATE,
    Interest,
    PendingPacket,
)
from gtools.proxy.extension.sdk import Extension, dispatch
from gtools.proxy.extension.sdk_utils import helper


s = helper()


class MovementAnalyzer(Extension):
    def __init__(self) -> None:
        super().__init__(name="MovementAnalyzer", interest=[Interest(interest=INTEREST_STATE_UPDATE)])
        self.output = ""
        self.rec = False
        self.first_move = -1

    @dispatch(
        Interest(
            interest=INTEREST_STATE,
            direction=DIRECTION_CLIENT_TO_SERVER,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        ),
    )
    def on_something(self, event: PendingPacket) -> PendingPacket | None:
        if self.first_move == -1:
            self.first_move = time.time()

        pkt = NetPacket.deserialize(event.buf).tank
        line = f"{time.time() - self.first_move} {pkt.flags.name}, {pkt.vector_x}, {pkt.vector_y}"
        if self.rec:
            with open(self.output, "a") as f:
                f.write(f"{line}\n")
            print(f"write {line}")
        else:
            print(line)

    @dispatch(s.command("/rec", s.auto))
    def _rec(self, event: PendingPacket) -> PendingPacket | None:
        name = s.parse_command(event)
        self.output = name
        self.rec = not self.rec
        if self.rec:
            self.first_move = -1
        self.console_log(f"rec is now {self.rec}")

        return self.cancel()

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    MovementAnalyzer().standalone()
