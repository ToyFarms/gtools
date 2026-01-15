from enum import IntEnum, auto
import random
import time
from typing import Iterator

from pyglm.glm import ivec2

from gtools.baked.items import DIGIVEND_MACHINE, VENDING_MACHINE
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.particles import ParticleID
from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.variant import Variant
from gtools.core.growtopia.world import Tile, VendingMachineTile
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
from gtools.proxy.extension.sdk import Extension, dispatch, dispatch_fallback
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket
from gtools.proxy.extension.sdk_utils import helper
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


def bresenham(x0: int, y0: int, x1: int, y1: int) -> Iterator[ivec2]:
    dx = x1 - x0
    dy = y1 - y0

    xsign = 1 if dx > 0 else -1
    ysign = 1 if dy > 0 else -1

    dx = abs(dx)
    dy = abs(dy)

    if dx > dy:
        xx, xy, yx, yy = xsign, 0, 0, ysign
    else:
        dx, dy = dy, dx
        xx, xy, yx, yy = 0, ysign, xsign, 0

    D = 2 * dy - dx
    y = 0

    for x in range(dx + 1):
        yield ivec2(x0 + x * xx + y * yx, y0 + x * xy + y * yy)
        if D >= 0:
            y += 1
            D -= 2 * dx
        D += 2 * dy


s = helper()


class UtilityExtension(Extension):
    def __init__(self) -> None:

        super().__init__(
            name="utils",
            interest=[
                Interest(interest=InterestType.INTEREST_STATE_UPDATE),
                s.command_toggle("/exit", Action.EXIT),
                Interest(
                    interest=InterestType.INTEREST_GAME_MESSAGE,
                    game_message=InterestGameMessage(action=b"quit_to_exit"),
                    direction=DIRECTION_CLIENT_TO_SERVER,
                    blocking_mode=BLOCKING_MODE_BLOCK,
                    id=Action.BLOCK_EXTRA_QUIT_TO_EXIT,
                ),
                s.command("/warp", Action.WARP),
                Interest(
                    interest=InterestType.INTEREST_CALL_FUNCTION,
                    call_function=InterestCallFunction(where=[s.variant[0] == b"OnRequestWorldSelectMenu"]),
                    direction=DIRECTION_SERVER_TO_CLIENT,
                    blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
                    id=Action.EXITED,
                ),
                s.command("/fd", Action.FAST_DROP_TOGGLE),
                Interest(
                    interest=INTEREST_CALL_FUNCTION,
                    blocking_mode=BLOCKING_MODE_BLOCK,
                    direction=DIRECTION_SERVER_TO_CLIENT,
                    call_function=InterestCallFunction(
                        where=[
                            s.variant[0] == b"OnDialogRequest",
                            s.variant[1].contains(b"How many to drop"),
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
                            s.variant[0] == b"OnDialogRequest",
                            s.variant[1].contains(b"The Growtopia Gazette"),
                        ]
                    ),
                    id=Action.GAZETTE_DIALOG,
                ),
                s.command_toggle("/ping", Action.PING_CMD),
            ],
        )
        self.should_block = False
        self.warp_target = None
        self.fast_drop = False
        self.intercept_warp = True

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


    @dispatch(s.command_toggle("/nowrap", id=200))
    def _toggle_nowrap(self, event: PendingPacket) -> PendingPacket | None:
        self.intercept_warp = not self.intercept_warp
        self.console_log(f"simulate warp: {self.intercept_warp}")

        return self.cancel()

    @dispatch_fallback
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
            case Action.WARP if self.intercept_warp:
                self.warp_target = pkt.generic_text.relative[b"text", 1].decode().removeprefix("/warp").strip()
                self.console_log(f"warping to {self.warp_target!r}")
                self.to_main_menu()
                return self.cancel()
            case Action.EXITED if self.intercept_warp:
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

                    self.push(res)
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

    @dispatch(s.command("/item", id=100))
    def _item(self, event: PendingPacket) -> PendingPacket | None:
        if self.state.world:
            id = s.parse_command(event)
            if id:
                self.console_log(f"{self.state.world.dropped.get_total(int(id))}")
            else:
                self.console_log(f"{self.state.world.dropped}")
        return self.cancel()

    @dispatch(s.command("/search", id=101))
    def _search(self, event: PendingPacket) -> PendingPacket | None:
        search = s.parse_command(event).strip()
        for item in item_database.search(search):
            self.console_log(f"{item.name.decode()}: rarity={item.rarity}, id={item.id}")
        return self.cancel()

    @dispatch(s.command("/find", id=102))
    def _vend(self, event: PendingPacket) -> PendingPacket | None:
        if not self.state.world:
            self.console_log("not in a world!")
            return self.cancel()

        search = s.parse_command(event).strip()
        item = item_database.search(search)[0]
        found: list[Tile] = []
        self.console_log(f"searching for {item.name.decode()}")

        for tile in self.state.world.tiles:
            if tile.fg_id in (VENDING_MACHINE, DIGIVEND_MACHINE):
                if not isinstance(tile.extra, VendingMachineTile):
                    continue

                if tile.extra.item_id == item.id:
                    found.append(tile)

        if not found:
            self.console_log(f"item '{item.name.decode()}' not found")
            return self.cancel()

        self.console_log(f"{item.name.decode()}:")
        for tile in found:
            if not isinstance(tile.extra, VendingMachineTile):
                continue

            self.console_log(f"    pos={tile.pos.x},{tile.pos.y}, price={tile.extra.price}")

        t = 0
        for tile in found:
            for tile_inbetween in bresenham(int(self.state.me.pos.x // 32), int(self.state.me.pos.y // 32), tile.pos.x, tile.pos.y):
                schedule_task(lambda x=tile_inbetween, t=t: self.send_particle(ParticleID.GEIGER_PING, tile=x), t)
                t += 0.1

            t0 = t
            t += 1
            for _ in range(5):
                schedule_task(lambda x=tile.pos: self.send_particle(ParticleID.GEIGER_PING, 2, tile=x), t)
                t += 2
            t = t0

        return self.cancel()

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    UtilityExtension().standalone()
