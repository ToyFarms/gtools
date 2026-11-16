"""CyBot item data + tile-extra wire format.

Client evidence (see ``docs/cybot.md`` §2/§3):
* ``cybot_related`` (60 B, items.dat v>=9) is 15 little-endian u32 read by the
  client at the in-memory item record ``+0x78``; the payload depends on the item
  type (COMMAND / ROBOT) -- ``deserializeItemDatabase`` 0x14053C9A0 + every
  consumer listed in the doc.
* ``CY_BOT_TILE`` (0x3F) tile extra (``TileExtra::Parse`` 0x1405588F0):
  ``u32 count`` then per entry ``u32 item_id; u8 enabled; u32 unk20; i32 unk24;
  H string``, then ``u32 anchor_ms`` + ``u32 activated``. The old flat
  interpretation (``u32; u32; 7 bytes``) only consumed the right byte count
  while the strings are empty -- the raw byte regression below pins the real one.
"""

import struct

from gtools.baked.items import (
    COMMAND_MOVE_LEFT,
    COMMAND_MOVE_RIGHT,
    SHOCKBOT_LEVEL_1,
    SHOOTERBOT_LEVEL_1,
    SPIKEBOT_LEVEL_1,
)
from gtools.core.buffer import Buffer
from gtools.core.growtopia.items_dat import (
    ItemInfoCyBotCommand,
    ItemInfoCyBotRobot,
    ItemInfoType,
    item_database,
)
from gtools.core.growtopia.world import CyBotCommandData, CybotTile, TileExtra, TileExtraType

MOVE_LEFT = COMMAND_MOVE_LEFT  # 5672
MOVE_RIGHT = COMMAND_MOVE_RIGHT  # 5674
BASIC_SHOT_LEFT = 5682
LONG_SHOT_LEFT = 5698
SHOOTERBOT_L1 = SHOOTERBOT_LEVEL_1  # 5708
SHOCKBOT_L1 = SHOCKBOT_LEVEL_1  # 5668
SPIKEBOT_L1 = SPIKEBOT_LEVEL_1  # 5670

# Raw CY_BOT_TILE extra of the FlameBot L4 tile at (86,35) of WOLFWORLD8 (28 B):
# type 0x3F, count 1, entry (Basic Shot Right, enabled, 0, 0, ""), anchor, activated.
WOLFWORLD8_FLAMEBOT_EXTRA = bytes.fromhex(
    "3f"
    "01000000"
    "34160000" "01" "00000000" "00000000" "0000"
    "73fbfe10"
    "01000000"
)


# -- item fields ---------------------------------------------------------------------


def test_command_item_decodes_the_cybot_payload() -> None:
    item = item_database.get(MOVE_LEFT)

    assert isinstance(item.cybot, ItemInfoCyBotCommand)
    assert item.cybot.mirror_item_id == MOVE_RIGHT
    assert item.cybot.move_offset == (-1, 0)
    assert item.frame_interval_ms == 500  # the client's command duration (+0x10C)


def test_shot_command_decodes_speed_and_lifetime() -> None:
    basic = item_database.get(BASIC_SHOT_LEFT).cybot
    long = item_database.get(LONG_SHOT_LEFT).cybot

    assert isinstance(basic, ItemInfoCyBotCommand) and isinstance(long, ItemInfoCyBotCommand)
    assert basic.shot_speed == 16
    assert basic.shot_speed_px_per_ms == 0.16
    assert basic.shot_lifetime_ms == 800  # 0.16 px/ms * 800 ms = 128 px = 4 tiles
    assert long.shot_lifetime_ms == 2400  # 384 px = 12 tiles


