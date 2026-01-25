from pyglm.glm import vec2

from gtools.core.growtopia.packet import TankFlags
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


class Particle(Extension):
    def __init__(self) -> None:
        super().__init__(name="analyze", interest=[Interest(interest=INTEREST_STATE_UPDATE)])
        self.id = 0
        self.alternate = 0

    @dispatch(
        Interest(
            interest=INTEREST_STATE,
            state=InterestState(where=[s.tank_flags.bit_test(s.uint(TankFlags.PUNCH))]),
            direction=DIRECTION_CLIENT_TO_SERVER,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        )
    )
    def _on_punch(self, _event: PendingPacket) -> PendingPacket | None:
        self.send_particle(self.id, self.alternate, abs=self.state.me.pos + vec2(0, -64))

    @dispatch(s.command("/s", s.auto))
    def send(self, event: PendingPacket) -> PendingPacket | None:
        id = int(s.parse_command(event))
        self.send_particle(id, self.alternate, abs=self.state.me.pos + vec2(0, -32))
        return self.cancel()

    @dispatch(s.command("/set", s.auto))
    def set_id(self, event: PendingPacket) -> PendingPacket | None:
        self.id = int(s.parse_command(event))
        self.console_log(f"id set to {self.id}")
        return self.cancel()

    @dispatch(s.command("/alt", s.auto))
    def set_alternate(self, event: PendingPacket) -> PendingPacket | None:
        self.alternate = int(s.parse_command(event))
        self.console_log(f"alternate set to {self.id}")
        return self.cancel()

    @dispatch(s.command("/c", s.auto))
    def complete(self, event: PendingPacket) -> PendingPacket | None:
        with open("particle.txt", "a") as f:
            name = s.parse_command(event)
            f.write(f"{self.id}={name.strip()}\n")
            self.console_log(f"saved id {self.id} as '{name}', next!")
            self.id += 1
        return self.cancel()

    @dispatch(s.command_toggle("/n", s.auto))
    def next(self, _event: PendingPacket) -> PendingPacket | None:
        self.id += 1
        self.console_log(f"next id {self.id}")
        return self.cancel()

    @dispatch(s.command_toggle("/p", s.auto))
    def prev(self, _event: PendingPacket) -> PendingPacket | None:
        self.id -= 1
        self.console_log(f"prev id {self.id}")
        return self.cancel()

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    Particle().standalone()
