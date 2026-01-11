# https://github.com/CLOEI/gtworld-r/tree/284a2bb9f501e740401c4f0aa025d11adbed2b02

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntFlag
from inspect import isabstract
import logging
from typing import ClassVar, Self

from pyglm.glm import ivec2, vec2
from gtools.core.buffer import Buffer
import cbor2

from gtools.core.growtopia.items_dat import Item, ItemInfoFlag2, ItemInfoTextureType, ItemInfoType, item_database
from gtools.core.growtopia.packet import TankPacket
from gtools.core.growtopia.player import Player
from gtools.protogen import growtopia_pb2
from gtools.baked.items import ItemID


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
class GuildData:
    unk1: int = 0  # u8
    unk2: int = 0  # u32
    unk3: int = 0  # u32
    unk4: int = 0  # u32
    unk5: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, id: int) -> "GuildData":
        t = cls()
        # guild lock
        if id != 5814:
            t.unk1 = s.read_u8()
        t.unk2 = s.read_u32()
        t.unk3 = s.read_u32()
        t.unk4 = s.read_u32()
        t.unk5 = s.read_u32()

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


@dataclass(slots=True)
class BedrockData:
    unk1: int = 0  # u64

    @classmethod
    def deserialize(cls, s: Buffer) -> "BedrockData":
        t = cls()
        t.unk1 = s.read_u64()

        return t


CborData = dict
SpecialData = GuildData | StarshipHullData | BedrockData | CborData


