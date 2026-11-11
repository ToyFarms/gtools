import random
import sys
import math
import json
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Iterator
from pyglm.glm import vec2, vec4

import glfw
from OpenGL.GL import GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, glClear, glClearColor
from imgui_bundle import imgui
from imgui_bundle.python_backends.glfw_backend import GlfwRenderer

from gtools import setting
from gtools.baked.items import MAIN_DOOR, SNOWSHOES
from gtools.core.growtopia.items_dat import ItemInfoClothingType, item_database
from gtools.core.growtopia.world import World
from gtools.core.growtopia.player import Player
from gtools.gui.event import EventRouter, KeyEvent, MouseButtonEvent, ResizeEvent
from gtools.gui.lib.world_renderer import WorldRenderer
from gtools.core.growtopia.packet import TankPacket
from gtools.core.growtopia.player import CharacterFlags, CharacterState
from gtools.core.growtopia.physics.controller import (
    PlayerController,
    TILE,
    HITBOX,
    FIXED_DT,
    JUMP_SPEED,
    JUMP_CUT_ACCEL,
    MAX_FALL,
    WATER_VERTICAL_SCALE,
    SLIDE_ACCEL_SCALE,
    SLIDE_WALL_BOUNCE,
    BOUNCY_SPEED,
    TRAMPOLINE_SPEED,
    TRAMPOLINE_MOMENTUM_SPEED,
    DAMAGING_KNOCKBACK_SPEED,
    DAMAGING_LAUNCH_SPEED,
    DAMAGING_LAUNCH_NO_GRAVITY_SPEED,
    JUMP_REDUCED_SCALE,
    SLOW_FALL_ACCEL_SCALE,
    ANTIGRAVITY_ACCEL_SCALE,
    MUD_SPEED_SCALE,
    WATER_FLOAT_ACCEL,
    WATER_FLOAT_FALL_ACCEL,
    WATER_FLOAT_MAX_FALL,
    WATER_FLOAT_DURATION_MS,
    CLIMB_GEAR_ITEMS,
    FLOATIE_ITEMS,
    GLIDE_ITEMS,
    PARASOL_ITEMS,
    SKATING_ITEMS,
    SLIPPERY_ITEMS,
    WATER_VEHICLE_ITEMS,
    FLOATIE_ITEMS,
)
from gtools.core.growtopia.physics.pathfinding import PathAutopilot, SegmentedPathfinder
from gtools.core.growtopia.physics.pathfinding.types import SegmentKind

PLAYER_NET_ID = 1
_TILE_HALF = TILE / 2.0

RECORDING_DIR = Path(__file__).resolve().parent / "recordings"

# -- modifier menu ---------------------------------------------------------------------
# The Player menu lists the engine's clothing *modifiers* (one collapsing header per
# client branch), not body slots: an item's slot is resolved from items.dat, so the same
# item can never be listed under the wrong part. The sets come from the controller, which
# is the single source of truth for the per-tick checks.
_CLOTHING_SLOTS = {
    ItemInfoClothingType.HAT: "hat",
    ItemInfoClothingType.SHIRT: "shirt",
    ItemInfoClothingType.PANTS: "pants",
    ItemInfoClothingType.SHOES: "shoes",
    ItemInfoClothingType.FACE: "face",
    ItemInfoClothingType.HAND: "hand",
    ItemInfoClothingType.BACK: "back",
    ItemInfoClothingType.HAIR: "hair",
    ItemInfoClothingType.NECK: "neck",
    ItemInfoClothingType.ARTIFACTS: "artifacts",
}
_label_cache: dict[int, str] = {}
_groups_cache: tuple[tuple[str, tuple[int, ...]], ...] | None = None

# Overlay colour per segment kind -- the movement method, not the action that was
# attempted: a "jump" that lands in water is SWIM and is drawn as such.
_SEGMENT_COLORS: dict[SegmentKind, tuple[float, float, float, float]] = {
    SegmentKind.WALK: (0.36, 0.86, 0.44, 1.0),
    SegmentKind.JUMP: (0.95, 0.78, 0.25, 1.0),
    SegmentKind.JUMP_UP: (0.95, 0.62, 0.20, 1.0),
    SegmentKind.JUMP_OVER: (0.98, 0.50, 0.16, 1.0),
    SegmentKind.FALL: (0.40, 0.62, 1.00, 1.0),
    SegmentKind.DROP_THROUGH: (0.35, 0.85, 0.95, 1.0),
    SegmentKind.CLIMB: (0.85, 0.45, 0.95, 1.0),
    SegmentKind.SWIM: (0.25, 0.85, 0.90, 1.0),
    SegmentKind.SLOW_FALL: (0.62, 0.78, 1.00, 1.0),
    SegmentKind.BOUNCE: (0.70, 0.40, 1.00, 1.0),
    SegmentKind.BOUNCE_UP: (0.82, 0.35, 1.00, 1.0),
    SegmentKind.WIND: (0.30, 0.90, 0.70, 1.0),
    SegmentKind.WELL: (0.55, 0.40, 0.95, 1.0),
    SegmentKind.DAMAGE_LAUNCH: (0.95, 0.25, 0.25, 1.0),
    SegmentKind.DAMAGE_KNOCKBACK: (0.95, 0.40, 0.10, 1.0),
}


