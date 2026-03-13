from dataclasses import dataclass, field
from datetime import datetime, timezone
from rapidfuzz import fuzz, process
from enum import IntEnum
import logging
import os
from pathlib import Path
import pickle
import tempfile
from typing import Any, Hashable, Literal, Sequence, overload
import inspect

import xxhash
from zmq import IntFlag

from gtools.core.wsl import windows_home

if not os.environ.get("NO_BAKED", None):
    from gtools.baked import items
from gtools.core.buffer import Buffer
from gtools import setting


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


SECRET = b"PBG892FXX982ABC*"


def _decrypt(s: bytes, item_id: int) -> bytes:
    chars = bytearray()
    for i in range(len(s)):
        xor = SECRET[(i + item_id) % len(SECRET)]
        chars.append((s[i] ^ xor))

    return bytes(chars)


TEXTURE_WITH_ICONS_VARIANT = {
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
        return self.id % 2 == 1

    def is_steam(self) -> bool:
        return self.item_type in (
            ItemInfoType.STEAMPUNK,
            ItemInfoType.STEAM_LAVA_IF_ON,
            ItemInfoType.STEAM_ORGAN,
        ) or self.id in (
            items.STEAM_DOOR,
            items.STEAM_LAUNCHER,
            items.STEAM_PIPE,
            items.SPIRIT_STORAGE_UNIT,
            items.STEAM_SPIKES,
            items.STEAM_LAMP,
        )

    def is_background(self) -> bool:
        return self.item_type in (
            ItemInfoType.BACKGROUND,
            ItemInfoType.BACKGD_SFX_EXTRA_FRAME,
            ItemInfoType.BACK_BOOMBOX,
            ItemInfoType.MUSICNOTE,
        )

    def get_tex_stride(self) -> int:
        match self.texture_type:
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

    def get_default_tex(self) -> int:
        match self.texture_type:
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
                return 0
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

    def get_icon_texture(self) -> str | None:
        return TEXTURE_WITH_ICONS_VARIANT.get(self.texture_file)

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


@dataclass
class ItemDatabase:
    version: int
    item_count: int
    items: dict[int, Item]


class item_database:
    _db: ItemDatabase | None = None
    _date_fmt = "%Y%m%d_%H%M%S"
    _schema_hash_cache: str | None = None
    logger = logging.getLogger("item_database")

    # TODO: i think version is not only the version number, but the content needs to be factored in
    _version_cache: dict[int, ItemDatabase] = {}
    _name_index_cache: dict[int, dict[bytes, Item]] = {}
    _name_str_list_cache: dict[int, list[str]] = {}
    _name_str_to_items_cache: dict[int, dict[str, list[Item]]] = {}

    @classmethod
    def _schema_hash(cls) -> str:
        if cls._schema_hash_cache is not None:
            return cls._schema_hash_cache

        schema_classes = [
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
        combined = "\n".join(inspect.getsource(c) for c in schema_classes)
        cls._schema_hash_cache = xxhash.xxh64_hexdigest(combined.encode())
        return cls._schema_hash_cache

    @classmethod
    def _atomic_write(cls, path: Path, obj: Any) -> None:
        fd, tmp = tempfile.mkstemp(prefix="tmp_itemdb-", suffix=".pkl", dir=str(path.parent))
        os.close(fd)
        try:
            with open(tmp, "wb") as f:
                pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, str(path))
        finally:
            try:
                if Path(tmp).exists():
                    Path(tmp).unlink()
            except Exception:
                pass

    @classmethod
    def _atomic_write_bytes(cls, path: Path, data: bytes) -> None:
        fd, tmp = tempfile.mkstemp(prefix="tmp_itemdb-", suffix=".dat", dir=str(path.parent))
        os.close(fd)
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, str(path))
        finally:
            try:
                if Path(tmp).exists():
                    Path(tmp).unlink()
            except Exception:
                pass

    @classmethod
    def db(cls) -> ItemDatabase:
        if not cls._db:
            candidate: list[Path] = [
                windows_home() / "AppData" / "Local" / "Growtopia" / "cache" / "items.dat",
                Path(os.getenv("ITEMS", "items.dat")),
                setting.appdir / "resources" / "items.dat",
            ]
            for path in candidate:
                if not path.is_file() or path.stat().st_size == 0:
                    continue

                try:
                    cls._db = cls.deserialize(path)
                    cls.logger.info(f"using items.dat from {path}")
                    break
                except Exception as e:
                    cls.logger.error(f"failed parsing items.dat: {e}")

        if not cls._db:
            raise ValueError("no valid items.dat found")

        return cls._db

    @classmethod
    def _save_cache(cls, hash: str, db: ItemDatabase, source_path: Path | None = None, source_bytes: bytes | None = None) -> None:
        version_dir = setting.appdir / "item_database" / f"v{db.version}"
        version_dir.mkdir(parents=True, exist_ok=True)

        existing = next(version_dir.glob(f"*_{hash}.pkl"), None)
        if existing is not None:
            cls._version_cache[db.version] = db
            cls.logger.debug(f"cache file already exists: {existing}")
            cls._build_name_index(db)
        else:
            filename = f"{datetime.now(timezone.utc).strftime(cls._date_fmt)}_{hash}.pkl"
            try:
                cls._atomic_write(version_dir / filename, {"schema": cls._schema_hash(), "db": db})
                cls._version_cache[db.version] = db
                cls.logger.info(f"wrote cache {filename} version={db.version}")
                cls._build_name_index(db)
            except Exception as e:
                cls.logger.error(f"failed saving cache {filename}: {e}")

        # archive items.dat
        data_to_archive: bytes | None = None
        if source_bytes is not None:
            data_to_archive = source_bytes
        elif source_path is not None and source_path.is_file():
            try:
                data_to_archive = source_path.read_bytes()
            except Exception as e:
                cls.logger.error(f"failed reading source_path for archive {source_path}: {e}")
                data_to_archive = None

        if data_to_archive is not None:
            existing_dat = next(version_dir.glob(f"*_{hash}.dat"), None)
            if existing_dat is not None:
                cls.logger.debug(f"archive file already exists: {existing_dat}")
            else:
                dat_filename = f"{datetime.now(timezone.utc).strftime(cls._date_fmt)}_{hash}.dat"
                try:
                    cls._atomic_write_bytes(version_dir / dat_filename, data_to_archive)
                    cls.logger.info(f"archived items.dat version {db.version} at {version_dir / dat_filename}")
                except Exception as e:
                    cls.logger.error(f"archive failed {dat_filename}: {e}")

    @classmethod
    def _load_cache(cls, hash: str, version: int) -> ItemDatabase | None:
        if (cached := cls._version_cache.get(version)) is not None:
            return cached

        version_dir = setting.appdir / "item_database" / f"v{version}"
        if not version_dir.is_dir():
            return None

        pattern = f"*_{hash}.pkl"
        candidates = sorted(version_dir.glob(pattern), reverse=True)
        for path in candidates:
            if not path.is_file():
                continue
            try:
                with path.open("rb") as f:
                    payload = pickle.load(f)

                if isinstance(payload, ItemDatabase):
                    cached = payload
                    stored_schema = None
                else:
                    stored_schema = payload.get("schema")
                    cached = payload.get("db")

                if stored_schema != cls._schema_hash():
                    cls.logger.info(f"schema mismatch in cache {path}, invalidating")
                    path.unlink(missing_ok=True)
                    return None

                if getattr(cached, "version", None) != version:
                    cls.logger.warning(f"cached file version mismatch {path} (expected {version})")
                    continue

                cls._version_cache[version] = cached
                cls.logger.info(f"loaded cache {path}")
                return cached
            except Exception as e:
                cls.logger.error(f"failed parsing pickle object {path}: {e}, invalidating")
                path.unlink(missing_ok=True)

    @classmethod
    def load_version(cls, version: int) -> ItemDatabase | None:
        if (cached := cls._version_cache.get(version)) is not None:
            return cached

        version_dir = setting.appdir / "item_database" / f"v{version}"
        if not version_dir.is_dir():
            return

        candidates = sorted(version_dir.glob("*"), reverse=True)
        for path in candidates:
            if not path.is_file():
                continue

            try:
                with path.open("rb") as f:
                    cached = pickle.load(f)
                    cls._version_cache[version] = cached
                    cls._build_name_index(cached)
                    return cached
            except Exception as e:
                cls.logger.error("failed parsing pickle object %s: %s", path, e)

    @classmethod
    def deserialize(cls, path_or_data: str | Path | bytes) -> ItemDatabase:
        if isinstance(path_or_data, bytes):
            data = path_or_data
            source_path = None
            source_bytes = data
        else:
            path_or_data = Path(path_or_data)
            data = path_or_data.read_bytes()
            source_path = path_or_data
            source_bytes = None

        s = Buffer(data)
        version = s.read_u16()
        item_count = s.read_u32()

        hash = xxhash.xxh64_hexdigest(data)
        if (cached := cls._load_cache(hash, version)) is not None:
            return cached

        items: dict[int, Item] = {}
        for _ in range(item_count):
            item = Item.deserialize(s, version)
            items[item.id] = item

        db = ItemDatabase(version=version, item_count=item_count, items=items)
        cls._save_cache(hash, db, source_path, source_bytes)

        return db

    @classmethod
    def _build_name_index(cls, db: ItemDatabase) -> None:
        version = getattr(db, "version", None)
        if version is None:
            return

        if version in cls._name_index_cache:
            return

        name_index: dict[bytes, Item] = {}
        name_str_to_items: dict[str, list[Item]] = {}
        name_str_list: list[str] = []

        for item in db.items.values():
            name_bytes = getattr(item, "name", None)
            if name_bytes is None:
                continue

            if name_bytes not in name_index:
                name_index[name_bytes] = item

            name_str = name_bytes.decode()
            if name_str not in name_str_to_items:
                name_str_to_items[name_str] = []
                name_str_list.append(name_str)
            name_str_to_items[name_str].append(item)

        cls._name_index_cache[version] = name_index
        cls._name_str_to_items_cache[version] = name_str_to_items
        cls._name_str_list_cache[version] = name_str_list
        cls.logger.debug(f"built name index for version {version} ({len(name_str_list)} names)")

    @classmethod
    def items(cls) -> dict[int, Item]:
        return cls.db().items

    @classmethod
    def get(cls, id: int) -> Item:
        return cls.db().items[id]

    @classmethod
    def get_by_name(cls, name: bytes | str) -> Item:
        db = cls.db()
        version = getattr(db, "version", None)
        if version is None:
            raise ValueError("database has no version")

        key = name.encode() if isinstance(name, str) else name
        cls._build_name_index(db)

        name_index = cls._name_index_cache.get(version, {})
        try:
            return name_index[key]
        except KeyError:
            raise KeyError(f"no item with exact name {key!r} in version {version}")

    @overload
    @classmethod
    def search(
        cls,
        query: bytes | str,
        n: int = ...,
        cutoff: float = ...,
        version: int | None = ...,
        return_scores: Literal[False] = ...,
    ) -> Sequence[Item]: ...
    @overload
    @classmethod
    def search(
        cls,
        query: bytes | str,
        n: int = ...,
        cutoff: float = ...,
        version: int | None = ...,
        return_scores: Literal[True] = ...,
    ) -> Sequence[tuple[Item, float]]: ...

    @classmethod
    def search(
        cls,
        query: bytes | str,
        n: int = 5,
        cutoff: float = 0.6,
        version: int | None = None,
        return_scores: bool = False,
    ) -> Sequence[tuple[Item, float]] | Sequence[Item]:
        query = query if isinstance(query, str) else query.decode()

        if version is None:
            version = getattr(cls.db(), "version", None)
            if version is None:
                raise ValueError("no database version available to search")

        db = cls._version_cache.get(version) or cls.load_version(version) or cls.db()
        cls._build_name_index(db)
        name_list = cls._name_str_list_cache.get(version, [])
        name_str_to_items = cls._name_str_to_items_cache.get(version, {})

        if not name_list:
            return []

        query_normalized = query.strip().lower()

        def combined_scorer(
            _s1: Sequence[Hashable],
            s2: Sequence[Hashable],
            score_cutoff: float | None = None,
        ) -> float:
            s2 = str(s2)
            choice_normalized = s2.lower()

            if query_normalized == choice_normalized:
                return 100.0
            if choice_normalized.startswith(query_normalized):
                return 95.0
            if f" {query_normalized} " in f" {choice_normalized} ":
                return 90.0

            scores = []

            ratio_score = fuzz.ratio(query_normalized, choice_normalized)
            scores.append(ratio_score * 1.0)

            partial_score = fuzz.partial_ratio(query_normalized, choice_normalized)
            scores.append(partial_score * 0.9)

            token_sort_score = fuzz.token_sort_ratio(query_normalized, choice_normalized)
            scores.append(token_sort_score * 0.85)

            token_set_score = fuzz.token_set_ratio(query_normalized, choice_normalized)
            scores.append(token_set_score * 0.8)

            scores.sort(reverse=True)
            weighted_score = scores[0] * 0.5 + scores[1] * 0.3 + scores[2] * 0.15 + scores[3] * 0.05

            return max(weighted_score, 0.0)

        cutoff_percent = cutoff * 100
        matches = process.extract(query, name_list, scorer=combined_scorer, score_cutoff=cutoff_percent, limit=n * 3)

        results: list[tuple[Item, float]] = []
        seen_item_ids: set[int] = set()

        for matched_name, score, _ in matches:
            items_for_name = name_str_to_items.get(matched_name, [])
            normalized_score = score / 100.0

            for item in items_for_name:
                if item.id in seen_item_ids:
                    continue
                results.append((item, normalized_score))
                seen_item_ids.add(item.id)

                if len(results) >= n:
                    break

            if len(results) >= n:
                break

        if len(results) < n:
            additional_cutoff = max(cutoff_percent * 0.7, 30.0)
            additional_matches = process.extract(
                query, [name for name in name_list if name not in [m[0] for m in matches]], scorer=combined_scorer, score_cutoff=additional_cutoff, limit=n * 2
            )

            for matched_name, score, _ in additional_matches:
                items_for_name = name_str_to_items.get(matched_name, [])
                normalized_score = score / 100.0

                for item in items_for_name:
                    if item.id in seen_item_ids:
                        continue
                    results.append((item, normalized_score))
                    seen_item_ids.add(item.id)

                    if len(results) >= n:
                        break

                if len(results) >= n:
                    break

        results.sort(key=lambda x: x[1], reverse=True)
        results = results[:n]

        if return_scores:
            return results
        else:
            return [itm for itm, _ in results]

    @classmethod
    def has_version(cls, version: int) -> bool:
        if version in cls._version_cache:
            return True

        version_dir = setting.appdir / "item_database" / f"v{version}"
        if not version_dir.is_dir():
            return False

        return any(p.is_file() for p in version_dir.iterdir())

    @classmethod
    def v(cls, version: int) -> ItemDatabase:
        db = cls.load_version(version)
        if db is None:
            raise ValueError(f"no cached item database for version {version}")
        return db

    @classmethod
    def is_background(cls, id: int) -> bool:
        return cls.get(id).item_type in (
            ItemInfoType.BACKGROUND,
            ItemInfoType.BACKGD_SFX_EXTRA_FRAME,
            ItemInfoType.BACK_BOOMBOX,
            ItemInfoType.MUSICNOTE,
        )

    @classmethod
    def is_seed(cls, id: int) -> bool:
        return id % 2 == 1

    @classmethod
    def is_steam(cls, id: int) -> bool:
        return item_database.get(id).item_type in (
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
