from dataclasses import dataclass
from enum import IntEnum, auto
import math
import random
import time

from pyglm.glm import ivec2, vec2
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket, TankFlags, TankPacket, TankType
from gtools.core.growtopia.particles import ParticleID
from gtools.core.growtopia.player import CharacterFlags
from gtools.core.task_scheduler import schedule_task
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    INTEREST_CALL_FUNCTION,
    INTEREST_PING_REPLY,
    INTEREST_STATE,
    INTEREST_STATE_UPDATE,
    INTEREST_TILE_APPLY_DAMAGE,
    INTEREST_TILE_CHANGE_REQUEST,
    Interest,
    InterestCallFunction,
    InterestState,
    PendingPacket,
)
from gtools.proxy.extension.sdk import Extension, dispatch, register_thread
from gtools.proxy.extension.sdk_utils import helper
from gtools.proxy.state import Status
from thirdparty.enet.bindings import ENetPacketFlag


@dataclass(slots=True)
class TileChangeRequest:
    item_id: int
    target: ivec2


class State(IntEnum):
    BREAKING = auto()
    BUILDING = auto()


s = helper()


class AutoBreakExtension(Extension):
    def __init__(self) -> None:
        super().__init__(
            name="auto_break",
            interest=[Interest(interest=INTEREST_STATE_UPDATE)],
        )
        self.enabled = False
        self.target: list[ivec2] = []
        self.auto_state = State.BREAKING
        self.punching_state = False

        self._set_id_to_next = False
        self.item_id = 0
        self.place_pending: dict[ivec2, float] = {}
        self.last_confirmation = 0
        self.recording = False

    @dispatch(Interest(interest=INTEREST_TILE_APPLY_DAMAGE, blocking_mode=BLOCKING_MODE_SEND_AND_FORGET, direction=DIRECTION_SERVER_TO_CLIENT, id=s.auto))
    def _apply_damange(self, _event: PendingPacket) -> PendingPacket | None:
        self.last_confirmation = time.time()

    @dispatch(Interest(interest=INTEREST_PING_REPLY, blocking_mode=BLOCKING_MODE_SEND_AND_FORGET, direction=DIRECTION_SERVER_TO_CLIENT, id=s.auto))
    def _ping_reply(self, _event: PendingPacket) -> PendingPacket | None:
        self.last_confirmation = time.time()

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
                if target in self.place_pending and time.monotonic() - self.place_pending[target] < 1:
                    continue

                assert self.item_id != 0
                self.place_pending[target] = time.monotonic()
                return TileChangeRequest(self.item_id, target)
            self.auto_state = State.BREAKING
            return True

        return False

    @register_thread
    def thread_punch(self) -> None:
        last_tile_change: float = math.inf
        printed = False

        while True:
            while self.state.status == Status.IN_WORLD and self.state.world and self.enabled:
                if time.monotonic() - last_tile_change > 0.3:
                    break

                if self.state.me.character.flags & CharacterFlags.FROZEN:
                    if not printed:
                        print("waiting because character is frozen")
                        printed = True
                    time.sleep(0.01)
                    continue

                if self.last_confirmation != 0 and time.time() - self.last_confirmation > 2:
                    if not printed:
                        print("server not responding in a while, waiting...")
                        printed = True
                    time.sleep(0.01)
                    continue
                printed = False

                next = self.get_next_target()
                if isinstance(next, bool) or not next:
                    time.sleep(0.01)
                    continue

                if not self.send_tile_change_request(next.item_id, next.target):
                    time.sleep(0.01)
                    continue

                last_tile_change = time.monotonic()
                time.sleep(random.uniform(0.19, 0.21))

            if self.enabled and self.state.status != Status.IN_WORLD:
                self.punching_state = False
                self.enabled = False
                self.last_confirmation = 0
                self.console_log("auto disabled")

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

    @dispatch(s.command_toggle("/auto", id=s.auto))
    def _toggle_auto(self, _event: PendingPacket) -> PendingPacket | None:
        if self.item_id != 0:
            self.enabled = not self.enabled
            self.console_log(f"auto is now {self.enabled}")
            if self.enabled:
                self.last_confirmation = time.time()
        else:
            self.console_log(f"set item id first")

        return self.cancel()

    @dispatch(s.command("/t", id=s.auto))
    def _template(self, event: PendingPacket) -> PendingPacket | None:
        self.enabled = False

        template = s.parse_command(event)
        if template == "bfg":
            self.target.clear()
            for x in range(2):
                sign = -1 if self.state.me.state & TankFlags.FACING_LEFT else 1
                target = ivec2(self.state.me.pos // 32) + ((x + 1) * sign, 0)
                self.target.append(target)
                self.send_particle(ParticleID.LBOT_PLACE, tile=target)
        else:
            if not self.recording:
                self.target.clear()
                self.recording = True
                self.console_log("now recording action, invoke this command again to complete")
            else:
                self.recording = False
                self.target = list(set(self.target))
                self.target.sort(key=lambda pos: (pos.x, -pos.y))
                self.console_log(f"target: {len(self.target)}")
                t = 0
                for _ in range(5):
                    for tile in self.target:
                        schedule_task(lambda tile=tile: self.send_particle(ParticleID.LBOT_PLACE, tile=tile), t)
                        t += 0.1
                    t += 0.5

        return self.cancel()

    @dispatch(
        Interest(
            interest=INTEREST_STATE,
            state=InterestState(where=[s.tank_flags.bit_test(s.uint(TankFlags.PUNCH))]),
            direction=DIRECTION_CLIENT_TO_SERVER,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        )
    )
    def _on_punch(self, event: PendingPacket) -> PendingPacket | None:
        if self._set_id_to_next and self.state.world:
            pkt = NetPacket.deserialize(event.buf)
            if tile := self.state.world.get_tile(ivec2(pkt.tank.int_x, pkt.tank.int_y)):
                self.item_id = tile.fg_id if tile.fg_id != 0 else tile.bg_id
                self.console_log(f"item_id set to {self.item_id} ({item_database.get(self.item_id).name.decode()})")
                self._set_id_to_next = False

        if self.recording:
            pkt = NetPacket.deserialize(event.buf)
            pos = ivec2(pkt.tank.int_x, pkt.tank.int_y)
            self.target.append(pos)
            self.console_log(f"recorded at {pos.x}, {pos.y}")
            self.send_particle(ParticleID.LBOT_PLACE, tile=pos)

    @dispatch(s.command("/id", id=s.auto))
    def _set_id(self, event: PendingPacket) -> PendingPacket | None:
        id = s.parse_command(event)
        if id:
            self.item_id = int(id)
            self.console_log(f"item_id set to {self.item_id} ({item_database.get(self.item_id).name.decode()})")
        else:
            self._set_id_to_next = True
        return self.cancel()

    @dispatch(
        Interest(
            interest=INTEREST_STATE,
            state=InterestState(where=[s.tank_flags.bit_test(s.uint(TankFlags.PLACE))]),
            direction=DIRECTION_CLIENT_TO_SERVER,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        ),
    )
    def _on_build(self, event: PendingPacket) -> PendingPacket | None:
        if self._set_id_to_next:
            pkt = NetPacket.deserialize(event.buf)
            self.item_id = pkt.tank.value
            self.console_log(f"item_id set to {self.item_id} ({item_database.get(self.item_id).name.decode()})")
            self._set_id_to_next = False

        if self.recording:
            pkt = NetPacket.deserialize(event.buf)
            pos = ivec2(pkt.tank.int_x, pkt.tank.int_y)
            self.target.append(pos)
            self.console_log(f"recorded at {pos.x}, {pos.y}")
            self.send_particle(ParticleID.LBOT_PLACE, tile=pos)

    @dispatch(
        Interest(
            interest=INTEREST_CALL_FUNCTION,
            call_function=InterestCallFunction(where=[s.variant[0] == b"OnTalkBubble", s.variant[2] == b"The `2MAGPLANT 5000`` is empty!"]),
            direction=DIRECTION_SERVER_TO_CLIENT,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        ),
    )
    def _mag_empty(self, _event: PendingPacket) -> PendingPacket | None:
        self.enabled = False
        self.console_log("auto disabled because of empty magplants")

    @dispatch(
        Interest(
            interest=INTEREST_TILE_CHANGE_REQUEST,
            direction=DIRECTION_SERVER_TO_CLIENT,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        ),
    )
    def _tile_change_confirm(self, event: PendingPacket) -> PendingPacket | None:
        self.last_confirmation = time.time()
        if self.place_pending:
            pkt = NetPacket.deserialize(event.buf)
            target = ivec2(pkt.tank.int_x, pkt.tank.int_y)

            if target in self.place_pending and pkt.tank.value != 18:
                del self.place_pending[target]

    def destroy(self) -> None:
        pass

    def send_tile_change_request(self, id: int, target_tile: ivec2) -> bool:
        if not self.in_range(target_tile, id == 18) or self.state.status != Status.IN_WORLD:
            return False
        if (id == 18 and self.block_destroyed(target_tile)) or (id != 18 and not self.can_place(target_tile, id)):
            return False
        if id != 18 and self.state.inventory.get(id) is None:
            return False

        punch_or_place = TankFlags.PUNCH if id == 18 else TankFlags.PLACE
        facing_left = self.facing_left(vec2(target_tile * 32))
        print(f"last={time.time()-self.last_confirmation:.2f}, tile change at {target_tile} {id=} facing={'left' if self.state.me.state & TankFlags.FACING_LEFT != 0 else 'right'}")
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
