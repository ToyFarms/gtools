from gtools.core.growtopia.items_dat import Item, item_database
from gtools.core.growtopia.packet import NetPacket, TankFlags
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    INTEREST_STATE,
    Interest,
    InterestState,
    PendingPacket,
)
from gtools.proxy.extension.client.sdk import Extension, dispatch
from gtools.proxy.extension.client.sdk_utils import helper

s = helper()


class PlantHelper(Extension):
    def __init__(self) -> None:
        super().__init__(name="PlantHelper")

        self.seed_id = 0
        self.record_next_plant = False

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
        print(pkt.tank.value)

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    PlantHelper().standalone()
