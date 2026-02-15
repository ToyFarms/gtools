import click
from gtools.core.growtopia.packet import NetPacket
from gtools.core.growtopia.world import World
from gtools.core.wsl import windows_home


@click.command()
@click.argument("name")
def world(name: str) -> None:
    f = windows_home() / ".gtools/worlds" / name
    pkt = NetPacket.deserialize(f.read_bytes())
    w = World.from_net(pkt.tank)

    print(w)
