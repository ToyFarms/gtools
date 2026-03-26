import inspect
import logging
import os
import pickle
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any, ClassVar, Hashable, Literal, Sequence, overload

import xxhash
from rapidfuzz import fuzz, process
from zmq import IntFlag

from gtools import setting
from gtools.core.buffer import Buffer
from gtools.core.wsl import windows_home

if not os.environ.get("NO_BAKED", None):
    from gtools.baked import items


class WeatherType(IntEnum):
    DEFAULT = 0
    SUNSET = 1
    NIGHT = 2
    DESERT = 3
    SUNNY = 4
    RAINY_CITY = 5
    HARVEST = 6
    MARS = 7
    SPOOKY = 8
    MAW = 9
    BLANK = 10
    SNOWY = 11
    GROWCH = 12
    GROWCH_HAPPY = 13
    UNDERSEA = 14
    WARP = 15
    COMET = 16
    COMET2 = 17
    PARTY = 18
    PINEAPPLE = 19
    SNOWY_NIGHT = 20
    SPRING = 21
    WOLF = 22
    NOT_INITIALIZED = 23
    PURPLE_HAZE = 24
    FIRE_HAZE = 25
    GREEN_HAZE = 26
    AQUA_HAZE = 27
    CUSTOM_HAZE = 28
    CUSTOM_ITEMS = 29
    PAGODA = 30
    APOCALYPSE = 31
    JUNGLE = 32
    BALLOON_WARZ = 33
    BACKGROUND = 34
    AUTUMN = 35
    HEART = 36
    STPATRICKS = 37
    ICE_AGE = 38
    VOLCANO = 39
    FLOATING_ISLANDS = 40
    MASCOT = 41
    DIGITAL_RAIN = 42
    MONOCHROME = 43
    TREASURE = 44
    SURGERY = 45
    BOUNTIFUL = 46
    METEOR = 47
    STARS = 48
    ASCENDED = 49
    DESTROYED = 50
    GROWTOPIA_SIGN = 51
    DUNGEON = 52
    LEGENDARY_CITY = 53
    BLOOD_DRAGON = 54
    POP_CITY = 55
    ANZU = 56
    TMNT_CITY = 57
    RAD_CITY = 58
    PLAZA = 59
    NEBULA = 60
    PROTOSTAR = 61
    DARK_MOUNTAINS = 62
    AC15 = 63
    MOUNT_GROWMORE = 64
    CRACK_IN_REALITY = 65
    LNY_NIAN = 66
    RAYMAN_LOCK = 67
    STEAMPUNK = 68
    REALM_OF_SPIRITS = 69
    BLACK_HOLE = 70
    GEMS = 71
    HOLIDAY_HAVEN = 72
    FENYX_LOCK = 73
    ENCHANTED_LOCK = 74
    ROYAL_ENCHANTED_LOCK = 75
    NEPTUNES_ATLANTIS = 76
    PINUSKI_PETAL_PURRFECT_HAVEN = 77
    CANDY_LAND = 78
    DRAGONS_KEEP = 79
    EMERALD_CITY = 80
    ANCESTRAL_PLANE = 81
    BLACK_DIGITAL_RAIN = 82

    @classmethod
    def _missing_(cls, value: int) -> "WeatherType":
        obj = int.__new__(cls, value)
        obj._name_ = f"UNKNOWN_{value}"
        obj._value_ = value
        return obj


class TerraformType(IntEnum):
    DEFAULT = 0
    BEACH = 1
    DESERT = 2
    HARVEST = 3
    MARS = 4
    EMPTY = 5
    UNDERSEA = 6
    CAVE = 7
    JUNGLE = 8
    STARSHIP_IMPERIAL_HAWK = 9
    STARSHIP_IMPERIAL_VULTURE = 10
    STARSHIP_IMPERIAL_FALCON = 11
    STARSHIP_STELLARIX_STARHUNTER = 12
    STARSHIP_STELLARIX_ASSASIN = 13
    STARSHIP_STELLARIX_LEGION = 14
    STARSHIP_GREEZAK_DRAGONSTAR = 15
    STARSHIP_GREEZAK_TRIUMPH = 16
    STARSHIP_GREEZAK_PRAETORIAN = 17
    STARSHIP_HYPERTECH_ETRENAL = 18
    MONOCHROME = 19
    TREASURE = 20
    SURGERY = 21
    BOUNTIFUL = 22
    MINE = 23
    FTUE = 24
    DUNGEON_1 = 25
    DUNGEON_2 = 26
    DUNGEON_3 = 27
    DUNGEON_4 = 28
    DUNGEON_5 = 29
    STARSHIP_STARTREK = 30
    STARSHIP_STARTREK_LAND = 31
    PLAYER_FIREST_WORLD = 32
    CANDY_LAND = 33


class ItemFlag(IntFlag):
    NONE = 0
    FLIPPABLE = 1 << 0
    EDITABLE = 1 << 1
    SEEDLESS = 1 << 2
    PERMANENT = 1 << 3
    DROPLESS = 1 << 4
    NO_SELF = 1 << 5
    NO_SHADOW = 1 << 6
    WORLD_LOCKED = 1 << 7
    BETA = 1 << 8
    AUTO_PICKUP = 1 << 9
    MOD_FLAG = 1 << 10
    RANDOM_GROW = 1 << 11
    PUBLIC = 1 << 12
    FOREGROUND = 1 << 13
    HOLIDAY = 1 << 14
    UNTRADEABLE = 1 << 15


