import math
from collections.abc import Callable
from dataclasses import dataclass, field

from gtools.baked.items import (
    ADVENTURE_BARRIER,
    ADVENTURE_IDOL_GATE,
    ADVENTURE_ITEM_KEY,
    ADVENTURE_TOMB_GATE,
    ANGEL_OF_MERCY_S_WINGS,
    CARDBOARD_NESSIE,
    CELESTIAL_HALO,
    CLOAK_OF_FALLING_WATERS,
    CLOAK_OF_HOVERATION,
    DA_VINCI_WINGS,
    DARKEST_SKULL_PARASOL,
    DRACONIC_ROCKET_PARASOL,
    FISHING_DINGHY,
    FLAMING_FLOATIES,
    FLOATING_LEAF,
    GIANT_FALLING_SHAMROCK,
    GO_ANYWHERE_SURFBOARD,
    GOLDEN_JET_SKI,
    GOLDEN_SILK_SCARF,
    GROW_AIR_BALLOON,
    GROW_X_ROCKET_WINGS,
    HARVEST_SCARF,
    HAY,
    HELPING_HAND,
    HYPERTECH_ANTIGRAVITY_FIELD,
    ICE_CRUST_BLOCK,
    JET_SKI,
    JET_SKI_CHARIOT,
    LEGENDARY_WINGS,
    LIGHTNING_UMBRELLA,
    LOCKED_ADVENTURE_DOOR,
    MAGIC_CARPET,
    OIL_PAPER_UMBRELLA,
    PARASOL,
    POSSESSING_SCARF,
    RAYMAN_S_HAIR,
    RING_OF_WINDS,
    SEA_MONSTER_FLOATIE,
    SILK_SCARF,
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
    TURKEY_HAT,
    UNICORN_FLOATIE,
    WATER_WINGS,
    ZEPHYR_HELM,
)
from gtools.core.growtopia.items_dat import ItemInfoCollisionType, ItemInfoFlag2, ItemInfoType, item_database
from gtools.core.growtopia.packet import TankFlags, TankPacket, TankType
from gtools.core.growtopia.player import CharacterFlags, CharacterState, Clothing
from gtools.core.growtopia.world import BalloonOMaticTile, LockTile, StormyCloudTile, Tile, TileFlags, World

TILE = 32.0
HITBOX = (20.0, 30.0)
FIXED_DT = 1 / 60

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
# `sub_14053C770`: the water vehicles that grant the water-float state on entry
_WATER_VEHICLES = {
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
}

StateCallback = Callable[[TankPacket], None]
DeathCallback = Callable[["PhysicsComponent", int, int], None]


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


@dataclass(slots=True)
class PhysicsComponent:
    net_id: int
    x: float
    y: float
    state: CharacterState = field(default_factory=CharacterState)
    on_state: StateCallback | None = None
    on_death: DeathCallback | None = None
    permissions: CollisionPermissions = field(default_factory=CollisionPermissions)

    vx: float = 0.0
    vy: float = 0.0
    facing_right: bool = True
    grounded: bool = False
    sliding: bool = False
    in_water: bool = False

    left: bool = False
    right: bool = False
    jump: bool = False
    jump_latch: bool = False
    double_jumped: bool = False

    force_send: bool = False

    # hazards / death -- mirrors NetAvatar::killPlayer (0x1405024E0) and the damaging probes
    killed: bool = False  # avatar+0x138 == 2 (dying latch)
    killed_pending: bool = False  # one-shot GOT_KILLED event bit (avatar+0x134)
    on_fire: bool = False  # one-shot FIRE_DAMAGE event bit
    on_acid: bool = False  # one-shot ACID_DAMAGE event bit
    damaged: bool = False  # one-shot DAMAGE event bit
    # avatar+0x131: set by the Y damaging response, cleared by the tile-below query
    # (sub_140505CB0) the moment the avatar touches the ground / by a server snapshot.
    # While set, validatePhysics scales the input acceleration to 0.15 and skips the
    # idle friction lerp (slippery, barely-controllable air state), see `_simulate`.
    damage_slip: bool = False

    # vertical-axis state (NetAvatar::integrateVerticalAxis 0x140510580)
    water_float: bool = False  # avatar+0x1FB9: water vehicles suppress water gravity for 3 s
    water_enter_ms: float = 0.0  # avatar+0x07C: getTick() when the avatar entered water
    mud: bool = False  # avatar+0x0DE: standing in MUD (reduced jump + 0.6 speed cap)
    left_ground: bool = False  # avatar+0x140: coyote flag, set when walking off an edge
    parasol: bool = False  # avatar+0x0DF per-tick state -> TankFlags.PARASOL (0x40000)
    glide: bool = False  # avatar+0x0E0 per-tick state -> TankFlags.UNK_GRAVITY_RELATED (0x80000)

    # last bounce, reported in the STATE frame's int_x/int_y/value (fillTankStatePacket, 0x1404FBEB0)
    bounce_tx: int = -1
    bounce_ty: int = -1
    bounce_item: int = 0

    frac_x: float = 0.0
    frac_y: float = 0.0
    next_poll_ms: float = 0.0
    last_key: tuple | None = None
    dup_pending: bool = False


