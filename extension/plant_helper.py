import time

from pyglm.glm import ivec2
from gtools.core.growtopia.items_dat import Item, ItemInfoCollisionType, ItemInfoType, item_database
from gtools.core.growtopia.packet import NetPacket, TankFlags
from gtools.core.growtopia.particles import ParticleID
from gtools.core.growtopia.world import SeedTile, Tile, TileFlags
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    INTEREST_STATE,
    Interest,
    InterestState,
    PendingPacket,
)
from gtools.proxy.extension.client.sdk import Extension, dispatch, register_thread
from gtools.proxy.extension.client.sdk_utils import helper

s = helper()


class PlantHelper(Extension):
    def __init__(self) -> None:
        super().__init__(name="PlantHelper")

        self.seed_id = 0
        self.record_next_plant = False
        self.enabled = False

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

    def can_plant(self, tile: Tile) -> bool:
        if not self.state.world:
            return False

        if tile.fg_id != 0:
            return False

        if tile.fg_id % 2 != 0 and isinstance(tile.extra, SeedTile):
            if tile.flags & TileFlags.WAS_SPLICED != 0:
                return False

        below = self.state.world.get_tile(tile.pos.x, tile.pos.y + 1)
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

    @register_thread
    def worker(self) -> None:
        while True:
            if not self.enabled or not self.state.world:
                time.sleep(0.1)
                continue

            if not (player := self.state.world.get_player(self.state.me.net_id)):
                time.sleep(0.5)
                continue

            rel = player.pos % 32
            in_middle = ivec2(rel.x > 32 - player.colrect.w, rel.y > 32 - player.colrect.z)
            for x in range(-player.state.build_range, player.state.build_range + 1 + in_middle.x):
                for y in range(-player.state.build_range, player.state.build_range + 1 + in_middle.y):
                    target = ivec2(player.pos // 32)
                    target += ivec2(x, y)

                    if (tile := self.state.world.get_tile(target)) and self.can_plant(tile):
                        self.send_particle(ParticleID.LBOT_PLACE, tile=target)

            time.sleep(0.1)

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    PlantHelper().standalone()
