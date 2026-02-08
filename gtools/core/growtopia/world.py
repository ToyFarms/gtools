# shoutout https://github.com/CLOEI/gtworld-r/tree/284a2bb9f501e740401c4f0aa025d11adbed2b02

from dataclasses import dataclass, field
from enum import IntFlag, IntEnum
import logging
from typing import Iterator, Type

from pyglm.glm import ivec2, vec2
from gtools.baked.items import (
    AUCTION_BLOCK,
    AUTO_SURGEON_STATION,
    BATTLE_PET_CAGE,
    BOUNTIFUL_BAMBOO_BACKGROUND_ROOTS,
    BOUNTIFUL_BAMBOO_LADDER_ROOTS,
    BOUNTIFUL_BAMBOO_PLATFORM_ROOTS,
    BOUNTIFUL_BAMBOO_SPIKES_ROOTS,
    BOUNTIFUL_CLIMBING_HYDRANGEA_LATTICE_ROOTS,
    BOUNTIFUL_CORPSE_FLOWER_ROOTS,
    BOUNTIFUL_FLOWERING_GARLAND_ROOTS,
    BOUNTIFUL_FLOWERING_LATTICE_ROOTS,
    BOUNTIFUL_GROWTOPIAN_EATING_LOOMING_PLANT_ROOTS,
    BOUNTIFUL_JUNGLE_TEMPLE_BACKGROUND_ROOTS,
    BOUNTIFUL_JUNGLE_TEMPLE_DOOR_ROOTS,
    BOUNTIFUL_JUNGLE_TEMPLE_PILLAR_ROOTS,
    BOUNTIFUL_JUNGLE_TEMPLE_ROOTS,
    BOUNTIFUL_LATTICE_FENCE_ROOTS,
    BOUNTIFUL_MONKSHOOD_ROOTS,
    BOUNTIFUL_WHITE_DOLL_S_EYES_ROOTS,
    DATA_BEDROCK,
    DATA_BEDROCK_CANDY,
    DATA_STARSHIP_HULL,
    EPOCH_MACHINE,
    GUILD_LOCK,
    INFINITY_WEATHER_MACHINE,
    KRANKEN_S_GALACTIC_BLOCK,
    OFFERING_TABLE,
    OPERATING_TABLE,
    PARTY_PROJECTOR,
    WEATHER_MACHINE_BACKGROUND,
)
from gtools.core.buffer import Buffer
import cbor2

from gtools.core.growtopia.items_dat import ItemInfoFlag2, ItemInfoTextureType, ItemInfoType, item_database
from gtools.core.growtopia.packet import NetPacket, TankPacket
from gtools.core.growtopia.player import Player
from gtools.core.growtopia.rttex import RtTexManager
from gtools.protogen import growtopia_pb2
import numpy as np
import numpy.typing as npt

from gtools import setting


@dataclass(slots=True)
class SilkwormColor:
    a: int = 0  # u8
    r: int = 0  # u8
    g: int = 0  # u8
    b: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer) -> "SilkwormColor":
        color = int.from_bytes(s.read_bytes(4))
        t = SilkwormColor(
            a=(color >> 24) & 0xFF,
            r=(color >> 16) & 0xFF,
            g=(color >> 8) & 0xFF,
            b=(color >> 0) & 0xFF,
        )

        return t


@dataclass(slots=True)
class FishInfo:
    fish_item_id: int = 0  # u32
    lbs: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer) -> "FishInfo":
        t = cls()
        t.fish_item_id = s.read_u32()
        t.lbs = s.read_u32()
        return t


@dataclass(slots=True)
class StorageBlockItemInfo:
    unk1: bytes = b""  # 3
    id: int = 0  # u32
    unk2: int = 0  # u16
    amount: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer) -> "StorageBlockItemInfo":
        t = cls()
        t.unk1 = s.read_bytes(3)
        t.id = s.read_u32()
        t.unk2 = s.read_u16()
        t.amount = s.read_u32()

        return t


@dataclass(slots=True)
class CookingOvenIngredientInfo:
    item_id: int = 0  # u32
    amount: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer) -> "CookingOvenIngredientInfo":
        t = CookingOvenIngredientInfo()
        t.item_id = s.read_u32()
        t.amount = s.read_u32()
        return t


@dataclass(slots=True)
class CyBotCommandData:
    command_id: int = 0  # u32
    is_command_used: int = 0  # u32
    unk1: bytes = b""  # 7 byte

    @classmethod
    def deserialize(cls, s: Buffer) -> "CyBotCommandData":
        t = CyBotCommandData()
        t.command_id = s.read_u32()
        t.is_command_used = s.read_u32()
        t.unk1 = s.read_bytes(7)
        return t


@dataclass(slots=True)
class StarshipHullData:
    unk1: int = 0  # u32
    unk2: int = 0  # u32
    unk3: int = 0  # u32
    unk4: int = 0  # u32
    unk5: int = 0  # u32
    unk6: int = 0  # u32
    unk7: int = 0  # u64
    unk8: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, format_version: int) -> "StarshipHullData":
        t = cls()
        t.unk1 = s.read_u32()
        t.unk2 = s.read_u32()
        t.unk3 = s.read_u32()
        t.unk4 = s.read_u32()
        t.unk5 = s.read_u32()
        t.unk6 = s.read_u32()
        if format_version > 10:
            t.unk7 = s.read_u64()
        if format_version > 14:
            t.unk8 = s.read_u32()

        return t


class TileExtraType(IntEnum):
    NONE = 0x0
    DOOR_TILE = 0x1
    SIGN_TILE = 0x2
    LOCK_TILE = 0x3
    SEED_TILE = 0x4
    MAILBOX_TILE = 0x6
    BULLETIN_TILE = 0x7
    DICE_TILE = 0x8
    PROVIDER = 0x9
    ACHIEVEMENT_BLOCK_TILE = 0xA
    HEART_MONITOR_TILE = 0xB
    DONATION_BOX_TILE = 0xC
    STUFF_FOR_TOYS_TILE = 0xD
    MANNEQUIN_TILE = 0xE
    BUNNY_EGG_TILE = 0xF
    TEAM_TILE = 0x10
    GAME_GENERATOR_TILE = 0x11
    XENONITE_CRYSTAL_TILE = 0x12
    PHONE_BOOTH_TILE = 0x13
    CRYSTAL_TILE = 0x14
    CRIME_IN_PROGRESS_TILE = 0x15
    DISPLAY_BLOCK_TILE = 0x17
    VENDING_MACHINE_TILE = 0x18
    GIVING_TREE_TILE = 0x1C
    COUNTRY_FLAG_TILE = 0x21
    WEATHER_MACHINE_TILE = 0x28
    DATA_BEDROCK_TILE = 0x2A
    SPOTLIGHT_TILE = 0x16
    FISH_TANK_PORT_TILE = 0x19
    SOLAR_COLLECTOR_TILE = 0x1A
    FORGE_TILE = 0x1B
    STEAM_ORGAN_TILE = 0x1E
    SILKWORM_TILE = 0x1F
    SEWING_MACHINE_TILE = 0x20
    LOBSTER_TRAP_TILE = 0x22
    PAINTING_EASEL_TILE = 0x23
    PET_BATTLE_CAGE_TILE = 0x24
    PET_TRAINER_TILE = 0x25
    STEAM_ENGINE_TILE = 0x26
    LOCK_BOT_TILE = 0x27
    SPIRIT_STORAGE_UNIT_TILE = 0x29
    SHELF_TILE = 0x2B
    VIP_ENTRANCE_TILE = 0x2C
    CHALLENGE_TIMER_TILE = 0x2D
    FISH_WALL_MOUNT_TILE = 0x2F
    PORTRAIT_TILE = 0x30
    GUILD_WEATHER_MACHINE_TILE = 0x31
    FOSSIL_PREP_STATION_TILE = 0x32
    DNA_EXTRACTOR_TILE = 0x33
    BLASTER_TILE = 0x34
    CHEMSYNTH_TANK_TILE = 0x35
    STORAGE_BLOCK_TILE = 0x36
    COOKING_OVEN_TILE = 0x37
    AUDIO_RACK_TILE = 0x38
    GEIGER_CHARGER_TILE = 0x39
    ADVENTURE_BEGINS_TILE = 0x3A
    TOMB_ROBBER_TILE = 0x3B
    BALLOON_O_MATIC_TILE = 0x3C
    TRAINING_PORT_TILE = 0x3D
    ITEM_SUCKER_TILE = 0x3E
    CYBOT_TILE = 0x3F
    GUILD_ITEM_TILE = 0x41
    GROWSCAN_TILE = 0x42
    CONTAINMENT_FIELD_POWER_NODE_TILE = 0x43
    SPIRIT_BOARD_TILE = 0x44
    TESSERACT_MANIPULATOR_TILE = 0x45
    HEART_OF_GAIA_TILE = 0x46
    TECHNO_ORGANIC_ENGINE_TILE = 0x47
    STORMY_CLOUD_TILE = 0x48
    TEMPORARY_PLATFORM_TILE = 0x49
    SAFE_VAULT_TILE = 0x4A
    ANGELIC_COUNTING_CLOUD_TILE = 0x4B
    PVE_NPC_TILE = 0x4C
    INFINITY_WEATHER_MACHINE_TILE = 0x4D
    COMPLETIONIST_TILE = 0x4E  # unused
    PINEAPPLE_GUZZLER_TILE = 0x4F
    KRANKEN_GALATIC_BLOCK_TILE = 0x50
    FRIENDS_ENTRANCE_TILE = 0x51

    @staticmethod
    def from_item_type(type: ItemInfoType) -> "TileExtraType":
        return _ITEMINFO_TO_TILEEXTRA[type]


