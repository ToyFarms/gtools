from abc import abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum, IntFlag, IntEnum, auto
import logging
from pathlib import Path
from typing import Any, Callable, Iterator, Literal, Type, overload

from pyglm import glm
from pyglm.glm import ivec2, vec2
from gtools.baked.items import (
    ANCIENT_BLOCK,
    ANGRY_ADVENTURE_GORILLA,
    AQUA_CAVE_CRYSTAL_SEED,
    AUCTION_BLOCK,
    AUTO_SURGEON_STATION,
    BATTLE_PET_CAGE,
    BEDROCK,
    BEDROCK_CANDY,
    BIG_LOCK,
    BLANK,
    BONE_CHECKPOINT,
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
    BUILDER_S_LOCK,
    CAVE_COLUMN,
    CAVE_DIRT,
    CAVE_PLATFORM,
    CLIMBING_BOOTS_SEED,
    CLIMBING_WALL,
    DARK_CAVE_BACKGROUND,
    DATA_BEDROCK,
    DATA_BEDROCK_CANDY,
    DATA_STARSHIP_HULL,
    DECORATIVE_ROOF_DRAGON,
    DIAMOND_REGAL_BANNISTER,
    DIAMOND_REGAL_STAIRS,
    DIRT,
    DWARVEN_BACKGROUND,
    EPOCH_MACHINE,
    FISSURE,
    GOLEM_S_GIFT,
    GREAT_TURRET_OF_GROWTOPIA,
    GREAT_WALL_OF_GROWTOPIA,
    GROWMOJI_TURKEY_SEED,
    GUILD_FLAG_POLE_SPEAR,
    GUILD_FLAG_POLE_WINGS,
    GUILD_FLAG_SHIELD_OPEN_DIVISION_CLOSE_SEED,
    GUILD_FLAG_TATTERS,
    GUILD_LOCK,
    HAUNTED_HOUSE,
    HUGE_LOCK,
    INFINITY_CROWN,
    INFINITY_WEATHER_MACHINE,
    KRANKEN_S_GALACTIC_BLOCK,
    LOVEWILLOW,
    MAGIC_INFUSED_STONE,
    MAGIC_INFUSED_STONE_BACKGROUND_SEED,
    MAGIC_INFUSED_VEIN,
    MAGIC_INFUSED_VEIN_SEED,
    MANOR_HOUSE_SANDSTONE,
    MANOR_HOUSE_SANDSTONE_STEPS,
    MASTER_PENG_STONEWORK,
    MONOCHROMATIC_BEDROCK,
    MYSTERY_DOOR,
    OPERATING_TABLE,
    PARTY_PROJECTOR,
    PURE_MAGIC_ORE,
    PURPLE_CAVE_CRYSTAL,
    REGAL_BANNISTER,
    REGAL_STAIRS,
    SMALL_LOCK,
    STALACTITE,
    STALAGMITE,
    STEAM_LAUNCHER,
    STEAM_PIPE,
    STONE_PAGODA,
    STONE_PAGODA_BASE,
    STONE_PAGODA_ROOF_ELEMENT_SEED,
    TRANSDIMENSIONAL_VAPORIZER_RAY,
    TWISTED_ROOF,
    TWISTED_WINDOWS,
    WEATHER_MACHINE_BACKGROUND,
    WEEPING_WILLOW,
    WEEPING_WILLOW_BRANCH,
    WEEPING_WILLOW_FOLIAGE,
    WELL_OF_LOVE,
    WILL_OF_THE_WILD,
    WINTERFEST_CALENDAR_2017,
)
from gtools.core.buffer import Buffer
import cbor2

from gtools.core.color import color_matrix_filter
from gtools.core.growtopia.inventory import Inventory
from gtools.core.growtopia.items_dat import (
    ItemFlag,
    ItemInfoCollisionType,
    ItemInfoFlag2,
    ItemInfoTextureType,
    ItemInfoType,
    TerraformType,
    WeatherType,
    item_database,
)
from gtools.core.growtopia.note import ACCIDENT_MAP, CODE_TO_INSTRUMENT_SET, CODE_TO_PITCH_MAP, ID_TO_INSTRUMENT_SET, SHEET_FLAT_ID, SHEET_SHARP_ID, Y_TO_PITCH_MAP, Note, Sheet
from gtools.core.growtopia.packet import NetPacket, TankFlags, TankPacket
from gtools.core.growtopia.player import Player
from gtools.core.growtopia.rttex import RTTexManager
from gtools.core.mixer import AudioMixer
from gtools.protogen import growtopia_pb2
import numpy as np
import numpy.typing as npt

from gtools import setting

# shoutout https://github.com/CLOEI/gtworld-r/tree/284a2bb9f501e740401c4f0aa025d11adbed2b02
# and https://github.com/badewen/Growtopia-Things/tree/187a6b312b5e0acec24ccf6749bda113a0279e02
# for most of these tile


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

    def serialize_into(self, s: Buffer) -> None:
        color = ((self.a & 0xFF) << 24) | ((self.r & 0xFF) << 16) | ((self.g & 0xFF) << 8) | ((self.b & 0xFF) << 0)
        s.write_bytes(color.to_bytes(4))


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

    def serialize_into(self, s: Buffer) -> None:
        s.write_u32(self.fish_item_id)
        s.write_u32(self.lbs)


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

    def serialize_into(self, s: Buffer) -> None:
        s.write_bytes(self.unk1)
        s.write_u32(self.id)
        s.write_u16(self.unk2)
        s.write_u32(self.amount)


# TODO: figure out why some item_id have abnormally high value
@dataclass(slots=True)
class CookingOvenIngredientInfo:
    item_id: int = 0  # u16
    amount: int = 0  # u16

    @classmethod
    def deserialize(cls, s: Buffer) -> "CookingOvenIngredientInfo":
        t = CookingOvenIngredientInfo()
        t.item_id = s.read_u16()
        t.amount = s.read_u16()

        return t

    def serialize_into(self, s: Buffer) -> None:
        s.write_u16(self.item_id)
        s.write_u16(self.amount)


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

    def serialize_into(self, s: Buffer) -> None:
        s.write_u32(self.command_id)
        s.write_u32(self.is_command_used)
        s.write_bytes(self.unk1)


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

    def serialize_into(self, s: Buffer, _fg_id: int, _bg_id: int, format_version: int) -> None:
        s.write_u32(self.unk1)
        s.write_u32(self.unk2)
        s.write_u32(self.unk3)
        s.write_u32(self.unk4)
        s.write_u32(self.unk5)
        s.write_u32(self.unk6)

        if format_version > 10:
            s.write_u64(self.unk7)
        if format_version > 14:
            s.write_u32(self.unk8)


class TileExtraType(IntEnum):
    NONE = 0x0
    DOOR_TILE = 0x1
    SIGN_TILE = 0x2
    LOCK_TILE = 0x3
    SEED_TILE = 0x4
    UNK_SCROLL_BULETTIN = 0x5
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


CBOR_IDs = [
    PARTY_PROJECTOR,
    AUCTION_BLOCK,
    BATTLE_PET_CAGE,
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


@dataclass(slots=True)
class TileExtra:
    type: TileExtraType = TileExtraType.NONE
    data: "GuildItemTile | StarshipHullData | None" = None

    @classmethod
    def deserialize_extra(cls, s: Buffer, fg: int = -1, bg: int = -1, format_version: int = 999999999) -> "TileExtra":
        type = s.read_u8()
        handler = _TILE_EXTRA_REGISTRY.get(type)
        if not handler:
            raise NotImplementedError(f"no tile extra for id {type}, {fg=}, {bg=}")

        extra = handler.int__deserialize(s, fg, bg, format_version)
        extra.type = TileExtraType(type)

        item = item_database.get(fg or bg)
        if item.id == DATA_STARSHIP_HULL and format_version > 4:
            extra.data = StarshipHullData.deserialize(s, format_version)

        # NOTE: we need to check if we are not already a GUILD_ITEM_TILE extra, as to not parse it 2x
        if type != TileExtraType.GUILD_ITEM_TILE:
            if item.flags2 & ItemInfoFlag2.GUILD_ITEM != 0:
                extra.data = GuildItemTile.int__deserialize(s, fg, bg, format_version)

        # TODO: there is a special tile extra such as data starship, bedrock data, guild data
        # these are handled specially, and are executed for all tile extra, because the tile can have
        # multiple extra data, such as guild lock, which contains LockTile and GuildItemData
        # verify it, if i have the sample

        return extra

    def serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int = 999999999) -> None:
        s.write_u8(self.type.value)
        self.int__serialize_into(s, fg_id, bg_id, format_version)
        if self.data:
            self.data.serialize_into(s, fg_id, bg_id, format_version)

    def serialize(self, fg_id: int, bg_id: int, format_version: int = 999999999) -> bytes:
        s = Buffer()
        self.serialize_into(s, fg_id, bg_id, format_version)
        return s.getvalue()

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

    @classmethod
    @abstractmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "TileExtra": ...
    @abstractmethod
    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None: ...


# i hate this, should've just be one big switch statement, but python being python doesn't have efficient big branch optimization
# another thing is duplicate logic for serialize/deserialize, ideally it would just be one schema used for both, but whatever it rarely changes anyway


@dataclass(slots=True)
class DoorTile(TileExtra):
    text: bytes = b""
    unk1: int = 0  # u8

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "DoorTile":
        t = cls()
        t.text = s.read_pascal_bytes("H")
        t.unk1 = s.read_u8()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_pascal_bytes("H", self.text)
        s.write_u8(self.unk1)


@dataclass(slots=True)
class SignTile(TileExtra):
    text: bytes = b""
    unk1: int = 0  # i32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SignTile":
        t = cls()
        t.text = s.read_pascal_bytes("H")
        t.unk1 = s.read_i32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_pascal_bytes("H", self.text)
        s.write_i32(self.unk1)


@dataclass(slots=True)
class LockTile(TileExtra):
    flags: int = 0  # u8
    owner_uid: int = 0  # u32
    access_count: int = 0  # u32
    access_uids: list[int] = field(default_factory=list)  # Vec<i32>
    minimum_level: int = 0  # u32
    unk1: int = 0  # u32

    bpm: int = 100

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "LockTile":
        t = cls()
        t.flags = s.read_u8()
        t.owner_uid = s.read_u32()
        t.access_count = s.read_u32()
        for i in range(t.access_count):
            v = s.read_i32()

            if v < 0:
                t.bpm = abs(v)

            t.access_uids.append(v)

        if format_version >= 12:
            t.minimum_level = s.read_u32()
        if format_version >= 13:
            t.unk1 = s.read_u32()

        return t

    def set_bpm(self, bpm: int) -> None:
        set = False
        for i in range(self.access_count):
            if self.access_uids[i] < 0:
                self.access_uids[i] = bpm
                self.bpm = bpm
                set = True
                break

        if not set:
            self.access_uids.append(-bpm)
            self.bpm = bpm

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u8(self.flags)
        s.write_u32(self.owner_uid)
        s.write_u32(self.access_count)

        for i, uid in enumerate(self.access_uids):
            s.write_i32(uid)

        if format_version >= 12:
            s.write_u32(self.minimum_level)
        if format_version >= 13:
            s.write_u32(self.unk1)


@dataclass(slots=True)
class SeedTile(TileExtra):
    time_passed: int = 0  # u32
    item_on_tree: int = 0  # u8

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SeedTile":
        t = cls()
        t.time_passed = s.read_u32()
        t.item_on_tree = s.read_u8()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.time_passed)
        s.write_u8(self.item_on_tree)


# id 5, never seen it, no mention in the source (world: START)
@dataclass(slots=True)
class ScrollBulletinTile(TileExtra):

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ScrollBulletinTile":
        t = cls()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        pass


@dataclass(slots=True)
class MailboxTile(TileExtra):
    unk1: bytes = b""
    unk2: bytes = b""
    unk3: bytes = b""
    unk4: int = 0  # u8

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "MailboxTile":
        t = cls()
        t.unk1 = s.read_pascal_bytes("H")
        t.unk2 = s.read_pascal_bytes("H")
        t.unk3 = s.read_pascal_bytes("H")
        t.unk4 = s.read_u8()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_pascal_bytes("H", self.unk1)
        s.write_pascal_bytes("H", self.unk2)
        s.write_pascal_bytes("H", self.unk3)
        s.write_u8(self.unk4)


@dataclass(slots=True)
class BulletinTile(TileExtra):
    unk1: bytes = b""
    unk2: bytes = b""
    unk3: bytes = b""
    unk4: int = 0  # u8

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "BulletinTile":
        t = cls()
        t.unk1 = s.read_pascal_bytes("H")
        t.unk2 = s.read_pascal_bytes("H")
        t.unk3 = s.read_pascal_bytes("H")
        t.unk4 = s.read_u8()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_pascal_bytes("H", self.unk1)
        s.write_pascal_bytes("H", self.unk2)
        s.write_pascal_bytes("H", self.unk3)
        s.write_u8(self.unk4)


@dataclass(slots=True)
class DiceTile(TileExtra):
    symbol: int = 0  # u8

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "DiceTile":
        t = cls()
        t.symbol = s.read_u8()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u8(self.symbol)


@dataclass(slots=True)
class ProviderTile(TileExtra):
    time_passed: int = 0  # u32
    time_ms: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ProviderTile":
        t = cls()
        t.time_passed = s.read_u32()

        if (fg_id == WELL_OF_LOVE and format_version > 16) or fg_id == WINTERFEST_CALENDAR_2017:
            t.time_ms = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.time_passed)
        if (fg_id == WELL_OF_LOVE and format_version > 16) or fg_id == WINTERFEST_CALENDAR_2017:
            s.write_u32(self.time_ms)


@dataclass(slots=True)
class AchievementBlockTile(TileExtra):
    unk1: int = 0  # u32
    tile_type: int = 0  # u8

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "AchievementBlockTile":
        t = cls()
        t.unk1 = s.read_u32()
        t.tile_type = s.read_u8()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.unk1)
        s.write_u8(self.tile_type)


@dataclass(slots=True)
class HeartMonitorTile(TileExtra):
    unk1: int = 0  # u32
    player_name: bytes = b""

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "HeartMonitorTile":
        t = cls()
        t.unk1 = s.read_u32()
        t.player_name = s.read_pascal_bytes("H")

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.unk1)
        s.write_pascal_bytes("H", self.player_name)


