"""PlayerController -- the client's tile-interaction pipeline (``HandleTouch``).

Covers the press/hold/release model, the per-tile de-duplication (Fist repeats,
items do not), the reach gate, the punch-animation cadence, the position-stamped
``TILE_CHANGE_REQUEST``, the chained STATE action bits (``PUNCH|TILE_CHANGE`` /
``PLACE|TILE_CHANGE``), the steam-launcher ``TILE_ACTIVATE_REQUEST`` and the
dropped-object ``ITEM_ACTIVATE_OBJECT_REQUEST``.  Client evidence:
``docs/tile-change-request.md``.
"""

from pyglm.glm import ivec2, vec2

from gtools.baked.items import (
    DIRT,
    DIRT_SEED,
    FLOWERY_WALLPAPER,
    GEMS,
    HEROIC_TIGHTS_OF_PREVENTION,
    PRESENT_GOBLIN_DISGUISE,
    STEAM_LAUNCHER,
)
from gtools.core.growtopia.inventory import Inventory
from gtools.core.growtopia.items_dat import is_seed
from gtools.core.growtopia.packet import TankFlags, TankType
from gtools.core.growtopia.physics.controller import (
    FIST_ID,
    HITBOX,
    PUNCH_REPEAT_MS,
    TOUCH_HOLD_TIMEOUT_MS,
    TOUCH_REACH_PX,
    PlayerController,
    _STATE_EVENT_FLAGS,
)
from gtools.core.growtopia.player import CharacterFlags, CharacterState, Clothing, Player
from gtools.core.growtopia.world import DroppedItem, Tile, TileFlags, World

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


def test_punch_stamps_facing_from_the_punched_tile() -> None:
    """The punch reaction targets the tile -- facing follows its side (avatar+0x61).

    ``sub_14012ECC0`` stamps the render target to the tile centre and
    ``sub_140133A90`` (0x140133B40/0x140133BA4) writes ``avatar+0x61``: left when the
    avatar's centre x is greater than the tile's, right otherwise. The avatar centre
    is at x = 112 here, so tile 5 (160..191) faces right and tiles 1..2 face left.
    """
    session = Session()
    controller = session.controller
    controller.facing_right = False  # facing the wrong way ...

    controller.touch_press(*FIST_TILE)  # ... punching a tile to the right ...
    controller.step()

    assert not (int(session.requests[0].flags) & int(TankFlags.FACING_LEFT))
    assert controller.facing_right

    controller.touch_release()
    while controller.time_ms < PUNCH_REPEAT_MS:  # wait out the punch animation gate
        controller.step()

    controller.touch_press(2, FLOOR_Y)  # ... then a tile to the left flips it back
    controller.step()

    assert int(session.requests[1].flags) & int(TankFlags.FACING_LEFT)
    assert int(session.frames[-1].flags) & int(TankFlags.FACING_LEFT)


def test_reach_uses_the_character_state_range() -> None:
    """Reach = the collision rect expanded by ``state.<punch|build>_range * 32`` px.

    ``HandleTouch`` (0x14041222C) takes the punch range for the Fist and the build
    range otherwise (``sub_1403F2760``/``sub_1403F24C0``), sweeps
    ``collectGridTilesInRect`` over the expanded rect and drops everything else; the
    150 px radius only sets the highlight latch.
    """
    session = Session()
    controller = session.controller
    # rect x = 102..122, y = 226..256; a punch (margin 2 * 32) sweeps tiles 1..5 x 5..9
    assert controller._touch_in_reach(5, FLOOR_Y, FIST_ID)
    assert not controller._touch_in_reach(6, FLOOR_Y, FIST_ID)

    controller.state.punch_range = 4  # a Punch Range mod widens the sweep, not the radius
    assert controller._touch_in_reach(6, FLOOR_Y, FIST_ID)

    # blocks use the build range, so the same tile is out of reach for a placement
    assert not controller._touch_in_reach(6, FLOOR_Y, DIRT)
    controller.state.build_range = 4
    assert controller._touch_in_reach(6, FLOOR_Y, DIRT)


def test_tile_inside_the_radius_but_out_of_reach_sends_nothing() -> None:
    """The 150 px radius is not a reach fallback -- it only sets the highlight latch."""
    session = Session()
    assert session.controller._touch_in_reach(6, FLOOR_Y, FIST_ID) is False
    dx = 6 * 32 + 16 - (session.controller.x + session.controller.width / 2)
    dy = FLOOR_Y * 32 + 16 - (session.controller.y + session.controller.height / 2)
    assert dx * dx + dy * dy < TOUCH_REACH_PX**2  # well inside the latch radius

    session.controller.touch_press(6, FLOOR_Y)
    session.controller.step()
    assert session.requests == []