_ITEMINFO_TO_TILEEXTRA: dict[ItemInfoType, TileExtraType] = {
    ItemInfoType.USER_DOOR: TileExtraType.DOOR_TILE,
    ItemInfoType.LOCK: TileExtraType.LOCK_TILE,
    ItemInfoType.SIGN: TileExtraType.SIGN_TILE,
    ItemInfoType.DOOR: TileExtraType.DOOR_TILE,
    ItemInfoType.USER_DOOR: TileExtraType.DOOR_TILE,
    ItemInfoType.SEED: TileExtraType.SEED_TILE,
    ItemInfoType.PORTAL: TileExtraType.DOOR_TILE,
    ItemInfoType.MAILBOX: TileExtraType.MAILBOX_TILE,
    ItemInfoType.BULLETIN: TileExtraType.BULLETIN_TILE,
    ItemInfoType.DICE: TileExtraType.DICE_TILE,
    ItemInfoType.PROVIDER: TileExtraType.PROVIDER,
    ItemInfoType.ACHIEVEMENT: TileExtraType.ACHIEVEMENT_BLOCK_TILE,
    ItemInfoType.SUNGATE: TileExtraType.DOOR_TILE,
    ItemInfoType.HEART_MONITOR: TileExtraType.HEART_MONITOR_TILE,
    ItemInfoType.DONATION_BOX: TileExtraType.DONATION_BOX_TILE,
    ItemInfoType.TOYBOX: TileExtraType.STUFF_FOR_TOYS_TILE,
    ItemInfoType.MANNEQUIN: TileExtraType.MANNEQUIN_TILE,
    # ItemInfoType.CAMERA                  : , what is the extra type for jammer again?
    ItemInfoType.MAGICEGG: TileExtraType.BUNNY_EGG_TILE,
    ItemInfoType.TEAM: TileExtraType.TEAM_TILE,
    ItemInfoType.GAME_GEN: TileExtraType.GAME_GENERATOR_TILE,
    ItemInfoType.XENONITE: TileExtraType.XENONITE_CRYSTAL_TILE,
    ItemInfoType.DRESSUP: TileExtraType.PHONE_BOOTH_TILE,
    ItemInfoType.CRYSTAL: TileExtraType.CRYSTAL_TILE,
    ItemInfoType.BURGLAR: TileExtraType.CRIME_IN_PROGRESS_TILE,
    ItemInfoType.SPOTLIGHT: TileExtraType.SPOTLIGHT_TILE,
    ItemInfoType.DISPLAY_BLOCK: TileExtraType.DISPLAY_BLOCK_TILE,
    ItemInfoType.VENDING: TileExtraType.VENDING_MACHINE_TILE,
    ItemInfoType.FISHTANK: TileExtraType.FISH_TANK_PORT_TILE,
    ItemInfoType.SOLAR: TileExtraType.SOLAR_COLLECTOR_TILE,
    ItemInfoType.FORGE: TileExtraType.FORGE_TILE,
    ItemInfoType.GIVING_TREE: TileExtraType.GIVING_TREE_TILE,
    ItemInfoType.GIVING_TREE_STUMP: TileExtraType.GIVING_TREE_TILE,
    ItemInfoType.STEAM_ORGAN: TileExtraType.STEAM_ORGAN_TILE,
    ItemInfoType.TAMAGOTCHI: TileExtraType.SILKWORM_TILE,
    ItemInfoType.SEWING: TileExtraType.SEWING_MACHINE_TILE,
    ItemInfoType.FLAG: TileExtraType.COUNTRY_FLAG_TILE,
    ItemInfoType.LOBSTER_TRAP: TileExtraType.LOBSTER_TRAP_TILE,
    ItemInfoType.ARTCANVAS: TileExtraType.PAINTING_EASEL_TILE,
    ItemInfoType.BATTLE_CAGE: TileExtraType.PET_BATTLE_CAGE_TILE,
    ItemInfoType.PET_TRAINER: TileExtraType.PET_TRAINER_TILE,
    ItemInfoType.STEAM_ENGINE: TileExtraType.STEAM_ENGINE_TILE,
    ItemInfoType.LOCK_BOT: TileExtraType.LOCK_BOT_TILE,
    ItemInfoType.WEATHER_SPECIAL: TileExtraType.WEATHER_MACHINE_TILE,
    ItemInfoType.SPIRIT_STORAGE: TileExtraType.SPIRIT_STORAGE_UNIT_TILE,
    ItemInfoType.DISPLAY_SHELF: TileExtraType.SHELF_TILE,
    ItemInfoType.VIP_DOOR: TileExtraType.VIP_ENTRANCE_TILE,
    ItemInfoType.CHAL_TIMER: TileExtraType.CHALLENGE_TIMER_TILE,
    ItemInfoType.CHAL_FLAG: TileExtraType.CHALLENGE_TIMER_TILE,
    ItemInfoType.FISH_MOUNT: TileExtraType.FISH_WALL_MOUNT_TILE,
    ItemInfoType.PORTRAIT: TileExtraType.PORTRAIT_TILE,
    ItemInfoType.WEATHER_SPECIAL2: TileExtraType.GUILD_WEATHER_MACHINE_TILE,
    ItemInfoType.FOSSIL_PREP: TileExtraType.FOSSIL_PREP_STATION_TILE,
    ItemInfoType.DNA_MACHINE: TileExtraType.DNA_EXTRACTOR_TILE,
    ItemInfoType.BLASTER: TileExtraType.BLASTER_TILE,
    ItemInfoType.CHEMTANK: TileExtraType.CHEMSYNTH_TANK_TILE,
    ItemInfoType.STORAGE: TileExtraType.STORAGE_BLOCK_TILE,
    ItemInfoType.OVEN: TileExtraType.COOKING_OVEN_TILE,
    ItemInfoType.SUPER_MUSIC: TileExtraType.AUDIO_RACK_TILE,
    ItemInfoType.GEIGERCHARGE: TileExtraType.GEIGER_CHARGER_TILE,
    ItemInfoType.ADVENTURE_RESET: TileExtraType.ADVENTURE_BEGINS_TILE,
    ItemInfoType.TOMB_ROBBER: TileExtraType.TOMB_ROBBER_TILE,
    ItemInfoType.FACTION: TileExtraType.BALLOON_O_MATIC_TILE,
    # ItemInfoType.RED_FACTION             : , entrance, idk what is the tile extra for this
    # ItemInfoType.GREEN_FACTION           : ,
    # ItemInfoType.BLUE_FACTION            : ,
    ItemInfoType.FISHGOTCHI_TANK: TileExtraType.TRAINING_PORT_TILE,
    ItemInfoType.ITEM_SUCKER: TileExtraType.ITEM_SUCKER_TILE,
    ItemInfoType.ROBOT: TileExtraType.CYBOT_TILE,
    ItemInfoType.LUCKY_TICKET: TileExtraType.ANGELIC_COUNTING_CLOUD_TILE,  # maybe? the wiki mentions raffling
    ItemInfoType.STATS_BLOCK: TileExtraType.GROWSCAN_TILE,
    ItemInfoType.FIELD_NODE: TileExtraType.CONTAINMENT_FIELD_POWER_NODE_TILE,
    ItemInfoType.OUIJA_BOARD: TileExtraType.SPIRIT_BOARD_TILE,
    ItemInfoType.AUTO_ACTION_BREAK: TileExtraType.TESSERACT_MANIPULATOR_TILE,
    ItemInfoType.AUTO_ACTION_HARVEST: TileExtraType.HEART_OF_GAIA_TILE,
    ItemInfoType.AUTO_ACTION_HARVEST_SUCK: TileExtraType.TECHNO_ORGANIC_ENGINE_TILE,
    ItemInfoType.LIGHTNING_CLOUD: TileExtraType.STORMY_CLOUD_TILE,
    ItemInfoType.PHASED_BLOCK: TileExtraType.TEMPORARY_PLATFORM_TILE,
    ItemInfoType.PASSWORD_STORAGE: TileExtraType.SAFE_VAULT_TILE,
    ItemInfoType.PHASED_BLOCK2: TileExtraType.ANGELIC_COUNTING_CLOUD_TILE,
    ItemInfoType.PVE_NPC: TileExtraType.PVE_NPC_TILE,
    ItemInfoType.INFINITY_WEATHER_MACHINE: TileExtraType.INFINITY_WEATHER_MACHINE_TILE,
    ItemInfoType.COMPLETIONIST: TileExtraType.COMPLETIONIST_TILE,
    ItemInfoType.FEEDING_BLOCK: TileExtraType.PINEAPPLE_GUZZLER_TILE,
    ItemInfoType.KRANKENS_BLOCK: TileExtraType.KRANKEN_GALATIC_BLOCK_TILE,
    ItemInfoType.FRIENDS_ENTRANCE: TileExtraType.FRIENDS_ENTRANCE_TILE,
}


@dataclass(slots=True)
class TileExtra:
    type: TileExtraType = TileExtraType.NONE

    @classmethod
    def deserialize(cls, s: Buffer, fg: int = -1, bg: int = -1, format_version=999999999) -> "TileExtra":
        type = s.read_u8()
        handler = _TILE_EXTRA_REGISTRY.get(type)
        if not handler:
            raise NotImplementedError(f"no tile extra for id {type}")

        extra = handler.deserialize(s, fg, bg, format_version)
        extra.type = TileExtraType(type)

        item = item_database.get(fg or bg)
        if item.id == DATA_STARSHIP_HULL and format_version > 4:
            print(StarshipHullData.deserialize(s, format_version))

        return extra

    @classmethod
    def new(cls, type: TileExtraType) -> "TileExtra":
        extra = _TILE_EXTRA_REGISTRY.get(type)
        if not extra:
            raise NotImplementedError(f"no tile extra for id {type}")
        return extra()

    def expect[T](self, expect: Type[T]) -> T:
        if not isinstance(self, expect):
            raise TypeError(f"expected {expect.__class__} but got {self.__class__}")
        return self


@dataclass(slots=True)
class DoorTile(TileExtra):
    text: bytes = b""
    unk1: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "DoorTile":
        t = cls()
        t.text = s.read_pascal_bytes("H")
        t.unk1 = s.read_u8()

        return t


