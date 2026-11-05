"""PlayerController -- the client's tile-interaction pipeline (``HandleTouch``).

Covers the press/hold/release model, the per-tile de-duplication (Fist repeats,
items do not), the reach gate, the punch-animation cadence, the position-stamped
``TILE_CHANGE_REQUEST``, the chained STATE action bits (``PUNCH|TILE_CHANGE`` /
``PLACE|TILE_CHANGE``), the optimistic application and the steam-launcher
``ITEM_ACTIVATE_OBJECT_REQUEST``.  Client evidence: ``docs/tile-change-request.md``.
"""

from pyglm.glm import ivec2

from gtools.baked.items import DIRT, STEAM_LAUNCHER
from gtools.core.growtopia.inventory import Inventory
from gtools.core.growtopia.packet import TankFlags, TankType
from gtools.core.growtopia.physics.controller import (
    FIST_ID,
    HITBOX,
    PUNCH_REPEAT_MS,
    TOUCH_HOLD_TIMEOUT_MS,
    PlayerController,
)
from gtools.core.growtopia.player import Player
from gtools.core.growtopia.world import Tile, TileFlags, World

FLOOR_Y = 8
STAND_Y = FLOOR_Y * 32 - HITBOX[1]
FIST_TILE = (5, FLOOR_Y)
FAR_TILE = (14, FLOOR_Y)


def make_world(*extras) -> World:
    tiles = [Tile(fg_id=DIRT, pos=ivec2(x, FLOOR_Y)) for x in range(16)]
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


def test_press_punches_and_chains_the_state_frame() -> None:
    session = Session()
    session.controller.touch_press(*FIST_TILE)
    session.controller.step()

    assert len(session.requests) == 1
    request = session.requests[0]
    assert request.value == FIST_ID
    assert (request.int_x, request.int_y) == FIST_TILE
    assert (request.vector_x, request.vector_y) == session.pos  # position stamp

    frame = session.frames[-1]
    assert int(frame.flags) & int(TankFlags.PUNCH)
    assert int(frame.flags) & int(TankFlags.TILE_CHANGE)
    assert (frame.int_x, frame.int_y) == FIST_TILE  # punchTile stamps the bounce tile
    assert frame.value == 0
    assert session.controller.action_flags == TankFlags.NONE  # consumed by the frame


def test_hold_repeats_the_punch_after_the_animation_gate() -> None:
    session = Session()
    session.controller.touch_press(*FIST_TILE)
    session.controller.step()
    assert len(session.requests) == 1

    # holding immediately does not re-send: the punch animation gate is closed
    session.controller.touch_hold(*FIST_TILE)
    assert len(session.requests) == 1

    while session.controller.time_ms < PUNCH_REPEAT_MS:
        session.controller.step()
        session.controller.touch_hold(*FIST_TILE)

    assert len(session.requests) == 2, "the Fist must keep punching while held"
    assert session.requests[1].value == FIST_ID


def test_hold_with_a_placeable_never_repeats() -> None:
    session = Session(hand_item=DIRT)

    session.controller.touch_press(*FIST_TILE)
    session.controller.step()
    assert len(session.requests) == 1

    for _ in range(30):  # > PUNCH_REPEAT_MS of hold ticks
        session.controller.step()
        session.controller.touch_hold(*FIST_TILE)

    assert len(session.requests) == 1, "hold ticks must not re-place (HandleTouch isBreakTap==false)"

    frame = next(p for p in session.frames if int(p.flags) & int(TankFlags.PLACE))
    assert int(frame.flags) & int(TankFlags.TILE_CHANGE)


def test_a_new_press_re_arms_the_per_tile_dedupe() -> None:
    session = Session(hand_item=DIRT)

    session.controller.touch_press(*FIST_TILE)
    session.controller.step()
    session.controller.touch_hold(*FIST_TILE)
    session.controller.step()
    assert len(session.requests) == 1

    session.controller.touch_release()
    session.controller.touch_press(*FIST_TILE)  # client writes lastTileIndex = -1
    session.controller.step()
    assert len(session.requests) == 2


def test_out_of_reach_touch_is_ignored() -> None:
    session = Session()
    session.controller.touch_press(*FAR_TILE)
    session.controller.step()

    assert session.requests == []


def test_hold_stops_after_the_client_timeout() -> None:
    session = Session()
    session.controller.touch_press(*FIST_TILE)
    assert session.controller.touch_active is True

    while session.controller.time_ms <= TOUCH_HOLD_TIMEOUT_MS:
        session.controller.step()
        session.controller.touch_hold(*FIST_TILE)

    assert session.controller.touch_active is False
    assert session.requests, "the hold must have punched before timing out"


def test_place_applies_optimistically_and_pays_from_inventory() -> None:
    inventory = Inventory()
    inventory.add(DIRT, 3)
    session = Session(inventory, hand_item=DIRT)

    session.world.get_tile(2, FLOOR_Y).fg_id = 0
    session.controller.touch_press(2, FLOOR_Y)
    session.controller.step()

    assert session.world.get_tile(2, FLOOR_Y).fg_id == DIRT, "optimistic application"
    assert inventory.get(DIRT).amount == 3, "no player registered -> no payment"

    session.world.add_player(Player(net_id=session.controller.net_id, user_id=1))
    session.world.get_tile(3, FLOOR_Y).fg_id = 0
    session.controller.touch_release()
    session.controller.touch_press(3, FLOOR_Y)
    session.controller.step()

    assert session.world.get_tile(3, FLOOR_Y).fg_id == DIRT
    assert inventory.get(DIRT).amount == 2


def test_optimistic_application_can_be_disabled() -> None:
    inventory = Inventory()
    inventory.add(DIRT, 2)
    session = Session(inventory, hand_item=DIRT, optimistic=False)

    session.world.get_tile(2, FLOOR_Y).fg_id = 0
    session.controller.touch_press(2, FLOOR_Y)
    session.controller.step()

    assert session.world.get_tile(2, FLOOR_Y).fg_id == 0
    assert inventory.get(DIRT).amount == 2


def test_punch_stamps_facing_left() -> None:
    session = Session()
    session.controller.facing_right = False
    session.controller.touch_press(*FIST_TILE)
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