class PhysicsEngine:
    def __init__(
        self,
        world: World,
        *,
        hitbox: tuple[float, float] = HITBOX,
        fixed_dt: float = FIXED_DT,
        on_state: StateCallback | None = None,
        on_death: DeathCallback | None = None,
        auto_respawn: bool = True,
    ) -> None:
        self.world = world
        self.width, self.height = hitbox
        self.fixed_dt = fixed_dt
        self.on_state = on_state
        self.on_death = on_death
        self.auto_respawn = auto_respawn
        self.components: dict[int, PhysicsComponent] = {}
        self.tick = 0
        self.time_ms = 0.0
        self._accumulator = 0.0

    def register(
        self,
        net_id: int,
        x: float,
        y: float,
        *,
        state: CharacterState | None = None,
        on_state: StateCallback | None = None,
        on_death: DeathCallback | None = None,
    ) -> PhysicsComponent:
        if net_id in self.components:
            raise ValueError(f"net_id {net_id} is already registered")
        c = PhysicsComponent(net_id, x, y, state or CharacterState(), on_state, on_death)
        self._check_tile_mod(c)
        self.components[net_id] = c

        return c

    def unregister(self, net_id: int) -> PhysicsComponent | None:
        return self.components.pop(net_id, None)

    def set_input(self, net_id: int, *, left: bool = False, right: bool = False, jump: bool = False) -> None:
        c = self.components[net_id]
        c.left, c.right = left, right
        if jump != c.jump:
            c.jump_latch = jump
            if jump:
                self._jump(c)

        c.jump = jump

    def _jump(self, c: PhysicsComponent) -> None:
        """The jump action -- `TryPlaceSeedAtTile` (0x140506430) + `NetAvatar::onJump` (0x1404FE4A50).

        The launch is only allowed when grounded, inside the `left_ground` coyote window
        (`+0x140`), with the double-jump token (`+0x1F8`, refilled while grounded with
        `CharacterFlags.DOUBLE_JUMP`), with the flying/NOCLIP mod, or while paddling in
        water (`vy >= 0` or the water-float state). Antigravity tiles and slippery poles
        refill the token. The strength is `-450`, reduced to `-270` in water, on hay,
        on snow without SNOWSHOES, in mud and on a slippery pole.
        """
        clothing = self._clothing(c)
        below = self._below_tile(c)
        centre = self._centre_tile(c)
        antigrav = (below is not None and below.fg_id == HYPERTECH_ANTIGRAVITY_FIELD) or (centre is not None and centre.fg_id == HYPERTECH_ANTIGRAVITY_FIELD)
        pole = (centre is not None and centre.fg_id == SLIPPERY_FLAG_POLE) or (below is not None and below.fg_id == SLIPPERY_FLAG_POLE)
        double_jump = bool(c.state.flags & CharacterFlags.DOUBLE_JUMP) and not c.double_jumped
        can_swim = c.in_water and (c.vy > 0.0 or c.water_float)
        can_jump = c.grounded or c.left_ground or double_jump or bool(c.state.flags & CharacterFlags.NOCLIP) or antigrav or pole or can_swim

        # the client consumes the coyote flag on every jump action, successful or not
        c.left_ground = False
        if not can_jump:
            return

        was_grounded = c.grounded
        shoes = clothing.shoes if clothing is not None else 0
        snow_locked = below is not None and below.fg_id == SNOW_BLOCK and shoes != SNOWSHOES
        reduced = c.in_water or c.mud or pole or (below is not None and below.fg_id == HAY) or snow_locked
        # NOTE: `grounded` is intentionally left for `_settle` to re-derive at the end of
        # the tick -- like the STATE-driven launch the recorded fits in §10 analyse, the
        # launch tick then skips gravity and travels the full -450.
        c.vy = -JUMP_SPEED * (JUMP_REDUCED_SCALE if reduced else 1.0)
        if not was_grounded:
            c.double_jumped = True  # an airborne launch consumes the token (`unk_1F8 = 0`)
        if antigrav or pole:
            c.double_jumped = False  # `unk_1F8 = 1` before onJump refills it

    def teleport(self, net_id: int, x: float, y: float) -> None:
        c = self.components[net_id]
        c.x, c.y = x, y
        c.vx = c.vy = c.frac_x = c.frac_y = 0.0
        c.grounded = c.sliding = c.in_water = False
        # a server position snap (ProcessTankUpdatePacket -> sub_140501290) clears
        # avatar+0x138 (dying) and avatar+0x131 (damage slip state)
        c.killed = False
        c.damage_slip = False
        self._check_tile_mod(c)

    def update(self, dt: float) -> None:
        self._accumulator += dt
        while self._accumulator >= self.fixed_dt:
            self._accumulator -= self.fixed_dt
            self.step()

    def step(self) -> None:
        self.tick += 1
        self.time_ms += self.fixed_dt * 1000.0
        for c in list(self.components.values()):
            self._simulate(c)
            self._send_state(c)
            self._auto_respawn(c)

    def _auto_respawn(self, c: PhysicsComponent) -> None:
        """Mirror the server's answer to `action|respawn_spike` without a server.

        The client sends that text packet from killPlayer and waits for the server to
        snap it back home; with auto_respawn (the default) the engine teleports the
        local player to `World.get_respawn_position()` right after the GOT_KILLED
        frame left in `_send_state`. Callers can turn this off and respawn on
        `on_death` themselves.
        """
        if not (c.killed and self.auto_respawn) or not self.world.is_local_player(c.net_id):
            return

        pos = self.world.get_respawn_position((self.width, self.height))
        if pos is not None:
            self.teleport(c.net_id, *pos)

    def build_state_packet(self, net_id: int) -> TankPacket:
        c = self.components[net_id]
        flags = TankFlags.NONE
        if c.grounded:
            flags |= TankFlags.STANDING
        if not c.facing_right:
            flags |= TankFlags.FACING_LEFT
        if c.sliding:
            flags |= TankFlags.SLIDE
        if c.in_water:
            flags |= TankFlags.SWIM
        if c.double_jumped:
            flags |= TankFlags.DOUBLE_JUMPED
        if c.jump:
            flags |= TankFlags.JUMP
        if c.parasol:
            flags |= TankFlags.PARASOL  # avatar+0x0DF
        if c.glide:
            flags |= TankFlags.UNK_GRAVITY_RELATED  # avatar+0x0E0
        # one-shot event bits -- ORed in like avatar+0x134 and consumed by `_send_state`
        if c.killed_pending:
            flags |= TankFlags.GOT_KILLED
        if c.on_fire:
            flags |= TankFlags.FIRE_DAMAGE
        if c.on_acid:
            flags |= TankFlags.ACID_DAMAGE
        if c.damaged:
            flags |= TankFlags.DAMAGE

        return TankPacket(
            type=TankType.STATE,
            net_id=net_id,
            flags=flags,
            vector_x=float(math.floor(c.x + 0.5)),
            vector_y=float(math.floor(c.y + 0.5)),
            vector_x2=c.vx,
            vector_y2=c.vy,
            float_var=c.state.velocity_in_water,
            value=c.bounce_item,
            int_x=c.bounce_tx,
            int_y=c.bounce_ty,
        )

    def _simulate(self, c: PhysicsComponent) -> None:
        if c.killed:
            # NetControllerLocal::Update (0x140511A50) skips the physics step while
            # avatar+0x138 (dying) is set -- the corpse does not integrate.
            return

        dt, st = self.fixed_dt, c.state
        self._check_tile_mod(c)

        # vertical -- NetAvatar::integrateVerticalAxis (0x140510580)
        c.parasol = c.glide = False  # +0xDF/+0xE0 are per-tick wire state
        centre = self._centre_tile(c)
        if c.grounded:
            c.vy = min(c.vy, 0.0)
        else:
            accel = st.vertical_accel  # base, the water scale is applied below
            max_fall = MAX_FALL
            if accel > 0.0:
                if c.vy < 0.0 and not c.jump_latch:
                    accel += JUMP_CUT_ACCEL
                elif c.damage_slip:
                    # +0x131 branch: += 0.85 * 5000
                    accel += JUMP_CUT_ACCEL * 0.85
                # slow fall: parachute-like items while the jump button is held
                if c.vy > 0.0 and c.jump_latch and not c.in_water and not (c.state.flags & CharacterFlags.ZOMBIE):
                    slow = self._slow_fall_flags(c)
                    if slow is not None:
                        accel *= SLOW_FALL_ACCEL_SCALE
                        c.parasol, c.glide = slow
                # antigravity field / hover particle
                if centre is not None and centre.fg_id == HYPERTECH_ANTIGRAVITY_FIELD:
                    accel *= ANTIGRAVITY_ACCEL_SCALE
            if c.in_water:
                accel *= WATER_VERTICAL_SCALE
                max_fall = MAX_FALL * WATER_VERTICAL_SCALE
                if c.water_float:
                    # a water vehicle suppresses water gravity entirely (+0x1FB9)
                    accel = 0.0
                    max_fall = 0.0
                if self._is_floatie(c):
                    accel = WATER_FLOAT_ACCEL
                    if c.vy > 0.0:
                        accel = WATER_FLOAT_FALL_ACCEL
                        c.vy = min(c.vy, WATER_FLOAT_MAX_FALL)
            elif centre is not None and centre.fg_id == SLIPPERY_FLAG_POLE:
                accel *= WATER_VERTICAL_SCALE
                max_fall = MAX_FALL * WATER_VERTICAL_SCALE
            c.vy = min(c.vy + dt * accel, max_fall)
            if accel < 0.0:
                c.vy = max(c.vy, -max_fall)

        # horizontal
        direction = int(c.right) - int(c.left)
        if direction:
            c.facing_right = direction > 0
        elif c.vx:
            c.facing_right = c.vx > 0.0
        cap = st.velocity_in_water if c.in_water else st.max_velocity
        if c.mud:
            cap *= MUD_SPEED_SCALE  # +0xDE, validatePhysics's BYTE6 branch
        step_v = st.horizontal_accel * dt
        if c.sliding and c.vy <= 0.0:
            step_v *= SLIDE_ACCEL_SCALE
        if c.damage_slip:
            # validatePhysics scales the whole input magnitude by 0.15 while +0x131 is
            # set (the scale stacks with the ice slide one)
            step_v *= SLIDE_ACCEL_SCALE
        if c.sliding or c.damage_slip:
            # neither state applies idle damping, and neither decelerates a momentum
            # that is already outside the speed cap -- both client paths skip it
            if direction > 0 and c.vx < cap:
                c.vx = min(c.vx + step_v, cap)
            elif direction < 0 and c.vx > -cap:
                c.vx = max(c.vx - step_v, -cap)
        else:
            c.vx = self._approach(c.vx, direction * cap, step_v)

        step_x = max(-TILE, min(TILE, c.vx * dt))
        step_y = max(-TILE, min(TILE, c.vy * dt))
        self._touch(c, step_x, step_y)
        self._move(c, c.vx * dt, 0)
        self._move(c, c.vy * dt, 1)
        self._settle(c)

        c.x = max(0.0, min(self.world.width * TILE - self.width, c.x))
        c.y = max(0.0, min(self.world.height * TILE - self.height, c.y))

        # the client's tile-step query (sub_140505CB0's sibling) touches CHECKPOINTs from
        # the collision rect; World keeps the MAIN_DOOR fallback and `exit_world` resets it
        self.world.update_local_respawn(c.net_id, c.x, c.y, self.width, self.height)

    @staticmethod
    def _approach(value: float, target: float, step: float) -> float:
        return min(value + step, target) if value < target else max(value - step, target)

    @staticmethod
    def _vertical_accel(c: PhysicsComponent) -> float:
        return c.state.vertical_accel * WATER_VERTICAL_SCALE if c.in_water else c.state.vertical_accel

    def _touch(self, c: PhysicsComponent, step_x: float, step_y: float) -> None:
        if c.state.flags & CharacterFlags.NOCLIP:
            return  # avatar+0x188 bit 0 -- no tile interaction at all, not even bounce

        w, h = self.width, self.height
        ignore_spikes = bool(c.state.flags & CharacterFlags.IGNORE_SPIKES)
        ignore_lava = bool(c.state.flags & CharacterFlags.IGNORE_LAVA)

        # X probe -- NetAvatar::handleTileInteraction (0x140501DF0). The probe rect is the
        # collision rect translated by the tick's X displacement; only the hazard and the
        # bounce branches stop the column-major scan, a deadly hit keeps it going.
        for tx, ty in self._overlap(c.x + step_x, c.y, c.x + step_x + w, c.y + h):
            self._cache_touch(c, tx, ty)
            if not ignore_spikes and self._is_deadly(tx, ty):
                self._kill(c, tx, ty)
                continue

            hazard = None if ignore_lava else self._damaging_event(tx, ty)
            if hazard is not None:
                self._damaging_x(c, hazard)
                break

            if self._item_type(tx, ty) == ItemInfoType.BOUNCY:
                self._bounce(c, tx, ty)
                break

            if self._interaction_blocked(c, tx, ty):
                if c.damage_slip:
                    c.vx *= DAMAGE_SLIP_WALL_BOUNCE
                else:
                    c.vx = c.vx * SLIDE_WALL_BOUNCE if c.sliding else 0.0

        # Y probe -- NetAvatar vfunc_48 (0x1405021D0). The `+1` px quirk keeps a grounded
        # avatar in contact with whatever it is standing on; deadly returns 1 (continue),
        # damaging/bouncy/launch act and stop the scan.
        probe = 1.0 if (step_y == 0.0 and c.grounded) else step_y
        for tx, ty in self._overlap(c.x, c.y + probe, c.x + w, c.y + probe + h):
            self._cache_touch(c, tx, ty)
            if not ignore_spikes and self._is_deadly(tx, ty):
                self._kill(c, tx, ty)
                continue

            hazard = None if ignore_lava else self._damaging_event(tx, ty)
            if hazard is not None:
                self._damaging_y(c, hazard)
                break

            kind = self._item_type(tx, ty)
            if kind == ItemInfoType.BOUNCY:
                self._bounce(c, tx, ty)
                break

            launch = self._landing_launch(c, tx, ty, kind)
            if launch is not None:
                c.vy = launch
                c.grounded = False
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

    def _kill(self, c: PhysicsComponent, tx: int, ty: int) -> None:
        """NetAvatar::killPlayer (0x1405024E0): latch the dying state and arm GOT_KILLED."""
        if c.killed:
            return  # guarded by avatar+0x138 -- one kill per death

        c.killed = True
        c.killed_pending = True
        c.force_send = True
        if (send := c.on_death or self.on_death) is not None:
            send(c, tx, ty)

    @staticmethod
    def _apply_damage(c: PhysicsComponent, event: TankFlags) -> None:
        # the event bits ride the next 200 ms poll: unlike the kill (which sets the poll
        # reset bit 0x800 through onPositionSnapped) they do not expedite the send gate
        if event & TankFlags.FIRE_DAMAGE:
            c.on_fire = True
        elif event & TankFlags.ACID_DAMAGE:
            c.on_acid = True
        else:
            c.damaged = True

    def _damaging_x(self, c: PhysicsComponent, event: TankFlags) -> None:
        """NetAvatar::handleDamagingTileCollision (0x1404FBFF0): invert the collided X
        axis and clamp it to at least 300 px/s away from the tile."""
        self._apply_damage(c, event)
        c.vx = -c.vx
        if not c.damage_slip:
            if c.vx < 0.0:
                c.vx = min(-DAMAGING_KNOCKBACK_SPEED, c.vx)
            else:
                c.vx = max(DAMAGING_KNOCKBACK_SPEED, c.vx)

    def _damaging_y(self, c: PhysicsComponent, event: TankFlags) -> None:
        """sub_1404FC0B0 (0x1404FC0B0): -800 launch when falling (or a sign flip while
        rising, -50 without a vertical acceleration axis) plus a same-direction
        horizontal clamp. Also sets avatar+0x131 (the damage slip state): while
        airborne the input acceleration is scaled to 0.15 and idle friction is
        suppressed, until the tile-below query finds ground again (see `_simulate`,
        `_settle`)."""
        if c.state.vertical_accel <= 0.0:
            c.vy = DAMAGING_LAUNCH_NO_GRAVITY_SPEED
        elif c.vy < 0.0:
            c.vy = -c.vy
        else:
            c.vy = DAMAGING_LAUNCH_SPEED

        c.grounded = False
        self._apply_damage(c, event)

        if c.vx == 0.0:
            c.vx = -1.0 if not c.facing_right else 1.0

        if c.vx < 0.0:
            c.vx = min(-DAMAGING_KNOCKBACK_SPEED, c.vx)
        else:
            c.vx = max(DAMAGING_KNOCKBACK_SPEED, c.vx)

        c.damage_slip = True

    def _bounce(self, c: PhysicsComponent, tx: int, ty: int) -> None:
        angle = math.atan2(
            c.y + self.height / 2 - (ty * TILE + TILE / 2),
            c.x + self.width / 2 - (tx * TILE + TILE / 2),
        )
        c.vx, c.vy = math.cos(angle) * BOUNCY_SPEED, math.sin(angle) * BOUNCY_SPEED
        c.grounded = False
        c.jump_latch = False
        c.sliding = True
        self._on_tile_bounce_hit(c, tx, ty)

    def _landing_launch(self, c: PhysicsComponent, tx: int, ty: int, kind: int | None) -> float | None:
        tile = self.world.get_tile(tx, ty)
        steam = tile is not None and tile.fg_id == STEAM_LAUNCHER and tile.flags & TileFlags.IS_ON
        if kind not in (ItemInfoType.TRAMPOLINE, ItemInfoType.TRAMPOLINE_MOMENTUM) and not steam:
            return

        if self._vertical_accel(c) <= 0.0 or c.vy < 0.0:
            return

        if ty * TILE < c.y + self.height - _EPS:
            return

        self._on_tile_bounce_hit(c, tx, ty)
        if kind == ItemInfoType.TRAMPOLINE_MOMENTUM:
            return TRAMPOLINE_MOMENTUM_SPEED

        if steam and tile is not None:
            # TODO: client also sends a tile-activate request
            tile.flags &= ~TileFlags.IS_ON

        return TRAMPOLINE_SPEED

    def _on_tile_bounce_hit(self, c: PhysicsComponent, tx: int, ty: int) -> None:
        """NetAvatar::onTileBounceHit (0x140502AB0): remember the bounce for the next STATE frame."""
        tile = self.world.get_tile(tx, ty)
        c.bounce_tx, c.bounce_ty = tx, ty
        c.bounce_item = tile.fg_id if tile is not None else 0

    def _move(self, c: PhysicsComponent, delta: float, axis: int) -> None:
        total = delta + (c.frac_x if axis == 0 else c.frac_y)
        steps = math.floor(total + 0.5)
        if axis == 0:
            c.frac_x = total - steps
        else:
            c.frac_y = total - steps
        direction = 1 if steps > 0 else -1
        for _ in range(abs(steps)):
            if axis == 0:
                if self._blocked_x(c, c.x + direction, c.y, direction):
                    return

                c.x += direction
            else:
                if self._blocked_y(c, c.x, c.y + direction, direction):
                    return

                c.y += direction

    def _can_enter_x(self, c: PhysicsComponent, tx: int, ty: int, direction: int) -> bool:
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

        return not self._blocks_like_client(c, tile, kind)

    def _can_enter_y(self, c: PhysicsComponent, tx: int, ty: int, y: float, direction: int) -> bool:
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

        return not self._blocks_like_client(c, tile, kind)

    def _blocked_x(self, c: PhysicsComponent, x: float, y: float, direction: int) -> bool:
        edge = x + self.width if direction > 0 else x
        tx = math.floor((edge - direction * _EPS) / TILE)
        return any(
            not self._can_enter_x(c, tx, ty, direction) for ty in range(math.floor((y + _EPS) / TILE), math.floor((y + self.height - _EPS) / TILE) + 1)
        )

    def _blocked_y(self, c: PhysicsComponent, x: float, y: float, direction: int) -> bool:
        edge = y + self.height if direction > 0 else y
        ty = math.floor((edge - direction * _EPS) / TILE)
        return any(
            not self._can_enter_y(c, tx, ty, y, direction) for tx in range(math.floor((x + _EPS) / TILE), math.floor((x + self.width - _EPS) / TILE) + 1)
        )

    def _settle(self, c: PhysicsComponent) -> None:
        feet = c.y + self.height
        row = math.floor((feet + 0.5) / TILE)
        support = any(self._is_ground(c, tx, row) for tx in self._columns(c.x + 2.0, c.x + self.width - 2.0))
        if support and abs(feet - row * TILE) <= 0.5 and c.vy >= 0.0:
            c.y = row * TILE - self.height
            c.vy = 0.0
            c.grounded = True
            c.double_jumped = False
            # sub_140505CB0 clears avatar+0x131 as soon as the tile-below query finds
            # ground -- touching down restores normal control
            c.damage_slip = False
        else:
            if c.grounded:
                c.left_ground = True  # +0x140 is set when the ground query stops finding floor
            c.grounded = False

    def _check_tile_mod(self, c: PhysicsComponent) -> None:
        centre = self.world.get_tile(math.floor((c.x + self.width / 2) / TILE), math.floor((c.y + self.height / 2) / TILE))
        was_water = c.in_water
        c.in_water = bool(centre and centre.flags & TileFlags.IS_WET)

        row = math.floor((c.y + self.height) / TILE)
        below = [tile for tx in self._columns(c.x + 2.0, c.x + self.width - 2.0) if (tile := self.world.get_tile(tx, row)) is not None]
        if any(self._is_slippery(tile) for tile in below):
            c.sliding = True
        elif c.grounded:
            c.sliding = False
        c.mud = any(tile.fg_id > 0 and item_database.get(tile.fg_id).item_type == ItemInfoType.MUD for tile in below)

        self._update_water_state(c, was_water)

    def _update_water_state(self, c: PhysicsComponent, was_water: bool) -> None:
        """`updateBlockStateFromPlayerInteraction` (0x140509C20): the water-float state.

        Entering water with a water vehicle (surfboards/boats/JET_SKI/...) turns on
        `water_float` (avatar+0x1FB9) for 3000 ms; FISHING_DINGHY / JET_SKI /
        GOLDEN_JET_SKI keep it while in water. While set, `integrateVerticalAxis`
        zeroes both the water gravity and the fall speed.
        """
        if c.in_water and not was_water:
            c.water_enter_ms = self.time_ms
            if self._has_water_vehicle(c):
                c.water_float = True
        if not c.in_water:
            c.water_float = False
        elif self.time_ms - c.water_enter_ms > WATER_FLOAT_DURATION_MS and not self._has_water_float_perm(c):
            c.water_float = False

    # -- clothing / item helpers -------------------------------------------------

    def _clothing(self, c: PhysicsComponent) -> Clothing | None:
        player = self.world.players.get(c.net_id)
        return player.clothing if player is not None else None

    def _has_water_vehicle(self, c: PhysicsComponent) -> bool:
        clothing = self._clothing(c)
        if clothing is None:
            return False

        return clothing.hand in _WATER_VEHICLES or clothing.shoes in _WATER_VEHICLES

    def _has_water_float_perm(self, c: PhysicsComponent) -> bool:
        clothing = self._clothing(c)
        return clothing is not None and clothing.shoes in (FISHING_DINGHY, JET_SKI, GOLDEN_JET_SKI)

    def _is_floatie(self, c: PhysicsComponent) -> bool:
        clothing = self._clothing(c)
        if clothing is None:
            return False

        return clothing.neck in (SEA_MONSTER_FLOATIE, UNICORN_FLOATIE) or clothing.hand in (WATER_WINGS, FLAMING_FLOATIES)

    def _slow_fall_flags(self, c: PhysicsComponent) -> tuple[bool, bool] | None:
        """The two parachute groups of integrateVerticalAxis (0x140510580).

        Returns `(parasol, glide)` -- `parasol` maps to avatar+0xDF and the PARASOL
        event bit (0x40000), `glide` to avatar+0xE0 and UNK_GRAVITY_RELATED (0x80000).
        """
        clothing = self._clothing(c)
        if clothing is None:
            return None

        if (
            clothing.hand in (PARASOL, DRACONIC_ROCKET_PARASOL, DARKEST_SKULL_PARASOL, LIGHTNING_UMBRELLA, OIL_PAPER_UMBRELLA, GIANT_FALLING_SHAMROCK, RING_OF_WINDS)
            or clothing.shoes == MAGIC_CARPET
            or clothing.back == GROW_X_ROCKET_WINGS
        ):
            return True, False
        if clothing.shoes == FLOATING_LEAF or clothing.hat == CELESTIAL_HALO:
            return True, False
        if (
            clothing.back
            in (
                SODA_JETPACK,
                SUPER_SQUIRT_GUN_JETPACK,
                LEGENDARY_WINGS,
                DA_VINCI_WINGS,
                CLOAK_OF_FALLING_WATERS,
                SPECTRAL_MANTLE,
                CLOAK_OF_HOVERATION,
                ANGEL_OF_MERCY_S_WINGS,
                HELPING_HAND,
            )
            or clothing.pants == SUPER_SQUIRT_GUN_JETPACK_PANTS
            or clothing.shoes in (SPACE_THRUSTER_BOOST_BOOTS, GROW_AIR_BALLOON)
            or clothing.hat in (ZEPHYR_HELM, TURKEY_HAT)
            or clothing.hair == RAYMAN_S_HAIR
            or clothing.neck in (SILK_SCARF, GOLDEN_SILK_SCARF, POSSESSING_SCARF, HARVEST_SCARF)
            or clothing.hand == STEAMPUNK_ARM
        ):
            return False, True

        return None

    def _centre_tile(self, c: PhysicsComponent) -> Tile | None:
        return self.world.get_tile(math.floor((c.x + self.width / 2) / TILE), math.floor((c.y + self.height / 2) / TILE))

    def _below_tile(self, c: PhysicsComponent) -> Tile | None:
        """First foreground tile at the row under the feet (the jump/mud surface)."""
        row = math.floor((c.y + self.height) / TILE)
        for tx in self._columns(c.x + 2.0, c.x + self.width - 2.0):
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

    def _interaction_blocked(self, c: PhysicsComponent, tx: int, ty: int) -> bool:
        """CanPassThroughTile (0x140554C10, isBreakTap=1) -- the wall response + climb gate."""
        entry = self._active_tile(tx, ty)
        if entry is None:
            return False

        tile, kind = entry
        if kind in (ItemInfoCollisionType.JUMP_THROUGH, ItemInfoCollisionType.JUMP_DOWN, ItemInfoCollisionType.ONE_WAY):
            return False  # probes only, never a wall response
        return self._blocks_like_client(c, tile, kind)

    def _blocks_like_client(self, c: PhysicsComponent, tile: Tile, kind: ItemInfoCollisionType) -> bool:
        """The per-type switch of CanPassThroughTile (1 = blocking/interactive)."""
        if kind == ItemInfoCollisionType.NONE:
            return False
        if kind == ItemInfoCollisionType.ONE_WAY:
            return False  # directional, never collected for the vertical step
        if kind == ItemInfoCollisionType.GATEWAY:
            return not self._gateway_open(c, tile)
        if kind == ItemInfoCollisionType.VIP_DOOR:
            return not self._vip_door_open(c, tile)
        if kind == ItemInfoCollisionType.FRIEND_ENTRANCE:
            return not self._friend_entrance_open(c, tile)
        if kind == ItemInfoCollisionType.ADVENTURE:
            return not self._adventure_open(c, tile)
        if kind == ItemInfoCollisionType.FACTION:
            return not self._faction_open(c, tile)
        if kind == ItemInfoCollisionType.GUILD:
            return not self._guild_open(c, tile)
        if kind == ItemInfoCollisionType.CLOUD:
            # client reads extra+0x140; a cloud without its extra blocks too
            extra = tile.extra
            return not isinstance(extra, StormyCloudTile) or extra.is_solid > 0
        return True  # FULL and the state-gated COLLIDE_IF variants

    def _is_ground(self, c: PhysicsComponent, tx: int, ty: int) -> bool:
        """Ground support (sub_140564570 with a7=1): blocking tiles except JUMP_DOWN."""
        entry = self._active_tile(tx, ty)
        if entry is None or entry[1] == ItemInfoCollisionType.JUMP_DOWN:
            return False
        return self._blocks_like_client(c, *entry)

    def _cache_touch(self, c: PhysicsComponent, tx: int, ty: int) -> None:
        """Record a touched tile in the five-slot cache scanned by ``TileExistsAt``.

        The client keeps the last five tiles the avatar touched at avatar+0x2E0
        and ``TileExistsAt`` (0x140519D80) only compares their foreground ids.
        The adventure key gate reads this cache, so the engine tracks the same
        ids (most recent last, duplicates moved to the back).
        """
        tile = self.world.get_tile(tx, ty)
        if tile is None or tile.fg_id <= 0:
            return

        cache = c.permissions.tile_cache
        if tile.fg_id in cache:
            cache.remove(tile.fg_id)
        cache.append(tile.fg_id)
        del cache[:-5]

    # -- lock / door permissions (CanPassThroughTile + canDoorPassedThrough) ------

    def _lock_passes(self, c: PhysicsComponent, extra, tile: Tile | None, is_break_tap: bool) -> bool:
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

        perms = c.permissions
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

    def _lock_check(self, c: PhysicsComponent, tile: Tile) -> bool:
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
        return self._lock_passes(c, extra, tile, True)

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

    def _gateway_open(self, c: PhysicsComponent, tile: Tile) -> bool:
        """GATEWAY: ``canDoorPassedThrough_1`` or the public flag."""
        return bool(tile.flags & TileFlags.IS_OPEN_TO_PUBLIC) or self._lock_check(c, tile)

    def _vip_door_open(self, c: PhysicsComponent, tile: Tile) -> bool:
        """VIP_DOOR: ``canDoorPassedThrough(extra, userID, tile, 1)``; no extra blocks."""
        if tile.extra is None:
            return False
        return self._lock_passes(c, tile.extra, tile, True)

    def _friend_entrance_open(self, c: PhysicsComponent, tile: Tile) -> bool:
        """FRIEND_ENTRANCE -- canFriendEntrancePassedThrough (0x1405587B0).

        The lock/access path runs with ``isBreakTap=0``; then the extra's
        ``placedTimestamp`` (avatar-side init 1) must be 1 and either the
        friend state (avatar+0x2DB0 + a world owner) or the world owner's own
        user id must hold.
        """
        extra = tile.extra
        if extra is None:
            return False

        perms = c.permissions
        owner_uid = self.world.get_owner_user_id()
        friend_state = perms.friend and owner_uid >= 0
        if self._lock_passes(c, extra, tile, False):
            return True
        if getattr(extra, "placed_timestamp", 0) != 1:
            return False
        if not friend_state and perms.user_id != owner_uid:
            return False
        return True

    def _adventure_open(self, c: PhysicsComponent, tile: Tile) -> bool:
        """ADVENTURE branch of CanPassThroughTile.

        ``LOCKED_ADVENTURE_DOOR`` needs the adventure key in the avatar's touch
        cache (``TileExistsAt`` + ``ADVENTURE_ITEM_KEY``); the barrier / idol /
        tomb gates toggle on the avatar+0x2E8[40/41/42] event flags.
        """
        perms = c.permissions
        if tile.fg_id == LOCKED_ADVENTURE_DOOR:
            return ADVENTURE_ITEM_KEY in perms.tile_cache

        flag = _ADVENTURE_GATE_FLAGS.get(tile.fg_id)
        if flag is None:
            return False  # unknown ADVENTURE tile -> block
        on = bool(tile.flags & TileFlags.IS_ON)
        if flag in perms.adventure_flags:
            return not on  # event flag set: open while IS_ON is clear
        return on  # otherwise: open while IS_ON is set

    def _faction_open(self, c: PhysicsComponent, tile: Tile) -> bool:
        """FACTION branch: team byte (extra+0x80), public flag, access list."""
        perms = c.permissions
        extra = tile.extra
        team = extra.team_type if isinstance(extra, BalloonOMaticTile) else 0
        public = bool(tile.flags & TileFlags.IS_OPEN_TO_PUBLIC)
        if perms.has_team:
            if public:
                return perms.team == team
            return self._lock_check(c, tile) and perms.team == team
        if not public:
            return self._lock_check(c, tile)
        return True

    def _guild_open(self, c: PhysicsComponent, tile: Tile) -> bool:
        """GUILD branch: guild id/rank gate, then the lock path, then public."""
        extra = tile.extra
        if not isinstance(extra, LockTile):
            return False

        perms = c.permissions
        guild_ok = bool(extra.guild_id) and perms.guild_id == extra.guild_id and perms.guild_rank >= self._guild_required_rank(extra)
        return guild_ok or self._lock_check(c, tile) or bool(tile.flags & TileFlags.IS_OPEN_TO_PUBLIC)

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

    def _send_state(self, c: PhysicsComponent) -> None:
        send = c.on_state or self.on_state
        if send is None:
            return

        if c.force_send:
            c.force_send = False
            c.next_poll_ms = 0.0
        if self.time_ms < c.next_poll_ms:
            return

        c.next_poll_ms = self.time_ms + TANK_STATE_POLL_MS

        pkt = self.build_state_packet(c.net_id)
        key = (pkt.vector_x, pkt.vector_y, pkt.vector_x2, pkt.vector_y2, int(pkt.flags), pkt.float_var)
        if key != c.last_key:
            c.last_key = key
            c.dup_pending = True
        elif c.dup_pending:
            c.dup_pending = False
        else:
            return

        # the client's fillTankStatePacket clears avatar+0x134 and the bounce tile after
        # building the frame, so the event bits and the bounce coordinates ride one packet
        c.killed_pending = c.on_fire = c.on_acid = c.damaged = False
        c.bounce_tx = c.bounce_ty = -1
        c.bounce_item = 0
        send(pkt)