@dataclass(slots=True)
class SignTile(TileExtra):
    text: bytes = b""
    unk1: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SignTile":
        t = cls()
        t.text = s.read_pascal_bytes("H")
        t.unk1 = s.read_u32()

        return t


@dataclass(slots=True)
class LockTile(TileExtra):
    flags: int = 0  # u8
    owner_uid: int = 0  # u32
    access_count: int = 0  # u32
    access_uids: list[int] = field(default_factory=list)  # Vec<u32>
    minimum_level: int = 0  # u32
    unk1: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "LockTile":
        t = cls()
        t.flags = s.read_u8()
        t.owner_uid = s.read_u32()
        t.access_count = s.read_u32()
        for _ in range(t.access_count):
            t.access_uids.append(s.read_u32())
        if format_version >= 12:
            t.minimum_level = s.read_u32()
        if format_version >= 13:
            t.unk1 = s.read_u32()

        return t


@dataclass(slots=True)
class SeedTile(TileExtra):
    time_passed: int = 0  # u32
    item_on_tree: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SeedTile":
        t = cls()
        t.time_passed = s.read_u32()
        t.item_on_tree = s.read_u8()

        return t


@dataclass(slots=True)
class MailboxTile(TileExtra):
    unk1: bytes = b""
    unk2: bytes = b""
    unk3: bytes = b""
    unk4: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "MailboxTile":
        t = cls()
        t.unk1 = s.read_pascal_bytes("H")
        t.unk2 = s.read_pascal_bytes("H")
        t.unk3 = s.read_pascal_bytes("H")
        t.unk4 = s.read_u8()

        return t


@dataclass(slots=True)
class BulletinTile(TileExtra):
    unk1: bytes = b""
    unk2: bytes = b""
    unk3: bytes = b""
    unk4: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "BulletinTile":
        t = cls()
        t.unk1 = s.read_pascal_bytes("H")
        t.unk2 = s.read_pascal_bytes("H")
        t.unk3 = s.read_pascal_bytes("H")
        t.unk4 = s.read_u8()

        return t


@dataclass(slots=True)
class DiceTile(TileExtra):
    symbol: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "DiceTile":
        t = cls()
        t.symbol = s.read_u8()

        return t


@dataclass(slots=True)
class ProviderTile(TileExtra):
    time_passed: int = 0  # u32
    time_ms: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ProviderTile":
        t = cls()
        t.time_passed = s.read_u32()

        # well of love, winter calendar 2017
        if (fg_id == 10656 and format_version > 16) or fg_id == 5318:
            t.time_ms = s.read_u32()

        return t


@dataclass(slots=True)
class AchievementBlockTile(TileExtra):
    unk1: int = 0  # u32
    tile_type: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "AchievementBlockTile":
        t = cls()
        t.unk1 = s.read_u32()
        t.tile_type = s.read_u8()

        return t


@dataclass(slots=True)
class HeartMonitorTile(TileExtra):
    unk1: int = 0  # u32
    player_name: bytes = b""

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "HeartMonitorTile":
        t = cls()
        t.unk1 = s.read_u32()
        t.player_name = s.read_pascal_bytes("H")

        return t


@dataclass(slots=True)
class DonationBoxTile(TileExtra):
    unk1: bytes = b""
    unk2: bytes = b""
    unk3: bytes = b""
    unk4: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "DonationBoxTile":
        t = cls()
        t.unk1 = s.read_pascal_bytes("H")
        t.unk2 = s.read_pascal_bytes("H")
        t.unk3 = s.read_pascal_bytes("H")
        t.unk4 = s.read_u8()

        return t


@dataclass(slots=True)
class StuffForToysTile(TileExtra):
    unk1: bytes = b""
    unk2: bytes = b""
    unk3: bytes = b""
    unk4: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "StuffForToysTile":
        t = cls()
        t.unk1 = s.read_pascal_bytes("H")
        t.unk2 = s.read_pascal_bytes("H")
        t.unk3 = s.read_pascal_bytes("H")
        t.unk4 = s.read_u8()

        return t


@dataclass(slots=True)
class MannequinTile(TileExtra):
    text: bytes = b""
    unk1: int = 0  # u8
    unk2: int = 0  # u32
    clothing_1: int = 0  # u16
    clothing_2: int = 0  # u16
    clothing_3: int = 0  # u16
    clothing_4: int = 0  # u16
    clothing_5: int = 0  # u16
    clothing_6: int = 0  # u16
    clothing_7: int = 0  # u16
    clothing_8: int = 0  # u16
    clothing_9: int = 0  # u16

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "MannequinTile":
        t = cls()
        t.text = s.read_pascal_bytes("H")
        t.unk1 = s.read_u8()
        t.unk2 = s.read_u32()
        t.clothing_1 = s.read_u16()
        t.clothing_2 = s.read_u16()
        t.clothing_3 = s.read_u16()
        t.clothing_4 = s.read_u16()
        t.clothing_5 = s.read_u16()
        t.clothing_6 = s.read_u16()
        t.clothing_7 = s.read_u16()
        t.clothing_8 = s.read_u16()
        t.clothing_9 = s.read_u16()

        return t


@dataclass(slots=True)
class BunnyEggTile(TileExtra):
    eggs_placed: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "BunnyEggTile":
        t = cls()
        t.eggs_placed = s.read_u32()

        return t


@dataclass(slots=True)
class TeamTile(TileExtra):
    team: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "TeamTile":
        t = cls()
        t.team = s.read_u8()

        return t


@dataclass(slots=True)
class GameGeneratorTile(TileExtra):
    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GameGeneratorTile":
        t = cls()
        return t


@dataclass(slots=True)
class XenoniteCrystalTile(TileExtra):
    unk1: int = 0  # u8
    unk2: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "XenoniteCrystalTile":
        t = cls()
        t.unk1 = s.read_u8()
        t.unk2 = s.read_u32()

        return t


@dataclass(slots=True)
class PhoneBoothTile(TileExtra):
    clothing_1: int = 0  # u16
    clothing_2: int = 0  # u16
    clothing_3: int = 0  # u16
    clothing_4: int = 0  # u16
    clothing_5: int = 0  # u16
    clothing_6: int = 0  # u16
    clothing_7: int = 0  # u16
    clothing_8: int = 0  # u16
    clothing_9: int = 0  # u16

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PhoneBoothTile":
        t = cls()
        t.clothing_1 = s.read_u16()
        t.clothing_2 = s.read_u16()
        t.clothing_3 = s.read_u16()
        t.clothing_4 = s.read_u16()
        t.clothing_5 = s.read_u16()
        t.clothing_6 = s.read_u16()
        t.clothing_7 = s.read_u16()
        t.clothing_8 = s.read_u16()
        t.clothing_9 = s.read_u16()

        return t


@dataclass(slots=True)
class CrystalTile(TileExtra):
    unk1: bytes = b""

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "CrystalTile":
        t = cls()
        t.unk1 = s.read_pascal_bytes("H")

        return t


@dataclass(slots=True)
class CrimeInProgressTile(TileExtra):
    unk1: bytes = b""
    unk2: int = 0  # u32
    unk3: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "CrimeInProgressTile":
        t = CrimeInProgressTile()
        t.unk1 = s.read_pascal_bytes("H")
        t.unk2 = s.read_u32()
        t.unk3 = s.read_u8()
        return t


@dataclass(slots=True)
class DisplayBlockTile(TileExtra):
    item_id: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "DisplayBlockTile":
        t = cls()
        t.item_id = s.read_u32()

        return t


@dataclass(slots=True)
class VendingMachineTile(TileExtra):
    item_id: int = 0  # u32
    price: int = 0  # i32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "VendingMachineTile":
        t = cls()
        t.item_id = s.read_u32()
        t.price = s.read_i32()

        return t


@dataclass(slots=True)
class GivingTreeTile(TileExtra):
    unk1: int = 0  # u16
    unk2: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GivingTreeTile":
        t = cls()
        t.unk1 = s.read_u16()
        t.unk2 = s.read_u32()
        return t


@dataclass(slots=True)
class CountryFlagTile(TileExtra):
    country: bytes = b""

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "CountryFlagTile":
        t = cls()
        t.country = s.read_pascal_bytes("H")

        return t


@dataclass(slots=True)
class WeatherMachineTile(TileExtra):
    item_id: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "WeatherMachineTile":
        t = cls()
        t.item_id = s.read_u32()

        return t


@dataclass(slots=True)
class DataBedrockTile(TileExtra):
    unk1: int = 0  # u8
    unk2: int = 0  # u32
    unk3: int = 0  # u32
    unk4: int = 0  # u32
    unk5: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "DataBedrockTile":
        t = cls()
        s.rpos += 1
        if format_version > 18:
            t.unk1 = s.read_u32()
            t.unk2 = s.read_u32()
            t.unk3 = s.read_u32()
        if format_version > 19:
            t.unk4 = s.read_u32()
            t.unk5 = s.read_u32()

        return t


@dataclass(slots=True)
class SpotlightTile(TileExtra):

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SpotlightTile":
        t = SpotlightTile()
        return t