class ItemInfoType(IntEnum):
    ANY_BUT_SEED = -2 & 0xFF  # (uint8_t)-2
    ANY = -1 & 0xFF  # (uint8_t)-1
    FIST = 0
    WRENCH = 1
    USER_DOOR = 2
    LOCK = 3
    GEMS = 4
    TREASURE = 5
    DEADLY = 6
    TRAMPOLINE = 7
    CONSUMABLE = 8
    GATEWAY = 9
    SIGN = 10
    SFX_WITH_EXTRA_FRAME = 11
    BOOMBOX = 12
    DOOR = 13
    PLATFORM = 14
    BEDROCK = 15
    LAVA = 16
    NORMAL = 17
    BACKGROUND = 18
    SEED = 19
    CLOTHES = 20
    NORMAL_WITH_EXTRA_FRAME = 21
    BACKGD_SFX_EXTRA_FRAME = 22
    BACK_BOOMBOX = 23
    BOUNCY = 24
    POINTY = 25
    PORTAL = 26
    CHECKPOINT = 27
    MUSICNOTE = 28
    ICE = 29
    RACE_FLAG = 30
    SWITCHEROO = 31
    CHEST = 32
    MAILBOX = 33
    BULLETIN = 34
    PINATA = 35
    DICE = 36
    COMPONENT = 37
    PROVIDER = 38
    LAB = 39
    ACHIEVEMENT = 40
    WEATHER_MACHINE = 41
    SCOREBOARD = 42
    SUNGATE = 43
    PROFILE = 44
    DEADLY_IF_ON = 45
    HEART_MONITOR = 46
    DONATION_BOX = 47
    TOYBOX = 48
    MANNEQUIN = 49
    CAMERA = 50
    MAGICEGG = 51
    TEAM = 52
    GAME_GEN = 53
    XENONITE = 54
    DRESSUP = 55
    CRYSTAL = 56
    BURGLAR = 57
    COMPACTOR = 58
    SPOTLIGHT = 59
    WIND = 60
    DISPLAY_BLOCK = 61
    VENDING = 62
    FISHTANK = 63
    PETFISH = 64
    SOLAR = 65
    FORGE = 66
    GIVING_TREE = 67
    GIVING_TREE_STUMP = 68
    STEAMPUNK = 69
    STEAM_LAVA_IF_ON = 70
    STEAM_ORGAN = 71
    TAMAGOTCHI = 72
    SEWING = 73
    FLAG = 74
    LOBSTER_TRAP = 75
    ARTCANVAS = 76
    BATTLE_CAGE = 77
    PET_TRAINER = 78
    STEAM_ENGINE = 79
    LOCK_BOT = 80
    WEATHER_SPECIAL = 81
    SPIRIT_STORAGE = 82
    DISPLAY_SHELF = 83
    VIP_DOOR = 84
    CHAL_TIMER = 85
    CHAL_FLAG = 86
    FISH_MOUNT = 87
    PORTRAIT = 88
    WEATHER_SPECIAL2 = 89
    FOSSIL = 90
    FOSSIL_PREP = 91
    DNA_MACHINE = 92
    BLASTER = 93
    VALHOWLA = 94
    CHEMSYNTH = 95
    CHEMTANK = 96
    STORAGE = 97
    OVEN = 98
    SUPER_MUSIC = 99
    GEIGERCHARGE = 100
    ADVENTURE_RESET = 101
    TOMB_ROBBER = 102
    FACTION = 103
    RED_FACTION = 104
    GREEN_FACTION = 105
    BLUE_FACTION = 106
    ARTIFACT = 107
    TRAMPOLINE_MOMENTUM = 108
    FISHGOTCHI_TANK = 109
    FISHING_BLOCK = 110
    ITEM_SUCKER = 111
    ITEM_PLANTER = 112
    ROBOT = 113
    COMMAND = 114
    LUCKY_TICKET = 115
    STATS_BLOCK = 116
    FIELD_NODE = 117
    OUIJA_BOARD = 118
    ARCHITECT_MACHINE = 119
    STARSHIP = 120
    AUTODELETE = 121
    BOOMBOX2 = 122
    AUTO_ACTION_BREAK = 123
    AUTO_ACTION_HARVEST = 124
    AUTO_ACTION_HARVEST_SUCK = 125
    LIGHTNING_CLOUD = 126
    PHASED_BLOCK = 127
    MUD = 128
    ROOT_CUTTING = 129
    PASSWORD_STORAGE = 130
    PHASED_BLOCK2 = 131
    BOMB = 132
    PVE_NPC = 133
    INFINITY_WEATHER_MACHINE = 134
    SLIME = 135
    ACID = 136
    COMPLETIONIST = 137
    PUNCH_TOGGLE = 138
    ANZU_BLOCK = 139
    FEEDING_BLOCK = 140
    KRANKENS_BLOCK = 141
    FRIENDS_ENTRANCE = 142
    PEARLS = 143

    @classmethod
    def _missing_(cls, value: int) -> "ItemInfoType":
        obj = int.__new__(cls, value)
        obj._name_ = f"UNKNOWN_{value}"
        obj._value_ = value
        return obj


class ItemInfoMaterialType(IntEnum):
    WOODEN = 0
    GLASS = 1
    ROCK = 2
    METAL = 3

    @classmethod
    def _missing_(cls, value: int) -> "ItemInfoMaterialType":
        obj = int.__new__(cls, value)
        obj._name_ = f"UNKNOWN_{value}"
        obj._value_ = value
        return obj


class ItemInfoVisualEffect(IntEnum):
    NONE = 0
    FLAME_LICK = 1
    SMOKING = 2
    GLOW_TINT1 = 3
    ANIM = 4
    BUBBLES = 5
    PET = 6
    PET_ANIM = 7
    NO_ARMS = 8
    WAVEY = 9
    WAVEY_ANIM = 10
    BOTHARMS = 11
    LOWHAIR = 12
    UNDERFACE = 13
    SKINTINT = 14
    MASK = 15
    ANIM_MASK = 16
    LOWHAIR_MASK = 17
    GHOST = 18
    BUBBLE_MACHINE = 46
    PULSE = 19
    COLORIZE = 20
    COLORIZE_TO_SHIRT = 21
    COLORIZE_ANIM = 22
    HIGHFACE = 23
    HIGHFACE_ANIM = 24
    RAINBOW_SHIFT = 25
    BACKFORE = 26
    COLORIZE_WITH_SKIN = 27
    NO_RENDER = 28
    SPIN = 29
    OFFHAND = 30
    WINGED = 31
    SINK = 32
    DARKNESS = 33
    LIGHTSOURCE = 34
    LIGHT_IF_ON = 35
    DISCOLOR = 36
    STEP_SPIN = 37
    PETCOLORED = 38
    SILKFOOT = 39
    TILTY = 40
    TILTY_DARK = 41
    NEXT_FRAME_IF_ON = 42
    WOBBLE = 43
    SCROLL = 44
    LIGHTSOURCE_PULSE = 45
    VERYLOWHAIR = 47
    VERYLOWHAIR_MASK = 48


