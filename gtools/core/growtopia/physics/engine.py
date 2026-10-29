import math
from collections.abc import Callable
from dataclasses import dataclass, field

from gtools.baked.items import ICE_CRUST_BLOCK, STEAM_LAUNCHER
from gtools.core.growtopia.items_dat import ItemInfoCollisionType, ItemInfoType, item_database
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
BOUNCY_SPEED = 500.0
TRAMPOLINE_SPEED = -800.0
TRAMPOLINE_MOMENTUM_SPEED = -531.25
TANK_STATE_POLL_MS = 200.0

_EPS = 1e-4
_SOLID = {ItemInfoCollisionType.FULL, ItemInfoCollisionType.COLLIDE_IF_ON, ItemInfoCollisionType.COLLIDE_IF_OFF}
_PLATFORM = {ItemInfoCollisionType.JUMP_THROUGH, ItemInfoCollisionType.ONE_WAY, ItemInfoCollisionType.CLOUD}

StateCallback = Callable[[TankPacket], None]


@dataclass(slots=True)
class PhysicsComponent:
    net_id: int
    x: float
    y: float
    state: CharacterState = field(default_factory=CharacterState)
    on_state: StateCallback | None = None

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

    frac_x: float = 0.0
    frac_y: float = 0.0
    next_poll_ms: float = 0.0
    last_key: tuple | None = None
    dup_pending: bool = False


class PhysicsEngine:
    def __init__(self, world: World, *, hitbox: tuple[float, float] = HITBOX, fixed_dt: float = FIXED_DT, on_state: StateCallback | None = None) -> None:
        self.world = world
        self.width, self.height = hitbox
        self.fixed_dt = fixed_dt
        self.on_state = on_state
        self.components: dict[int, PhysicsComponent] = {}
        self.tick = 0
        self.time_ms = 0.0
        self._accumulator = 0.0

    def register(self, net_id: int, x: float, y: float, *, state: CharacterState | None = None, on_state: StateCallback | None = None) -> PhysicsComponent:
        if net_id in self.components:
            raise ValueError(f"net_id {net_id} is already registered")
        c = PhysicsComponent(net_id, x, y, state or CharacterState(), on_state)
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
        dt, st = self.fixed_dt, c.state
        self._check_tile_mod(c)

        # vertical
        if c.grounded:
            c.vy = min(c.vy, 0.0)
        else:
            accel = self._vertical_accel(c)
            if accel > 0.0 and c.vy < 0.0 and not c.jump_latch:
                accel += JUMP_CUT_ACCEL
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
        if c.sliding:
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

    @staticmethod
    def _approach(value: float, target: float, step: float) -> float:
        return min(value + step, target) if value < target else max(value - step, target)

    @staticmethod
    def _vertical_accel(c: PhysicsComponent) -> float:
        return c.state.vertical_accel * WATER_VERTICAL_SCALE if c.in_water else c.state.vertical_accel

    def _touch(self, c: PhysicsComponent, step_x: float, step_y: float) -> None:
        w, h = self.width, self.height

        if step_x:
            for tx, ty in self._overlap(c.x + step_x, c.y, c.x + step_x + w, c.y + h):
                if self._item_type(tx, ty) == ItemInfoType.BOUNCY:
                    self._bounce(c, tx, ty)
                    break
                if self._is_solid(tx, ty):
                    c.vx = c.vx * SLIDE_WALL_BOUNCE if c.sliding else 0.0
                    break

        probe = 1.0 if (step_y == 0.0 and c.grounded) else step_y
        if probe:
            for tx, ty in self._overlap(c.x, c.y + probe, c.x + w, c.y + probe + h):
                kind = self._item_type(tx, ty)
                if kind == ItemInfoType.BOUNCY:
                    self._bounce(c, tx, ty)
                    break
                launch = self._landing_launch(c, tx, ty, kind)
                if launch is not None:
                    c.vy = launch
                    c.grounded = False
                    break

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
            send(pkt)
        elif c.dup_pending:
            c.dup_pending = False
            send(pkt)
