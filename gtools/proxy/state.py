from dataclasses import dataclass, field
from enum import IntEnum
import logging
import struct
from typing import Iterator, OrderedDict
from pyglm.glm import ivec2, vec2, vec4

from gtools.core.buffer import Buffer
from gtools.core.growtopia import world
from gtools.core.growtopia.items_dat import ItemInfoType, item_database
from gtools.core.growtopia.packet import TankFlags
from gtools.core.protocol import Serializable
from gtools.protogen import growtopia_pb2
from gtools.protogen.state_pb2 import ModifyItem, ModifyWorld, StateUpdate, StateUpdateWhat


# TODO: this fits in core better
@dataclass(slots=True)
class Item(Serializable):
    id: int = 0
    amount: int = 0
    flags: int = 0

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
            flags=proto.flags,
        )

    def to_proto(self) -> growtopia_pb2.Item:
        return growtopia_pb2.Item(
            id=self.id,
            amount=self.amount,
            flags=self.flags,
        )


@dataclass(slots=True)
class Inventory(Serializable):
    _items_map: OrderedDict[int, Item] = field(default_factory=OrderedDict)

    def __init__(self, items: Iterator[Item] | None = None) -> None:
        object.__setattr__(
            self,
            "_items_map",
            OrderedDict((x.id, x) for x in (items or iter(()))),
        )

    @classmethod
    def deserialize(cls, data: bytes) -> "Inventory":
        buf = Buffer(data)
        buf.rpos += 5

        count = buf.read_u16()
        return cls(Item(id=buf.read_u16(), amount=buf.read_u8(), flags=buf.read_u8()) for _ in range(count))

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
        return iter(self._items_map.values())

    def __len__(self) -> int:
        return len(self._items_map)

    def __iter__(self) -> Iterator[Item]:
        return iter(self._items_map.values())

    def __contains__(self, id: int) -> bool:
        return id in self._items_map

    def __getitem__(self, id: int) -> Item:
        return self._items_map[id]

    def remove(self, id: int) -> Item:
        return self._items_map.pop(id)

    def set_item(self, item: Item) -> None:
        self._items_map[item.id] = item

    def add(self, id: int, to_add: int) -> Item:
        item = self._items_map.get(id)
        if item is None:
            item = Item(id=id)
            self._items_map[id] = item

        if item.add(to_add) == 0:
            self._items_map.pop(id, None)

        return item

    def get(self, id: int, default: Item | None = None) -> Item | None:
        return self._items_map.get(id, default)

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.Inventory) -> "Inventory":
        return cls(items=(Item.from_proto(x) for x in proto.items))

    def to_proto(self) -> growtopia_pb2.Inventory:
        return growtopia_pb2.Inventory(items=[x.to_proto() for x in self.items])


@dataclass(slots=True)
class Player:
    net_id: int = 0
    user_id: int = 0
    eid: bytes = b""
    ip: bytes = b""
    colrect: vec4 = field(default_factory=vec4)
    pos: vec2 = field(default_factory=vec2)
    name: bytes = b""
    titleIcon: bytes = b""
    country: bytes = b""
    invis: int = 0
    mstate: int = 0
    smstate: int = 0
    online_id: bytes = b""
    state: TankFlags = TankFlags.NONE

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.Player) -> "Player":
        return cls(
            net_id=proto.netID,
            user_id=proto.userID,
            eid=proto.eid,
            ip=proto.ip,
            colrect=vec4(
                proto.colrect.x,
                proto.colrect.y,
                proto.colrect.w,
                proto.colrect.h,
            ),
            pos=vec2(proto.posXY.x, proto.posXY.y),
            name=proto.name,
            titleIcon=proto.titleIcon,
            country=proto.country,
            invis=proto.invis,
            mstate=proto.mstate,
            smstate=proto.smstate,
            online_id=proto.onlineID,
            state=TankFlags(proto.state),
        )

    def to_proto(self) -> growtopia_pb2.Player:
        return growtopia_pb2.Player(
            netID=self.net_id,
            userID=self.user_id,
            eid=self.eid,
            ip=self.ip,
            colrect=growtopia_pb2.Vec4I(
                x=int(self.colrect.x),
                y=int(self.colrect.y),
                w=int(self.colrect.w),
                h=int(self.colrect.z),
            ),
            posXY=growtopia_pb2.Vec2F(
                x=self.pos.x,
                y=self.pos.y,
            ),
            name=self.name,
            titleIcon=self.titleIcon,
            country=self.country,
            invis=self.invis,
            mstate=self.mstate,
            smstate=self.smstate,
            onlineID=self.online_id,
            state=self.state,
        )