class ItemInfoTextureType(IntEnum):
    SINGLE_FRAME_ALONE = 0
    SINGLE_FRAME = 1
    SMART_EDGE = 2
    SMART_EDGE_HORIZ = 3
    SMART_CLING = 4
    SMART_CLING2 = 5
    SMART_OUTER = 6
    RANDOM = 7
    SMART_EDGE_VERT = 8
    SMART_EDGE_HORIZ_CAVE = 9
    SMART_EDGE_DIAGON = 10


class ItemInfoCollisionType(IntEnum):
    NONE = 0
    FULL = 1
    JUMP_THROUGH = 2
    GATEWAY = 3
    COLLIDE_IF_OFF = 4
    ONE_WAY = 5
    VIP_DOOR = 6
    JUMP_DOWN = 7
    ADVENTURE = 8
    COLLIDE_IF_ON = 9
    FACTION = 10
    GUILD = 11
    CLOUD = 12
    FRIEND_ENTRANCE = 13


class ItemInfoClothingType(IntEnum):
    NONE = 0
    SHIRT = 1
    PANTS = 2
    SHOES = 3
    FACE = 4
    HAND = 5
    BACK = 6
    HAIR = 7
    NECK = 8
    ARTIFACTS = 9


class ItemInfoSeedBase(IntEnum):
    NONE = 0
    SHADE_UPPER = 1
    EMPTY = 2
    ROUGH = 3
    LINES = 4
    EMPTY2 = 5
    ROUGH2 = 6
    ROUGH3 = 7
    LINES2 = 8
    CIRCLE_CENTER = 9
    CIRCLE_CENTER2 = 10
    EMPTY3 = 11
    DARK_BOTTOM = 12
    SHADE_TOP = 13
    EMPTY4 = 14
    CRACKED = 15


class ItemInfoSeedOverlay(IntEnum):
    LINES = 0
    STRIPEY = 2
    POLKA_DOT = 4
    SHADE_HALF = 6
    CROSS = 8
    JAGGED_LINE = 10
    WAVEY_LINES = 12
    DIAGONAL_LINES = 14


class ItemInfoTreeBase(IntEnum):
    BRANCH_TREE = 0
    ROOTS = 1
    ROOTS2 = 2
    BIG_TRUNK = 3
    BRANCH_TREE2 = 4
    NO_ROOTS = 5
    BENT_SLIGHTLY = 6
    VINE_LIKE_PLANT = 7


class ItemInfoTreeLeaves(IntEnum):
    FLAT_LEAVES = 0
    BIG_TRIANGULAR_LEAVES = 2
    BIG_CIRCLE_LEAVES = 4
    CIRCULAR_LEAVES = 6


@dataclass(slots=True, init=False)
class ItemInfoColor:
    a: int = 0
    r: int = 0
    g: int = 0
    b: int = 0

    def __init__(self, x: int = 0) -> None:
        self.b = (x >> 24) & 0xFF
        self.g = (x >> 16) & 0xFF
        self.r = (x >> 8) & 0xFF
        self.a = x & 0xFF

    def __int__(self) -> int:
        return ((self.b & 0xFF) << 24) | ((self.g & 0xFF) << 16) | ((self.r & 0xFF) << 8) | (self.a & 0xFF)


class FXFlags(IntFlag):
    NONE = 0
    MULTI_ANIM_START = 1 << 0
    MULTI_ANIM2_START = 1 << 1
    PING_PONG_ANIM_START = 1 << 2
    OVERLAY_OBJECT = 1 << 3
    RENDER_F_X_VARIANT_VERSION = 1 << 4
    OFFSET_UP = 1 << 5
    DUAL_LAYER = 1 << 6
    USE_SKIN_TINT = 1 << 7
    SEED_TINT_LAYER1 = 1 << 8
    SEED_TINT_LAYER2 = 1 << 9
    RAINBOW_TINT_LAYER1 = 1 << 10
    RAINBOW_TINT_LAYER2 = 1 << 11
    GLOW = 1 << 12
    NO_ARMS = 1 << 13
    RENDER_OFF_HAND = 1 << 14
    FRONT_ARM_PUNCH = 1 << 15
    SLOW_FALL_OBJECT = 1 << 16
    REPLACEMENT_SPRITE = 1 << 17
    ORB_FLOAT = 1 << 18


class ItemInfoFlag2(IntFlag):
    NONE = 0
    ROBOT_DEADLY = 1 << 0
    ROBOT_SHOOT_LEFT = 1 << 1
    ROBOT_SHOOT_RIGHT = 1 << 2
    ROBOT_SHOOT_DOWN = 1 << 3
    ROBOT_SHOOT_UP = 1 << 4
    ROBOT_CAN_SHOOT = 1 << 5
    ROBOT_LAVA = 1 << 6
    ROBOT_POINTY = 1 << 7
    ROBOT_SHOOT_DEADLY = 1 << 8
    GUILD_ITEM = 1 << 9
    GUILD_FLAG = 1 << 10
    STARSHIP_HELM = 1 << 11
    STARSHIP_REACTOR = 1 << 12
    STARSHIP_VIEWSCREEN = 1 << 13
    SUPER_MOD = 1 << 14
    TILE_DEADLY_IF_ON = 1 << 15
    LONG_HAND_ITEM64x32 = 1 << 16
    GEMLESS = 1 << 17
    CLOTHES_TRANSMUTABLE = 1 << 18
    ILLEGAL = 1 << 19
    ILLEGAL_INVENTORY_FLOAT = 1 << 20
    ILLEGAL_WORLD = 1 << 21
    UNUSED = 1 << 22
    ONE_IN_WORLD = 1 << 23
    ONLY_FOR_WORLD_OWNER = 1 << 24
    NO_UPGRADE = 1 << 25
    EXTINGUISH_FIRE = 1 << 26
    EXTINGUISH_FIRE_NO_DAMAGE = 1 << 27
    NEED_RECEPTION_DESK = 1 << 28


