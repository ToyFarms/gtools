from enum import IntEnum, auto
import random
import time

from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.variant import Variant
from gtools.core.task_scheduler import schedule_task
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    INTEREST_CALL_FUNCTION,
    Interest,
    InterestCallFunction,
    InterestGameMessage,
    InterestType,
    PendingPacket,
)
from gtools.proxy.extension.sdk import Extension
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket
from thirdparty.enet.bindings import ENetPacketFlag


class Action(IntEnum):
    EXIT = auto()
    BLOCK_EXTRA_QUIT_TO_EXIT = auto()
    WARP = auto()
    EXITED = auto()

    FAST_DROP_TOGGLE = auto()
    FAST_DROP_REQUEST = auto()

    GAZETTE_DIALOG = auto()
    PING_CMD = auto()


class UtilityExtension(Extension):
    def __init__(self) -> None:

        super().__init__(
            name="utils",
            interest=[
                self.command_toggle("/exit", Action.EXIT),
                Interest(
                    interest=InterestType.INTEREST_GAME_MESSAGE,
                    game_message=InterestGameMessage(action=b"quit_to_exit"),
                    direction=DIRECTION_CLIENT_TO_SERVER,
                    blocking_mode=BLOCKING_MODE_BLOCK,
                    id=Action.BLOCK_EXTRA_QUIT_TO_EXIT,
                ),
                self.command("/warp", Action.WARP),
                Interest(
                    interest=InterestType.INTEREST_CALL_FUNCTION,
                    call_function=InterestCallFunction(where=[self.variant[0] == b"OnRequestWorldSelectMenu"]),
                    direction=DIRECTION_SERVER_TO_CLIENT,
                    blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
                    id=Action.EXITED,
                ),
                self.command("/fd", Action.FAST_DROP_TOGGLE),
                Interest(
                    interest=INTEREST_CALL_FUNCTION,
                    blocking_mode=BLOCKING_MODE_BLOCK,
                    direction=DIRECTION_SERVER_TO_CLIENT,
                    call_function=InterestCallFunction(
                        where=[
                            self.variant[0] == b"OnDialogRequest",
                            self.variant[1].contains(b"How many to drop"),
                        ]
                    ),
                    id=Action.FAST_DROP_REQUEST,
                ),
                Interest(
                    interest=INTEREST_CALL_FUNCTION,
                    blocking_mode=BLOCKING_MODE_BLOCK,
                    direction=DIRECTION_SERVER_TO_CLIENT,
                    call_function=InterestCallFunction(
                        where=[
                            self.variant[0] == b"OnDialogRequest",
                            self.variant[1].contains(b"The Growtopia Gazette"),
                        ]
                    ),
                    id=Action.GAZETTE_DIALOG,
                ),
                self.command_toggle("/ping", Action.PING_CMD),
            ],
        )
        self.should_block = False
        self.warp_target = None
        self.fast_drop = False

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
            case Action.PING_CMD:
                self.console_log(f"server={self.state.me.server_ping} client={self.state.me.client_ping}")
                return self.cancel()
            case Action.EXIT:
                self.to_main_menu()
                return self.cancel()
            case Action.BLOCK_EXTRA_QUIT_TO_EXIT:
                if self.should_block:
                    print("BLCOKED EXTRA QUIT_TO_EXIT")
                    self.should_block = False
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
                    time.sleep(random.uniform(0.529, 0.723))
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
                                ).append_nl(),
                            ),
                            DIRECTION_CLIENT_TO_SERVER,
                            ENetPacketFlag.RELIABLE,
                        )
                    )
                    self.warp_target = None
            case Action.FAST_DROP_TOGGLE:
                self.fast_drop = not self.fast_drop
                self.console_log(f"fast drop enabled: {self.fast_drop}")
                return self.cancel()
            case Action.FAST_DROP_REQUEST:
                if self.fast_drop:
                    var = Variant.deserialize(pkt.tank.extended_data)
                    if b"How many to drop" not in var.as_string[1]:
                        return

                    kv = StrKV.deserialize(var.as_string[1])

                    res_data = StrKV()
                    res_data[b"action"] = b"dialog_return"
                    res_data[b"dialog_name"] = b"drop_item"
                    res_data[b"itemID"] = kv.relative[b"itemID", 1], b""
                    res_data[b"count"] = kv.relative[b"count", 2]

                    res = PreparedPacket(
                        NetPacket(NetType.GENERIC_TEXT, data=res_data.append_nl()),
                        DIRECTION_CLIENT_TO_SERVER,
                        ENetPacketFlag.RELIABLE,
                    )

                    schedule_task(lambda: self.push(res), random.uniform(0.712, 0.9812))
                    return self.cancel()
            case Action.GAZETTE_DIALOG:
                time.sleep(random.uniform(0.518, 0.812))
                return self.forward(
                    PendingPacket(
                        buf=NetPacket(
                            type=NetType.GENERIC_TEXT,
                            data=StrKV(
                                [
                                    [b"action", b"dialog_return"],
                                    [b"dialog_name", b"gazette"],
                                    [b"buttonClicked", b"banner"],
                                ]
                            )
                            .append_nl()
                            .append_nl(),
                        ).serialize(),
                        direction=DIRECTION_CLIENT_TO_SERVER,
                        packet_flags=ENetPacketFlag.RELIABLE,
                    )
                )

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    UtilityExtension().standalone()

