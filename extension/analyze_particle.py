from pyglm.glm import vec2

from gtools.core.growtopia.packet import NetPacket, TankFlags
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    INTEREST_STATE,
    INTEREST_STATE_UPDATE,
    Interest,
    InterestState,
    PendingPacket,
)
from gtools.proxy.extension.sdk import Extension
from gtools.proxy.extension.sdk_utils import helper

s = helper()


class Particle(Extension):
    def __init__(self) -> None:
        # TODO: design a better command design
        super().__init__(
            name="analyze",
            interest=[
                Interest(
                    interest=INTEREST_STATE_UPDATE,
                ),
                Interest(
                    interest=INTEREST_STATE,
                    state=InterestState(where=[s.tank_flags.bit_test(s.uint(TankFlags.PUNCH))]),
                    direction=DIRECTION_CLIENT_TO_SERVER,
                    blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
                    id=0,
                ),
                s.command("/set", 1),  # set id
                s.command("/c", 2),  # complete
                s.command_toggle("/n", 3),  # next
                s.command_toggle("/p", 4),  # prev
                s.command("/a", 5),  # set the first args
                s.command("/b", 6),  # set the second args
                s.command("/s", 7),  # send
            ],
        )
        self.id = 0
        self.first_args = 0
        self.second_args = 0

    def process(self, event: PendingPacket) -> PendingPacket | None:
        match event.interest_id:
            case 0:
                self.send_particle(self.id, self.first_args, self.second_args, abs=self.state.me.pos + vec2(0, -64))
            case 7:
                id = int(NetPacket.deserialize(event.buf).generic_text.relative[b"text", 1].decode().removeprefix("/s"))
                self.send_particle(id, self.first_args, self.second_args, abs=self.state.me.pos + vec2(0, -32))
                return self.cancel()
            case 1:
                self.id = int(NetPacket.deserialize(event.buf).generic_text.relative[b"text", 1].decode().removeprefix("/set"))
                self.console_log(f"id set to {self.id}")
                return self.cancel()
            case 5:
                self.first_args = int(NetPacket.deserialize(event.buf).generic_text.relative[b"text", 1].decode().removeprefix("/a"))
                self.console_log(f"first set to {self.first_args}")
                return self.cancel()
            case 6:
                self.second_args = int(NetPacket.deserialize(event.buf).generic_text.relative[b"text", 1].decode().removeprefix("/b"))
                self.console_log(f"second set to {self.second_args}")
                return self.cancel()
            case 2:
                with open("particle.txt", "a") as f:
                    name = NetPacket.deserialize(event.buf).generic_text.relative[b"text", 1].decode().removeprefix("/c")
                    f.write(f"{self.id}={name.strip()}\n")
                    self.console_log(f"saved id {self.id} as '{name}', next!")
                    self.id += 1
                return self.cancel()
            case 3:
                self.id += 1
                self.console_log(f"next id {self.id}")
                return self.cancel()
            case 4:
                self.id -= 1
                self.console_log(f"prev id {self.id}")
                return self.cancel()

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    Particle().standalone()
