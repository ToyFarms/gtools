from pathlib import Path

import pytest

from gtools.core.growtopia.packet import NetPacket
from gtools.proxy.state import World


TEST_FILES = [x for x in Path("tests/res").glob("*") if x.is_file()]

@pytest.mark.parametrize("path", TEST_FILES, ids=[p.name for p in TEST_FILES])
def test_proto_conversion(path: Path) -> None:
    b = path.read_bytes()
    pkt = NetPacket.deserialize(b)

    orig = World.deserialize(pkt.tank.extended_data)
    proto = orig.to_proto()

    parsed = World.from_proto(proto)
    for x, y in zip(parsed.tiles, orig.tiles):
        assert x == y

    assert parsed.name == orig.name

    for x, y in zip(parsed.dropped.items, orig.dropped.items):
        assert x == y


@pytest.mark.parametrize("path", TEST_FILES, ids=[p.name for p in TEST_FILES])
def test_buffer_conversion(path: Path) -> None:
    b = path.read_bytes()
    pkt = NetPacket.deserialize(b)

    data = pkt.tank.extended_data
    world = World.from_extended(data)

    out = world.serialize()

    assert data == out
