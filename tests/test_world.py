from pathlib import Path

from gtools.core.growtopia.packet import NetPacket
from gtools.proxy.state import World


def test_conversion() -> None:
    b = Path("tests/res/FD1234.bin").read_bytes()
    pkt = NetPacket.deserialize(b)

    orig = World.deserialize(pkt.tank.extended_data)
    proto = orig.to_proto()

    parsed = World.from_proto(proto)
    for x, y in zip(parsed.tiles, orig.tiles):
        assert x == y

    assert parsed.name == orig.name

    for x, y in zip(parsed.dropped.items, orig.dropped.items):
        assert x == y
