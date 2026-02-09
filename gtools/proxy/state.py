from dataclasses import dataclass, field
from enum import IntEnum
import logging
import time
from pyglm.glm import ivec2, vec2

from gtools import setting
from gtools.core.async_writer import write_async
from gtools.core.buffer import Buffer
from gtools.core.growtopia import world
from gtools.core.growtopia.inventory import Inventory
from gtools.core.growtopia.packet import NetType, PreparedPacket, TankFlags, TankType
from gtools.core.growtopia.player import CharacterState, Player
from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.variant import Variant
from gtools.core.growtopia.world import LockTile, Npc, NpcState, Tile, TileExtraType, TileFlags, World
from gtools.protogen import growtopia_pb2
from gtools.protogen.extension_pb2 import INTEREST_STATE_UPDATE, Packet
from gtools.protogen.state_pb2 import (
    STATE_ENTER_WORLD,
    STATE_EXIT_WORLD,
    STATE_MODIFY_INVENTORY,
    STATE_MODIFY_ITEM,
    STATE_MODIFY_WORLD,
    STATE_NPC_UPDATE,
    STATE_PLAYER_JOIN,
    STATE_PLAYER_LEAVE,
    STATE_PLAYER_UPDATE,
    STATE_SEND_INVENTORY,
    STATE_SEND_LOCK,
    STATE_SET_CHARACTER_STATE,
    STATE_SET_MY_PLAYER,
    STATE_SET_MY_TELEMETRY,
    STATE_TILE_CHANGE_REQUEST,
    STATE_UPDATE_STATUS,
    STATE_UPDATE_TREE_STATE,
    EnterWorld,
    ModifyInventory,
    ModifyItem,
    ModifyWorld,
    NpcRemove,
    NpcUpdate,
    NpcUpdatePos,
    NpcUpdateTarget,
    PlayerUpdate,
    SendLock,
    SetMyTelemetry,
    StateUpdate,
    StateUpdateWhat,
    TileChangeRequest,
    UpdateTreeState,
)
from gtools.proxy.extension.broker import Broker


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


