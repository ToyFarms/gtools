# https://github.com/CLOEI/gtworld-r/tree/284a2bb9f501e740401c4f0aa025d11adbed2b02

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntFlag
from inspect import isabstract
import logging
from typing import Any, ClassVar

from pyglm.glm import ivec2, vec2
from gtools.core.buffer import Buffer
import cbor2

from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.packet import TankPacket
from gtools.protogen import growtopia_pb2


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


class TileExtra(ABC):
    ID: ClassVar[int]

    _registry: dict[int, type["TileExtra"]] = {}
    logger = logging.getLogger("tile_extra")

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if cls.ID is None:
            raise ValueError(f"{cls.__name__} must define an id")

        if cls.ID in TileExtra._registry:
            return

        TileExtra._registry[cls.ID] = cls

    @classmethod
    @abstractmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "TileExtra": ...

    @classmethod
    def dispatch(cls, s: Buffer, fg: int = -1, bg: int = -1) -> "TileExtra":
        type = s.read_u8()
        if type not in TileExtra._registry:
            raise NotImplementedError(f"no tile extra for id {type}")

        t = TileExtra._registry[type]

        if isabstract(t):
            raise NotImplementedError(f"parser for object {t.__name__} is not implemented")

        return t.deserialize(s, fg, bg)


@dataclass(slots=True)
class DoorTile(TileExtra):
    ID = 1
    text: bytes = b""
    unk1: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "DoorTile":
        t = cls()
        t.text = s.read_pascal_bytes("H")
        t.unk1 = s.read_u8()

        return t


@dataclass(slots=True)
class SignTile(TileExtra):
    ID = 2
    text: bytes = b""
    unk1: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "SignTile":
        t = cls()
        t.text = s.read_pascal_bytes("H")
        t.unk1 = s.read_u32()

        return t


@dataclass(slots=True)
class LockTile(TileExtra):
    ID = 3
    flags: int = 0  # u8
    owner_uid: int = 0  # u32
    access_count: int = 0  # u32
    access_uids: list[int] = field(default_factory=list)  # Vec<u32>
    minimum_level: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "LockTile":
        t = cls()
        t.flags = s.read_u8()
        t.owner_uid = s.read_u32()
        t.access_count = s.read_u32()

        for _ in range(t.access_count):
            t.access_uids.append(s.read_u32())
        t.minimum_level = s.read_u8()

        _ = s.read_bytes(7)

        if fg_id == 5814:
            s.rpos += 16

        return t


@dataclass(slots=True)
class SeedTile(TileExtra):
    ID = 4
    time_passed: int = 0  # u32
    item_on_tree: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "SeedTile":
        t = cls()
        t.time_passed = s.read_u32()
        t.item_on_tree = s.read_u8()

        return t


@dataclass(slots=True)
class MailboxTile(TileExtra):
    ID = 6
    unk1: bytes = b""
    unk2: bytes = b""
    unk3: bytes = b""
    unk4: int = 0  # u8


@dataclass(slots=True)
class BulletinTile(TileExtra):
    ID = 7
    unk1: bytes = b""
    unk2: bytes = b""
    unk3: bytes = b""
    unk4: int = 0  # u8


@dataclass(slots=True)
class DiceTile(TileExtra):
    ID = 8
    symbol: int = 0  # u8


@dataclass(slots=True)
class ChemicalSourceTile(TileExtra):
    ID = 9
    time_passed: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "ChemicalSourceTile":
        t = cls()
        t.time_passed = s.read_u32()

        if fg_id == 10656:
            s.rpos += 4

        return t


@dataclass(slots=True)
class AchievementBlockTile(TileExtra):
    ID = 10
    unk1: int = 0  # u32
    tile_type: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "AchievementBlockTile":
        t = cls()
        t.unk1 = s.read_u32()
        t.tile_type = s.read_u8()

        return t


