"""Synthetic wire regressions for ``World.deserialize`` / ``World.serialize``.

Client evidence:
* ``parseTile`` (0x140555A50) calls ``replaceTileForegroud`` (0x140555EB0) *before* the
  ``HAS_EXTRA_DATA`` gate, and that function forces the flag for the structural item
  types (doors, seeds, locks, guild items, ...). Saves (v0/v3 in particular) therefore
  carry an extra without the flag bit and it must be inferred from the foreground item.
* ``World::LoadFromMem`` (0x14055E690) only reads the 12-byte weather block for
  ``version >= 3``.
* The trailing guild-item payload has no type byte of its own (it follows the parent
  extra directly, see ``TileExtra::Parse`` ``handleSpecialTile``).
"""

import cbor2

from gtools.baked.items import DIRT, DIRT_SEED, GUILD_LOCK, MAIN_DOOR
from gtools.core.buffer import Buffer
from gtools.core.growtopia.packet import NetType, TankPacket
from gtools.core.growtopia.world import (
    WEATHER_MACHINE_CONCERT_LIGHTS,
    DoorTile,
    GivingTreeStumpTile,
    GuildWeatherMachineTile,
    TileExtraType,
    TileFlags,
    World,
)


def wire_tile(fg: int = 0, bg: int = 0, parent: int = 0, flags: int = 0, extra: bytes = b"") -> bytes:
    b = bytearray()
    b += fg.to_bytes(2, "little")
    b += bg.to_bytes(2, "little")
    b += parent.to_bytes(2, "little")
    b += flags.to_bytes(2, "little")
    b += extra
    return bytes(b)


def build_world(*, version: int, tiles: list[bytes], name: bytes = b"TEST", weather: bytes | None = None) -> bytes:
    s = Buffer()
    s.write_u16(version)
    s.write_u32(0)
    s.write_pascal_bytes("H", name)
    s.write_u32(4)
    s.write_u32(4)
    s.write_u32(len(tiles))
    s.write_bytes(b"\x00" * 5)

    for tile in tiles:
        s.write_bytes(tile)

    s.write_bytes(b"\x00" * 12)  # unk4
    s.write_u32(0)  # dropped.nb_items
    s.write_u32(0)  # dropped.last_uid
    if weather is None and version >= 3:
        weather = b"\x00" * 12
    s.write_bytes(weather or b"")
    return s.serialize()


def test_door_extra_without_flag_is_inferred() -> None:
    """A Main Door with ``flags == 0`` still carries its door extra (old saves)."""
    extra = b"\x01\x04\x00EXIT\x00"  # type DOOR_TILE, "EXIT", public byte
    data = build_world(
        version=23,
        tiles=[
            wire_tile(),
            wire_tile(fg=MAIN_DOOR, extra=extra),
            wire_tile(),
            wire_tile(fg=DIRT),
        ],
    )

    world = World.from_extended(data)

    assert world.garbage_start == -1
    door = world.tiles[1]
    assert door.fg_id == MAIN_DOOR
    assert isinstance(door.extra, DoorTile)
    assert door.extra.text == b"EXIT"
    assert door.flags & TileFlags.HAS_EXTRA_DATA  # the client leaves the forced flag set


def test_seed_extra_without_flag_is_inferred() -> None:
    """A foreground seed tile without the flag parses its 5-byte seed payload (IIT_SEED)."""
    data = build_world(
        version=3,
        tiles=[
            wire_tile(),
            wire_tile(fg=DIRT_SEED, flags=TileFlags.IS_SEEDLING, extra=b"\x04\x1f\x00\x00\x00\x03"),
            wire_tile(),
            wire_tile(),
        ],
    )

    world = World.from_extended(data)

    assert world.garbage_start == -1
    assert world.tiles[1].extra is not None
    assert world.tiles[1].extra.type == TileExtraType.SEED_TILE
    assert world.tiles[1].extra.time_passed == 31


def test_none_extra_is_consumed_and_dropped() -> None:
    """A ``NONE`` (0) extra byte is consumed; parseTile drops the extra and clears the flag."""
    data = build_world(
        version=23,
        tiles=[
            wire_tile(fg=DIRT, flags=TileFlags.HAS_EXTRA_DATA, extra=b"\x00"),
            wire_tile(fg=DIRT),
            wire_tile(fg=DIRT),
            wire_tile(fg=DIRT),
        ],
    )

    world = World.from_extended(data)

    assert world.garbage_start == -1
    assert world.tiles[0].extra is None
    assert not world.tiles[0].flags & TileFlags.HAS_EXTRA_DATA


