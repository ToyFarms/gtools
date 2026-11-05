"""PlayerController -- outbound tile-change flow (punch / place / activate).

Covers the intent queue and its ~200 ms flush gate, the position-stamped
``TILE_CHANGE_REQUEST`` with the FACING_LEFT flag, the chained STATE frame carrying
PUNCH/PLACE|TILE_CHANGE through the controller's action bits, the optimistic
application against the inventory provider, and the steam-launcher
``ITEM_ACTIVATE_OBJECT_REQUEST`` sent straight from the landing handler.
"""

from pyglm.glm import ivec2

from gtools.baked.items import DIRT, STEAM_LAUNCHER
from gtools.core.growtopia.inventory import Inventory
from gtools.core.growtopia.packet import TankFlags, TankType
from gtools.core.growtopia.physics.controller import FIST_ID, HITBOX, PlayerController
from gtools.core.growtopia.player import Player
from gtools.core.growtopia.world import Tile, TileFlags, World

FLOOR_Y = 8
STAND_Y = FLOOR_Y * 32 - HITBOX[1]


def make_world(*extras) -> World:
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(8)]
    tiles.extend(Tile(fg_id=item_id, pos=ivec2(x, y), flags=flags) for item_id, x, y, flags in extras)
    return World.from_tiles(tiles)


class Session:
    """World + controller + packet recorder sharing one inventory provider."""

    def __init__(self, inventory: Inventory | None = None, **kwargs) -> None:
        self.world = make_world()
        self.inventory = inventory if inventory is not None else Inventory()
        self.packets = []
        self.pos = (3 * 32 + 6.0, STAND_Y)

        self.controller = PlayerController(
            self.world,
            net_id=1,
            x=self.pos[0],
            y=self.pos[1],
            send=self.packets.append,
            inventory_provider=lambda: self.inventory,
            **kwargs,
        )
        self.world.set_local_player(1)

    @property
    def requests(self):
        return [p for p in self.packets if p.type == TankType.TILE_CHANGE_REQUEST]

    @property
    def frames(self):
        return [p for p in self.packets if p.type == TankType.STATE]


def test_punch_sends_a_fist_request_and_chains_the_state_frame() -> None:
    session = Session()
    session.controller.request_punch(5, FLOOR_Y)
    session.controller.step()

    assert len(session.requests) == 1
    request = session.requests[0]
    assert request.value == FIST_ID
    assert (request.int_x, request.int_y) == (5, FLOOR_Y)
    assert (request.vector_x, request.vector_y) == session.pos  # position stamp

    frame = session.frames[-1]
    assert int(frame.flags) & int(TankFlags.PUNCH)
    assert int(frame.flags) & int(TankFlags.TILE_CHANGE)
    assert session.controller.action_flags == TankFlags.NONE  # consumed by the frame


def test_place_marks_place_event_on_the_state_frame() -> None:
    session = Session()
    session.controller.request_place(DIRT, 5, FLOOR_Y)
    session.controller.step()

    frame = session.frames[-1]
    assert int(frame.flags) & int(TankFlags.PLACE)
    assert int(frame.flags) & int(TankFlags.TILE_CHANGE)
    assert session.controller.action_flags == TankFlags.NONE


def test_flush_is_gated_to_the_interval() -> None:
    session = Session()
    session.controller.request_punch(5, FLOOR_Y)
    session.controller.step()
    assert len(session.requests) == 1

    session.controller.request_punch(6, FLOOR_Y)
    session.controller.step()  # inside the 200 ms gate
    assert len(session.requests) == 1

    for _ in range(20):  # ~200 ms at 60 Hz
        session.controller.step()

    assert len(session.requests) == 2
    assert (session.requests[1].int_x, session.requests[1].int_y) == (6, FLOOR_Y)


def test_place_applies_optimistically_and_pays_from_inventory() -> None:
    inventory = Inventory()
    inventory.add(DIRT, 3)
    session = Session(inventory)

    session.world.get_tile(2, FLOOR_Y).fg_id = 0
    session.controller.request_place(DIRT, 2, FLOOR_Y)
    session.controller.step()

    assert session.world.get_tile(2, FLOOR_Y).fg_id == DIRT, "optimistic application"
    assert inventory.get(DIRT).amount == 3, "no player registered -> no payment"

    session.world.add_player(Player(net_id=session.controller.net_id, user_id=1))
    session.world.get_tile(3, FLOOR_Y).fg_id = 0
    session.controller.request_place(DIRT, 3, FLOOR_Y)
    for _ in range(20):
        session.controller.step()

    assert session.world.get_tile(3, FLOOR_Y).fg_id == DIRT
    assert inventory.get(DIRT).amount == 2


def test_optimistic_application_can_be_disabled() -> None:
    inventory = Inventory()
    inventory.add(DIRT, 2)
    session = Session(inventory, optimistic=False)

    session.world.get_tile(2, FLOOR_Y).fg_id = 0
    session.controller.request_place(DIRT, 2, FLOOR_Y)
    session.controller.step()

    assert session.world.get_tile(2, FLOOR_Y).fg_id == 0
    assert inventory.get(DIRT).amount == 2


def test_activate_request_bypasses_the_flush_gate() -> None:
    session = Session()
    session.controller.request_punch(5, FLOOR_Y)
    session.controller.step()
    before = len(session.packets)

    session.controller.request_activate(6, FLOOR_Y, STEAM_LAUNCHER)

    assert len(session.packets) == before + 1
    activate = session.packets[-1]
    assert activate.type == TankType.ITEM_ACTIVATE_OBJECT_REQUEST
    assert (activate.int_x, activate.int_y) == (6, FLOOR_Y)
    assert activate.value == STEAM_LAUNCHER


def test_punch_stamps_facing_left() -> None:
    session = Session()
    session.controller.facing_right = False
    session.controller.request_punch(5, FLOOR_Y)
    session.controller.step()

    assert session.requests[0].flags & TankFlags.FACING_LEFT


def test_steam_launcher_clears_is_on_and_requests_activate() -> None:
    world = make_world((STEAM_LAUNCHER, 3, FLOOR_Y - 1, TileFlags.IS_ON))
    packets = []
    controller = PlayerController(world, x=3 * 32 + 6.0, y=(FLOOR_Y - 4) * 32, send=packets.append)

    for _ in range(40):
        controller.step()
        if any(p.type == TankType.ITEM_ACTIVATE_OBJECT_REQUEST for p in packets):
            break

    activates = [p for p in packets if p.type == TankType.ITEM_ACTIVATE_OBJECT_REQUEST]
    assert len(activates) == 1
    assert (activates[0].int_x, activates[0].int_y) == (3, FLOOR_Y - 1)
    assert activates[0].value == STEAM_LAUNCHER
    assert not (world.get_tile(3, FLOOR_Y - 1).flags & TileFlags.IS_ON), "optimistic IS_ON clear"
