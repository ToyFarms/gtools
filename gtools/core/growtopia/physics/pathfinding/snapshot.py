"""Flat world snapshot used by the fast evaluator and the probe world.

The snapshot turns the object-heavy ``World.tiles`` dict into index-addressed
arrays with the exact derived facts the movement/interaction predicates need:
collision kind (state-aware), blocking class, platform/jump-down/one-way flags,
wet/climb/hazard/bounce/wind/slide/mud/well columns.

**Deadly and damaging are deliberately separate columns.**  A deadly tile latches
``PlayerController.killed`` (terminal); a damaging tile is traversable and only
produces a knockback/launch event plus ``damage_slip``.

Permission-gated tiles (GATEWAY, VIP_DOOR, FRIEND_ENTRANCE, ADVENTURE, FACTION,
GUILD, CLOUD) are marked ``gated`` and are resolved by calling the controller's own
predicates through ``PermissionView`` -- the lock model is never re-implemented here.
"""

from __future__ import annotations

from typing import Any

from pyglm.glm import ivec2

from gtools.baked.items import ADVENTURE_ROPE_PITON, CLIMBING_WALL, GRAVITY_WELL, ICE_CRUST_BLOCK, SLIPPERY_FLAG_POLE, STEAM_LAUNCHER
from gtools.core.growtopia.items_dat import ItemInfoCollisionType, ItemInfoFlag2, ItemInfoType, item_database
from gtools.core.growtopia.physics.controller import TILE, PlayerController
from gtools.core.growtopia.world import Tile, TileFlags

_GATED = frozenset({
    ItemInfoCollisionType.GATEWAY,
    ItemInfoCollisionType.VIP_DOOR,
    ItemInfoCollisionType.FRIEND_ENTRANCE,
    ItemInfoCollisionType.ADVENTURE,
    ItemInfoCollisionType.FACTION,
    ItemInfoCollisionType.GUILD,
    ItemInfoCollisionType.CLOUD,
})

DAMAGE_NONE = 0
DAMAGE_FIRE = 1
DAMAGE_ACID = 2
DAMAGE_GENERIC = 3

BOUNCE_NONE = 0
BOUNCE_RADIAL = 1
BOUNCE_TRAMPOLINE = 2
BOUNCE_TRAMPOLINE_MOMENTUM = 3
BOUNCE_STEAM = 4

_EMPTY = ItemInfoCollisionType.NONE


def _account(grid: "TileGrid", idx: int, old_well: int, old_wind: int, old_surface: int, old_hazard: int) -> None:
    """Keep the feature-presence counters in sync with one reclassified tile."""
    grid.well_count += (1 if grid.well_range[idx] else 0) - (1 if old_well else 0)
    grid.wind_count += (1 if grid.wind[idx] else 0) - (1 if old_wind else 0)
    surface = 1 if (grid.slippery[idx] or grid.mud[idx]) else 0
    grid.surface_count += surface - (1 if old_surface else 0)
    hazard = 1 if (grid.deadly[idx] or grid.deadly_if_on[idx] or grid.damage[idx] or grid.damage_if_on[idx]) else 0
    grid.hazard_count += hazard - (1 if old_hazard else 0)


class TileGrid:
    """Index-addressed tile facts (``idx = y * width + x``)."""

    __slots__ = (
        "width",
        "height",
        "fg_id",
        "flags",
        "parent_index",
        "collision",
        "item_type",
        "blocks",
        "platform",
        "jump_down",
        "one_way",
        "gated",
        "deadly",
        "deadly_if_on",
        "damage",
        "damage_if_on",
        "bouncy",
        "wind",
        "wet",
        "climbable",
        "slippery",
        "mud",
        "well_range",
        "version",
        "well_count",
        "wind_count",
        "surface_count",
        "hazard_count",
    )

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        n = max(0, width * height)
        self.fg_id = [0] * n
        self.flags = [0] * n
        self.parent_index = [0] * n
        self.collision = [0] * n
        self.item_type = [0] * n
        self.blocks = bytearray(n)
        self.platform = bytearray(n)
        self.jump_down = bytearray(n)
        self.one_way = [0] * n  # 0 none, +1 faces right, -1 faces left
        self.gated = bytearray(n)
        self.deadly = bytearray(n)
        self.deadly_if_on = bytearray(n)
        self.damage = bytearray(n)
        self.damage_if_on = bytearray(n)
        self.bouncy = bytearray(n)
        self.wind = [0] * n  # 0 none, +1 push right, -1 push left
        self.wet = bytearray(n)
        self.climbable = bytearray(n)
        self.slippery = bytearray(n)
        self.mud = bytearray(n)
        self.well_range = [0] * n  # px; 0 = not a gravity well
        self.version = [0] * n
        # presence counters: let the evaluator skip whole feature scans on maps
        # that contain none of them (exact: absence of the feature is a no-op)
        self.well_count = 0
        self.wind_count = 0
        self.surface_count = 0
        self.hazard_count = 0

    def index(self, x: int, y: int) -> int | None:
        if 0 <= x < self.width and 0 <= y < self.height:
            return y * self.width + x

        return None

    def flags_at(self, idx: int, overrides: dict[int, int] | None = None) -> int:
        if overrides:
            override = overrides.get(idx)
            if override is not None:
                return override

        return self.flags[idx]