@dataclass(slots=True)
class HeartMonitorTile(TileExtra):
    ID = 11
    unk1: int = 0  # u32
    player_name: bytes = b""

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "HeartMonitorTile":
        t = cls()
        t.unk1 = s.read_u32()
        t.player_name = s.read_pascal_bytes("H")

        return t


@dataclass(slots=True)
class DonationBoxTile(TileExtra):
    ID = 12
    unk1: bytes = b""
    unk2: bytes = b""
    unk3: bytes = b""
    unk4: int = 0  # u8


@dataclass(slots=True)
class MannequinTile(TileExtra):
    ID = 14
    text: bytes = b""
    unk1: int = 0  # u8
    clothing_1: int = 0  # u32
    clothing_2: int = 0  # u16
    clothing_3: int = 0  # u16
    clothing_4: int = 0  # u16
    clothing_5: int = 0  # u16
    clothing_6: int = 0  # u16
    clothing_7: int = 0  # u16
    clothing_8: int = 0  # u16
    clothing_9: int = 0  # u16
    clothing_10: int = 0  # u16

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "MannequinTile":
        t = cls()
        t.text = s.read_pascal_bytes("H")
        t.unk1 = s.read_u8()
        t.clothing_1 = s.read_u32()
        t.clothing_2 = s.read_u16()
        t.clothing_3 = s.read_u16()
        t.clothing_4 = s.read_u16()
        t.clothing_5 = s.read_u16()
        t.clothing_6 = s.read_u16()
        t.clothing_7 = s.read_u16()
        t.clothing_8 = s.read_u16()
        t.clothing_9 = s.read_u16()
        t.clothing_10 = s.read_u16()

        return t


@dataclass(slots=True)
class BunnyEggTile(TileExtra):
    ID = 15
    eggs_placed: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "BunnyEggTile":
        t = cls()
        t.eggs_placed = s.read_u32()

        return t


@dataclass(slots=True)
class GamePackTile(TileExtra):
    ID = 16
    team: int = 0  # u8


@dataclass(slots=True)
class GameGeneratorTile(TileExtra):
    ID = 17

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int) -> "GameGeneratorTile":
        t = cls()
        return t


@dataclass(slots=True)
class XenoniteCrystalTile(TileExtra):
    ID = 20
    ID = 18
    unk1: int = 0  # u8
    unk2: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "XenoniteCrystalTile":
        t = cls()
        t.unk1 = s.read_u8()
        t.unk2 = s.read_u32()

        return t


@dataclass(slots=True)
class PhoneBoothTile(TileExtra):
    ID = 19
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
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "PhoneBoothTile":
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
    ID = 20
    unk1: bytes = b""


@dataclass(slots=True)
class CrimeInProgressTile(TileExtra):
    ID = 21
    unk1: bytes = b""
    unk2: int = 0  # u32
    unk3: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "CrimeInProgressTile":
        t = CrimeInProgressTile()
        t.unk1 = s.read_pascal_bytes("H")
        t.unk2 = s.read_u32()
        t.unk3 = s.read_u8()
        return t


@dataclass(slots=True)
class DisplayBlockTile(TileExtra):
    ID = 23
    item_id: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "DisplayBlockTile":
        t = cls()
        t.item_id = s.read_u32()

        return t


@dataclass(slots=True)
class VendingMachineTile(TileExtra):
    ID = 24
    item_id: int = 0  # u32
    price: int = 0  # i32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "VendingMachineTile":
        t = cls()
        t.item_id = s.read_u32()
        t.price = s.read_i32()

        return t


@dataclass(slots=True)
class GivingTreeTile(TileExtra):
    ID = 28
    unk1: int = 0  # u16
    unk2: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "GivingTreeTile":
        t = cls()
        t.unk1 = s.read_u16()
        t.unk2 = s.read_u32()
        return t