_SECRET = b"PBG892FXX982ABC*"


def _decrypt(s: bytes, item_id: int) -> bytes:
    return bytes(s[i] ^ _SECRET[(i + item_id) % len(_SECRET)] for i in range(len(s)))


TEXTURE_WITH_ICONS_VARIANT: dict[bytes, str] = {
    b"bf_begchmp.rttex": "bf_begchmp_icon.rttex",
    b"comhr.rttex": "comhr_icon.rttex",
    b"d_aura.rttex": "d_aura_icon.rttex",
    b"es_egchmp.rttex": "es_egchmp_icon.rttex",
    b"io_rif.rttex": "io_rif_icon.rttex",
    b"io_rif_wing.rttex": "io_rif_wing_icon.rttex",
    b"mi_minbot.rttex": "mi_minbot_icon.rttex",
    b"player_chestitem2.rttex": "player_chestitem2_icon.rttex",
    b"player_chestitem.rttex": "player_chestitem_icon.rttex",
    b"player_cosmetics1.rttex": "player_cosmetics1_icon.rttex",
    b"player_cosmetics2.rttex": "player_cosmetics2_icon.rttex",
    b"player_cosmetics3.rttex": "player_cosmetics3_icon.rttex",
    b"player_cosmetics4.rttex": "player_cosmetics4_icon.rttex",
    b"player_faceitem5.rttex": "player_faceitem5_icon.rttex",
    b"player_faceitem6.rttex": "player_faceitem6_icon.rttex",
    b"player_faceitem7.rttex": "player_faceitem7_icon.rttex",
    b"player_feet10.rttex": "player_feet10_icon.rttex",
    b"player_feet11.rttex": "player_feet11_icon.rttex",
    b"player_feet12.rttex": "player_feet12_icon.rttex",
    b"player_feet13.rttex": "player_feet13_icon.rttex",
    b"player_feet14.rttex": "player_feet14_icon.rttex",
    b"player_feet15.rttex": "player_feet15_icon.rttex",
    b"player_feet16.rttex": "player_feet16_icon.rttex",
    b"player_feet2.rttex": "player_feet2_icon.rttex",
    b"player_feet3.rttex": "player_feet3_icon.rttex",
    b"player_feet4.rttex": "player_feet4_icon.rttex",
    b"player_feet5.rttex": "player_feet5_icon.rttex",
    b"player_feet6.rttex": "player_feet6_icon.rttex",
    b"player_feet7.rttex": "player_feet7_icon.rttex",
    b"player_feet8.rttex": "player_feet8_icon.rttex",
    b"player_feet9.rttex": "player_feet9_icon.rttex",
    b"player_feet.rttex": "player_feet_icon.rttex",
    b"player_feet_monthly1.rttex": "player_feet_monthly1_icon.rttex",
    b"player_hair3.rttex": "player_hair3_icon.rttex",
    b"player_hair4.rttex": "player_hair4_icon.rttex",
    b"player_hair5.rttex": "player_hair5_icon.rttex",
    b"player_hair_monthly1.rttex": "player_hair_monthly1_icon.rttex",
    b"player_handitem2.rttex": "player_handitem2_icon.rttex",
    b"player_handitem3.rttex": "player_handitem3_icon.rttex",
    b"player_handitem4.rttex": "player_handitem4_icon.rttex",
    b"player_handitem5.rttex": "player_handitem5_icon.rttex",
    b"player_handitem6.rttex": "player_handitem6_icon.rttex",
    b"player_handitem7.rttex": "player_handitem7_icon.rttex",
    b"player_handitem.rttex": "player_handitem_icon.rttex",
    b"player_hater.rttex": "player_hater_icon.rttex",
    b"player_longhanditem1.rttex": "player_longhanditem1_icon.rttex",
    b"player_longhanditem2.rttex": "player_longhanditem2_icon.rttex",
    b"player_longhanditem3.rttex": "player_longhanditem3_icon.rttex",
    b"player_longhanditem4.rttex": "player_longhanditem4_icon.rttex",
    b"player_pants2.rttex": "player_pants2_icon.rttex",
    b"player_pants3.rttex": "player_pants3_icon.rttex",
    b"player_pants_monthly1.rttex": "player_pants_monthly1_icon.rttex",
    b"player_shirt3.rttex": "player_shirt3_icon.rttex",
    b"player_shirt4.rttex": "player_shirt4_icon.rttex",
    b"player_shirt_monthly1.rttex": "player_shirt_monthly1_icon.rttex",
    b"st_caura.rttex": "st_caura_icon.rttex",
}


def is_seed(id: int) -> bool:
    return id % 2 == 1


def is_steam(item_type: ItemInfoType) -> bool:
    return item_type in (
        ItemInfoType.STEAMPUNK,
        ItemInfoType.STEAM_LAVA_IF_ON,
        ItemInfoType.STEAM_ORGAN,
    ) or id in (
        items.STEAM_DOOR,
        items.STEAM_LAUNCHER,
        items.STEAM_PIPE,
        items.SPIRIT_STORAGE_UNIT,
        items.STEAM_SPIKES,
        items.STEAM_LAMP,
    )


