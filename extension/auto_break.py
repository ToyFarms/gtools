from dataclasses import dataclass
from enum import IntEnum, auto
import math
from queue import Empty
import random
import time

from pyglm.glm import ivec2, vec2
from gtools.core.ack_queue import AckQueue
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket, TankFlags, TankPacket, TankType
from gtools.core.growtopia.particles import ParticleID
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    INTEREST_CALL_FUNCTION,
    INTEREST_STATE,
    INTEREST_STATE_UPDATE,
    Interest,
    InterestCallFunction,
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
    TOGGLE_NEXT_SET_ID = auto()
    BUILD = auto()
    PUNCH = auto()
    MAG_EMPTY = auto()


@dataclass(slots=True)
class TileChangeRequest:
    item_id: int
    target: ivec2


class State(IntEnum):
    BREAKING = auto()
    BUILDING = auto()


class AutoBreakExtension(Extension):
    def __init__(self) -> None:
        super().__init__(
            name="auto_break",
            interest=[
                Interest(interest=INTEREST_STATE_UPDATE),
                self.command_toggle("/auto", Action.TOGGLE_AUTO),
                self.command_toggle("/rec", Action.REC),
                self.command("/t", Action.TEMPLATE),
                self.command("/id", Action.TOGGLE_NEXT_SET_ID),
                Interest(
                    interest=INTEREST_STATE,
                    state=InterestState(where=[self.tank_flags.bit_test(self.uint(TankFlags.PUNCH))]),
                    direction=DIRECTION_CLIENT_TO_SERVER,
                    blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
                    id=Action.PUNCH,
                ),
                Interest(
                    interest=INTEREST_STATE,
                    state=InterestState(where=[self.tank_flags.bit_test(self.uint(TankFlags.PLACE))]),
                    direction=DIRECTION_CLIENT_TO_SERVER,
                    blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
                    id=Action.BUILD,
                ),
                Interest(
                    interest=INTEREST_CALL_FUNCTION,
                    call_function=InterestCallFunction(where=[self.variant[0] == b"OnTalkBubble", self.variant[2] == b"The `2MAGPLANT 5000`` is empty!"]),
                    direction=DIRECTION_SERVER_TO_CLIENT,
                    blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
                    id=Action.MAG_EMPTY,
                ),
            ],
        )
        self.enabled = False
        self.target: list[ivec2] = []
        self.auto_state = State.BREAKING
        self.punching_state = False

        self._set_id_to_next = False
        self.item_id = 0

    # def thread_ping(self) -> None:
    #     while True:
    #         if self.state.status == Status.IN_WORLD and self.state.world and not self.enabled:
    #             for t in self.target:
    #                 if tile := self.state.world.get_tile(t):
    #                     self.console_log(f"{tile.fg_id} {self.state.me.character.punch_range}")

    #                 if self.in_range(ivec2(self.state.me.pos // 32), t, self.state.me.character.punch_range):
    #                     self.send_particle(ParticleID.LBOT_PLACE, tile=t)
    #                 time.sleep(0.1)
    #         time.sleep(0.5)

    def find_next_target(self) -> bool:
        if self.state.world is None:
            return False

        for i, target in enumerate(self.target):
            tile = self.state.world.get_tile(target)
            if not tile:
                continue

            if tile.fg_id != 0:
                self.target_idx = i
                return True

        return False

    def get_next_target(self) -> TileChangeRequest | bool:
        """true means state change"""
        if self.auto_state == State.BREAKING:
            for target in self.target:
                if not self.in_range(target, punch=True) or self.block_destroyed(target):
                    continue

                return TileChangeRequest(item_id=18, target=target)
            self.auto_state = State.BUILDING
            return True
        elif self.auto_state == State.BUILDING:
            for target in self.target:
                if not self.in_range(target, punch=False) or not self.can_place(target, self.item_id):
                    continue

                assert self.item_id != 0
                return TileChangeRequest(self.item_id, target)
            self.auto_state = State.BREAKING
            return True

        return False

    def thread_punch(self) -> None:
        last_tile_change: float = math.inf

        while True:
            while self.state.status == Status.IN_WORLD and self.state.world and self.enabled:
                if time.monotonic() - last_tile_change > 0.3:
                    break

                next = self.get_next_target()
                if isinstance(next, bool) or not next:
                    continue

                if not self.send_tile_change_request(next.item_id, next.target):
                    continue

                last_tile_change = time.monotonic()
                time.sleep(random.uniform(0.19, 0.21))

            last_tile_change = math.inf
            self.reset_state()
            time.sleep(0.1)

    def block_destroyed(self, pos: ivec2) -> bool:
        if not self.state.world:
            return False

        tile = self.state.world.get_tile(pos)
        if not tile:
            return False

        return tile.fg_id == 0 and tile.bg_id == 0

    def can_place(self, pos: ivec2, item_id: int) -> bool:
        if not self.state.world:
            return False

        tile = self.state.world.get_tile(pos)
        if not tile:
            return False

        if not item_database.is_background(item_id):
            return tile.fg_id == 0

        # you can always place background except on bedrock and when its the same type
        return tile.bg_id != 1 or tile.bg_id != item_id

    def stop_auto(self) -> None:
        self.enabled = False

    def process(self, event: PendingPacket) -> PendingPacket | None:
        match event.interest_id:
            case Action.TOGGLE_AUTO:
                if self.item_id != 0:
                    self.enabled = not self.enabled
                    self.console_log(f"auto is now {self.enabled}")
                else:
                    self.console_log(f"set item id first")
                return self.cancel()
            case Action.REC:
                pass
            case Action.TEMPLATE:
                self.enabled = False

                template = self.parse_command(event)
                if template == "bfg":
                    self.target.clear()
                    for x in range(2):
                        sign = -1 if self.state.me.state & TankFlags.FACING_LEFT else 1
                        target = ivec2(self.state.me.pos // 32) + ((x + 1) * sign, 0)
                        self.target.append(target)
                        self.send_particle(ParticleID.LBOT_PLACE, tile=target)

                return self.cancel()
            case Action.TOGGLE_NEXT_SET_ID:
                id = self.parse_command(event)
                if id:
                    self.item_id = int(id)
                    self.console_log(f"item_id set to {self.item_id} ({item_database.get(self.item_id).name.decode()})")
                else:
                    self._set_id_to_next = True
                return self.cancel()
            case Action.BUILD:
                if self._set_id_to_next:
                    pkt = NetPacket.deserialize(event.buf)
                    self.item_id = pkt.tank.value
                    self.console_log(f"item_id set to {self.item_id} ({item_database.get(self.item_id).name.decode()})")
                    self._set_id_to_next = False
            case Action.PUNCH:
                if self._set_id_to_next and self.state.world:
                    pkt = NetPacket.deserialize(event.buf)
                    if tile := self.state.world.get_tile(ivec2(pkt.tank.int_x, pkt.tank.int_y)):
                        self.item_id = tile.fg_id if tile.fg_id != 0 else tile.bg_id
                        self.console_log(f"item_id set to {self.item_id} ({item_database.get(self.item_id).name.decode()})")
                        self._set_id_to_next = False
            case Action.MAG_EMPTY:
                self.enabled = False
                self.console_log("auto disabled because of empty magplants")

    def destroy(self) -> None:
        pass

    def send_tile_change_request(self, id: int, target_tile: ivec2) -> bool:
        if not self.in_range(target_tile, id == 18) or self.state.status != Status.IN_WORLD:
            return False
        if (id == 18 and self.block_destroyed(target_tile)) or (id != 18 and not self.can_place(target_tile, id)):
            return False
        if id != 18 and self.state.inventory.get(id) is None:
            self.console_log(f"running out of item: disabling auto")
            self.enabled = False
            return False

        print(f"tile change at {target_tile} {id=}")
        punch_or_place = TankFlags.PUNCH if id == 18 else TankFlags.PLACE
        facing_left = self.facing_left(vec2(target_tile * 32))
        self.push(
            PreparedPacket(
                packet=NetPacket(
                    type=NetType.TANK_PACKET,
                    data=TankPacket(
                        type=TankType.TILE_CHANGE_REQUEST,
                        value=id,
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
                        flags=facing_left | TankFlags.STANDING | punch_or_place | TankFlags.TILE_CHANGE,
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

        print("sending reset state")
        facing_left = self.state.me.state & TankFlags.FACING_LEFT
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
        time.sleep(random.uniform(0.19, 0.21))
        self.push(PreparedPacket(packet=pkt, flags=ENetPacketFlag.RELIABLE, direction=DIRECTION_CLIENT_TO_SERVER))
        self.punching_state = False


if __name__ == "__main__":
    AutoBreakExtension().standalone()