@dataclass(slots=True)
class CountryFlagTile(TileExtra):
    ID = 33
    country: bytes = b""

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "CountryFlagTile":
        t = cls()
        t.country = s.read_pascal_bytes("H")

        return t


@dataclass(slots=True)
class WeatherMachineTile(TileExtra):
    ID = 40
    settings: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "WeatherMachineTile":
        t = cls()
        t.settings = s.read_u32()

        return t


@dataclass(slots=True)
class DataBedrockTile(TileExtra):
    ID = 42

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "DataBedrockTile":
        t = cls()
        _ = s.read_bytes(21)
        return t


@dataclass(slots=True)
class SpotlightTile(TileExtra):
    ID = 22

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int) -> "SpotlightTile":
        t = SpotlightTile()
        return t


@dataclass(slots=True)
class FishTankPortTile(TileExtra):
    ID = 25
    flags: int = 0  # u8
    fishes: list[FishInfo] = field(default_factory=list)

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "FishTankPortTile":
        t = cls()
        t.flags = s.read_u8()

        for _ in range(s.read_u32() // 2):
            t.fishes.append(FishInfo.deserialize(s))

        return t


@dataclass(slots=True)
class SolarCollectorTile(TileExtra):
    ID = 26
    unk1: bytes = b""  # [u8; 5]

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "SolarCollectorTile":
        t = SolarCollectorTile()
        t.unk1 = s.read_bytes(5)
        return t


@dataclass(slots=True)
class ForgeTile(TileExtra):
    ID = 27
    temperature: int = 0  # u32


@dataclass(slots=True)
class SteamOrganTile(TileExtra):
    ID = 30
    inbytesument_type: int = 0  # u8
    note: int = 0  # u32


@dataclass(slots=True)
class Color:
    a: int
    r: int
    g: int
    b: int


@dataclass(slots=True)
class SilkwormTile(TileExtra):
    ID = 31
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
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "SilkwormTile":
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
    ID = 32
    bolt_id_list: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "SewingMachineTile":
        t = cls()

        for _ in range(s.read_u32()):
            t.bolt_id_list.append(s.read_u32())

        return t


@dataclass(slots=True)
class LobsterTrapTile(TileExtra):
    ID = 34

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int) -> "LobsterTrapTile":
        t = LobsterTrapTile()
        return t


@dataclass(slots=True)
class PaintingEaselTile(TileExtra):
    ID = 35
    item_id: int = 0  # u32
    label: bytes = b""

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "PaintingEaselTile":
        t = cls()
        t.item_id = s.read_u32()
        t.label = s.read_pascal_bytes("H")

        return t


@dataclass(slots=True)
class PetBattleCageTile(TileExtra):
    ID = 36
    name: bytes = b""
    unk1: bytes = b""

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "PetBattleCageTile":
        t = cls()
        t.name = s.read_pascal_bytes("H")
        t.unk1 = s.read_bytes(12)
        return t


@dataclass(slots=True)
class PetTrainerTile(TileExtra):
    ID = 37
    name: bytes = b""
    pet_total_count: int = 0  # u32
    unk1: int = 0  # u32
    pets_id: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "PetTrainerTile":
        t = cls()
        t.name = s.read_pascal_bytes("H")
        t.pet_total_count = s.read_u32()
        t.unk1 = s.read_u32()

        for _ in range(t.pet_total_count):
            t.pets_id.append(s.read_u32())

        return t


@dataclass(slots=True)
class SteamEngineTile(TileExtra):
    ID = 38
    temperature: int = 0  # u32


@dataclass(slots=True)
class LockBotTile(TileExtra):
    ID = 39
    time_passed: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "LockBotTile":
        t = cls()
        t.time_passed = s.read_u32()

        return t


@dataclass(slots=True)
class SpiritStorageUnitTile(TileExtra):
    ID = 41
    ghost_jar_count: int = 0  # u32