def test_punching_empty_air_sends_nothing() -> None:
    """An empty tile only punches when another avatar stands on it (HandleTouch tail)."""
    session = Session()
    session.world.get_tile(2, FLOOR_Y).fg_id = 0
    session.controller.touch_press(2, FLOOR_Y)
    session.controller.step()

    assert session.requests == []

    session.world.get_tile(2, FLOOR_Y).bg_id = DIRT  # a background is a target
    session.controller.touch_release()
    session.controller.touch_press(2, FLOOR_Y)
    session.controller.step()
    assert len(session.requests) == 1


def test_planting_a_seed_needs_solid_ground_below() -> None:
    """``IsTileBelowPlantable`` -- "(Can't plant a tree in the air!)" sends nothing."""
    session = Session(hand_item=DIRT_SEED)  # a seed (odd id)
    assert is_seed(DIRT_SEED)

    session.world.get_tile(2, FLOOR_Y).fg_id = 0  # empty, nothing solid below it
    session.controller.touch_press(2, FLOOR_Y)
    session.controller.step()
    assert session.requests == []

    session.world.get_tile(2, FLOOR_Y).fg_id = DIRT  # the tile above the floor is plantable
    session.controller.touch_release()
    session.controller.touch_press(2, FLOOR_Y - 1)
    session.controller.step()
    assert len(session.requests) == 1
    assert session.requests[0].value == DIRT_SEED


def test_placing_a_block_on_a_filled_tile_is_not_applied_locally() -> None:
    """The client sends any item onto a breakable tile and lets the server decide.

    The engine keeps the request (client behaviour) but must not overwrite the
    existing foreground -- only a server broadcast may change a filled tile.
    """
    inventory = Inventory()
    inventory.add(GEMS, 1)  # a non-background, non-seed item
    session = Session(inventory, hand_item=GEMS)

    session.controller.touch_press(*FIST_TILE)
    session.controller.step()

    assert len(session.requests) == 1
    assert session.world.get_tile(*FIST_TILE).fg_id == DIRT


def test_placing_a_background_replaces_only_the_background() -> None:
    """``isItemPlaceOverForegroundType`` -- types 18 / 22 / 23 / 28 go over a filled fg.

    The client compares ``tile->bg_id`` with the held item and aborts before the send
    when it already is that background, so a second tap on the same tile is silent.
    """
    inventory = Inventory()
    inventory.add(FLOWERY_WALLPAPER, 2)
    session = Session(inventory, hand_item=FLOWERY_WALLPAPER)
    tile = session.world.get_tile(*FIST_TILE)
    tile.bg_id = 0

    session.controller.touch_press(*FIST_TILE)
    session.controller.step()

    assert len(session.requests) == 1
    assert tile.bg_id == FLOWERY_WALLPAPER  # the background is applied locally
    assert tile.fg_id == DIRT  # the foreground is untouched

    session.controller.touch_release()
    session.controller.touch_press(*FIST_TILE)
    session.controller.step()
    assert len(session.requests) == 1  # that wallpaper is already there


def test_jump_flag_is_a_one_shot_event() -> None:
    """`JUMP` rides exactly one STATE frame -- it is an event (avatar+0x134), not state.

    Traffic proof (traffic.txt 17:47:50): one `FACING_LEFT|JUMP` frame, then
    `FACING_LEFT` alone while the avatar is still rising with the button held.
    Client code: TryPlaceSeedAtTile ORs 0x80 on every launch (0x1405066DE).
    """
    session = Session()
    controller = session.controller
    controller.step()  # settle on the floor

    controller.set_input(jump=True)
    for _ in range(15):  # the bit waits for the next ~200 ms STATE poll, like the client
        controller.step()

    assert controller.vy < 0.0
    assert sum(1 for p in session.frames if int(p.flags) & int(TankFlags.JUMP)) == 1

    for _ in range(30):  # airborne, button still held
        controller.step()

    assert sum(1 for p in session.frames if int(p.flags) & int(TankFlags.JUMP)) == 1


