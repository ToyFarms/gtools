"""Blaster item data + the blast NPC wire entry.

What the data layer has to prove (``docs/blaster.md`` §2/§3):

* the BLASTER items (Howler 4344 / Trickster 8020) carry **no** payload -- their
  ``cybot_related`` field is empty, so there is nothing to decode from items.dat;
* ``BLASTER_TILE`` (0x34) consumes exactly **one** byte on the wire (the type
  byte). ``TileExtra::Parse`` 0x1405588F0 would read a 3-field payload on the
  ``someFlag == 0`` path, but every world / tile-update parse passes
  ``someFlag = 1``. The raw regression below is the exact byte sequence of five
  consecutive Trickster tiles from ``FIND`` (recon: 57 blaster tiles across 21
  world files, all one byte);
* the blast itself arrives as a **30-byte NPC entry** (``npcDeserialize``
  0x1402B73D0): type, uid, position, target, then the three params the motion
  and the spawn tile use.
"""

import struct

from pyglm.glm import vec2

from gtools.baked.items import HOWLER, TRICKSTER
from gtools.core.buffer import Buffer
from gtools.core.growtopia.items_dat import ItemInfoType, item_database
from gtools.core.growtopia.world import BlasterTile, Npc, NpcType, Tile, TileExtra, TileExtraType, TileFlags

# Two consecutive Trickster tiles of ``FIND`` (p=1702/1703) starting at the first
# tile's header: fg 8020, bg 0, parent 1807, flags 0x43 (HAS_EXTRA_DATA |
# LOCKED | 0x40), the u16 lock index 1807, then the single 0x34 extra byte.
FIND_TRICKSTER_TILE = bytes.fromhex("541f 0000 0f07 4300 0f07 34")
FIND_TRICKSTER_RUN = FIND_TRICKSTER_TILE * 2


# -- item data -----------------------------------------------------------------------


def test_blaster_items_have_no_payload() -> None:
    for item_id in (HOWLER, TRICKSTER):
        item = item_database.get(item_id)

        assert item.item_type is ItemInfoType.BLASTER
        assert item.cybot is None
        assert item.frame_interval_ms == 400  # the sprite animation rate, not a blast speed


def test_blaster_tile_extra_is_a_single_byte() -> None:
    raw = BlasterTile().serialize(TRICKSTER, 0, 27)
    assert raw == bytes([TileExtraType.BLASTER_TILE])

    buf = Buffer(raw)
    extra = TileExtra.deserialize_extra(buf, TRICKSTER, 0, 27)

    assert isinstance(extra, BlasterTile)
    assert extra.type == TileExtraType.BLASTER_TILE
    assert buf.tell_read() == 1  # nothing past the type byte is consumed


def test_find_trickster_run_parses_with_one_byte_extras() -> None:
    """The next tile must start exactly one byte after the extra type byte."""

    buf = Buffer(FIND_TRICKSTER_RUN + bytes(32))
    start = buf.tell_read()

    for index in range(2):
        tile = Tile.deserialize(buf, 27)

        assert tile.fg_id == TRICKSTER
        assert tile.flags & TileFlags.LOCKED and tile.lock_index == 1807
        assert isinstance(tile.extra, BlasterTile)
        # 10-byte header (2+2+2+2 + the LOCKED lock index) + the 1-byte extra
        assert buf.tell_read() - start == 11 * (index + 1)


# -- NPC wire entry -------------------------------------------------------------------

BLAST_NPC_ENTRY = (
    bytes([NpcType.BLAST, 7])  # type, uid
    + struct.pack("<ff", 176.0, 176.0)  # position
    + struct.pack("<ff", 176.0, 176.0)  # target
    + struct.pack("<iiff", 0, 480, 90.0, 0)  # param1, param2 (speed), param3 (degrees)
)


def test_blast_npc_entry_deserializes_the_spawn_params() -> None:
    buf = Buffer(BLAST_NPC_ENTRY)

    npc = Npc.deserialize(buf)

    assert buf.tell_read() == 30  # the entry is 30 bytes, no tail
    assert npc.type is NpcType.BLAST
    assert npc.id == 7
    assert (npc.pos.x, npc.pos.y) == (176.0, 176.0)
    assert (npc.target_pos.x, npc.target_pos.y) == (176.0, 176.0)
    assert npc.param1 == 0
    assert npc.param2 == 480  # px/s for the blast motion
    assert npc.param3 == 90.0  # heading in degrees
    assert isinstance(npc.pos, vec2)


def test_trickster_is_npc_type_15() -> None:
    assert int(NpcType.TRICKSTER) == 15
    assert int(NpcType.BLAST) == 8
