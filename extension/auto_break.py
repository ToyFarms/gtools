from enum import IntEnum, auto
import math
from queue import Empty
import random
import time

from pyglm.glm import ivec2, vec2
from gtools.core.ack_queue import AckQueue
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket, TankFlags, TankPacket, TankType
from gtools.core.growtopia.particles import ParticleID
from gtools.core.growtopia.variant import Variant
from gtools.core.signal import Signal
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    INTEREST_STATE,
    INTEREST_STATE_UPDATE,
    Interest,
    InterestState,
    InterestType,
    PendingPacket,
)
from gtools.proxy.extension.sdk import Extension
from gtools.proxy.state import Status
from thirdparty.enet.bindings import ENetPacketFlag


class Action(IntEnum):
    TOGGLE_AUTO = auto()
    REC = auto()
    TEMPLATE = auto()


class AutoBreakExtension(Extension):
    def __init__(self) -> None:
        super().__init__(
            name="auto_break",
            interest=[
                Interest(interest=INTEREST_STATE_UPDATE),
                self.command_toggle("/auto", Action.TOGGLE_AUTO),
                self.command_toggle("/rec", Action.REC),
                self.command("/templ", Action.TEMPLATE),
            ],
        )
        self.enabled = False
        self.target: list[ivec2] = []
        self.punching_state = False

        self.original_name: bytes | None = None
        self.title_icon: bytes | None = None

        self.punch_queue: AckQueue[tuple[ivec2, int]] = AckQueue()
        self.version = 0

    def thread_ping(self) -> None:
        while True:
            if self.state.status == Status.IN_WORLD and self.state.world and not self.enabled:
                for t in self.target:
                    if tile := self.state.world.get_tile(t):
                        self.console_log(f"{tile.fg_id}")
                    self.send_particle(ParticleID.LBOT_PLACE, tile=t)
                    time.sleep(0.1)
            time.sleep(1)

    def send_punch_packet(self, target_tile: ivec2) -> bool:
        if not self.in_range(ivec2(self.state.me.pos // 32), target_tile, self.state.me.punch_range) or self.state.status != Status.IN_WORLD:
            return False

        facing_left = self.facing_left(vec2(self.target * 32))
        self.push(
            PreparedPacket(
                packet=NetPacket(
                    type=NetType.TANK_PACKET,
                    data=TankPacket(
                        type=TankType.TILE_CHANGE_REQUEST,
                        value=18,
                        vector_x=self.state.me.pos.x,
                        vector_y=self.state.me.pos.y,
                        int_x=target_tile.x,
                        int_y=target_tile.y,
                        flags=facing_left,
                    ),
                ),
                direction=DIRECTION_CLIENT_TO_SERVER,
                flags=ENetPacketFlag.RELIABLE,
            )
        )
        self.push(
            PreparedPacket(
                packet=NetPacket(
                    type=NetType.TANK_PACKET,
                    data=TankPacket(
                        type=TankType.STATE,
                        vector_x=self.state.me.pos.x,
                        vector_y=self.state.me.pos.y,
                        int_x=target_tile.x,
                        int_y=target_tile.y,
                        flags=facing_left | TankFlags.STANDING | TankFlags.PUNCH | TankFlags.TILE_CHANGE,
                    ),
                ),
                direction=DIRECTION_CLIENT_TO_SERVER,
                flags=ENetPacketFlag.NONE,
            )
        )
        self.punching_state = True
        return True

    def reset_state(self) -> None:
        if not self.punching_state or self.state.status != Status.IN_WORLD:
            return

        facing_left = self.facing_left(vec2(self.target * 32))
        pkt = NetPacket(
            type=NetType.TANK_PACKET,
            data=TankPacket(
                type=TankType.STATE,
                vector_x=self.state.me.pos.x,
                vector_y=self.state.me.pos.y,
                int_x=-1,
                int_y=-1,
                flags=facing_left | TankFlags.STANDING,
            ),
        )
        self.push(PreparedPacket(packet=pkt, flags=ENetPacketFlag.NONE, direction=DIRECTION_CLIENT_TO_SERVER))
        time.sleep(random.uniform(0.17, 0.22))
        self.push(PreparedPacket(packet=pkt, flags=ENetPacketFlag.RELIABLE, direction=DIRECTION_CLIENT_TO_SERVER))
        self.punching_state = False

    # def thread_punch(self) -> None:
    #     last_punch: float = math.inf
    #     while True:
    #         while self.state.status == Status.IN_WORLD and self.enabled:
    #             if time.monotonic() - last_punch > 0.3:
    #                 break

    #             try:
    #                 target, ver = self.punch_queue.get_nowait()
    #             except Empty:
    #                 continue

    #             if ver != self.version:
    #                 continue

    #             if not self.send_punch_packet(target):
    #                 continue

    #             self.punch_queue.ack()
    #             last_punch = time.monotonic()
    #             time.sleep(random.uniform(0.17, 0.22))

    #         last_punch = math.inf
    #         self.reset_state()
    #         time.sleep(0.1)

    def stop_auto(self) -> None:
        self.enabled = False
        self.version += 1

    def process(self, event: PendingPacket) -> PendingPacket | None:
        match event.interest_id:
            case Action.TOGGLE_AUTO:
                self.enabled = not self.enabled
                return self.cancel()
            case Action.REC:
                pass
            case Action.TEMPLATE:
                self.enabled = False

                template = self.parse_command(event)
                if template == "bfg":
                    self.stop_auto()
                    self.target.clear()
                    for x in range(2):
                        sign = -1 if self.state.me.state & TankFlags.FACING_LEFT else 1
                        self.target.append(ivec2(self.state.me.pos // 32) + ((x + 1) * sign, 0))

                return self.cancel()

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    AutoBreakExtension().standalone()
