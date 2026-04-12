from collections import defaultdict
import click
from gtools import setting
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.packet import NetPacket
from gtools.core.growtopia.world import World


@click.command()
@click.argument("name")
def dropped(name: str) -> None:
    f = setting.appdir / "worlds" / name
    pkt = NetPacket.deserialize(f.read_bytes())
    w = World.from_tank(pkt.tank)

    items = defaultdict(int)
    for item in w.dropped.items:
        items[item.id] += item.amount

    for id, amount in items.items():
        print(f"{item_database.get(id).name.decode()}: {amount:,}")