def is_background(item_type: ItemInfoType) -> bool:
    return item_type in (
        ItemInfoType.BACKGROUND,
        ItemInfoType.BACKGD_SFX_EXTRA_FRAME,
        ItemInfoType.BACK_BOOMBOX,
        ItemInfoType.MUSICNOTE,
    )


def get_tex_stride(texture_type: ItemInfoTextureType) -> int:
    match texture_type:
        case ItemInfoTextureType.SINGLE_FRAME_ALONE:
            return 0
        case ItemInfoTextureType.SINGLE_FRAME:
            return 0
        case ItemInfoTextureType.SMART_EDGE:
            return 8
        case ItemInfoTextureType.SMART_EDGE_HORIZ:
            return 8
        case ItemInfoTextureType.SMART_CLING:
            return 5
        case ItemInfoTextureType.SMART_CLING2:
            return 8
        case ItemInfoTextureType.SMART_OUTER:
            return 5
        case ItemInfoTextureType.RANDOM:
            return 4
        case ItemInfoTextureType.SMART_EDGE_VERT:
            return 10
        case ItemInfoTextureType.SMART_EDGE_HORIZ_CAVE:
            return 4
        case ItemInfoTextureType.SMART_EDGE_DIAGON:
            return 4


def get_default_tex(texture_type: ItemInfoTextureType) -> int:
    match texture_type:
        case ItemInfoTextureType.SINGLE_FRAME_ALONE:
            return 0
        case ItemInfoTextureType.SINGLE_FRAME:
            return 0
        case ItemInfoTextureType.SMART_EDGE:
            return 0
        case ItemInfoTextureType.SMART_EDGE_HORIZ:
            return 0
        case ItemInfoTextureType.SMART_CLING:
            return 3
        case ItemInfoTextureType.SMART_CLING2:
            return 12
        case ItemInfoTextureType.SMART_OUTER:
            return 0
        case ItemInfoTextureType.RANDOM:
            return 0
        case ItemInfoTextureType.SMART_EDGE_VERT:
            return 0
        case ItemInfoTextureType.SMART_EDGE_HORIZ_CAVE:
            return 3
        case ItemInfoTextureType.SMART_EDGE_DIAGON:
            return 0


def get_icon_texture(texture_file: bytes) -> str | None:
    return TEXTURE_WITH_ICONS_VARIANT.get(texture_file)


