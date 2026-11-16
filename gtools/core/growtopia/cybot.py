"""Client-side CyBot (ROBOT / COMMAND tiles) simulation.

Faithful port of the Growtopia client's robot system; every rule here maps to a
verified client function or data field, documented in `docs/cybot.md`:

- item data (`Item.cybot` + ``frame_interval_ms``) -> the command/robot fields,
- ``cybotRebuildCommands`` 0x1403EB8B0 -> :meth:`CyBot.rebuild`,
- ``cybotScheduleFromClock`` 0x1403EB1D0 -> :meth:`CyBot.schedule`,
- ``cybotTick`` 0x1403EBF60 -> :meth:`CyBot.tick`,
- ``cybotRecomputeTarget`` 0x1403EB000 / ``cybotMove`` 0x1403EC090 -> movement,
- ``cybotExecuteCommand`` 0x1403EA820 -> :meth:`CyBot.execute_command`,
- projectile pool 0x1403E97E0/0x1403E9C70 -> :class:`CyBotProjectile`,
- ``cybotApplyMeleeDamage`` 0x1403EA370 + ``cybotProjectilesCheckKill``
  0x1403E9670 -> :meth:`CyBotWorld.apply_melee` / :meth:`CyBotWorld.check_kills`.

The simulation is deterministic given (tile data, clock). It never sends
packets (the client does not either) and never mutates tiles.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING

from gtools.core.growtopia.items_dat import (
    Item,
    ItemInfoCyBotCommand,
    ItemInfoCyBotRobot,
    ItemInfoFlag2,
    ItemInfoType,
    item_database,
)
from gtools.core.growtopia.player import CharacterFlags
from gtools.core.growtopia.world import CybotTile, World

if TYPE_CHECKING:
    from gtools.core.growtopia.packet import TankFlags
    from gtools.core.growtopia.physics.controller import PlayerController

TILE = 32
"""Tile size in pixels (the client's constant)."""

SPRITE_SIZE = 32
"""Robot / projectile sprite size in pixels (npc1.rttex frames)."""

FRAME_RATE_IDLE_MS = 200
"""Idle / walking animation step (client divides the clock by 200)."""

FRAME_RATE_MOVE_MS = 400
"""Directional (shooting pose) animation step (client divides by 400)."""

MELEE_HALF_EXTENT = 10.0
"""The melee box is ``pos +/- 10`` px (client writes the corners of a 20x20 box)."""

MAIN_DOOR = 6
"""Item id of the Main Door tile -- robot damage is skipped while standing on one."""


def monotonic_ms() -> float:
    """Default simulation clock: the same monotonic-ms source ``World.clock`` uses."""
    return time.monotonic() * 1000.0


class CyBotDirection(IntEnum):
    """Command / sprite direction (``cybotCommandDirection`` 0x1403EACA0)."""

    NONE = 0
    LEFT = 1
    RIGHT = 2
    UP = 3
    DOWN = 4


def command_direction(flags2: int) -> CyBotDirection:
    """Map a COMMAND item's ``flags2`` ROBOT_SHOOT_* bits to a direction code.

    ``cybotCommandDirection``: LEFT(0x2)->1, RIGHT(0x4)->2, UP(0x10)->3,
    DOWN(0x8)->4, otherwise 0 (movement / pause commands carry no direction).
    """
    if flags2 & ItemInfoFlag2.ROBOT_SHOOT_LEFT:
        return CyBotDirection.LEFT
    if flags2 & ItemInfoFlag2.ROBOT_SHOOT_RIGHT:
        return CyBotDirection.RIGHT
    if flags2 & ItemInfoFlag2.ROBOT_SHOOT_UP:
        return CyBotDirection.UP
    if flags2 & ItemInfoFlag2.ROBOT_SHOOT_DOWN:
        return CyBotDirection.DOWN
    return CyBotDirection.NONE


def _item(item_id: int) -> Item | None:
    try:
        return item_database.get(item_id)
    except KeyError:
        return None


def command_info(item_id: int) -> ItemInfoCyBotCommand | None:
    """The typed ``cybot`` payload of a COMMAND item, ``None`` when not applicable."""
    item = _item(item_id)
    if item is None or not isinstance(item.cybot, ItemInfoCyBotCommand):
        return None
    return item.cybot


def robot_info(item_id: int) -> ItemInfoCyBotRobot | None:
    """The typed ``cybot`` payload of a ROBOT item, ``None`` when not applicable."""
    item = _item(item_id)
    if item is None or not isinstance(item.cybot, ItemInfoCyBotRobot):
        return None
    return item.cybot


def command_duration_ms(item_id: int) -> int:
    """Per-command duration: the item's ``frame_interval_ms`` (client ``+0x10C``)."""
    item = _item(item_id)
    return int(item.frame_interval_ms) if item is not None else 0


@dataclass(slots=True)
class RobotCommand:
    """One entry of the robot's runtime command list (client: 8-byte pair)."""

    direction: CyBotDirection
    item_id: int
    info: ItemInfoCyBotCommand | None = None
    duration_ms: int = 0


@dataclass(slots=True)
class CyBotProjectile:
    """A shot in flight (client object 0x48, pool at WorldView+0x3608)."""

    base_frame: int
    frame_count: int
    angle: float
    x: float
    y: float
    origin_x: float
    origin_y: float
    flip: bool
    armed: bool  # client: -1 armed / -128 unactivated sentinel
    life_ms: int
    speed: float  # px per ms
    dir_x: float
    dir_y: float
    deadly: bool
    accrued_ms: int = 0
    last_ms: int = 0

    def update(self, now_ms: int) -> bool:
        """Advance the projectile; returns ``False`` once its lifetime is over.

        Client ``cybotProjectilesUpdate``: ``pos += dt * speed * dir``, retire
        when ``accrued >= life``. No tile collision is tested.
        """
        if self.accrued_ms >= self.life_ms:
            return False

        if now_ms > self.last_ms:
            dt = now_ms - self.last_ms
            self.x += dt * self.speed * self.dir_x
            self.y += dt * self.speed * self.dir_y
            self.last_ms = now_ms
            self.accrued_ms += dt

        return True

    def frame(self, now_ms: int) -> int:
        """Sprite frame: ``base + clock/200 % frame_count`` (client 0x1403E9B00)."""
        return self.base_frame + (now_ms // FRAME_RATE_IDLE_MS) % max(1, self.frame_count)


@dataclass(slots=True)
class RobotSprite:
    """Renderer-facing snapshot of one robot (pure data, no GL)."""

    frame: int
    x: float
    y: float
    flip: bool
    alpha: float
    armed: bool


@dataclass(slots=True)
class ProjectileSprite:
    """Renderer-facing snapshot of one projectile.

    ``flip`` and ``angle`` are consumed by the draw path: ``cybotProjectileRender``
    (0x1403E9B00) passes the projectile's +0x1C flip byte and +0x10 angle (degrees;
    0 left/right, -90 up, +90 down) into ``spriteDraw`` -- see the asm, the
    decompiler drops those stack arguments.
    """

    frame: int
    x: float
    y: float
    flip: bool
    angle: float


@dataclass(slots=True)
class CyBotHit:
    """Outcome of one robot-vs-player contact (test/debug friendly)."""

    robot: CyBot
    kind: str  # "kill" | "damage"
    axis: int  # 0 = X, 1 = Y


class CyBot:
    """One robot entity (client object 0x90, no vtable).

    Field names mirror the client offsets documented in ``docs/cybot.md`` §4.2.
    """

    __slots__ = (
        "tile_x",
        "tile_y",
        "fg_id",
        "commands",
        "cycle_duration_ms",
        "index",
        "cmd_start_ms",
        "cmd_end_ms",
        "last_move_ms",
        "cycle_anchor_ms",
        "x",
        "y",
        "target_x",
        "target_y",
        "facing_left",
        "draw_counter",
        "shoot_deadly",
        "hit_axis",
        "activated",
    )

    def __init__(self, tile_x: int, tile_y: int, fg_id: int, extra: CybotTile) -> None:
        self.tile_x = tile_x
        self.tile_y = tile_y
        self.fg_id = fg_id
        self.commands: list[RobotCommand] = []

        # +0x18 cycle duration, +0x1C index, +0x20/+0x24 window, +0x28 last move,
        # +0x2C anchor, +0x30..+0x3C position/target, +0x40 facing, +0x44 draw counter,
        # +0x78 shoot-deadly, +0x7C hit axis
        self.cycle_duration_ms = 0
        self.index = 0
        self.cmd_start_ms = 0
        self.cmd_end_ms = 0
        self.last_move_ms = 0
        self.cycle_anchor_ms = 0
        self.x = float(tile_x * TILE + TILE / 2)
        self.y = float(tile_y * TILE + TILE / 2)
        self.target_x = self.x
        self.target_y = self.y
        self.facing_left = False
        self.draw_counter = 0
        self.shoot_deadly = False
        self.hit_axis = -1
        self.activated = 0

        self.rebuild(extra)

    # -- construction / refresh (client `cybotRebuildCommands`) ----------------------

    def rebuild(self, extra: CybotTile) -> None:
        """Rebuild the command list from the tile extra; no scheduling.

        Mirrors ``cybotRebuildCommands`` 0x1403EB8B0: primary commands in tile
        order, then the *mirror* pass (reverse order) when the program moves
        (sum of the move offsets != 0), appending each command's mirror id when
        that id resolves to a COMMAND item.
        """
        self.commands.clear()
        self.activated = int(extra.activated)
        self.shoot_deadly = self._item_flags2(self.fg_id) & ItemInfoFlag2.ROBOT_SHOOT_DEADLY != 0

        primaries = [
            RobotCommand(
                direction=command_direction(self._item_flags2(int(entry.item_id))),
                item_id=int(entry.item_id),
                info=command_info(int(entry.item_id)),
                duration_ms=command_duration_ms(int(entry.item_id)),
            )
            for entry in extra.commands
        ]
        self.commands.extend(primaries)

        total_dx = sum(cmd.info.move_dx for cmd in primaries if cmd.info is not None)
        total_dy = sum(cmd.info.move_dy for cmd in primaries if cmd.info is not None)
        if total_dx != 0 or total_dy != 0:
            for cmd in reversed(primaries):
                if cmd.info is None or cmd.info.mirror_item_id == 0:
                    continue
                mirror_item = _item(cmd.info.mirror_item_id)
                if mirror_item is None or mirror_item.item_type != ItemInfoType.COMMAND:
                    continue
                mirror_id = cmd.info.mirror_item_id
                self.commands.append(
                    RobotCommand(
                        direction=command_direction(int(mirror_item.flags2)),
                        item_id=mirror_id,
                        info=command_info(mirror_id),
                        duration_ms=command_duration_ms(mirror_id),
                    )
                )

        self.cycle_duration_ms = sum(cmd.duration_ms for cmd in self.commands)
        self.cycle_anchor_ms = int(extra.anchor_ms)
        self.index = 0
        self.cmd_start_ms = 0
        self.cmd_end_ms = 0
        self.last_move_ms = 0
        self.draw_counter = 0
        self.hit_axis = -1

    @staticmethod
    def _item_flags2(item_id: int) -> int:
        item = _item(item_id)
        return int(item.flags2) if item is not None else 0

    # -- scheduling (client `cybotScheduleFromClock`) ---------------------------------

    def schedule(self, now_ms: int) -> None:
        """Phase-sync the cycle from ``now_ms`` against the tile anchor.

        Client ``cybotScheduleFromClock``: clamp a future anchor to ``now``
        (logging "Problem , saved time has to be less"), then
        ``phase = (now - anchor) % cycle`` and pick the command containing it.
        """
        if not self.commands or self.cycle_duration_ms <= 0:
            return

        anchor = self.cycle_anchor_ms
        if now_ms < anchor:
            anchor = now_ms

        elapsed = now_ms - anchor
        phase = elapsed % self.cycle_duration_ms
        cycles = elapsed // self.cycle_duration_ms

        index = 0
        acc = 0
        for i, cmd in enumerate(self.commands):
            if acc + cmd.duration_ms > phase:
                index = i
                break
            acc += cmd.duration_ms
        else:  # pragma: no cover - defensive; phase always lands inside the cycle
            index = len(self.commands) - 1
            acc = self.cycle_duration_ms - self.commands[index].duration_ms

        self.index = index
        self.cmd_start_ms = anchor + cycles * self.cycle_duration_ms + acc
        self.cmd_end_ms = self.cmd_start_ms + self.commands[index].duration_ms
        self.last_move_ms = self.cmd_start_ms
        self.recompute_target(self.index, reset_pos=True)

    # -- per-frame (client `cybotTick` + `cybotMove`) ---------------------------------

    def tick(self, now_ms: int) -> CyBotProjectile | None:
        """Advance the command cycle by one frame.

        Client ``cybotTick``: when the window has passed, run the *ended*
        command's effect, advance (wrapping), open the next window and recompute
        the target; then move. Returns the projectile spawned this tick, if any.
        """
        if not self.commands:
            return None

        spawned: CyBotProjectile | None = None
        if now_ms > self.cmd_end_ms:
            spawned = self.execute_command(now_ms)
            self.index = (self.index + 1) % len(self.commands)
            self.cmd_start_ms = self.cmd_end_ms
            self.cmd_end_ms = self.cmd_start_ms + self.commands[self.index].duration_ms
            self.draw_counter = 0
            self.recompute_target(self.index, reset_pos=False)

        self.move(now_ms)
        return spawned

    def execute_command(self, now_ms: int) -> CyBotProjectile | None:
        """Shot spawn for the command whose window just ended.

        Client ``cybotExecuteCommand``: only COMMAND items with a shoot
        direction do anything; unarmed robots (``activated <= 0``) have their
        ``shoot_deadly`` cleared and fire non-lethal shots.
        """
        cmd = self.current_command
        if cmd is None or cmd.info is None or cmd.direction == CyBotDirection.NONE:
            return None

        robot = robot_info(self.fg_id)
        if robot is None:
            return None

        armed = self.armed
        if not armed:
            self.shoot_deadly = False

        offset = cmd.info.muzzle_for_direction(int(cmd.direction))
        dir_x, dir_y = {
            CyBotDirection.LEFT: (-1.0, 0.0),
            CyBotDirection.RIGHT: (1.0, 0.0),
            CyBotDirection.UP: (0.0, -1.0),
            CyBotDirection.DOWN: (0.0, 1.0),
        }[cmd.direction]

        return CyBotProjectile(
            base_frame=robot.projectile_base_frame,
            frame_count=robot.projectile_frames,
            angle={
                CyBotDirection.LEFT: 0.0,
                CyBotDirection.RIGHT: 0.0,
                CyBotDirection.UP: -90.0,
                CyBotDirection.DOWN: 90.0,
            }[cmd.direction],
            x=self.x + offset[0],
            y=self.y + offset[1],
            origin_x=self.x + offset[0],
            origin_y=self.y + offset[1],
            flip=cmd.direction == CyBotDirection.LEFT,
            armed=armed,
            life_ms=cmd.info.shot_lifetime_ms,
            speed=cmd.info.shot_speed_px_per_ms,
            dir_x=dir_x,
            dir_y=dir_y,
            deadly=self.shoot_deadly,
            last_ms=now_ms,
        )

    def move(self, now_ms: int) -> None:
        """Lerp the visual position toward the target (client ``cybotMove``).

        One tile (32 px) is covered per command window: ``step = dt * 32/duration``.
        """
        if not self.commands:
            return
        if now_ms < self.cmd_start_ms or now_ms >= self.cmd_end_ms:
            return  # client DebugLog("Skipping Movement")

        duration = self.commands[self.index].duration_ms
        if duration <= 0:
            return

        dt = now_ms - self.last_move_ms
        self.last_move_ms = now_ms
        step = dt * (TILE / duration)

        prev_x = self.x
        self.x = _lerp_to(self.x, self.target_x, step)
        self.y = _lerp_to(self.y, self.target_y, step)

        if self.x < prev_x:
            self.facing_left = True
        elif self.x > prev_x:
            self.facing_left = False

    def recompute_target(self, index: int, *, reset_pos: bool) -> None:
        """Recompute position/target from the command offsets.

        Client ``cybotRecomputeTarget``: with ``reset_pos`` replay every offset
        before ``index`` from the tile centre (deterministic reconstruction),
        then set the target to ``pos + current offset``.
        """
        if reset_pos:
            self.x = float(self.tile_x * TILE + TILE / 2)
            self.y = float(self.tile_y * TILE + TILE / 2)
            for cmd in self.commands[:index]:
                if cmd.info is not None:
                    self.x += cmd.info.move_dx * TILE
                    self.y += cmd.info.move_dy * TILE

        self.target_x = self.x
        self.target_y = self.y
        if self.commands:
            cmd = self.commands[index]
            if cmd.info is not None:
                self.target_x += cmd.info.move_dx * TILE
                self.target_y += cmd.info.move_dy * TILE

    # -- helpers ---------------------------------------------------------------------

    @property
    def armed(self) -> bool:
        return self.activated > 0

    @property
    def current_command(self) -> RobotCommand | None:
        return self.commands[self.index] if self.commands else None

    def sprite_frame(self, now_ms: int) -> int:
        """Linear npc1.rttex frame for the current command (client ``cybotRender``).

        idle (direction 0): ``base + elapsed/200 % idle_frames``;
        left/right (1/2): ``base + idle + elapsed/400 % direction_frames``;
        up (3): one ``direction_frames`` step further; down (4): two steps.
        """
        robot = robot_info(self.fg_id)
        if robot is None:
            return 0

        elapsed = max(0, now_ms - self.cmd_start_ms)
        direction = self.current_command.direction if self.current_command is not None else CyBotDirection.NONE

        idle_frames = max(1, robot.idle_frames)
        direction_frames = max(1, robot.direction_frames)

        if direction in (CyBotDirection.LEFT, CyBotDirection.RIGHT):
            # both directions share the same frames; only the flip differs
            return robot.sprite_base_frame + robot.idle_frames + (elapsed // FRAME_RATE_MOVE_MS) % direction_frames
        if direction == CyBotDirection.UP:
            return (
                robot.sprite_base_frame
                + robot.idle_frames
                + robot.direction_frames
                + (elapsed // FRAME_RATE_MOVE_MS) % direction_frames
            )
        if direction == CyBotDirection.DOWN:
            return (
                robot.sprite_base_frame
                + robot.idle_frames
                + 2 * robot.direction_frames
                + (elapsed // FRAME_RATE_MOVE_MS) % direction_frames
            )
        return robot.sprite_base_frame + (elapsed // FRAME_RATE_IDLE_MS) % idle_frames

    def sprite_flip(self) -> bool:
        """Client flip argument per direction (``cybotRender`` 0x1403EB420):
        left -> always, right -> never, idle / up / down -> the facing flag."""
        direction = self.current_command.direction if self.current_command is not None else CyBotDirection.NONE
        if direction == CyBotDirection.LEFT:
            return True
        if direction == CyBotDirection.RIGHT:
            return False
        return self.facing_left

    def sprite(self, now_ms: int) -> RobotSprite:
        return RobotSprite(
            frame=self.sprite_frame(now_ms),
            x=self.x,
            y=self.y,
            flip=self.sprite_flip(),
            alpha=1.0 if self.armed else 0.5,  # client alpha 255 armed / 128 unarmed
            armed=self.armed,
        )

    def rect(self) -> tuple[float, float, float, float]:
        """The 20x20 melee box (client: ``pos +/- 10``)."""
        return (
            self.x - MELEE_HALF_EXTENT,
            self.y - MELEE_HALF_EXTENT,
            self.x + MELEE_HALF_EXTENT,
            self.y + MELEE_HALF_EXTENT,
        )


def _lerp_to(value: float, target: float, step: float) -> float:
    """The client's ``lerpTo`` (0x1400E2200): move toward the target, clamped."""
    if value > target:
        value -= step
        if value < target:
            value = target
    else:
        value += step
        if value > target:
            value = target
    return value


class CyBotWorld:
    """The robot list + projectile pool (client: WorldView+0x35E8 / +0x3608).

    Drive it with :meth:`tick` (client WorldView update) and, from the avatar's
    probe pass (``PlayerController._touch``), :meth:`apply_melee` +
    :meth:`check_kills` (client ``FindNearestInteractableTile``).
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self.clock = clock or monotonic_ms
        self.robots: list[CyBot] = []
        self.projectiles: list[CyBotProjectile] = []
        self.next_hit_ms = 0  # client WorldView+0x3600

    # -- registration -----------------------------------------------------------------

    def clear(self) -> None:
        self.robots.clear()
        self.projectiles.clear()
        self.next_hit_ms = 0

    def load(self, world: World, now_ms: int | None = None) -> None:
        """Register every robot tile of a world (client ``cybotRegisterAllFromWorld``)."""
        self.clear()
        now = self.now(now_ms)
        for tile in world.tiles.values():
            extra = tile.extra
            if not isinstance(extra, CybotTile):
                continue
            if not self._is_robot(tile.fg_id):
                continue
            robot = CyBot(tile.pos.x, tile.pos.y, tile.fg_id, extra)
            robot.schedule(now)
            self.robots.append(robot)

    def sync_tile(self, world: World, x: int, y: int, now_ms: int | None = None) -> None:
        """Net effect of the client's tile-change paths for one tile position.

        The client refreshes an existing robot on a server TILE_UPDATE
        (``cybotRefreshAtTile``), registers one on an applied tile change
        (``cybotRegisterAtTile``) and frees it when the robot tile is gone
        (``unregisterTile``). All three end up here.
        """
        now = self.now(now_ms)
        tile = world.get_tile(x, y)
        index = next((i for i, r in enumerate(self.robots) if r.tile_x == x and r.tile_y == y), None)

        robot_tile = tile is not None and isinstance(tile.extra, CybotTile) and self._is_robot(tile.fg_id)
        if not robot_tile:
            if index is not None:
                self.robots.pop(index)
            return

        assert tile is not None and isinstance(tile.extra, CybotTile)
        if index is None:
            robot = CyBot(x, y, tile.fg_id, tile.extra)
            self.robots.append(robot)
        else:
            robot = self.robots[index]
            robot.fg_id = tile.fg_id
            robot.rebuild(tile.extra)
        robot.schedule(now)

    @staticmethod
    def _is_robot(item_id: int) -> bool:
        item = _item(item_id)
        return item is not None and item.item_type == ItemInfoType.ROBOT

    def robot_at(self, x: int, y: int) -> CyBot | None:
        return next((r for r in self.robots if r.tile_x == x and r.tile_y == y), None)

    # -- per-frame --------------------------------------------------------------------

    def now(self, now_ms: int | None = None) -> int:
        return int(self.clock()) if now_ms is None else int(now_ms)

    def tick(self, now_ms: int | None = None) -> None:
        """Advance every robot and projectile (client WorldView update)."""
        now = self.now(now_ms)
        for robot in self.robots:
            spawned = robot.tick(now)
            if spawned is not None:
                self.projectiles.append(spawned)

        self.projectiles = [p for p in self.projectiles if p.update(now)]

    # -- avatar interaction (client FindNearestInteractableTile) ----------------------

    def apply_melee(self, player: PlayerController, now_ms: int | None = None) -> list[CyBotHit]:
        """Robot melee pass (client ``cybotProbeAll`` / ``cybotApplyMeleeDamage``).

        Mirrors the all/stop semantics: a kill (or the world hit gate) stops the
        scan at that robot. Returns the applied hits for tests/debugging.
        """
        now = self.now(now_ms)
        hits: list[CyBotHit] = []

        for robot in self.robots:
            robot.hit_axis = -1
            if not self._armed_for_damage(player, robot):
                continue

            flags2 = robot._item_flags2(robot.fg_id)
            deadly = bool(flags2 & ItemInfoFlag2.ROBOT_DEADLY)
            lava = bool(flags2 & ItemInfoFlag2.ROBOT_LAVA)
            pointy = bool(flags2 & ItemInfoFlag2.ROBOT_POINTY)
            if not (deadly or lava or pointy):
                continue
            if self._player_on_main_door(player):
                continue

            if not _rect_overlaps(self._player_rect(player), robot.rect()):
                continue

            if deadly:
                if not player.killed:  # client: avatar state 0x2088 == 6 suppresses it
                    player._kill(robot.tile_x, robot.tile_y)
                hits.append(CyBotHit(robot, "kill", -1))
                break  # client returns 0 -> cybotProbeAll stops

            if self.next_hit_ms > now:
                break  # client returns 0 at the world gate

            info = robot_info(robot.fg_id)
            self.next_hit_ms = now + (info.melee_cooldown_ms if info is not None else 0)

            axis = self._knockback_axis(player, robot)
            robot.hit_axis = axis
            event = self._damage_event(lava)
            if axis == 0:
                player._damaging_x(event)
            else:
                player._damaging_y(event)
            hits.append(CyBotHit(robot, "damage", axis))

        return hits

    def check_kills(self, player: PlayerController) -> CyBotProjectile | None:
        """Deadly-projectile pass (client ``cybotProjectilesCheckKill``).

        Returns the projectile that killed the player, if any.
        """
        rect = self._player_rect(player)
        for projectile in self.projectiles:
            if not projectile.deadly:
                continue
            if projectile.x < rect[0] or projectile.x > rect[2]:
                continue
            if projectile.y < rect[1] or projectile.y > rect[3]:
                continue
            if not player.killed:
                player._kill(0, 0)
            return projectile
        return None

    # -- renderer feed ----------------------------------------------------------------

    def robot_sprites(self, now_ms: int | None = None) -> list[RobotSprite]:
        now = self.now(now_ms)
        return [robot.sprite(now) for robot in self.robots]

    def projectile_sprites(self, now_ms: int | None = None) -> list[ProjectileSprite]:
        now = self.now(now_ms)
        return [ProjectileSprite(p.frame(now), p.x, p.y, p.flip, p.angle) for p in self.projectiles]

    # -- gates ------------------------------------------------------------------------

    @staticmethod
    def _armed_for_damage(player: PlayerController, robot: CyBot) -> bool:
        """Client ``cybotArmedForDamage``: local player, no IGNORE_SPIKES, armed robot.

        The client also gates on ``avatar+0x179/+0x17A`` (build-override bytes):
        when either is set, NOCLIP refuses the damage. Those bytes are not
        modelled by the engine yet and are treated as clear -- NOCLIP avatars are
        already skipped because ``PlayerController._touch`` returns early for
        them, exactly like the client's probe pass.
        """
        if robot.activated <= 0:
            return False
        return not (player.state.flags & CharacterFlags.IGNORE_SPIKES)

    @staticmethod
    def _player_rect(player: PlayerController) -> tuple[float, float, float, float]:
        return (player.x, player.y, player.x + player.width, player.y + player.height)

    @staticmethod
    def _player_on_main_door(player: PlayerController) -> bool:
        """Client: the tile at the player's position being a Main Door skips robots."""
        tile = player.world.get_tile(
            int((player.x + player.width / 2) // TILE),
            int((player.y + player.height / 2) // TILE),
        )
        return tile is not None and tile.fg_id == MAIN_DOOR

    @staticmethod
    def _knockback_axis(player: PlayerController, robot: CyBot) -> int:
        """Client: the angle between the robot and the player's rect centre picks
        the response axis -- mostly to the side -> X, mostly above/below -> Y."""
        cx = player.x + player.width / 2
        cy = player.y + player.height / 2
        dx = robot.x - cx
        dy = robot.y - cy
        if dx == 0.0 and dy == 0.0:
            return 0
        # The client folds the acos angle to [0, 180): < 45 or > 135 deg -> X.
        # Equivalent with atan2 over absolute deltas: < 45 deg from the X axis -> X.
        angle = math.degrees(math.atan2(abs(dy), abs(dx)))
        return 1 if angle >= 45.0 else 0

    @staticmethod
    def _damage_event(lava: bool) -> TankFlags:
        from gtools.core.growtopia.packet import TankFlags

        return TankFlags.FIRE_DAMAGE if lava else TankFlags.DAMAGE


def _rect_overlaps(rect: tuple[float, float, float, float], box: tuple[float, float, float, float]) -> bool:
    """Point-in-rect test with the client's "both orderings" quirk.

    ``cybotApplyMeleeDamage`` tests each of the four box corners against the
    player rect with
    ``(p.x >= r.left and r.right >= p.x) or (r.left >= p.x and p.x >= r.right)``
    (the second disjunct also catches inverted rects), same for y.
    """
    left, top, right, bottom = rect
    for px, py in ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])):
        inside_x = (px >= left and right >= px) or (left >= px and px >= right)
        inside_y = (py >= top and bottom >= py) or (top >= py and py >= bottom)
        if inside_x and inside_y:
            return True
    return False


def robots_from_world(world: World, clock: Callable[[], float] | None = None) -> CyBotWorld:
    """Convenience: a :class:`CyBotWorld` loaded from a world's robot tiles."""
    manager = CyBotWorld(clock)
    manager.load(world)
    return manager
