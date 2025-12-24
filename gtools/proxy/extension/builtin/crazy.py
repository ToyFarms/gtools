from enum import IntEnum, auto
import logging
import random
import time

from pyglm.glm import ivec2, vec2

from gtools.core.growtopia.create import console_message, particle
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    INTEREST_GENERIC_TEXT,
    INTEREST_SEND_PARTICLE_EFFECT,
    INTEREST_STATE_UPDATE,
    INTEREST_TILE_CHANGE_REQUEST,
    Interest,
    InterestGenericText,
    InterestSendParticleEffect,
    InterestTileChangeRequest,
    PendingPacket,
)
from gtools.protogen.op_pb2 import OP_EQ, BinOp
from gtools.protogen.strkv_pb2 import Clause, FindCol, FindRow, Query
from gtools.proxy.extension.sdk import Extension
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket, TankFlags, TankPacket, TankType
from gtools.proxy.state import Status
from thirdparty.enet.bindings import ENetPacketFlag


class CrazyStuff(Extension):
    def __init__(self) -> None:
        logging.basicConfig(level=logging.DEBUG)

        super().__init__(
            name="crazy",
            interest=[
                Interest(
                    interest=INTEREST_STATE_UPDATE,
                ),
            ],
        )
        self.i = 0
        self.side = 5
        self.row = 5

    def send_particle(self, id: int, *, abs: vec2 | None = None, tile: ivec2 | None = None) -> None:
        pos = abs if abs else tile * 32 + 16 if tile else None
        pos = abs if abs else (tile[0] * 32.0 + 16, tile[1] * 32.0 + 16) if tile else None
        if not pos:
            return

        self.push(PreparedPacket(particle(id, pos[0], pos[1]), DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))

    def thread_1(self) -> None:
        while True:
            if self.state.status == Status.IN_WORLD:
                for x in range(-self.side * 32, self.side * 32, 32):
                    for y in range(-self.row * 32, self.row * 32, 32):
                        self.send_particle(self.i, abs=self.state.me.pos + vec2(x, y))
                        self.i += 1
                        self.i = self.i % 330

                        time.sleep(0.05)
            time.sleep(1)

    def process(self, event: PendingPacket) -> PendingPacket | None:
        pass

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    CrazyStuff().start(block=True)