def test_double_jump_flag_is_a_one_shot_event() -> None:
    """`DOUBLE_JUMPED` is armed on an *airborne* launch only and rides one frame.

    Traffic proof (traffic.txt 17:48:10-11): the grounded first jump carries `JUMP`
    alone, the airborne second carries `JUMP|DOUBLE_JUMPED` once, then the flag is
    gone while still in the air. Client code: onJump ORs 0x4000000 only when
    avatar+0xDC == 0 (0x1404FEE5B skips the branch while grounded; the OR is at
    0x1404FF0D7).
    """
    session = Session(state=CharacterState(flags=CharacterFlags.DOUBLE_JUMP))
    controller = session.controller
    controller.step()  # settle on the floor

    controller.set_input(jump=True)  # grounded launch
    for _ in range(15):  # wait out the STATE poll
        controller.step()

    first = [p for p in session.frames if int(p.flags) & int(TankFlags.JUMP)]
    assert len(first) == 1
    assert not int(first[0].flags) & int(TankFlags.DOUBLE_JUMPED), "grounded launch must not set it"

    controller.set_input(jump=False)
    controller.step()
    controller.set_input(jump=True)  # airborne launch consumes the double-jump token
    for _ in range(15):  # wait out the STATE poll
        controller.step()

    double_frames = [p for p in session.frames if int(p.flags) & int(TankFlags.DOUBLE_JUMPED)]
    assert len(double_frames) == 1
    assert int(double_frames[0].flags) & int(TankFlags.JUMP)  # the launch event rides with it

    for _ in range(20):  # still airborne
        controller.step()

    assert sum(1 for p in session.frames if int(p.flags) & int(TankFlags.DOUBLE_JUMPED)) == 1


def test_forced_send_mask_matches_the_client() -> None:
    """`sendTankState` bypasses its duplicate check for `pkt.flags & 0x10C16740`.

    Verified in the binary at 0x1404F5F30 (`test dword ptr [rbx+18h], 10C16740h`,
    bytes `F7 43 18 40 67 C1 10`). It is exactly these ten bits -- notably NOT
    TILE_CHANGE (0x800), which instead resets the 200 ms poll timer at
    0x1404F5E4C, and not GOT_PUNCHED/TRAMPOLINE/UNK_TILE_CHANGE.
    """
    assert int(_STATE_EVENT_FLAGS) == 0x10C16740


def test_first_state_frame_carries_reset_visual_state() -> None:
    """AvatarPacketSender+0x8C starts at 1 (sub_1404F5DA0): the first STATE has 0x4.

    Client evidence: the first client STATE after OnSpawn/OnSetPos in
    ``.gtools/logs/20260327_163020_app.log`` carries RESET_VISUAL_STATE (then
    RESET_VISUAL_STATE|STANDING on the next poll).
    """
    session = Session()
    session.controller.step()

    assert session.frames, "the first poll sends a STATE frame"
    assert int(session.frames[0].flags) & int(TankFlags.RESET_VISUAL_STATE)


def test_reset_visual_state_is_one_shot_and_teleport_rearms_it() -> None:
    session = Session()
    first = session.controller.build_state_packet()
    assert int(first.flags) & int(TankFlags.RESET_VISUAL_STATE), "sender ctor latch"

    second = session.controller.build_state_packet()
    assert not int(second.flags) & int(TankFlags.RESET_VISUAL_STATE), "consumed at build time"

    # OnSetPos (sub_140501290) re-arms AvatarPacketSender+0x8C; teleport() is its model
    session.controller.teleport(5 * 32 + 6.0, STAND_Y)
    third = session.controller.build_state_packet()
    assert int(third.flags) & int(TankFlags.RESET_VISUAL_STATE)


def test_handle_set_pos_teleports_and_rearms_reset_visual_state() -> None:
    """The server OnSetPos call (sub_140501290) sets the position and the latch."""
    session = Session()
    session.controller.step()  # consume the join latch

    session.controller.handle_set_pos(10 * 32 + 6.0, STAND_Y)

    assert (session.controller.x, session.controller.y) == (10 * 32 + 6.0, STAND_Y)
    assert session.controller.vx == 0.0 and session.controller.vy == 0.0
    pkt = session.controller.build_state_packet()
    assert int(pkt.flags) & int(TankFlags.RESET_VISUAL_STATE)


