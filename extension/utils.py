from enum import IntEnum, auto
import random
import time

from pyglm.glm import ivec2

from gtools.core.growtopia.strkv import StrKV
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    INTEREST_SEND_PARTICLE_EFFECT,
    INTEREST_STATE_UPDATE,
    INTEREST_TILE_CHANGE_REQUEST,
    Interest,
    InterestCallFunction,
    InterestGameMessage,
    InterestType,
    PendingPacket,
)
from gtools.proxy.extension.sdk import Extension
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket, TankFlags, TankPacket, TankType
from gtools.proxy.state import Status
from thirdparty.enet.bindings import ENetPacketFlag


class Action(IntEnum):
    EXIT = 0
    BLOCK_EXTRA_QUIT_TO_EXIT = 1
    WARP = 2
    EXITED = 3


GEIGER_PING = 114
LBOT_BLOCK_PLACE = 88


class AutoFishExtension(Extension):
    def __init__(self) -> None:

        super().__init__(
            name="utils",
            interest=[
                self.command_toggle("/exit", Action.EXIT),
                self.command("/warp", Action.WARP),
                Interest(
                    interest=InterestType.INTEREST_GAME_MESSAGE,
                    game_message=InterestGameMessage(action=b"quit_to_exit"),
                    direction=DIRECTION_CLIENT_TO_SERVER,
                    blocking_mode=BLOCKING_MODE_BLOCK,
                    id=Action.BLOCK_EXTRA_QUIT_TO_EXIT,
                ),
                Interest(
                    interest=InterestType.INTEREST_CALL_FUNCTION,
                    call_function=InterestCallFunction(fn_name=b"OnRequestWorldSelectMenu"),
                    direction=DIRECTION_SERVER_TO_CLIENT,
                    blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
                    id=Action.EXITED,
                ),
            ],
        )
        self.should_block = False
        self.warp_target = None

    # def thread_1(self) -> None:
    #     while True:
    #         self.console_log(f"{self.should_block}")
    #         time.sleep(1)

    def to_main_menu(self) -> None:
        self.should_block = True
        self.push(
            PreparedPacket(
                NetPacket(
                    NetType.GAME_MESSAGE,
                    StrKV([[b"action", b"quit_to_exit"]]),
                ),
                DIRECTION_CLIENT_TO_SERVER,
                ENetPacketFlag.RELIABLE,
            )
        )

    def process(self, event: PendingPacket) -> PendingPacket | None:
        pkt = NetPacket.deserialize(event.buf)
        match event.interest_id:
            case Action.EXIT:
                self.to_main_menu()
                return self.cancel()
            case Action.BLOCK_EXTRA_QUIT_TO_EXIT:
                if self.should_block:
                    self.should_block = False
                    print("BLOCKED QUIT_TO_EXIT")
                    return self.cancel()
                else:
                    return self.pass_to_next()
            case Action.WARP:
                self.warp_target = pkt.generic_text.relative[b"text", 1].decode().removeprefix("/warp").strip()
                self.console_log(f"warping to {self.warp_target!r}")
                self.to_main_menu()
                return self.cancel()
            case Action.EXITED:
                if self.warp_target:
                    time.sleep(1)
                    self.push(
                        PreparedPacket(
                            NetPacket(
                                NetType.GAME_MESSAGE,
                                StrKV(
                                    [
                                        [b"action", b"join_request"],
                                        [b"name", self.warp_target.encode()],
                                        [b"invitedWorld", b"0"],
                                    ]
                                ).with_trailing_newline(),
                            ),
                            DIRECTION_CLIENT_TO_SERVER,
                            ENetPacketFlag.RELIABLE,
                        )
                    )
                    self.warp_target = None

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    AutoFishExtension().standalone()