@dataclass(slots=True)
class DonationBoxTile(TileExtra):
    unk1: bytes = b""
    unk2: bytes = b""
    unk3: bytes = b""
    unk4: int = 0  # u8

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "DonationBoxTile":
        t = cls()
        t.unk1 = s.read_pascal_bytes("H")
        t.unk2 = s.read_pascal_bytes("H")
        t.unk3 = s.read_pascal_bytes("H")
        t.unk4 = s.read_u8()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_pascal_bytes("H", self.unk1)
        s.write_pascal_bytes("H", self.unk2)
        s.write_pascal_bytes("H", self.unk3)
        s.write_u8(self.unk4)


@dataclass(slots=True)
class StuffForToysTile(TileExtra):
    unk1: bytes = b""
    unk2: bytes = b""
    unk3: bytes = b""
    unk4: int = 0  # u8

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "StuffForToysTile":
        t = cls()
        t.unk1 = s.read_pascal_bytes("H")
        t.unk2 = s.read_pascal_bytes("H")
        t.unk3 = s.read_pascal_bytes("H")
        t.unk4 = s.read_u8()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_pascal_bytes("H", self.unk1)
        s.write_pascal_bytes("H", self.unk2)
        s.write_pascal_bytes("H", self.unk3)
        s.write_u8(self.unk4)


@dataclass(slots=True)
class MannequinTile(TileExtra):
    text: bytes = b""
    unk1: int = 0  # u8
    unk2: int = 0  # u32
    hair: int = 0  # u16
    shirt: int = 0  # u16
    pants: int = 0  # u16
    shoes: int = 0  # u16
    face: int = 0  # u16
    hand: int = 0  # u16
    back: int = 0  # u16
    hat: int = 0  # u16
    neck: int = 0  # u16

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "MannequinTile":
        t = cls()
        t.text = s.read_pascal_bytes("H")
        t.unk1 = s.read_u8()
        t.unk2 = s.read_u32()
        t.hair = s.read_u16()
        t.shirt = s.read_u16()
        t.pants = s.read_u16()
        t.shoes = s.read_u16()
        t.face = s.read_u16()
        t.hand = s.read_u16()
        t.back = s.read_u16()
        t.hat = s.read_u16()
        t.neck = s.read_u16()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_pascal_bytes("H", self.text)
        s.write_u8(self.unk1)
        s.write_u32(self.unk2)
        s.write_u16(self.hair)
        s.write_u16(self.shirt)
        s.write_u16(self.pants)
        s.write_u16(self.shoes)
        s.write_u16(self.face)
        s.write_u16(self.hand)
        s.write_u16(self.back)
        s.write_u16(self.hat)
        s.write_u16(self.neck)


@dataclass(slots=True)
class BunnyEggTile(TileExtra):
    eggs_placed: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "BunnyEggTile":
        t = cls()
        t.eggs_placed = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.eggs_placed)


@dataclass(slots=True)
class TeamTile(TileExtra):
    team: int = 0  # u8

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "TeamTile":
        t = cls()
        t.team = s.read_u8()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u8(self.team)


@dataclass(slots=True)
class GameGeneratorTile(TileExtra):
    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GameGeneratorTile":
        t = cls()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        pass


@dataclass(slots=True)
class XenoniteCrystalTile(TileExtra):
    unk1: int = 0  # u8
    unk2: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "XenoniteCrystalTile":
        t = cls()
        t.unk1 = s.read_u8()
        t.unk2 = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u8(self.unk1)
        s.write_u32(self.unk2)


@dataclass(slots=True)
class PhoneBoothTile(TileExtra):
    hair: int = 0  # u16
    shirt: int = 0  # u16
    pants: int = 0  # u16
    shoes: int = 0  # u16
    face: int = 0  # u16
    hand: int = 0  # u16
    back: int = 0  # u16
    hat: int = 0  # u16
    neck: int = 0  # u16

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PhoneBoothTile":
        t = cls()
        t.hair = s.read_u16()
        t.shirt = s.read_u16()
        t.pants = s.read_u16()
        t.shoes = s.read_u16()
        t.face = s.read_u16()
        t.hand = s.read_u16()
        t.back = s.read_u16()
        t.hat = s.read_u16()
        t.neck = s.read_u16()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u16(self.hair)
        s.write_u16(self.shirt)
        s.write_u16(self.pants)
        s.write_u16(self.shoes)
        s.write_u16(self.face)
        s.write_u16(self.hand)
        s.write_u16(self.back)
        s.write_u16(self.hat)
        s.write_u16(self.neck)


@dataclass(slots=True)
class CrystalTile(TileExtra):
    unk1: bytes = b""

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "CrystalTile":
        t = cls()
        t.unk1 = s.read_pascal_bytes("H")

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_pascal_bytes("H", self.unk1)


@dataclass(slots=True)
class CrimeInProgressTile(TileExtra):
    unk1: bytes = b""
    unk2: int = 0  # u32
    unk3: int = 0  # u8

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "CrimeInProgressTile":
        t = CrimeInProgressTile()
        t.unk1 = s.read_pascal_bytes("H")
        t.unk2 = s.read_u32()
        t.unk3 = s.read_u8()
        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_pascal_bytes("H", self.unk1)
        s.write_u32(self.unk2)
        s.write_u8(self.unk3)


@dataclass(slots=True)
class DisplayBlockTile(TileExtra):
    item_id: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "DisplayBlockTile":
        t = cls()
        t.item_id = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.item_id)


@dataclass(slots=True)
class VendingMachineTile(TileExtra):
    item_id: int = 0  # u32
    price: int = 0  # i32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "VendingMachineTile":
        t = cls()
        t.item_id = s.read_u32()
        t.price = s.read_i32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.item_id)
        s.write_i32(self.price)


@dataclass(slots=True)
class GivingTreeTile(TileExtra):
    unk1: int = 0  # u16
    unk2: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GivingTreeTile":
        t = cls()
        t.unk1 = s.read_u16()
        t.unk2 = s.read_u32()
        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u16(self.unk1)
        s.write_u32(self.unk2)


@dataclass(slots=True)
class CountryFlagTile(TileExtra):
    country: bytes = b""

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "CountryFlagTile":
        t = cls()
        t.country = s.read_pascal_bytes("H")

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_pascal_bytes("H", self.country)


@dataclass(slots=True)
class WeatherMachineTile(TileExtra):
    item_id: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "WeatherMachineTile":
        t = cls()
        t.item_id = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.item_id)


@dataclass(slots=True)
class DataBedrockTile(TileExtra):
    unk1: int = 0  # u8
    unk2: int = 0  # u32
    unk3: int = 0  # u32
    unk4: int = 0  # u32
    unk5: int = 0  # i32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "DataBedrockTile":
        t = cls()
        s.rpos += 1  # constant 0
        if format_version > 18:
            t.unk1 = s.read_u32()
            t.unk2 = s.read_u32()
            t.unk3 = s.read_u32()
        if format_version > 19:
            t.unk4 = s.read_u32()
            t.unk5 = s.read_i32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u8(0)
        if format_version > 18:
            s.write_u32(self.unk1)
            s.write_u32(self.unk2)
            s.write_u32(self.unk3)
        if format_version > 19:
            s.write_u32(self.unk4)
            s.write_i32(self.unk5)


@dataclass(slots=True)
class SpotlightTile(TileExtra):

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SpotlightTile":
        t = SpotlightTile()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        pass


@dataclass(slots=True)
class FishTankPortTile(TileExtra):
    flags: int = 0  # u8
    fishes: list[FishInfo] = field(default_factory=list)

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "FishTankPortTile":
        t = cls()
        t.flags = s.read_u8()

        for _ in range(s.read_u32() // 2):
            t.fishes.append(FishInfo.deserialize(s))

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u8(self.flags)
        s.write_u32(len(self.fishes) * 2)
        for fish in self.fishes:
            fish.serialize_into(s)


@dataclass(slots=True)
class SolarCollectorTile(TileExtra):
    unk1: int = 0  # u8
    unk2: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SolarCollectorTile":
        t = cls()
        t.unk1 = s.read_u8()
        t.unk2 = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u8(self.unk1)
        s.write_u32(self.unk2)


@dataclass(slots=True)
class ForgeTile(TileExtra):
    temperature: int = 0  # u32
    unk1: int = 0  # u8
    unk2: int = 0  # u16

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ForgeTile":
        t = cls()
        t.temperature = s.read_u8()
        t.unk1 = s.read_u8()
        t.unk2 = s.read_u16()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u8(self.temperature)
        s.write_u8(self.unk1)
        s.write_u16(self.unk2)


@dataclass(slots=True)
class SteamOrganTile(TileExtra):
    instrument_type: int = 0  # u8
    note: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SteamOrganTile":
        t = cls()
        t.instrument_type = s.read_u8()
        t.note = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u8(self.instrument_type)
        s.write_u32(self.note)


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
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SilkwormTile":
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

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u8(self.flags)
        s.write_pascal_bytes("H", self.name)
        s.write_u32(self.age)
        s.write_u32(self.unk1)
        s.write_u32(self.unk2)
        s.write_u8(self.can_be_fed)
        s.write_u32(self.food_saturation)
        s.write_u32(self.water_saturation)
        self.color.serialize_into(s)
        s.write_u32(self.sick_duration)


@dataclass(slots=True)
class SewingMachineTile(TileExtra):
    bolt_id_list: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SewingMachineTile":
        t = cls()

        for _ in range(s.read_u32()):
            t.bolt_id_list.append(s.read_u32())

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(len(self.bolt_id_list))
        for bolt_id in self.bolt_id_list:
            s.write_u32(bolt_id)


@dataclass(slots=True)
class LobsterTrapTile(TileExtra):

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "LobsterTrapTile":
        t = LobsterTrapTile()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        pass


@dataclass(slots=True)
class PaintingEaselTile(TileExtra):
    item_id: int = 0  # u32
    label: bytes = b""

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PaintingEaselTile":
        t = cls()
        t.item_id = s.read_u32()
        t.label = s.read_pascal_bytes("H")

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.item_id)
        s.write_pascal_bytes("H", self.label)


@dataclass(slots=True)
class PetBattleCageTile(TileExtra):
    name: bytes = b""
    unk1: bytes = b""

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PetBattleCageTile":
        t = cls()
        t.name = s.read_pascal_bytes("H")
        t.unk1 = s.read_bytes(12)
        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_pascal_bytes("H", self.name)
        s.write_bytes(self.unk1)


@dataclass(slots=True)
class PetTrainerTile(TileExtra):
    name: bytes = b""
    pet_count: int = 0  # u32
    unk1: int = 0  # u32
    pets_id: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PetTrainerTile":
        t = cls()
        t.name = s.read_pascal_bytes("H")
        t.pet_count = s.read_u32()
        t.unk1 = s.read_u32()

        for _ in range(t.pet_count):
            t.pets_id.append(s.read_u32())

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_pascal_bytes("H", self.name)
        s.write_u32(self.pet_count)
        s.write_u32(self.unk1)
        for pet_id in self.pets_id:
            s.write_u32(pet_id)


@dataclass(slots=True)
class SteamEngineTile(TileExtra):
    temperature: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SteamEngineTile":
        t = cls()
        t.temperature = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.temperature)


@dataclass(slots=True)
class LockBotTile(TileExtra):
    time_passed: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "LockBotTile":
        t = cls()
        t.time_passed = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.time_passed)


@dataclass(slots=True)
class SpiritStorageUnitTile(TileExtra):
    ghost_jar_count: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SpiritStorageUnitTile":
        t = cls()
        t.ghost_jar_count = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.ghost_jar_count)


@dataclass(slots=True)
class ShelfTile(TileExtra):
    top_left_item_id: int = 0  # u32
    top_right_item_id: int = 0  # u32
    bottom_left_item_id: int = 0  # u32
    bottom_right_item_id: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ShelfTile":
        t = cls()
        t.top_left_item_id = s.read_u32()
        t.top_right_item_id = s.read_u32()
        t.bottom_left_item_id = s.read_u32()
        t.bottom_right_item_id = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.top_left_item_id)
        s.write_u32(self.top_right_item_id)
        s.write_u32(self.bottom_left_item_id)
        s.write_u32(self.bottom_right_item_id)


@dataclass(slots=True)
class VipEntranceTile(TileExtra):
    unk1: int = 0  # u8
    owner_uid: int = 0  # u32
    access_uids: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "VipEntranceTile":
        t = cls()
        t.unk1 = s.read_u8()
        t.owner_uid = s.read_u32()
        size = s.read_u32()
        for _ in range(size):
            t.access_uids.append(s.read_u32())

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u8(self.unk1)
        s.write_u32(self.owner_uid)
        s.write_u32(len(self.access_uids))
        for uid in self.access_uids:
            s.write_u32(uid)


@dataclass(slots=True)
class ChallengeTimerTile(TileExtra):

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ChallengeTimerTile":
        t = cls()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        pass


@dataclass(slots=True)
class FishWallMountTile(TileExtra):
    label: bytes = b""
    item_id: int = 0  # u32
    lb: int = 0  # u8

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "FishWallMountTile":
        t = cls()
        t.label = s.read_pascal_bytes("H")
        t.item_id = s.read_u32()
        t.lb = s.read_u8()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_pascal_bytes("H", self.label)
        s.write_u32(self.item_id)
        s.write_u8(self.lb)


@dataclass(slots=True)
class PortraitTile(TileExtra):
    label: bytes = b""
    unk1: int = 0
    unk2: int = 0
    unk3: int = 0
    unk4: int = 0
    face: int = 0
    hat: int = 0
    hair: int = 0
    unk8: int = 0
    unk9: int = 0
    unk10: int = 0
    unk11: bytes = b""

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PortraitTile":
        t = cls()

        t.label = s.read_pascal_bytes("H")
        t.unk1 = s.read_u32()
        t.unk2 = s.read_u32()
        t.unk3 = s.read_u32()
        t.unk4 = s.read_u32()

        t.face = s.read_u16()
        t.hat = s.read_u16()
        t.hair = s.read_u16()

        if format_version >= 4 and any(x in (WILL_OF_THE_WILD, GOLEM_S_GIFT) for x in (t.face, t.hat, t.hair)):
            t.unk8 = s.read_u32()
            t.unk9 = s.read_u32()

        if format_version >= 9:
            t.unk10 = s.read_u32()

        if format_version >= 23 and t.hat == INFINITY_CROWN:
            t.unk11 = s.read_pascal_bytes("H")

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_pascal_bytes("H", self.label)
        s.write_u32(self.unk1)
        s.write_u32(self.unk2)
        s.write_u32(self.unk3)
        s.write_u32(self.unk4)
        s.write_u16(self.face)
        s.write_u16(self.hat)
        s.write_u16(self.hair)
        if format_version >= 4 and any(x in (WILL_OF_THE_WILD, GOLEM_S_GIFT) for x in (self.face, self.hat, self.hair)):
            s.write_u32(self.unk8)
            s.write_u32(self.unk9)
        if format_version >= 9:
            s.write_u32(self.unk10)
        if format_version >= 23 and self.hat == INFINITY_CROWN:
            s.write_pascal_bytes("H", self.unk11)


