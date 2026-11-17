"""Client-side blast simulation for the Blaster items (Howler / Trickster).

A blast is **not** a tile entity: the client models it as an NPC. The server
spawns it with a tank packet and the client only *simulates* it -- motion, the
particle trail and the player kill. There is no client firing path at all: the
fire cadence, the blast speed/heading and the blast lifetime are the server's
choice (`[server-side]`, ``docs/blaster.md`` §1/§9).

Client evidence (``export/ida_pseudocode/functions/``):

* ``handleNPC`` 0x1403F3DF0 -- tank ``animation_type`` 2 (ADD) ->
  ``npc`` 0x1402B6260 -> ``createNpcAndPushBack`` 0x1402B56F0; 7 (DIE) ->
  ``npcHandleAction`` 0x1402B5A40; 1 (DELETE) -> ``npcResetAction`` 0x1402B59E0.
* ``createNpcAndPushBack`` -- ``type = object_type`` (8 = BLAST/Howler,
  15 = TRICKSTER), ``uid = jump_count``, ``param1 = int_x``, ``param2 = int_y``
  (the speed), ``param3 = particle_rotation`` (the heading, degrees),
  ``timer = 0``. A re-sent uid updates the existing entry; the vector cannot
  grow past 106 entries. Both blaster types then look up the tile under the
  spawn point and, when it is a BLASTER item, arm its 1000 ms tile timer and
  play ``audio/flame_go.wav``.
* ``updateNPC`` 0x1402B7530, cases 8 / 15 -- ``timer += dt``; when
  ``timer >= 0.1`` spawn one trail particle (*at the pre-move position*) and
  ``timer -= 0.1``; then ``pos += (cos, sin)(param3) * (int)param2 * dt``.
  Nothing else: **no tile collision and no despawn condition** -- only the
  server's DELETE / DIE events end a blast.
* The kill test runs inside that same update: the blast point must be inside
  ``getPlayerCollisionRect``, the avatar must not be dying (``state_2088 == 6``)
  and the tile under the player's hitbox centre must exist and not be an item
  of type ``DOOR`` (13); then ``killPlayer(player, 0)``.
* ``npcHandleAction`` -- on DIE, type 8 bursts 4 x particle 212 at random
  angles, type 15 spawns effect entries 178 + 223 (not particle sprites), then
  the NPC type is cleared.
* ``renderNpc`` 0x1402B6950 draws nothing for types 8 / 15, so the projectile
  is visible only as its particle trail (212 -> ``game/particles.rttex`` cell
  (0, 2), 276 -> ``game/particles2.rttex`` cell (8, 14); 16 px cells).

Deliberate deviations, all documented in ``docs/blaster.md`` §10:

* ``avatar+0x179/+0x17A`` (build-override bytes) are not modelled, so the
  ``(f179 || f17A) && NOCLIP`` immunity conjunction is never satisfied -- the
  same treatment ``CyBotWorld`` applies.
* The client's particle pool is 512 slots; the oldest entry is recycled here
  once that many are alive.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from gtools.core.growtopia.items_dat import ItemInfoType, item_database
from gtools.core.growtopia.world import Npc, NpcType, Tile, World

TILE = 32

PARTICLE_INTERVAL_S = 0.1
"""``updateNPC``: one trail particle per frame while ``timer >= 0.1``."""

PARTICLE_LIFE_MS = 500
"""Particle record ``+44`` is initialised to 0.5 for 212/276.

The field is only *inferred* to be a lifetime in seconds (the same field holds
2.0-3.0 for particle 197); it is the only per-id duration the record carries.
"""

MAX_PARTICLES = 512
"""[engine bound] live trail particles kept per world.