def test_steam_launcher_clears_is_on_and_sends_tile_activate() -> None:
    world = make_world((STEAM_LAUNCHER, 3, FLOOR_Y - 1, TileFlags.IS_ON))
    packets = []
    controller = PlayerController(world, x=3 * 32 + 6.0, y=(FLOOR_Y - 4) * 32, send=packets.append)

    for _ in range(40):
        controller.step()
        if any(p.type == TankType.TILE_ACTIVATE_REQUEST for p in packets):
            break

    activates = [p for p in packets if p.type == TankType.TILE_ACTIVATE_REQUEST]
    assert len(activates) == 1
    assert (activates[0].int_x, activates[0].int_y) == (3, FLOOR_Y - 1)
    assert activates[0].value == 0, "type 7 carries no item id"
    assert (activates[0].vector_x, activates[0].vector_y) == (0.0, 0.0), "no position stamp"
    assert not (world.get_tile(3, FLOOR_Y - 1).flags & TileFlags.IS_ON), "optimistic IS_ON clear"


def _dropped_at_player(world: World, *, id: int = DIRT, dy: float = 0.0) -> DroppedItem:
    dropped = DroppedItem(id=id, pos=vec2(3 * 32 + 6.0, STAND_Y + dy), amount=1)
    world.dropped.add_item(dropped)
    return dropped


def test_walking_over_a_dropped_object_sends_item_activate_object_request() -> None:
    """The only type-11 sender is the dropped-object collector (0x1403F60E0)."""
    world = make_world()
    dropped = _dropped_at_player(world)
    packets = []
    controller = PlayerController(world, x=3 * 32 + 6.0, y=STAND_Y, send=packets.append)

    controller.step()

    collects = [p for p in packets if p.type == TankType.ITEM_ACTIVATE_OBJECT_REQUEST]
    assert len(collects) == 1
    pkt = collects[0]
    assert pkt.net_id == 0
    assert pkt.value == dropped.uid  # object+0x14
    assert (pkt.vector_x, pkt.vector_y) == (controller.x, controller.y)
    assert pkt.int_x == int(controller.x) + 4 + int(controller.y)  # position stamp
    assert pkt.int_y == 0
    assert pkt.float_var == 0 and pkt.flags == 0
    assert not [p for p in packets if p.type == TankType.ITEM_ACTIVATE_REQUEST]

    frame = next(p for p in packets if p.type == TankType.STATE)
    assert int(frame.flags) & int(TankFlags.OBJECT_COLLECT)


def test_dropped_object_collect_retries_after_three_seconds() -> None:
    world = make_world()
    _dropped_at_player(world)
    packets = []
    controller = PlayerController(world, x=3 * 32 + 6.0, y=STAND_Y, send=packets.append)

    for _ in range(220):  # 3.66 s at 60 Hz
        controller.step()

    collects = [p for p in packets if p.type == TankType.ITEM_ACTIVATE_OBJECT_REQUEST]
    assert len(collects) == 2, "object+0x1C is cleared after 3000 ms (DroppedObject::getScale)"


def test_solid_tile_at_the_object_centre_blocks_collection() -> None:
    """requestCollectDroppedObject requires CanPassThroughTile(tile at x+8, y+8, isBreakTap=1) == 0."""
    world = make_world((DIRT, 3, FLOOR_Y - 1, TileFlags.NONE))
    _dropped_at_player(world)
    packets = []
    controller = PlayerController(world, x=3 * 32 + 6.0, y=STAND_Y, send=packets.append)

    controller.step()

    assert not [p for p in packets if p.type == TankType.ITEM_ACTIVATE_OBJECT_REQUEST]


def _collect_packets(world: World) -> list:
    packets = []
    controller = PlayerController(world, x=3 * 32 + 6.0, y=STAND_Y, send=packets.append)
    controller.step()
    return [p for p in packets if p.type == TankType.ITEM_ACTIVATE_OBJECT_REQUEST]


def test_heroic_tights_block_dirt_but_not_gems() -> None:
    world = make_world()
    world.players[1] = Player(net_id=1, clothing=Clothing(pants=HEROIC_TIGHTS_OF_PREVENTION))
    _dropped_at_player(world)
    assert not _collect_packets(world)

    # 112 (GEMS) is exempt from the Heroic Tights / Magic Magnet gates
    world = make_world()
    world.players[1] = Player(net_id=1, clothing=Clothing(pants=HEROIC_TIGHTS_OF_PREVENTION))
    gems = _dropped_at_player(world, id=GEMS, dy=-1.0)
    assert [p for p in _collect_packets(world) if p.value == gems.uid]


def test_goblin_disguise_face_blocks_all_dropped_object_collection() -> None:
    world = make_world()
    world.players[1] = Player(net_id=1, clothing=Clothing(face=PRESENT_GOBLIN_DISGUISE))
    _dropped_at_player(world)
    assert not _collect_packets(world)