@dataclass(slots=True)
class FishTankPortTile(TileExtra):
    flags: int = 0  # u8
    fishes: list[FishInfo] = field(default_factory=list)

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "FishTankPortTile":
        t = cls()
        t.flags = s.read_u8()

        for _ in range(s.read_u32() // 2):
            t.fishes.append(FishInfo.deserialize(s))

        return t


@dataclass(slots=True)
class SolarCollectorTile(TileExtra):
    unk1: int = 0  # u8
    unk2: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SolarCollectorTile":
        t = cls()
        t.unk1 = s.read_u8()
        t.unk2 = s.read_u32()

        return t


@dataclass(slots=True)
class ForgeTile(TileExtra):
    temperature: int = 0  # u32
    unk1: int = 0  # u8
    unk2: int = 0  # u16

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ForgeTile":
        t = cls()
        t.temperature = s.read_u8()
        t.unk1 = s.read_u8()
        t.unk2 = s.read_u16()

        return t


@dataclass(slots=True)
class SteamOrganTile(TileExtra):
    instrument_type: int = 0  # u8
    note: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SteamOrganTile":
        t = cls()
        t.instrument_type = s.read_u8()
        t.note = s.read_u32()

        return t


@dataclass(slots=True)
class SilkwormTile(TileExtra):
    flags: int = 0  # u8
    name: bytes = b""
    age: int = 0  # u32
    unk1: int = 0  # u32
    unk2: int = 0  # u32
    can_be_fed: int = 0  # u8
    food_saturation: int = 0  # u32
    water_saturation: int = 0  # u32
    color: SilkwormColor = field(default_factory=SilkwormColor)
    sick_duration: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SilkwormTile":
        t = cls()

        t.flags = s.read_u8()
        t.name = s.read_pascal_bytes("H")
        t.age = s.read_u32()
        t.unk1 = s.read_u32()
        t.unk2 = s.read_u32()
        t.can_be_fed = s.read_u8()
        t.food_saturation = s.read_u32()
        t.water_saturation = s.read_u32()
        t.color = SilkwormColor.deserialize(s)
        t.sick_duration = s.read_u32()

        return t


@dataclass(slots=True)
class SewingMachineTile(TileExtra):
    bolt_id_list: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SewingMachineTile":
        t = cls()

        for _ in range(s.read_u32()):
            t.bolt_id_list.append(s.read_u32())

        return t


@dataclass(slots=True)
class LobsterTrapTile(TileExtra):

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "LobsterTrapTile":
        t = LobsterTrapTile()
        return t


@dataclass(slots=True)
class PaintingEaselTile(TileExtra):
    item_id: int = 0  # u32
    label: bytes = b""

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PaintingEaselTile":
        t = cls()
        t.item_id = s.read_u32()
        t.label = s.read_pascal_bytes("H")

        return t


@dataclass(slots=True)
class PetBattleCageTile(TileExtra):
    name: bytes = b""
    unk1: bytes = b""

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PetBattleCageTile":
        t = cls()
        t.name = s.read_pascal_bytes("H")
        t.unk1 = s.read_bytes(12)
        return t


@dataclass(slots=True)
class PetTrainerTile(TileExtra):
    name: bytes = b""
    pet_count: int = 0  # u32
    unk1: int = 0  # u32
    pets_id: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PetTrainerTile":
        t = cls()
        t.name = s.read_pascal_bytes("H")
        t.pet_count = s.read_u32()
        t.unk1 = s.read_u32()

        for _ in range(t.pet_count):
            t.pets_id.append(s.read_u32())

        return t


@dataclass(slots=True)
class SteamEngineTile(TileExtra):
    temperature: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SteamEngineTile":
        t = cls()
        t.temperature = s.read_u32()

        return t


@dataclass(slots=True)
class LockBotTile(TileExtra):
    time_passed: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "LockBotTile":
        t = cls()
        t.time_passed = s.read_u32()

        return t


@dataclass(slots=True)
class SpiritStorageUnitTile(TileExtra):
    ghost_jar_count: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SpiritStorageUnitTile":
        t = cls()
        t.ghost_jar_count = s.read_u32()

        return t


@dataclass(slots=True)
class ShelfTile(TileExtra):
    top_left_item_id: int = 0  # u32
    top_right_item_id: int = 0  # u32
    bottom_left_item_id: int = 0  # u32
    bottom_right_item_id: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ShelfTile":
        t = cls()
        t.top_left_item_id = s.read_u32()
        t.top_right_item_id = s.read_u32()
        t.bottom_left_item_id = s.read_u32()
        t.bottom_right_item_id = s.read_u32()

        return t


@dataclass(slots=True)
class VipEntranceTile(TileExtra):
    unk1: int = 0  # u8
    owner_uid: int = 0  # u32
    access_uids: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "VipEntranceTile":
        t = cls()
        t.unk1 = s.read_u8()
        t.owner_uid = s.read_u32()
        size = s.read_u32()
        for _ in range(size):
            t.access_uids.append(s.read_u32())

        return t


@dataclass(slots=True)
class ChallengeTimerTile(TileExtra):

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ChallengeTimerTile":
        t = cls()

        return t


@dataclass(slots=True)
class FishWallMountTile(TileExtra):
    label: bytes = b""
    item_id: int = 0  # u32
    lb: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "FishWallMountTile":
        t = cls()
        t.label = s.read_pascal_bytes("H")
        t.item_id = s.read_u32()
        t.lb = s.read_u8()

        return t


@dataclass(slots=True)
class PortraitTile(TileExtra):
    label: bytes = b""
    unk1: int = 0
    unk2: int = 0
    unk3: int = 0
    unk4: int = 0
    unk5: int = 0
    unk6: int = 0
    face: int = 0
    hat: int = 0
    hair: int = 0
    unk10: int = 0

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PortraitTile":
        t = cls()
        t.label = s.read_pascal_bytes("H")
        t.unk1 = s.read_u32()
        t.unk2 = s.read_u32()
        t.unk3 = s.read_u32()
        t.unk4 = s.read_u32()
        t.unk5 = s.read_u8()
        t.unk6 = s.read_u8()
        t.face = s.read_u16()
        t.hat = s.read_u16()
        t.hair = s.read_u16()
        t.unk10 = s.read_u16()

        return t


@dataclass(slots=True)
class GuildWeatherMachineTile(TileExtra):
    cycle_time_ms: int = 0  # u32
    gravity: int = 0  # u32
    flags: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GuildWeatherMachineTile":
        t = cls()
        t.cycle_time_ms = s.read_u32()
        t.gravity = s.read_u32()
        t.flags = s.read_u8()

        return t


@dataclass(slots=True)
class FossilPrepStationTile(TileExtra):
    unk1: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "FossilPrepStationTile":
        t = cls()
        t.unk1 = s.read_u32()
        return t


@dataclass(slots=True)
class DnaExtractorTile(TileExtra):

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "DnaExtractorTile":
        t = cls()
        return t


@dataclass(slots=True)
class BlasterTile(TileExtra):

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "BlasterTile":
        t = cls()
        return t


@dataclass(slots=True)
class ChemsynthTankTile(TileExtra):
    current_chem: int = 0  # u32
    target_chem: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ChemsynthTankTile":
        t = cls()
        t.current_chem = s.read_u32()
        t.target_chem = s.read_u32()

        return t


@dataclass(slots=True)
class StorageBlockTile(TileExtra):
    items: list[StorageBlockItemInfo] = field(default_factory=list)

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "StorageBlockTile":
        t = cls()
        for _ in range(s.read_u16() // 13):
            t.items.append(StorageBlockItemInfo.deserialize(s))

        return t


@dataclass(slots=True)
class CookingOvenTile(TileExtra):
    temperature_level: int = 0  # u32
    ingredients: list[CookingOvenIngredientInfo] = field(default_factory=list)
    unk1: int = 0  # u32
    unk2: int = 0  # u32
    unk3: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "CookingOvenTile":
        t = cls()
        t.temperature_level = s.read_u32()

        for _ in range(s.read_u32()):
            t.ingredients.append(CookingOvenIngredientInfo.deserialize(s))

        t.unk1 = s.read_u32()
        t.unk2 = s.read_u32()
        t.unk3 = s.read_u32()

        return t


@dataclass(slots=True)
class AudioRackTile(TileExtra):
    note: bytes = b""
    volume: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "AudioRackTile":
        t = cls()
        t.note = s.read_pascal_bytes("H")
        t.volume = s.read_u32()

        return t


@dataclass(slots=True)
class GeigerChargerTile(TileExtra):
    unk1: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GeigerChargerTile":
        t = cls()
        t.unk1 = s.read_u32()
        return t


@dataclass(slots=True)
class AdventureBeginsTile(TileExtra):

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "AdventureBeginsTile":
        t = cls()
        return t


@dataclass(slots=True)
class TombRobberTile(TileExtra):

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "TombRobberTile":
        return TombRobberTile()


@dataclass(slots=True)
class BalloonOMaticTile(TileExtra):
    total_rarity: int = 0  # u32
    team_type: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "BalloonOMaticTile":
        t = BalloonOMaticTile()
        t.total_rarity = s.read_u32()
        t.team_type = s.read_u8()

        return t


@dataclass(slots=True)
class TrainingPortTile(TileExtra):
    fish_lb: int = 0  # u32
    fish_status: int = 0  # u16
    fish_id: int = 0  # u32
    fish_total_exp: int = 0  # u32
    fish_level: int = 0  # u32
    unk2: int = 0  # u32
    unk3: bytes = b""  # u8 * 13

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "TrainingPortTile":
        t = TrainingPortTile()
        t.fish_lb = s.read_u32()
        t.fish_status = s.read_u16()
        t.fish_id = s.read_u32()
        t.fish_total_exp = s.read_u32()
        t.fish_level = s.read_u32()
        t.unk2 = s.read_u32()
        t.unk3 = s.read_bytes(13)

        return t


@dataclass(slots=True)
class ItemSuckerTile(TileExtra):
    item_id_to_suck: int = 0  # u32
    item_amount: int = 0  # u32
    flags: int = 0  # u16
    limit: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ItemSuckerTile":
        t = cls()
        t.item_id_to_suck = s.read_u32()
        t.item_amount = s.read_u32()
        t.flags = s.read_u16()
        t.limit = s.read_u32()

        return t


@dataclass(slots=True)
class CybotTile(TileExtra):
    commands: list[CyBotCommandData] = field(default_factory=list)
    sync_timer: int = 0  # u32
    activated: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "CybotTile":
        t = cls()

        for _ in range(s.read_u32()):
            t.commands.append(CyBotCommandData.deserialize(s))

        t.sync_timer = s.read_u32()
        t.activated = s.read_u32()

        return t


@dataclass(slots=True)
class GuildItemTile(TileExtra):
    unk1: int = 0  # u8
    unk2: int = 0  # u32
    unk3: int = 0  # u32
    unk4: int = 0  # u32
    unk5: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GuildItemTile":
        t = cls()
        if id != GUILD_LOCK:
            t.unk1 = s.read_u8()
        t.unk2 = s.read_u32()
        t.unk3 = s.read_u32()
        t.unk4 = s.read_u32()
        t.unk5 = s.read_u32()
        return t


@dataclass(slots=True)
class GrowscanTile(TileExtra):
    unk1: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GrowscanTile":
        t = cls()
        t.unk1 = s.read_u8()
        return t


@dataclass(slots=True)
class ContainmentFieldPowerNodeTile(TileExtra):
    time_ms: int = 0  # u32
    unk1: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ContainmentFieldPowerNodeTile":
        t = cls()
        t.time_ms = s.read_u32()
        for _ in range(s.read_u32()):
            t.unk1.append(s.read_u32())
        return t


@dataclass(slots=True)
class SpiritBoardTile(TileExtra):
    unk1: int = 0  # u32
    unk2: bytes = b""
    unk3: bytes = b""
    unk4: list[int] = field(default_factory=list)

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SpiritBoardTile":
        t = cls()
        t.unk1 = s.read_u32()
        t.unk2 = s.read_pascal_bytes("H")
        t.unk3 = s.read_pascal_bytes("H")
        for _ in range(s.read_u32()):
            t.unk4.append(s.read_u32())
        return t


@dataclass(slots=True)
class TesseractManipulatorTile(TileExtra):
    gems: int = 0  # u32
    next_update_ms: int = 0  # u32
    item_id: int = 0  # u32
    enabled: bool = False  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "TesseractManipulatorTile":
        t = cls()
        t.gems = s.read_u32()
        t.next_update_ms = s.read_u32()
        t.item_id = s.read_u32()
        if format_version >= 8:
            t.enabled = s.read_u32() != 0

        return t


@dataclass(slots=True)
class HeartOfGaiaTile(TileExtra):
    gems: int = 0  # u32
    next_update_ms: int = 0  # u32
    item_id: int = 0  # u32
    enabled: bool = False  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "HeartOfGaiaTile":
        t = cls()
        t.gems = s.read_u32()
        t.next_update_ms = s.read_u32()
        t.item_id = s.read_u32()
        if format_version >= 8:
            t.enabled = s.read_u32() != 0

        return t


@dataclass(slots=True)
class TechnoOrganicEngineTile(TileExtra):
    unk1: int = 0  # u32
    unk2: int = 0  # u32
    unk3: int = 0  # u32
    unk4: int = 0  # u32
    unk5: int = 0  # u32
    unk6: int = 0  # u32
    unk7: int = 0  # u8
    unk8: int = 0  # u8
    unk9: int = 0  # u32
    unk10: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "TechnoOrganicEngineTile":
        t = cls()
        t.unk1 = s.read_u32()
        t.unk2 = s.read_u32()
        t.unk3 = s.read_u32()
        if format_version > 8:
            t.unk4 = s.read_u32()
        t.unk5 = s.read_u32()
        t.unk6 = s.read_u32()
        t.unk7 = s.read_u8()
        t.unk8 = s.read_u8()
        t.unk9 = s.read_u32()
        t.unk10 = s.read_u32()

        return t


@dataclass(slots=True)
class StormyCloudTile(TileExtra):
    sting_duration: int = 0  # u32
    is_solid: int = 0  # u32
    non_solid_duration: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "StormyCloudTile":
        t = cls()
        t.sting_duration = s.read_u32()
        t.is_solid = s.read_u32()
        t.non_solid_duration = s.read_u32()

        return t


@dataclass(slots=True)
class TemporaryPlatformTile(TileExtra):
    time_ms: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "TemporaryPlatformTile":
        t = cls()
        t.time_ms = s.read_u32()
        return TemporaryPlatformTile()


@dataclass(slots=True)
class SafeVaultTile(TileExtra):

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SafeVaultTile":
        t = SafeVaultTile()
        return t


@dataclass(slots=True)
class AngelicCountingCloudTile(TileExtra):
    is_raffling: int = 0  # u32
    ascii: bytes = b""

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "AngelicCountingCloudTile":
        t = cls()
        t.is_raffling = s.read_u32()
        t.ascii = s.read_pascal_bytes("H")
        return t


@dataclass(slots=True)
class PveNpcData:
    field_1: int = 0  # u32
    field_2: int = 0  # u32
    field_3: int = 0  # u32
    field_4: int = 0  # u32
    field_5: int = 0  # u32
    field_b6: bool = False  # u32
    field_b7: bool = False  # u32
    field_8: int = 0  # u32
    field_9: int = 0  # u32
    field_10: int = 0  # u32
    field_b11: bool = False  # u32
    field_12: int = 0  # u32
    field_13: int = 0  # u32
    field_14: int = 0  # u32
    field_b15: bool = False  # u32
    field_16: int = 0  # u32
    field_17: int = 0  # u32
    field_18: int = 0  # u32
    field_19: int = 0  # u32
    field_b20: bool = False  # u32
    field_21: int = 0  # u32
    field_22: int = 0  # u32
    field_23: int = 0  # u32
    field_25: int = 0  # u32
    field_b26: bool = False  # u32
    pos: list[tuple[int, int]] = field(default_factory=list)  # vector<vec2<i32>>

    @classmethod
    def deserialize(cls, s: Buffer) -> "PveNpcData":
        t = cls()
        t.field_1 = s.read_u32()
        t.field_2 = s.read_u32()
        t.field_3 = s.read_u32()
        t.field_4 = s.read_u32()
        t.field_5 = s.read_u32()
        t.field_b6 = s.read_u32() != 0
        t.field_b7 = s.read_u32() != 0
        t.field_8 = s.read_u32()
        t.field_9 = s.read_u32()
        t.field_10 = s.read_u32()
        t.field_b11 = s.read_u32() != 0
        t.field_12 = s.read_u32()
        t.field_13 = s.read_u32()
        t.field_14 = s.read_u32()
        t.field_b15 = s.read_u32() != 0
        t.field_16 = s.read_u32()
        t.field_17 = s.read_u32()
        t.field_18 = s.read_u32()
        t.field_19 = s.read_u32()
        t.field_b20 = s.read_u32() != 0
        t.field_21 = s.read_u32()
        t.field_22 = s.read_u32()
        t.field_23 = s.read_u32()
        t.field_25 = s.read_u32()
        t.field_b26 = s.read_u32() != 0
        for _ in range(s.read_u32()):
            t.pos.append((s.read_u32(), s.read_u32()))

        return t


@dataclass(slots=True)
class PveNpcTile(TileExtra):
    arr: list[PveNpcData] = field(default_factory=list)  # len 3

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PveNpcTile":
        t = cls()
        for i in range(3):
            t.arr.append(PveNpcData.deserialize(s))

        return t


@dataclass(slots=True)
class InfinityWeatherMachineTile(TileExtra):
    cycle_time_ms: int = 0  # u32
    weather_machine_list: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "InfinityWeatherMachineTile":
        t = cls()
        t.cycle_time_ms = s.read_u32()
        for _ in range(s.read_u32()):
            t.weather_machine_list.append(s.read_u32())

        return t


@dataclass(slots=True)
class CompletionistTile(TileExtra):
    unk1: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "CompletionistTile":
        t = cls()
        t.unk1 = s.read_u32()

        return t


@dataclass(slots=True)
class PineappleGuzzlerTile(TileExtra):
    pineapple_fed: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PineappleGuzzlerTile":
        t = cls()
        t.pineapple_fed = s.read_u32()

        return t


@dataclass(slots=True)
class KrankenGalaticBlockTile(TileExtra):
    pattern_index: int = 0  # u8
    unk1: int = 0  # u32
    r: int = 0  # u8
    g: int = 0  # u8
    b: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "KrankenGalaticBlockTile":
        t = cls()
        t.pattern_index = s.read_u8()
        t.unk1 = s.read_u32()
        t.r = s.read_u8()
        t.g = s.read_u8()
        t.b = s.read_u8()
        return t


@dataclass(slots=True)
class FriendsEntranceTile(TileExtra):
    owner_user_id: int = 0  # u32
    unk1: int = 0  # u16
    unk2: int = 0  # u16

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "FriendsEntranceTile":
        t = cls()
        t.owner_user_id = s.read_u32()
        t.unk1 = s.read_u16()
        t.unk2 = s.read_u16()
        return t


_TILE_EXTRA_REGISTRY: dict[int, type[TileExtra]] = {
    TileExtraType.DOOR_TILE: DoorTile,
    TileExtraType.SIGN_TILE: SignTile,
    TileExtraType.LOCK_TILE: LockTile,
    TileExtraType.SEED_TILE: SeedTile,
    TileExtraType.MAILBOX_TILE: MailboxTile,
    TileExtraType.BULLETIN_TILE: BulletinTile,
    TileExtraType.DICE_TILE: DiceTile,
    TileExtraType.PROVIDER: ProviderTile,
    TileExtraType.ACHIEVEMENT_BLOCK_TILE: AchievementBlockTile,
    TileExtraType.HEART_MONITOR_TILE: HeartMonitorTile,
    TileExtraType.DONATION_BOX_TILE: DonationBoxTile,
    TileExtraType.STUFF_FOR_TOYS_TILE: StuffForToysTile,
    TileExtraType.MANNEQUIN_TILE: MannequinTile,
    TileExtraType.BUNNY_EGG_TILE: BunnyEggTile,
    TileExtraType.TEAM_TILE: TeamTile,
    TileExtraType.GAME_GENERATOR_TILE: GameGeneratorTile,
    TileExtraType.XENONITE_CRYSTAL_TILE: XenoniteCrystalTile,
    TileExtraType.PHONE_BOOTH_TILE: PhoneBoothTile,
    TileExtraType.CRYSTAL_TILE: CrystalTile,
    TileExtraType.CRIME_IN_PROGRESS_TILE: CrimeInProgressTile,
    TileExtraType.DISPLAY_BLOCK_TILE: DisplayBlockTile,
    TileExtraType.VENDING_MACHINE_TILE: VendingMachineTile,
    TileExtraType.GIVING_TREE_TILE: GivingTreeTile,
    TileExtraType.COUNTRY_FLAG_TILE: CountryFlagTile,
    TileExtraType.WEATHER_MACHINE_TILE: WeatherMachineTile,
    TileExtraType.DATA_BEDROCK_TILE: DataBedrockTile,
    TileExtraType.SPOTLIGHT_TILE: SpotlightTile,
    TileExtraType.FISH_TANK_PORT_TILE: FishTankPortTile,
    TileExtraType.SOLAR_COLLECTOR_TILE: SolarCollectorTile,
    TileExtraType.FORGE_TILE: ForgeTile,
    TileExtraType.STEAM_ORGAN_TILE: SteamOrganTile,
    TileExtraType.SILKWORM_TILE: SilkwormTile,
    TileExtraType.SEWING_MACHINE_TILE: SewingMachineTile,
    TileExtraType.LOBSTER_TRAP_TILE: LobsterTrapTile,
    TileExtraType.PAINTING_EASEL_TILE: PaintingEaselTile,
    TileExtraType.PET_BATTLE_CAGE_TILE: PetBattleCageTile,
    TileExtraType.PET_TRAINER_TILE: PetTrainerTile,
    TileExtraType.STEAM_ENGINE_TILE: SteamEngineTile,
    TileExtraType.LOCK_BOT_TILE: LockBotTile,
    TileExtraType.SPIRIT_STORAGE_UNIT_TILE: SpiritStorageUnitTile,
    TileExtraType.SHELF_TILE: ShelfTile,
    TileExtraType.VIP_ENTRANCE_TILE: VipEntranceTile,
    TileExtraType.CHALLENGE_TIMER_TILE: ChallengeTimerTile,
    TileExtraType.FISH_WALL_MOUNT_TILE: FishWallMountTile,
    TileExtraType.PORTRAIT_TILE: PortraitTile,
    TileExtraType.GUILD_WEATHER_MACHINE_TILE: GuildWeatherMachineTile,
    TileExtraType.FOSSIL_PREP_STATION_TILE: FossilPrepStationTile,
    TileExtraType.DNA_EXTRACTOR_TILE: DnaExtractorTile,
    TileExtraType.BLASTER_TILE: BlasterTile,
    TileExtraType.CHEMSYNTH_TANK_TILE: ChemsynthTankTile,
    TileExtraType.STORAGE_BLOCK_TILE: StorageBlockTile,
    TileExtraType.COOKING_OVEN_TILE: CookingOvenTile,
    TileExtraType.AUDIO_RACK_TILE: AudioRackTile,
    TileExtraType.GEIGER_CHARGER_TILE: GeigerChargerTile,
    TileExtraType.ADVENTURE_BEGINS_TILE: AdventureBeginsTile,
    TileExtraType.TOMB_ROBBER_TILE: TombRobberTile,
    TileExtraType.BALLOON_O_MATIC_TILE: BalloonOMaticTile,
    TileExtraType.TRAINING_PORT_TILE: TrainingPortTile,
    TileExtraType.ITEM_SUCKER_TILE: ItemSuckerTile,
    TileExtraType.CYBOT_TILE: CybotTile,
    TileExtraType.GUILD_ITEM_TILE: GuildItemTile,
    TileExtraType.GROWSCAN_TILE: GrowscanTile,
    TileExtraType.CONTAINMENT_FIELD_POWER_NODE_TILE: ContainmentFieldPowerNodeTile,
    TileExtraType.SPIRIT_BOARD_TILE: SpiritBoardTile,
    TileExtraType.TESSERACT_MANIPULATOR_TILE: TesseractManipulatorTile,
    TileExtraType.HEART_OF_GAIA_TILE: HeartOfGaiaTile,
    TileExtraType.TECHNO_ORGANIC_ENGINE_TILE: TechnoOrganicEngineTile,
    TileExtraType.STORMY_CLOUD_TILE: StormyCloudTile,
    TileExtraType.TEMPORARY_PLATFORM_TILE: TemporaryPlatformTile,
    TileExtraType.SAFE_VAULT_TILE: SafeVaultTile,
    TileExtraType.ANGELIC_COUNTING_CLOUD_TILE: AngelicCountingCloudTile,
    TileExtraType.PVE_NPC_TILE: PveNpcTile,
    TileExtraType.INFINITY_WEATHER_MACHINE_TILE: InfinityWeatherMachineTile,
    TileExtraType.COMPLETIONIST_TILE: CompletionistTile,
    TileExtraType.PINEAPPLE_GUZZLER_TILE: PineappleGuzzlerTile,
    TileExtraType.KRANKEN_GALATIC_BLOCK_TILE: KrankenGalaticBlockTile,
    TileExtraType.FRIENDS_ENTRANCE_TILE: FriendsEntranceTile,
}


class TileFlags(IntFlag):
    NONE = 0
    HAS_EXTRA_DATA = 1 << 0
    LOCKED = 1 << 1
    WAS_SPLICED = 1 << 2
    WILL_SPAWN_SEEDS_TOO = 1 << 3
    IS_SEEDLING = 1 << 4
    FLIPPED_X = 1 << 5
    IS_ON = 1 << 6
    IS_OPEN_TO_PUBLIC = 1 << 7
    BG_IS_ON = 1 << 8
    FG_ALT_MODE = 1 << 9
    IS_WET = 1 << 10
    GLUED = 1 << 11
    ON_FIRE = 1 << 12
    PAINTED_RED = 1 << 13
    PAINTED_GREEN = 1 << 14
    PAINTED_BLUE = 1 << 15


@dataclass(slots=True)
class Tile:
    fg_id: int = 0
    bg_id: int = 0
    lock_index: int = 0
    parent_index: int = 0
    flags: TileFlags = TileFlags.NONE
    extra: TileExtra | None = None
    _extra_raw: bytes = b""
    index: int = 0
    pos: ivec2 = field(default_factory=ivec2)

    # data
    fg_tex_index: int = 0
    bg_tex_index: int = 0
    json_data: dict = field(default_factory=dict)

    logger = logging.getLogger("tile")

    def get_texture(self, mgr: RtTexManager, id: int, tex_index: int) -> npt.NDArray[np.uint8]:
        item = item_database.get(id)

        stride = item.get_tex_stride()
        is_flipped = self.flags & TileFlags.FLIPPED_X != 0
        # TODO: we need to determine to ignore flipped, because some tile just doesn't care
        if is_flipped and item.texture_type == ItemInfoTextureType.SMART_EDGE_HORIZ:
            # handle flipped couch texture
            if tex_index == 0:
                tex_index = 2
            elif tex_index == 2:
                tex_index = 0

        off = ivec2(tex_index % max(stride, 1), tex_index // stride if stride else 0)
        tex = (ivec2(item.tex_coord_x, item.tex_coord_y) + off) * 32

        return mgr.get(setting.asset_path / item.texture_file.decode(), tex.x, tex.y, 32, 32, flip_x=is_flipped)

    def get_fg_texture(self, mgr: RtTexManager) -> npt.NDArray[np.uint8]:
        return self.get_texture(mgr, self.fg_id, self.fg_tex_index)

    def get_bg_texture(self, mgr: RtTexManager) -> npt.NDArray[np.uint8]:
        return self.get_texture(mgr, self.bg_id, self.bg_tex_index)

    @property
    def front(self) -> int:
        return self.fg_id if self.fg_id > 0 else self.bg_id if self.bg_id > 0 else 0

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.Tile) -> "Tile":
        return cls(
            fg_id=proto.fg_id,
            bg_id=proto.bg_id,
            parent_index=proto.parent_index,
            lock_index=proto.lock_index,
            flags=TileFlags(proto.flags),
            extra=TileExtra.deserialize(Buffer(proto.extra), proto.fg_id, proto.bg_id) if proto.extra else None,
            _extra_raw=proto.extra,
            index=proto.index,
            pos=ivec2(proto.x, proto.y),
            json_data=cbor2.loads(proto.json_data),
        )

    def to_proto(self) -> growtopia_pb2.Tile:
        return growtopia_pb2.Tile(
            fg_id=self.fg_id,
            bg_id=self.bg_id,
            parent_index=self.parent_index,
            lock_index=self.lock_index,
            flags=TileFlags(self.flags),
            extra=self._extra_raw,
            index=self.index,
            x=self.pos.x,
            y=self.pos.y,
            json_data=cbor2.dumps(self.json_data),
        )

    @classmethod
    def deserialize(cls, s: Buffer, format_version: int = 999999999999) -> "Tile":
        tile = cls()
        tile.fg_id = s.read_u16()
        tile.bg_id = s.read_u16()
        tile.parent_index = s.read_u16()
        tile.flags = TileFlags(s.read_u16())

        if tile.flags & TileFlags.LOCKED:
            tile.lock_index = s.read_u16()

        if tile.flags & TileFlags.HAS_EXTRA_DATA:
            start = s.rpos
            tile.extra = TileExtra.deserialize(s, tile.fg_id, tile.bg_id, format_version)
            extra_size = s.rpos - start

            s.rpos = start
            tile._extra_raw = s.read_bytes(extra_size)

        cbor_ids = [
            PARTY_PROJECTOR,
            AUCTION_BLOCK,
            BATTLE_PET_CAGE,
            OFFERING_TABLE,
            OPERATING_TABLE,
            AUTO_SURGEON_STATION,
            BOUNTIFUL_FLOWERING_LATTICE_ROOTS,
            BOUNTIFUL_CLIMBING_HYDRANGEA_LATTICE_ROOTS,
            BOUNTIFUL_FLOWERING_GARLAND_ROOTS,
            BOUNTIFUL_LATTICE_FENCE_ROOTS,
            BOUNTIFUL_JUNGLE_TEMPLE_ROOTS,
            BOUNTIFUL_JUNGLE_TEMPLE_BACKGROUND_ROOTS,
            BOUNTIFUL_JUNGLE_TEMPLE_DOOR_ROOTS,
            BOUNTIFUL_JUNGLE_TEMPLE_PILLAR_ROOTS,
            BOUNTIFUL_BAMBOO_BACKGROUND_ROOTS,
            BOUNTIFUL_BAMBOO_PLATFORM_ROOTS,
            BOUNTIFUL_BAMBOO_LADDER_ROOTS,
            BOUNTIFUL_BAMBOO_SPIKES_ROOTS,
            BOUNTIFUL_WHITE_DOLL_S_EYES_ROOTS,
            BOUNTIFUL_MONKSHOOD_ROOTS,
            BOUNTIFUL_CORPSE_FLOWER_ROOTS,
            BOUNTIFUL_GROWTOPIAN_EATING_LOOMING_PLANT_ROOTS,
        ]

        if tile.front in cbor_ids:
            tile.json_data = cbor2.loads(s.read_pascal_bytes("I"))

        return tile


@dataclass(slots=True)
class DroppedItem:
    id: int = 0
    pos: vec2 = field(default_factory=vec2)
    amount: int = 0
    flags: int = 0
    uid: int = 0

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.DroppedItem) -> "DroppedItem":
        return DroppedItem(
            id=proto.id,
            pos=vec2(proto.x, proto.y),
            amount=proto.amount,
            flags=proto.flags,
            uid=proto.uid,
        )

    def to_proto(self) -> growtopia_pb2.DroppedItem:
        return growtopia_pb2.DroppedItem(
            id=self.id,
            x=self.pos.x,
            y=self.pos.y,
            amount=self.amount,
            flags=self.flags,
            uid=self.uid,
        )


@dataclass(slots=True)
class Dropped:
    nb_items: int = 0
    last_uid: int = 0
    items: list[DroppedItem] = field(default_factory=list)

    def get_total(self, id: int) -> int:
        total = 0
        for item in self.items:
            if item.id == id:
                total += item.amount

        return total

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.Dropped) -> "Dropped":
        return cls(
            nb_items=proto.nb_items,
            last_uid=proto.last_uid,
            items=list(map(lambda x: DroppedItem.from_proto(x), proto.items)),
        )

    def to_proto(self) -> growtopia_pb2.Dropped:
        return growtopia_pb2.Dropped(
            nb_items=self.nb_items,
            last_uid=self.last_uid,
            items=list(map(lambda x: x.to_proto(), self.items)),
        )