There is no client constant to copy: ``spawnParticle`` 0x1403E4A10 walks a
dynamic 104-byte record pool and, when it is full, overwrites the slot holding
the smallest ``+64`` priority byte. The engine caps the list instead, dropping
the oldest, so a pathological frame cannot grow memory without bound.
"""

NPC_CAP = 106
"""``createNpcAndPushBack`` refuses to push when the NPC vector has > 105 entries."""

TRAIL_PARTICLE: dict[NpcType, int] = {
    NpcType.BLAST: 212,  # Howler
    NpcType.TRICKSTER: 276,  # Trickster
}

BLAST_TYPES: tuple[NpcType, ...] = (NpcType.BLAST, NpcType.TRICKSTER)

SPAWN_TILE_INTERVAL_MS = 1000
"""``setTileNextUpdate(tile, 1000)`` in the feather-attack spawn branch."""

SPAWN_SOUND = "audio/flame_go.wav"

IMPACT_PARTICLES = 4
"""``npcHandleAction``: BLAST bursts 4 x particle 212 at random angles."""

IMPACT_EFFECTS: dict[NpcType, tuple[int, ...]] = {
    NpcType.TRICKSTER: (178, 223),  # effect-pool ids, no particle sprite
}

PARTICLE_SPRITES: dict[int, tuple[str, tuple[int, int]]] = {
    212: ("game/particles.rttex", (0, 2)),
    276: ("game/particles2.rttex", (8, 14)),
}
"""Particle id -> (sheet, 16 px cell), from ``sub_1402CD860``'s draw cases.