@dataclass(slots=True)
class World(Serializable):
    inner: world.World = field(default_factory=world.World)
    player: list[Player] = field(default_factory=list)
    door_id: bytes = b""

    logger = logging.getLogger("world")

    def serialize(self) -> bytes:
        # TODO:
        return b""

    @classmethod
    def deserialize(cls, data: bytes) -> "World":
        return cls(inner=world.World.from_extended(data))

    def get_player(self, net_id: int) -> Player | None:
        for p in self.player:
            if p.net_id == net_id:
                return p
        self.logger.warning(f"player with net_id={net_id} does not exists in world {self.inner.name}")

    def add_player(self, player: Player) -> None:
        self.player.append(player)

    def remove_player(self, player: Player) -> None:
        self.player.remove(player)

    def remove_player_by_id(self, net_id: int) -> None:
        self.player = [p for p in self.player if p.net_id != net_id]

    def get_tile(self, pos: ivec2) -> world.Tile | None:
        for tile in self.inner.tiles:
            if tile.pos == pos:
                return tile

        self.logger.warning(f"tile {pos} in {self.inner.name} does not exists")

    def index_tile(self, pos: ivec2) -> int | None:
        for i, tile in enumerate(self.inner.tiles):
            if tile.pos == pos:
                return i

        self.logger.warning(f"tile {pos} in {self.inner.name} does not exists")

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

        if item_database.get(id).item_type in (
            ItemInfoType.BACKGROUND,
            ItemInfoType.BACKGD_SFX_EXTRA_FRAME,
            ItemInfoType.MUSICNOTE,
        ):
            tile.bg_id = id
        else:
            tile.fg_id = id
            if id % 2 != 0:
                tile.extra = world.SeedTile()

    def replace_tile(self, tile: world.Tile) -> None:
        if idx := self.index_tile(tile.pos):
            self.inner.tiles[idx] = tile

    def create_dropped(self, id: int, pos: vec2, amount: int, flags: int) -> None:
        dropped = world.DroppedItem(
            id=id,
            pos=pos,
            amount=amount,
            flags=flags,
            uid=self.inner.dropped.last_uid + 1,
        )
        self.inner.dropped.last_uid += 1
        self.inner.dropped.items.append(dropped)
        self.inner.dropped.nb_items += 1

    def remove_dropped(self, uid: int) -> world.DroppedItem | None:
        for i, item in enumerate(self.inner.dropped.items):
            if item.uid != uid:
                continue

            self.inner.dropped.items.pop(i)
            self.inner.dropped.nb_items -= 1
            return item

    def set_dropped(self, uid: int, amount: int) -> None:
        for item in self.inner.dropped.items:
            if item.uid != uid:
                continue

            item.amount = amount

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.World) -> "World":
        return cls(
            inner=world.World.from_proto(proto),
            player=[Player.from_proto(x) for x in proto.player],
        )

    def to_proto(self) -> growtopia_pb2.World:
        return growtopia_pb2.World(
            inner=self.inner.to_proto(),
            player=[x.to_proto() for x in self.player],
        )


@dataclass(slots=True)
class Me:
    net_id: int = 0
    build_range: int = 0
    punch_range: int = 0
    pos: vec2 = field(default_factory=lambda: vec2(0, 0))
    state: TankFlags = TankFlags.NONE
    server_ping: int = 0
    client_ping: int = 0
    time_since_login: float = 0.0
    time_in_world: float = 0.0

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.Me) -> "Me":
        return cls(
            net_id=proto.net_id,
            build_range=proto.build_range,
            punch_range=proto.punch_range,
            pos=vec2(proto.pos.x, proto.pos.y),
            state=TankFlags(proto.state),
            server_ping=proto.server_ping,
            client_ping=proto.client_ping,
            time_since_login=proto.time_since_login,
            time_in_world=proto.time_in_world,
        )

    def to_proto(self) -> growtopia_pb2.Me:
        return growtopia_pb2.Me(
            net_id=self.net_id,
            build_range=self.build_range,
            punch_range=self.punch_range,
            pos=growtopia_pb2.Vec2F(x=self.pos.x, y=self.pos.y),
            state=self.state,
            server_ping=self.server_ping,
            client_ping=self.client_ping,
            time_since_login=self.time_since_login,
            time_in_world=self.time_in_world,
        )


class Status(IntEnum):
    DISCONNECTED = 0
    CONNECTED = 1
    CONNECTING = 2
    LOGGING_IN = 3
    LOGGED_IN = 4
    IN_WORLD = 5