def _segment_color(kind: SegmentKind) -> tuple[float, float, float, float]:
    return _SEGMENT_COLORS.get(kind, (0.90, 0.90, 0.90, 1.0))


def _item_name(item: int) -> str:
    name = item_database.get(item).name

    return name.decode() if isinstance(name, bytes) else name


def _clothing_slot(item: int) -> str:
    """The `Clothing` field an item is worn in (items.dat `clothing_type`)."""
    return _CLOTHING_SLOTS[item_database.get(item).clothing_type]


def _item_label(item: int) -> str:
    """`Name (slot id)` -- cached, items.dat is only read on first sight of an item."""
    label = _label_cache.get(item)
    if label is None:
        label = f"{_item_name(item)} ({_clothing_slot(item)} {item})"
        _label_cache[item] = label

    return label


def _modifier_groups() -> tuple[tuple[str, tuple[int, ...]], ...]:
    """`(header, item ids)` per modifier, built lazily (importing the demo must not read items.dat)."""
    global _groups_cache
    if _groups_cache is None:
        groups = (
            ("Slow fall - parasol (hold jump)", PARASOL_ITEMS),
            ("Slow fall - wings / jetpack (hold jump)", GLIDE_ITEMS),
            ("Water float - floatie", FLOATIE_ITEMS),
            ("Water vehicle - buoyancy (dinghy / jet skis hold it)", WATER_VEHICLE_ITEMS),
            ("Wall climbing - gear (Climbing Wall / roped piton)", CLIMB_GEAR_ITEMS),
            ("Slippery - slide on any surface (wear the Snowman Mask + Suit together)", SLIPPERY_ITEMS),
            ("Skating - cancel the slide (ice control)", SKATING_ITEMS),
            ("Snowshoes - keep the snow jump", frozenset({SNOWSHOES})),
        )
        _groups_cache = tuple((header, tuple(sorted(items, key=lambda i: _item_name(i).lower()))) for header, items in groups)

    return _groups_cache


_PHYSICS_KEYS = {
    glfw.KEY_A,
    glfw.KEY_D,
    glfw.KEY_W,
    glfw.KEY_S,
    glfw.KEY_LEFT,
    glfw.KEY_RIGHT,
    glfw.KEY_UP,
    glfw.KEY_DOWN,
    glfw.KEY_SPACE,
}

_KEY_NAMES = {
    glfw.KEY_A: "A",
    glfw.KEY_D: "D",
    glfw.KEY_W: "W",
    glfw.KEY_S: "S",
    glfw.KEY_LEFT: "LEFT",
    glfw.KEY_RIGHT: "RIGHT",
    glfw.KEY_UP: "UP",
    glfw.KEY_DOWN: "DOWN",
    glfw.KEY_SPACE: "SPACE",
    glfw.KEY_ESCAPE: "ESC",
    glfw.KEY_R: "R",
    glfw.KEY_TAB: "TAB",
    glfw.KEY_F3: "F3",
    glfw.KEY_F4: "F4",
    glfw.KEY_F5: "F5",
    glfw.KEY_F6: "F6",
}


def _key_name(key: int) -> str:
    return _KEY_NAMES.get(key, f"KEY_{key}")


