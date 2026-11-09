"""PlayerController -- the local player's simulation and outbound tile-change flow.

One class owns everything needed to drive a local player:

* the per-tick physics port (formerly ``PhysicsEngine`` + ``PhysicsComponent``):
  input, collision, hazards, water/slide and the STATE frames -- see
  ``docs/netavatar-physics.md``, every ``_``-prefixed method names the client
  function it mirrors;
* the tile-interaction pipeline (the client's ``HandleTouch`` / ``onTouchInput`` /
  ``onTouchHoldTick``): press/hold/release, the per-tile de-duplication, the reach
  gate, the position-stamped ``TILE_CHANGE_REQUEST``, the chained STATE action bits
  (``PUNCH|TILE_CHANGE`` / ``PLACE|TILE_CHANGE``), the optional optimistic
  application and the steam-launcher ``ITEM_ACTIVATE_OBJECT_REQUEST``. See
  ``docs/tile-change-request.md`` for the client evidence.

A controller *is* the local avatar: there is no component registry, no world
subsystem and no attachment step; ``send`` is the single packet sink.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from gtools.baked.items import (
    ABOMINABLE_SNOWMAN_MASK,
    ABOMINABLE_SNOWMAN_SUIT,
    ADVENTURE_BARRIER,
    ADVENTURE_IDOL_GATE,
    ADVENTURE_ITEM_KEY,
    ADVENTURE_ITEM_ROPE,
    ADVENTURE_ROPE_PITON,
    ADVENTURE_TOMB_GATE,
    ANGEL_OF_MERCY_S_WINGS,
    BOB_THE_GROSS_BLOB,
    BUNNY_EGG,
    CARDBOARD_NESSIE,
    CARRIED_GAME_EGG,
    CARRIED_GAME_FLAG,
    CELESTIAL_HALO,
    CHICKEN_PLOW,
    CLAWS_OF_BARKO,
    CLIMBING_BOOTS,
    CLIMBING_PICKS,
    CLIMBING_WALL,
    CLOAK_OF_FALLING_WATERS,
    CLOAK_OF_HOVERATION,
    DA_VINCI_WINGS,
    DARKEST_SKULL_PARASOL,
    DEAR_JOHN_TRACTOR,
    DISPLAY_BOX,
    DOOM_PLOW,
    DRACONIC_ROCKET_PARASOL,
    EZIO_S_BOOTS,
    FISHING_DINGHY,
    FLAMING_FLOATIES,
    FLOATING_LEAF,
    GEMS,
    GIANT_FALLING_SHAMROCK,
    GO_ANYWHERE_SURFBOARD,
    GOLDEN_JET_SKI,
    GRAVITY_WELL,
    GOLDEN_SILK_SCARF,
    GROW_AIR_BALLOON,
    GROW_X_ROCKET_WINGS,
    HARVESTER,
    HARVESTER_OF_SORROWS,
    HARVEST_SCARF,
    HAY,
    HELPING_HAND,
    HEROIC_TIGHTS_OF_PREVENTION,
    HYPERTECH_ANTIGRAVITY_FIELD,
    ICE_CRUST_BLOCK,
    ICE_SKATES_OF_WINTER,
    JET_SKI,
    JET_SKI_CHARIOT,
    LEGENDARY_WINGS,
    LIGHTNING_UMBRELLA,
    LOCKED_ADVENTURE_DOOR,
    MAGIC_CARPET,
    MAGIC_MAGNET,
    MOUNTAIN_BOOTS,
    OIL_PAPER_UMBRELLA,
    PARASOL,
    PINEAPPLE_PLOUGH,
    POSSESSING_SCARF,
    PRESENT_GOBLIN_DISGUISE,
    RAYMAN_S_HAIR,
    RING_OF_WINDS,
    ROYAL_WINTER_SEAL,
    SEA_MONSTER_FLOATIE,
    SILK_SCARF,
    SLEDDING_PENGUIN,
    SLIPPERY_CHEMICAL_COAT,
    SLIPPERY_FLAG_POLE,
    SNOWSHOES,
    SNOW_BLOCK,
    SODA_JETPACK,
    SPACE_THRUSTER_BOOST_BOOTS,
    SPECTRAL_MANTLE,
    STEAM_LAUNCHER,
    STEAMPUNK_ARM,
    SUPER_SQUIRT_GUN_JETPACK,
    SUPER_SQUIRT_GUN_JETPACK_PANTS,
    SURFBOARD,
    SURFBOARD_ELECTRIC_GREEN,
    SURFBOARD_FLAME,
    SURFBOARD_WAVE,
    SWAN_BOAT,
    TARANTULA_LEGS,
    TRANSMATTER_FIELD,
    TURKEY_HAT,
    UNICORN_FLOATIE,
    WATER_WINGS,
    WILL_OF_THE_WILD,
    ZAMGROWNI,
    ZEPHYR_HELM,
)
from gtools.core.growtopia.items_dat import ItemInfoCollisionType, ItemInfoFlag2, ItemInfoType, item_database
from gtools.core.growtopia.packet import TankFlags, TankPacket, TankType
from gtools.core.growtopia.player import CharacterFlags, CharacterState, Clothing
from gtools.core.growtopia.world import BalloonOMaticTile, DoorTile, DroppedItem, LockTile, SeedTile, StormyCloudTile, Tile, TileFlags, World

if TYPE_CHECKING:
    from gtools.core.growtopia.inventory import Inventory

TILE = 32.0
HITBOX = (20.0, 30.0)
FIXED_DT = 1 / 60

# WIND tiles (Conveyor Block / Summer Breeze / ...): validatePhysics pushes the
# horizontal axis toward the tile's facing; walking against the wind is clamped
WIND_OPPOSE_SPEED = 100.0  # kBounceClamp_100p0
WIND_CROSS_ZERO = 1000.0  # kBounceCrossZero_1000p0 (the client's reverse threshold)

# Gravity Well (6772): an active well pulls the nearest avatar toward its centre
GRAVITY_WELL_PULL = 60.0  # findNearestInteractableTileDirection scales the unit vector by 60
GRAVITY_WELL_FALL_SPEEDUP = 3.0  # while falling, the horizontal component is tripled
GRAVITY_WELL_UP_SPEEDUP = 7.0  # a mostly-vertical upward pull is multiplied by 7
GRAVITY_WELL_RANGE_TILES = 5  # items.dat tile_range of the Gravity Well (the search span)

# adventure gate item ids -> avatar+0x2E8 event-flag index (CanPassThroughTile)
_ADVENTURE_GATE_FLAGS = {
    ADVENTURE_BARRIER: 40,
    ADVENTURE_IDOL_GATE: 41,
    ADVENTURE_TOMB_GATE: 42,
}

JUMP_SPEED = 450.0
JUMP_CUT_ACCEL = 5000.0
JUMP_REDUCED_SCALE = 0.6  # water / hay / snow / mud / pole launch
MAX_FALL = 400.0
WATER_VERTICAL_SCALE = 0.3
SLOW_FALL_ACCEL_SCALE = 0.3  # parasols and gliders while the jump button is held
ANTIGRAVITY_ACCEL_SCALE = 0.75 * 0.5  # HYPERTECH field / hover particle
WATER_FLOAT_ACCEL = -12.0  # 400 * -0.03, floatie buoyancy
WATER_FLOAT_FALL_ACCEL = -320.0  # 400 * -0.8, floatie while falling
WATER_FLOAT_MAX_FALL = 40.0  # 400 * 0.1, floatie fall clamp
WATER_FLOAT_DURATION_MS = 3000.0  # kConst_3000p0_D98
MUD_SPEED_SCALE = 0.6
SLIDE_ACCEL_SCALE = 0.15
SLIDE_WALL_BOUNCE = -0.7
DAMAGE_SLIP_WALL_BOUNCE = -0.01  # 0x14095C488, the 0x131 branch of the wall response
BOUNCY_SPEED = 500.0
TRAMPOLINE_SPEED = -800.0
TRAMPOLINE_MOMENTUM_SPEED = -531.25
DAMAGING_KNOCKBACK_SPEED = 300.0  # kConst_300p0_CF8
DAMAGING_LAUNCH_SPEED = -800.0  # kConst_800p0_D08
DAMAGING_LAUNCH_NO_GRAVITY_SPEED = -50.0  # kConst_800p0_D08 * -0.0625
TANK_STATE_POLL_MS = 200.0

_EPS = 1e-4
# NOTE: the client has two collision layers (see docs/collision-port-backlog.md):
#  - movement: WorldView::collectStepTiles + NetAvatar::canMoveXInto/canMoveYInto
#  - interaction: CanPassThroughTile (wall response + climb), `_interaction_blocked`

# -- clothing modifier groups ----------------------------------------------------------
# One group per client modifier branch, shared by the per-tick clothing checks and the
# demo menu so the two cannot drift:
#   * parasol / glide   -- integrateVerticalAxis (0x140510580, `+0xDF` / `+0xE0`)
#   * floatie / vehicle -- updateBlockStateFromPlayerInteraction (0x140509C20)
#   * climb gear        -- handleTileInteraction (0x140501DF0)
#   * slippery / skates -- sub_140505CB0 (the tile-below query)
# Every item id has exactly one `clothing_type`, so worn membership alone decides the mod
# (the client reads the same equipped-item ids).
PARASOL_ITEMS = frozenset({
    PARASOL,
    DRACONIC_ROCKET_PARASOL,
    DARKEST_SKULL_PARASOL,
    LIGHTNING_UMBRELLA,
    OIL_PAPER_UMBRELLA,
    GIANT_FALLING_SHAMROCK,
    RING_OF_WINDS,
    MAGIC_CARPET,
    FLOATING_LEAF,
    CELESTIAL_HALO,
    GROW_X_ROCKET_WINGS,
})
GLIDE_ITEMS = frozenset({
    SODA_JETPACK,
    SUPER_SQUIRT_GUN_JETPACK,
    LEGENDARY_WINGS,
    DA_VINCI_WINGS,
    CLOAK_OF_FALLING_WATERS,
    SPECTRAL_MANTLE,
    CLOAK_OF_HOVERATION,
    ANGEL_OF_MERCY_S_WINGS,
    HELPING_HAND,
    SUPER_SQUIRT_GUN_JETPACK_PANTS,
    SPACE_THRUSTER_BOOST_BOOTS,
    GROW_AIR_BALLOON,
    ZEPHYR_HELM,
    TURKEY_HAT,
    RAYMAN_S_HAIR,
    SILK_SCARF,
    GOLDEN_SILK_SCARF,
    POSSESSING_SCARF,
    HARVEST_SCARF,
    STEAMPUNK_ARM,
})
FLOATIE_ITEMS = frozenset({SEA_MONSTER_FLOATIE, UNICORN_FLOATIE, WATER_WINGS, FLAMING_FLOATIES})
# `sub_14053C770`: the water vehicles that grant the water-float state on entry
WATER_VEHICLE_ITEMS = frozenset({
    SURFBOARD,
    SURFBOARD_FLAME,
    SURFBOARD_WAVE,
    SURFBOARD_ELECTRIC_GREEN,
    FISHING_DINGHY,
    GO_ANYWHERE_SURFBOARD,
    CARDBOARD_NESSIE,
    JET_SKI_CHARIOT,
    SWAN_BOAT,
    JET_SKI,
    GOLDEN_JET_SKI,
})
CLIMB_GEAR_ITEMS = frozenset({CLIMBING_PICKS, CLAWS_OF_BARKO, CLIMBING_BOOTS, 8018, TARANTULA_LEGS, MOUNTAIN_BOOTS, EZIO_S_BOOTS, WILL_OF_THE_WILD})
# the Abominable Snowman pair must be worn together -- see `_slippery_clothing`
SLIPPERY_ITEMS = frozenset({ABOMINABLE_SNOWMAN_SUIT, ABOMINABLE_SNOWMAN_MASK, BOB_THE_GROSS_BLOB, SLIPPERY_CHEMICAL_COAT, SLEDDING_PENGUIN})
_SLIPPERY_ALONE = SLIPPERY_ITEMS - {ABOMINABLE_SNOWMAN_MASK, ABOMINABLE_SNOWMAN_SUIT}
SKATING_ITEMS = frozenset({ICE_SKATES_OF_WINTER})

# -- walk-over item mods (NetAvatar::tryPlaceSeedOrFertilizer, 0x140506910) ------------
# Tree Harvesting shoes: harvest the tree on the tile the avatar walks over.
TREE_HARVESTING_ITEMS = frozenset({DEAR_JOHN_TRACTOR, HARVESTER, HARVESTER_OF_SORROWS, PINEAPPLE_PLOUGH, ZAMGROWNI})
# Chicken Plow / Doom Plow: plant the selected seed while walking (splice on a seed tile).
PLOW_ITEMS = frozenset({CHICKEN_PLOW, DOOM_PLOW})

FIST_ID = 18  # ItemInfoType.FIST -- the hand/punch item (client itemId 0x12)
WRENCH_ID = 32  # ItemInfoType.WRENCH -- the "no item selected" fallback for solid tiles
TOUCH_REACH_PX = 150.0  # HandleTouch hold-path radius (0x1408EE898 = 150.0f)
TOUCH_HOLD_TIMEOUT_MS = 11000.0  # onTouchHoldTick stops the hold after 0x2AF8 ms
# the client gates repeated punches on the punch animation (avatar+0x1A4 == 18);
# 200 ms is the resulting cadence (measured 5/s mode, docs/tile-change-request.md §5)
PUNCH_REPEAT_MS = 200.0

# -- dropped-object collection (ITEM_ACTIVATE_OBJECT_REQUEST, TankType 11) -------------
# The only sender of type 11 is the dropped-object collector, NOT the tile activator
# (`sendTileActivateRequest` 0x1404074F0 sends TILE_ACTIVATE_REQUEST/7 for the steam
# launcher) nor the item activator (`sendItemActivateRequest` 0x140407400 sends
# ITEM_ACTIVATE_REQUEST/10 for the backpack upgrade).
DROPPED_OBJECT_SIZE = 16.0  # DroppedObject::getRect: AABB = (x, y, x + 16, y + 16)
OBJECT_SPAWN_ANIM_MS = 630.0  # DroppedObject::getScale: the spawn scale reaches 1.0 at +630 ms
OBJECT_COLLECT_RETRY_MS = 3000.0  # DroppedObject::getScale clears object+0x1C after 3 s
# Inventory::canAddItem accepts these regardless of inventory space
_ALWAYS_COLLECTIBLE = frozenset({GEMS, CARRIED_GAME_FLAG, CARRIED_GAME_EGG})

# sendTankState's dedupe bypass mask (0x10C16740, verified at 0x1404F5F30): a
# frame carrying any of these event bits is always sent, even when identical
_STATE_EVENT_FLAGS = (
    TankFlags.FIRE_DAMAGE  # 0x40
    | TankFlags.GOT_KILLED  # 0x100
    | TankFlags.PUNCH  # 0x200
    | TankFlags.PLACE  # 0x400
    | TankFlags.RESPAWN  # 0x2000
    | TankFlags.OBJECT_COLLECT  # 0x4000
    | TankFlags.DAMAGE  # 0x10000
    | TankFlags.POWER_UP_PUNCH_START  # 0x400000
    | TankFlags.POWER_UP_PUNCH_END  # 0x800000
    | TankFlags.ACID_DAMAGE  # 0x10000000
)

SendCallback = Callable[[TankPacket], None]
DeathCallback = Callable[["PlayerController", int, int], None]





@dataclass(slots=True)
class CollisionPermissions:
    """Local-player context for the lock/door collision checks.

    Mirrors the ``NetAvatar`` fields the client's permission branches read
    (see ``docs/collision-port-backlog.md`` and ``docs/netavatar-physics.md``
    §12.4):

    * ``user_id`` -- avatar+0x13C, compared against lock owners/access lists;
    * ``guild_id`` / ``guild_rank`` -- avatar+0x94 / avatar+0xA0, the
      ``canDoorPassedThrough`` guild branch (protocol >= 36);
    * ``team`` / ``has_team`` -- avatar+0x288 / avatar+0x294, the FACTION
      gate compares it with the door's team byte;
    * ``adventure_flags`` -- avatar+0x2E8[40/41/42] non-zero; the adventure
      barrier / idol gate / tomb gate toggle on these event flags;
    * ``tile_cache`` -- avatar+0x2E0, the five touched foreground ids scanned
      by ``TileExistsAt`` (the locked adventure door needs
      ``ADVENTURE_ITEM_KEY`` in it);
    * ``friend`` -- avatar+0x2DB0, the friends-entrance state;
    * ``protocol_version`` -- gates the guild branch (client: >= 36).
    """

    user_id: int = 0
    guild_id: int = 0
    guild_rank: int = 0
    team: int = 0
    has_team: bool = False
    adventure_flags: set[int] = field(default_factory=set)
    tile_cache: list[int] = field(default_factory=list)
    friend: bool = False
    protocol_version: int = 999999999


class PlayerController:
    """The local player: per-tick simulation + outbound tile-change/collect requests.

    One instance simulates one local avatar. ``send`` is the single packet sink for
    the STATE frames, the tile-change/activate requests and the dropped-object
    collect request; ``on_death`` is called once per death, before the optional
    auto-respawn.

    The live avatar state mirrors the client ``NetAvatar`` fields documented in
    ``docs/netavatar-physics.md`` (offsets in the field comments).
    """

    def __init__(
        self,
        world: World,
        *,
        net_id: int = 1,
        x: float = 0.0,
        y: float = 0.0,
        state: CharacterState | None = None,
        hitbox: tuple[float, float] = HITBOX,
        fixed_dt: float = FIXED_DT,
        send: SendCallback | None = None,
        on_death: DeathCallback | None = None,
        auto_respawn: bool = True,
        inventory_provider: Callable[[], "Inventory | None"] | None = None,
        optimistic: bool = True,
        hand_item: int = FIST_ID,
    ) -> None:
        self.world = world
        self.net_id = net_id
        self.width, self.height = hitbox
        self.fixed_dt = fixed_dt
        self.send = send
        self.on_death = on_death
        self.auto_respawn = auto_respawn
        self.inventory_provider = inventory_provider or (lambda: None)
        self.optimistic = optimistic
        self.hand_item = hand_item  # the client's selected item (GameState+0x248)
        # dropped-object collection state: client object+0x18 (spawn tick) and
        # +0x1C (activate tick). Objects already in the world are fully spawned.
        self._drop_seen_ms: dict[int, float] = {item.uid: 0.0 for item in world.dropped}
        self._collect_ms: dict[int, float] = {}

        # -- avatar live state (was PhysicsComponent) --------------------------
        self.x = float(x)
        self.y = float(y)
        self.state = state or CharacterState()
        # local-player context for the lock/door branches (avatar+0x13C, +0x94, ...)
        self.permissions = CollisionPermissions()

        self.vx = 0.0
        self.vy = 0.0
        self.facing_right = True
        self.grounded = False
        self.sliding = False
        self.in_water = False

        self.left = False
        self.right = False
        self.jump = False
        self.jump_latch = False
        self.double_jumped = False
        self.climbing = False  # Wall Climbing grip (handleTileInteraction grab)

        self.force_send = False

        # hazards / death -- mirrors NetAvatar::killPlayer (0x1405024E0) and the damaging probes
        self.killed = False  # avatar+0x138 == 2 (dying latch)
        self.killed_pending = False  # one-shot GOT_KILLED event bit (avatar+0x134)
        self.on_fire = False  # one-shot FIRE_DAMAGE event bit
        self.on_acid = False  # one-shot ACID_DAMAGE event bit
        self.damaged = False  # one-shot DAMAGE event bit
        # one-shot action bits (PUNCH / PLACE / TILE_CHANGE) set by the tile-change
        # flow; the client ORs its event mask into the next STATE frame (fillTankStatePacket)
        self.action_flags = TankFlags.NONE
        # avatar+0x131: set by the Y damaging response, cleared by the tile-below query
        # (sub_140505CB0) the moment the avatar touches the ground / by a server snapshot.
        # While set, validatePhysics scales the input acceleration to 0.15 and skips the
        # idle friction lerp (slippery, barely-controllable air state), see `_simulate`.
        self.damage_slip = False

        # vertical-axis state (NetAvatar::integrateVerticalAxis 0x140510580)
        self.water_float = False  # avatar+0x1FB9: water vehicles suppress water gravity for 3 s
        self.water_enter_ms = 0.0  # avatar+0x07C: getTick() when the avatar entered water
        self.mud = False  # avatar+0x0DE: standing in MUD (reduced jump + 0.6 speed cap)
        self.left_ground = False  # avatar+0x140: coyote flag, set when walking off an edge
        self.parasol = False  # avatar+0x0DF per-tick state -> TankFlags.PARASOL (0x40000)
        self.glide = False  # avatar+0x0E0 per-tick state -> TankFlags.UNK_GRAVITY_RELATED (0x80000)

        # last bounce, reported in the STATE frame's int_x/int_y/value (fillTankStatePacket, 0x1404FBEB0)
        self.bounce_tx = -1
        self.bounce_ty = -1
        self.bounce_item = 0

        self.frac_x = 0.0
        self.frac_y = 0.0
        self.next_poll_ms = 0.0
        self.last_key: tuple | None = None
        self.dup_pending = False

        # -- controller clock / touch state ------------------------------------
        # mirrors LevelTouchComponent (TouchInputState): +0xB8 lastTileIndex,
        # +0xC8 holdActive, +0xD8 hold-start tick
        self.tick = 0
        self.time_ms = 0.0
        self.touch_active = False
        self.touch_start_ms = 0.0
        self.touch_last_tile: tuple[int, int] | None = None
        self.punch_ready_ms = 0.0
        self._accumulator = 0.0

        self._check_tile_mod()

    # -- placement -------------------------------------------------------------

    def spawn(self, x: float, y: float, *, state: CharacterState | None = None) -> "PlayerController":
        """Place the local player at ``(x, y)``; optionally replace its CharacterState."""
        if state is not None:
            self.state = state
        self.teleport(x, y)

        return self

    # -- input -----------------------------------------------------------------

    def set_input(self, *, left: bool = False, right: bool = False, jump: bool = False) -> None:
        self.left, self.right = left, right
        if jump != self.jump:
            self.jump_latch = jump
            if jump:
                self._jump()

        self.jump = jump

    def _jump(self) -> None:
        """The jump action -- `TryPlaceSeedAtTile` (0x140506430) + `NetAvatar::onJump` (0x1404FE4A50).

        The launch is only allowed when grounded, inside the `left_ground` coyote window
        (`+0x140`), with the double-jump token (`+0x1F8`, refilled while grounded with
        `CharacterFlags.DOUBLE_JUMP`), with the flying/NOCLIP mod, or while paddling in
        water (`vy >= 0` or the water-float state). Antigravity tiles and slippery poles
        refill the token. The strength is `-450`, reduced to `-270` in water, on hay,
        on snow without SNOWSHOES, in mud and on a slippery pole.
        """
        clothing = self._clothing()
        below = self._below_tile()
        centre = self._centre_tile()
        antigrav = (below is not None and below.fg_id == HYPERTECH_ANTIGRAVITY_FIELD) or (centre is not None and centre.fg_id == HYPERTECH_ANTIGRAVITY_FIELD)
        pole = (centre is not None and centre.fg_id == SLIPPERY_FLAG_POLE) or (below is not None and below.fg_id == SLIPPERY_FLAG_POLE)
        double_jump = bool(self.state.flags & CharacterFlags.DOUBLE_JUMP) and not self.double_jumped
        can_swim = self.in_water and (self.vy > 0.0 or self.water_float)
        can_jump = self.grounded or self.left_ground or double_jump or bool(self.state.flags & CharacterFlags.NOCLIP) or antigrav or pole or can_swim

        # the client consumes the coyote flag on every jump action, successful or not
        self.left_ground = False
        if not can_jump:
            return

        self.climbing = False  # a jump releases the climb grip

        was_grounded = self.grounded
        shoes = clothing.shoes if clothing is not None else 0
        snow_locked = below is not None and below.fg_id == SNOW_BLOCK and shoes != SNOWSHOES
        reduced = self.in_water or self.mud or pole or (below is not None and below.fg_id == HAY) or snow_locked
        # NOTE: `grounded` is intentionally left for `_settle` to re-derive at the end of
        # the tick -- like the STATE-driven launch the recorded fits in §10 analyse, the
        # launch tick then skips gravity and travels the full -450.
        self.vy = -JUMP_SPEED * (JUMP_REDUCED_SCALE if reduced else 1.0)

        # the jump bits are one-shot events (avatar+0x134), not on-wire state:
        # TryPlaceSeedAtTile ORs JUMP on *every* launch (0x1405066DE), and onJump
        # adds DOUBLE_JUMPED for an airborne launch only -- it skips that branch
        # while on-ground (0x1404FEE5B), which is why the first jump never carries
        # it (traffic.txt 17:48:10-11: `JUMP` once, then `JUMP|DOUBLE_JUMPED` once).
        self.action_flags |= TankFlags.JUMP
        if not was_grounded and (double_jump or antigrav or pole):
            self.action_flags |= TankFlags.DOUBLE_JUMPED

        if not was_grounded:
            self.double_jumped = True  # an airborne launch consumes the token (`unk_1F8 = 0`)
        if antigrav or pole:
            self.double_jumped = False  # `unk_1F8 = 1` before onJump refills it

    def teleport(self, x: float, y: float) -> None:
        self.x, self.y = x, y
        self.vx = self.vy = self.frac_x = self.frac_y = 0.0
        self.grounded = self.sliding = self.in_water = False
        # a server position snap (ProcessTankUpdatePacket -> sub_140501290) clears
        # avatar+0x138 (dying) and avatar+0x131 (damage slip state)
        self.killed = False
        self.damage_slip = False
        self._check_tile_mod()

    def update(self, dt: float) -> None:
        self._accumulator += dt
        while self._accumulator >= self.fixed_dt:
            self._accumulator -= self.fixed_dt
            self.step()

    def step(self) -> None:
        """One fixed tick: simulate, send STATE, auto-respawn.

        Touch actions arrive from the input layer (`touch_press` / `touch_hold` /
        `touch_release`) and send immediately (the client's ``HandleTouch`` calls
        ``SendPacketRaw`` itself); their action bits force the next STATE frame out.
        """
        self.tick += 1
        self.time_ms += self.fixed_dt * 1000.0
        self._simulate()
        self._walk_item_mods()  # NetAvatar::tryPlaceSeedOrFertilizer (0x140506910)
        self._collect_dropped_items()  # NetAvatar::collectDroppedItems (0x140506720) in tickAux
        self._send_state()
        self._auto_respawn()

    def _auto_respawn(self) -> None:
        """Mirror the server's answer to `action|respawn_spike` without a server.

        The client sends that text packet from killPlayer and waits for the server to
        snap it back home; with auto_respawn (the default) the controller teleports the
        local player to `World.get_respawn_position()` right after the GOT_KILLED
        frame left in `_send_state`. Callers can turn this off and respawn on
        `on_death` themselves.
        """
        if not (self.killed and self.auto_respawn) or not self.world.is_local_player(self.net_id):
            return

        pos = self.world.get_respawn_position((self.width, self.height))
        if pos is not None:
            self.teleport(*pos)

    def build_state_packet(self) -> TankPacket:
        flags = TankFlags.NONE
        if self.grounded:
            flags |= TankFlags.STANDING
        if not self.facing_right:
            flags |= TankFlags.FACING_LEFT
        if self.sliding:
            flags |= TankFlags.SLIDE
        if self.in_water:
            flags |= TankFlags.SWIM
        # NOTE: JUMP and DOUBLE_JUMPED are *one-shot* events, not state -- they are
        # armed by `_jump` in `action_flags` and ride exactly one built frame. The
        # client never re-sends them while the button stays held or while airborne
        # (traffic.txt 17:47:50: `FACING_LEFT|JUMP` once, then `FACING_LEFT` rising).
        if self.parasol:
            flags |= TankFlags.PARASOL  # avatar+0x0DF
        if self.glide:
            flags |= TankFlags.UNK_GRAVITY_RELATED  # avatar+0x0E0
        # one-shot event bits -- ORed in like avatar+0x134 and consumed by `_send_state`
        if self.killed_pending:
            flags |= TankFlags.GOT_KILLED
        if self.on_fire:
            flags |= TankFlags.FIRE_DAMAGE
        if self.on_acid:
            flags |= TankFlags.ACID_DAMAGE
        if self.damaged:
            flags |= TankFlags.DAMAGE
        # pending tile-change action bits (PUNCH / PLACE | TILE_CHANGE), consumed by `_send_state`
        flags |= self.action_flags

        return TankPacket(
            type=TankType.STATE,
            net_id=self.net_id,
            flags=flags,
            vector_x=float(math.floor(self.x + 0.5)),
            vector_y=float(math.floor(self.y + 0.5)),
            vector_x2=self.vx,
            vector_y2=self.vy,
            float_var=self.state.velocity_in_water,
            value=self.bounce_item,
            int_x=self.bounce_tx,
            int_y=self.bounce_ty,
        )

    def _simulate(self) -> None:
        if self.killed:
            # NetControllerLocal::Update (0x140511A50) skips the physics step while
            # avatar+0x138 (dying) is set -- the corpse does not integrate.
            return

        dt, st = self.fixed_dt, self.state
        self._check_tile_mod()

        # vertical -- NetAvatar::integrateVerticalAxis (0x140510580)
        self.parasol = self.glide = False  # +0xDF/+0xE0 are per-tick wire state
        centre = self._centre_tile()
        if self.grounded:
            self.vy = min(self.vy, 0.0)
        else:
            accel = st.vertical_accel  # base, the water scale is applied below
            max_fall = MAX_FALL
            if accel > 0.0:
                if self.vy < 0.0 and not self.jump_latch:
                    accel += JUMP_CUT_ACCEL
                elif self.damage_slip:
                    # +0x131 branch: += 0.85 * 5000
                    accel += JUMP_CUT_ACCEL * 0.85
                # slow fall: parachute-like items while the jump button is held
                if self.vy > 0.0 and self.jump_latch and not self.in_water and not (self.state.flags & CharacterFlags.ZOMBIE):
                    slow = self._slow_fall_flags()
                    if slow is not None:
                        accel *= SLOW_FALL_ACCEL_SCALE
                        self.parasol, self.glide = slow
                # antigravity field / hover particle
                if centre is not None and centre.fg_id == HYPERTECH_ANTIGRAVITY_FIELD:
                    accel *= ANTIGRAVITY_ACCEL_SCALE
            if self.in_water:
                accel *= WATER_VERTICAL_SCALE
                max_fall = MAX_FALL * WATER_VERTICAL_SCALE
                if self.water_float:
                    # a water vehicle suppresses water gravity entirely (+0x1FB9)
                    accel = 0.0
                    max_fall = 0.0
                if self._is_floatie():
                    accel = WATER_FLOAT_ACCEL
                    if self.vy > 0.0:
                        accel = WATER_FLOAT_FALL_ACCEL
                        self.vy = min(self.vy, WATER_FLOAT_MAX_FALL)
            elif centre is not None and centre.fg_id == SLIPPERY_FLAG_POLE:
                accel *= WATER_VERTICAL_SCALE
                max_fall = MAX_FALL * WATER_VERTICAL_SCALE
            self.vy = min(self.vy + dt * accel, max_fall)
            if accel < 0.0:
                self.vy = max(self.vy, -max_fall)

        # horizontal
        direction = int(self.right) - int(self.left)
        if direction:
            self.facing_right = direction > 0
        elif self.vx:
            self.facing_right = self.vx > 0.0
        cap = st.velocity_in_water if self.in_water else st.max_velocity
        if self.mud:
            cap *= MUD_SPEED_SCALE  # +0xDE, validatePhysics's BYTE6 branch
        step_v = st.horizontal_accel * dt
        if self.sliding and self.vy <= 0.0:
            step_v *= SLIDE_ACCEL_SCALE
        if self.damage_slip:
            # validatePhysics scales the whole input magnitude by 0.15 while +0x131 is
            # set (the scale stacks with the ice slide one)
            step_v *= SLIDE_ACCEL_SCALE
        if self.sliding or self.damage_slip:
            # neither state applies idle damping, and neither decelerates a momentum
            # that is already outside the speed cap -- both client paths skip it
            if direction > 0 and self.vx < cap:
                self.vx = min(self.vx + step_v, cap)
            elif direction < 0 and self.vx > -cap:
                self.vx = max(self.vx - step_v, -cap)
        else:
            self.vx = self._approach(self.vx, direction * cap, step_v)

        self._apply_wind(cap)

        # Gravity Wells fold their pull into the tick's movement delta (the client's
        # probe uses `(vy + pull.y) * dt`), so the pull goes through collision too
        pull_x, pull_y = self._gravity_well_pull()
        step_x = max(-TILE, min(TILE, (self.vx + pull_x) * dt))
        step_y = max(-TILE, min(TILE, (self.vy + pull_y) * dt))
        self._touch(step_x, step_y)
        self._move((self.vx + pull_x) * dt, 0)
        self._move((self.vy + pull_y) * dt, 1)
        self._settle()

        self.x = max(0.0, min(self.world.width * TILE - self.width, self.x))
        self.y = max(0.0, min(self.world.height * TILE - self.height, self.y))

        # the client's tile-step query (sub_140505CB0's sibling) touches CHECKPOINTs from
        # the collision rect; World keeps the MAIN_DOOR fallback and `exit_world` resets it
        self.world.update_local_respawn(self.net_id, self.x, self.y, self.width, self.height)

    def _apply_wind(self, cap: float) -> None:
        """WIND tiles push the avatar -- ``validatePhysics`` tail (0x14050587E).

        The tile at the collision-rect centre (``getTileAtPlayerPosition``) with
        ``item_type == WIND`` (60: Summer Breeze / Clover Fan / Conveyor Block /
        Megawatt Bass Speaker / Space Conveyor Block / Starship Turbo Fan / Winter
        Wind) drives the horizontal axis toward its facing:

        * not flipped (``tile.flags & 0x20`` clear): pushes **right** to the speed
          cap; leftward motion is clamped to ``-100``;
        * flipped (``FLIPPED_X``): pushes **left** to ``-cap``; rightward motion is
          clamped to ``+100``.

        The client computes ``v49 = 100`` and the cross-zero ``1000`` and rebuilds
        the axis triplet (``value = base + C; half = base*0.5 + C``); in water/mud
        the fallback uses the same (already scaled) speed cap as the input.
        """
        direction = self._wind_direction()
        if direction is None:
            return

        if direction:  # flipped -> push left
            if self.vx > WIND_OPPOSE_SPEED:
                self.vx = WIND_OPPOSE_SPEED
            elif self.vx <= 0.0:
                self.vx = -cap
        else:  # push right
            if self.vx < -WIND_OPPOSE_SPEED:
                self.vx = -WIND_OPPOSE_SPEED
            elif self.vx >= 0.0:
                self.vx = cap

    def _gravity_well_pull(self) -> tuple[float, float]:
        """The nearest active Gravity Well's pull vector, in px/s.

        Client evidence: ``sub_140572FB0`` (0x140572FB0) tracks gravity wells
        (item id ``0x1A74`` / 6772 with tile flag ``IS_ON``) in a set on the
        particle manager (``+0x3668``); ``NetAvatar::tickAux`` (0x140503DAE)
        copies that set and calls ``findNearestInteractableTileDirection``
        (0x140510FE0), which picks the nearest well whose centre is inside a
        ``tile_range * 32`` box (the well's ``tile_range`` is 5, read from the
        runtime item record at ``+0x25C``) and returns
        ``normalize(wellCentre - avatarCentre) * 60`` after three modifiers:

        * while falling (``vy > 0``) the horizontal component is tripled;
        * an upward pull is zeroed when the horizontal offset dominates
          (``|dx| > |dy|`` or ``|dx| > 16``);
        * a mostly-vertical upward pull (``|y| > |x|``, ``y < 0``) is multiplied
          by 7.

        The engine folds the result into the tick's movement delta; the pull is
        only active while the well's ``IS_ON`` bit is set.
        """
        centre_x = self.x + self.width / 2.0
        centre_y = self.y + self.height / 2.0
        span = GRAVITY_WELL_RANGE_TILES

        best_delta: tuple[float, float] | None = None
        best_dist2 = float("inf")
        for tx in range(int(centre_x // TILE) - span, int(centre_x // TILE) + span + 1):
            for ty in range(int(centre_y // TILE) - span, int(centre_y // TILE) + span + 1):
                tile = self.world.get_tile(tx, ty)
                if tile is None or tile.fg_id != GRAVITY_WELL or not tile.flags & TileFlags.IS_ON:
                    continue

                item = item_database.get(tile.fg_id)
                reach = float(getattr(item, "tile_range", 0) or 1) * TILE
                dx = tx * TILE + TILE / 2.0 - centre_x
                dy = ty * TILE + TILE / 2.0 - centre_y
                if reach <= abs(dx) or reach <= abs(dy):
                    continue

                dist2 = dx * dx + dy * dy
                if dist2 < best_dist2:
                    best_dist2, best_delta = dist2, (dx, dy)

        if best_delta is None:
            return (0.0, 0.0)

        dx, dy = best_delta
        dist = math.hypot(dx, dy)
        if dist == 0.0:
            return (0.0, 0.0)

        pull_x = dx / dist * GRAVITY_WELL_PULL
        pull_y = dy / dist * GRAVITY_WELL_PULL
        if self.vy > 0.0:
            pull_x *= GRAVITY_WELL_FALL_SPEEDUP
        if pull_y < 0.0 and (abs(dx) > abs(dy) or abs(dx) > 16.0):
            pull_y = 0.0
        if pull_y < 0.0 and abs(pull_y) > abs(pull_x):
            pull_y *= GRAVITY_WELL_UP_SPEEDUP

        return (pull_x, pull_y)

    def _slippery_clothing(self) -> bool:
        """The Slippery mod (''glide on any surface'').

        ``sub_140505CB0`` (the tile-below query) ORs slide clothing into its
        result: Abominable Snowman Mask (7410, hat) + Suit (7408, shirt), Bob The
        Gross Blob (8374, neck), Slippery Chemical Coat (9078, shirt) or Sledding
        Penguin (10404, shoes) -- offsets ``+0x2C6/+0x2C8/+0x2D6/+0x2CC``.
        """
        clothing = self._clothing()
        if clothing is None:
            return False

        if clothing.hat == ABOMINABLE_SNOWMAN_MASK and clothing.shirt == ABOMINABLE_SNOWMAN_SUIT:
            return True

        return bool(self._worn_items() & _SLIPPERY_ALONE)

    def _wearing_skates(self) -> bool:
        """The Skating mod: ``ICE_SKATES_OF_WINTER`` cancels the slide flag."""
        return bool(self._worn_items() & SKATING_ITEMS)

    def _climb_gear(self) -> bool:
        """Wall Climbing gear -- the client checks inventory slots 5/3/7.

        ``handleTileInteraction`` accepts hand ``3588`` Climbing Picks / ``8042``
        Claws of Barko; shoes ``3590`` Climbing Boots / ``8018`` S.P.I.D.E.R.
        Legs / ``9034`` Tarantula Legs / ``5440`` Mountain Boots / ``7094``
        Ezio's Boots; hair ``5712`` Will of the Wild (the client additionally
        requires its toggle bit 8 in ``avatar+0x18C``, not modelled here).
        """
        return bool(self._worn_items() & CLIMB_GEAR_ITEMS)

    def _climb_surface(self) -> Tile | None:
        """The climbable tile at the avatar centre, if the gear/rope allows it."""
        tile = self._centre_tile()
        if tile is None or tile.fg_id <= 0:
            return None

        if tile.fg_id == CLIMBING_WALL:
            return tile if self._climb_gear() else None
        if tile.fg_id == ADVENTURE_ROPE_PITON:
            return tile if ADVENTURE_ITEM_ROPE in self.permissions.tile_cache else None

        return None

    def _try_climb(self) -> bool:
        """Climb grab -- the wall-response branch of ``handleTileInteraction``.

        With ``vy >= 0`` (falling or level), not grounded, the tile at the
        collision-rect centre (``getTileAtPlayerPosition``) must be a
        ``CLIMBING_WALL`` (3586) while the climb gear is worn, or an
        ``ADVENTURE_ROPE_PITON`` (4700) with the Adventure Rope (1694) in the
        avatar's five-slot touch cache (``TileExistsAt``). The grab zeroes both
        axes and sets grounded; while ``climbing`` the tick stays grounded (the
        client's grab sets ``0xDC`` and the tile-step query leaves it set when no
        ground tile is found), so the avatar hangs until it jumps or the centre
        tile stops being climbable.
        """
        if self.climbing or self.vy < 0.0 or self.grounded:
            return False
        if self._climb_surface() is None:
            return False

        self.climbing = True
        self.vx = self.vy = 0.0
        self.grounded = True

        return True

    # -- walk-over item mods (NetAvatar::tryPlaceSeedOrFertilizer) -----------------

    @staticmethod
    def _is_seed_item(item_id: int) -> bool:
        """``isItemSeed`` (0x1403F5B80): the item is a seed (the odd-half of each pair)."""
        item = item_database.get(item_id)

        return item is not None and item.item_type == ItemInfoType.SEED

    def _collision_on(self, tx: int, ty: int) -> bool:
        """``isTileCollisionOn`` (0x140554F60): the tile's collision is active.

        ``IsTileBelowPlantable`` (0x140561B60) resolves ``(tileX, tileY + 1)`` and requires
        this -- a seed needs a solid tile under it.
        """
        return self._collision(tx, ty) != ItemInfoCollisionType.NONE

    def _walk_item_mods(self) -> None:
        """The per-tick walk-over mods -- ``NetAvatar::tryPlaceSeedOrFertilizer`` (0x140506910).

        Verified branches (both additionally gated on the client's ``canAvatarInteract``,
        a state/velocity gate the engine does not model):

        * **Tree Harvesting** shoes (898 Dear John Tractor, 1830 Harvester, 1966 Harvester
          Of Sorrows, 9650 Pineapple Plough, 10504 Zamgrowni): the tile at the player
          position must be a planted seed whose growth has elapsed
          (``World.tree_ready`` -- the client's ``unk5 < elapsed`` test); the request is
          the FIST ``TILE_CHANGE_REQUEST`` (value ``0x12``) -- the same packet as a manual
          punch -- and the server answers with the harvest broadcast. The client also
          bumps its ``axis80`` animation axis here, which the engine has no equivalent
          for.
        * **Chicken Plow / Doom Plow**: only while grounded and moving (``vx != 0``, the
          client's ``horizontalVelocity`` test):
          - an empty centre tile that is not a door, whose tile below has collision on,
            with a seed selected -> send the placement request with the selected seed id;
          - an existing seed tile with an extra that is not already spliced
            (``flags & WAS_SPLICED``) and a seed selected -> send the same request again;
            the server marks the splice (``WILL_SPAWN_SEEDS_TOO``). The client's extra
            ``unk5 > elapsed`` test on this branch only fires for ``RANDOM_GROW`` seeds
            and reads the same unmappable ItemDat field, so it is not modelled.
        """
        clothing = self._clothing()
        if clothing is None:
            return

        tile = self._centre_tile()
        if tile is None:
            return

        if clothing.shoes in TREE_HARVESTING_ITEMS:
            if self.world.tree_ready(tile):
                self.request_punch(tile.pos.x, tile.pos.y)
            return

        if clothing.shoes not in PLOW_ITEMS or not self.grounded or self.vx == 0.0:
            return
        if not self._is_seed_item(self.hand_item):
            return

        tx, ty = tile.pos.x, tile.pos.y
        if tile.fg_id == 0:
            if not isinstance(tile.extra, DoorTile) and self._collision_on(tx, ty + 1):
                self.request_place(self.hand_item, tx, ty)
        elif isinstance(tile.extra, SeedTile) and not tile.flags & TileFlags.WAS_SPLICED:
            self.request_place(self.hand_item, tx, ty, splice=True)

    def _collect_dropped_items(self) -> None:
        """The per-tick dropped-object collect -- ``NetAvatar::collectDroppedItems`` (0x140506720).

        ``NetAvatar::tickAux`` calls this every tick. It walks the world's dropped
        objects, requires the object's spawn animation to be finished
        (``DroppedObject::getScale`` returns 1.0), tests the 16x16 object AABB against the
        player collision rect and then calls ``requestCollectDroppedObject`` -- the only sender
        of ``ITEM_ACTIVATE_OBJECT_REQUEST`` (TankType 11) in the client.

        Objects already present when the controller is built count as fully
        spawned; objects added later keep the client's 630 ms spawn-in gate.
        """
        if self.killed or self.state.flags & CharacterFlags.NOCLIP:
            return

        left, top = self.x, self.y
        right, bottom = self.x + self.width, self.y + self.height
        for item in self.world.dropped:
            if item.uid not in self._drop_seen_ms:
                self._drop_seen_ms[item.uid] = self.time_ms

            if self._drop_scale(item.uid) < 1.0:
                continue

            stamp = self._collect_ms.get(item.uid)
            if stamp is not None:
                if self.time_ms - stamp < OBJECT_COLLECT_RETRY_MS:
                    continue
                del self._collect_ms[item.uid]

            # DroppedObject::getRect: object AABB = (x, y, x + 16, y + 16)
            if item.pos.x + DROPPED_OBJECT_SIZE <= left or right <= item.pos.x:
                continue
            if item.pos.y + DROPPED_OBJECT_SIZE <= top or bottom <= item.pos.y:
                continue

            # NetAvatar::collectDroppedItems: team flag/egg objects are hidden while
            # avatar+0x284[17] == 0xFF (the ctor default) or [18] != 0xFF.
            if item.id in (CARRIED_GAME_FLAG, CARRIED_GAME_EGG):
                continue

            if self._drop_tile_blocks(item) or not self._drop_mod_allows(item):
                continue

            # requestCollectDroppedObject stamps object+0x1C = getTick() before the inventory
            # test, so a rejected collect retries on the 3 s timer.
            self._collect_ms[item.uid] = self.time_ms
            if not self._can_carry_item(item.id):
                continue

            self.request_collect_object(item)

        live = {item.uid for item in self.world.dropped}
        for uid in self._drop_seen_ms.keys() - live:
            self._drop_seen_ms.pop(uid, None)
            self._collect_ms.pop(uid, None)

    def _drop_scale(self, uid: int) -> float:
        """``DroppedObject::getScale`` spawn-in scale: 0 -> 1 over 630 ms (1.0 when done)."""
        spawn = self._drop_seen_ms.get(uid, 0.0)
        if spawn <= 0.0:
            return 1.0
        elapsed = self.time_ms - spawn
        if elapsed <= 0.0:
            return 0.0
        if elapsed >= OBJECT_SPAWN_ANIM_MS:
            return 1.0
        ratio = elapsed / OBJECT_SPAWN_ANIM_MS
        return ratio * ratio

    def _drop_tile_blocks(self, item: DroppedItem) -> bool:
        """The tile at the object centre -- ``getTileAtPosition`` in ``requestCollectDroppedObject``.

        ``CanPassThroughTile(tile, ..., 1)`` must be 0. Display Box / Transmatter
        Field tiles are passable normally but additionally require
        ``canDoorPassedThrough_1`` (the avatar+0x17A owner override is not modelled).
        """
        tx = int((item.pos.x + 8.0) / TILE)
        ty = int((item.pos.y + 8.0) / TILE)
        if item.pos.x + 8.0 < 0.0 or item.pos.y + 8.0 < 0.0 or tx < 0 or ty < 0:
            return False
        tile = self.world.get_tile(tx, ty)
        if tile is None:
            return False
        if self._interaction_blocked(tx, ty):
            return True
        if tile.fg_id in (DISPLAY_BOX, TRANSMATTER_FIELD):
            return not self._lock_check(tile)
        return False

    def _drop_mod_allows(self, item: DroppedItem) -> bool:
        """The three clothing gates of ``requestCollectDroppedObject``.

        The client reads ``NetAvatar::getClothingOrMods(avatar, 1)`` -- the clothing mirror at
        avatar+0x2B4 built by ``NetAvatar::buildClothingMods``: +4 pants, +8 face, +0xA hand.
        Transmuted clothing variants are not modelled (the controller compares the
        worn item ids directly).
        """
        clothing = self._clothing()
        if clothing is None:
            return True
        if clothing.face == PRESENT_GOBLIN_DISGUISE:
            return False
        if clothing.pants == HEROIC_TIGHTS_OF_PREVENTION and item.id != GEMS:
            return False
        if clothing.hand == MAGIC_MAGNET and item.id not in (GEMS, ROYAL_WINTER_SEAL):
            # the client also allows the id in GameState+0xE8 (the local placement
            # preview); the controller maps that slot to the selected hand item
            if self.hand_item not in (0, item.id):
                return False
        return True

    def _can_carry_item(self, item_id: int) -> bool:
        """``Inventory::canAddItem``: one more item fits in the inventory (approx. stack cap)."""
        inventory = self.inventory_provider()
        if inventory is None or inventory.max_slot <= 0:
            return True  # no live inventory -> let the server decide
        if item_id in _ALWAYS_COLLECTIBLE:
            return True
        if item_id in inventory:
            return inventory[item_id].amount < 200
        return len(inventory) < inventory.max_slot

    def _wind_direction(self) -> bool | None:
        """``True`` when the centre tile is a WIND tile facing left, ``False`` for
        right, ``None`` when there is no WIND tile under the avatar."""
        tile = self._centre_tile()
        if tile is None or tile.fg_id <= 0:
            return None

        if item_database.get(tile.fg_id).item_type != ItemInfoType.WIND:
            return None

        return bool(tile.flags & TileFlags.FLIPPED_X)

    @staticmethod
    def _approach(value: float, target: float, step: float) -> float:
        return min(value + step, target) if value < target else max(value - step, target)

    def _vertical_accel(self) -> float:
        return self.state.vertical_accel * WATER_VERTICAL_SCALE if self.in_water else self.state.vertical_accel

    def _touch(self, step_x: float, step_y: float) -> None:
        if self.state.flags & CharacterFlags.NOCLIP:
            return  # avatar+0x188 bit 0 -- no tile interaction at all, not even bounce

        w, h = self.width, self.height
        ignore_spikes = bool(self.state.flags & CharacterFlags.IGNORE_SPIKES)
        ignore_lava = bool(self.state.flags & CharacterFlags.IGNORE_LAVA)

        # X probe -- NetAvatar::handleTileInteraction (0x140501DF0). The probe rect is the
        # collision rect translated by the tick's X displacement; only the hazard and the
        # bounce branches stop the column-major scan, a deadly hit keeps it going.
        for tx, ty in self._overlap(self.x + step_x, self.y, self.x + step_x + w, self.y + h):
            self._cache_touch(tx, ty)
            if not ignore_spikes and self._is_deadly(tx, ty):
                self._kill(tx, ty)
                continue

            hazard = None if ignore_lava else self._damaging_event(tx, ty)
            if hazard is not None:
                self._damaging_x(hazard)
                break

            if self._item_type(tx, ty) == ItemInfoType.BOUNCY:
                self._bounce(tx, ty)
                break

            if self._interaction_blocked(tx, ty):
                if self.damage_slip:
                    self.vx *= DAMAGE_SLIP_WALL_BOUNCE
                else:
                    self.vx = self.vx * SLIDE_WALL_BOUNCE if self.sliding else 0.0
                # the client's climb grab lives in this wall-response branch and can
                # freeze the avatar on a Climbing Wall / roped piton
                if self._try_climb():
                    return

        # Y probe -- NetAvatar vfunc_48 (0x1405021D0). The `+1` px quirk keeps a grounded
        # avatar in contact with whatever it is standing on; deadly returns 1 (continue),
        # damaging/bouncy/launch act and stop the scan.
        probe = 1.0 if (step_y == 0.0 and self.grounded) else step_y
        for tx, ty in self._overlap(self.x, self.y + probe, self.x + w, self.y + probe + h):
            self._cache_touch(tx, ty)
            if not ignore_spikes and self._is_deadly(tx, ty):
                self._kill(tx, ty)
                continue

            hazard = None if ignore_lava else self._damaging_event(tx, ty)
            if hazard is not None:
                self._damaging_y(hazard)
                break

            kind = self._item_type(tx, ty)
            if kind == ItemInfoType.BOUNCY:
                self._bounce(tx, ty)
                break

            launch = self._landing_launch(tx, ty, kind)
            if launch is not None:
                self.vy = launch
                self.grounded = False
                break

    def _is_deadly(self, tx: int, ty: int) -> bool:
        """NetAvatar::handleTileInteraction deadly branch (0x140501E5C..0x140501E94)."""
        tile = self.world.get_tile(tx, ty)
        if tile is None or tile.fg_id <= 0:
            return False

        item = item_database.get(tile.fg_id)
        on = bool(tile.flags & TileFlags.IS_ON)
        return (
            item.item_type == ItemInfoType.DEADLY
            or (bool(item.flags2 & ItemInfoFlag2.TILE_DEADLY_IF_ON) and on)
            or (item.item_type == ItemInfoType.DEADLY_IF_ON and on)
        )

    def _damaging_event(self, tx: int, ty: int) -> TankFlags | None:
        """Damaging branch of both probes; returns the one-shot event it arms."""
        tile = self.world.get_tile(tx, ty)
        if tile is None or tile.fg_id <= 0:
            return None

        kind = item_database.get(tile.fg_id).item_type
        on = bool(tile.flags & TileFlags.IS_ON)
        if kind == ItemInfoType.LAVA or tile.flags & TileFlags.ON_FIRE:
            return TankFlags.FIRE_DAMAGE

        if kind == ItemInfoType.ACID:
            return TankFlags.ACID_DAMAGE

        if kind == ItemInfoType.POINTY or (kind == ItemInfoType.LIGHTNING_CLOUD and on) or (kind == ItemInfoType.STEAM_LAVA_IF_ON and on):
            return TankFlags.DAMAGE

        return None

    def _kill(self, tx: int, ty: int) -> None:
        """NetAvatar::killPlayer (0x1405024E0): latch the dying state and arm GOT_KILLED."""
        if self.killed:
            return  # guarded by avatar+0x138 -- one kill per death

        self.killed = True
        self.killed_pending = True
        self.force_send = True
        if (send := self.on_death) is not None:
            send(self, tx, ty)

    def _apply_damage(self, event: TankFlags) -> None:
        # the event bits ride the next 200 ms poll: unlike the kill (which sets the poll
        # reset bit 0x800 through onPositionSnapped) they do not expedite the send gate
        if event & TankFlags.FIRE_DAMAGE:
            self.on_fire = True
        elif event & TankFlags.ACID_DAMAGE:
            self.on_acid = True
        else:
            self.damaged = True

    def _damaging_x(self, event: TankFlags) -> None:
        """NetAvatar::handleDamagingTileCollision (0x1404FBFF0): invert the collided X
        axis and clamp it to at least 300 px/s away from the tile."""
        self._apply_damage(event)
        self.vx = -self.vx
        if not self.damage_slip:
            if self.vx < 0.0:
                self.vx = min(-DAMAGING_KNOCKBACK_SPEED, self.vx)
            else:
                self.vx = max(DAMAGING_KNOCKBACK_SPEED, self.vx)

    def _damaging_y(self, event: TankFlags) -> None:
        """sub_1404FC0B0 (0x1404FC0B0): -800 launch when falling (or a sign flip while
        rising, -50 without a vertical acceleration axis) plus a same-direction
        horizontal clamp. Also sets avatar+0x131 (the damage slip state): while
        airborne the input acceleration is scaled to 0.15 and idle friction is
        suppressed, until the tile-below query finds ground again (see `_simulate`,
        `_settle`)."""
        if self.state.vertical_accel <= 0.0:
            self.vy = DAMAGING_LAUNCH_NO_GRAVITY_SPEED
        elif self.vy < 0.0:
            self.vy = -self.vy
        else:
            self.vy = DAMAGING_LAUNCH_SPEED

        self.grounded = False
        self._apply_damage(event)

        if self.vx == 0.0:
            self.vx = -1.0 if not self.facing_right else 1.0

        if self.vx < 0.0:
            self.vx = min(-DAMAGING_KNOCKBACK_SPEED, self.vx)
        else:
            self.vx = max(DAMAGING_KNOCKBACK_SPEED, self.vx)

        self.damage_slip = True

    def _bounce(self, tx: int, ty: int) -> None:
        angle = math.atan2(
            self.y + self.height / 2 - (ty * TILE + TILE / 2),
            self.x + self.width / 2 - (tx * TILE + TILE / 2),
        )
        self.vx, self.vy = math.cos(angle) * BOUNCY_SPEED, math.sin(angle) * BOUNCY_SPEED
        self.grounded = False
        self.jump_latch = False
        self.sliding = True
        self._on_tile_bounce_hit(tx, ty)

    def _landing_launch(self, tx: int, ty: int, kind: int | None) -> float | None:
        tile = self.world.get_tile(tx, ty)
        steam = tile is not None and tile.fg_id == STEAM_LAUNCHER and tile.flags & TileFlags.IS_ON
        if kind not in (ItemInfoType.TRAMPOLINE, ItemInfoType.TRAMPOLINE_MOMENTUM) and not steam:
            return

        if self._vertical_accel() <= 0.0 or self.vy < 0.0:
            return

        if ty * TILE < self.y + self.height - _EPS:
            return

        self._on_tile_bounce_hit(tx, ty)
        if kind == ItemInfoType.TRAMPOLINE_MOMENTUM:
            return TRAMPOLINE_MOMENTUM_SPEED

        if steam and tile is not None:
            # the client clears IS_ON and sends the activate request from the landing
            # handler (sendTileActivateRequest -> TILE_ACTIVATE_REQUEST/7), not on the
            # 200 ms tile-change grid and not the dropped-object type 11
            tile.flags &= ~TileFlags.IS_ON
            self.request_tile_activate(tx, ty)

        return TRAMPOLINE_SPEED

    def _on_tile_bounce_hit(self, tx: int, ty: int) -> None:
        """NetAvatar::onTileBounceHit (0x140502AB0): remember the bounce for the next STATE frame."""
        tile = self.world.get_tile(tx, ty)
        self.bounce_tx, self.bounce_ty = tx, ty
        self.bounce_item = tile.fg_id if tile is not None else 0

    def _move(self, delta: float, axis: int) -> None:
        total = delta + (self.frac_x if axis == 0 else self.frac_y)
        steps = math.floor(total + 0.5)
        if axis == 0:
            self.frac_x = total - steps
        else:
            self.frac_y = total - steps
        direction = 1 if steps > 0 else -1
        for _ in range(abs(steps)):
            if axis == 0:
                if self._blocked_x(self.x + direction, self.y, direction):
                    return

                self.x += direction
            else:
                if self._blocked_y(self.x, self.y + direction, direction):
                    return

                self.y += direction

    def _can_enter_x(self, tx: int, ty: int, direction: int) -> bool:
        """Movement-layer X predicate -- collectStepTiles + canMoveXInto (0x1405617E0 / 0x140512A40)."""
        entry = self._active_tile(tx, ty)
        if entry is None:
            return True

        tile, kind = entry
        if kind in (ItemInfoCollisionType.JUMP_THROUGH, ItemInfoCollisionType.JUMP_DOWN):
            return True  # never block horizontally
        if kind == ItemInfoCollisionType.ONE_WAY:
            flipped = bool(tile.flags & TileFlags.FLIPPED_X)
            return (flipped and direction < 0) or (not flipped and direction > 0)

        return not self._blocks_like_client(tile, kind)

    def _can_enter_y(self, tx: int, ty: int, y: float, direction: int) -> bool:
        """Movement-layer Y predicate -- canMoveYInto (0x140512A80). `y` is the step's new top."""
        entry = self._active_tile(tx, ty)
        if entry is None:
            return True

        tile, kind = entry
        if kind == ItemInfoCollisionType.JUMP_THROUGH:
            # land exactly on the platform edge (newBottom == tileTop + 1)
            if direction > 0 and math.floor(y + self.height) == ty * int(TILE) + 1:
                return False
            return True
        if kind == ItemInfoCollisionType.JUMP_DOWN:
            return direction > 0  # can fall through, cannot rise into it
        if kind == ItemInfoCollisionType.ONE_WAY:
            return True  # never collected for the vertical step

        return not self._blocks_like_client(tile, kind)

    def _blocked_x(self, x: float, y: float, direction: int) -> bool:
        edge = x + self.width if direction > 0 else x
        tx = math.floor((edge - direction * _EPS) / TILE)
        return any(
            not self._can_enter_x(tx, ty, direction) for ty in range(math.floor((y + _EPS) / TILE), math.floor((y + self.height - _EPS) / TILE) + 1)
        )

    def _blocked_y(self, x: float, y: float, direction: int) -> bool:
        edge = y + self.height if direction > 0 else y
        ty = math.floor((edge - direction * _EPS) / TILE)
        return any(
            not self._can_enter_y(tx, ty, y, direction) for tx in range(math.floor((x + _EPS) / TILE), math.floor((x + self.width - _EPS) / TILE) + 1)
        )

    def _settle(self) -> None:
        if self.climbing:
            # the grab keeps the avatar grounded; the client's tile-step query leaves
            # 0xDC set while no ground tile is found under the climbable column
            self.grounded = True
            self.vy = 0.0

            return

        feet = self.y + self.height
        row = math.floor((feet + 0.5) / TILE)
        support = any(self._is_ground(tx, row) for tx in self._columns(self.x + 2.0, self.x + self.width - 2.0))
        if support and abs(feet - row * TILE) <= 0.5 and self.vy >= 0.0:
            self.y = row * TILE - self.height
            self.vy = 0.0
            self.grounded = True
            self.double_jumped = False
            # sub_140505CB0 clears avatar+0x131 as soon as the tile-below query finds
            # ground -- touching down restores normal control
            self.damage_slip = False
        else:
            if self.grounded:
                self.left_ground = True  # +0x140 is set when the ground query stops finding floor
            self.grounded = False

    def _check_tile_mod(self) -> None:
        centre = self.world.get_tile(math.floor((self.x + self.width / 2) / TILE), math.floor((self.y + self.height / 2) / TILE))
        if self.climbing and self._climb_surface() is None:
            self.climbing = False  # walked off the column / gear changed
        was_water = self.in_water
        self.in_water = bool(centre and centre.flags & TileFlags.IS_WET)

        row = math.floor((self.y + self.height) / TILE)
        below = [tile for tx in self._columns(self.x + 2.0, self.x + self.width - 2.0) if (tile := self.world.get_tile(tx, row)) is not None]
        # `sub_140505CB0` also honours the Slippery clothing (slide on any surface)
        # and the Skating mod (ICE_SKATES_OF_WINTER forces the slide flag off)
        slippery = not self._wearing_skates() and (self._slippery_clothing() or any(self._is_slippery(tile) for tile in below))
        if slippery:
            self.sliding = True
        elif self.grounded:
            self.sliding = False
        self.mud = any(tile.fg_id > 0 and item_database.get(tile.fg_id).item_type == ItemInfoType.MUD for tile in below)

        self._update_water_state(was_water)

    def _update_water_state(self, was_water: bool) -> None:
        """`updateBlockStateFromPlayerInteraction` (0x140509C20): the water-float state.

        Entering water with a water vehicle (surfboards/boats/JET_SKI/...) turns on
        `water_float` (avatar+0x1FB9) for 3000 ms; FISHING_DINGHY / JET_SKI /
        GOLDEN_JET_SKI keep it while in water. While set, `integrateVerticalAxis`
        zeroes both the water gravity and the fall speed.
        """
        if self.in_water and not was_water:
            self.water_enter_ms = self.time_ms
            if self._has_water_vehicle():
                self.water_float = True
        if not self.in_water:
            self.water_float = False
        elif self.time_ms - self.water_enter_ms > WATER_FLOAT_DURATION_MS and not self._has_water_float_perm():
            self.water_float = False

    # -- clothing / item helpers -------------------------------------------------

    def _clothing(self) -> Clothing | None:
        player = self.world.players.get(self.net_id)
        return player.clothing if player is not None else None

    def _worn_items(self) -> frozenset[int]:
        """The equipped clothing item ids (all slots), for the modifier-group checks."""
        clothing = self._clothing()
        if clothing is None:
            return frozenset()

        return frozenset(item for _, item in clothing if item)

    def _has_water_vehicle(self) -> bool:
        return bool(self._worn_items() & WATER_VEHICLE_ITEMS)

    def _has_water_float_perm(self) -> bool:
        clothing = self._clothing()
        return clothing is not None and clothing.shoes in (FISHING_DINGHY, JET_SKI, GOLDEN_JET_SKI)

    def _is_floatie(self) -> bool:
        clothing = self._clothing()
        if clothing is None:
            return False

        return bool(self._worn_items() & FLOATIE_ITEMS)

    def _slow_fall_flags(self) -> tuple[bool, bool] | None:
        """The two parachute groups of integrateVerticalAxis (0x140510580).

        Returns `(parasol, glide)` -- `parasol` maps to avatar+0xDF and the PARASOL
        event bit (0x40000), `glide` to avatar+0xE0 and UNK_GRAVITY_RELATED (0x80000).
        """
        worn = self._worn_items()
        if worn & PARASOL_ITEMS:
            return True, False
        if worn & GLIDE_ITEMS:
            return False, True

        return None

    def _centre_tile(self) -> Tile | None:
        return self.world.get_tile(math.floor((self.x + self.width / 2) / TILE), math.floor((self.y + self.height / 2) / TILE))

    def _below_tile(self) -> Tile | None:
        """First foreground tile at the row under the feet (the jump/mud surface)."""
        row = math.floor((self.y + self.height) / TILE)
        for tx in self._columns(self.x + 2.0, self.x + self.width - 2.0):
            tile = self.world.get_tile(tx, row)
            if tile is not None and tile.fg_id > 0:
                return tile

        return None

    def _collision(self, tx: int, ty: int) -> ItemInfoCollisionType:
        tile = self.world.get_tile(tx, ty)
        if tile is None or tile.fg_id <= 0:
            return ItemInfoCollisionType.NONE

        kind = item_database.get(tile.fg_id).collision_type
        on = bool(tile.flags & TileFlags.IS_ON)
        if (kind == ItemInfoCollisionType.COLLIDE_IF_ON and not on) or (kind == ItemInfoCollisionType.COLLIDE_IF_OFF and on):
            return ItemInfoCollisionType.NONE

        return kind

    def _active_tile(self, tx: int, ty: int) -> tuple[Tile, ItemInfoCollisionType] | None:
        """The tile and its state-aware collision kind (`None` when the slot is empty)."""
        tile = self.world.get_tile(tx, ty)
        if tile is None or tile.fg_id <= 0:
            return None

        return tile, self._collision(tx, ty)

    def _interaction_blocked(self, tx: int, ty: int) -> bool:
        """CanPassThroughTile (0x140554C10, isBreakTap=1) -- the wall response + climb gate."""
        entry = self._active_tile(tx, ty)
        if entry is None:
            return False

        tile, kind = entry
        if kind in (ItemInfoCollisionType.JUMP_THROUGH, ItemInfoCollisionType.JUMP_DOWN, ItemInfoCollisionType.ONE_WAY):
            return False  # probes only, never a wall response
        return self._blocks_like_client(tile, kind)

    def _blocks_like_client(self, tile: Tile, kind: ItemInfoCollisionType) -> bool:
        """The per-type switch of CanPassThroughTile (1 = blocking/interactive)."""
        if kind == ItemInfoCollisionType.NONE:
            return False
        if kind == ItemInfoCollisionType.ONE_WAY:
            return False  # directional, never collected for the vertical step
        if kind == ItemInfoCollisionType.GATEWAY:
            return not self._gateway_open(tile)
        if kind == ItemInfoCollisionType.VIP_DOOR:
            return not self._vip_door_open(tile)
        if kind == ItemInfoCollisionType.FRIEND_ENTRANCE:
            return not self._friend_entrance_open(tile)
        if kind == ItemInfoCollisionType.ADVENTURE:
            return not self._adventure_open(tile)
        if kind == ItemInfoCollisionType.FACTION:
            return not self._faction_open(tile)
        if kind == ItemInfoCollisionType.GUILD:
            return not self._guild_open(tile)
        if kind == ItemInfoCollisionType.CLOUD:
            # client reads extra+0x140; a cloud without its extra blocks too
            extra = tile.extra
            return not isinstance(extra, StormyCloudTile) or extra.is_solid > 0
        return True  # FULL and the state-gated COLLIDE_IF variants

    def _is_ground(self, tx: int, ty: int) -> bool:
        """Ground support (sub_140564570 with a7=1): blocking tiles except JUMP_DOWN."""
        entry = self._active_tile(tx, ty)
        if entry is None or entry[1] == ItemInfoCollisionType.JUMP_DOWN:
            return False
        return self._blocks_like_client(*entry)

    def _cache_touch(self, tx: int, ty: int) -> None:
        """Record a touched tile in the five-slot cache scanned by ``TileExistsAt``.

        The client keeps the last five tiles the avatar touched at avatar+0x2E0
        and ``TileExistsAt`` (0x140519D80) only compares their foreground ids.
        The adventure key gate reads this cache, so the controller tracks the
        same ids (most recent last, duplicates moved to the back).
        """
        tile = self.world.get_tile(tx, ty)
        if tile is None or tile.fg_id <= 0:
            return

        cache = self.permissions.tile_cache
        if tile.fg_id in cache:
            cache.remove(tile.fg_id)
        cache.append(tile.fg_id)
        del cache[:-5]

    # -- lock / door permissions (CanPassThroughTile + canDoorPassedThrough) ------

    def _lock_passes(self, extra, tile: Tile | None, is_break_tap: bool) -> bool:
        """canDoorPassedThrough (0x140557A20).

        Pass when the tile is open to public, when break-tapping one's own lock,
        through the guild branches (protocol >= 36, lock guild id at extra+0xF8),
        or when the user id is in the lock's access list. ``extra`` may be any
        lock-shaped extra (``LockTile``, ``VipEntranceTile``,
        ``FriendsEntranceTile``); the door-state byte is its first serialized
        byte (client TileExtra+0x09, bits 0x40/0x80).
        """
        if tile is not None and tile.flags & TileFlags.IS_OPEN_TO_PUBLIC:
            return True
        if extra is None or not hasattr(extra, "owner_uid"):
            return False

        perms = self.permissions
        if is_break_tap and perms.user_id == extra.owner_uid:
            return True

        guild_id = getattr(extra, "guild_id", 0)
        if perms.protocol_version >= 36 and guild_id:
            if perms.guild_id == guild_id:
                state = getattr(extra, "door_flags", 0)
                if state & 0x40:
                    if state & 0x80:
                        return True
                elif state & 0x80 and 1 <= perms.guild_rank <= 2:
                    return True
                if state & 0x40 and perms.guild_rank == 2:
                    return True

        return perms.user_id in getattr(extra, "access_uids", ())

    def _lock_check(self, tile: Tile) -> bool:
        """canDoorPassedThrough_1 (0x140555950).

        The tile's own lock extra wins; otherwise the tile's ``parent_index``
        lock is used; otherwise the world lock. The resolved lock is checked
        with ``isBreakTap=1`` (the client forces it).
        """
        extra = tile.extra
        world_lock = self.world.get_world_lock()
        if not isinstance(extra, LockTile) and not tile.parent_index and world_lock is None:
            return True  # nothing locks this tile -> pass
        if not isinstance(extra, LockTile):
            index = tile.parent_index
            if not index and world_lock is not None:
                index = self.world.index_tile(world_lock.pos)
            tile = self.world.get_tile(index)
            if tile is None:
                return False
            extra = tile.extra
        return self._lock_passes(extra, tile, True)

    @staticmethod
    def _guild_required_rank(extra) -> int:
        """getGuildDoorRequiredRank (0x140551E30): extra+0x09 door bits -> 0..3."""
        if extra is None:
            return 3
        state = getattr(extra, "door_flags", 0)
        if state & 0x40:
            if state & 0x80:
                return 0
        elif state & 0x80:
            return 1
        return 2 if state & 0x40 else 3

    def _gateway_open(self, tile: Tile) -> bool:
        """GATEWAY: ``canDoorPassedThrough_1`` or the public flag."""
        return bool(tile.flags & TileFlags.IS_OPEN_TO_PUBLIC) or self._lock_check(tile)

    def _vip_door_open(self, tile: Tile) -> bool:
        """VIP_DOOR: ``canDoorPassedThrough(extra, userID, tile, 1)``; no extra blocks."""
        if tile.extra is None:
            return False
        return self._lock_passes(tile.extra, tile, True)

    def _friend_entrance_open(self, tile: Tile) -> bool:
        """FRIEND_ENTRANCE -- canFriendEntrancePassedThrough (0x1405587B0).

        The lock/access path runs with ``isBreakTap=0``; then the extra's
        ``placedTimestamp`` (avatar-side init 1) must be 1 and either the
        friend state (avatar+0x2DB0 + a world owner) or the world owner's own
        user id must hold.
        """
        extra = tile.extra
        if extra is None:
            return False

        perms = self.permissions
        owner_uid = self.world.get_owner_user_id()
        friend_state = perms.friend and owner_uid >= 0
        if self._lock_passes(extra, tile, False):
            return True
        if getattr(extra, "placed_timestamp", 0) != 1:
            return False
        if not friend_state and perms.user_id != owner_uid:
            return False
        return True

    def _adventure_open(self, tile: Tile) -> bool:
        """ADVENTURE branch of CanPassThroughTile.

        ``LOCKED_ADVENTURE_DOOR`` needs the adventure key in the avatar's touch
        cache (``TileExistsAt`` + ``ADVENTURE_ITEM_KEY``); the barrier / idol /
        tomb gates toggle on the avatar+0x2E8[40/41/42] event flags.
        """
        perms = self.permissions
        if tile.fg_id == LOCKED_ADVENTURE_DOOR:
            return ADVENTURE_ITEM_KEY in perms.tile_cache

        flag = _ADVENTURE_GATE_FLAGS.get(tile.fg_id)
        if flag is None:
            return False  # unknown ADVENTURE tile -> block
        on = bool(tile.flags & TileFlags.IS_ON)
        if flag in perms.adventure_flags:
            return not on  # event flag set: open while IS_ON is clear
        return on  # otherwise: open while IS_ON is set

    def _faction_open(self, tile: Tile) -> bool:
        """FACTION branch: team byte (extra+0x80), public flag, access list."""
        perms = self.permissions
        extra = tile.extra
        team = extra.team_type if isinstance(extra, BalloonOMaticTile) else 0
        public = bool(tile.flags & TileFlags.IS_OPEN_TO_PUBLIC)
        if perms.has_team:
            if public:
                return perms.team == team
            return self._lock_check(tile) and perms.team == team
        if not public:
            return self._lock_check(tile)
        return True

    def _guild_open(self, tile: Tile) -> bool:
        """GUILD branch: guild id/rank gate, then the lock path, then public."""
        extra = tile.extra
        if not isinstance(extra, LockTile):
            return False

        perms = self.permissions
        guild_ok = bool(extra.guild_id) and perms.guild_id == extra.guild_id and perms.guild_rank >= self._guild_required_rank(extra)
        return guild_ok or self._lock_check(tile) or bool(tile.flags & TileFlags.IS_OPEN_TO_PUBLIC)

    def _item_type(self, tx: int, ty: int) -> int | None:
        tile = self.world.get_tile(tx, ty)
        return int(item_database.get(tile.fg_id).item_type) if tile and tile.fg_id > 0 else None

    @staticmethod
    def _is_slippery(tile: Tile | None) -> bool:
        if tile is None or tile.fg_id <= 0:
            return False

        return (tile.fg_id == ICE_CRUST_BLOCK and not (tile.flags & TileFlags.IS_ON)) or item_database.get(tile.fg_id).item_type == ItemInfoType.ICE

    @staticmethod
    def _columns(left: float, right: float) -> range:
        return range(math.floor(left / TILE), math.floor(right / TILE) + 1)

    def _overlap(self, left: float, top: float, right: float, bottom: float):
        for tx in range(math.floor((left + _EPS) / TILE), math.floor((right - _EPS) / TILE) + 1):
            for ty in range(math.floor((top + _EPS) / TILE), math.floor((bottom - _EPS) / TILE) + 1):
                tile = self.world.get_tile(tx, ty)
                if tile is not None and tile.fg_id > 0:
                    yield tx, ty

    # -- tile interactions (the client's HandleTouch pipeline) -------------------

    def touch_press(self, tx: int, ty: int) -> None:
        """Button press on the tile at ``(tx, ty)`` -- the client's ``onTouchInput``.

        Arms the hold, resets the per-tile de-duplication (the client writes
        ``lastTileIndex = -1``) and runs the full tap action (``isBreakTap = true``).
        """
        self.touch_active = True
        self.touch_start_ms = self.time_ms
        self.touch_last_tile = None
        self._handle_touch(tx, ty, is_break_tap=True)

    def touch_hold(self, tx: int, ty: int) -> None:
        """Held-button tick -- the client's ``onTouchHoldTick`` (runs per frame).

        The client re-runs the touch at the cached cursor position while the button
        is held, stops after ``TOUCH_HOLD_TIMEOUT_MS`` (11 s) and uses the lighter
        ``isBreakTap = false`` branch of ``HandleTouch``.
        """
        if not self.touch_active:
            return

        if self.time_ms - self.touch_start_ms > TOUCH_HOLD_TIMEOUT_MS:
            self.touch_release()
            return

        self._handle_touch(tx, ty, is_break_tap=False)

    def touch_release(self) -> None:
        """Button release -- the client's ``OnTouchEnd``."""
        self.touch_active = False
        self.touch_start_ms = 0.0

    def _handle_touch(self, tx: int, ty: int, *, is_break_tap: bool) -> None:
        """``HandleTouch`` (0x140411CF0): the gates, then the request.

        Verified client behaviour:

        * the tile is resolved from the cursor (``getTileAtPosition``);
        * **per-tile de-duplication** -- ``if (item_type != 0 && lastTileIndex ==
          tile) return``; the Fist's ``item_type`` is ``ItemInfoType.FIST`` (0), so
          the hand is the only item allowed to re-trigger the same tile (this is
          what lets a held button keep punching);
        * **reach** -- the tile must overlap the collision rect expanded by
          ``(levelReach + 2)`` tiles or be within ``0x1408EE898`` = 150 px of the
          avatar centre (the flags2 radius variant is gated on dead item 9638);
        * **item** -- the hand item (client ``GameState+0x248``); 0 falls back to
          ``WRENCH`` (32) on solid tiles, otherwise ``FIST`` (18);
        * **hold** ticks never place -- only the tap branch prepares a placement
          (``beginPlaceTile`` -> ``PLACE|TILE_CHANGE``); repeated punches are gated
          by the punch animation (``avatar+0x1A4 == 18``), modelled here with
          ``PUNCH_REPEAT_MS``;
        * **seeds are validated locally, not sent differently** -- for a seed
          (``isItemSeed``) on an empty tile the client requires
          ``IsTileBelowPlantable`` and otherwise aborts with "(Can't plant a tree in
          the air!)" without sending; the request itself is the same
          ``TILE_CHANGE_REQUEST`` as a block placement (docs/02_packet -- the
          ``hasExtraFloat``/splice field is behind the protocol kill switch). A seed
          placed on an existing seed tile (or ``BUNNY_EGG``) is the *splice* case.
        """
        if self.killed:
            return

        tile = self.world.get_tile(tx, ty)
        if tile is None:
            return

        item_id = self.hand_item or (WRENCH_ID if tile.fg_id else FIST_ID)
        item = item_database.get(item_id)

        if item.item_type != ItemInfoType.FIST and self.touch_last_tile == (tx, ty):
            return  # the client ignores a repeated touch on the same tile for items
        self.touch_last_tile = (tx, ty)

        if not self._touch_in_reach(tx, ty):
            return

        if item.item_type == ItemInfoType.FIST:
            # the client refreshes the local action result every hold tick and sends
            # a punch whenever the punch animation is not running (0x1A4 != 18)
            if self.time_ms < self.punch_ready_ms:
                return

            self.punch_ready_ms = self.time_ms + PUNCH_REPEAT_MS

        elif item.item_type == ItemInfoType.WRENCH:
            return  # the wrench never places; it only opens the lock/edit paths

        elif not is_break_tap:
            return  # hold ticks skip the tap branch's placement preparation

        if self._is_seed_item(item_id):
            if tile.fg_id == 0 and not self._collision_on(tx, ty + 1):
                return  # "(Can't plant a tree in the air!)" -- the client sends nothing
            if isinstance(tile.extra, SeedTile) or tile.fg_id == BUNNY_EGG:
                self.request_change(item_id, tx, ty, splice=True)  # second seed -> splice
                return

        self.request_change(item_id, tx, ty)

    def _touch_in_reach(self, tx: int, ty: int) -> bool:
        """HandleTouch reach gate (model of the rect + radius checks)."""
        margin = 2 * TILE  # client: (levelReach + 2) tiles; levelReach defaults to 0
        tile_left, tile_top = tx * TILE, ty * TILE
        if self.x - margin < tile_left + TILE and self.x + self.width + margin > tile_left and self.y - margin < tile_top + TILE and self.y + self.height + margin > tile_top:
            return True

        # the client's flags2 radius branch (70.4/166.4/102.4 px) is gated on the dead
        # null item 9638 + a mod item, so only the 150 px radius is modelled
        dx = tile_left + TILE / 2 - (self.x + self.width / 2)
        dy = tile_top + TILE / 2 - (self.y + self.height / 2)
        return dx * dx + dy * dy <= TOUCH_REACH_PX * TOUCH_REACH_PX

    # -- outbound tile changes ---------------------------------------------------

    def request_punch(self, tx: int, ty: int) -> None:
        """Punch/break ``(tx, ty)`` -- ``NetAvatar::punchTile`` (0x1404FFC20)."""
        self.request_change(FIST_ID, tx, ty)

    def request_place(self, id: int, tx: int, ty: int, *, splice: bool = False, item_on_tree: int = 0) -> None:
        """Place ``id`` at ``(tx, ty)`` (seed planting uses ``splice``/``item_on_tree``)."""
        self.request_change(id, tx, ty, splice=splice, item_on_tree=item_on_tree)

    def request_change(self, id: int, tx: int, ty: int, *, splice: bool = False, item_on_tree: int = 0) -> None:
        """Send ``TILE_CHANGE_REQUEST`` and arm the chained STATE frame.

        ``sendTileChangeRequest`` (0x140407570) stamps the player position and
        ``FACING_LEFT`` and puts the used item id in ``value``. The event mask gets
        the action bits and forces the next STATE frame out: ``PUNCH|TILE_CHANGE``
        for the FIST (``HandleTileActionResult``) and ``PLACE|TILE_CHANGE`` for a
        placement (``beginPlaceTile``).
        """
        flags = TankFlags.FACING_LEFT if not self.facing_right else TankFlags.NONE

        if id == FIST_ID:
            self.bounce_tx, self.bounce_ty = tx, ty  # punchTile stamps +0xD0/+0xD4
            self.bounce_item = 0  # ... and +0x17C (fillTankStatePacket int_x/int_y/value)
            self.action_flags |= TankFlags.TILE_CHANGE | TankFlags.PUNCH
        else:
            self.action_flags |= TankFlags.TILE_CHANGE | TankFlags.PLACE
            if self.optimistic:
                self._apply_optimistic(id, tx, ty, flags, splice=splice, item_on_tree=item_on_tree)

        self.force_send = True

        if self.send is None:
            return

        self.send(
            TankPacket(
                type=TankType.TILE_CHANGE_REQUEST,
                net_id=0,
                flags=flags,
                value=id,
                int_x=tx,
                int_y=ty,
                vector_x=self.x,
                vector_y=self.y,
            )
        )

    def request_tile_activate(self, tx: int, ty: int) -> None:
        """Send ``TILE_ACTIVATE_REQUEST`` (TankType 7) for the tile at ``(tx, ty)``.

        ``sendTileActivateRequest`` (0x1404074F0) is the client's tile activator:
        the 56-byte packet is zeroed except ``type``, ``int_x`` = tile->tileX and
        ``int_y`` = tile->tileY. It carries no ``value`` and no position stamp.
        The steam launcher's landing branch is its only gameplay caller; it is a
        different packet from ``ITEM_ACTIVATE_OBJECT_REQUEST`` (11).
        """
        if self.send is None:
            return

        self.send(TankPacket(type=TankType.TILE_ACTIVATE_REQUEST, net_id=0, int_x=tx, int_y=ty))

    def request_collect_object(self, dropped: DroppedItem) -> None:
        """Send ``ITEM_ACTIVATE_OBJECT_REQUEST`` (TankType 11) for a dropped object.

        Evidence: ``requestCollectDroppedObject`` (0x1403F60E0), the sole type-11 sender, called
        by ``NetAvatar::collectDroppedItems`` (0x140506720) from ``NetAvatar::tickAux``. The
        56-byte packet is zeroed except:

        * ``value`` -- the object uid (object+0x14);
        * ``vector_x`` / ``vector_y`` -- the avatar collision top-left;
        * ``int_x`` -- ``(int)posx + 4 + (int)posy`` (a server position stamp);
        * ``int_y`` -- 0.

        ``net_id`` is 0. The client also ORs ``OBJECT_COLLECT`` (0x4000) into the
        STATE event mask via ``sub_1404F71C0``; ``_STATE_EVENT_FLAGS`` lets that
        bit ride the next 200 ms STATE frame past the dedupe.
        """
        self.action_flags |= TankFlags.OBJECT_COLLECT
        if self.send is None:
            return

        self.send(
            TankPacket(
                type=TankType.ITEM_ACTIVATE_OBJECT_REQUEST,
                net_id=0,
                value=dropped.uid,
                vector_x=self.x,
                vector_y=self.y,
                int_x=int(self.x) + 4 + int(self.y),
                int_y=0,
            )
        )

    def _apply_optimistic(self, id: int, tx: int, ty: int, flags: TankFlags, *, splice: bool = False, item_on_tree: int = 0) -> None:
        """Apply the change locally (the server broadcast reconciles later)."""
        inventory = self.inventory_provider()
        if inventory is None:
            return

        tile = self.world.get_tile(tx, ty)
        if tile is None:
            return

        self.world.tile_change(
            tile,
            inventory,
            id=id,
            flags=flags,
            net_id=self.net_id,
            splice=splice,
            should_take_item=True,
            item_on_tree=item_on_tree,
        )

    # -- STATE frame -------------------------------------------------------------

    def _send_state(self) -> None:
        send = self.send
        if send is None:
            return

        if self.force_send:
            self.force_send = False
            self.next_poll_ms = 0.0
        if self.time_ms < self.next_poll_ms:
            return

        self.next_poll_ms = self.time_ms + TANK_STATE_POLL_MS

        pkt = self.build_state_packet()
        # the client memcmps the whole 56-byte frame; compare every field we fill
        key = (pkt.net_id, int(pkt.flags), pkt.vector_x, pkt.vector_y, pkt.vector_x2, pkt.vector_y2, pkt.float_var, pkt.value, pkt.int_x, pkt.int_y)

        # fillTankStatePacket consumes avatar+0x134 and the bounce tile while it *builds*
        # the frame -- even when the send gate then drops it -- so the one-shot bits
        # (incl. JUMP/DOUBLE_JUMPED) ride exactly one attempt
        self.killed_pending = self.on_fire = self.on_acid = self.damaged = False
        self.action_flags = TankFlags.NONE
        self.bounce_tx = self.bounce_ty = -1
        self.bounce_item = 0

        if key != self.last_key:
            self.last_key = key
            self.dup_pending = True
        elif self.dup_pending:
            self.dup_pending = False
        elif not (int(pkt.flags) & int(_STATE_EVENT_FLAGS)):
            return

        send(pkt)