@dataclass(slots=True)
class Item:
    id: int = 0  # u32
    flags: ItemFlag = ItemFlag.NONE  # u16
    item_type: ItemInfoType = ItemInfoType.FIST  # u8
    material: ItemInfoMaterialType = ItemInfoMaterialType.WOODEN  # u8
    name: bytes = b""  # str with 2 bytes size prefix
    texture_file: bytes = b""  # str with 2 bytes size prefix
    texture_file_hash: int = 0  # u32
    visual_effect: ItemInfoVisualEffect = ItemInfoVisualEffect.NONE  # u8
    cooking_time: int = 0  # i32
    tex_coord_x: int = 0  # u8
    tex_coord_y: int = 0  # u8
    texture_type: ItemInfoTextureType = ItemInfoTextureType.SINGLE_FRAME_ALONE  # u8
    unk7: int = 0  # u8
    collision_type: ItemInfoCollisionType = ItemInfoCollisionType.NONE  # u8
    health: int = 0  # u8
    restore_time: int = 0  # u32
    clothing_type: ItemInfoClothingType = ItemInfoClothingType.NONE  # u8
    rarity: int = 0  # u16
    max_amount: int = 0  # u8
    extra_file: bytes = b""  # str with 2 bytes size prefix
    extra_file_hash: int = 0  # u32
    frame_interval_ms: int = 0  # u32
    pet_name: bytes = b""  # str with 2 bytes size prefix
    pet_prefix: bytes = b""  # str with 2 bytes size prefix
    pet_suffix: bytes = b""  # str with 2 bytes size prefix
    pet_ability: bytes = b""  # str with 2 bytes size prefix
    seed_base: ItemInfoSeedBase = ItemInfoSeedBase.NONE  # u8
    seed_overlay: ItemInfoSeedOverlay = ItemInfoSeedOverlay.LINES  # u8
    tree_base: ItemInfoTreeBase = ItemInfoTreeBase.BRANCH_TREE  # u8
    tree_leaves: ItemInfoTreeLeaves = ItemInfoTreeLeaves.FLAT_LEAVES  # u8
    seed_color: ItemInfoColor = field(default_factory=ItemInfoColor)  # u32
    seed_overlay_color: ItemInfoColor = field(default_factory=ItemInfoColor)  # u32
    ingredient_: int = 0  # u32
    grow_time: int = 0  # u32
    fx_flags: FXFlags = FXFlags.NONE  # u32
    animating_coordinates: bytes = b""  # str with 2 bytes size prefix
    animating_texture_files: bytes = b""  # str with 2 bytes size prefix
    animating_coordinates_2: bytes = b""  # str with 2 bytes size prefix
    unk1: int = 0  # u32  unused? all item zero
    unk2: int = 0  # u32  neon nerve, stitchlips, omegalul all 2
    flags2: ItemInfoFlag2 = ItemInfoFlag2.NONE  # u32
    cybot_related: bytes = b""  # u8 (60)
    tile_range: int = 0  # u32
    vault_capacity: int = 0  # u32
    punch_options: bytes = b""  # str with 2 bytes size prefix
    masked_body_len: int = 0  # u32  only on Haunted Jack O' Lantern with value 2, matches [4, 7, 9, 9, 9, 9, 9, 9, 9] with 2 element differing
    body_render_mask: bytes = b""  # u8 (9)  each byte represent a body part, if its not '\t' its rendered differently, such as on Haunted Jack O' Lantern
    light_range: int = 0  # u32
    unk5: int = 0  # u32
    can_sit: int = 0  # u8
    player_offset_x: int = 0  # u32
    player_offset_y: int = 0  # u32
    chair_texture_x: int = 0  # u32
    chair_texture_y: int = 0  # u32
    chair_leg_offset_x: int = 0  # i32
    chair_leg_offset_y: int = 0  # i32
    chair_texture_file: bytes = b""  # str with 2 bytes size prefix
    renderer_data_file: bytes = b""  # str with 2 bytes size prefix
    unk6: int = 0  # u32  only on Buster Brush with value 1815
    renderer_data_file_hash: int = 0  # u32
    has_alt_tile: int = 0  # u8
    alt_index_offset: int = 0  # u16
    alt_unk1: int = 0  # u32
    alt_unk2: int = 0  # u8
    alt_unk3: int = 0  # u8
    player_transform_related: int = 0  # u16
    info: bytes = b""  # str with 2 bytes size prefix
    ingredients: tuple[int, int] = field(default_factory=lambda: (0, 0))  # u16 (2)
    unk9: int = 0  # u8  only on Me11e's Snowshine with value 2

    def is_seed(self) -> bool:
        return is_seed(self.id)

    def is_steam(self) -> bool:
        return is_steam(self.item_type)

    def is_background(self) -> bool:
        return is_background(self.item_type)

    def get_tex_stride(self) -> int:
        return get_tex_stride(self.texture_type)

    def get_default_tex(self) -> int:
        return get_default_tex(self.texture_type)

    def get_icon_texture(self) -> str | None:
        return get_icon_texture(self.texture_file)

    @classmethod
    def deserialize(cls, s: Buffer, version: int = 99999999999) -> "Item":
        item = cls()

        item.id = s.read_u32()
        item.flags = ItemFlag(s.read_u16())
        item.item_type = ItemInfoType(s.read_u8())
        item.material = ItemInfoMaterialType(s.read_u8())
        item.name = _decrypt(s.read_pascal_bytes("H"), item.id)
        item.texture_file = s.read_pascal_bytes("H")
        item.texture_file_hash = s.read_u32()
        item.visual_effect = ItemInfoVisualEffect(s.read_u8())
        item.cooking_time = s.read_i32()
        item.tex_coord_x = s.read_u8()
        item.tex_coord_y = s.read_u8()
        item.texture_type = ItemInfoTextureType(s.read_u8())
        item.unk7 = s.read_u8()
        item.collision_type = ItemInfoCollisionType(s.read_u8())
        item.health = s.read_u8()
        item.restore_time = s.read_u32()
        item.clothing_type = ItemInfoClothingType(s.read_u8())
        item.rarity = s.read_u16()
        item.max_amount = s.read_u8()
        item.extra_file = s.read_pascal_bytes("H")
        item.extra_file_hash = s.read_u32()
        item.frame_interval_ms = s.read_u32()
        item.pet_name = s.read_pascal_bytes("H")
        item.pet_prefix = s.read_pascal_bytes("H")
        item.pet_suffix = s.read_pascal_bytes("H")
        item.pet_ability = s.read_pascal_bytes("H")
        item.seed_base = ItemInfoSeedBase(s.read_u8())
        item.seed_overlay = ItemInfoSeedOverlay(s.read_u8())
        item.tree_base = ItemInfoTreeBase(s.read_u8())
        item.tree_leaves = ItemInfoTreeLeaves(s.read_u8())
        item.seed_color = ItemInfoColor(s.read_u32())
        item.seed_overlay_color = ItemInfoColor(s.read_u32())
        item.ingredient_ = s.read_u32()
        item.grow_time = s.read_u32()
        item.fx_flags = FXFlags(s.read_u32())
        item.animating_coordinates = s.read_pascal_bytes("H")
        item.animating_texture_files = s.read_pascal_bytes("H")
        item.animating_coordinates_2 = s.read_pascal_bytes("H")
        item.unk1 = s.read_u32()
        item.unk2 = s.read_u32()
        item.flags2 = ItemInfoFlag2(s.read_u32())
        item.cybot_related = s.read_bytes(60)
        item.tile_range = s.read_u32()
        item.vault_capacity = s.read_u32()
        if version >= 11:
            item.punch_options = s.read_pascal_bytes("H")
        if version >= 12:
            item.masked_body_len = s.read_u32()
            item.body_render_mask = s.read_bytes(9)
        if version >= 13:
            item.light_range = s.read_u32()
        if version >= 14:
            item.unk5 = s.read_u32()
        if version >= 15:
            item.can_sit = s.read_u8()
            item.player_offset_x = s.read_u32()
            item.player_offset_y = s.read_u32()
            item.chair_texture_x = s.read_u32()
            item.chair_texture_y = s.read_u32()
            item.chair_leg_offset_x = s.read_i32()
            item.chair_leg_offset_y = s.read_i32()
            item.chair_texture_file = s.read_pascal_bytes("H")
        if version >= 16:
            item.renderer_data_file = s.read_pascal_bytes("H")
        if version >= 17:
            item.unk6 = s.read_u32()
        if version >= 18:
            item.renderer_data_file_hash = s.read_u32()
        if version >= 19:
            item.has_alt_tile = s.read_u8()
            item.alt_index_offset = s.read_u16()
            item.alt_unk1 = s.read_u32()
            item.alt_unk2 = s.read_u8()
            item.alt_unk3 = s.read_u8()
        if version >= 21:
            item.player_transform_related = s.read_i16()
        if version >= 22:
            item.info = s.read_pascal_bytes("H")
        if version >= 23:
            item.ingredients = (s.read_u16(), s.read_u16())
        if version >= 24:
            item.unk9 = s.read_u8()

        return item


_CACHE_DATE_FMT = "%Y%m%d_%H%M%S"
_log = logging.getLogger("ItemDatabase")


def _atomic_write(path: Path, obj: Any) -> None:
    fd, tmp = tempfile.mkstemp(prefix="tmp_itemdb-", suffix=".pkl", dir=str(path.parent))
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, str(path))
    finally:
        Path(tmp).unlink(missing_ok=True)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix="tmp_itemdb-", suffix=".dat", dir=str(path.parent))
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, str(path))
    finally:
        Path(tmp).unlink(missing_ok=True)


