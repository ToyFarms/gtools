import math
from collections.abc import Callable
from dataclasses import dataclass, field

from gtools.baked.items import ICE_CRUST_BLOCK, STEAM_LAUNCHER
from gtools.core.growtopia.items_dat import ItemInfoCollisionType, ItemInfoFlag2, ItemInfoType, item_database
from gtools.core.growtopia.packet import TankFlags, TankPacket, TankType
from gtools.core.growtopia.player import CharacterFlags, CharacterState
from gtools.core.growtopia.world import Tile, TileFlags, World

TILE = 32.0
HITBOX = (20.0, 30.0)
FIXED_DT = 1 / 60

JUMP_SPEED = 450.0
JUMP_CUT_ACCEL = 5000.0
MAX_FALL = 400.0
WATER_VERTICAL_SCALE = 0.3
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
_SOLID = {ItemInfoCollisionType.FULL, ItemInfoCollisionType.COLLIDE_IF_ON, ItemInfoCollisionType.COLLIDE_IF_OFF}
_PLATFORM = {ItemInfoCollisionType.JUMP_THROUGH, ItemInfoCollisionType.ONE_WAY, ItemInfoCollisionType.CLOUD}

StateCallback = Callable[[TankPacket], None]
DeathCallback = Callable[["PhysicsComponent", int, int], None]