def test_giving_tree_stump_extra_has_no_payload() -> None:
    """0x1D (``FISH_TANK_PORT_TILE|SEED_TILE``) is one type byte only."""
    stump_extra = b"\x1d"
    data = build_world(
        version=23,
        tiles=[
            wire_tile(fg=DIRT, flags=TileFlags.HAS_EXTRA_DATA, extra=stump_extra),
            wire_tile(fg=DIRT),
            wire_tile(fg=DIRT),
            wire_tile(fg=DIRT),
        ],
    )

    world = World.from_extended(data)

    assert world.garbage_start == -1
    assert isinstance(world.tiles[0].extra, GivingTreeStumpTile)
    assert world.serialize() == data


def test_version_0_world_has_no_weather_block() -> None:
    """v0 saves end after the dropped items -- no 12-byte weather block."""
    data = build_world(version=0, tiles=[wire_tile(fg=DIRT)] * 4)

    world = World.from_extended(data)

    assert world.garbage_start == -1
    assert world.version == 0
    # serialize must not invent the weather block for v0 either
    assert world.serialize() == data
    assert World.deserialize(world.serialize()).garbage_start == -1


def test_version_3_world_keeps_weather_block() -> None:
    weather = b"\x01\x00" + b"\x00\x00" + b"\x02\x00" + b"\x00\x00" + b"\x00\x00\x00\x00"
    data = build_world(version=3, tiles=[wire_tile(fg=DIRT)] * 4, weather=weather)

    world = World.from_extended(data)

    assert world.garbage_start == -1
    assert world.serialize() == data


def test_concert_lights_cbor_payload() -> None:
    """16094 (WEATHER_MACHINE_CONCERT_LIGHTS) is a CBOR tile: extra + u32 length + map."""
    extra = b"\x31" + (2).to_bytes(4, "little") + (50).to_bytes(4, "little") + b"\x00"
    body = cbor2.dumps({"jsonString": ""})
    colt = wire_tile(
        fg=WEATHER_MACHINE_CONCERT_LIGHTS,
        flags=TileFlags.HAS_EXTRA_DATA,
        extra=extra + len(body).to_bytes(4, "little") + body,
    )
    data = build_world(version=27, tiles=[wire_tile(), colt, wire_tile(), wire_tile()])

    world = World.from_extended(data)

    assert world.garbage_start == -1
    tile = world.tiles[1]
    assert isinstance(tile.extra, GuildWeatherMachineTile)
    assert tile.json_data == {"jsonString": ""}


def test_from_file_keeps_the_last_world_byte(tmp_path) -> None:
    """Saved files may omit the NetPacket "anomaly byte"; from_file must not truncate."""
    data = build_world(version=0, tiles=[wire_tile(fg=DIRT)] * 4)
    path = tmp_path / "TEST"
    path.write_bytes(NetType.TANK_PACKET.value.to_bytes(4, "little") + TankPacket(extended_data=data).serialize())

    world = World.from_file(path)

    assert world.garbage_start == -1
    assert world.tiles[0].fg_id == DIRT


def test_guild_data_roundtrip_has_no_type_byte() -> None:
    """The trailing guild payload follows the lock extra without its own 0x41 byte."""
    lock_extra = (
        b"\x03"  # LOCK_TILE
        + b"\x20"  # door state
        + (1234).to_bytes(4, "little")  # owner uid
        + (1).to_bytes(4, "little")  # access count
        + (99).to_bytes(4, "little", signed=True)  # one access uid
        + (1).to_bytes(4, "little")  # minimum level (v >= 12)
        + (2).to_bytes(4, "little")  # guild id (v >= 13)
        # guild data (GUILD_LOCK skips the leading u8): unk2..unk5
        + (2).to_bytes(4, "little")
        + (3).to_bytes(4, "little")
        + (4).to_bytes(4, "little")
        + (5).to_bytes(4, "little")
    )
    data = build_world(
        version=23,
        tiles=[
            wire_tile(),
            wire_tile(fg=GUILD_LOCK, flags=TileFlags.HAS_EXTRA_DATA | TileFlags.LOCKED, extra=b"\x00\x00" + lock_extra),
            wire_tile(),
            wire_tile(),
        ],
    )

    world = World.from_extended(data)

    assert world.garbage_start == -1
    extra = world.tiles[1].extra
    assert extra is not None
    assert extra.type == TileExtraType.LOCK_TILE
    assert extra.data is not None  # GuildItemTile
    assert world.serialize() == data
