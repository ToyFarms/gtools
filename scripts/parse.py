from pprint import pprint
import click
from gtools.core.growtopia.packet import NetPacket


@click.command()
@click.argument("buf", nargs=-1)
def parse(buf: tuple[str, ...]) -> None:
    buf_str: str = " ".join(buf)
    buf_str = buf_str.removeprefix("DEBUG:proxy:b").removeprefix("b").removeprefix('"').removeprefix("'").removesuffix("'").removesuffix('"')
    b = buf_str.encode().decode("unicode_escape").encode("latin1")

    pprint(NetPacket.deserialize(b))