@dataclass(slots=True)
class ShelfTile(TileExtra):
    ID = 43
    top_left_item_id: int = 0  # u32
    top_right_item_id: int = 0  # u32
    bottom_left_item_id: int = 0  # u32
    bottom_right_item_id: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "ShelfTile":
        t = cls()
        t.top_left_item_id = s.read_u32()
        t.top_right_item_id = s.read_u32()
        t.bottom_left_item_id = s.read_u32()
        t.bottom_right_item_id = s.read_u32()

        return t


@dataclass(slots=True)
class VipEntranceTile(TileExtra):
    ID = 44
    unk1: int = 0  # u8
    owner_uid: int = 0  # u32
    access_uids: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "VipEntranceTile":
        t = cls()
        t.unk1 = s.read_u8()
        t.owner_uid = s.read_u32()
        size = s.read_u32()
        for _ in range(size):
            t.access_uids.append(s.read_u32())

        return t


@dataclass(slots=True)
class ChallangeTimerTile(TileExtra):
    ID = 45
    pass


@dataclass(slots=True)
class FishWallMountTile(TileExtra):
    ID = 47
    label: bytes = b""
    item_id: int = 0  # u32
    lb: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "FishWallMountTile":
        t = cls()
        t.label = s.read_pascal_bytes("H")
        t.item_id = s.read_u32()
        t.lb = s.read_u8()

        return t


@dataclass(slots=True)
class PortraitTile(TileExtra):
    ID = 48
    label: bytes = b""
    unk1: int = 0  # u32
    unk2: int = 0  # u32
    unk3: int = 0  # u32
    unk4: int = 0  # u32
    face: int = 0  # u32
    hat: int = 0  # u32
    hair: int = 0  # u32
    unk5: int = 0  # u16
    unk6: int = 0  # u16

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "PortraitTile":
        t = cls()
        t.label = s.read_pascal_bytes("H")
        t.unk1 = s.read_u32()
        t.unk2 = s.read_u32()
        t.unk3 = s.read_u32()
        t.unk4 = s.read_u32()
        t.face = s.read_u32()
        t.hat = s.read_u32()
        t.hair = s.read_u32()
        t.unk5 = s.read_u16()
        t.unk6 = s.read_u16()

        return t


@dataclass(slots=True)
class GuildWeatherMachineTile(TileExtra):
    ID = 49
    unk1: int = 0  # u32
    gravity: int = 0  # u32
    flags: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "GuildWeatherMachineTile":
        t = cls()
        t.unk1 = s.read_u32()
        t.gravity = s.read_u32()
        t.flags = s.read_u8()

        return t


@dataclass(slots=True)
class FossilPrepStationTile(TileExtra):
    ID = 50
    unk1: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "FossilPrepStationTile":
        t = cls()
        t.unk1 = s.read_u32()
        return t


@dataclass(slots=True)
class DnaExtractorTile(TileExtra):
    ID = 51

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int) -> "DnaExtractorTile":
        t = cls()
        return t


@dataclass(slots=True)
class HowlerTile(TileExtra):
    ID = 52

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int) -> "HowlerTile":
        t = cls()
        return t


@dataclass(slots=True)
class ChemsynthTankTile(TileExtra):
    ID = 53
    current_chem: int = 0  # u32
    target_chem: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "ChemsynthTankTile":
        t = cls()
        t.current_chem = s.read_u32()
        t.target_chem = s.read_u32()

        return t