class TileExtra(ABC):
    ID: ClassVar[int]

    _registry: dict[int, type["TileExtra"]] = {}
    logger = logging.getLogger("tile_extra")
    special_data: SpecialData | None = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if cls.ID is None:
            raise ValueError(f"{cls.__name__} must define an id")

        if cls.ID in TileExtra._registry:
            return

        TileExtra._registry[cls.ID] = cls

    @classmethod
    @abstractmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> Self: ...

    @classmethod
    def handle_special_tile(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> SpecialData | None:
        item = item_database.get(fg_id if fg_id > 0 else bg_id)

        cbor_ids = [
            15376,  # party projector
            8642,  # bountiful lattice fence roots
            15546,  # auction block
            14666,  # auto surgeon
            14662,  # operating table
            3548,  # battle pet cage
        ]

        if item.flags2 & ItemInfoFlag2.GUILD_ITEM:
            return GuildData.deserialize(s, item.id)
        elif item.id == 6546 and format_version > 4:  # starship hull
            return StarshipHullData.deserialize(s, format_version)
        elif item.id == 42 and format_version > 10:  # bedrock
            return BedrockData.deserialize(s)
        elif item.id in cbor_ids:
            return cbor2.loads(s.read_pascal_bytes("I"))

    @classmethod
    def dispatch(cls, s: Buffer, fg: int = -1, bg: int = -1, format_version=999999999) -> "TileExtra":
        type = s.read_u8()
        if type not in TileExtra._registry:
            raise NotImplementedError(f"no tile extra for id {type}")

        t = TileExtra._registry[type]

        if isabstract(t):
            raise NotImplementedError(f"parser for object {t.__name__} is not implemented")

        extra = t.deserialize(s, fg, bg, format_version)
        if fg > 0 or bg > 0:
            extra.special_data = cls.handle_special_tile(s, fg, bg, format_version)

        return extra


@dataclass(slots=True)
class DoorTile(TileExtra):
    ID = 1
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
    ID = 2
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
    ID = 3
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
    ID = 4
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
    ID = 6
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
    ID = 7
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
    ID = 8
    symbol: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "DiceTile":
        t = cls()
        t.symbol = s.read_u8()

        return t


@dataclass(slots=True)
class ChemicalSourceTile(TileExtra):
    ID = 9
    time_passed: int = 0  # u32
    time_ms: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ChemicalSourceTile":
        t = cls()
        t.time_passed = s.read_u32()

        # well of love, winter calendar 2017
        if (fg_id == 10656 and format_version > 16) or fg_id == 5318:
            t.time_ms = s.read_u32()

        return t


@dataclass(slots=True)
class AchievementBlockTile(TileExtra):
    ID = 10
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
    ID = 11
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
    ID = 12
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
class Unk5TileExtra(TileExtra):
    ID = 13
    unk1: bytes = b""
    unk2: bytes = b""
    unk3: bytes = b""
    unk4: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "Unk5TileExtra":
        t = cls()
        t.unk1 = s.read_pascal_bytes("H")
        t.unk2 = s.read_pascal_bytes("H")
        t.unk3 = s.read_pascal_bytes("H")
        t.unk4 = s.read_u8()

        return t


@dataclass(slots=True)
class MannequinTile(TileExtra):
    ID = 14
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
    ID = 15
    eggs_placed: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "BunnyEggTile":
        t = cls()
        t.eggs_placed = s.read_u32()

        return t


@dataclass(slots=True)
class GamePackTile(TileExtra):
    ID = 16
    team: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GamePackTile":
        t = cls()
        t.team = s.read_u8()

        return t


@dataclass(slots=True)
class GameGeneratorTile(TileExtra):
    ID = 17

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GameGeneratorTile":
        t = cls()
        return t


@dataclass(slots=True)
class XenoniteCrystalTile(TileExtra):
    ID = 18
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
    ID = 20
    unk1: bytes = b""

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "CrystalTile":
        t = cls()
        t.unk1 = s.read_pascal_bytes("H")

        return t


@dataclass(slots=True)
class CrimeInProgressTile(TileExtra):
    ID = 21
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
    ID = 23
    item_id: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "DisplayBlockTile":
        t = cls()
        t.item_id = s.read_u32()

        return t


@dataclass(slots=True)
class VendingMachineTile(TileExtra):
    ID = 24
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
    ID = 28
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
    ID = 33
    country: bytes = b""

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "CountryFlagTile":
        t = cls()
        t.country = s.read_pascal_bytes("H")

        return t


@dataclass(slots=True)
class WeatherMachineTile(TileExtra):
    ID = 40
    settings: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "WeatherMachineTile":
        t = cls()
        t.settings = s.read_u32()

        return t


@dataclass(slots=True)
class DataBedrockTile(TileExtra):
    ID = 42
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
    ID = 22

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SpotlightTile":
        t = SpotlightTile()
        return t


@dataclass(slots=True)
class FishTankPortTile(TileExtra):
    ID = 25
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
    ID = 26
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
    ID = 27
    temperature: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ForgeTile":
        t = cls()
        t.temperature = s.read_u8()

        return t


@dataclass(slots=True)
class SteamOrganTile(TileExtra):
    ID = 30
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
    ID = 32
    bolt_id_list: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SewingMachineTile":
        t = cls()

        for _ in range(s.read_u32()):
            t.bolt_id_list.append(s.read_u32())

        return t


@dataclass(slots=True)
class LobsterTrapTile(TileExtra):
    ID = 34

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "LobsterTrapTile":
        t = LobsterTrapTile()
        return t


@dataclass(slots=True)
class PaintingEaselTile(TileExtra):
    ID = 35
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
    ID = 36
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
    ID = 37
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
    ID = 38
    temperature: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SteamEngineTile":
        t = cls()
        t.temperature = s.read_u32()

        return t


@dataclass(slots=True)
class LockBotTile(TileExtra):
    ID = 39
    time_passed: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "LockBotTile":
        t = cls()
        t.time_passed = s.read_u32()

        return t


@dataclass(slots=True)
class SpiritStorageUnitTile(TileExtra):
    ID = 41
    ghost_jar_count: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SpiritStorageUnitTile":
        t = cls()
        t.ghost_jar_count = s.read_u32()

        return t


@dataclass(slots=True)
class ShelfTile(TileExtra):
    ID = 43
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
    ID = 44
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
class ChallangeTimerTile(TileExtra):
    ID = 45

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "ChallangeTimerTile":
        t = cls()

        return t


@dataclass(slots=True)
class FishWallMountTile(TileExtra):
    ID = 47
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
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PortraitTile":
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
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GuildWeatherMachineTile":
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
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "FossilPrepStationTile":
        t = cls()
        t.unk1 = s.read_u32()
        return t


@dataclass(slots=True)
class DnaExtractorTile(TileExtra):
    ID = 51

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "DnaExtractorTile":
        t = cls()
        return t


@dataclass(slots=True)
class HowlerTile(TileExtra):
    ID = 52

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "HowlerTile":
        t = cls()
        return t


@dataclass(slots=True)
class ChemsynthTankTile(TileExtra):
    ID = 53
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
    ID = 54
    items: list[StorageBlockItemInfo] = field(default_factory=list)

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "StorageBlockTile":
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
    ID = 56
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
    ID = 57
    unk1: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GeigerChargerTile":
        t = cls()
        t.unk1 = s.read_u32()
        return t


@dataclass(slots=True)
class AdventureBeginsTile(TileExtra):
    ID = 58

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "AdventureBeginsTile":
        t = cls()
        return t


@dataclass(slots=True)
class TombRobberTile(TileExtra):
    ID = 59

    @classmethod
    def deserialize(cls, _s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "TombRobberTile":
        return TombRobberTile()


@dataclass(slots=True)
class BalloonOMaticTile(TileExtra):
    ID = 60
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
    ID = 61
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
    ID = 62
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
class CyBotTile(TileExtra):
    ID = 63
    commands: list[CyBotCommandData] = field(default_factory=list)
    sync_timer: int = 0  # u32
    activated: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "CyBotTile":
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
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GuildItemTile":
        t = cls()
        t.unk1 = s.read_bytes(17)
        return t


@dataclass(slots=True)
class GrowscanTile(TileExtra):
    ID = 66
    unk1: int = 0  # u8

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "GrowscanTile":
        t = cls()
        t.unk1 = s.read_u8()
        return t


@dataclass(slots=True)
class ContainmentFieldPowerNodeTile(TileExtra):
    ID = 67
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
    ID = 68
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
class TesseractManipulator(TileExtra):
    ID = 69
    gems: int = 0  # u32
    next_update_ms: int = 0  # u32
    item_id: int = 0  # u32
    enabled: bool = False  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "TesseractManipulator":
        t = cls()
        t.gems = s.read_u32()
        t.next_update_ms = s.read_u32()
        t.item_id = s.read_u32()
        if format_version >= 8:
            t.enabled = s.read_u32() != 0

        return t


@dataclass(slots=True)
class Unk2TileExtra(TileExtra):
    # the same exact structure as tm, probably toe or hog
    ID = 70
    gems: int = 0  # u32
    next_update_ms: int = 0  # u32
    item_id: int = 0  # u32
    enabled: bool = False  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "Unk2TileExtra":
        t = cls()
        t.gems = s.read_u32()
        t.next_update_ms = s.read_u32()
        t.item_id = s.read_u32()
        if format_version >= 8:
            t.enabled = s.read_u32() != 0

        return t


@dataclass(slots=True)
class Unk3TileExtra(TileExtra):
    ID = 71
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
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "Unk3TileExtra":
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
    ID = 72
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
    ID = 73
    time_ms: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "TemporaryPlatformTile":
        t = cls()
        t.time_ms = s.read_u32()
        return TemporaryPlatformTile()


@dataclass(slots=True)
class SafeVaultTile(TileExtra):
    ID = 74

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "SafeVaultTile":
        t = SafeVaultTile()
        return t


@dataclass(slots=True)
class AngelicCountingCloudTile(TileExtra):
    ID = 75
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
    field_11: int = 0  # u32
    field_b12: bool = False  # u32
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
    pos: list[tuple[int, int]] = field(default_factory=list)  # vector<vec2<i32>>
    field_b27: bool = False  # u32

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
        t.field_11 = s.read_u32()
        t.field_b12 = s.read_u32() != 0
        t.field_13 = s.read_u32()
        t.field_10 = s.read_u32()
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
        t.field_b27 = s.read_u32() != 0
        for _ in range(s.read_u32()):
            t.pos.append((s.read_u32(), s.read_u32()))

        return t


# probably outdated but oh well
@dataclass(slots=True)
class PveNpcTile(TileExtra):
    ID = 76
    arr: list[PveNpcData] = field(default_factory=list)  # len 3

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PveNpcTile":
        t = cls()
        for i in range(3):
            t.arr.append(PveNpcData.deserialize(s))

        return t


@dataclass(slots=True)
class InfinityWeatherMachineTile(TileExtra):
    ID = 77
    interval_minutes: int = 0  # u32
    weather_machine_list: list[int] = field(default_factory=list)  # Vec<u32>

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "InfinityWeatherMachineTile":
        t = cls()
        t.interval_minutes = s.read_u32()
        for _ in range(s.read_u32()):
            t.weather_machine_list.append(s.read_u32())

        return t


@dataclass(slots=True)
class Unk4TileExtra(TileExtra):
    ID = 78
    unk1: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "Unk4TileExtra":
        t = cls()
        t.unk1 = s.read_u32()

        return t


@dataclass(slots=True)
class PineappleGuzzlerTile(TileExtra):
    ID = 79
    pineapple_fed: int = 0  # u32

    @classmethod
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "PineappleGuzzlerTile":
        t = cls()
        t.pineapple_fed = s.read_u32()

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
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "KrakenGalaticBlockTile":
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
    def deserialize(cls, s: Buffer, fg_id: int, bg_id: int, format_version: int) -> "FriendsEntranceTile":
        t = cls()
        t.owner_user_id = s.read_u32()
        t.unk1 = s.read_u16()
        t.unk2 = s.read_u16()
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

    logger = logging.getLogger("tile")

    @property
    def front(self) -> int:
        return self.fg_id if self.fg_id > 0 else self.bg_id if self.bg_id > 0 else 0

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
        )

    @classmethod
    def deserialize(cls, s: Buffer, format_version: int = 999999999999) -> "Tile":
        tile = cls()
        tile.fg_id = s.read_u16()
        tile.bg_id = s.read_u16()
        tile.parent_block_index = s.read_u16()
        tile.flags = TileFlags(s.read_u16())

        if tile.flags & TileFlags.LOCKED:
            tile.lock_block_index = s.read_u16()

        if tile.flags & TileFlags.HAS_EXTRA_DATA:
            start = s.rpos
            tile.extra = TileExtra.dispatch(s, tile.fg_id, tile.bg_id, format_version)
            extra_size = s.rpos - start

            s.rpos = start
            tile._extra_raw = s.read_bytes(extra_size)

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
    version: int = 0  # u32
    unk1: int = 0  # u16
    name: bytes = b""
    width: int = 0  # u32
    height: int = 0  # u32
    nb_tiles: int = 0  # u32
    unk2: bytes = b"\x00" * 5
    tiles: list[Tile] = field(default_factory=list)
    unk3: bytes = b"\x00" * 12
    dropped: Dropped = field(default_factory=Dropped)
    unk4: bytes = b"\x00" * 12

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

    def get_tile(self, pos: ivec2) -> Tile | None:
        for tile in self.tiles:
            if tile.pos == pos:
                return tile

        self.logger.warning(f"tile {pos} in {self.name} does not exists")

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

    def replace_tile(self, tile: Tile) -> None:
        if idx := self.index_tile(tile.pos):
            self.tiles[idx] = tile

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

    def is_item_steam(self, item: Item) -> bool:
        return item.item_type in (ItemInfoType.STEAMPUNK, ItemInfoType.STEAM_LAVA_IF_ON, ItemInfoType.STEAM_ORGAN) or item.id in (
            ItemID.STEAM_DOOR,
            ItemID.STEAM_LAUNCHER,
            ItemID.STEAM_PIPE,
            ItemID.SPIRIT_STORAGE_UNIT,
            ItemID.STEAM_SPIKES,
            ItemID.STEAM_LAMP,
        )

    def is_tile_candidate_for_connectivity(self, tile: Tile, item_id: int, cave_related: int) -> bool:
        if tile.pos.x < 0 or tile.pos.y < 0:
            return True
        if tile.pos.x >= self.width or tile.pos.y >= self.height:
            return True

        item = item_database.get(item_id)

        if tile.front and (tile.front & 1) == 0 and tile.flags & TileFlags.GLUED != 0:
            return True

        if cave_related and item.id == ItemID.CAVE_DIRT and tile.front == ItemID.CAVE_COLUMN:
            return True

        def label_29() -> bool:
            if tile.front >= ItemID.PURPLE_CAVE_CRYSTAL and tile.front <= ItemID.AQUA_CAVE_CRYSTAL:
                return True
            return label_31()

        def label_31() -> bool:
            if not cave_related and item.id == ItemID.CAVE_DIRT:
                if tile.front == ItemID.CLIMBING_WALL:
                    return True
                return tile.front == item.id
            return label_35()

        def label_35() -> bool:
            if item.id == ItemID.STEAM_PIPE:
                if item.is_steam():
                    return True
                # falls through to label_60
            if item.id == ItemID.STONE_PAGODA:
                if tile.front == ItemID.MASTER_PENG_STONEWORK:
                    return True
                elif tile.front == ItemID.STONE_PAGODA_BASE:
                    return cave_related != 2
                # falls through to label_60

            if item.id != 4202:
                match item.id:
                    case ItemID.BEDROCK:
                        if tile.front == ItemID.DATA_BEDROCK:
                            return True
                    case ItemID.DATA_BEDROCK:
                        if tile.front == ItemID.BEDROCK:
                            return True
                        if tile.front == ItemID.MONOCHROMATIC_BEDROCK:
                            return True
                    case ItemID.MONOCHROMATIC_BEDROCK:
                        if tile.front == ItemID.DATA_BEDROCK:
                            return True
                    case ItemID.ANCIENT_BLOCK:
                        if tile.front == ItemID.MYSTERY_DOOR:
                            return True
                    case _:
                        if item.id == 2 and tile.front == ItemID.FISSURE:
                            return True
                # falls through to label_60
            else:
                if tile.front != ItemID.STONE_PAGODA_BASE:
                    # goto LABEL_60
                    pass  # Falls through
                else:
                    return cave_related == 0

            # LABEL_60 starts here
            return label_60()

        def label_60() -> bool:
            if (
                cave_related
                and ((item.id - ItemID.GUILD_FLAG_POLE_SPEAR) & 0xFFFFFFFD) == 0
                and ItemID.GUILD_FLAG_SHIELD_OPEN_DIVISION_CLOSE >= tile.front >= ItemID.GUILD_FLAG_TATTERS
                or item.id == ItemID.MANOR_HOUSE_SANDSTONE
                and tile.front == ItemID.MANOR_HOUSE_SANDSTONE_STEPS
            ):
                return True

            if cave_related == 2:
                match item.id:
                    case ItemID.WEEPING_WILLOW_STREAMERS:
                        if tile.front == ItemID.WEEPING_WILLOW_FOLIAGE:
                            return True
                        return tile.front == item.id
                    case ItemID.LOVEWILLOW_S_LACE:
                        if tile.front == ItemID.LOVEWILLOW:
                            return True
                        return tile.front == item.id
                    case ItemID.PILLAR_OF_THE_DEAD:
                        if tile.front == ItemID.BONE_CHECKPOINT:
                            return True
                        return tile.front == item.id

            match item.id:
                case ItemID.MAGIC_INFUSED_VEIN:
                    if tile.front != ItemID.PURE_MAGIC_ORE:
                        if tile.front == ItemID.MAGIC_INFUSED_STONE:
                            return True
                        return tile.front == item.id
                    return True
                case ItemID.MAGIC_INFUSED_STONE:
                    if tile.front == ItemID.PURE_MAGIC_ORE:
                        return True
                case ItemID.PURE_MAGIC_ORE:
                    if tile.front == ItemID.MAGIC_INFUSED_STONE:
                        return True
                case _:
                    if item.id == 10596 and tile.front == ItemID.GREAT_TURRET_OF_GROWTOPIA:
                        return True
                    return tile.front == item.id

            if tile.front == ItemID.MAGIC_INFUSED_VEIN:
                return True

            return tile.front == item.id

        match cave_related:
            case 2:
                if item.id == ItemID.CAVE_DIRT:
                    if tile.front == ItemID.STALAGMITE:
                        return True
                    return label_29()
                if item.id == ItemID.CAVE_COLUMN:
                    if tile.front == ItemID.CAVE_PLATFORM:
                        return True
                    return tile.front == item.id
            case 1:
                if item.id != ItemID.CAVE_DIRT:
                    return label_35()
                if tile.front == ItemID.STALACTITE:
                    return True
                return label_29()
            case 0:
                if item.id != ItemID.CAVE_DIRT:
                    return label_35()
                if tile.front == ItemID.CAVE_PLATFORM:
                    return True
                return label_29()

        if item.id == ItemID.CAVE_DIRT:
            return label_29()

        return label_31()

    def get_texture_index(self, tile: Tile) -> int:
        item = item_database.get(tile.front)
        match item.texture_type:
            case ItemInfoTextureType.SINGLE_FRAME_ALONE | ItemInfoTextureType.SINGLE_FRAME | ItemInfoTextureType.SMART_OUTER:
                return 0
            case ItemInfoTextureType.SMART_EDGE:

                east = self.get_tile(tile.pos + (1, 0))

    @classmethod
    def from_tank(cls, tank: TankPacket | bytes) -> "World":
        return cls.deserialize(Buffer(tank if isinstance(tank, bytes) else tank.extended_data), 60)

    @classmethod
    def from_extended(cls, extended: bytes) -> "World":
        return cls.deserialize(Buffer(extended))

    def serialize(self) -> bytes:
        # TODO:
        return b""

    @classmethod
    def deserialize(cls, s: bytes | Buffer, offset: int = 0) -> "World":
        s = Buffer(s)

        world = cls()

        s.rpos += offset
        world.version = s.read_u32()
        world.unk1 = s.read_u16()
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
