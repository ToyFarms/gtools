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

import xxhash
from zmq import IntFlag

if not os.environ.get("NO_BAKED", None):
    from gtools.baked import items
from gtools.core.buffer import Buffer
from gtools.proxy.setting import setting


SECRET = b"PBG892FXX982ABC*"


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
        self.a = (x >> 24) & 0xFF
        self.r = (x >> 16) & 0xFF
        self.g = (x >> 8) & 0xFF
        self.b = x & 0xFF

    def __int__(self) -> int:
        return ((self.a & 0xFF) << 24) | ((self.r & 0xFF) << 16) | ((self.g & 0xFF) << 8) | (self.b & 0xFF)


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
    STARSHIP_VIEW_SCREEN = 1 << 13
    SUPER_MOD = 1 << 14
    TILE_DEADLY_IF_ON = 1 << 15
    LONG_HAND_ITEM64X32 = 1 << 16
    GEMLESS = 1 << 17
    TRANSMUTABLE = 1 << 18
    DUNGEON_ITEM = 1 << 19
    PVE_MELEE = 1 << 20
    PVE_RANGED = 1 << 21
    PVE_AUTO_AIM = 1 << 22
    ONE_IN_WORLD = 1 << 23
    ONLY_FOR_WORLD_OWNER = 1 << 24
    NO_UPGRADE = 1 << 25
    EXTINGUISH_FIRE = 1 << 26
    EXTINGUISH_FIRE_NO_DAMAGE = 1 << 27
    NEED_RECEPTION_DESK = 1 << 28
    USE_PAINT = 1 << 29


def _decrypt(s: bytes, item_id: int) -> bytes:
    chars = bytearray()
    for i in range(len(s)):
        xor = SECRET[(i + item_id) % len(SECRET)]
        chars.append((s[i] ^ xor))

    return bytes(chars)