@dataclass(slots=True)
class GuildWeatherMachineTile(TileExtra):
    cycle_time_ms: int = 0  # u32
    gravity: int = 0  # u32
    flags: int = 0  # u8

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GuildWeatherMachineTile":
        t = cls()
        t.cycle_time_ms = s.read_u32()
        t.gravity = s.read_u32()
        t.flags = s.read_u8()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.cycle_time_ms)
        s.write_u32(self.gravity)
        s.write_u8(self.flags)


@dataclass(slots=True)
class FossilPrepStationTile(TileExtra):
    unk1: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "FossilPrepStationTile":
        t = cls()
        t.unk1 = s.read_u32()
        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.unk1)


@dataclass(slots=True)
class DnaExtractorTile(TileExtra):

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "DnaExtractorTile":
        t = cls()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        pass


@dataclass(slots=True)
class BlasterTile(TileExtra):

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "BlasterTile":
        t = cls()
        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        pass


@dataclass(slots=True)
class ChemsynthTankTile(TileExtra):
    current_chem: int = 0  # u32
    target_chem: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ChemsynthTankTile":
        t = cls()
        t.current_chem = s.read_u32()
        t.target_chem = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.current_chem)
        s.write_u32(self.target_chem)


@dataclass(slots=True)
class StorageBlockTile(TileExtra):
    items: list[StorageBlockItemInfo] = field(default_factory=list)

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "StorageBlockTile":
        t = cls()
        for _ in range(s.read_u16() // 13):
            t.items.append(StorageBlockItemInfo.deserialize(s))

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u16(len(self.items) * 13)
        for item in self.items:
            item.serialize_into(s)


@dataclass(slots=True)
class CookingOvenTile(TileExtra):
    temperature_level: int = 0  # u32
    ingredients: list[CookingOvenIngredientInfo] = field(default_factory=list)
    unk1: int = 0  # u32
    unk2: int = 0  # u64

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "CookingOvenTile":
        t = cls()

        t.temperature_level = s.read_u32()
        for _ in range(s.read_u32()):
            t.ingredients.append(CookingOvenIngredientInfo.deserialize(s))

        t.unk1 = s.read_u32()

        if format_version >= 14:
            t.unk2 = s.read_u64()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.temperature_level)
        s.write_u32(len(self.ingredients))
        for ingredient in self.ingredients:
            ingredient.serialize_into(s)
        s.write_u32(self.unk1)
        if format_version >= 14:
            s.write_u64(self.unk2)


@dataclass(slots=True)
class AudioRackTile(TileExtra):
    note: bytes = b""
    volume: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "AudioRackTile":
        t = cls()
        t.note = s.read_pascal_bytes("H")
        t.volume = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_pascal_bytes("H", self.note)
        s.write_u32(self.volume)


@dataclass(slots=True)
class GeigerChargerTile(TileExtra):
    unk1: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GeigerChargerTile":
        t = cls()
        t.unk1 = s.read_u32()
        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.unk1)


@dataclass(slots=True)
class AdventureBeginsTile(TileExtra):

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "AdventureBeginsTile":
        t = cls()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        pass


@dataclass(slots=True)
class TombRobberTile(TileExtra):

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "TombRobberTile":
        t = cls()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        pass


@dataclass(slots=True)
class BalloonOMaticTile(TileExtra):
    total_rarity: int = 0  # u32
    team_type: int = 0  # u8

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "BalloonOMaticTile":
        t = BalloonOMaticTile()
        t.total_rarity = s.read_u32()
        t.team_type = s.read_u8()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.total_rarity)
        s.write_u8(self.team_type)


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
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "TrainingPortTile":
        t = TrainingPortTile()
        t.fish_lb = s.read_u32()
        t.fish_status = s.read_u16()
        t.fish_id = s.read_u32()
        t.fish_total_exp = s.read_u32()
        t.fish_level = s.read_u32()
        t.unk2 = s.read_u32()
        t.unk3 = s.read_bytes(13)

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.fish_lb)
        s.write_u16(self.fish_status)
        s.write_u32(self.fish_id)
        s.write_u32(self.fish_total_exp)
        s.write_u32(self.fish_level)
        s.write_u32(self.unk2)
        s.write_bytes(self.unk3)


@dataclass(slots=True)
class ItemSuckerTile(TileExtra):
    item_id: int = 0  # u32
    item_amount: int = 0  # u32
    flags: int = 0  # u16
    limit: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ItemSuckerTile":
        t = cls()
        t.item_id = s.read_u32()
        t.item_amount = s.read_u32()
        t.flags = s.read_u16()
        t.limit = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.item_id)
        s.write_u32(self.item_amount)
        s.write_u16(self.flags)
        s.write_u32(self.limit)


@dataclass(slots=True)
class CybotTile(TileExtra):
    commands: list[CyBotCommandData] = field(default_factory=list)
    sync_timer: int = 0  # u32
    activated: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "CybotTile":
        t = cls()

        for _ in range(s.read_u32()):
            t.commands.append(CyBotCommandData.deserialize(s))

        t.sync_timer = s.read_u32()
        t.activated = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(len(self.commands))
        for cmd in self.commands:
            cmd.serialize_into(s)
        s.write_u32(self.sync_timer)
        s.write_u32(self.activated)


@dataclass(slots=True)
class GuildItemTile(TileExtra):
    unk1: int = 0  # u8
    unk2: int = 0  # u32
    unk3: int = 0  # u32
    unk4: int = 0  # u32
    unk5: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GuildItemTile":
        t = cls()
        if fg_id != GUILD_LOCK:
            t.unk1 = s.read_u8()
        t.unk2 = s.read_u32()
        t.unk3 = s.read_u32()
        t.unk4 = s.read_u32()
        t.unk5 = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        if fg_id != GUILD_LOCK:
            s.write_u8(self.unk1)
        s.write_u32(self.unk2)
        s.write_u32(self.unk3)
        s.write_u32(self.unk4)
        s.write_u32(self.unk5)


@dataclass(slots=True)
class GrowscanTile(TileExtra):
    unk1: int = 0  # u8

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GrowscanTile":
        t = cls()
        t.unk1 = s.read_u8()
        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u8(self.unk1)


@dataclass(slots=True)
class ContainmentFieldPowerNodeTile(TileExtra):
    time_ms: int = 0  # u32
    unk1: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ContainmentFieldPowerNodeTile":
        t = cls()
        t.time_ms = s.read_u32()
        for _ in range(s.read_u32()):
            t.unk1.append(s.read_u32())
        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.time_ms)
        s.write_u32(len(self.unk1))
        for v in self.unk1:
            s.write_u32(v)


@dataclass(slots=True)
class SpiritBoardTile(TileExtra):
    unk1: int = 0  # u32
    unk2: bytes = b""
    unk3: bytes = b""
    unk4: list[int] = field(default_factory=list)

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SpiritBoardTile":
        t = cls()
        t.unk1 = s.read_u32()
        t.unk2 = s.read_pascal_bytes("H")
        t.unk3 = s.read_pascal_bytes("H")
        for _ in range(s.read_u32()):
            t.unk4.append(s.read_u32())
        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.unk1)
        s.write_pascal_bytes("H", self.unk2)
        s.write_pascal_bytes("H", self.unk3)
        s.write_u32(len(self.unk4))
        for v in self.unk4:
            s.write_u32(v)


@dataclass(slots=True)
class TesseractManipulatorTile(TileExtra):
    gems: int = 0  # u32
    next_update_ms: int = 0  # u32
    item_id: int = 0  # u32
    enabled: bool = False  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "TesseractManipulatorTile":
        t = cls()
        t.gems = s.read_u32()
        t.next_update_ms = s.read_u32()
        t.item_id = s.read_u32()
        if format_version >= 8:
            t.enabled = s.read_u32() != 0

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.gems)
        s.write_u32(self.next_update_ms)
        s.write_u32(self.item_id)
        if format_version >= 8:
            s.write_u32(1 if self.enabled else 0)


@dataclass(slots=True)
class HeartOfGaiaTile(TileExtra):
    gems: int = 0  # u32
    next_update_ms: int = 0  # u32
    item_id: int = 0  # u32
    enabled: bool = False  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "HeartOfGaiaTile":
        t = cls()
        t.gems = s.read_u32()
        t.next_update_ms = s.read_u32()
        t.item_id = s.read_u32()
        if format_version >= 8:
            t.enabled = s.read_u32() != 0

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.gems)
        s.write_u32(self.next_update_ms)
        s.write_u32(self.item_id)
        if format_version >= 8:
            s.write_u32(1 if self.enabled else 0)


@dataclass(slots=True)
class TechnoOrganicEngineTile(TileExtra):
    unk1: int = 0  # u32
    unk2: int = 0  # u32
    item_id: int = 0  # u32
    unk4: int = 0  # u32
    unk5: int = 0  # u32
    unk6: int = 0  # u32
    unk7: int = 0  # u8
    unk8: int = 0  # u8
    unk9: int = 0  # u32
    unk10: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "TechnoOrganicEngineTile":
        t = cls()
        t.unk1 = s.read_u32()
        t.unk2 = s.read_u32()
        t.item_id = s.read_u32()
        if format_version > 8:
            t.unk4 = s.read_u32()
        t.unk5 = s.read_u32()
        t.unk6 = s.read_u32()
        t.unk7 = s.read_u8()
        t.unk8 = s.read_u8()
        t.unk9 = s.read_u32()
        t.unk10 = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.unk1)
        s.write_u32(self.unk2)
        s.write_u32(self.item_id)
        if format_version > 8:
            s.write_u32(self.unk4)
        s.write_u32(self.unk5)
        s.write_u32(self.unk6)
        s.write_u8(self.unk7)
        s.write_u8(self.unk8)
        s.write_u32(self.unk9)
        s.write_u32(self.unk10)


@dataclass(slots=True)
class StormyCloudTile(TileExtra):
    sting_duration: int = 0  # u32
    is_solid: int = 0  # u32
    non_solid_duration: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "StormyCloudTile":
        t = cls()
        t.sting_duration = s.read_u32()
        t.is_solid = s.read_u32()
        t.non_solid_duration = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.sting_duration)
        s.write_u32(self.is_solid)
        s.write_u32(self.non_solid_duration)


@dataclass(slots=True)
class TemporaryPlatformTile(TileExtra):
    time_ms: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "TemporaryPlatformTile":
        t = cls()
        t.time_ms = s.read_u32()
        return TemporaryPlatformTile()

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.time_ms)


@dataclass(slots=True)
class SafeVaultTile(TileExtra):

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SafeVaultTile":
        t = SafeVaultTile()
        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        pass


@dataclass(slots=True)
class AngelicCountingCloudTile(TileExtra):
    is_raffling: int = 0  # u32
    ascii: bytes = b""

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "AngelicCountingCloudTile":
        t = cls()
        t.is_raffling = s.read_u32()
        t.ascii = s.read_pascal_bytes("H")
        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.is_raffling)
        s.write_pascal_bytes("H", self.ascii)


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

    def serialize_into(self, s: Buffer) -> None:
        s.write_u32(self.field_1)
        s.write_u32(self.field_2)
        s.write_u32(self.field_3)
        s.write_u32(self.field_4)
        s.write_u32(self.field_5)
        s.write_u32(1 if self.field_b6 else 0)
        s.write_u32(1 if self.field_b7 else 0)
        s.write_u32(self.field_8)
        s.write_u32(self.field_9)
        s.write_u32(self.field_10)
        s.write_u32(1 if self.field_b11 else 0)
        s.write_u32(self.field_12)
        s.write_u32(self.field_13)
        s.write_u32(self.field_14)
        s.write_u32(1 if self.field_b15 else 0)
        s.write_u32(self.field_16)
        s.write_u32(self.field_17)
        s.write_u32(self.field_18)
        s.write_u32(self.field_19)
        s.write_u32(1 if self.field_b20 else 0)
        s.write_u32(self.field_21)
        s.write_u32(self.field_22)
        s.write_u32(self.field_23)
        s.write_u32(self.field_25)
        s.write_u32(1 if self.field_b26 else 0)
        s.write_u32(len(self.pos))
        for x, y in self.pos:
            s.write_u32(x)
            s.write_u32(y)


@dataclass(slots=True)
class PveNpcTile(TileExtra):
    arr: list[PveNpcData] = field(default_factory=list)  # len 3

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PveNpcTile":
        t = cls()
        for _ in range(3):
            t.arr.append(PveNpcData.deserialize(s))

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        for npc in self.arr:
            npc.serialize_into(s)


@dataclass(slots=True)
class InfinityWeatherMachineTile(TileExtra):
    cycle_time_ms: int = 0  # u32
    weather_machine_list: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "InfinityWeatherMachineTile":
        t = cls()
        t.cycle_time_ms = s.read_u32()
        for _ in range(s.read_u32()):
            t.weather_machine_list.append(s.read_u32())

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.cycle_time_ms)
        s.write_u32(len(self.weather_machine_list))
        for item_id in self.weather_machine_list:
            s.write_u32(item_id)


@dataclass(slots=True)
class CompletionistTile(TileExtra):
    unk1: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "CompletionistTile":
        t = cls()
        t.unk1 = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.unk1)


@dataclass(slots=True)
class PineappleGuzzlerTile(TileExtra):
    pineapple_fed: int = 0  # u32

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PineappleGuzzlerTile":
        t = cls()
        t.pineapple_fed = s.read_u32()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.pineapple_fed)


@dataclass(slots=True)
class KrankenGalaticBlockTile(TileExtra):
    pattern_index: int = 0  # u8
    unk1: int = 0  # u32
    r: int = 0  # u8
    g: int = 0  # u8
    b: int = 0  # u8

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "KrankenGalaticBlockTile":
        t = cls()
        t.pattern_index = s.read_u8()
        t.unk1 = s.read_u32()
        t.r = s.read_u8()
        t.g = s.read_u8()
        t.b = s.read_u8()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u8(self.pattern_index)
        s.write_u32(self.unk1)
        s.write_u8(self.r)
        s.write_u8(self.g)
        s.write_u8(self.b)


