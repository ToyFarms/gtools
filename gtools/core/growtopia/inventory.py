from dataclasses import dataclass, field
from enum import IntFlag
import struct
from typing import Iterator, OrderedDict

from gtools.baked.items import MAGPLANT_5000_REMOTE, WORLD_KEY
from gtools.core.buffer import Buffer
from gtools.core.protocol import Serializable
from gtools.protogen import growtopia_pb2


class ItemFlags(IntFlag):
    NONE = 0
    ACTIVE = 1 << 0


@dataclass(slots=True)
class Item(Serializable):
    id: int = 0
    amount: int = 0
    flags: ItemFlags = ItemFlags.NONE

    @classmethod
    def deserialize(cls, data: bytes) -> "Item":
        return cls(*struct.unpack("<HBB", data))

    def serialize(self) -> bytes:
        return struct.pack("<HBB", self.id, self.amount, self.flags)

    def add(self, add: int) -> int:
        self.amount = min(max(self.amount + add, 0), 200)
        return self.amount

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.Item) -> "Item":
        return cls(
            id=proto.id,
            amount=proto.amount,
            flags=ItemFlags(proto.flags),
        )

    def to_proto(self) -> growtopia_pb2.Item:
        return growtopia_pb2.Item(
            id=self.id,
            amount=self.amount,
            flags=int(self.flags),
        )


@dataclass(slots=True)
class Inventory(Serializable):
    max_slot: int = 0
    items_map: OrderedDict[int, Item] = field(default_factory=OrderedDict)

    @classmethod
    def from_iter(cls, max_slot: int, items: Iterator[Item]) -> "Inventory":
        return cls(max_slot=max_slot, items_map=OrderedDict((x.id, x) for x in (items or iter(()))))

    @classmethod
    def deserialize(cls, data: bytes) -> "Inventory":
        buf = Buffer(data)
        buf.rpos += 1

        max_slot = buf.read_u32()
        count = buf.read_u16()

        return Inventory.from_iter(
            max_slot=max_slot,
            items=(Item(id=buf.read_u16(), amount=buf.read_u8(), flags=ItemFlags(buf.read_u8())) for _ in range(count)),
        )

    def serialize(self) -> bytes:
        buf = Buffer()

        buf.write_u16(len(self))
        for item in self:
            buf.write_u16(item.id)
            buf.write_u8(item.amount)
            buf.write_u8(item.flags)

        return buf.serialize()

    @property
    def items(self) -> Iterator[Item]:
        return iter(self.items_map.values())

    def __len__(self) -> int:
        return len(self.items_map)

    def __iter__(self) -> Iterator[Item]:
        return iter(self.items_map.values())

    def __contains__(self, id: int) -> bool:
        return id in self.items_map

    def __getitem__(self, id: int) -> Item:
        return self.items_map[id]

    def remove(self, id: int) -> Item:
        return self.items_map.pop(id)

    def set_item(self, item: Item) -> None:
        self.items_map[item.id] = item

    def _is_ghost_item(self, id: int) -> bool:
        return id in (WORLD_KEY, MAGPLANT_5000_REMOTE)

    def add(self, id: int, to_add: int) -> Item:
        item = self.items_map.get(id)
        if item is None:
            item = Item(id=id)
            self.items_map[id] = item

        if item.add(to_add) == 0:
            self.items_map.pop(id, None)

        return item

    def get(self, id: int, default: Item | None = None) -> Item | None:
        return self.items_map.get(id, default)

    def clear_ghost_item(self) -> None:
        self.items_map = OrderedDict((k, v) for k, v in self.items_map.items() if not self._is_ghost_item(v.id))

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.Inventory) -> "Inventory":
        return cls.from_iter(
            max_slot=proto.max_slot,
            items=(Item.from_proto(x) for x in proto.items),
        )

    def to_proto(self) -> growtopia_pb2.Inventory:
        return growtopia_pb2.Inventory(
            max_slot=self.max_slot,
            items=[x.to_proto() for x in self.items],
        )