@dataclass(slots=True)
class Telemetry:
    server_ping: int = 0
    client_ping: int = 0
    enter_world_time: float = 0
    logged_in_time: float = 0


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
    telemetry: Telemetry = field(default_factory=Telemetry)

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

    def send_state_update(self, broker: Broker, upd: StateUpdate) -> None:
        self.update(upd)
        broker.process_event_any(INTEREST_STATE_UPDATE, Packet(type=Packet.TYPE_STATE_UPDATE, state_update=upd))

    def update_status(self, broker: Broker, status: Status) -> None:
        match status:
            case Status.IN_WORLD:
                self.telemetry.enter_world_time = time.time()
            case Status.CONNECTED:
                self.telemetry.enter_world_time = 0.0
            case Status.LOGGED_IN:
                self.telemetry.logged_in_time = time.time()
            case Status.DISCONNECTED:
                self.telemetry.logged_in_time = 0.0

        self.send_state_update(broker, StateUpdate(what=STATE_UPDATE_STATUS, update_status=status))

    def emit_telemetry(self, broker: Broker) -> None:
        now = time.time()
        self.send_state_update(
            broker,
            StateUpdate(
                what=STATE_SET_MY_TELEMETRY,
                set_my_telemetry=SetMyTelemetry(
                    server_ping=self.telemetry.server_ping,
                    client_ping=self.telemetry.client_ping,
                    time_since_login=now - self.telemetry.logged_in_time if self.telemetry.logged_in_time != 0.0 else 0.0,
                    time_in_world=now - self.telemetry.enter_world_time if self.telemetry.enter_world_time != 0.0 else 0.0,
                ),
            ),
        )

    # TODO: remove ModifyWorld, just make it super specific to one event
    def emit_event(self, broker: Broker, event: PreparedPacket) -> None:
        """emit event only sends command through the protobuf, no state update should be happening inside this function"""
        pkt = event.as_net
        match pkt.type:
            case NetType.GAME_MESSAGE:
                match bytes(pkt.game_message[b"action", 1]):
                    case b"quit":
                        self.send_state_update(broker, StateUpdate(what=STATE_EXIT_WORLD))
                        self.update_status(broker, Status.DISCONNECTED)
                    case b"quit_to_exit":
                        self.send_state_update(broker, StateUpdate(what=STATE_EXIT_WORLD))
                        self.update_status(broker, Status.CONNECTED)
            case NetType.TANK_PACKET:
                match pkt.tank.type:
                    case TankType.STATE:
                        # NOTE: net_id of 0 is self
                        self.send_state_update(
                            broker,
                            StateUpdate(
                                what=STATE_PLAYER_UPDATE,
                                player_update=PlayerUpdate(
                                    net_id=pkt.tank.net_id,
                                    x=pkt.tank.vector_x,
                                    y=pkt.tank.vector_y,
                                    flags=pkt.tank.flags,
                                ),
                            ),
                        )
                    case TankType.TILE_CHANGE_REQUEST:
                        self.send_state_update(
                            broker,
                            StateUpdate(
                                what=STATE_TILE_CHANGE_REQUEST,
                                tile_change_req=TileChangeRequest(
                                    x=pkt.tank.int_x,
                                    y=pkt.tank.int_y,
                                    id=pkt.tank.value,
                                    flags=pkt.tank.flags,
                                    splice=pkt.tank.jump_count == 1,
                                    seed_id=pkt.tank.animation_type,
                                ),
                            ),
                        )
                    case TankType.SEND_TILE_TREE_STATE:
                        self.send_state_update(
                            broker,
                            StateUpdate(
                                what=STATE_UPDATE_TREE_STATE,
                                update_tree_state=UpdateTreeState(
                                    x=pkt.tank.int_x,
                                    y=pkt.tank.int_y,
                                    item_id=pkt.tank.value,
                                    harvest=pkt.tank.target_net_id == -1,
                                ),
                            ),
                        )
                    case TankType.NPC:
                        match pkt.tank.animation_type:
                            case 0:
                                npc = Npc.deserialize(Buffer(pkt.tank.extended_data))
                                self.send_state_update(
                                    broker,
                                    StateUpdate(
                                        what=STATE_NPC_UPDATE,
                                        npc_update=NpcUpdate(
                                            op=NpcUpdate.OP_ADD,
                                            npc=npc.to_proto(),
                                        ),
                                    ),
                                )
                            case 1:
                                self.send_state_update(
                                    broker,
                                    StateUpdate(
                                        what=STATE_NPC_UPDATE,
                                        npc_update=NpcUpdate(
                                            op=NpcUpdate.OP_RESET_STATE,
                                            id=pkt.tank.jump_count,
                                        ),
                                    ),
                                )
                            case 2:
                                npc = Npc()
                                npc.state = NpcState(pkt.tank.object_type)
                                npc.id = pkt.tank.jump_count
                                npc.pos = vec2(pkt.tank.vector_x, pkt.tank.vector_y)
                                npc.target_pos = vec2(pkt.tank.vector_x2, pkt.tank.vector_y2)
                                npc.param1 = pkt.tank.int_x
                                npc.param2 = pkt.tank.int_y
                                npc.param3 = pkt.tank.particle_rotation

                                self.send_state_update(
                                    broker,
                                    StateUpdate(
                                        what=STATE_NPC_UPDATE,
                                        npc_update=NpcUpdate(
                                            op=NpcUpdate.OP_ADD,
                                            npc=npc.to_proto(),
                                        ),
                                    ),
                                )
                            case 3:
                                self.send_state_update(
                                    broker,
                                    StateUpdate(
                                        what=STATE_NPC_UPDATE,
                                        npc_update=NpcUpdate(
                                            op=NpcUpdate.OP_UPDATE_TARGET,
                                            update_target=NpcUpdatePos(
                                                id=pkt.tank.jump_count,
                                                param1=pkt.tank.int_x,
                                                param2=pkt.tank.int_y,
                                                param3=pkt.tank.particle_rotation,
                                                x=pkt.tank.vector_x2,
                                                y=pkt.tank.vector_y2,
                                            ),
                                        ),
                                    ),
                                )
                            case 4:
                                self.send_state_update(
                                    broker,
                                    StateUpdate(
                                        what=STATE_NPC_UPDATE,
                                        npc_update=NpcUpdate(
                                            op=NpcUpdate.OP_REMOVE,
                                            remove=NpcRemove(id=pkt.tank.jump_count, state=pkt.tank.object_type),
                                        ),
                                    ),
                                )
                            case 5:
                                # send particle and play audio for GHOST_SHARK, TRAPPED_GHOST_JAR, HOMING_PROJECTILE, UNK4
                                pass
                            case 6:
                                self.send_state_update(
                                    broker,
                                    StateUpdate(
                                        what=STATE_NPC_UPDATE,
                                        npc_update=NpcUpdate(
                                            op=NpcUpdate.OP_UPDATE_POS,
                                            update_target=NpcUpdatePos(
                                                id=pkt.tank.jump_count,
                                                param1=pkt.tank.int_x,
                                                param2=pkt.tank.int_y,
                                                param3=pkt.tank.particle_rotation,
                                                x=pkt.tank.vector_x,
                                                y=pkt.tank.vector_y,
                                            ),
                                        ),
                                    ),
                                )
                            case 7:
                                # send particle and play audio for NORMAL_FEATHER_ATTACK, ROTATING, THANKSGIVING_TURKEY, and ULT_FEATHER_ATTACK
                                self.send_state_update(
                                    broker,
                                    StateUpdate(
                                        what=STATE_NPC_UPDATE,
                                        npc_update=NpcUpdate(
                                            op=NpcUpdate.OP_UPDATE_POS,
                                            update_target=NpcUpdatePos(
                                                id=pkt.tank.jump_count,
                                                x=pkt.tank.vector_x,
                                                y=pkt.tank.vector_y,
                                            ),
                                        ),
                                    ),
                                )
                                self.send_state_update(
                                    broker,
                                    StateUpdate(
                                        what=STATE_NPC_UPDATE,
                                        npc_update=NpcUpdate(
                                            op=NpcUpdate.OP_RESET_STATE,
                                            id=pkt.tank.jump_count,
                                        ),
                                    ),
                                )
                            case 9:
                                # just spawning particle for THANKSGIVING_TURKEY, and ROTATING
                                pass
                    case TankType.SEND_TILE_UPDATE_DATA:
                        tile = Tile.deserialize(Buffer(pkt.tank.extended_data))
                        tile.pos.x = pkt.tank.int_x
                        tile.pos.y = pkt.tank.int_y

                        self.send_state_update(
                            broker,
                            StateUpdate(
                                what=STATE_MODIFY_WORLD,
                                modify_world=ModifyWorld(
                                    op=ModifyWorld.OP_REPLACE,
                                    tile=tile.to_proto(),
                                ),
                            ),
                        )
                    case TankType.SEND_TILE_UPDATE_DATA_MULTIPLE:
                        buf = Buffer(pkt.tank.extended_data)
                        while not buf.eof():
                            x = buf.read_i32()
                            y = buf.read_i32()
                            tile = Tile.deserialize(buf)
                            tile.pos.x = x
                            tile.pos.y = y

                            self.send_state_update(
                                broker,
                                StateUpdate(
                                    what=STATE_MODIFY_WORLD,
                                    modify_world=ModifyWorld(
                                        op=ModifyWorld.OP_REPLACE,
                                        tile=tile.to_proto(),
                                    ),
                                ),
                            )
                    case TankType.SEND_LOCK:
                        buf = Buffer(pkt.tank.extended_data)
                        assert len(buf) == pkt.tank.target_net_id * 2, f"expected {pkt.tank.target_net_id} 2 bytes element, got {len(buf)}"

                        affected: list[int] = []
                        for _ in range(pkt.tank.target_net_id):
                            affected.append(buf.read_u16())

                        self.send_state_update(
                            broker,
                            StateUpdate(
                                what=STATE_SEND_LOCK,
                                send_lock=SendLock(
                                    x=pkt.tank.int_x,
                                    y=pkt.tank.int_y,
                                    lock_owner_id=pkt.tank.net_id,
                                    lock_item_id=pkt.tank.value,
                                    tiles_affected=affected,
                                ),
                            ),
                        )
                    case TankType.CALL_FUNCTION:
                        v = Variant.deserialize(pkt.tank.extended_data)
                        fn = v.as_string[0]
                        if fn == b"OnSpawn":
                            kv = StrKV.deserialize(v.as_string[1])
                            if b"type" in kv:
                                self.send_state_update(
                                    broker,
                                    StateUpdate(
                                        what=STATE_SET_MY_PLAYER,
                                        set_my_player=int(kv[b"netID", 1]),
                                    ),
                                )

                            self.send_state_update(
                                broker,
                                StateUpdate(
                                    what=STATE_PLAYER_JOIN,
                                    player_join=growtopia_pb2.Player(
                                        netID=int(kv[b"netID", 1]),
                                        userID=int(kv[b"userID", 1]),
                                        eid=b"|".join(kv[b"eid", 1:]),
                                        ip=bytes(kv[b"ip", 1]),
                                        colrect=growtopia_pb2.Vec4I(
                                            x=int(kv[b"colrect", 1]),
                                            y=int(kv[b"colrect", 2]),
                                            w=int(kv[b"colrect", 3]),
                                            h=int(kv[b"colrect", 4]),
                                        ),
                                        posXY=growtopia_pb2.Vec2F(
                                            x=float(kv[b"posXY", 1]),
                                            y=float(kv[b"posXY", 2]),
                                        ),
                                        name=bytes(kv[b"name", 1]),
                                        titleIcon=bytes(kv[b"titleIcon", 1]),
                                        country=b"|".join(kv[b"country", 1:]),
                                        invis=int(kv[b"invis", 1]),
                                        mstate=int(kv[b"mstate", 1]),
                                        smstate=int(kv[b"smstate", 1]),
                                        onlineID=bytes(kv[b"onlineID", 1]),
                                    ),
                                ),
                            )
                        elif fn == b"OnRemove":
                            kv = StrKV.deserialize(v.as_string[1])
                            self.send_state_update(
                                broker,
                                StateUpdate(
                                    what=STATE_PLAYER_LEAVE,
                                    player_leave=int(kv[b"netID", 1]),
                                ),
                            )
                    case TankType.ITEM_CHANGE_OBJECT:
                        if pkt.tank.net_id == -1:  # add new
                            self.send_state_update(
                                broker,
                                StateUpdate(
                                    what=STATE_MODIFY_ITEM,
                                    modify_item=ModifyItem(
                                        op=ModifyItem.OP_CREATE,
                                        item_id=pkt.tank.value,
                                        x=pkt.tank.vector_x,
                                        y=pkt.tank.vector_y,
                                        amount=int(pkt.tank.float_var),
                                        flags=pkt.tank.object_type,
                                    ),
                                ),
                            )
                        elif pkt.tank.net_id == -3:  # set amount
                            self.send_state_update(
                                broker,
                                StateUpdate(
                                    what=STATE_MODIFY_ITEM,
                                    modify_item=ModifyItem(
                                        op=ModifyItem.OP_SET_AMOUNT,
                                        uid=pkt.tank.value,
                                        amount=pkt.tank.jump_count,
                                    ),
                                ),
                            )
                        else:  # someone took it
                            self.send_state_update(
                                broker,
                                StateUpdate(
                                    what=STATE_MODIFY_ITEM,
                                    modify_item=ModifyItem(
                                        op=ModifyItem.OP_TAKE,
                                        uid=pkt.tank.value,
                                    ),
                                ),
                            )
                    case TankType.SEND_INVENTORY_STATE:
                        self.send_state_update(
                            broker,
                            StateUpdate(
                                what=STATE_SEND_INVENTORY,
                                send_inventory=Inventory.deserialize(pkt.tank.extended_data).to_proto(),
                            ),
                        )
                    case TankType.MODIFY_ITEM_INVENTORY:
                        # jump count = remove, animation_type = add
                        to_add = -pkt.tank.jump_count if pkt.tank.jump_count != 0 else pkt.tank.animation_type
                        self.send_state_update(
                            broker,
                            StateUpdate(
                                what=STATE_MODIFY_INVENTORY,
                                modify_inventory=ModifyInventory(
                                    id=pkt.tank.value,
                                    to_add=to_add,
                                ),
                            ),
                        )
                    case TankType.SET_CHARACTER_STATE:
                        self.send_state_update(
                            broker,
                            StateUpdate(
                                what=STATE_SET_CHARACTER_STATE,
                                character_state=growtopia_pb2.CharacterState(
                                    net_id=pkt.tank.net_id,
                                    build_range=pkt.tank.jump_count - 128 + 2,  # + 2 for default range
                                    punch_range=pkt.tank.animation_type - 128 + 2,
                                    flags=pkt.tank.value,
                                    velocity=pkt.tank.vector_x2,
                                    gravity=pkt.tank.vector_y2,
                                    acceleration=pkt.tank.vector_x,
                                    velocity_in_water=pkt.tank.float_var,
                                    jump_strength=pkt.tank.vector_y,
                                ),
                            ),
                        )
                    case TankType.SEND_MAP_DATA:
                        world = World.deserialize(pkt.tank.extended_data, pkt.tank.int_x).to_proto()
                        write_async(pkt.serialize(), setting.appdir / "worlds" / world.inner.name.decode(), "wb")

                        self.send_state_update(
                            broker,
                            StateUpdate(
                                what=STATE_ENTER_WORLD,
                                enter_world=EnterWorld(
                                    enter_world=world,
                                ),
                            ),
                        )
                        self.update_status(broker, Status.IN_WORLD)

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
                        self.world.replace_whole_tile(world.Tile.from_proto(upd.modify_world.tile))
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
            case StateUpdateWhat.STATE_SEND_LOCK:
                if not self.world:
                    self.logger.warning("send lock, but world is not initialized")
                    return

                if lock_tile := self.world.get_tile(ivec2(upd.send_lock.x, upd.send_lock.y)):
                    # place lock if it doesn't exists
                    if (
                        (lock_tile.extra and lock_tile.extra.type != TileExtraType.LOCK_TILE)
                        or lock_tile.extra is None
                        or lock_tile.extra.expect(LockTile).owner_uid != upd.send_lock.lock_owner_id
                    ):
                        self.world.place_fg(lock_tile, upd.send_lock.lock_item_id)
                        assert lock_tile.extra
                        lock_tile.extra.expect(LockTile).owner_uid = upd.send_lock.lock_owner_id

                    self.world.remove_locked(lock_tile)

                    for tile in upd.send_lock.tiles_affected:
                        target_tile = self.world.get_tile(tile)
                        if not target_tile:
                            raise ValueError(f"send_lock: tile at {tile=} should exists, but it doesn't")

                        target_tile.flags |= TileFlags.LOCKED
                        target_tile.lock_index = lock_tile.index
            case StateUpdateWhat.STATE_UPDATE_TREE_STATE:
                if not self.world:
                    self.logger.warning("update tree state, but world is not initialized")
                    return

                if tile := self.world.get_tile(ivec2(upd.update_tree_state.x, upd.update_tree_state.y)):
                    self.world.update_tree(
                        tile=tile,
                        item_id=upd.update_tree_state.item_id,
                        harvest=upd.update_tree_state.harvest,
                        spawn_seed_flag=upd.update_tree_state.add_spawn_seeds_flag,
                        seedling_flag=upd.update_tree_state.add_seedling_flag,
                    )
            case StateUpdateWhat.STATE_TILE_CHANGE_REQUEST:
                if not self.world:
                    self.logger.warning("tile change request, but world is not initialized")
                    return

                if tile := self.world.get_tile(ivec2(upd.tile_change_req.x, upd.tile_change_req.y)):
                    self.world.tile_change(
                        tile=tile,
                        id=upd.tile_change_req.id,
                        flags=TankFlags(upd.tile_change_req.flags),
                        splice=upd.tile_change_req.splice,
                        seed_id=upd.tile_change_req.seed_id,
                    )
            case StateUpdateWhat.STATE_NPC_UPDATE:
                if not self.world:
                    self.logger.warning("npc update, but world is not initialized")
                    return

                match upd.npc_update.op:
                    case NpcUpdate.OP_ADD:
                        self.world.add_npc(Npc.from_proto(upd.npc_update.npc))
                    case NpcUpdate.OP_REMOVE:
                        self.world.remove_npc_by_id(upd.npc_update.id)
                    case NpcUpdate.OP_RESET_STATE:
                        if npc := self.world.get_npc(upd.npc_update.id):
                            npc.reset_state()
                    case NpcUpdate.OP_UPDATE_TARGET:
                        tgt = upd.npc_update.update_target
                        if npc := self.world.get_npc(tgt.id):
                            if tgt.param1 != 0:
                                npc.param1 = tgt.param1
                            if tgt.param2 != 0:
                                npc.param2 = tgt.param2
                            if tgt.param3 != 0.0:
                                npc.param3 = tgt.param3
                            npc.target_pos = vec2(tgt.x, tgt.y)
                    case NpcUpdate.OP_UPDATE_POS:
                        tgt = upd.npc_update.update_target
                        if npc := self.world.get_npc(tgt.id):
                            if tgt.param1 != 0:
                                npc.param1 = tgt.param1
                            if tgt.param2 != 0:
                                npc.param2 = tgt.param2
                            if tgt.param3 != 0.0:
                                npc.param3 = tgt.param3
                            npc.pos = vec2(tgt.x, tgt.y)
