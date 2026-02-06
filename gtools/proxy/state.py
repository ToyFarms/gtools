from dataclasses import dataclass, field
from enum import IntEnum
import logging
from pyglm.glm import ivec2, vec2

from gtools.core.growtopia import world
from gtools.core.growtopia.inventory import Inventory
from gtools.core.growtopia.packet import TankFlags
from gtools.core.growtopia.player import CharacterState, Player
from gtools.core.growtopia.world import World
from gtools.protogen import growtopia_pb2
from gtools.protogen.state_pb2 import ModifyItem, ModifyWorld, StateUpdate, StateUpdateWhat


@dataclass(slots=True)
class Me:
    net_id: int = 0
    build_range: int = 0
    punch_range: int = 0
    pos: vec2 = field(default_factory=vec2)
    flags: TankFlags = TankFlags.NONE
    state: CharacterState = field(default_factory=CharacterState)
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
            flags=TankFlags(proto.flags),
            state=CharacterState.from_proto(proto.state),
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
            flags=self.flags,
            state=self.state.to_proto(),
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
                    self.me.flags = TankFlags(upd.player_update.flags)
                    net_id = self.me.net_id

                if player := self.world.get_player(net_id):
                    player.pos = pos
                    player.flags = TankFlags(upd.player_update.flags)
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
            case StateUpdateWhat.STATE_SET_CHARACTER_STATE:
                state = CharacterState.from_proto(upd.character_state)
                if upd.character_state.net_id == self.me.net_id:
                    self.me.state = state

                if self.world and (player := self.world.get_player(upd.character_state.net_id)):
                    player.state = state
            case StateUpdateWhat.STATE_SEND_INVENTORY:
                self.inventory = Inventory.from_proto(upd.send_inventory)
            case StateUpdateWhat.STATE_MODIFY_INVENTORY:
                self.inventory.add(upd.modify_inventory.id, upd.modify_inventory.to_add)
            case StateUpdateWhat.STATE_ENTER_WORLD:
                self.world = World.from_proto(upd.enter_world.enter_world)
            case StateUpdateWhat.STATE_EXIT_WORLD:
                self.world = None
                self.inventory.clear_ghost_item()
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