_SCHEMA_CLASSES = [
    Item,
    ItemInfoColor,
    ItemFlag,
    ItemInfoType,
    ItemInfoMaterialType,
    ItemInfoVisualEffect,
    ItemInfoTextureType,
    ItemInfoCollisionType,
    ItemInfoClothingType,
    ItemInfoSeedBase,
    ItemInfoSeedOverlay,
    ItemInfoTreeBase,
    ItemInfoTreeLeaves,
    FXFlags,
    ItemInfoFlag2,
]

_ITEMS_DAT_CANDIDATES: list[Path] = [
    windows_home() / "AppData" / "Local" / "Growtopia" / "cache" / "items.dat",
    Path(os.getenv("ITEMS", "items.dat")),
    setting.appdir / "resources" / "items.dat",
]


class ItemDatabase:
    _mem: ClassVar[dict[str, "ItemDatabase"]] = {}
    _latest_per_version: ClassVar[dict[int, "ItemDatabase"]] = {}

    _schema_hash_cache: ClassVar[str | None] = None

    def __init__(
        self,
        version: int,
        items: dict[int, Item],
        *,
        source_hash: str = "",
    ) -> None:
        self.version = version
        self.items = items
        self._source_hash = source_hash

        self._name_index: dict[bytes, Item] = {}
        self._name_str_list: list[str] = []
        self._name_str_to_items: dict[str, list[Item]] = {}
        self._name_index_built = False

    def __repr__(self) -> str:
        return f"ItemDatabase(version={self.version}, items={len(self.items)})"

    @property
    def item_count(self) -> int:
        return len(self.items)

    @classmethod
    def _schema_hash(cls) -> str:
        if cls._schema_hash_cache is None:
            combined = "\n".join(inspect.getsource(c) for c in _SCHEMA_CLASSES)
            cls._schema_hash_cache = xxhash.xxh64_hexdigest(combined.encode())

        return cls._schema_hash_cache

    def _ensure_name_index(self) -> None:
        if self._name_index_built:
            return

        for item in self.items.values():
            if not item.name:
                continue

            self._name_index.setdefault(item.name, item)
            name_str = item.name.decode()
            if name_str not in self._name_str_to_items:
                self._name_str_to_items[name_str] = []
                self._name_str_list.append(name_str)

            self._name_str_to_items[name_str].append(item)

        self._name_index_built = True

    def get(self, id: int) -> Item:
        return self.items[id]

    def get_by_name(self, name: bytes | str) -> Item:
        self._ensure_name_index()
        key = name.encode() if isinstance(name, str) else name

        try:
            return self._name_index[key]
        except KeyError:
            raise KeyError(f"no item with name {key!r}")

    @overload
    def search(
        self,
        query: bytes | str,
        n: int = ...,
        cutoff: float = ...,
        return_scores: Literal[False] = ...,
    ) -> Sequence[Item]: ...

    @overload
    def search(
        self,
        query: bytes | str,
        n: int = ...,
        cutoff: float = ...,
        return_scores: Literal[True] = ...,
    ) -> Sequence[tuple[Item, float]]: ...

    def search(
        self,
        query: bytes | str,
        n: int = 5,
        cutoff: float = 0.6,
        return_scores: bool = False,
    ) -> Sequence[tuple[Item, float]] | Sequence[Item]:
        self._ensure_name_index()
        query_str = query if isinstance(query, str) else query.decode()
        query_norm = query_str.strip().lower()

        def scorer(
            _s1: Sequence[Hashable],
            s2: Sequence[Hashable],
            score_cutoff: float | None = None,
        ) -> float:
            _ = score_cutoff
            choice = str(s2).lower()
            if query_norm == choice:
                return 100.0
            if choice.startswith(query_norm):
                return 95.0
            if f" {query_norm} " in f" {choice} ":
                return 90.0
            raw = sorted(
                [
                    fuzz.ratio(query_norm, choice) * 1.00,
                    fuzz.partial_ratio(query_norm, choice) * 0.90,
                    fuzz.token_sort_ratio(query_norm, choice) * 0.85,
                    fuzz.token_set_ratio(query_norm, choice) * 0.80,
                ],
                reverse=True,
            )
            return raw[0] * 0.50 + raw[1] * 0.30 + raw[2] * 0.15 + raw[3] * 0.05

        cutoff_pct = cutoff * 100
        seen: set[int] = set()
        results: list[tuple[Item, float]] = []

        def _collect(matches: list) -> None:
            for matched_name, score, _ in matches:
                for item in self._name_str_to_items.get(matched_name, []):
                    if item.id in seen:
                        continue
                    results.append((item, score / 100.0))
                    seen.add(item.id)
                    if len(results) >= n:
                        return

        primary = process.extract(
            query_str,
            self._name_str_list,
            scorer=scorer,
            score_cutoff=cutoff_pct,
            limit=n * 3,
        )
        _collect(primary)

        if len(results) < n:
            already_matched = {m[0] for m in primary}
            secondary = process.extract(
                query_str,
                [name for name in self._name_str_list if name not in already_matched],
                scorer=scorer,
                score_cutoff=max(cutoff_pct * 0.7, 30.0),
                limit=n * 2,
            )
            _collect(secondary)

        results.sort(key=lambda x: x[1], reverse=True)
        results = results[:n]
        return results if return_scores else [item for item, _ in results]

    def _cache_dir(self, base: Path | None = None) -> Path:
        return (base or setting.appdir / "item_database") / f"v{self.version}"

    def save_cache(self, base_dir: Path | None = None) -> None:
        if not self._source_hash:
            _log.warning("save_cache: no source hash, skipping")
            return

        dir_ = self._cache_dir(base_dir)
        dir_.mkdir(parents=True, exist_ok=True)
        if next(dir_.glob(f"*_{self._source_hash}.pkl"), None):
            _log.debug("cache already present, skipping write")
            return

        filename = f"{datetime.now(timezone.utc).strftime(_CACHE_DATE_FMT)}" f"_{self._source_hash}.pkl"
        try:
            _atomic_write(dir_ / filename, {"schema": self._schema_hash(), "db": self})
            _log.info("wrote cache %s  version=%d", filename, self.version)
        except Exception as e:
            _log.error("failed writing cache %s: %s", filename, e)

    def archive_source(self, data: bytes, base_dir: Path | None = None) -> None:
        if not self._source_hash:
            return

        dir_ = self._cache_dir(base_dir)
        dir_.mkdir(parents=True, exist_ok=True)
        if next(dir_.glob(f"*_{self._source_hash}.dat"), None):
            return

        filename = f"{datetime.now(timezone.utc).strftime(_CACHE_DATE_FMT)}" f"_{self._source_hash}.dat"

        try:
            _atomic_write_bytes(dir_ / filename, data)
            _log.info("archived items.dat v%d → %s", self.version, filename)
        except Exception as e:
            _log.error("archive failed %s: %s", filename, e)

    @classmethod
    def _try_load_disk_cache(
        cls,
        source_hash: str,
        version: int,
        base_dir: Path | None = None,
    ) -> "ItemDatabase | None":
        dir_ = (base_dir or setting.appdir / "item_database") / f"v{version}"
        if not dir_.is_dir():
            return None

        for path in sorted(dir_.glob(f"*_{source_hash}.pkl"), reverse=True):
            try:
                with path.open("rb") as f:
                    payload = pickle.load(f)
                stored_schema = payload.get("schema") if isinstance(payload, dict) else None
                db = payload.get("db") if isinstance(payload, dict) else payload
                if stored_schema != cls._schema_hash():
                    _log.info("schema mismatch, invalidating %s", path)
                    path.unlink(missing_ok=True)
                    continue
                if not isinstance(db, ItemDatabase) or db.version != version:
                    continue
                cls._mem[source_hash] = db
                cls._latest_per_version[version] = db
                _log.info("loaded disk cache %s", path.name)

                return db
            except Exception as e:
                _log.error("corrupt cache %s: %s – removing", path, e)
                path.unlink(missing_ok=True)

        return None

    @classmethod
    def deserialize(cls, data: bytes) -> "ItemDatabase":
        s = Buffer(data)
        version = s.read_u16()
        item_count = s.read_u32()
        parsed: dict[int, Item] = {}

        for _ in range(item_count):
            item = Item.deserialize(s, version)
            parsed[item.id] = item

        source_hash = xxhash.xxh64_hexdigest(data)
        return cls(version=version, items=parsed, source_hash=source_hash)

    @classmethod
    def load(cls, source: str | Path | bytes, *, cached: bool = False, cache_base_dir: Path | None = None) -> "ItemDatabase":
        if isinstance(source, bytes):
            data, source_path = source, None
        else:
            source_path = Path(source)
            data = source_path.read_bytes()

        source_hash = xxhash.xxh64_hexdigest(data)

        # in-memory hit.
        if (hit := cls._mem.get(source_hash)) is not None:
            return hit

        # disk-cache hit
        if cached:
            version = int.from_bytes(data[:2], "little")
            if (hit := cls._try_load_disk_cache(source_hash, version, cache_base_dir)) is not None:
                return hit

        # deserialize
        db = cls.deserialize(data)
        cls._mem[source_hash] = db
        cls._latest_per_version[db.version] = db

        if cached:
            db.save_cache(cache_base_dir)
            db.archive_source(data, cache_base_dir)

        return db

    @classmethod
    def latest(cls, cache_base_dir: Path | None = None) -> "ItemDatabase":
        for path in _ITEMS_DAT_CANDIDATES:
            if not path.is_file() or path.stat().st_size == 0:
                continue
            try:
                db = cls.load(path, cached=True, cache_base_dir=cache_base_dir)
                _log.info("latest: loaded from %s (v%d)", path, db.version)
                return db
            except Exception as e:
                _log.error("latest: failed loading %s: %s", path, e)

        raise FileNotFoundError("no valid items.dat found. checked: " + ", ".join(str(p) for p in _ITEMS_DAT_CANDIDATES))

    @classmethod
    def for_version(
        cls,
        version: int,
        cache_base_dir: Path | None = None,
    ) -> "ItemDatabase":
        if (hit := cls._latest_per_version.get(version)) is not None:
            return hit

        dir_ = (cache_base_dir or setting.appdir / "item_database") / f"v{version}"
        if not dir_.is_dir():
            raise ValueError(f"no cached database for version {version}")

        for path in sorted(dir_.glob("*.pkl"), reverse=True):
            try:
                with path.open("rb") as f:
                    payload = pickle.load(f)
                stored_schema = payload.get("schema") if isinstance(payload, dict) else None
                db = payload.get("db") if isinstance(payload, dict) else payload
                if stored_schema != cls._schema_hash():
                    _log.info("schema mismatch, invalidating %s", path)
                    path.unlink(missing_ok=True)
                    continue
                if not isinstance(db, ItemDatabase) or db.version != version:
                    continue
                cls._mem[db._source_hash] = db
                cls._latest_per_version[version] = db
                _log.info("for_version(%d): loaded from %s", version, path.name)
                return db
            except Exception as e:
                _log.error("corrupt cache %s: %s – removing", path, e)
                path.unlink(missing_ok=True)

        raise ValueError(f"no valid cached database for version {version}")

    @classmethod
    def has_version(cls, version: int, cache_base_dir: Path | None = None) -> bool:
        if version in cls._latest_per_version:
            return True

        dir_ = (cache_base_dir or setting.appdir / "item_database") / f"v{version}"
        return dir_.is_dir() and any(p.is_file() for p in dir_.iterdir())


item_database = ItemDatabase.latest()