@dataclass(slots=True)
class StorageBlockTile(TileExtra):
    ID = 54
    items: list[StorageBlockItemInfo] = field(default_factory=list)

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "StorageBlockTile":
        t = cls()
        for _ in range(s.read_u16() // 13):
            t.items.append(StorageBlockItemInfo.deserialize(s))

        return t


@dataclass(slots=True)
class CookingOvenTile(TileExtra):
    ID = 55
    temperature_level: int = 0  # u32
    ingredients: list[CookingOvenIngredientInfo] = field(default_factory=list)
    unk1: int = 0  # u32
    unk2: int = 0  # u32
    unk3: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "CookingOvenTile":
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
    ID = 56
    note: bytes = b""
    volume: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "AudioRackTile":
        t = cls()
        t.note = s.read_pascal_bytes("H")
        t.volume = s.read_u32()

        return t


@dataclass(slots=True)
class GeigerChargerTile(TileExtra):
    ID = 57
    unk1: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "GeigerChargerTile":
        t = cls()
        t.unk1 = s.read_u32()
        return t


@dataclass(slots=True)
class AdventureBeginsTile(TileExtra):
    ID = 58

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int) -> "AdventureBeginsTile":
        t = cls()
        return t


@dataclass(slots=True)
class TombRobberTile(TileExtra):
    ID = 59

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int) -> "TombRobberTile":
        return TombRobberTile()


@dataclass(slots=True)
class BalloonOMaticTile(TileExtra):
    ID = 60
    total_rarity: int = 0  # u32
    team_type: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "BalloonOMaticTile":
        t = BalloonOMaticTile()
        t.total_rarity = s.read_u32()
        t.team_type = s.read_u8()

        return t


@dataclass(slots=True)
class TrainingPortTile(TileExtra):
    ID = 61
    fish_lb: int = 0  # u32
    fish_status: int = 0  # u16
    fish_id: int = 0  # u32
    fish_total_exp: int = 0  # u32
    fish_level: int = 0  # u32
    unk2: int = 0  # u32
    unk3: bytes = b""  # u8 * 13

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "TrainingPortTile":
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
    ID = 62
    item_id_to_suck: int = 0  # u32
    item_amount: int = 0  # u32
    flags: int = 0  # u16
    limit: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "ItemSuckerTile":
        t = cls()
        t.item_id_to_suck = s.read_u32()
        t.item_amount = s.read_u32()
        t.flags = s.read_u16()
        t.limit = s.read_u32()

        return t


@dataclass(slots=True)
class CyBotTile(TileExtra):
    ID = 63
    commands: list[CyBotCommandData] = field(default_factory=list)
    sync_timer: int = 0  # u32
    activated: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "CyBotTile":
        t = cls()

        for _ in range(s.read_u32()):
            t.commands.append(CyBotCommandData.deserialize(s))

        t.sync_timer = s.read_u32()
        t.activated = s.read_u32()

        return t


@dataclass(slots=True)
class GuildItemTile(TileExtra):
    ID = 65
    unk1: bytes = b""  # 17

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "GuildItemTile":
        t = cls()
        t.unk1 = s.read_bytes(17)
        return t


@dataclass(slots=True)
class GrowscanTile(TileExtra):
    ID = 66
    unk1: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "GrowscanTile":
        t = cls()
        t.unk1 = s.read_u8()
        return t


@dataclass(slots=True)
class ContainmentFieldPowerNodeTile(TileExtra):
    ID = 67
    ghost_jar_count: int = 0  # u32
    unk1: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "ContainmentFieldPowerNodeTile":
        t = cls()
        t.ghost_jar_count = s.read_u32()
        for _ in range(s.read_u32()):
            t.unk1.append(s.read_u32())
        return t


@dataclass(slots=True)
class SpiritBoardTile(TileExtra):
    ID = 68
    unk1: int = 0  # u32
    unk2: int = 0  # u32
    unk3: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "SpiritBoardTile":
        t = cls()
        t.unk1 = s.read_u32()
        t.unk2 = s.read_u32()
        t.unk3 = s.read_u32()
        return t


@dataclass(slots=True)
class StormyCloudTile(TileExtra):
    ID = 72
    sting_duration: int = 0  # u32
    is_solid: int = 0  # u32
    non_solid_duration: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "StormyCloudTile":
        t = cls()
        t.sting_duration = s.read_u32()
        t.is_solid = s.read_u32()
        t.non_solid_duration = s.read_u32()

        return t


