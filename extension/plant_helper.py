import random
import time

from pyglm.glm import ivec2
from gtools.core.growtopia.items_dat import Item, ItemInfoCollisionType, ItemInfoType, item_database
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket, TankFlags, TankPacket, TankType
from gtools.core.growtopia.particles import ParticleID
from gtools.core.growtopia.world import SeedTile, Tile, TileFlags
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    INTEREST_STATE,
    INTEREST_TILE_CHANGE_REQUEST,
    Interest,
    InterestState,
    PendingPacket,
)
from gtools.proxy.extension.client.sdk import Extension, dispatch, register_thread
from gtools.proxy.extension.client.sdk_utils import helper
from gtools.proxy.state import Status
from thirdparty.enet.bindings import ENetPacketFlag

s = helper()


class PlantHelper(Extension):
    def __init__(self) -> None:
        super().__init__(name="PlantHelper")

        self.seed_id = 0
        self.record_next_plant = False
        self.enabled = False

        self.place_pending: dict[ivec2, float] = {}
        self.placing_state = False

        self.plant_delay_min = 0.08
        self.plant_delay_max = 0.11
        self.next_plant_allowed = 0.0
        self.last_plant = time.monotonic()

    def get_item_id(self, id_or_name: int | str | bytes) -> Item:
        if isinstance(id_or_name, int):
            return item_database.get(id_or_name)
        else:
            if isinstance(id_or_name, bytes):
                id_or_name = id_or_name.decode()

            if id_or_name.isnumeric():
                return item_database.get(int(id_or_name))
            else:
                return item_database.search(id_or_name, n=1)[0]

    @dispatch(s.command("/seed", s.auto))
    def set_seed(self, event: PendingPacket) -> PendingPacket | None:
        cmd = s.parse_command(event)
        if cmd:
            item = self.get_item_id(cmd)
            if not item.is_seed():
                item = item_database.get(item.id + 1)

            self.console_log(f"seed id set to {item.id} ({item.name})")
            self.seed_id = item.id
        else:
            self.console_log("plant one seed to get the id")
            self.record_next_plant = True

        return self.cancel()

    @dispatch(
        Interest(
            interest=INTEREST_STATE,
            state=InterestState(
                where=[
                    s.tank_flags.bit_test(s.int(TankFlags.PLACE)),
                    s.tank_flags.bit_test(s.int(TankFlags.TILE_CHANGE)),
                    s.tank_value.not_divides_by(s.int(2)),
                ]
            ),
            direction=DIRECTION_CLIENT_TO_SERVER,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        ),
    )
    def on_plant(self, event: PendingPacket) -> PendingPacket | None:
        pkt = NetPacket.deserialize(event.buf)
        if self.record_next_plant:
            self.seed_id = pkt.tank.value
            self.console_log(f"seed id set to {self.seed_id} ({item_database.get(self.seed_id).name})")
            self.record_next_plant = False

    @dispatch(s.command_toggle("/en", s.auto))
    def toggle_enable(self, event: PendingPacket) -> PendingPacket | None:
        self.enabled = not self.enabled
        self.console_log(f"plant helper is now {'active' if self.enabled else 'disabled'}")

        return self.cancel()

    def can_plant_at(self, tile: Tile) -> bool:
        if not self.state.world:
            return False

        if tile.fg_id != 0:
            return False

        if tile.fg_id % 2 != 0 and isinstance(tile.extra, SeedTile):
            if tile.flags & TileFlags.WAS_SPLICED != 0:
                return False

        below = self.state.world.get_tile(tile.pos.x, tile.pos.y + 1, log=False)
        if not below:
            return False

        if below.fg_id == 0:
            return False

        item = item_database.get(below.fg_id)
        if item.item_type == ItemInfoType.SWITCHEROO and below.flags & TileFlags.IS_ON != 0:
            return False

        if item.collision_type == ItemInfoCollisionType.NONE:
            return False

        if item.collision_type == ItemInfoCollisionType.COLLIDE_IF_OFF and below.flags & TileFlags.IS_ON != 0:
            return False

        if item.collision_type == ItemInfoCollisionType.COLLIDE_IF_ON and below.flags & TileFlags.IS_ON == 0:
            return False

        return True

    def plant(self, target: ivec2) -> bool:
        if not self.state.world or self.state.status != Status.IN_WORLD:
            return False

        if self.seed_id == 0 or self.state.inventory.get(self.seed_id) is None:
            return False

        facing_left = self.facing_left(tile=target)

        self.push(
            PreparedPacket(
                packet=NetPacket(
                    type=NetType.TANK_PACKET,
                    data=TankPacket(
                        type=TankType.TILE_CHANGE_REQUEST,
                        value=self.seed_id,
                        vector_x=self.state.me.pos.x,
                        vector_y=self.state.me.pos.y,
                        int_x=target.x,
                        int_y=target.y,
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
                        value=self.seed_id,
                        vector_x=self.state.me.pos.x,
                        vector_y=self.state.me.pos.y,
                        int_x=target.x,
                        int_y=target.y,
                        flags=facing_left | TankFlags.STANDING | TankFlags.PLACE | TankFlags.TILE_CHANGE,
                    ),
                ),
                direction=DIRECTION_CLIENT_TO_SERVER,
                flags=ENetPacketFlag.NONE,
            )
        )

        self.placing_state = True
        return True

    def reset_state(self) -> None:
        if not self.placing_state or self.state.status != Status.IN_WORLD:
            return

        facing_left = self.state.me.flags & TankFlags.FACING_LEFT
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
        self.placing_state = False

    @dispatch(
        Interest(
            interest=INTEREST_TILE_CHANGE_REQUEST,
            direction=DIRECTION_SERVER_TO_CLIENT,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        ),
    )
    def _tile_change_confirm(self, event: PendingPacket) -> PendingPacket | None:
        if self.place_pending:
            pkt = NetPacket.deserialize(event.buf)
            target = ivec2(pkt.tank.int_x, pkt.tank.int_y)
            self.place_pending.pop(target, None)

    @register_thread
    def worker(self) -> None:
        while True:
            while self.enabled and self.state.world and self.state.status == Status.IN_WORLD and self.seed_id != 0:
                if not (player := self.state.world.get_player(self.state.me.net_id)):
                    time.sleep(0.1)
                    continue

                if self.state.inventory.get(self.seed_id).amount <= 0:
                    break

                now = time.monotonic()
                self.place_pending = {k: v for k, v in self.place_pending.items() if now - v < 0.5}

                for x_off in range(self.state.me.state.build_range + 5):
                    target = ivec2(player.pos // 32)
                    if player.flags & TankFlags.FACING_LEFT:
                        target.x -= x_off
                    else:
                        target.x += x_off

                    if (
                        (tile := self.state.world.get_tile(target))
                        and self.can_plant_at(tile)
                        and self.in_range(target, punch=False)
                        and self.state.inventory.get(self.seed_id).amount > 0
                        and target not in self.place_pending
                    ):
                        wait = self.next_plant_allowed - time.monotonic()
                        if wait > 0:
                            break

                        self.send_particle(ParticleID.LBOT_PLACE, tile=target)
                        if self.plant(target):
                            self.last_plant = time.monotonic()
                            self.place_pending[target] = time.monotonic()
                            self.next_plant_allowed = time.monotonic() + random.uniform(self.plant_delay_min, self.plant_delay_max)

                time.sleep(1 / 60)
                # if time.monotonic() - self.last_plant > 0.2:
                #     break

            # self.reset_state()
            # time.sleep(0.2)

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    PlantHelper().standalone()