class WorldSnapshot:
    """A mutable snapshot of a ``World`` with per-tile versions.

    ``sync_tile`` is the incremental path (driven by ``WorldEvent.TILE_UPDATE`` in
    the follower); ``sync`` rebuilds everything.
    """

    def __init__(self, world: Any) -> None:
        self.width = int(world.width)
        self.height = int(world.height)
        self.grid = TileGrid(self.width, self.height)
        self.epoch = 0
        self.world_lock_idx = -1
        self.owner_uid = -1
        self._extras: dict[int, Any] = {}
        self._tile_cache: dict[int, Tile] = {}
        self.sync(world)

    # -- building ---------------------------------------------------------------

    def sync(self, world: Any) -> None:
        if int(world.width) != self.width or int(world.height) != self.height:
            self.width = int(world.width)
            self.height = int(world.height)
            self.grid = TileGrid(self.width, self.height)

        self.epoch += 1
        self._extras.clear()
        self._tile_cache.clear()

        for idx, tile in world.tiles.items():
            if 0 <= idx < len(self.grid.fg_id):
                self._classify(idx, tile)
                if tile.extra is not None:
                    self._extras[idx] = tile.extra

        lock = world.get_world_lock()
        self.world_lock_idx = world.index_tile(lock.pos) if lock is not None else -1
        self.owner_uid = world.get_owner_user_id()

    def sync_tile(self, world: Any, x: int, y: int) -> bool:
        idx = self.grid.index(int(x), int(y))
        if idx is None:
            return False

        tile = world.get_tile(int(x), int(y))
        if tile is None:
            tile = Tile(pos=ivec2(int(x), int(y)))

        self._classify(idx, tile)
        self._extras[idx] = tile.extra
        self._tile_cache.pop(idx, None)
        self.grid.version[idx] += 1
        self.epoch += 1

        return True

    def rebuild(self, world: Any) -> None:
        self.sync(world)

    def _classify(self, idx: int, tile: Tile) -> None:
        grid = self.grid
        fg = int(tile.fg_id)
        flags = int(tile.flags)
        grid.fg_id[idx] = fg
        grid.flags[idx] = flags
        grid.parent_index[idx] = int(tile.parent_index)
        grid.wet[idx] = 1 if flags & TileFlags.IS_WET else 0
        old_well = grid.well_range[idx]
        old_wind = grid.wind[idx]
        old_surface = grid.slippery[idx] or grid.mud[idx]
        old_hazard = grid.deadly[idx] or grid.deadly_if_on[idx] or grid.damage[idx] or grid.damage_if_on[idx]

        if fg <= 0:
            grid.collision[idx] = 0
            grid.item_type[idx] = 0
            grid.blocks[idx] = 0
            grid.platform[idx] = 0
            grid.jump_down[idx] = 0
            grid.one_way[idx] = 0
            grid.gated[idx] = 0
            grid.deadly[idx] = 0
            grid.deadly_if_on[idx] = 0
            grid.damage[idx] = 0
            grid.damage_if_on[idx] = 0
            grid.bouncy[idx] = 0
            grid.wind[idx] = 0
            grid.climbable[idx] = 0
            grid.slippery[idx] = 0
            grid.mud[idx] = 0
            grid.well_range[idx] = 0
            _account(grid, idx, old_well, old_wind, old_surface, old_hazard)
            return

        item = item_database.get(fg)
        item_type = int(item.item_type)
        on = bool(flags & TileFlags.IS_ON)

        kind = item.collision_type
        if (kind == ItemInfoCollisionType.COLLIDE_IF_ON and not on) or (kind == ItemInfoCollisionType.COLLIDE_IF_OFF and on):
            kind = ItemInfoCollisionType.NONE
        grid.collision[idx] = int(kind)
        grid.item_type[idx] = item_type

        # movement/interaction blocking class (permission-gated kinds stay unresolved)
        grid.blocks[idx] = 0
        grid.platform[idx] = 0
        grid.jump_down[idx] = 0
        grid.one_way[idx] = 0
        grid.gated[idx] = 0
        if kind in (ItemInfoCollisionType.JUMP_THROUGH,):
            grid.platform[idx] = 1
        elif kind == ItemInfoCollisionType.JUMP_DOWN:
            grid.jump_down[idx] = 1
        elif kind == ItemInfoCollisionType.ONE_WAY:
            grid.one_way[idx] = -1 if flags & TileFlags.FLIPPED_X else 1
        elif kind in _GATED:
            grid.gated[idx] = 1
        elif kind == ItemInfoCollisionType.NONE:
            pass
        else:
            grid.blocks[idx] = 1

        # deadly: DEADLY always, DEADLY_IF_ON while IS_ON, flags2 TILE_DEADLY_IF_ON while IS_ON
        grid.deadly[idx] = 1 if item_type == ItemInfoType.DEADLY else 0
        grid.deadly_if_on[idx] = 1 if (item_type == ItemInfoType.DEADLY_IF_ON or (int(item.flags2) & int(ItemInfoFlag2.TILE_DEADLY_IF_ON))) else 0

        # damaging: fire / acid / generic, split into always-on and IS_ON variants
        damage = DAMAGE_NONE
        damage_if_on = DAMAGE_NONE
        if item_type == ItemInfoType.LAVA:
            damage = DAMAGE_FIRE
        elif item_type == ItemInfoType.ACID:
            damage = DAMAGE_ACID
        elif item_type == ItemInfoType.POINTY:
            damage = DAMAGE_GENERIC
        elif item_type == ItemInfoType.LIGHTNING_CLOUD:
            damage_if_on = DAMAGE_GENERIC
        elif item_type == ItemInfoType.STEAM_LAVA_IF_ON:
            damage_if_on = DAMAGE_GENERIC
        grid.damage[idx] = damage
        grid.damage_if_on[idx] = damage_if_on

        if item_type == ItemInfoType.BOUNCY:
            grid.bouncy[idx] = BOUNCE_RADIAL
        elif item_type == ItemInfoType.TRAMPOLINE:
            grid.bouncy[idx] = BOUNCE_TRAMPOLINE
        elif item_type == ItemInfoType.TRAMPOLINE_MOMENTUM:
            grid.bouncy[idx] = BOUNCE_TRAMPOLINE_MOMENTUM
        elif fg == STEAM_LAUNCHER and on:
            grid.bouncy[idx] = BOUNCE_STEAM
        else:
            grid.bouncy[idx] = BOUNCE_NONE

        grid.wind[idx] = (-1 if flags & TileFlags.FLIPPED_X else 1) if item_type == ItemInfoType.WIND else 0
        grid.climbable[idx] = 1 if fg in (CLIMBING_WALL, ADVENTURE_ROPE_PITON) else 0
        grid.slippery[idx] = 1 if ((fg == ICE_CRUST_BLOCK and not on) or item_type == ItemInfoType.ICE) else 0
        grid.mud[idx] = 1 if item_type == ItemInfoType.MUD else 0
        grid.well_range[idx] = int(getattr(item, "tile_range", 0) or 1) * int(TILE) if fg == GRAVITY_WELL else 0

        # state-dependent damage/on-fire bit (ON_FIRE is a tile flag, not item data)
        if flags & TileFlags.ON_FIRE:
            grid.damage[idx] = DAMAGE_FIRE

        _account(grid, idx, old_well, old_wind, old_surface, old_hazard)

    # -- queries ----------------------------------------------------------------

    def version_at(self, x: int, y: int) -> int:
        idx = self.grid.index(x, y)
        return self.grid.version[idx] if idx is not None else 0

    def max_version_in_bbox(self, bbox: tuple[int, int, int, int]) -> int:
        x0, y0, x1, y1 = bbox
        grid = self.grid
        best = 0
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(grid.width - 1, x1)
        y1 = min(grid.height - 1, y1)
        for y in range(y0, y1 + 1):
            base = y * grid.width
            for x in range(x0, x1 + 1):
                value = grid.version[base + x]
                if value > best:
                    best = value

        return best

    def tile_at(self, x: int, y: int, overrides: dict[int, int] | None = None) -> Tile | None:
        idx = self.grid.index(int(x), int(y))
        if idx is None:
            return None

        return self.tile(idx, overrides)

    def tile(self, idx: int, overrides: dict[int, int] | None = None) -> Tile:
        cached = self._tile_cache.get(idx)
        flags = self.grid.flags_at(idx, overrides)
        if cached is not None and int(cached.flags) == flags:
            return cached

        width = self.grid.width
        tile = Tile(
            fg_id=self.grid.fg_id[idx],
            flags=TileFlags(flags),
            extra=self._extras.get(idx),
            parent_index=self.grid.parent_index[idx],
            index=idx,
            pos=ivec2(idx % width, idx // width),
        )
        self._tile_cache[idx] = tile

        return tile

    def fresh_tile(self, idx: int, overrides: dict[int, int] | None = None) -> Tile:
        """A new ``Tile`` instance (safe for the oracle to mutate)."""
        width = self.grid.width
        return Tile(
            fg_id=self.grid.fg_id[idx],
            flags=TileFlags(self.grid.flags_at(idx, overrides)),
            extra=self._extras.get(idx),
            parent_index=self.grid.parent_index[idx],
            index=idx,
            pos=ivec2(idx % width, idx // width),
        )

    def world_lock_tile(self) -> Tile | None:
        return self.tile(self.world_lock_idx) if self.world_lock_idx >= 0 else None

    def invalidate_tile(self, x: int, y: int) -> None:
        idx = self.grid.index(int(x), int(y))
        if idx is None:
            return

        self.grid.version[idx] += 1
        self.epoch += 1
        self._tile_cache.pop(idx, None)

    def probe_world(self, *, players: dict | None = None, local_net_id: int = 0) -> "ProbeWorld":
        return ProbeWorld(self, players=players or {}, local_net_id=local_net_id)


class PermissionView:
    """Borrows ``PlayerController``'s lock/door predicates (zero duplication)."""

    _blocks_like_client = PlayerController._blocks_like_client
    _gateway_open = PlayerController._gateway_open
    _vip_door_open = PlayerController._vip_door_open
    _friend_entrance_open = PlayerController._friend_entrance_open
    _adventure_open = PlayerController._adventure_open
    _faction_open = PlayerController._faction_open
    _guild_open = PlayerController._guild_open
    _guild_required_rank = staticmethod(PlayerController._guild_required_rank)
    _lock_passes = PlayerController._lock_passes
    _lock_check = PlayerController._lock_check

    __slots__ = ("world", "permissions")

    def __init__(self, world: "ProbeWorld", permissions: Any) -> None:
        self.world = world
        self.permissions = permissions


class ProbeWorld:
    """Minimal duck-typed ``World`` for the controller oracle.

    Only the surface ``PlayerController`` actually reads during ``step`` is
    implemented. Tile clones are isolated from the live world, so the oracle may
    mutate flags (steam launcher ``IS_ON``) without leaking.
    """

    __slots__ = ("snapshot", "width", "height", "players", "dropped", "local_net_id", "_cache")

    def __init__(self, snapshot: WorldSnapshot, *, players: dict | None = None, local_net_id: int = 0) -> None:
        self.snapshot = snapshot
        self.width = snapshot.width
        self.height = snapshot.height
        self.players = players or {}
        self.dropped: list = []
        self.local_net_id = local_net_id
        self._cache: dict[int, Tile] = {}

    # -- World surface used by PlayerController ---------------------------------

    def get_tile(self, x: Any, y: int | None = None) -> Tile | None:
        if isinstance(x, ivec2):
            tx, ty = int(x.x), int(x.y)
        elif y is None:
            idx = int(x)
            if not (0 <= idx < len(self.snapshot.grid.fg_id)):
                return None
            tx, ty = idx % self.snapshot.grid.width, idx // self.snapshot.grid.width
        else:
            tx, ty = int(x), int(y)

        idx = self.snapshot.grid.index(tx, ty)
        if idx is None:
            return None

        tile = self._cache.get(idx)
        if tile is None:
            tile = self.snapshot.fresh_tile(idx)
            self._cache[idx] = tile

        return tile

    def index_tile(self, pos: ivec2) -> int:
        return pos.y * self.width + pos.x

    def index_to_pos(self, index: int) -> ivec2:
        return ivec2(index % self.width, index // self.width)

    def get_world_lock(self) -> Tile | None:
        return self.snapshot.world_lock_tile()

    def get_owner_user_id(self) -> int:
        return self.snapshot.owner_uid

    def get_player(self, net_id: int) -> Any | None:
        return self.players.get(net_id)

    def is_local_player(self, net_id: int) -> bool:
        return self.local_net_id != 0 and net_id == self.local_net_id

    def update_local_respawn(self, net_id: int, x: float, y: float, width: float, height: float) -> None:
        return None

    def get_respawn_position(self, hitbox: tuple[float, float] = (20.0, 30.0)) -> tuple[float, float] | None:
        return None

    def tree_ready(self, tile: Tile) -> bool:
        return False

    def tile_change(self, *args: Any, **kwargs: Any) -> None:
        return None