@dataclass(slots=True)
class FriendsEntranceTile(TileExtra):
    owner_uid: int = 0  # u32
    unk1: int = 0  # u16
    unk2: int = 0  # u16

    @classmethod
    def int__deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "FriendsEntranceTile":
        t = cls()
        t.owner_uid = s.read_u32()
        t.unk1 = s.read_u16()
        t.unk2 = s.read_u16()

        return t

    def int__serialize_into(self, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> None:
        s.write_u32(self.owner_uid)
        s.write_u16(self.unk1)
        s.write_u16(self.unk2)


_TILE_EXTRA_REGISTRY: dict[int, type[TileExtra]] = {
    TileExtraType.DOOR_TILE: DoorTile,
    TileExtraType.SIGN_TILE: SignTile,
    TileExtraType.LOCK_TILE: LockTile,
    TileExtraType.SEED_TILE: SeedTile,
    TileExtraType.UNK_SCROLL_BULETTIN: ScrollBulletinTile,
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

    def is_painted(self) -> bool:
        return self.value & (TileFlags.PAINTED_RED | TileFlags.PAINTED_GREEN | TileFlags.PAINTED_BLUE) != 0


def _make_matrix(r: float, g: float, b: float) -> npt.NDArray[np.float32]:
    M = np.zeros((4, 5), dtype=np.float32)
    M[0, 0] = r
    M[1, 1] = g
    M[2, 2] = b
    M[3, 3] = 1.0
    M.flags.writeable = False
    return M


_COLOR_MATRICES = {
    0b000: _make_matrix(1.0, 1.0, 1.0),  # none
    0b001: _make_matrix(1.0, 0.235, 0.235),  # red
    0b010: _make_matrix(0.235, 1.0, 0.235),  # green
    0b011: _make_matrix(1.0, 1.0, 0.235),  # yellow
    0b100: _make_matrix(0.235, 0.235, 1.0),  # blue
    0b101: _make_matrix(1.0, 0.235, 1.0),  # purple
    0b110: _make_matrix(0.235, 1.0, 1.0),  # aqua
    0b111: _make_matrix(0.235, 0.235, 0.235),  # charcoal
}
COLOR_MASK = TileFlags.PAINTED_RED | TileFlags.PAINTED_GREEN | TileFlags.PAINTED_BLUE
COLOR_SHIFT = TileFlags.PAINTED_RED.bit_length() - 1


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
    overlay_tex_index: int = 0  # ON_FIRE, IS_WET
    json_data: dict = field(default_factory=dict)

    logger = logging.getLogger("tile")

    def get_paint_index(self) -> int:
        return (int(self.flags) & COLOR_MASK) >> COLOR_SHIFT

    def tex_pos(self, id: int, tex_index: int) -> tuple[ivec2, bool]:
        item = item_database.get(id)

        stride = item.get_tex_stride()
        if item.flags & ItemFlag.FLIPPABLE != 0:
            is_flipped = self.flags & TileFlags.FLIPPED_X != 0
            if is_flipped and item.texture_type == ItemInfoTextureType.SMART_EDGE_HORIZ:
                # handle flipped couch texture
                if tex_index == 0:
                    tex_index = 2
                elif tex_index == 2:
                    tex_index = 0
        else:
            is_flipped = False

        if (
            item.collision_type == ItemInfoCollisionType.COLLIDE_IF_OFF
            and self.flags & TileFlags.IS_ON != 0
            or item.collision_type == ItemInfoCollisionType.COLLIDE_IF_ON
            and self.flags & TileFlags.IS_ON == 0
            or item.item_type == ItemInfoType.BOOMBOX
            and self.flags & TileFlags.IS_ON != 0
        ):
            tex_index += 1
            stride = 2

        off = ivec2(tex_index % max(stride, 1), tex_index // stride if stride else 0)
        tex = ivec2(item.tex_coord_x, item.tex_coord_y) + off

        return tex, is_flipped

    def get_texture(self, mgr: RTTexManager, id: int, tex_index: int) -> npt.NDArray[np.uint8]:
        item = item_database.get(id)

        tex_pos, is_flipped = self.tex_pos(id, tex_index)
        tex = mgr.get(setting.gt_path / "game" / item.texture_file.decode(), tex_pos.x * 32, tex_pos.y * 32, 32, 32, flip_x=is_flipped)
        # in the website, they uses css feColorMatrix which uses linear space, but in the game they don't,
        # causing a more saturated color as opposed to a "pastel" look in the website
        tex = color_matrix_filter(tex, _COLOR_MATRICES[self.get_paint_index()], linear=False)

        return tex

    def get_fg_texture(self, mgr: RTTexManager) -> npt.NDArray[np.uint8]:
        return self.get_texture(mgr, self.fg_id, self.fg_tex_index)

    def get_bg_texture(self, mgr: RTTexManager) -> npt.NDArray[np.uint8]:
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
            extra=TileExtra.deserialize_extra(Buffer(proto.extra), proto.fg_id, proto.bg_id) if proto.extra else None,
            _extra_raw=proto.extra,
            index=proto.index,
            pos=ivec2(proto.x, proto.y),
            fg_tex_index=proto.fg_tex_index,
            bg_tex_index=proto.bg_tex_index,
            overlay_tex_index=proto.overlay_tex_index,
            json_data=cbor2.loads(proto.json_data) if proto.json_data else {},
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
            fg_tex_index=self.fg_tex_index,
            bg_tex_index=self.bg_tex_index,
            overlay_tex_index=self.overlay_tex_index,
            json_data=cbor2.dumps(self.json_data) if self.json_data else None,
        )

    @classmethod
    def deserialize(cls, s: Buffer, format_version: int = 999999999999, strict: bool = True) -> "Tile":
        tile = cls()
        tile.fg_id = s.read_u16()
        tile.bg_id = s.read_u16()
        if strict:
            if tile.fg_id > item_database.item_count:
                raise ValueError(f"illegal foreground item: {tile.fg_id}")
            if tile.bg_id > item_database.item_count:
                raise ValueError(f"illegal background item: {tile.bg_id}")

        tile.parent_index = s.read_u16()
        tile.flags = TileFlags(s.read_u16())

        if tile.flags & TileFlags.LOCKED:
            tile.lock_index = s.read_u16()

        if tile.flags & TileFlags.HAS_EXTRA_DATA:
            start = s.rpos
            tile.extra = TileExtra.deserialize_extra(s, tile.fg_id, tile.bg_id, format_version)
            extra_size = s.rpos - start

            s.rpos = start
            tile._extra_raw = s.read_bytes(extra_size)

        if tile.fg_id in CBOR_IDs:
            tile.json_data = cbor2.loads(s.read_pascal_bytes("I"))

        return tile

    def serialize_into(self, s: Buffer, format_version: int = 999999999999) -> bytes:
        s.write_u16(self.fg_id)
        s.write_u16(self.bg_id)
        s.write_u16(self.parent_index)
        s.write_u16(int(self.flags))

        if self.flags & TileFlags.LOCKED:
            s.write_u16(self.lock_index)

        if self.flags & TileFlags.HAS_EXTRA_DATA:
            if self.extra is not None:
                self.extra.serialize_into(s, self.fg_id, self.bg_id, format_version)

        if self.fg_id in CBOR_IDs:
            s.write_pascal_bytes("I", cbor2.dumps(self.json_data))

        return s.getvalue()

    def serialize(self, format_version: int = 999999999999) -> bytes:
        s = Buffer()
        self.serialize_into(s, format_version)
        return s.getvalue()


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


class NpcType(IntEnum):
    NONE = 0
    GHOST = 1
    GHOST_JAR = 2
    BEE_SWARM = 3
    HARVEST_GHOST = 4
    GROWGANOTH = 5
    GHOST_SHARK = 6
    XMAS_GHOST = 7
    BLAST = 8
    PINATA = 9
    GHOST_CAPTURE_MACHINE = 10
    BOSS_GHOST = 11
    MIND_CONTROL_GHOST = 12
    GHOST_BE_GONE = 13
    HUNTED_TURKEY = 14
    TRICKSTER = 15
    THANKSGIVING_TURKEY_BOSS = 16
    THANKSGIVING_TURKEY_BOSS_FEATHER_PROJECTILE = 17
    ATTACKER_MINION_TURKEY = 18
    BEACH_ENEMY = 19
    XML_CONFIGURED = 20
    XML_RENDERED = 21


class NpcEvent(IntEnum):
    FULL_STATE = 0
    DELETE = 1
    ADD = 2
    MOVE = 3
    SUCKED = 4
    BURP = 5
    TELEPORT = 6
    DIE = 7
    PUNCH = 8
    OUCH = 9
    ATTACK = 10
    PREPARE_TO_ATACK = 11


@dataclass(slots=True)
class Npc:
    type: NpcType = NpcType.NONE  # u8
    id: int = 0  # u8
    pos: vec2 = field(default_factory=vec2)  # f32 * 2
    target_pos: vec2 = field(default_factory=vec2)  # f32 * 2
    param1: int = 0  # next state, scale  i32
    param2: int = 0  # orbit radius  i32
    param3: float = 0.0  # speed, orbit radius  f32
    facing_left: bool = False

    @classmethod
    def deserialize(cls, s: Buffer) -> "Npc":
        t = cls()

        t.type = NpcType(s.read_u8())
        t.id = s.read_u8()
        t.pos.x = s.read_f32()
        t.pos.y = s.read_f32()
        t.target_pos.x = s.read_f32()
        t.target_pos.y = s.read_f32()
        t.param1 = s.read_i32()
        t.param2 = s.read_i32()
        t.param3 = s.read_f32()

        return t

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.Npc) -> "Npc":
        return cls(
            id=proto.id,
            type=NpcType(proto.type),
            pos=vec2(proto.x, proto.y),
            target_pos=vec2(proto.target_x, proto.target_y),
            param1=proto.param1,
            param2=proto.param2,
            param3=proto.param3,
            facing_left=proto.facing_left,
        )

    def to_proto(self) -> growtopia_pb2.Npc:
        return growtopia_pb2.Npc(
            id=self.id,
            type=self.type,
            x=self.pos.x,
            y=self.pos.y,
            target_x=self.target_pos.x,
            target_y=self.target_pos.y,
            param1=self.param1,
            param2=self.param2,
            param3=self.param3,
            facing_left=self.facing_left,
        )


class WorldEvent(Enum):
    TILE_UPDATE = auto()
    DROPPED_UPDATE = auto()
    PLAYER_UPDATE = auto()
    NPC_UPDATE = auto()


@dataclass(slots=True)
class World:
    id: int = 0  # u32, from int_x in tank packet
    version: int = 0  # u32
    f: int = 0  # u16
    name: bytes = b""
    width: int = 0  # u32
    height: int = 0  # u32
    nb_tiles: int = 0  # u32
    unk2: bytes = b"\x00" * 5
    tiles: dict[int, Tile] = field(default_factory=dict, repr=False)
    unk4: bytes = b"\x00" * 12
    dropped: Dropped = field(default_factory=Dropped, repr=False)
    default_weather: WeatherType = WeatherType.DEFAULT  # u16
    terraform: TerraformType = TerraformType.DEFAULT  # u16
    active_weather: WeatherType = WeatherType.DEFAULT  # u16
    unk8: int = 0  # u16
    unk9: int = 0  # u32

    # state (not in data)
    players: dict[int, Player] = field(default_factory=dict)
    garbage_start: int = -1
    logger = logging.getLogger("world")
    npcs: dict[int, Npc] = field(default_factory=dict)
    sheet: Sheet | None = None

    _listeners: defaultdict[WorldEvent, list[Callable]] = field(default_factory=lambda: defaultdict(list), init=False, repr=False)

    @overload
    def subscribe(self, event: Literal[WorldEvent.DROPPED_UPDATE], callback: Callable[[], None]) -> None: ...
    @overload
    def subscribe(self, event: Literal[WorldEvent.TILE_UPDATE], callback: Callable[[int, int], None]) -> None: ...
    @overload
    def subscribe(self, event: Literal[WorldEvent.PLAYER_UPDATE], callback: Callable[[], None]) -> None: ...
    @overload
    def subscribe(self, event: Literal[WorldEvent.NPC_UPDATE], callback: Callable[[], None]) -> None: ...
    def subscribe(self, event: WorldEvent, callback: Callable) -> None:
        self._listeners[event].append(callback)

    def unsubscribe(self, event: WorldEvent, callback: Callable) -> None:
        try:
            self._listeners[event].remove(callback)
        except ValueError:
            pass

    def broadcast(self, event: WorldEvent, *args: Any) -> None:
        for cb in self._listeners[event]:
            cb(*args)

    def get_notes(self) -> list[Note]:
        ret: list[Note] = []

        for tile in self.tiles.values():
            # 4 (60 / 14) staff in one world, the topmost is 0, each staff height is 14 note
            staff_baseline = int(tile.pos.y // 14) * 14

            if tile.extra and isinstance(tile.extra, AudioRackTile):
                rack = tile.extra.expect(AudioRackTile)
                notes = rack.note.split(b" ")

                for note in notes:
                    if not note or len(note) != 3:
                        continue

                    code, pitch_str, accidental = list(note.decode())
                    pitch, octave = CODE_TO_PITCH_MAP[pitch_str]

                    ret.append(
                        Note(
                            base=pitch,
                            octave=octave,
                            accident=ACCIDENT_MAP[accidental],
                            instrument=CODE_TO_INSTRUMENT_SET[code],
                            timestamp=int(staff_baseline // 14) * self.width + tile.pos.x,
                            volume=rack.volume / 100 if rack.volume != 0 else 0,
                        )
                    )
                    continue

            if tile.bg_id == 0:
                continue

            item = item_database.get(tile.bg_id)
            if item.item_type == ItemInfoType.MUSICNOTE:
                accident = Note.SHARP if tile.bg_id in SHEET_SHARP_ID else Note.FLAT if tile.bg_id in SHEET_FLAT_ID else Note.NATURAL

                pitch, octave = Y_TO_PITCH_MAP[tile.pos.y - staff_baseline]

                ret.append(
                    Note(
                        base=pitch,
                        octave=octave,
                        accident=accident,
                        instrument=ID_TO_INSTRUMENT_SET[tile.bg_id],
                        timestamp=int(tile.pos.y // 14) * self.width + tile.pos.x,
                    )
                )

        return ret

    def get_sheet(self, mixer: AudioMixer) -> Sheet:
        lock = self.get_world_lock()
        if lock is None or lock.extra is None:
            bpm = 100
        else:
            bpm = lock.extra.expect(LockTile).bpm

        if not self.sheet:
            self.sheet = Sheet(
                bpm=bpm,
                notes=self.get_notes(),
                mixer=mixer,
            )

        return self.sheet

    def get_npc(self, id: int) -> Npc | None:
        npc = self.npcs.get(id)
        if not npc:
            self.logger.warning(f"no npc with id {id} on {self.name}")

        return npc

    def add_npc(self, npc: Npc) -> None:
        self.npcs[npc.id] = npc
        self.broadcast(WorldEvent.NPC_UPDATE)

    def remove_npc(self, npc: Npc) -> None:
        self.npcs.pop(npc.id, None)
        self.broadcast(WorldEvent.NPC_UPDATE)

    def remove_npc_by_id(self, id: int) -> None:
        self.npcs.pop(id)
        self.broadcast(WorldEvent.NPC_UPDATE)

    def update_npc(self, dt: float) -> None:
        for npc in self.npcs.values():
            delta = npc.target_pos - npc.pos
            distance = glm.length(delta)

            if distance > 0:
                npc.facing_left = delta.x < 0

                step = npc.param3 * dt
                if step >= distance:
                    npc.pos = vec2(npc.target_pos.x, npc.target_pos.y)
                else:
                    direction = delta / distance
                    npc.pos += direction * step

    def get_player(self, net_id: int) -> Player | None:
        player = self.players.get(net_id)
        if not player:
            self.logger.warning(f"player with net_id={net_id} does not exists in world {self.name}")

        return player

    def add_player(self, player: Player) -> None:
        self.players[player.net_id] = player
        self.broadcast(WorldEvent.PLAYER_UPDATE)

    def remove_player(self, player: Player) -> None:
        self.players.pop(player.net_id, None)
        self.broadcast(WorldEvent.PLAYER_UPDATE)

    def remove_player_by_id(self, net_id: int) -> None:
        self.players.pop(net_id, None)
        self.broadcast(WorldEvent.PLAYER_UPDATE)

    @classmethod
    def from_tiles(cls, tiles: list[Tile]) -> "World":
        world = cls()
        xs = [t.pos.x for t in tiles]
        width = max(xs) + 1

        for tile in tiles:
            idx = tile.pos.y * width + tile.pos.x
            world.tiles[idx] = tile

        world.fix()

        return world

    def fix(self) -> None:
        """adjust width, height, nb_tiles based on the tiles dict. also fills in any gap."""
        xs = [t.pos.x for t in self.tiles.values()]
        ys = [t.pos.y for t in self.tiles.values()]
        if xs:
            self.width = max(xs) + 1
        if ys:
            self.height = max(ys) + 1

        for y in range(self.height):
            for x in range(self.width):
                idx = y * self.width + x
                if idx not in self.tiles:
                    tile = Tile(pos=ivec2(x, y))
                    tile.index = idx
                    self.tiles[idx] = tile

        self.nb_tiles = len(self.tiles)

    def get_world_lock(self) -> Tile | None:
        for tile in self.tiles.values():
            if not tile.extra:
                continue

            if isinstance(tile.extra, LockTile) and not tile.fg_id in (SMALL_LOCK, BIG_LOCK, HUGE_LOCK, BUILDER_S_LOCK):
                return tile

    def tile_exists(self, pos: ivec2 | int) -> bool:
        return self.get_tile(pos) is not None

    def get_front(self, pos: ivec2 | int) -> int:
        if (tile := self.get_tile(pos)) is not None:
            return tile.front

        return 0

    @overload
    def get_tile(self, x: ivec2) -> Tile | None: ...
    @overload
    def get_tile(self, x: int) -> Tile | None: ...
    @overload
    def get_tile(self, x: int, y: int) -> Tile | None: ...

    def get_tile(self, x: ivec2 | int, y: int | None = None) -> Tile | None:
        if isinstance(x, ivec2):
            idx = x.y * self.width + x.x
        elif y is None:
            idx = x
        else:
            idx = y * self.width + x

        tile = self.tiles.get(idx)
        if tile is None:
            self.logger.warning(f"tile idx={idx} in {self.name} does not exist")

        return tile

    def find_tile(self, where: Callable[[Tile], object]) -> Iterator[Tile]:
        for tile in self.tiles.values():
            if bool(where(tile)):
                yield tile

    def index_tile(self, pos: ivec2) -> int | None:
        return pos.y * self.width + pos.x

    def index_to_pos(self, index: int) -> ivec2:
        return ivec2(index % self.width, index // self.width)

    def destroy_tile(self, pos: ivec2) -> None:
        if (tile := self.get_tile(pos)) is None:
            return

        if tile.fg_id != 0:
            tile.fg_id = 0
        else:
            tile.bg_id = 0

        self.broadcast(WorldEvent.TILE_UPDATE, pos.x, pos.y)

    def place_tile(self, id: int, pos: ivec2) -> None:
        if (tile := self.get_tile(pos)) is None:
            return

        if item_database.get(id).is_background():
            tile.bg_id = id
        else:
            tile.fg_id = id
            if id % 2 != 0:
                tile.extra = SeedTile()

        self.broadcast(WorldEvent.TILE_UPDATE, pos.x, pos.y)

    def replace_whole_tile(self, tile: Tile) -> None:
        idx = self.index_tile(tile.pos)
        if idx is not None:
            tile.index = idx
            self.tiles[idx] = tile
            self.broadcast(WorldEvent.TILE_UPDATE, tile.pos.x, tile.pos.y)

    def place_fg(self, tile: Tile, fg: int, connection: int = 0, a5: bool = False, broadcast: bool = True) -> None:
        item = item_database.get(fg)
        if tile.extra:
            if tile.extra.type == TileExtraType.LOCK_TILE and tile.fg_id != fg:
                self.remove_locked(tile)
            tile.extra = None
        tile.fg_id = fg
        tile.fg_tex_index = connection

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
                tile.flags |= TileFlags.HAS_EXTRA_DATA
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

        if broadcast:
            self.broadcast(WorldEvent.TILE_UPDATE, tile.pos.x, tile.pos.y)

    def place_bg(self, tile: Tile, bg: int, connection: int = 0) -> None:
        if bg == TRANSDIMENSIONAL_VAPORIZER_RAY:
            tile.bg_id = 0
            tile.flags &= ~TileFlags.BG_IS_ON
        else:
            tile.bg_id = bg
        tile.bg_tex_index = connection

        self.broadcast(WorldEvent.TILE_UPDATE, tile.pos.x, tile.pos.y)

    def update_tile_connection(self, tile: Tile) -> None:
        item = item_database.get(tile.fg_id)
        texture_type = item.texture_type

        if item.is_steam():
            texture_type = ItemInfoTextureType.SMART_EDGE

        match texture_type:
            case ItemInfoTextureType.SINGLE_FRAME_ALONE | ItemInfoTextureType.SINGLE_FRAME | ItemInfoTextureType.SMART_OUTER:
                tile.fg_tex_index = 0
            case ItemInfoTextureType.SMART_EDGE:
                if item.is_steam():
                    tile.fg_tex_index = int(handle_smart_edge_connection(self, tile, 2))
                else:
                    tile.fg_tex_index = int(handle_smart_edge_connection(self, tile, 0))
            case ItemInfoTextureType.SMART_EDGE_HORIZ:
                if item.is_seed():
                    tile.fg_tex_index = int(handle_smart_edge_horiz_seed_connection(self, tile, 0))
                else:
                    tile.fg_tex_index = int(handle_smart_edge_horiz_connection(self, tile, 0))
            case ItemInfoTextureType.SMART_CLING2:
                tile.fg_tex_index = int(handle_smart_cling2_connection(self, tile, 0))
            case ItemInfoTextureType.SMART_CLING | ItemInfoTextureType.SMART_EDGE_HORIZ_CAVE:
                tile.fg_tex_index = int(handle_smart_cling_connection(self, tile, 0))
            case ItemInfoTextureType.RANDOM:
                if item.is_seed():
                    tile.fg_tex_index = int(handle_random_seed_connection(self, tile, 0))
                else:
                    tile.fg_tex_index = int(handle_random_connection(self, tile, 0))
            case ItemInfoTextureType.SMART_EDGE_VERT:
                tile.fg_tex_index = int(handle_smart_edge_vert_connection(self, tile, 0))
            case ItemInfoTextureType.SMART_EDGE_DIAGON:
                tile.fg_tex_index = int(handle_smart_edge_diagon_connection(self, tile, 0))

        item = item_database.get(tile.bg_id)
        match item.texture_type:
            case ItemInfoTextureType.SINGLE_FRAME_ALONE | ItemInfoTextureType.SINGLE_FRAME | ItemInfoTextureType.SMART_OUTER:
                tile.bg_tex_index = 0
            case ItemInfoTextureType.SMART_EDGE:
                tile.bg_tex_index = int(handle_smart_edge_connection(self, tile, 1))
            case ItemInfoTextureType.SMART_EDGE_HORIZ:
                if item.is_seed():
                    tile.bg_tex_index = int(handle_smart_edge_horiz_seed_connection(self, tile, 1))
                else:
                    tile.bg_tex_index = int(handle_smart_edge_horiz_connection(self, tile, 1))
            case ItemInfoTextureType.SMART_CLING2:
                tile.bg_tex_index = int(handle_smart_cling2_connection(self, tile, 1))
            case ItemInfoTextureType.SMART_CLING | ItemInfoTextureType.SMART_EDGE_HORIZ_CAVE:
                tile.bg_tex_index = int(handle_smart_cling_connection(self, tile, 1))
            case ItemInfoTextureType.RANDOM:
                tile.bg_tex_index = int(handle_random_connection(self, tile, 1))
            case ItemInfoTextureType.SMART_EDGE_VERT:
                tile.bg_tex_index = int(handle_smart_edge_vert_connection(self, tile, 1))
            case ItemInfoTextureType.SMART_EDGE_DIAGON:
                tile.bg_tex_index = int(handle_smart_edge_horiz_seed_connection(self, tile, 1))

        if tile.flags & (TileFlags.ON_FIRE | TileFlags.IS_WET):
            tile.overlay_tex_index = int(handle_smart_edge_connection(self, tile, 3))
        else:
            tile.overlay_tex_index = 0

        self.broadcast(WorldEvent.TILE_UPDATE, tile.pos.x, tile.pos.y)

    def update_all_connection(self) -> None:
        for tile in self.tiles.values():
            self.update_tile_connection(tile)

    def update_3x3_connection(self, tile_or_pos: Tile | ivec2 | int) -> None:
        if isinstance(tile_or_pos, Tile):
            tile = tile_or_pos
        else:
            tile = self.get_tile(tile_or_pos)
            if not tile:
                return

        for y in range(-1, 2):
            for x in range(-1, 2):
                if n := self.get_tile(tile.pos + ivec2(x, y)):
                    self.update_tile_connection(n)

    def update_tree(self, tile: Tile, item_id: int, harvest: bool, spawn_seed_flag: bool, seedling_flag: bool) -> None:
        if not tile.extra or tile.extra.type != TileExtraType.SEED_TILE:
            return

        if harvest:
            tile.flags &= ~(TileFlags.PAINTED_RED | TileFlags.PAINTED_GREEN | TileFlags.PAINTED_BLUE)
            self.place_fg(tile, 0)
            self.update_3x3_connection(tile)
        else:
            seed = tile.extra.expect(SeedTile)
            seed.item_on_tree = item_id
            if spawn_seed_flag:
                tile.flags |= TileFlags.WILL_SPAWN_SEEDS_TOO
            else:
                tile.flags &= ~TileFlags.WILL_SPAWN_SEEDS_TOO

            if seedling_flag:
                tile.flags |= TileFlags.IS_SEEDLING
            else:
                tile.flags &= ~TileFlags.IS_SEEDLING

            self.broadcast(WorldEvent.TILE_UPDATE, tile.pos.x, tile.pos.y)

            # TODO: set current time here
            # TODO: store somewhere the seed placed time

    def remove_locked(self, locked: Tile) -> Iterator[Tile]:
        if not locked.extra or locked.extra.type != TileExtraType.LOCK_TILE:
            return

        for tile in self.tiles.values():
            if tile.lock_index == locked.index:
                tile.flags &= ~TileFlags.LOCKED
                tile.lock_index = 0
                self.broadcast(WorldEvent.TILE_UPDATE, tile.pos.x, tile.pos.y)
                yield tile

    def plant(self, tile: Tile, id: int, item_on_tree: int, splice: bool) -> None:
        if splice:
            tile.flags |= TileFlags.WILL_SPAWN_SEEDS_TOO

        self.place_fg(tile, id)
        assert tile.extra
        tile.extra.expect(SeedTile).item_on_tree = item_on_tree

    def tile_change(
        self,
        tile: Tile,
        inventory: Inventory,
        id: int,
        flags: TankFlags,
        net_id: int,
        splice: bool = False,
        should_take_item: bool = True,
        item_on_tree: int = 0,
    ) -> None:
        item = item_database.get(id)

        if net_id != -1 and should_take_item and self.get_player(net_id):
            inventory.add(id, -1)

        if item.item_type == ItemInfoType.SEED:
            if tile.fg_id == 0:
                self.plant(tile, id, item_on_tree, splice)
            return

        if item.is_background():
            self.place_bg(tile, id)
            self.update_3x3_connection(tile)
            return
        else:
            if item.item_type != ItemInfoType.FIST:
                self.place_fg(tile, id)
                if id == ANGRY_ADVENTURE_GORILLA:
                    tile.flags |= TileFlags.IS_ON
            elif tile.fg_id:
                self.place_fg(tile, 0)
            elif tile.bg_id:
                self.place_bg(tile, 0)

        if item.is_background():
            if item.item_type == ItemInfoType.SEED and tile.extra:
                if splice:
                    tile.flags |= TileFlags.WILL_SPAWN_SEEDS_TOO
                else:
                    tile.flags &= ~TileFlags.WILL_SPAWN_SEEDS_TOO
                tile.flags |= TileFlags.IS_SEEDLING
                tile.extra.expect(SeedTile).item_on_tree = item_on_tree

        if item.flags2 & ItemFlag.FLIPPABLE != 0:
            if flags & TankFlags.FACING_LEFT:
                tile.flags |= TileFlags.FLIPPED_X
            else:
                tile.flags &= ~TileFlags.FLIPPED_X

        self.update_3x3_connection(tile)

    def update_lock(self, pos: ivec2, lock_owner_id: int, lock_item_id: int, tiles_affected: Iterator[int]) -> None:
        if lock_tile := self.get_tile(pos):
            # place lock if it doesn't exists
            if (lock_tile.extra and lock_tile.extra.type != TileExtraType.LOCK_TILE) or lock_tile.extra is None or lock_tile.extra.expect(LockTile).owner_uid != lock_owner_id:
                self.place_fg(lock_tile, lock_item_id, broadcast=False)
                assert lock_tile.extra
                lock_tile.extra.expect(LockTile).owner_uid = lock_owner_id
                self.broadcast(WorldEvent.TILE_UPDATE, lock_tile.pos.x, lock_tile.pos.y)

            self.remove_locked(lock_tile)

            for tile in tiles_affected:
                target_tile = self.get_tile(tile)
                if not target_tile:
                    raise ValueError(f"update_lock: tile at {tile=} should exists, but it doesn't")

                target_tile.flags |= TileFlags.LOCKED
                target_tile.lock_index = lock_tile.index

                # self.update_tile_connection(target_tile)
                self.broadcast(WorldEvent.TILE_UPDATE, target_tile.pos.x, target_tile.pos.y)

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

        self.broadcast(WorldEvent.DROPPED_UPDATE)

    def remove_dropped(self, uid: int) -> DroppedItem | None:
        for i, item in enumerate(self.dropped.items):
            if item.uid != uid:
                continue

            self.dropped.items.pop(i)
            self.dropped.nb_items -= 1
            self.broadcast(WorldEvent.DROPPED_UPDATE)
            return item

    def set_dropped(self, uid: int, amount: int) -> None:
        for item in self.dropped.items:
            if item.uid != uid:
                continue

            item.amount = amount
            self.broadcast(WorldEvent.DROPPED_UPDATE)

    @classmethod
    def from_tank(cls, tank: TankPacket | bytes) -> "World":
        if isinstance(tank, bytes):
            tank = NetPacket.deserialize(tank).tank

        return cls.deserialize(tank.extended_data, int_x_id=tank.int_x)

    @classmethod
    def from_extended(cls, extended: bytes) -> "World":
        return cls.deserialize(Buffer(extended))

    @classmethod
    def from_file(cls, file: Path | str) -> "World":
        return cls.from_tank(Path(file).read_bytes())

    def serialize(self) -> bytes:
        s = Buffer()

        s.write_u16(self.version)
        s.write_u32(self.f)
        s.write_pascal_bytes("H", self.name)
        s.write_u32(self.width)
        s.write_u32(self.height)
        s.write_u32(self.nb_tiles)

        s.write_bytes(self.unk2)

        for i in range(self.nb_tiles):
            tile = self.tiles[i]
            tile.serialize_into(s, self.version)

        s.write_bytes(self.unk4)

        s.write_u32(self.dropped.nb_items)
        s.write_u32(self.dropped.last_uid)

        for item in self.dropped.items:
            s.write_u16(item.id)
            s.write_f32(item.pos.x)
            s.write_f32(item.pos.y)
            s.write_u8(item.amount)
            s.write_u8(item.flags)
            s.write_u32(item.uid)

        s.write_u16(self.default_weather.value)
        s.write_u16(self.terraform.value)
        s.write_u16(self.active_weather.value)
        s.write_u16(self.unk8)
        s.write_u32(self.unk9)

        return s.getvalue()

    @classmethod
    def deserialize(cls, s: bytes | Buffer, int_x_id: int = 0) -> "World":
        # we delegate passing the id to the caller because we don't have the tank packet here
        s = Buffer(s)

        world = cls()

        world.id = int_x_id
        world.version = s.read_u16()
        world.f = s.read_u32()
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
            world.tiles[p] = tile

        world.update_all_connection()

        if failed:
            # if we fail, then we cannot parse dropped item, but we can take advantage of the fact that it always placed at the end
            # meaning we can parse it reversed from the end until it failed or found some impossible value
            try:
                with s.reversed(keep=False):
                    world.unk9 = s.read_u32()
                    world.unk8 = s.read_u16()
                    world.active_weather = WeatherType(s.read_u16())
                    world.terraform = TerraformType(s.read_u16())
                    world.default_weather = WeatherType(s.read_u16())

                    while True:
                        item = DroppedItem()
                        item.uid = s.read_u32()
                        item.flags = s.read_u8()
                        item.amount = s.read_u8()
                        item.pos = vec2(s.read_f32(), s.read_f32())
                        item.id = s.read_u16()

                        if item.id not in item_database.items:
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
            except Exception as e:
                # failed to parse dropped for some reason, whatever
                cls.logger.warning(f"failed to parse dropped item from the back: {e}")

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

        world.default_weather = WeatherType(s.read_u16())
        world.terraform = TerraformType(s.read_u16())
        world.active_weather = WeatherType(s.read_u16())
        world.unk8 = s.read_u16()
        world.unk9 = s.read_u32()

        return world

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.World) -> "World":
        tiles: dict[int, Tile] = {}
        for proto_tile in proto.inner.tiles:
            tile = Tile.from_proto(proto_tile)
            idx = tile.pos.y * proto.inner.width + tile.pos.x
            tile.index = idx
            tiles[idx] = tile

        return cls(
            name=proto.inner.name,
            width=proto.inner.width,
            height=proto.inner.height,
            nb_tiles=proto.inner.nb_tiles,
            tiles=tiles,
            dropped=Dropped.from_proto(proto.inner.dropped),
            garbage_start=proto.inner.garbage_start,
            players={p.net_id: p for p in (Player.from_proto(x) for x in proto.player)},
            npcs={npc.id: npc for npc in (Npc.from_proto(x) for x in proto.npcs)},
        )

    def to_proto(self) -> growtopia_pb2.World:
        return growtopia_pb2.World(
            inner=growtopia_pb2.WorldInner(
                name=self.name,
                width=self.width,
                height=self.height,
                nb_tiles=self.nb_tiles,
                tiles=[tile.to_proto() for tile in self.tiles.values()],
                dropped=self.dropped.to_proto(),
                garbage_start=self.garbage_start,
            ),
            player=[x.to_proto() for x in self.players.values()],
            npcs=[x.to_proto() for x in self.npcs.values()],
        )


def steam_can_connect(a1: World, a2: int, a3: int, /) -> bool:
    width: int = 0
    v5: Tile | None = None
    result: bool = False
    if a2 | a3 < 0:
        return False
    width = a1.width
    if width <= a2 or a1.height <= a3:
        return False
    v5 = a1.get_tile(a2, a3)
    if not v5:
        return False
    if ((v5.fg_id == BLANK or v5.fg_id & 1 != 0) or ((result := True), v5.flags & TileFlags.GLUED == 0)[-1],)[-1]:
        if item_database.get(v5.fg_id).is_steam():
            return v5.fg_id != STEAM_LAUNCHER
        return False
    return result


def tile_bg_equal(a1: World, x: int, y: int, target_id: int, flag: int, /) -> bool:
    result: bool = False
    width: int = 0
    v8: Tile | None = None
    bg_id: int = 0
    v10: int = 0
    result = True
    if x | y >= 0:
        width = a1.width
        if width > x and a1.height > y:
            v8 = a1.get_tile(x, y)
            if v8:
                bg_id = v8.bg_id
                if not v8.bg_id:
                    return bg_id == target_id
                if v8.flags & TileFlags.GLUED != 0:
                    return result
                if not flag | target_id ^ WEEPING_WILLOW_BRANCH:
                    if bg_id == WEEPING_WILLOW:
                        return result
                    return bg_id == target_id
                v10 = flag ^ 2
                if (target_id != HAUNTED_HOUSE or (v10 | bg_id ^ TWISTED_ROOF != 0 and bg_id != TWISTED_WINDOWS)) and (
                    target_id != DARK_CAVE_BACKGROUND or bg_id != DWARVEN_BACKGROUND
                ):
                    return bg_id == target_id
    return result


def tile_should_connect(a1: World, x: int, y: int, id: int, flag: int, /) -> bool:
    width: int = 0
    v9: Tile | None = None
    v10: int = 0
    v11: int = 0
    v12: bool | int = False
    __goto_return_value = False

    def __block_start():
        nonlocal v10, v11, v12, v9, width, __goto_return_value
        if x | y < 0:
            __goto_return_value = True
            return None
        width = a1.width
        if width <= x:
            __goto_return_value = True
            return None
        if a1.height <= y:
            __goto_return_value = True
            return None
        v9 = a1.get_tile(x, y)
        if not v9:
            __goto_return_value = True
            return None
        if v9.fg_id:
            if v9.fg_id & 1 == 0 and v9.flags & TileFlags.GLUED != 0:
                __goto_return_value = True
                return None
        if (flag != 0 and id == CAVE_DIRT) and v9.fg_id == CAVE_COLUMN:
            __goto_return_value = True
            return None
        v10 = id ^ CAVE_DIRT
        v11 = flag ^ 2
        if not flag ^ 2 | id ^ CAVE_DIRT:
            if v9.fg_id == STALAGMITE:
                __goto_return_value = True
                return None
            return "LABEL_15"
        if not v10 | flag ^ 1:
            if v9.fg_id == STALACTITE:
                __goto_return_value = True
                return None
            return "LABEL_15"
        v12 = flag == 0
        if not flag | v10:
            v12 = 1
            if v9.fg_id == CAVE_PLATFORM:
                __goto_return_value = v12
                return None
            if v9.fg_id >= PURPLE_CAVE_CRYSTAL and v9.fg_id < AQUA_CAVE_CRYSTAL_SEED or (v12 and v9.fg_id == CLIMBING_WALL):
                __goto_return_value = True
                return None
            return "LABEL_61"
        if not v11 | id ^ CAVE_COLUMN:
            v12 = 1
            if v9.fg_id == CAVE_PLATFORM:
                __goto_return_value = v12
                return None
            __goto_return_value = v9.fg_id == id
            return None
        if id == CAVE_DIRT:
            return "LABEL_15"
        if id > STONE_PAGODA_ROOF_ELEMENT_SEED:
            if id <= GROWMOJI_TURKEY_SEED:
                if id == DECORATIVE_ROOF_DRAGON:
                    if v9.fg_id == STONE_PAGODA_BASE:
                        __goto_return_value = v12
                        return None
                else:
                    if id == ANCIENT_BLOCK and v9.fg_id == MYSTERY_DOOR:
                        __goto_return_value = True
                        return None
                    return "LABEL_61"
            if id != MONOCHROMATIC_BEDROCK:
                if id == BEDROCK_CANDY:
                    if v9.fg_id == DATA_BEDROCK_CANDY:
                        __goto_return_value = True
                        return None
                else:
                    if id == DATA_BEDROCK_CANDY and v9.fg_id == BEDROCK_CANDY:
                        __goto_return_value = True
                        return None
                    return "LABEL_61"
            return "LABEL_45"
        if id <= CLIMBING_BOOTS_SEED:
            if id == DIRT:
                if v9.fg_id == FISSURE:
                    __goto_return_value = True
                    return None
                return "LABEL_61"
            if id != BEDROCK:
                return "LABEL_61"
            return "LABEL_45"
        while True:
            __switch_on0 = id
            _switch_matched_any0 = False
            __matched0 = False
            if __matched0 or __switch_on0 == STEAM_PIPE:
                if not __matched0 and __switch_on0 == STEAM_PIPE:
                    _switch_matched_any0 = True
                __matched0 = True
                if item_database.get(v9.fg_id).is_steam():
                    __goto_return_value = True
                    return None
                break
            if __matched0 or __switch_on0 == DATA_BEDROCK:
                if not __matched0 and __switch_on0 == DATA_BEDROCK:
                    _switch_matched_any0 = True
                __matched0 = True
                if v9.fg_id == BEDROCK or v9.fg_id == MONOCHROMATIC_BEDROCK:
                    __goto_return_value = True
                    return None
                break
            if __matched0 or __switch_on0 == STONE_PAGODA:
                if not __matched0 and __switch_on0 == STONE_PAGODA:
                    _switch_matched_any0 = True
                __matched0 = True
                if v9.fg_id == MASTER_PENG_STONEWORK:
                    __goto_return_value = True
                    return None
                if v9.fg_id == STONE_PAGODA_BASE:
                    __goto_return_value = flag != 2
                    return None
                break
            break
        if not flag:
            if id > MAGIC_INFUSED_STONE_BACKGROUND_SEED:
                if id == MAGIC_INFUSED_VEIN:
                    return "LABEL_95"
                return "LABEL_70"
            if id != MANOR_HOUSE_SANDSTONE:
                if id != MAGIC_INFUSED_STONE:
                    __goto_return_value = v9.fg_id == id
                    return None
                return "LABEL_79"
            return "LABEL_81"
        if id != GUILD_FLAG_POLE_SPEAR:
            if id != MANOR_HOUSE_SANDSTONE:
                if id == GUILD_FLAG_POLE_WINGS:
                    return "LABEL_65"
                if not v11 | id ^ 8934:
                    v12 = 1
                    if v9.fg_id == WEEPING_WILLOW_FOLIAGE:
                        __goto_return_value = v12
                        return None
                    __goto_return_value = v9.fg_id == id
                    return None
                if not v11 | id ^ 9308:
                    v12 = 1
                    if v9.fg_id == LOVEWILLOW:
                        __goto_return_value = v12
                        return None
                    __goto_return_value = v9.fg_id == id
                    return None
                if not v11 | id ^ 8344:
                    v12 = 1
                    if v9.fg_id == BONE_CHECKPOINT:
                        __goto_return_value = v12
                        return None
                    __goto_return_value = v9.fg_id == id
                    return None
                if id <= MAGIC_INFUSED_VEIN_SEED:
                    if id != MAGIC_INFUSED_STONE:
                        if id != MAGIC_INFUSED_VEIN:
                            __goto_return_value = v9.fg_id == id
                            return None
                        return "LABEL_95"
                    return "LABEL_79"
                return "LABEL_70"
            return "LABEL_81"
        if v9.fg_id < GUILD_FLAG_TATTERS:
            __goto_return_value = v9.fg_id == id
            return None
        v12 = 1
        if v9.fg_id >= GUILD_FLAG_SHIELD_OPEN_DIVISION_CLOSE_SEED:
            __goto_return_value = v9.fg_id == id
            return None
        __goto_return_value = v12
        return None

    def __block_LABEL_15():
        nonlocal v12
        v12 = 0
        return "LABEL_16"

    def __block_LABEL_16():
        nonlocal __goto_return_value
        assert v9 is not None, "v9 must not be None"
        if v9.fg_id >= PURPLE_CAVE_CRYSTAL and v9.fg_id < AQUA_CAVE_CRYSTAL_SEED or (v12 and v9.fg_id == CLIMBING_WALL):
            __goto_return_value = True
            return None
        return "LABEL_61"

    def __block_LABEL_45():
        nonlocal __goto_return_value
        assert v9 is not None, "v9 must not be None"
        if v9.fg_id == DATA_BEDROCK:
            __goto_return_value = True
            return None
        return "LABEL_61"

    def __block_LABEL_61():
        nonlocal __goto_return_value, v12
        assert v9 is not None, "v9 must not be None"
        if not flag:
            if id > MAGIC_INFUSED_STONE_BACKGROUND_SEED:
                if id == MAGIC_INFUSED_VEIN:
                    return "LABEL_95"
                return "LABEL_70"
            if id != MANOR_HOUSE_SANDSTONE:
                if id != MAGIC_INFUSED_STONE:
                    __goto_return_value = v9.fg_id == id
                    return None
                return "LABEL_79"
            return "LABEL_81"
        if id != GUILD_FLAG_POLE_SPEAR:
            if id != MANOR_HOUSE_SANDSTONE:
                if id == GUILD_FLAG_POLE_WINGS:
                    return "LABEL_65"
                if not v11 | id ^ 8934:
                    v12 = 1
                    if v9.fg_id == WEEPING_WILLOW_FOLIAGE:
                        __goto_return_value = v12
                        return None
                    __goto_return_value = v9.fg_id == id
                    return None
                if not v11 | id ^ 9308:
                    v12 = 1
                    if v9.fg_id == LOVEWILLOW:
                        __goto_return_value = v12
                        return None
                    __goto_return_value = v9.fg_id == id
                    return None
                if not v11 | id ^ 8344:
                    v12 = 1
                    if v9.fg_id == BONE_CHECKPOINT:
                        __goto_return_value = v12
                        return None
                    __goto_return_value = v9.fg_id == id
                    return None
                if id <= MAGIC_INFUSED_VEIN_SEED:
                    if id != MAGIC_INFUSED_STONE:
                        if id != MAGIC_INFUSED_VEIN:
                            __goto_return_value = v9.fg_id == id
                            return None
                        return "LABEL_95"
                    return "LABEL_79"
                return "LABEL_70"
            return "LABEL_81"
        return "LABEL_65"

    def __block_LABEL_65():
        nonlocal __goto_return_value, v12
        assert v9 is not None, "v9 must not be None"
        if v9.fg_id < GUILD_FLAG_TATTERS:
            __goto_return_value = v9.fg_id == id
            return None
        v12 = 1
        if v9.fg_id >= GUILD_FLAG_SHIELD_OPEN_DIVISION_CLOSE_SEED:
            __goto_return_value = v9.fg_id == id
            return None
        __goto_return_value = v12
        return None

    def __block_LABEL_70():
        nonlocal __goto_return_value, v12
        assert v9 is not None, "v9 must not be None"
        if id != PURE_MAGIC_ORE:
            if id != GREAT_WALL_OF_GROWTOPIA:
                __goto_return_value = v9.fg_id == id
                return None
            v12 = 1
            if v9.fg_id != GREAT_TURRET_OF_GROWTOPIA:
                __goto_return_value = v9.fg_id == id
                return None
            __goto_return_value = v12
            return None
        if v9.fg_id == MAGIC_INFUSED_STONE:
            __goto_return_value = True
            return None
        return "LABEL_87"

    def __block_LABEL_79():
        nonlocal __goto_return_value
        assert v9 is not None, "v9 must not be None"
        if v9.fg_id == PURE_MAGIC_ORE:
            __goto_return_value = True
            return None
        return "LABEL_87"

    def __block_LABEL_81():
        nonlocal __goto_return_value, v12
        assert v9 is not None, "v9 must not be None"
        v12 = 1
        if v9.fg_id == MANOR_HOUSE_SANDSTONE_STEPS:
            __goto_return_value = v12
            return None
        __goto_return_value = v9.fg_id == id
        return None

    def __block_LABEL_87():
        nonlocal __goto_return_value, v12
        assert v9 is not None, "v9 must not be None"
        v12 = 1
        if v9.fg_id == MAGIC_INFUSED_VEIN:
            __goto_return_value = v12
            return None
        __goto_return_value = v9.fg_id == id
        return None

    def __block_LABEL_95():
        nonlocal __goto_return_value, v12
        assert v9 is not None, "v9 must not be None"
        if v9.fg_id != PURE_MAGIC_ORE:
            v12 = 1
            if v9.fg_id == MAGIC_INFUSED_STONE:
                __goto_return_value = v12
                return None
            __goto_return_value = v9.fg_id == id
            return None
        __goto_return_value = True
        return None

    __goto_label = "start"
    while True:
        if __goto_label == "start":
            __goto_label = __block_start()
        elif __goto_label == "LABEL_15":
            __goto_label = __block_LABEL_15()
        elif __goto_label == "LABEL_16":
            __goto_label = __block_LABEL_16()
        elif __goto_label == "LABEL_45":
            __goto_label = __block_LABEL_45()
        elif __goto_label == "LABEL_61":
            __goto_label = __block_LABEL_61()
        elif __goto_label == "LABEL_65":
            __goto_label = __block_LABEL_65()
        elif __goto_label == "LABEL_70":
            __goto_label = __block_LABEL_70()
        elif __goto_label == "LABEL_79":
            __goto_label = __block_LABEL_79()
        elif __goto_label == "LABEL_81":
            __goto_label = __block_LABEL_81()
        elif __goto_label == "LABEL_87":
            __goto_label = __block_LABEL_87()
        elif __goto_label == "LABEL_95":
            __goto_label = __block_LABEL_95()
        else:
            break
        if __goto_label is None:
            break
    return __goto_return_value


def tile_flag_equal(world: World, x: int, y: int, flag: TileFlags, /) -> bool:
    if x | y < 0:
        return True

    if world.width <= x or world.height <= y:
        return True

    t = world.get_tile(x, y)
    if not t:
        return True

    return bool(t.flags & flag)


def handle_smart_edge_connection(world: World, a2: Tile | None, mode: int, /) -> int:
    x: int = 0
    y: int = 0
    x_plus_1: int = 0
    bg_id: int = 0
    x_min_1: int = 0
    y_min_1_1: int = 0
    v9: bool | int = False
    v10: bool | int = False
    bg_id_1: int = 0
    v12: bool | int = False
    v13: bool | int = False
    v14: int = 0
    y_min_1: int = 0
    fg_or_bg: int = 0
    v17: int = 0
    v18: int = 0
    v19: int = 0
    v20: int = 0
    v21: int = 0
    v22: int = 0
    v23: int = 0
    v24: int = 0
    v25: int = 0
    v26: bool | int = False
    v27: bool | int = False
    v28: bool | int = False
    v29: bool | int = False
    v30: int = 0
    v31: int = 0
    v32: bool | int = False
    v33: int = 0
    v34: bool | int = False
    v35: bool | int = False
    v36: int = 0
    x_1: int = 0
    x_plus_1_1: int = 0
    v40: bool | int = False
    should_connect: bool | int = False
    v42: bool | int = False
    v43: bool | int = False
    v44: bool | int = False
    v45: bool | int = False
    __goto_return_value: int = 0

    def __block_start():
        nonlocal fg_or_bg, should_connect, bg_id, bg_id_1, v10, v12, v13, v14, v17, v18, v19, v20, v21, v22, v23, v24, v25, v26, v27, v28, v29, v30, v31, v32, v33, v34, v35, v36, v40, v42, v43, v44, v45, v9, x, x_1, x_min_1, x_plus_1, x_plus_1_1, y, y_min_1, y_min_1_1, __goto_return_value
        if not a2:
            __goto_return_value = 12
            return None
        x = a2.pos.x
        y = a2.pos.y
        x_plus_1 = x + 1
        x_plus_1_1 = x + 1
        if mode == 2:
            should_connect = steam_can_connect(world, x_plus_1, y)
            v45 = steam_can_connect(world, x_plus_1, y + 1)
            v42 = steam_can_connect(world, x, y + 1)
            v40 = steam_can_connect(world, x - 1, y + 1)
            v12 = steam_can_connect(world, x - 1, y)
            y_min_1 = y - 1
            v9 = steam_can_connect(world, x - 1, y_min_1)
            v10 = steam_can_connect(world, x, y_min_1)
            v13 = steam_can_connect(world, x_plus_1_1, y_min_1)
        elif mode == 3:
            flag = a2.flags & (TileFlags.ON_FIRE | TileFlags.IS_WET)
            overlay_flag = TileFlags.ON_FIRE if (flag & TileFlags.ON_FIRE) else TileFlags.IS_WET

            should_connect = tile_flag_equal(world, x_plus_1, y, overlay_flag)
            v45 = tile_flag_equal(world, x_plus_1, y + 1, overlay_flag)
            v42 = tile_flag_equal(world, x, y + 1, overlay_flag)
            v40 = tile_flag_equal(world, x - 1, y + 1, overlay_flag)
            v12 = tile_flag_equal(world, x - 1, y, overlay_flag)
            y_min_1 = y - 1
            v9 = tile_flag_equal(world, x - 1, y_min_1, overlay_flag)
            v10 = tile_flag_equal(world, x, y_min_1, overlay_flag)
            v13 = tile_flag_equal(world, x_plus_1_1, y_min_1, overlay_flag)
        else:
            x_1 = a2.pos.x
            if mode == 1:
                bg_id = a2.bg_id
                should_connect = tile_bg_equal(world, x_plus_1, y, bg_id, 0)
                v45 = tile_bg_equal(world, x_plus_1, y + 1, bg_id, 0)
                v42 = tile_bg_equal(world, x, y + 1, bg_id, 0)
                x_min_1 = x - 1
                v40 = tile_bg_equal(world, x_min_1, y + 1, bg_id, 0)
                v43 = tile_bg_equal(world, x_min_1, y, bg_id, 0)
                y_min_1_1 = y - 1
                v9 = tile_bg_equal(world, x_min_1, y_min_1_1, bg_id, 0)
                v10 = tile_bg_equal(world, x_1, y_min_1_1, bg_id, 0)
                bg_id_1 = bg_id
                v12 = v43
                v13 = tile_bg_equal(world, x_plus_1_1, y_min_1_1, bg_id_1, 0)
            else:
                fg_or_bg = a2.fg_id
                should_connect = tile_should_connect(world, x_plus_1, y, fg_or_bg, 0)
                v17 = a2.fg_id
                v45 = tile_should_connect(world, x_plus_1, y + 1, v17, 0)
                v18 = a2.fg_id
                v42 = tile_should_connect(world, x, y + 1, v18, 0)
                v19 = x - 1
                v20 = a2.fg_id
                v40 = tile_should_connect(world, v19, y + 1, v20, 0)
                v21 = a2.fg_id
                v44 = tile_should_connect(world, v19, y, v21, 0)
                v22 = y - 1
                v23 = a2.fg_id
                v9 = tile_should_connect(world, v19, v22, v23, 0)
                v24 = a2.fg_id
                v10 = tile_should_connect(world, x_1, v22, v24, 0)
                v12 = v44
                v25 = a2.fg_id
                v13 = tile_should_connect(world, x_plus_1_1, v22, v25, 0)
        v26 = v42 and should_connect
        v27 = (v12 and v42) and should_connect
        if not v27 or not v10:
            if v27:
                v14 = 1
                if v45 and v40:
                    __goto_return_value = v14
                    return None
                v31 = v40 ^ 39
                v32 = not v45
                v14 = 37
                return "LABEL_26"
            if (v10 and v12) and should_connect:
                v14 = 2
                if v13 and v9:
                    __goto_return_value = v14
                    return None
                v33 = 42 - v9
                v34 = not v13
                v14 = 40
                return "LABEL_32"
            if v10 and v26:
                v14 = 3
                if v45 and v13:
                    __goto_return_value = v14
                    return None
                v31 = v13 ^ 33
                v32 = not v45
                v14 = 31
                return "LABEL_26"
            if (v10 and v12) and v42:
                v14 = 4
                if v9 and v40:
                    __goto_return_value = v14
                    return None
                v33 = 36 - v9
                v34 = not v40
                v14 = 34
                return "LABEL_32"
            if v26:
                v35 = not v45
                v36 = 5
                v14 = 45
            else:
                v14 = 28
                if v12 and should_connect:
                    __goto_return_value = v14
                    return None
                if v10 and should_connect:
                    v35 = not v13
                    v36 = 7
                    v14 = 43
                elif v12 and v42:
                    v35 = not v40
                    v36 = 6
                    v14 = 46
                else:
                    v14 = 9
                    if v10 and v42:
                        __goto_return_value = v14
                        return None
                    if not v10 or not v12:
                        v14 = 10
                        if should_connect:
                            v14 = 29
                        if should_connect or v42:
                            __goto_return_value = v14
                            return None
                        v33 = 12 - v10
                        v34 = not v12
                        v14 = 30
                        if v34:
                            __goto_return_value = v33
                            return None
                        __goto_return_value = v14
                        return None
                    v35 = not v9
                    v36 = 8
                    v14 = 44
            if not v35:
                __goto_return_value = v36
                return None
            __goto_return_value = v14
            return None
        v28 = v40 and v45
        v14 = 0
        if not v13:
            v14 = 14
        if not v9 or not v28:
            v14 = 13
            if not v13 or not v28:
                v14 = 15
                if (not v13 or not v9) or not v45:
                    v29 = v28 or (v9 and v40)
                    v30 = 3 * (not v28) + 17
                    v14 = 16
                    if not v13:
                        v14 = v30
                    if not v9 or not v40:
                        v14 = v30
                    if not v29:
                        v14 = 18
                        if not v13 or not v9:
                            if v13 and v45 or (v9 and v45):
                                __goto_return_value = 3 * (not v13 or not v45) + 19
                                return None
                            v14 = 21
                            if not v13 or not v40:
                                v14 = v45 + 25
                            if not v45 and (not v40):
                                v31 = 3 * (not v13) + 24
                                v32 = not v9
                                v14 = 23
                                return "LABEL_26"
        __goto_return_value = v14
        return None

    def __block_LABEL_26():
        nonlocal __goto_return_value
        if v32:
            __goto_return_value = v31
            return None
        __goto_return_value = v14
        return None

    def __block_LABEL_32():
        nonlocal __goto_return_value
        if v34:
            __goto_return_value = v33
            return None
        __goto_return_value = v14
        return None

    __goto_label = "start"
    while True:
        if __goto_label == "start":
            __goto_label = __block_start()
        elif __goto_label == "LABEL_26":
            __goto_label = __block_LABEL_26()
        elif __goto_label == "LABEL_32":
            __goto_label = __block_LABEL_32()
        else:
            break
        if __goto_label is None:
            break
    return __goto_return_value


def handle_smart_edge_horiz_seed_connection(world: World, tile: Tile, mode: int, /) -> int:
    x: int = 0
    y: int = 0
    flags: int = 0
    v6: int = 0
    bg_id: int = 0
    v8: int = 0
    v9: int = 0
    can_connect: bool | int = False
    v11: int = 0
    fg_or_bg: int = 0
    v13: int = 0
    v14: int = 0
    v15: int = 0
    v16: int = 0
    v17: int = 0
    v18: int = 0
    v19: bool | int = False
    x = tile.pos.x
    y = tile.pos.y
    if mode:
        flags = tile.flags
        v6 = (flags & TileFlags.FLIPPED_X) >> 5
        bg_id = tile.bg_id
        v8 = bg_can_connect(world, x + 1, y, bg_id, v6)
        v9 = bg_id
        can_connect = v8
        v11 = bg_can_connect(world, x - 1, y, v9, v6)
    else:
        fg_or_bg = tile.fg_id
        can_connect = fg_can_connect(world, x + 1, y, fg_or_bg, (tile.flags & TileFlags.FLIPPED_X) >> 5)
        v13 = tile.pos.x - 1
        v14 = tile.pos.y
        v15 = tile.fg_id
        v11 = fg_can_connect(world, v13, v14, v15, (tile.flags & TileFlags.FLIPPED_X) >> 5)
        flags = tile.flags
    v16 = v11 & can_connect
    v17 = 1
    if flags & TileFlags.FLIPPED_X != 0:
        if v16:
            return v17
        v18 = 3 * (v11 ^ 1)
        v19 = not can_connect
        v17 = 2
    else:
        if v16:
            return v17
        v18 = v11 ^ 3
        v17 = 0
        v19 = not can_connect
    if v19:
        return v18
    return v17


def bg_can_connect(world: World, x: int, y: int, target: int, flags: int, /) -> int:
    result: int = 0
    width: int = 0
    v8: Tile | None = None
    result = 1
    if x | y >= 0:
        width = world.width
        if width > x and world.height > y:
            v8 = world.get_tile(x, y)
            if v8:
                if not v8.bg_id or v8.flags & TileFlags.GLUED == 0:
                    if v8.bg_id == target:
                        return flags ^ (v8.flags & TileFlags.FLIPPED_X == 0)
                    else:
                        return 0
    return result


def fg_can_connect(world: World, x: int, y: int, target: int, flags: int, /) -> int:
    v5: bool | int = False
    width: int = 0
    v10: Tile | None = None
    v5 = 1
    if x | y >= 0:
        width = world.width
        if width > x and world.height > y:
            v10 = world.get_tile(x, y)
            if v10:
                if (v10.fg_id == BLANK or v10.fg_id & 1 != 0) or v10.flags & TileFlags.GLUED == 0:
                    if v10.fg_id == target:
                        return flags ^ (v10.flags & TileFlags.FLIPPED_X == 0)
                    else:
                        return 0
    return v5


def handle_smart_edge_horiz_connection(world: World, tile: Tile, mode: int, /) -> int:
    x: int = 0
    v4: int = 0
    y: int = 0
    should_connect: bool | int = False
    v8: bool | int = False
    fg_or_bg: int = 0
    v10: int = 0
    v11: int = 0
    v12: int = 0
    result: int = 0
    v14: bool | int = False
    v15: bool | int = False
    v16: bool | int = False
    v17: bool | int = False
    bg_id: int = 0
    x = tile.pos.x
    v4 = x + 1
    y = tile.pos.y
    if mode:
        bg_id = tile.bg_id
        should_connect = tile_bg_equal(world, v4, y, bg_id, 0)
        v8 = tile_bg_equal(world, x - 1, y, bg_id, 0)
    else:
        fg_or_bg = tile.fg_id
        should_connect = tile_should_connect(world, v4, y, fg_or_bg, 0)
        v10 = tile.pos.x - 1
        v11 = tile.pos.y
        v12 = tile.fg_id
        v8 = tile_should_connect(world, v10, v11, v12, 0)
    if (not should_connect or ((result := 1), not v8)[-1],)[-1]:
        if should_connect:
            if (tile.fg_id != REGAL_STAIRS or ((v14 := tile_should_connect(world, tile.pos.x, tile.pos.y - 1, REGAL_BANNISTER, 0)), (result := 4), not v14)[-1],)[-1]:
                if tile.fg_id != DIAMOND_REGAL_STAIRS:
                    return 0
                v15 = tile_should_connect(world, tile.pos.x, tile.pos.y - 1, DIAMOND_REGAL_BANNISTER, 0)
                result = 4
                if not v15:
                    return 0
        else:
            result = 3
            if v8:
                if (tile.fg_id != REGAL_STAIRS or ((v16 := tile_should_connect(world, tile.pos.x, tile.pos.y - 1, REGAL_BANNISTER, 0)), (result := 5), not v16)[-1],)[-1]:
                    if tile.fg_id != DIAMOND_REGAL_STAIRS:
                        return 2
                    v17 = tile_should_connect(world, tile.pos.x, tile.pos.y - 1, DIAMOND_REGAL_BANNISTER, 0)
                    result = 5
                    if not v17:
                        return 2
    return result


def handle_smart_cling2_connection(world: World, tile: Tile, mode: int, /) -> int:
    x: int = 0
    y: int = 0
    v5: int = 0
    bg_id: int = 0
    v7: bool | int = False
    v8: bool | int = False
    fg_or_bg: int = 0
    v10: int = 0
    v11: int = 0
    v12: int = 0
    v13: bool | int = False
    v14: int = 0
    v15: bool | int = False
    v16: bool | int = False
    v17: int = 0
    v18: bool | int = False
    should_connect: bool | int = False
    v21: bool | int = False
    x = tile.pos.x
    y = tile.pos.y
    v5 = x + 1
    if mode:
        bg_id = tile.bg_id
        should_connect = tile_bg_equal(world, v5, y, bg_id, 0)
        v21 = tile_bg_equal(world, x, y + 1, bg_id, 1)
        v7 = tile_bg_equal(world, x - 1, y, bg_id, 0)
        v8 = tile_bg_equal(world, x, y - 1, bg_id, 2)
    else:
        fg_or_bg = tile.fg_id
        should_connect = tile_should_connect(world, v5, y, fg_or_bg, 0)
        v10 = tile.fg_id
        v21 = tile_should_connect(world, x, y + 1, v10, 1)
        v11 = tile.fg_id
        v7 = tile_should_connect(world, x - 1, y, v11, 0)
        v12 = tile.fg_id
        v8 = tile_should_connect(world, x, y - 1, v12, 2)
    v13 = v21 and should_connect
    if (v7 and v21) and should_connect:
        return ((not v8 or not v7) or not v21) or not should_connect
    else:
        v14 = 2
        if (not v8 or not v7) or not should_connect:
            v14 = 3
            if not v8 or not v13:
                v15 = (v8 and v7) and v21
                v16 = (v15 or v13) or (v7 and should_connect)
                v17 = 8 * (not v13) + 5
                v18 = not v15
                v14 = 4
                if v18:
                    v14 = v17
                if not v16:
                    if v8 and should_connect or (v7 and v21):
                        return (v8 and should_connect) | 6
                    else:
                        v14 = 9
                        if not v8 or not v21:
                            v14 = 8
                            if not v8 or not v7:
                                v14 = 4 * should_connect + 10
                            if ((not v8 or not v7) and (not should_connect)) and (not v21):
                                v14 = 15
                                if not v7:
                                    return 12 - v8
    return v14


def handle_random_seed_connection(world: World, tile: Tile, mode: int, /) -> int:
    x: int = 0
    y: int = 0
    v5: int = 0
    bg_id: int = 0
    can_connect: int = 0
    v8: int = 0
    v9: bool | int = False
    v10: int = 0
    fg_or_bg: int = 0
    v12: int = 0
    v13: int = 0
    v14: int = 0
    v15: int = 0
    result: int = 0
    x = tile.pos.x
    y = tile.pos.y
    if mode:
        v5 = (tile.flags & TileFlags.FLIPPED_X) >> 5
        bg_id = tile.bg_id
        can_connect = bg_can_connect(world, tile.pos.x, y - 1, bg_id, v5)
        v8 = bg_id
        v9 = can_connect
        v10 = bg_can_connect(world, x, y + 1, v8, v5)
    else:
        fg_or_bg = tile.fg_id
        v9 = fg_can_connect(world, x, y - 1, fg_or_bg, (tile.flags & TileFlags.FLIPPED_X) >> 5)
        v12 = tile.pos.x
        v13 = tile.pos.y + 1
        v14 = tile.fg_id
        v10 = fg_can_connect(world, v12, v13, v14, (tile.flags & TileFlags.FLIPPED_X) >> 5)
    v15 = v10
    result = v10 ^ 3
    if v9:
        return v15
    return result


def handle_random_connection(world: World, tile: Tile, mode: int, /) -> int:
    x: int = 0
    y: int = 0
    v5: int = 0
    bg_id: int = 0
    should_connect: bool | int = False
    v8: bool | int = False
    fg_or_bg: int = 0
    v10: int = 0
    v11: int = 0
    v12: int = 0
    v13: bool | int = False
    result: int = 0
    x = tile.pos.x
    y = tile.pos.y
    v5 = y - 1
    if mode:
        bg_id = tile.bg_id
        should_connect = tile_bg_equal(world, tile.pos.x, v5, bg_id, 0)
        v8 = tile_bg_equal(world, x, y + 1, bg_id, 0)
    else:
        fg_or_bg = tile.fg_id
        should_connect = tile_should_connect(world, x, v5, fg_or_bg, 2)
        v10 = tile.pos.x
        v11 = tile.pos.y + 1
        v12 = tile.fg_id
        v8 = tile_should_connect(world, v10, v11, v12, 1)
    v13 = v8
    result = v8 ^ 3
    if should_connect:
        return v13
    return result


def handle_smart_edge_diagon_connection(world: World, tile: Tile, mode: int, /) -> int:
    flags: int = 0
    x: int = 0
    y: int = 0
    v6: int = 0
    v7: int = 0
    bg_id: int = 0
    can_connect: int = 0
    v10: int = 0
    v11: int = 0
    v12: int = 0
    v13: int = 0
    fg_or_bg: int = 0
    v15: int = 0
    v16: World | None = None
    v17: int = 0
    v18: int = 0
    v19: int = 0
    v20: int = 0
    v21: int = 0
    result: int = 0
    flags = tile.flags
    x = tile.pos.x
    y = tile.pos.y
    v6 = y + 1
    if mode:
        v7 = y - 1
        bg_id = tile.bg_id
        if flags & 32 != 0:
            can_connect = bg_can_connect(world, x + 1, v6, bg_id, 1)
            v10 = x - 1
            v11 = v7
            v12 = bg_id
            v13 = 1
        else:
            can_connect = bg_can_connect(world, x - 1, v6, bg_id, 0)
            v10 = x + 1
            v11 = v7
            v12 = bg_id
            v13 = 0
        v18 = bg_can_connect(world, v10, v11, v12, v13)
    else:
        fg_or_bg = tile.fg_id
        v15 = (tile.flags & TileFlags.FLIPPED_X) >> 5
        if flags & TileFlags.FLIPPED_X != 0:
            v16 = world
            can_connect = fg_can_connect(world, x + 1, v6, fg_or_bg, v15)
            v17 = tile.pos.x - 1
        else:
            v16 = world
            can_connect = fg_can_connect(world, x - 1, v6, fg_or_bg, v15)
            v17 = tile.pos.x + 1
        v19 = tile.pos.y - 1
        v20 = tile.fg_id
        v18 = fg_can_connect(v16, v17, v19, v20, (tile.flags & TileFlags.FLIPPED_X) >> 5)
    v21 = 3 * (v18 ^ 1)
    result = 2 - v18
    if not can_connect:
        return v21
    return result


def handle_smart_edge_vert_connection(world: World, tile: Tile, mode: int, /) -> int:
    x: int = 0
    v6: int = 0
    v7: int = 0
    y: int = 0
    width: int = 0
    v10: bool | int = False
    v11: int = 0
    fg_or_bg: int = 0
    v13: int = 0
    v15: int = 0
    v16: int = 0
    v17: int = 0
    v18: int = 0
    v19: int = 0
    bg_id: int = 0
    v21: bool | int = False
    v22: int = 0
    v23: int = 0
    v24: int = 0
    v25: int = 0
    v26: bool | int = False
    result: int = 0
    v28: bool | int = False
    v29: bool | int = False
    should_connect: bool | int = False
    x = tile.pos.x
    v6 = x
    v7 = x + 1
    y = tile.pos.y
    width = world.width
    v10 = 1
    if width <= v7 or world.height <= y:
        v29 = 1
    else:
        v11 = mode
        t = world.get_tile(v7 + y * width)
        if t:
            fg_or_bg = t.fg_id
            mode = v11
            v29 = fg_or_bg != CAVE_DIRT
            x = tile.pos.x
            y = tile.pos.y
            v6 = x
    if x:
        v13 = world.width
        if v13 >= v6 and world.height > y:
            t = world.get_tile(v6 - 1 + y * v13)
            if t:
                v15 = mode
                v16 = t.fg_id
                mode = v15
                v10 = v16 != CAVE_DIRT
    v28 = v10
    v17 = tile.pos.x
    v18 = v17 + 1
    v19 = tile.pos.y
    if mode:
        bg_id = tile.bg_id
        should_connect = tile_bg_equal(world, v18, v19, bg_id, 0)
        v21 = tile_bg_equal(world, v17 - 1, v19, bg_id, 0)
    else:
        v22 = tile.fg_id
        should_connect = tile_should_connect(world, v18, v19, v22, 0)
        v23 = tile.pos.x - 1
        v24 = tile.pos.y
        v25 = tile.fg_id
        v21 = tile_should_connect(world, v23, v24, v25, 0)
        v17 = tile.pos.x
        v19 = tile.pos.y
    v26 = tile_should_connect(world, v17, v19 + 1, CAVE_COLUMN, 0)
    result = 9
    if not v26:
        if v28:
            if v29:
                result = 1
                if not v21 or not should_connect:
                    result = 0
                    if not should_connect:
                        return v21 ^ 3
            else:
                return 3 * (not v21) + 5
        else:
            result = 6
            if v29:
                return 3 * (not should_connect) + 4
    return result


def handle_smart_cling_connection(world: World, tile: Tile, _a3: int) -> int:
    # idk why this texture is not handled with the other types
    def should_connect(x: int, y: int) -> bool:
        if not (0 <= x < world.width and 0 <= y < world.height):
            return False
        neighbor = world.get_tile(ivec2(x, y))
        if not neighbor or neighbor.fg_id == 0:
            return False

        item = item_database.get(neighbor.fg_id)

        if item.collision_type == ItemInfoCollisionType.COLLIDE_IF_OFF and neighbor.flags & TileFlags.IS_ON == 0:
            return True

        if item.collision_type == ItemInfoCollisionType.COLLIDE_IF_ON and neighbor.flags & TileFlags.IS_ON != 0:
            return True

        return item_database.get(neighbor.fg_id).collision_type == ItemInfoCollisionType.FULL

    x, y = tile.pos.x, tile.pos.y

    checks = [
        (3, x, y + 1),  # bottom
        (1, x, y - 1),  # top
        (0, x - 1, y),  # left
        (2, x + 1, y),  # right
    ]

    for texture, nx, ny in checks:
        if should_connect(nx, ny):
            return texture

    return 4