@dataclass(slots=True)
class TemporaryPlatformTile(TileExtra):
    ID = 73
    unk1: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "TemporaryPlatformTile":
        t = cls()
        t.unk1 = s.read_u32()
        return TemporaryPlatformTile()


@dataclass(slots=True)
class SafeVaultTile(TileExtra):
    ID = 74

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int) -> "SafeVaultTile":
        t = SafeVaultTile()
        return t


@dataclass(slots=True)
class AngelicCountingCloudTile(TileExtra):
    ID = 75
    is_raffling: int = 0  # u32
    unk1: int = 0  # u16
    ascii_code: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "AngelicCountingCloudTile":
        t = cls()
        t.is_raffling = s.read_u32()
        t.unk1 = s.read_u16()
        t.ascii_code = s.read_u8()
        return t


@dataclass(slots=True)
class InfinityWeatherMachineTile(TileExtra):
    ID = 77
    interval_minutes: int = 0  # u32
    weather_machine_list: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "InfinityWeatherMachineTile":
        t = cls()
        t.interval_minutes = s.read_u32()
        size = s.read_u32()
        for _ in range(size):
            t.weather_machine_list.append(s.read_u32())

        return t


@dataclass(slots=True)
class PineappleGuzzlerTile(TileExtra):
    ID = 79

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int) -> "PineappleGuzzlerTile":
        t = cls()
        return t


@dataclass(slots=True)
class KrakenGalaticBlockTile(TileExtra):
    ID = 80
    pattern_index: int = 0  # u8
    unk1: int = 0  # u32
    r: int = 0  # u8
    g: int = 0  # u8
    b: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "KrakenGalaticBlockTile":
        t = cls()
        t.pattern_index = s.read_u8()
        t.unk1 = s.read_u32()
        t.r = s.read_u8()
        t.g = s.read_u8()
        t.b = s.read_u8()
        return t


@dataclass(slots=True)
class FriendsEntranceTile(TileExtra):
    ID = 81
    owner_user_id: int = 0  # u32
    unk1: int = 0  # u16
    unk2: int = 0  # u16

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "FriendsEntranceTile":
        t = cls()
        t.owner_user_id = s.read_u32()
        t.unk1 = s.read_u16()
        t.unk2 = s.read_u16()
        return t


