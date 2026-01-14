from enum import IntEnum, auto
import random
import time

from pyglm.glm import ivec2

from gtools.core.growtopia.particles import ParticleID
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    INTEREST_SEND_PARTICLE_EFFECT,
    INTEREST_STATE_UPDATE,
    INTEREST_TILE_CHANGE_REQUEST,
    Interest,
    PendingPacket,
)
from gtools.proxy.extension.sdk import Extension, register_thread
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket, TankFlags, TankPacket, TankType
from gtools.proxy.extension.sdk_utils import helper
from gtools.proxy.state import Status
from thirdparty.enet.bindings import ENetPacketFlag


class Action(IntEnum):
    TOGGLE_AUTO = auto()
    INITIATE = auto()
    GOT_FISH = auto()


s = helper()


class AutoFishExtension(Extension):
    def __init__(self) -> None:
        super().__init__(
            name="auto_fish",
            interest=[
                s.command("/ft", Action.TOGGLE_AUTO),
                Interest(
                    interest=INTEREST_TILE_CHANGE_REQUEST,
                    blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
                    direction=DIRECTION_CLIENT_TO_SERVER,
                    id=Action.INITIATE,
                ),
                Interest(
                    interest=INTEREST_SEND_PARTICLE_EFFECT,
                    blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
                    direction=DIRECTION_SERVER_TO_CLIENT,
                    id=Action.GOT_FISH,
                ),
                Interest(
                    interest=INTEREST_STATE_UPDATE,
                ),
            ],
        )

        self.enabled = False
        self.fish_pos = ivec2(-1, -1)  # in tile space
        self.bait = -1

    @register_thread
    def thread_info(self) -> None:
        while True:
            if self.state.status == Status.IN_WORLD:
                self.send_particle(ParticleID.GEIGER_PING, abs=self.state.me.pos)
                self.send_particle(ParticleID.LBOT_PLACE, tile=self.fish_pos)

            self.console_log(f"{self.state.status.name} {self.state.inventory.get(self.bait)}")
            time.sleep(1)

    def process(self, event: PendingPacket) -> PendingPacket | None:
        pkt = NetPacket.deserialize(event.buf)
        match event.interest_id:
            case Action.TOGGLE_AUTO:
                if self.state.status != Status.IN_WORLD:
                    self.console_log("auto fish cannot enabled when not in a world, try re-entering the world")
                else:
                    self.enabled = not self.enabled
                    self.console_log(f"auto fish enabled: {self.enabled}")
                return self.cancel()
            case Action.INITIATE:
                self.bait = pkt.tank.value
                self.fish_pos = ivec2(pkt.tank.int_x, pkt.tank.int_y)
                self.console_log(f"bait: {self.bait}")
            case Action.GOT_FISH:
                if self.enabled and self.state.status == Status.IN_WORLD:
                    time.sleep(random.uniform(0.315, 0.519))

                    fish_pos = ivec2(pkt.tank.vector_x // 32, pkt.tank.vector_y // 32)
                    if (
                        self.bait in self.state.inventory
                        and self.state.inventory[self.bait].amount >= 1
                        and self.bait != -1
                        and fish_pos == self.fish_pos
                        and self.state.me.pos != (0, 0)
                        and self.in_range(self.fish_pos, punch=False)
                    ):
                        facing_left = TankFlags.NONE
                        if int(self.state.me.pos.x // 32) > self.fish_pos.x:
                            facing_left |= TankFlags.FACING_LEFT

                        # NOTE: gone fishin net id can be used to identify
                        self.send_particle(ParticleID.LBOT_PLACE, tile=self.fish_pos)
                        self.send_particle(ParticleID.GEIGER_PING, abs=self.state.me.pos)

                        self.send_reel_packet()
                        time.sleep(random.uniform(0.261, 0.400))
                        self.send_throw_packet()

    def facing_left(self, to: ivec2) -> TankFlags:
        bot_pos = ivec2(self.state.me.pos // 32)
        if bot_pos.x > to.x:
            return TankFlags.FACING_LEFT
        return TankFlags.NONE

    def click_packet(self) -> None:
        self.push(
            PreparedPacket(
                packet=NetPacket(
                    type=NetType.TANK_PACKET,
                    data=TankPacket(
                        type=TankType.TILE_CHANGE_REQUEST,
                        value=self.bait,
                        vector_x=self.state.me.pos.x,
                        vector_y=self.state.me.pos.y,
                        int_x=self.fish_pos.x,
                        int_y=self.fish_pos.y,
                        flags=self.facing_left(self.fish_pos),
                    ),
                ),
                direction=DIRECTION_CLIENT_TO_SERVER,
                flags=ENetPacketFlag.RELIABLE,
            )
        )

        time.sleep(random.uniform(0.08, 0.105))

        self.push(
            PreparedPacket(
                packet=NetPacket(
                    type=NetType.TANK_PACKET,
                    data=TankPacket(
                        type=TankType.STATE,
                        value=self.bait,
                        vector_x=self.state.me.pos.x,
                        vector_y=self.state.me.pos.y,
                        int_x=self.fish_pos.x,
                        int_y=self.fish_pos.y,
                        flags=self.facing_left(self.fish_pos) | TankFlags.STANDING | TankFlags.PLACE | TankFlags.TILE_CHANGE,
                    ),
                ),
                direction=DIRECTION_CLIENT_TO_SERVER,
                flags=ENetPacketFlag.NONE,
            )
        )

        time.sleep(random.uniform(0.08, 0.105))

        self.push(
            PreparedPacket(
                packet=NetPacket(
                    type=NetType.TANK_PACKET,
                    data=TankPacket(
                        type=TankType.STATE,
                        vector_x=self.state.me.pos.x,
                        vector_y=self.state.me.pos.y,
                        int_x=-1,
                        int_y=-1,
                        flags=self.facing_left(self.fish_pos) | TankFlags.STANDING,
                    ),
                ),
                direction=DIRECTION_CLIENT_TO_SERVER,
                flags=ENetPacketFlag.NONE,
            )
        )

    def send_throw_packet(self) -> None:
        self.click_packet()

    def send_reel_packet(self) -> None:
        self.click_packet()

        time.sleep(random.uniform(0.08, 0.105))

        self.push(
            PreparedPacket(
                packet=NetPacket(
                    type=NetType.TANK_PACKET,
                    data=TankPacket(
                        type=TankType.STATE,
                        vector_x=self.state.me.pos.x,
                        vector_y=self.state.me.pos.y,
                        int_x=-1,
                        int_y=-1,
                        flags=self.facing_left(self.fish_pos) | TankFlags.STANDING,
                    ),
                ),
                direction=DIRECTION_CLIENT_TO_SERVER,
                flags=ENetPacketFlag.RELIABLE,
            )
        )

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    AutoFishExtension().standalone()
