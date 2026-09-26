from gtools.core.growtopia.packet import NetPacket, TankFlags
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    DIRECTION_CLIENT_TO_SERVER,
    INTEREST_STATE,
    Interest,
    InterestState,
    PendingPacket,
)
from gtools.proxy.extension.client.sdk import Extension, dispatch
from gtools.proxy.extension.client.sdk_utils import helper

s = helper()


class Inspector(Extension):
    def __init__(self) -> None:
        super().__init__(name="Inspector")
        self.inspect = False

    @dispatch(
        Interest(
            interest=INTEREST_STATE,
            state=InterestState(where=[s.tank_flags.bit_test(s.uint(TankFlags.PUNCH))]),
            direction=DIRECTION_CLIENT_TO_SERVER,
            blocking_mode=BLOCKING_MODE_BLOCK,
            id=s.auto,
        )
    )
    def on_something(self, event: PendingPacket) -> PendingPacket | None:
        if self.inspect and self.state.world:
            pkt = NetPacket.deserialize(event.buf)
            self.console_log(f"{self.state.world.get_tile(pkt.tank.int_x, pkt.tank.int_y)}")
            return self.cancel()

    @dispatch(s.command("/t", id=s.auto))
    def _toggle(self, event: PendingPacket) -> PendingPacket | None:
        self.inspect = True
        return self.cancel()

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    Inspector().standalone()