class GPUPhysicsDemo:
    def __init__(self, world_path: str | None = None, width: int = 1280, height: int = 720):
        if not glfw.init():
            raise RuntimeError("Failed to initialize glfw")

        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
        glfw.window_hint(glfw.VISIBLE, True)

        self.window = glfw.create_window(width, height, "Growtopia Physics Demo (GPU)", None, None)
        if not self.window:
            glfw.terminate()
            raise RuntimeError("Failed to create glfw window")

        glfw.make_context_current(self.window)
        glfw.swap_interval(1)

        imgui.create_context()
        self.imgui_renderer = GlfwRenderer(self.window)
        self.io = imgui.get_io()

        self.world = self.load_world(world_path)
        self.world_path = world_path

        # no server/inventory in the demo: punch requests are logged, not applied
        self.controller = PlayerController(self.world, net_id=PLAYER_NET_ID, send=self._log_packet, optimistic=False)
        self.spawn = self._find_spawn(self.world)
        self.controller.spawn(*self.spawn, state=CharacterState(flags=CharacterFlags.DOUBLE_JUMP))
        self._accumulator = 0.0

        self._recording_file = None
        self._recording_path: Path | None = None
        self._recording_started_at = 0.0
        self._recording_ticks = 0
        self._recording_frames = 0
        self._recording_events: list[dict] = []

        self.world_renderer = WorldRenderer(self.world)

        self.player = Player(
            net_id=PLAYER_NET_ID,
            name=b"Player",
            colrect=vec4(0.0, 0.0, self.controller.width, self.controller.height),
            pos=vec2(*self._render_pos()),
        )
        self.world.add_player(self.player)
        self.world.set_local_player(self.player)  # owns the respawn/checkpoint state
        self._sync_player_entity()

        camera = self.world_renderer._camera
        camera.resize(width, height)
        camera.zoom = 2.0
        camera.pos = vec2(*self._camera_target_point())
        self.camera_follow_speed = 14.0
        self._camera_snapped = True

        self.keys_pressed = set()
        self.mouse_held = False
        self._context_tile: tuple[int, int] | None = None
        self.event_router = EventRouter(self.window)

        # -- pathfinding ---------------------------------------------------------
        # The pathfinder only *reads* the controller to plan; the autopilot drives it
        # exclusively through `set_input(left, right, jump)`, and the fixed-step loop
        # below calls `step()` -- the physics engine.  Nothing here writes x/y/vx/vy.
        self.pathfinder = SegmentedPathfinder(self.controller, time_budget_ms=150.0)
        self.autopilot = PathAutopilot(self.controller, self.pathfinder)
        self.path_status = "idle"
        self.show_path = True
        self.show_path_labels = True
        self.show_path_trail = True
        self._path_trail: deque[tuple[float, float]] = deque(maxlen=900)

        self.dt = FIXED_DT
        self.running = True

        print("GPU Physics Demo initialized")

    def _rand_iter[T](self, iter: Iterator[T]) -> T:
        try:
            item = next(iter)
        except StopIteration:
            raise ValueError("Iterator is empty")

        for i, x in enumerate(iter, start=2):
            if random.randrange(i) == 0:
                item = x

        return item

    def load_world(self, world_path: str | None = None) -> World:
        if world_path:
            return World.from_file(world_path)

        return World.from_file(self._rand_iter(Path(setting.appdir / "worlds").glob("*")))

    def _find_spawn(self, world: World) -> tuple[float, float]:
        for ty in range(world.height):
            for tx in range(world.width):
                tile = world.get_tile(tx, ty)
                if tile is not None and tile.fg_id == MAIN_DOOR:
                    w, h = HITBOX
                    return tx * TILE + (TILE - w) / 2.0, (ty + 1) * TILE - h

        return 0.0, 0.0

    def _render_pos(self) -> tuple[float, float]:
        return self.controller.x, self.controller.y

    def _camera_target_point(self) -> tuple[float, float]:
        x, y = self._render_pos()
        return x + self.controller.width / 2.0, y + self.controller.height / 2.0

    def _reset_avatar(self) -> None:
        self.controller.teleport(*self.spawn)
        self.controller.jump_latch = False
        self.controller.double_jumped = False
        self._camera_snapped = False
        self._sync_player_entity()

    def _sync_player_entity(self) -> None:
        self.player.pos = vec2(*self._render_pos())
        self.player.flags = self.controller.build_state_packet().flags

    def handle_input(self) -> None:
        left = glfw.KEY_A in self.keys_pressed or glfw.KEY_LEFT in self.keys_pressed
        right = glfw.KEY_D in self.keys_pressed or glfw.KEY_RIGHT in self.keys_pressed
        jump = glfw.KEY_W in self.keys_pressed or glfw.KEY_SPACE in self.keys_pressed or glfw.KEY_UP in self.keys_pressed

        if self.autopilot.active:
            if left or right or jump:
                # manual input always wins: drop the autopilot and drive normally
                self._release_path("cancelled by manual input")

            return

        self.controller.set_input(left=left, right=right, jump=jump)

    # -- pathfinding -----------------------------------------------------------

    def _pathfind_at_screen(self, sx: float, sy: float) -> None:
        tx, ty = self._tile_at_screen(sx, sy)
        if not (0 <= tx < self.world.width and 0 <= ty < self.world.height):
            print(f"pathfind outside the world: ({tx}, {ty})")

            return

        self._pathfind_to_tile(tx, ty)

    def _pathfind_to_tile(self, tx: int, ty: int) -> None:
        """Plan to ``(tx, ty)`` and let the autopilot walk/jump the avatar there."""
        started = time.perf_counter()
        result = self.autopilot.plan_to_tile(tx, ty)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        path = self.autopilot.path
        self._path_trail.clear()

        if path is None:
            self.path_status = self.autopilot.status
            print(f"pathfind -> ({tx}, {ty}) {self.path_status} [{elapsed_ms:.1f} ms]")

            return

        self.path_status = result.status.name
        kinds = ", ".join(kind.name for kind in path.kinds()[:8])
        suffix = ", ..." if len(path.segments) > 8 else ""
        print(
            f"pathfind -> ({tx}, {ty}) {result.status.name} in {elapsed_ms:.1f} ms: "
            f"{len(path.segments)} segments, {path.total_ticks} ticks [{kinds}{suffix}]"
        )

    def _release_path(self, reason: str | None) -> None:
        """Stop the autopilot and hand the avatar back to the keyboard.

        Only the input is reset -- the avatar's state is never touched, so it keeps
        the position/velocity the physics engine produced.
        """
        if not self.autopilot.active:
            return

        self.autopilot.cancel(reason)
        if reason is not None:
            print(f"path released: {reason}")
        self.path_status = self.autopilot.status

    def _active_path(self):
        return self.autopilot.path

    def _advance_tick(self) -> None:
        """One fixed tick: the autopilot supplies input, the controller does physics."""
        was_active = self.autopilot.active
        self.autopilot.advance()
        self.controller.step()
        if was_active and not self.autopilot.active:
            # the plan just finished: keep the printed status and the drawn route
            self.path_status = self.autopilot.status
            print(f"path finished: {self.autopilot.status}")


    @staticmethod
    def _log_packet(pkt: TankPacket) -> None:
        print(f"[packet] {pkt.compact_repr()}")

    def _tile_at_screen(self, sx: float, sy: float) -> tuple[int, int]:
        lx, ly = self.world_renderer._to_local(sx, sy)
        world_pos = self.world_renderer._camera.screen_to_world(lx, ly)

        return math.floor(world_pos.x / TILE), math.floor(world_pos.y / TILE)

    def _touch_at_screen(self, sx: float, sy: float) -> None:
        tx, ty = self._tile_at_screen(sx, sy)
        if not (0 <= tx < self.world.width and 0 <= ty < self.world.height):
            print(f"touch outside the world: ({tx}, {ty})")

        print(f"touch press -> tile ({tx}, {ty})")
        self.controller.touch_press(tx, ty)

    def handle_touch(self) -> None:
        """Feed the held button to the controller (client ``onTouchHoldTick``)."""
        if not self.mouse_held:
            return

        sx, sy = glfw.get_cursor_pos(self.window)
        tx, ty = self._tile_at_screen(sx, sy)
        if 0 <= tx < self.world.width and 0 <= ty < self.world.height:
            self.controller.touch_hold(tx, ty)

    def _toggle_recording(self) -> None:
        if self._recording_file is not None:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        try:
            RECORDING_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            self._recording_path = RECORDING_DIR / f"physics_{stamp}.jsonl"
            self._recording_file = self._recording_path.open("w", encoding="utf-8")
        except OSError as exc:
            print(f"Could not start recording: {exc}")
            self._recording_file = None
            self._recording_path = None

            return

        self._recording_started_at = glfw.get_time()
        self._recording_ticks = 0
        self._recording_frames = 0
        self._recording_events = []
        header = {
            "type": "header",
            "t": 0.0,
            "started_at": datetime.now().isoformat(timespec="milliseconds"),
            "source": str(Path(__file__).resolve()),
            "world_path": str(self.world_path) if self.world_path else None,
            "world_name": (self.world.name.decode("utf-8", "replace") if self.world is not None and getattr(self.world, "name", None) else None),
            "world_size": ([int(self.world.width), int(self.world.height)] if self.world is not None else None),
            "fixed_dt": self.controller.fixed_dt,
            "constants": {
                "TILE": TILE,
                "HITBOX": list(HITBOX),
                "FIXED_DT": FIXED_DT,
                "JUMP_SPEED": JUMP_SPEED,
                "JUMP_CUT_ACCEL": JUMP_CUT_ACCEL,
                "MAX_FALL": MAX_FALL,
                "WATER_VERTICAL_SCALE": WATER_VERTICAL_SCALE,
                "SLIDE_ACCEL_SCALE": SLIDE_ACCEL_SCALE,
                "SLIDE_WALL_BOUNCE": SLIDE_WALL_BOUNCE,
                "BOUNCY_SPEED": BOUNCY_SPEED,
                "TRAMPOLINE_SPEED": TRAMPOLINE_SPEED,
                "TRAMPOLINE_MOMENTUM_SPEED": TRAMPOLINE_MOMENTUM_SPEED,
                "DAMAGING_KNOCKBACK_SPEED": DAMAGING_KNOCKBACK_SPEED,
                "DAMAGING_LAUNCH_SPEED": DAMAGING_LAUNCH_SPEED,
                "DAMAGING_LAUNCH_NO_GRAVITY_SPEED": DAMAGING_LAUNCH_NO_GRAVITY_SPEED,
                "JUMP_REDUCED_SCALE": JUMP_REDUCED_SCALE,
                "SLOW_FALL_ACCEL_SCALE": SLOW_FALL_ACCEL_SCALE,
                "ANTIGRAVITY_ACCEL_SCALE": ANTIGRAVITY_ACCEL_SCALE,
                "MUD_SPEED_SCALE": MUD_SPEED_SCALE,
                "WATER_FLOAT_ACCEL": WATER_FLOAT_ACCEL,
                "WATER_FLOAT_FALL_ACCEL": WATER_FLOAT_FALL_ACCEL,
                "WATER_FLOAT_MAX_FALL": WATER_FLOAT_MAX_FALL,
                "WATER_FLOAT_DURATION_MS": WATER_FLOAT_DURATION_MS,
            },
            "character_state": self._state_snapshot(),
            "avatar_start": self._snapshot(),
        }
        self._write_record(header)
        print(f"Recording started: {self._recording_path}")
        print("  Use the Player menu to stop and save.")

    def _stop_recording(self) -> None:
        if self._recording_file is None:
            return

        if self._recording_events:
            self._write_record({"type": "final_events", "events": self._recording_events})
            self._recording_events = []

        self._write_record(
            {
                "type": "footer",
                "t": round(glfw.get_time() - self._recording_started_at, 6),
                "ticks": self._recording_ticks,
                "frames": self._recording_frames,
                "avatar": self._snapshot(),
            }
        )
        path = self._recording_path
        if self._recording_file is not None:
            try:
                self._recording_file.close()
            except OSError:
                pass

        self._recording_file = None
        self._recording_path = None
        if path is not None:
            try:
                (RECORDING_DIR / "latest.txt").write_text(str(path), encoding="utf-8")
            except OSError:
                pass

        print(f"Recording stopped: {path} " f"({self._recording_ticks} ticks, {self._recording_frames} frames)")

    def _write_record(self, record: dict) -> None:
        if self._recording_file is None:
            return

        try:
            self._recording_file.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")
            self._recording_file.flush()
        except Exception as exc:
            print(f"Recording write failed: {exc}")
            try:
                self._recording_file.close()
            except OSError:
                pass
            self._recording_file = None
            self._recording_path = None

    def _state_snapshot(self) -> dict:
        st = self.controller.state
        return {
            "flags": int(st.flags),
            "max_velocity": st.max_velocity,
            "horizontal_accel": st.horizontal_accel,
            "vertical_accel": st.vertical_accel,
            "velocity_in_water": st.velocity_in_water,
        }

    def _snapshot(self) -> dict:
        c = self.controller
        return {
            "x": round(c.x, 4),
            "y": round(c.y, 4),
            "vx": round(c.vx, 4),
            "vy": round(c.vy, 4),
            "frac_x": round(c.frac_x, 4),
            "frac_y": round(c.frac_y, 4),
            "facing_right": c.facing_right,
            "grounded": c.grounded,
            "sliding": c.sliding,
            "in_water": c.in_water,
            "left": c.left,
            "right": c.right,
            "jump": c.jump,
            "jump_latch": c.jump_latch,
            "double_jumped": c.double_jumped,
            "killed": c.killed,
            "killed_pending": c.killed_pending,
            "on_fire": c.on_fire,
            "on_acid": c.on_acid,
            "damaged": c.damaged,
            "damage_slip": c.damage_slip,
            "water_float": c.water_float,
            "mud": c.mud,
            "left_ground": c.left_ground,
            "parasol": c.parasol,
            "glide": c.glide,
        }

    def _record_tick(self) -> None:
        if self._recording_file is None:
            return

        self._recording_ticks += 1
        events = self._recording_events
        self._recording_events = []
        self._write_record(
            {
                "type": "tick",
                "t": round(glfw.get_time() - self._recording_started_at, 6),
                "tick": int(self.controller.tick),
                "dt": round(self.controller.fixed_dt, 6),
                "keys_pressed": sorted(_KEY_NAMES.get(key, f"KEY_{key}") for key in self.keys_pressed),
                "events": events,
                "avatar": self._snapshot(),
            }
        )

    def _record_frame(self, dt: float) -> None:
        if self._recording_file is None:
            return

        self._recording_frames += 1
        events = self._recording_events
        self._recording_events = []
        self._write_record(
            {
                "type": "frame",
                "t": round(glfw.get_time() - self._recording_started_at, 6),
                "frame": self._recording_frames,
                "dt": round(dt, 6),
                "tick": int(self.controller.tick),
                "keys_pressed": sorted(_key_name(k) for k in self.keys_pressed),
                "events": events,
                "avatar": self._snapshot(),
            }
        )

    def _process_events(self) -> None:
        for event in self.event_router.poll():
            if isinstance(event, KeyEvent):
                if self._recording_file is not None:
                    action_name = {
                        glfw.PRESS: "press",
                        glfw.RELEASE: "release",
                        glfw.REPEAT: "repeat",
                    }.get(event.action, str(event.action))
                    self._recording_events.append(
                        {
                            "t": round(glfw.get_time() - self._recording_started_at, 6),
                            "key": int(event.key),
                            "key_name": _key_name(event.key),
                            "action": action_name,
                        }
                    )

                if event.action == glfw.PRESS:
                    self.keys_pressed.add(event.key)
                    if event.key == glfw.KEY_ESCAPE:
                        self.running = False
                elif event.action == glfw.RELEASE:
                    self.keys_pressed.discard(event.key)

                if event.key in _PHYSICS_KEYS or event.key == glfw.KEY_ESCAPE:
                    continue

            if isinstance(event, MouseButtonEvent) and event.button == glfw.MOUSE_BUTTON_LEFT:
                if event.action == glfw.PRESS:
                    modifiers = glfw.get_key(self.window, glfw.KEY_LEFT_CONTROL) or glfw.get_key(
                        self.window, glfw.KEY_RIGHT_CONTROL
                    )
                    if modifiers:
                        # Ctrl+Click asks the pathfinder for a route (left click alone punches)
                        self._pathfind_at_screen(event.screen_x, event.screen_y)

                        continue

                    self.mouse_held = True
                    self._touch_at_screen(event.screen_x, event.screen_y)
                elif event.action == glfw.RELEASE:
                    self.mouse_held = False
                    self.controller.touch_release()
                continue  # left click no longer pans the camera

            if isinstance(event, MouseButtonEvent) and event.button == glfw.MOUSE_BUTTON_RIGHT and event.action == glfw.PRESS:
                tx, ty = self._tile_at_screen(event.screen_x, event.screen_y)
                if 0 <= tx < self.world.width and 0 <= ty < self.world.height:
                    self._context_tile = (tx, ty)  # the renderer still opens its own menu

            if isinstance(event, ResizeEvent):
                self.world_renderer._camera.resize(event.width, event.height)
                self.world_renderer._camera3d.resize(event.width, event.height)
                self.world_renderer._dirty = True
                continue

            self.world_renderer.handle_event(event)

    def update_physics(self, dt: float) -> None:
        self.handle_touch()  # client onTouchHoldTick: resolves the tile before the tick

        self._accumulator += dt
        while self._accumulator >= self.controller.fixed_dt:
            self._accumulator -= self.controller.fixed_dt
            self._advance_tick()
            self._record_tick()
            if self.show_path_trail:
                self._path_trail.append(
                    (self.controller.x + self.controller.width / 2.0, self.controller.y + self.controller.height / 2.0)
                )

        self._sync_player_entity()

    def update_camera(self, dt: float) -> None:
        camera = self.world_renderer._camera

        if any(gesture.active for gesture in self.world_renderer._drag_gestures.values()):
            self.world_renderer._dirty = True
            return

        half_w = camera.width / (2.0 * camera.zoom)
        half_h = camera.height / (2.0 * camera.zoom)

        world_min_x = -_TILE_HALF
        world_max_x = self.world.width * TILE - _TILE_HALF
        world_min_y = -_TILE_HALF
        world_max_y = self.world.height * TILE - _TILE_HALF
        focus_x, focus_y = self._camera_target_point()

        if world_max_x - world_min_x <= half_w * 2.0:
            target_x = (world_min_x + world_max_x) / 2.0
        else:
            target_x = max(
                world_min_x + half_w,
                min(world_max_x - half_w, focus_x),
            )

        if world_max_y - world_min_y <= half_h * 2.0:
            target_y = (world_min_y + world_max_y) / 2.0
        else:
            target_y = max(
                world_min_y + half_h,
                min(world_max_y - half_h, focus_y),
            )

        if not self._camera_snapped:
            camera.pos = vec2(target_x, target_y)
            self._camera_snapped = True
        else:
            alpha = 1.0 - math.exp(-self.camera_follow_speed * dt)
            camera.pos.x += (target_x - camera.pos.x) * alpha
            camera.pos.y += (target_y - camera.pos.y) * alpha

        self.world_renderer._dirty = True

    def render_world_context_menu(self) -> None:
        """Append the demo's entries to the renderer's right-click menu (demo-only).

        The renderer builds `world_context_menu` inline in `render()`; re-beginning
        the same popup while it is open adds our items after its own, with no
        change to `WorldRenderer`. Must run inside the host window so the popup ID
        resolves against the same window.
        """
        if self._context_tile is None or not imgui.is_popup_open("world_context_menu"):
            return

        if imgui.begin_popup("world_context_menu"):
            imgui.separator()
            if imgui.menu_item("Pathfind here", "Ctrl+Click", False)[0]:
                self._pathfind_to_tile(*self._context_tile)
                imgui.close_current_popup()
            if imgui.menu_item("Stop pathfinding", "", False, self.autopilot.active)[0]:
                self._release_path("stopped")
                imgui.close_current_popup()
            if imgui.menu_item("Teleport here", "", False)[0]:
                self._teleport_to_tile(*self._context_tile)
                imgui.close_current_popup()
            imgui.end_popup()

    def _teleport_to_tile(self, tx: int, ty: int) -> None:
        """Stand the local player on top of the tile at ``(tx, ty)``."""
        w, h = self.controller.width, self.controller.height
        self.controller.teleport(tx * TILE + (TILE - w) / 2.0, (ty + 1) * TILE - h)
        self.controller.jump_latch = False
        self.controller.double_jumped = False
        self._camera_snapped = False
        self._sync_player_entity()

    # -- path overlay ----------------------------------------------------------

    def _overlay_point(self, wx: float, wy: float) -> tuple[float, float]:
        """World -> absolute screen: the renderer draws its FBO at ``_image_origin``."""
        point = self.world_renderer._camera.world_to_screen(wx, wy)
        ox, oy = self.world_renderer._image_origin

        return ox + point.x, oy + point.y

    def _segment_points(self, segment) -> tuple[tuple[float, float], tuple[float, float]]:
        hw = self.controller.width / 2.0
        hh = self.controller.height / 2.0

        return (
            self._overlay_point(segment.start.x + hw, segment.start.y + hh),
            self._overlay_point(segment.end.x + hw, segment.end.y + hh),
        )

    def render_path_overlay(self) -> None:
        """Draw the planned route in world space (2D view only, inside the host window).

        One polyline per segment, coloured by the *observed* movement method, with
        the traversed part dimmed and the segment the avatar is executing
        highlighted.  The goal tile is outlined.  Purely visual: the follower
        drives the avatar through ``set_input`` and nothing here touches it.
        """
        if not self.show_path or self.world_renderer.mode_3d:
            return

        path = self._active_path()
        if path is None and self.autopilot.target is None:
            return

        draw = imgui.get_window_draw_list()
        u32 = imgui.get_color_u32

        if self.show_path_trail and len(self._path_trail) >= 2:
            previous = self._overlay_point(*self._path_trail[0])
            for point in list(self._path_trail)[1:]:
                current = self._overlay_point(*point)
                draw.add_line(imgui.ImVec2(*previous), imgui.ImVec2(*current), u32((1.0, 1.0, 1.0, 0.18)), 1.5)
                previous = current

        if self.autopilot.target is not None:
            tx, ty = self.autopilot.target
            if 0 <= tx < self.world.width and 0 <= ty < self.world.height:
                lo = self._overlay_point(tx * TILE, ty * TILE)
                hi = self._overlay_point((tx + 1) * TILE, (ty + 1) * TILE)
                goal_color = (1.0, 0.85, 0.25, 0.95)
                draw.add_rect(imgui.ImVec2(*lo), imgui.ImVec2(*hi), u32(goal_color), 2.0)
                draw.add_rect_filled(imgui.ImVec2(*lo), imgui.ImVec2(*hi), u32((1.0, 0.85, 0.25, 0.12)))
                label = "goal"
                draw.add_text(imgui.ImVec2(lo[0] + 3.0, lo[1] - 15.0), u32(goal_color), label)

        if path is None:
            return

        segments = path.segments
        current = self.autopilot.progress[0] if self.autopilot.active else -1
        labelled = self.show_path_labels and len(segments) <= 12

        for index, segment in enumerate(segments):
            start, end = self._segment_points(segment)
            r, g, b, a = _segment_color(segment.kind)
            if index < current:
                alpha, thickness = a * 0.28, 2.0
            elif current >= 0 and index == current:
                alpha, thickness = a, 4.0
            else:
                alpha, thickness = a * 0.75, 3.0

            color = u32((r, g, b, alpha))
            draw.add_line(imgui.ImVec2(*start), imgui.ImVec2(*end), color, thickness)
            dot = 4.5 if index == current else 3.0
            draw.add_circle_filled(imgui.ImVec2(*start), dot, color)
            draw.add_circle_filled(imgui.ImVec2(*end), dot, color)

            if labelled or index == current:
                mx, my = (start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0
                prefix = "! " if segment.damage_hits else ""
                draw.add_text(imgui.ImVec2(mx + 6.0, my - 7.0), u32((r, g, b, 1.0)), f"{prefix}{segment.kind.name}")

    def render_menu(self) -> None:
        """User-facing player menu: toggles only, no developer stats or key hints."""
        imgui.set_next_window_pos((10, 10), imgui.Cond_.first_use_ever)
        imgui.set_next_window_size((240, 0), imgui.Cond_.first_use_ever)

        if imgui.begin("Player", flags=imgui.WindowFlags_.always_auto_resize)[0]:
            if imgui.collapsing_header("Character"):
                self._flag_checkbox("Double jump", CharacterFlags.DOUBLE_JUMP)
                self._flag_checkbox("No clip", CharacterFlags.NOCLIP)
                self._flag_checkbox("Ignore lava", CharacterFlags.IGNORE_LAVA)
                self._flag_checkbox("Ignore spikes", CharacterFlags.IGNORE_SPIKES)

            if imgui.collapsing_header("Modifiers (clothing)"):
                for group, items in _modifier_groups():
                    if imgui.collapsing_header(group):
                        for item in items:
                            self._clothing_checkbox(_item_label(item), _clothing_slot(item), item)

            if imgui.button("Reset position"):
                self._reset_avatar()

            if imgui.collapsing_header("Pathfinding"):
                imgui.text_disabled("Ctrl+Click a tile to pathfind")
                imgui.text_disabled("Right click -> Pathfind here")
                imgui.text_disabled("Press a movement key to cancel")

                target = self.autopilot.target
                imgui.text(f"Target: {target[0]}, {target[1]}" if target else "Target: -")
                imgui.text_wrapped(f"Status: {self.path_status}")

                path = self._active_path()
                if path is not None:
                    counts: dict[str, int] = {}
                    for segment in path.segments:
                        counts[segment.kind.name] = counts.get(segment.kind.name, 0) + 1
                    breakdown = ", ".join(f"{name} x{count}" for name, count in counts.items())
                    imgui.text_wrapped(f"Segments: {len(path.segments)} ({path.total_ticks} ticks)")
                    imgui.text_wrapped(breakdown)
                    if path.damage_hits:
                        imgui.text_colored(imgui.ImVec4(1.0, 0.4, 0.3, 1.0), f"Damage hits: {path.damage_hits}")

                if self.autopilot.active:
                    index, tick, total = self.autopilot.progress
                    imgui.text(f"Executing: segment {index + 1}/{total}, tick {tick}, replans {self.autopilot.replans}")
                    if imgui.button("Stop pathfinding"):
                        self._release_path("stopped")
                else:
                    imgui.begin_disabled()
                    imgui.button("Stop pathfinding")
                    imgui.end_disabled()

                changed, value = imgui.checkbox("Show path", self.show_path)
                if changed:
                    self.show_path = value
                changed, value = imgui.checkbox("Segment labels", self.show_path_labels)
                if changed:
                    self.show_path_labels = value
                changed, value = imgui.checkbox("Avatar trail", self.show_path_trail)
                if changed:
                    self.show_path_trail = value
                    if not value:
                        self._path_trail.clear()

            recording = self._recording_file is not None
            changed, value = imgui.checkbox("Record session", recording)
            if changed and value != recording:
                self._toggle_recording()
        imgui.end()

    def _flag_checkbox(self, label: str, flag: CharacterFlags) -> None:
        changed, value = imgui.checkbox(label, bool(self.controller.state.flags & flag))
        if changed:
            if value:
                self.controller.state.flags |= flag
            else:
                self.controller.state.flags &= ~flag

    def _clothing_checkbox(self, label: str, slot: str, item: int) -> None:
        clothing = self.player.clothing
        changed, value = imgui.checkbox(label, getattr(clothing, slot) == item)
        if changed:
            setattr(clothing, slot, item if value else 0)

    def run(self) -> None:
        last_time = glfw.get_time()

        while self.running and not glfw.window_should_close(self.window):
            current_time = glfw.get_time()
            dt = current_time - last_time
            last_time = current_time
            dt = min(dt, 0.1)

            glfw.poll_events()
            self._process_events()
            self.handle_input()

            self.update_physics(dt)
            self._record_frame(dt)

            self.update_camera(dt)

            self.world_renderer.update(dt)

            glfw.make_context_current(self.window)

            self.imgui_renderer.process_inputs()
            imgui.new_frame()

            glClearColor(0.1, 0.1, 0.1, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)  # pyright: ignore[reportOperatorIssue]

            viewport = imgui.get_main_viewport()
            imgui.set_next_window_pos(viewport.pos)
            imgui.set_next_window_size(viewport.size)
            host_flags = (
                imgui.WindowFlags_.no_decoration
                | imgui.WindowFlags_.no_move
                | imgui.WindowFlags_.no_bring_to_front_on_focus
                | imgui.WindowFlags_.no_nav_focus
                | imgui.WindowFlags_.no_saved_settings
            )
            imgui.push_style_var(imgui.StyleVar_.window_padding, (0.0, 0.0))
            imgui.begin("##gpu_physics_world", flags=host_flags)
            self.world_renderer.set_active(True)
            self.world_renderer.render()
            self.render_path_overlay()
            self.render_world_context_menu()
            imgui.end()
            imgui.pop_style_var()

            self.render_menu()

            imgui.render()
            self.imgui_renderer.render(imgui.get_draw_data())

            glfw.swap_buffers(self.window)

        self._stop_recording()
        self.world_renderer.delete()
        self.event_router.delete()
        self.imgui_renderer.shutdown()
        glfw.destroy_window(self.window)
        glfw.terminate()


def main():
    world_path = None
    if len(sys.argv) > 1:
        world_path = sys.argv[1]

    demo = GPUPhysicsDemo(world_path=world_path)
    demo.run()


if __name__ == "__main__":
    main()