Both trails are drawn at the record's scale 1.0 and rotated to the flight
heading; impact effects 178 / 223 are effect-pool entries with no known sprite.
"""

PARTICLE_SHEETS: tuple[str, ...] = tuple(dict.fromkeys(sheet for sheet, _ in PARTICLE_SPRITES.values()))


def monotonic_ms() -> float:
    return time.monotonic() * 1000.0


@dataclass(slots=True)
class BlastParticle:
    """One trail / impact particle spawned by a blast.

    The client keeps these in a global particle pool: they stay where they were
    spawned while the blast flies on, so the trail is a set of static sprites
    that age independently.
    """

    particle_id: int
    x: float
    y: float
    angle: float
    age_ms: float = 0.0
    life_ms: float = PARTICLE_LIFE_MS


@dataclass(slots=True)
class Blast:
    """One blast in flight (client ``NPC`` entry, types 8 / 15).

    Field names follow the NPC struct: ``uid``/``type`` and the three wire
    params, where ``param2`` is the speed in px/s and ``param3`` the heading in
    degrees.
    """

    uid: int
    type: NpcType
    x: float
    y: float
    target_x: float = 0.0
    target_y: float = 0.0
    param1: int = 0
    speed: int = 0  # param2 -- ``(int)npc->param2``
    angle: float = 0.0  # param3 -- degrees
    timer: float = 0.0

    @classmethod
    def from_npc(cls, npc: Npc) -> "Blast":
        return cls(
            uid=npc.id,
            type=NpcType(npc.type),
            x=npc.pos.x,
            y=npc.pos.y,
            target_x=npc.target_pos.x,
            target_y=npc.target_pos.y,
            param1=npc.param1,
            speed=npc.param2,
            angle=npc.param3,
        )

    def update(self, dt_s: float) -> bool:
        """Advance one frame; returns ``True`` when a trail particle is due.

        Mirrors ``updateNPC`` exactly: the timer is tested *before* the move and
        the particle is spawned at the pre-move position, one per frame (the
        client uses ``if``, not ``while``, so a long frame emits a single
        particle and leaves the timer >= 0.1 for the next one).
        """
        self.timer += dt_s
        emit = self.timer >= PARTICLE_INTERVAL_S
        if emit:
            self.timer -= PARTICLE_INTERVAL_S

        speed = float(int(self.speed))
        radians = self.angle * math.pi / 180.0
        self.x += math.cos(radians) * dt_s * speed
        self.y += math.sin(radians) * dt_s * speed

        return emit


class BlastWorld:
    """The blast entities plus their particle pool.

    Drive it with :meth:`tick` (the client's WorldView NPC update) and
    :meth:`check_kills` from the avatar update; :meth:`add` / :meth:`despawn` /
    :meth:`delete` are the tank-packet entry points (``handleNPC``).
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self.clock = clock or monotonic_ms
        self.blasts: list[Blast] = []
        self.particles: list[BlastParticle] = []
        self.sounds: list[str] = []
        """``playAudio`` calls requested by the simulation; drained by the host."""
        self.effects: list[int] = []
        """Effect-pool ids (``maybeSpawnParticleEffect``) without a known sprite."""
        self._last_ms: int | None = None

    # -- registration (handleNPC) ------------------------------------------------------

    def clear(self) -> None:
        self.blasts.clear()
        self.particles.clear()
        self.sounds.clear()
        self.effects.clear()
        self._last_ms = None

    def add(self, npc: Npc, world: World | None = None, now_ms: int | None = None) -> Blast | None:
        """``handleNPC`` event 2 -> ``createNpcAndPushBack``.

        Returns the blast, or ``None`` for a non-blaster type / a full vector.
        A re-sent uid updates the existing blast in place (the client scans for
        ``uid == jump_count || type == 0``).
        """
        if npc.type not in BLAST_TYPES:
            return None

        blast = self.at(npc.id)
        if blast is None:
            if len(self.blasts) >= NPC_CAP:
                return None
            blast = Blast.from_npc(npc)
            self.blasts.append(blast)
        else:
            refreshed = Blast.from_npc(npc)
            blast.type = refreshed.type
            blast.x, blast.y = refreshed.x, refreshed.y
            blast.target_x, blast.target_y = refreshed.target_x, refreshed.target_y
            blast.param1 = refreshed.param1
            blast.speed = refreshed.speed
            blast.angle = refreshed.angle
            blast.timer = 0.0

        self._arm_spawn_tile(blast, world, now_ms)
        return blast

    def delete(self, uid: int) -> bool:
        """``handleNPC`` event 1 -> ``npcResetAction``: free the NPC slot.

        The client clears a field of the slot in place (slots are reused); the
        local model just drops the blast. No burst is spawned.
        """
        blast = self.at(uid)
        if blast is None:
            return False
        self.blasts.remove(blast)
        return True

    def despawn(self, uid: int, x: float | None = None, y: float | None = None) -> Blast | None:
        """``handleNPC`` event 7 -> ``npcHandleAction``: the impact burst.

        The action's ``vector_x/y`` becomes the NPC position (the burst point).
        Type 8 bursts four particle 212s at random angles; type 15 spawns the
        two effect ids. The NPC is then cleared.
        """
        blast = self.at(uid)
        if blast is None:
            return None

        if x is not None:
            blast.x = x
        if y is not None:
            blast.y = y

        if blast.type is NpcType.BLAST:
            for _ in range(IMPACT_PARTICLES):
                self._spawn_particle(212, blast.x, blast.y, _random_angle())
        self.effects.extend(IMPACT_EFFECTS.get(blast.type, ()))

        self.blasts.remove(blast)
        return blast

    def at(self, uid: int) -> Blast | None:
        return next((b for b in self.blasts if b.uid == uid), None)

    def _arm_spawn_tile(self, blast: Blast, world: World | None, now_ms: int | None) -> None:
        """The feather-attack spawn branch: tile timer + audio on a BLASTER tile."""
        if world is None:
            return
        tile = world.get_tile(math.floor(blast.x / TILE), math.floor(blast.y / TILE))
        if tile is None or not _is_item_type(tile, ItemInfoType.BLASTER):
            return
        tile.next_update_ms = self.now(now_ms) + SPAWN_TILE_INTERVAL_MS
        self.sounds.append(SPAWN_SOUND)

    # -- per-frame ---------------------------------------------------------------------

    def now(self, now_ms: int | None = None) -> int:
        return int(self.clock()) if now_ms is None else int(now_ms)

    def tick(self, now_ms: int | None = None) -> None:
        """Advance every blast and age the particle pool.

        The client passes the frame's ``deltaTime`` to ``updateNPC``; this
        derives it from the simulation clock and skips the very first frame
        (there is no previous sample to subtract).
        """
        now = self.now(now_ms)
        if self._last_ms is None:
            self._last_ms = now
            return

        dt_ms = max(0.0, float(now - self._last_ms))
        self._last_ms = now
        if dt_ms <= 0.0:
            return
        dt_s = dt_ms / 1000.0

        for blast in self.blasts:
            particle_id = TRAIL_PARTICLE.get(blast.type)
            # the client emits the particle *before* advancing the position
            pre_x, pre_y = blast.x, blast.y
            if blast.update(dt_s) and particle_id is not None:
                self._spawn_particle(particle_id, pre_x, pre_y, blast.angle)

        for particle in self.particles:
            particle.age_ms += dt_ms
        self.particles = [p for p in self.particles if p.age_ms < p.life_ms]

    # -- avatar interaction (inside updateNPC, not the probe pass) ---------------------

    def check_kills(self, player) -> Blast | None:
        """The blast kill test from ``updateNPC`` cases 8 / 15.

        Returns the blast that connected, if any. The gate order is the
        client's: point inside the collision rect, avatar not dying
        (``state_2088 == 6`` -> ``player.killed``), the tile under the player's
        hitbox centre exists and is not a door, then ``killPlayer``. The blast
        itself is *not* consumed -- the client never removes it here.
        """
        rect = _player_rect(player)
        for blast in self.blasts:
            if blast.type not in BLAST_TYPES:
                continue
            if not _point_in_rect(rect, blast.x, blast.y):
                continue
            if player.killed:
                continue
            if _player_tile_blocks_kill(player):
                continue
            player._kill(0, 0)
            return blast
        return None

    # -- renderer feed -----------------------------------------------------------------

    def particle_sprites(self) -> list[BlastParticle]:
        """Particles to draw this frame (trail + impact bursts)."""
        return list(self.particles)

    # -- particle pool -----------------------------------------------------------------

    def _spawn_particle(self, particle_id: int, x: float, y: float, angle: float) -> None:
        self.particles.append(BlastParticle(particle_id=particle_id, x=x, y=y, angle=angle))
        if len(self.particles) > MAX_PARTICLES:
            del self.particles[: len(self.particles) - MAX_PARTICLES]


class _Random:
    """Tiny deterministic-per-instance RNG for the impact burst angles.

    The client calls ``randFloat(0, 360)``; the exact stream is irrelevant to
    the result (four particles at random angles), and seeding keeps tests and
    replays reproducible.
    """

    __slots__ = ("_state",)

    def __init__(self) -> None:
        self._state = 0x2545F491

    def next_float(self) -> float:
        self._state = (self._state * 1103515245 + 12345) & 0x7FFFFFFF
        return self._state / 0x80000000


_rng = _Random()


def _random_angle() -> float:
    return _rng.next_float() * 360.0


def _item_type(tile: Tile) -> ItemInfoType | None:
    item = item_database.get(tile.fg_id) if tile.fg_id else None
    return item.item_type if item is not None else None


def _is_item_type(tile: Tile, item_type: ItemInfoType) -> bool:
    return _item_type(tile) == item_type


def _player_rect(player) -> tuple[float, float, float, float]:
    return (player.x, player.y, player.x + player.width, player.y + player.height)


def _player_tile_blocks_kill(player) -> bool:
    """The client's tile gate: skip the kill when the player tile is null or a door.

    ``getTileAtPlayerPosition`` is the tile under the hitbox centre. The client
    world is a full grid, so ``null`` only means *out of bounds*; an in-bounds
    empty position still has a tile object (``fg_id`` 0) and does not block the
    kill. ``World`` is sparse, hence the explicit bounds test.
    """
    world = player.world
    tx = math.floor((player.x + player.width / 2) / TILE)
    ty = math.floor((player.y + player.height / 2) / TILE)
    if not (0 <= tx < world.width and 0 <= ty < world.height):
        return True
    tile = world.get_tile(tx, ty)
    return tile is not None and _is_item_type(tile, ItemInfoType.DOOR)


def _point_in_rect(rect: tuple[float, float, float, float], x: float, y: float) -> bool:
    """``sub_14002F680``: point-in-rect, accepting either corner ordering."""
    left, top, right, bottom = rect
    inside_x = (x >= left and right >= x) or (left >= x and x >= right)
    inside_y = (y >= top and bottom >= y) or (top >= y and y >= bottom)
    return inside_x and inside_y