@dataclass(slots=True)
class State:
    world: World | None = None
    me: Me = field(default_factory=Me)
    status: Status = Status.DISCONNECTED
    inventory: Inventory = field(default_factory=Inventory)

    logger = logging.getLogger("state")

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.State) -> "State":
        return cls(
            world=World.from_proto(proto.world),
            me=Me.from_proto(proto.me),
            status=Status(proto.status),
            inventory=Inventory.from_proto(proto.inventory),
        )

    def to_proto(self) -> growtopia_pb2.State:
        return growtopia_pb2.State(
            world=self.world.to_proto() if self.world else None,
            me=self.me.to_proto() if self.me else None,
            status=self.status,
            inventory=self.inventory.to_proto(),
        )

    # TODO: make this code hot reload-able
    def update(self, upd: StateUpdate) -> None:
        match upd.what:
            case StateUpdateWhat.STATE_SET_MY_TELEMETRY:
                self.me.server_ping = upd.set_my_telemetry.server_ping
                self.me.client_ping = upd.set_my_telemetry.client_ping
                self.me.time_since_login = upd.set_my_telemetry.time_since_login
                self.me.time_in_world = upd.set_my_telemetry.time_in_world
            case StateUpdateWhat.STATE_PLAYER_UPDATE:
                if not self.world:
                    self.logger.warning("player update, but world is not initialized")
                    return

                pos = vec2(upd.player_update.x, upd.player_update.y)
                net_id = upd.player_update.net_id

                if net_id == 0:
                    self.me.pos = pos
                    self.me.state = TankFlags(upd.player_update.state)
                    net_id = self.me.net_id

                if player := self.world.get_player(net_id):
                    player.pos = pos
                    player.state = TankFlags(upd.player_update.state)
            case StateUpdateWhat.STATE_MODIFY_WORLD:
                if not self.world:
                    self.logger.warning("modify world, but world is not initialized")
                    return

                pos = ivec2(upd.modify_world.tile.x, upd.modify_world.tile.y)
                match upd.modify_world.op:
                    case ModifyWorld.OP_PLACE:
                        # place_tile doesn't care whether its fg or bg, we just use fg_id arbitrarily
                        self.world.place_tile(upd.modify_world.tile.fg_id, pos)
                    case ModifyWorld.OP_DESTROY:
                        self.world.destroy_tile(pos)
                    case ModifyWorld.OP_REPLACE:
                        self.world.replace_tile(world.Tile.from_proto(upd.modify_world.tile))
            case StateUpdateWhat.STATE_MODIFY_ITEM:
                if not self.world:
                    self.logger.warning("modify world item, but world is not initialized")
                    return

                match upd.modify_item.op:
                    case ModifyItem.OP_CREATE:
                        self.world.create_dropped(
                            upd.modify_item.item_id,
                            vec2(upd.modify_item.x, upd.modify_item.y),
                            upd.modify_item.amount,
                            upd.modify_item.flags,
                        )
                    case ModifyItem.OP_SET_AMOUNT:
                        self.world.set_dropped(upd.modify_item.uid, upd.modify_item.flags)
                    case ModifyItem.OP_TAKE:
                        if item := self.world.remove_dropped(upd.modify_item.uid):
                            self.inventory.add(item.id, item.amount)
            case StateUpdateWhat.STATE_SET_MY_PLAYER:
                self.me.net_id = upd.set_my_player
            case StateUpdateWhat.STATE_SEND_INVENTORY:
                self.inventory = Inventory.from_proto(upd.send_inventory)
            case StateUpdateWhat.STATE_MODIFY_INVENTORY:
                if self.inventory[upd.modify_inventory.id].add(upd.modify_inventory.to_add) == 0:
                    self.inventory.remove(upd.modify_inventory.id)
            case StateUpdateWhat.STATE_ENTER_WORLD:
                self.world = World.from_proto(upd.enter_world.enter_world)
                self.world.door_id = upd.enter_world.door_id
            case StateUpdateWhat.STATE_EXIT_WORLD:
                self.world = None
            case StateUpdateWhat.STATE_PLAYER_JOIN:
                if not self.world:
                    self.logger.warning("player join, but world is not initialized")
                    return

                self.world.add_player(Player.from_proto(upd.player_join))
            case StateUpdateWhat.STATE_PLAYER_LEAVE:
                if not self.world:
                    self.logger.warning("player leave, but world is not initialized")
                    return

                self.world.remove_player_by_id(upd.player_leave)
            case StateUpdateWhat.STATE_UPDATE_STATUS:
                self.status = Status(upd.update_status)


# TODO: configure broker address and push/pull address from _setting