@dataclass(slots=True)
class World:
    id: int = 0  # u32, from int_x in tank packet
    version: int = 0  # u32
    unk1: int = 0  # u16
    name: bytes = b""
    width: int = 0  # u32
    height: int = 0  # u32
    nb_tiles: int = 0  # u32
    unk2: bytes = b"\x00" * 5
    tiles: list[Tile] = field(default_factory=list, repr=False)
    unk4: bytes = b"\x00" * 12
    dropped: Dropped = field(default_factory=Dropped, repr=False)
    unk5: int = 0  # u16
    unk6: int = 0  # u16
    unk7: int = 0  # u16
    unk8: int = 0  # u16
    unk9: int = 0  # u32

    # state (not in data)
    player: list[Player] = field(default_factory=list)
    garbage_start: int = -1
    logger = logging.getLogger("world")

    def get_player(self, net_id: int) -> Player | None:
        for p in self.player:
            if p.net_id == net_id:
                return p
        self.logger.warning(f"player with net_id={net_id} does not exists in world {self.name}")

    def add_player(self, player: Player) -> None:
        self.player.append(player)

    def remove_player(self, player: Player) -> None:
        self.player.remove(player)

    def remove_player_by_id(self, net_id: int) -> None:
        self.player = [p for p in self.player if p.net_id != net_id]

    def fix(self) -> None:
        """adjust width, height, nb_tiles based on the tiles list. also fills in any gap, and sort it"""
        xs = [t.pos.x for t in self.tiles]
        ys = [t.pos.y for t in self.tiles]
        self.width = max(xs) + 1
        self.height = max(ys) + 1

        for y in range(self.height):
            for x in range(self.width):
                pos = ivec2(x, y)
                if not self.tile_exists(pos):
                    self.tiles.append(Tile(pos=pos))

        self.nb_tiles = len(self.tiles)
        self.tiles.sort(key=lambda tile: (tile.pos.y, tile.pos.x))

    def tile_exists(self, pos: ivec2) -> bool:
        for tile in self.tiles:
            if tile.pos == pos:
                return True

        return False

    def get_tile(self, pos: ivec2 | int) -> Tile | None:
        if isinstance(pos, int):
            pos = ivec2(pos % self.width, pos // self.width)
        for tile in self.tiles:
            if tile.pos == pos:
                return tile

        self.logger.warning(f"tile {pos} in {self.name} does not exists")
        # raise IndexError(f"tile {pos} in {self.name} does not exists")

    def index_tile(self, pos: ivec2) -> int | None:
        for i, tile in enumerate(self.tiles):
            if tile.pos == pos:
                return i

        self.logger.warning(f"tile {pos} in {self.name} does not exists")

    def destroy_tile(self, pos: ivec2) -> None:
        if (tile := self.get_tile(pos)) is None:
            return

        if tile.fg_id != 0:
            tile.fg_id = 0
        else:
            tile.bg_id = 0

    def place_tile(self, id: int, pos: ivec2) -> None:
        if (tile := self.get_tile(pos)) is None:
            return

        if item_database.is_background(id):
            tile.bg_id = id
        else:
            tile.fg_id = id
            if id % 2 != 0:
                tile.extra = SeedTile()

    def replace_whole_tile(self, tile: Tile) -> None:
        if idx := self.index_tile(tile.pos):
            self.tiles[idx] = tile

    def replace_fg(self, tile: Tile, fg: int, tex_index: int = 0, a5: bool = False) -> None:
        item = item_database.get(fg)
        if item:
            if tile.extra:
                if tile.extra.type == TileExtraType.LOCK_TILE and tile.fg_id != fg:
                    self.remove_locked(tile)
                tile.extra = None
            tile.fg_id = fg
            tile.fg_tex_index = tex_index

            if tile.fg_id == 0:
                tile.flags &= ~(TileFlags.WAS_SPLICED | TileFlags.IS_ON | TileFlags.IS_OPEN_TO_PUBLIC | TileFlags.FG_ALT_MODE)

            if item.item_type in (ItemInfoType.DOOR, ItemInfoType.LOCK):
                tile.flags &= ~(TileFlags.PAINTED_RED | TileFlags.PAINTED_GREEN | TileFlags.PAINTED_BLUE)

            if not a5:
                tile.flags &= ~TileFlags.HAS_EXTRA_DATA

            match item.item_type:
                case (
                    ItemInfoType.USER_DOOR
                    | ItemInfoType.LOCK
                    | ItemInfoType.SIGN
                    | ItemInfoType.DOOR
                    | ItemInfoType.SEED
                    | ItemInfoType.PORTAL
                    | ItemInfoType.MAILBOX
                    | ItemInfoType.BULLETIN
                    | ItemInfoType.DICE
                    | ItemInfoType.PROVIDER
                    | ItemInfoType.ACHIEVEMENT
                    | ItemInfoType.SUNGATE
                    | ItemInfoType.HEART_MONITOR
                    | ItemInfoType.DONATION_BOX
                    | ItemInfoType.TOYBOX
                    | ItemInfoType.MANNEQUIN
                    | ItemInfoType.CAMERA
                    | ItemInfoType.MAGICEGG
                    | ItemInfoType.TEAM
                    | ItemInfoType.GAME_GEN
                    | ItemInfoType.XENONITE
                    | ItemInfoType.DRESSUP
                    | ItemInfoType.CRYSTAL
                    | ItemInfoType.BURGLAR
                    | ItemInfoType.SPOTLIGHT
                    | ItemInfoType.DISPLAY_BLOCK
                    | ItemInfoType.VENDING
                    | ItemInfoType.FISHTANK
                    | ItemInfoType.SOLAR
                    | ItemInfoType.FORGE
                    | ItemInfoType.GIVING_TREE
                    | ItemInfoType.GIVING_TREE_STUMP
                    | ItemInfoType.STEAM_ORGAN
                    | ItemInfoType.TAMAGOTCHI
                    | ItemInfoType.SEWING
                    | ItemInfoType.FLAG
                    | ItemInfoType.LOBSTER_TRAP
                    | ItemInfoType.ARTCANVAS
                    | ItemInfoType.BATTLE_CAGE
                    | ItemInfoType.PET_TRAINER
                    | ItemInfoType.STEAM_ENGINE
                    | ItemInfoType.LOCK_BOT
                    | ItemInfoType.WEATHER_SPECIAL
                    | ItemInfoType.SPIRIT_STORAGE
                    | ItemInfoType.DISPLAY_SHELF
                    | ItemInfoType.VIP_DOOR
                    | ItemInfoType.CHAL_TIMER
                    | ItemInfoType.CHAL_FLAG
                    | ItemInfoType.FISH_MOUNT
                    | ItemInfoType.PORTRAIT
                    | ItemInfoType.WEATHER_SPECIAL2
                    | ItemInfoType.FOSSIL_PREP
                    | ItemInfoType.DNA_MACHINE
                    | ItemInfoType.BLASTER
                    | ItemInfoType.CHEMTANK
                    | ItemInfoType.STORAGE
                    | ItemInfoType.OVEN
                    | ItemInfoType.SUPER_MUSIC
                    | ItemInfoType.GEIGERCHARGE
                    | ItemInfoType.ADVENTURE_RESET
                    | ItemInfoType.TOMB_ROBBER
                    | ItemInfoType.FACTION
                    | ItemInfoType.RED_FACTION
                    | ItemInfoType.GREEN_FACTION
                    | ItemInfoType.BLUE_FACTION
                    | ItemInfoType.FISHGOTCHI_TANK
                    | ItemInfoType.ITEM_SUCKER
                    | ItemInfoType.ROBOT
                    | ItemInfoType.LUCKY_TICKET
                    | ItemInfoType.STATS_BLOCK
                    | ItemInfoType.FIELD_NODE
                    | ItemInfoType.OUIJA_BOARD
                    | ItemInfoType.AUTO_ACTION_BREAK
                    | ItemInfoType.AUTO_ACTION_HARVEST
                    | ItemInfoType.AUTO_ACTION_HARVEST_SUCK
                    | ItemInfoType.LIGHTNING_CLOUD
                    | ItemInfoType.PHASED_BLOCK
                    | ItemInfoType.PASSWORD_STORAGE
                    | ItemInfoType.PHASED_BLOCK2
                    | ItemInfoType.PVE_NPC
                    | ItemInfoType.INFINITY_WEATHER_MACHINE
                    | ItemInfoType.COMPLETIONIST
                    | ItemInfoType.FEEDING_BLOCK
                    | ItemInfoType.KRANKENS_BLOCK
                    | ItemInfoType.FRIENDS_ENTRANCE
                ):
                    tile.extra = TileExtra.new(TileExtraType.from_item_type(item.item_type))
                    # set some default value
                    if item.id == WEATHER_MACHINE_BACKGROUND:
                        tile.extra.expect(WeatherMachineTile).item_id = 0
                    if item.id == EPOCH_MACHINE:
                        e = tile.extra.expect(GuildWeatherMachineTile)
                        e.flags |= 0b11100
                        e.cycle_time_ms = 600
                    if item.id == INFINITY_WEATHER_MACHINE:
                        e = tile.extra.expect(InfinityWeatherMachineTile)
                        e.cycle_time_ms = 600
                    if item.item_type == ItemInfoType.KRANKENS_BLOCK and not a5:
                        new_tile_id = KRANKEN_S_GALACTIC_BLOCK + 2 * tile.extra.expect(KrankenGalaticBlockTile).pattern_index
                        if new_tile_id - KRANKEN_S_GALACTIC_BLOCK <= 24:
                            tile.fg_id = new_tile_id
                    # if item.item_type == ItemInfoType.PVE_NPC:
                    #     # initialize all three npc with some default value, idk what is it though
                    #     pass
                case ItemInfoType.BEDROCK:
                    if item.id in (DATA_BEDROCK, DATA_STARSHIP_HULL, DATA_BEDROCK_CANDY):
                        tile.extra = TileExtra.new(TileExtraType.from_item_type(item.item_type))
                        tile.flags |= TileFlags.HAS_EXTRA_DATA

            if item.flags2 & ItemInfoFlag2.GUILD_ITEM != 0 and not tile.extra:
                tile.extra = TileExtra.new(TileExtraType.from_item_type(item.item_type))
                tile.flags |= TileFlags.HAS_EXTRA_DATA

    def update_tree(self, tile: Tile, tank: TankPacket) -> None:
        if not tile.extra or tile.extra.type != TileExtraType.SEED_TILE:
            return

        if tank.target_net_id == -1:
            tile.flags &= ~(TileFlags.PAINTED_RED | TileFlags.PAINTED_GREEN | TileFlags.PAINTED_BLUE)
            self.replace_fg(tile, 0)
            # TODO: update connectivity 3x3 around this
        else:
            tile.extra.expect(SeedTile).item_on_tree = tank.value
            if tank.jump_count == 1:
                tile.flags |= TileFlags.WILL_SPAWN_SEEDS_TOO
            else:
                tile.flags &= ~TileFlags.WILL_SPAWN_SEEDS_TOO

            if tank.animation_type == 1:
                tile.flags |= TileFlags.IS_SEEDLING
            else:
                tile.flags &= ~TileFlags.IS_SEEDLING

            # TODO: set time here
            # TODO: store somewhere the seed placed time

    def remove_locked(self, locked: Tile) -> Iterator[Tile]:
        if not locked.extra or locked.extra.type != TileExtraType.LOCK_TILE:
            return

        for tile in self.tiles:
            if tile.lock_index == locked.index:
                tile.flags &= ~TileFlags.LOCKED
                tile.lock_index = 0
                yield tile

    def create_dropped(self, id: int, pos: vec2, amount: int, flags: int) -> None:
        dropped = DroppedItem(
            id=id,
            pos=pos,
            amount=amount,
            flags=flags,
            uid=self.dropped.last_uid + 1,
        )
        self.dropped.last_uid += 1
        self.dropped.items.append(dropped)
        self.dropped.nb_items += 1

    def remove_dropped(self, uid: int) -> DroppedItem | None:
        for i, item in enumerate(self.dropped.items):
            if item.uid != uid:
                continue

            self.dropped.items.pop(i)
            self.dropped.nb_items -= 1
            return item

    def set_dropped(self, uid: int, amount: int) -> None:
        for item in self.dropped.items:
            if item.uid != uid:
                continue

            item.amount = amount

    @classmethod
    def from_net(cls, tank: TankPacket | bytes) -> "World":
        if isinstance(tank, bytes):
            tank = NetPacket.deserialize(tank).tank

        return cls.deserialize(tank.extended_data, int_x_id=tank.int_x)

    @classmethod
    def from_extended(cls, extended: bytes) -> "World":
        return cls.deserialize(Buffer(extended))

    def serialize(self) -> bytes:
        # TODO:
        return b""

    @classmethod
    def deserialize(cls, s: bytes | Buffer, int_x_id: int = 0) -> "World":
        # we delegate passing the id to the caller because we don't have the tank packet here
        s = Buffer(s)

        world = cls()

        world.id = int_x_id
        world.version = s.read_u16()
        world.unk1 = s.read_u32()
        world.name = s.read_pascal_bytes("H")
        world.width = s.read_u32()
        world.height = s.read_u32()
        world.nb_tiles = s.read_u32()

        world.unk2 = s.read_bytes(5)

        failed = False
        for p in range(world.nb_tiles):
            try:
                tile = Tile.deserialize(s, world.version)
            except Exception as e:
                cls.logger.error(f"failed parsing world at offset={s.rpos}, peek={s.peek(100)}. err={e}")
                if not failed:
                    world.garbage_start = p
                failed = True
                # we keep going even though it will yield garbage, we can try to recover, but it can skip multiple tile which will cause weird offset
                # we can try to sync using bedrock, but its too unreliable

            tile.index = p
            tile.pos = ivec2(p % world.width, p // world.width)
            world.tiles.append(tile)

        if failed:
            # if we fail, then we cannot parse dropped item, but we can take advantage of the fact that it always placed at the end
            # meaning we can parse it reversed from the end until it failed or found some impossible value
            with s.reversed(keep=False):
                world.unk9 = s.read_u32()
                world.unk8 = s.read_u16()
                world.unk7 = s.read_u16()
                world.unk6 = s.read_u16()
                world.unk5 = s.read_u16()

                while True:
                    item = DroppedItem()
                    item.uid = s.read_u32()
                    item.flags = s.read_u8()
                    item.amount = s.read_u8()
                    item.pos = vec2(s.read_f32(), s.read_f32())
                    item.id = s.read_u16()

                    if item.id not in item_database.items():
                        break

                    # i don't know any item that can go past 200
                    if item.amount > 200:
                        break

                    # check for out of bound position
                    margin = 32  # a tile margin
                    if not (-margin < item.pos.x < world.width * 32 + margin) or not (-margin < item.pos.y < world.height * 32 + margin):
                        break

                    world.dropped.items.append(item)
                    world.dropped.nb_items += 1

                    with s.temp():
                        maybe_last_uid = s.read_u32()
                        maybe_nb_items = s.read_u32()
                        if maybe_nb_items == world.dropped.nb_items or item.uid == 1:
                            world.dropped.last_uid = maybe_last_uid
                            break

                world.unk4 = s.read_bytes(12)
            world.dropped.items.reverse()

            return world

        world.unk4 = s.read_bytes(12)
        world.dropped.nb_items = s.read_u32()
        world.dropped.last_uid = s.read_u32()
        for _ in range(world.dropped.nb_items):
            item = DroppedItem()
            item.id = s.read_u16()
            item.pos = vec2(s.read_f32(), s.read_f32())
            item.amount = s.read_u8()
            item.flags = s.read_u8()
            item.uid = s.read_u32()

            world.dropped.items.append(item)

        world.unk5 = s.read_u16()
        world.unk6 = s.read_u16()
        world.unk7 = s.read_u16()
        world.unk8 = s.read_u16()
        world.unk9 = s.read_u32()

        return world

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.World) -> "World":
        return cls(
            name=proto.inner.name,
            width=proto.inner.width,
            height=proto.inner.height,
            nb_tiles=proto.inner.nb_tiles,
            tiles=list(map(lambda x: Tile.from_proto(x), proto.inner.tiles)),
            dropped=Dropped.from_proto(proto.inner.dropped),
            garbage_start=proto.inner.garbage_start,
            player=[Player.from_proto(x) for x in proto.player],
        )

    def to_proto(self) -> growtopia_pb2.World:
        return growtopia_pb2.World(
            inner=growtopia_pb2.WorldInner(
                name=self.name,
                width=self.width,
                height=self.height,
                nb_tiles=self.nb_tiles,
                tiles=list(map(lambda x: x.to_proto(), self.tiles)),
                dropped=self.dropped.to_proto(),
                garbage_start=self.garbage_start,
            ),
            player=[x.to_proto() for x in self.player],
        )