@dataclass(slots=True)
class Item:
    id: int = 0  # u32
    flags: ItemFlag = ItemFlag.NONE  # u16
    item_type: ItemInfoType = ItemInfoType.FIST  # u8
    material: ItemInfoMaterialType = ItemInfoMaterialType.WOODEN  # u8
    name: bytes = b""  # lpchar
    texture_file: bytes = b""  # lpchar
    texture_file_hash: int = 0  # u32
    visual_effect: ItemInfoVisualEffect = ItemInfoVisualEffect.NONE  # u8
    cooking_time: int = 0  # u32
    tex_coord_x: int = 0  # u8
    tex_coord_y: int = 0  # u8
    texture_type: ItemInfoTextureType = ItemInfoTextureType.SINGLE_FRAME_ALONE  # u8
    is_stripey_wallpaper: int = 0  # u8
    collision_type: ItemInfoCollisionType = ItemInfoCollisionType.NONE  # u8
    health: int = 0  # u8
    restore_time: int = 0  # u32
    clothing_type: ItemInfoClothingType = ItemInfoClothingType.NONE  # u8
    rarity: int = 0  # u16
    max_amount: int = 0  # u8
    extra_file: bytes = b""  # lpchar
    extra_file_hash: int = 0  # u32
    frame_interval_ms: int = 0  # u32
    pet_name: bytes = b""  # lpchar
    pet_prefix: bytes = b""  # lpchar
    pet_suffix: bytes = b""  # lpchar
    pet_ability: bytes = b""  # lpchar
    seed_base: ItemInfoSeedBase = ItemInfoSeedBase.NONE  # u8
    seed_overlay: ItemInfoSeedOverlay = ItemInfoSeedOverlay.LINES  # u8
    tree_base: ItemInfoTreeBase = ItemInfoTreeBase.BRANCH_TREE  # u8
    tree_leaves: ItemInfoTreeLeaves = ItemInfoTreeLeaves.FLAT_LEAVES  # u8
    seed_color: ItemInfoColor = field(default_factory=ItemInfoColor)  # u32
    seed_overlay_color: ItemInfoColor = field(default_factory=ItemInfoColor)  # u32
    ingredient_: int = 0  # u32
    grow_time: int = 0  # u32
    fx_flags: FXFlags = FXFlags.NONE  # u32
    animating_coordinates: bytes = b""  # lpchar
    animating_texture_files: bytes = b""  # lpchar
    animating_coordinates_2: bytes = b""  # lpchar
    unk1: int = 0  # u32
    unk2: int = 0  # u32
    flags2: ItemInfoFlag2 = ItemInfoFlag2.NONE  # u32
    unk3: bytes = b""  # u8 (60)
    tile_range: int = 0  # u32
    vault_capacity: int = 0  # u32
    punch_options: bytes = b""  # lpchar
    unk4: int = 0  # u32
    body_part_list: bytes = b""  # u8 (9)
    light_range: int = 0  # u32
    unk5: int = 0  # u32
    can_sit: int = 0  # u8
    player_offset_x: int = 0  # u32
    player_offset_y: int = 0  # u32
    chair_texture_x: int = 0  # u32
    chair_texture_y: int = 0  # u32
    chair_leg_offset_x: int = 0  # u32
    chair_leg_offset_y: int = 0  # u32
    chair_texture_file: bytes = b""  # lpchar
    renderer_data_file: bytes = b""  # lpchar
    unk6: int = 0  # u32
    renderer_data_file_hash: int = 0  # u32
    unk7: bytes = b""  # u8 (9)
    unk8: int = 0  # u16
    info: bytes = b""  # lpchar
    ingredients: tuple[int, int] = field(default_factory=lambda: (0, 0))  # u16 (2)
    unk9: int = 0  # u8

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

    def get_tex_stride(self) -> int:
        match self.texture_type:
            case ItemInfoTextureType.SINGLE_FRAME_ALONE:
                return 0
            case ItemInfoTextureType.SINGLE_FRAME:
                return 0
            case ItemInfoTextureType.SMART_EDGE:
                return 8
            case ItemInfoTextureType.SMART_EDGE_HORIZ:
                return 0
            case ItemInfoTextureType.SMART_CLING:
                return 0
            case ItemInfoTextureType.SMART_CLING2:
                return 8
            case ItemInfoTextureType.SMART_OUTER:
                return 0
            case ItemInfoTextureType.RANDOM:
                return 0
            case ItemInfoTextureType.SMART_EDGE_VERT:
                return 0
            case ItemInfoTextureType.SMART_EDGE_HORIZ_CAVE:
                return 0
            case ItemInfoTextureType.SMART_EDGE_DIAGON:
                return 0

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
        item.cooking_time = s.read_u32()
        item.tex_coord_x = s.read_u8()
        item.tex_coord_y = s.read_u8()
        item.texture_type = ItemInfoTextureType(s.read_u8())
        item.is_stripey_wallpaper = s.read_u8()
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
        item.unk3 = s.read_bytes(60)
        item.tile_range = s.read_u32()
        item.vault_capacity = s.read_u32()
        if version >= 11:
            item.punch_options = s.read_pascal_bytes("H")
        if version >= 12:
            item.unk4 = s.read_u32()
            item.body_part_list = s.read_bytes(9)
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
            item.chair_leg_offset_x = s.read_u32()
            item.chair_leg_offset_y = s.read_u32()
            item.chair_texture_file = s.read_pascal_bytes("H")
        if version >= 16:
            item.renderer_data_file = s.read_pascal_bytes("H")
        if version >= 17:
            item.unk6 = s.read_u32()
        if version >= 18:
            item.renderer_data_file_hash = s.read_u32()
        if version >= 19:
            item.unk7 = s.read_bytes(9)
        if version >= 21:
            item.unk8 = s.read_u16()
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
    logger = logging.getLogger("item_database")

    # TODO: i think version is not only the version number, but the content needs to be factored in
    _version_cache: dict[int, ItemDatabase] = {}
    _name_index_cache: dict[int, dict[bytes, Item]] = {}
    _name_str_list_cache: dict[int, list[str]] = {}
    _name_str_to_items_cache: dict[int, dict[str, list[Item]]] = {}

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
                Path.home() / "AppData" / "Local" / "Growtopia" / "cache" / "items.dat",
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
                cls._atomic_write(version_dir / filename, db)
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
                    cached = pickle.load(f)
                    if getattr(cached, "version", None) != version:
                        cls.logger.warning(f"cached file version mismatch {path} (expected {version})")
                        continue
                    cls._version_cache[version] = cached
                    cls.logger.info(f"loaded cache {path}")
                    return cached
            except Exception as e:
                cls.logger.error(f"failed parsing pickle object {path}: {e}")

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
    def is_background(cls, item_id: int) -> bool:
        return cls.get(item_id).item_type in (
            ItemInfoType.BACKGROUND,
            ItemInfoType.BACKGD_SFX_EXTRA_FRAME,
            ItemInfoType.MUSICNOTE,
        )