@dataclass(slots=True)
class TesseractManipulator(TileExtra):
    ID = 69
    gems: int = 0  # u32
    unk1: int = 0  # u32
    unk2: int = 0  # u32
    unk3: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int) -> "TesseractManipulator":
        t = cls()
        t.gems = s.read_u32()
        t.unk1 = s.read_u32()
        t.unk2 = s.read_u32()
        t.unk3 = s.read_u32()
        return t


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
    parent_block_index: int = 0
    flags: TileFlags = TileFlags.NONE
    extra: TileExtra | None = None
    _extra_raw: bytes = b""
    pos: ivec2 = field(default_factory=ivec2)
    lock_block_index: int = 0
    cbor_data: dict[Any, Any] = field(default_factory=dict)

    logger = logging.getLogger("tile")

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.Tile) -> "Tile":
        return cls(
            fg_id=proto.fg_id,
            bg_id=proto.bg_id,
            parent_block_index=proto.parent_block_index,
            flags=TileFlags(proto.flags),
            extra=TileExtra.dispatch(Buffer(proto.extra)) if proto.extra else None,
            _extra_raw=proto.extra,
            pos=ivec2(proto.x, proto.y),
            lock_block_index=proto.lock_block_index,
            cbor_data=cbor2.loads(proto.cbor_data) if proto.cbor_data else {},
        )

    def to_proto(self) -> growtopia_pb2.Tile:
        return growtopia_pb2.Tile(
            fg_id=self.fg_id,
            bg_id=self.bg_id,
            parent_block_index=self.parent_block_index,
            flags=TileFlags(self.flags),
            extra=self._extra_raw,
            x=self.pos.x,
            y=self.pos.y,
            lock_block_index=self.lock_block_index,
            cbor_data=cbor2.dumps(self.cbor_data) if self.cbor_data else b"",
        )

    @classmethod
    def deserialize(cls, s: Buffer) -> "Tile":
        tile = cls()
        tile.fg_id = s.read_u16()
        tile.bg_id = s.read_u16()
        tile.parent_block_index = s.read_u16()
        tile.flags = TileFlags(s.read_u16())

        if tile.flags & TileFlags.LOCKED:
            tile.lock_block_index = s.read_u16()

        if tile.flags & TileFlags.HAS_EXTRA_DATA:
            start = s.rpos
            tile.extra = TileExtra.dispatch(s, tile.fg_id, tile.bg_id)
            extra_size = s.rpos - start

            s.rpos = start
            tile._extra_raw = s.read_bytes(extra_size)

        cbor_ids = [
            15376,  # Party Projector
            8642,  # Bountiful Lattice Fence Roots
            15546,  # Auction Block
            14666,  # Auto Surgeon
            14662,  # Operating Table
            3548,  # Battle Pet Cage
        ]

        if tile.fg_id in cbor_ids:
            tile.cbor_data = cbor2.loads(s.read_pascal_bytes("I"))

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
    unk1: bytes = b"\x00" * 6
    name: bytes = b""
    width: int = 0
    height: int = 0
    nb_tiles: int = 0
    unk2: bytes = b"\x00" * 5
    tiles: list[Tile] = field(default_factory=list)
    unk3: bytes = b"\x00" * 12
    dropped: Dropped = field(default_factory=Dropped)
    unk4: bytes = b"\x00" * 12

    garbage_start: int = -1
    logger = logging.getLogger("world")

    @classmethod
    def from_tank(cls, tank: TankPacket | bytes) -> "World":
        return cls.deserialize(Buffer(tank if isinstance(tank, bytes) else tank.extended_data), 60)

    @classmethod
    def from_extended(cls, extended: bytes) -> "World":
        return cls.deserialize(Buffer(extended))

    @classmethod
    def deserialize(cls, s: bytes | Buffer, offset: int = 0) -> "World":
        s = Buffer(s)

        world = cls()

        s.rpos += offset
        world.unk1 = s.read_bytes(6)
        world.name = s.read_pascal_bytes("H")
        world.width = s.read_u32()
        world.height = s.read_u32()
        world.nb_tiles = s.read_u32()

        world.unk2 = s.read_bytes(5)

        failed = False
        for p in range(world.nb_tiles):
            try:
                tile = Tile.deserialize(s)
            except Exception as e:
                cls.logger.error(f"failed parsing world at offset={s.rpos}, peek={s.peek(100)}. err={e}")
                if not failed:
                    world.garbage_start = p
                failed = True
                # we keep going even though it will yield garbage, we can try to recover, but it can skip multiple tile which will cause weird offset
                # we can try to sync using bedrock, but its too unreliable

            tile.pos = ivec2(p % world.width, p // world.width)
            world.tiles.append(tile)

        if failed:
            with s.reversed(keep=False):
                world.unk4 = s.read_bytes(12)

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

                world.unk3 = s.read_bytes(12)
            world.dropped.items.reverse()

            return world

        world.unk3 = s.read_bytes(12)

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

        world.unk4 = s.read_bytes(12)

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
        )

    def to_proto(self) -> growtopia_pb2.WorldInner:
        return growtopia_pb2.WorldInner(
            name=self.name,
            width=self.width,
            height=self.height,
            nb_tiles=self.nb_tiles,
            tiles=list(map(lambda x: x.to_proto(), self.tiles)),
            dropped=self.dropped.to_proto(),
            garbage_start=self.garbage_start,
        )