def test_robot_item_decodes_the_sprite_layout() -> None:
    item = item_database.get(SHOOTERBOT_L1)

    assert isinstance(item.cybot, ItemInfoCyBotRobot)
    assert item.cybot.sprite_base_frame == 0
    assert (item.cybot.idle_frames, item.cybot.direction_frames, item.cybot.projectile_frames) == (3, 6, 2)
    assert item.cybot.sprite_block_frames == 23  # the level stride seen in npc1.rttex
    assert item.cybot.projectile_base_frame == 21
    assert item.cybot.melee_cooldown_ms == 0


def test_robot_families_decode_their_base_frames() -> None:
    assert item_database.get(SHOCKBOT_L1).cybot.sprite_base_frame == 224  # walker, 3-frame stride
    assert item_database.get(SPIKEBOT_L1).cybot.sprite_base_frame == 192
    assert item_database.get(5780).cybot.sprite_base_frame == 23  # ShooterBot L2


def test_non_cybot_items_have_no_payload() -> None:
    for item_id in (2, 18, 242):  # dirt, fist, world lock
        item = item_database.get(item_id)
        assert item.item_type not in (ItemInfoType.ROBOT, ItemInfoType.COMMAND)
        assert item.cybot is None


def test_from_words_rejects_a_wrong_length() -> None:
    try:
        ItemInfoCyBotCommand.from_words((1, 2, 3))
    except ValueError as exc:
        assert "15 u32" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("from_words accepted a short word list")


# -- tile extra wire format ----------------------------------------------------------


def test_cybot_extra_round_trips_with_a_non_empty_name() -> None:
    extra = CybotTile(
        commands=[
            CyBotCommandData(item_id=MOVE_LEFT, enabled=1, unk20=7, unk24=-3, name=b"patrol"),
            CyBotCommandData(item_id=BASIC_SHOT_LEFT),
        ],
        anchor_ms=123456,
        activated=1,
    )

    raw = extra.serialize(0, 0, 27)

    # layout: u8 type, u32 count, then per entry
    # [u32 item_id, u8 enabled, u32 unk20, i32 unk24, H len + name], then 2x u32 tail
    assert raw[0] == TileExtraType.CYBOT_TILE
    assert raw[1:5] == struct.pack("<I", 2)
    assert raw[5:9] == struct.pack("<I", MOVE_LEFT)
    assert raw[9] == 1  # enabled
    assert raw[10:14] == struct.pack("<I", 7)  # unk20
    assert raw[14:18] == struct.pack("<i", -3)  # unk24
    assert raw[18:20] == struct.pack("<H", 6) and raw[20:26] == b"patrol"
    # the name makes the entry 15 + 6 bytes long -- the flat 15 B reader would desync here
    assert raw[26:30] == struct.pack("<I", BASIC_SHOT_LEFT)
    assert raw[41:49] == struct.pack("<II", 123456, 1)  # anchor_ms, activated
    assert len(raw) == 49

    parsed = TileExtra.deserialize_extra(Buffer(raw), 0, 0, 27)

    assert isinstance(parsed, CybotTile)
    assert parsed.commands[0] == extra.commands[0]
    assert parsed.commands[1].item_id == BASIC_SHOT_LEFT
    assert parsed.anchor_ms == 123456
    assert parsed.activated == 1
    assert parsed.type == TileExtraType.CYBOT_TILE


def test_wolfworld8_flamebot_extra_decodes_exactly() -> None:
    raw = WOLFWORLD8_FLAMEBOT_EXTRA
    parsed = TileExtra.deserialize_extra(Buffer(raw), 0, 0, 27)

    assert isinstance(parsed, CybotTile)
    assert len(parsed.commands) == 1
    command = parsed.commands[0]
    assert command.item_id == 5684  # Command - Basic Shot Right
    assert command.enabled == 1
    assert command.unk20 == 0
    assert command.unk24 == 0
    assert command.name == b""
    assert parsed.anchor_ms == 285_145_971
    assert parsed.activated == 1

    # ...and serializing it back reproduces the captured bytes (type prefix included)
    assert parsed.serialize(0, 0, 27) == raw
