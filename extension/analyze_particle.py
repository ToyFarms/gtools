import logging

from pyglm.glm import vec2

from gtools.core.growtopia.packet import NetPacket
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    INTEREST_STATE_UPDATE,
    INTEREST_TILE_CHANGE_REQUEST,
    Interest,
    InterestTileChangeRequest,
    PendingPacket,
)
from gtools.proxy.extension.sdk import Extension


class Particle(Extension):
    def __init__(self) -> None:
        logging.basicConfig(level=logging.DEBUG)

        # TODO: design a better command design
        super().__init__(
            name="crazy",
            interest=[
                Interest(
                    interest=INTEREST_STATE_UPDATE,
                ),
                Interest(
                    interest=INTEREST_TILE_CHANGE_REQUEST,
                    tile_change_request=InterestTileChangeRequest(
                        where=[
                            self.tank_value == self.uint32_t(18),
                        ]
                    ),
                    direction=DIRECTION_CLIENT_TO_SERVER,
                    blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
                    id=0
                ),
                self.command("/set", 1),  # set id
                self.command("/c", 2),  # complete
                self.command("/n", 3),  # next
                self.command("/p", 4),  # prev
            ],
        )
        self.id = 0

    def process(self, event: PendingPacket) -> PendingPacket | None:
        match event.interest_id:
            case 0:
                self.send_particle(self.id, abs=self.state.me.pos + vec2(0, -64))
            case 1:
                self.id = int(NetPacket.deserialize(event.buf).game_message[b"text", 1].decode().removeprefix("/set"))
                self.console_log(f"id set to {self.id}")
            case 2:
                with open("particle.txt", "a") as f:
                    name = NetPacket.deserialize(event.buf).game_message[b"text", 1].decode().removeprefix("/c")
                    f.write(name)
                    self.console_log(f"saved id {self.id} as '{name}', next!")
                    self.id += 1
            case 3:
                self.id += 1
                self.console_log(f"next id {self.id}")
            case 4:
                self.id -= 1
                self.console_log(f"prev id {self.id}")

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    Particle().standalone()