@dataclass(slots=True)
class PhysicsComponent:
    net_id: int
    x: float
    y: float
    state: CharacterState = field(default_factory=CharacterState)
    on_state: StateCallback | None = None
    on_death: DeathCallback | None = None

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
            if jump and c.grounded:
                c.vy = -JUMP_SPEED
                c.double_jumped = False
            elif jump and c.state.flags & CharacterFlags.DOUBLE_JUMP and not c.double_jumped:
                c.vy = -JUMP_SPEED
                c.double_jumped = True

        c.jump = jump

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
            int_x=-1,
            int_y=-1,
        )

    def _simulate(self, c: PhysicsComponent) -> None:
        if c.killed:
            # NetControllerLocal::Update (0x140511A50) skips the physics step while
            # avatar+0x138 (dying) is set -- the corpse does not integrate.
            return

        dt, st = self.fixed_dt, c.state
        self._check_tile_mod(c)

        # vertical
        if c.grounded:
            c.vy = min(c.vy, 0.0)
        else:
            accel = self._vertical_accel(c)
            if accel > 0.0:
                if c.vy < 0.0 and not c.jump_latch:
                    accel += JUMP_CUT_ACCEL
                elif c.damage_slip:
                    # integrateVerticalAxis's 0x131 branch: += 0.85 * 5000
                    accel += JUMP_CUT_ACCEL * 0.85
            max_fall = MAX_FALL * WATER_VERTICAL_SCALE if c.in_water else MAX_FALL
            c.vy = min(c.vy + dt * accel, max_fall)

        # horizontal
        direction = int(c.right) - int(c.left)
        if direction:
            c.facing_right = direction > 0
        elif c.vx:
            c.facing_right = c.vx > 0.0
        cap = st.velocity_in_water if c.in_water else st.max_velocity
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

            if self._is_solid(tx, ty):
                if c.damage_slip:
                    c.vx *= DAMAGE_SLIP_WALL_BOUNCE
                else:
                    c.vx = c.vx * SLIDE_WALL_BOUNCE if c.sliding else 0.0

        # Y probe -- NetAvatar vfunc_48 (0x1405021D0). The `+1` px quirk keeps a grounded
        # avatar in contact with whatever it is standing on; deadly returns 1 (continue),
        # damaging/bouncy/launch act and stop the scan.
        probe = 1.0 if (step_y == 0.0 and c.grounded) else step_y
        for tx, ty in self._overlap(c.x, c.y + probe, c.x + w, c.y + probe + h):
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

    def _landing_launch(self, c: PhysicsComponent, tx: int, ty: int, kind: int | None) -> float | None:
        tile = self.world.get_tile(tx, ty)
        steam = tile is not None and tile.fg_id == STEAM_LAUNCHER and tile.flags & TileFlags.IS_ON
        if kind not in (ItemInfoType.TRAMPOLINE, ItemInfoType.TRAMPOLINE_MOMENTUM) and not steam:
            return

        if self._vertical_accel(c) <= 0.0 or c.vy < 0.0:
            return

        if ty * TILE < c.y + self.height - _EPS:
            return

        if kind == ItemInfoType.TRAMPOLINE_MOMENTUM:
            return TRAMPOLINE_MOMENTUM_SPEED

        if steam and tile is not None:
            # TODO: client also sends a tile-activate request
            tile.flags &= ~TileFlags.IS_ON

        return TRAMPOLINE_SPEED

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
                if self._blocked_x(c.x + direction, c.y, direction):
                    return

                c.x += direction
            else:
                if self._blocked_y(c.x, c.y + direction, direction):
                    return

                c.y += direction

    def _blocked_x(self, x: float, y: float, direction: int) -> bool:
        edge = x + self.width if direction > 0 else x
        tx = math.floor((edge - direction * _EPS) / TILE)

        return any(self._is_solid(tx, ty) for ty in range(math.floor((y + _EPS) / TILE), math.floor((y + self.height - _EPS) / TILE) + 1))

    def _blocked_y(self, x: float, y: float, direction: int) -> bool:
        edge = y + self.height if direction > 0 else y
        ty = math.floor((edge - direction * _EPS) / TILE)
        for tx in range(math.floor((x + _EPS) / TILE), math.floor((x + self.width - _EPS) / TILE) + 1):
            if self._is_solid(tx, ty):
                return True

            if direction > 0 and self._is_platform(tx, ty) and edge - 1.0 <= ty * TILE + _EPS:
                return True

        return False

    def _settle(self, c: PhysicsComponent) -> None:
        feet = c.y + self.height
        row = math.floor((feet + 0.5) / TILE)
        support = any(self._is_solid(tx, row) or self._is_platform(tx, row) for tx in self._columns(c.x + 2.0, c.x + self.width - 2.0))
        if support and abs(feet - row * TILE) <= 0.5 and c.vy >= 0.0:
            c.y = row * TILE - self.height
            c.vy = 0.0
            c.grounded = True
            c.double_jumped = False
            # sub_140505CB0 clears avatar+0x131 as soon as the tile-below query finds
            # ground -- touching down restores normal control
            c.damage_slip = False
        else:
            c.grounded = False

    def _check_tile_mod(self, c: PhysicsComponent) -> None:
        centre = self.world.get_tile(math.floor((c.x + self.width / 2) / TILE), math.floor((c.y + self.height / 2) / TILE))
        c.in_water = bool(centre and centre.flags & TileFlags.IS_WET)

        row = math.floor((c.y + self.height) / TILE)
        if any(self._is_slippery(self.world.get_tile(tx, row)) for tx in self._columns(c.x + 2.0, c.x + self.width - 2.0)):
            c.sliding = True
        elif c.grounded:
            c.sliding = False

    def _collision(self, tx: int, ty: int) -> ItemInfoCollisionType:
        tile = self.world.get_tile(tx, ty)
        if tile is None or tile.fg_id <= 0:
            return ItemInfoCollisionType.NONE

        kind = item_database.get(tile.fg_id).collision_type
        on = bool(tile.flags & TileFlags.IS_ON)
        if (kind == ItemInfoCollisionType.COLLIDE_IF_ON and not on) or (kind == ItemInfoCollisionType.COLLIDE_IF_OFF and on):
            return ItemInfoCollisionType.NONE

        return kind

    def _is_solid(self, tx: int, ty: int) -> bool:
        return self._collision(tx, ty) in _SOLID

    def _is_platform(self, tx: int, ty: int) -> bool:
        return self._collision(tx, ty) in _PLATFORM

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

        # the client's fillTankStatePacket clears avatar+0x134 after building the frame,
        # so FIRE_DAMAGE / ACID_DAMAGE / DAMAGE / GOT_KILLED ride exactly one packet
        c.killed_pending = c.on_fire = c.on_acid = c.damaged = False
        send(pkt)
