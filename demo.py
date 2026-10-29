import random
import sys
import math
import json
from datetime import datetime
from pathlib import Path
from typing import Iterator
from pyglm.glm import vec2, vec4

import glfw
from OpenGL.GL import GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, glClear, glClearColor
from imgui_bundle import imgui
from imgui_bundle.python_backends.glfw_backend import GlfwRenderer

from gtools import setting
from gtools.baked.items import MAIN_DOOR
from gtools.core.growtopia.world import World
from gtools.core.growtopia.player import Player
from gtools.gui.event import EventRouter, KeyEvent, ResizeEvent
from gtools.gui.lib.world_renderer import WorldRenderer
from gtools.core.growtopia.player import CharacterFlags, CharacterState
from gtools.core.growtopia.physics.engine import (
    PhysicsEngine,
    PhysicsComponent,
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
)

PLAYER_NET_ID = 1
_TILE_HALF = TILE / 2.0

RECORDING_DIR = Path(__file__).resolve().parent / "recordings"


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
    glfw.KEY_F4,
    glfw.KEY_F5,
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

        self.engine = PhysicsEngine(self.world)
        self.spawn = self._find_spawn(self.world)
        self.body: PhysicsComponent = self.engine.register(PLAYER_NET_ID, *self.spawn, state=CharacterState(flags=CharacterFlags.DOUBLE_JUMP))
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
            colrect=vec4(0.0, 0.0, self.engine.width, self.engine.height),
            pos=vec2(*self._render_pos()),
        )
        self.world.add_player(self.player)
        self._sync_player_entity()

        camera = self.world_renderer._camera
        camera.resize(width, height)
        camera.zoom = 2.0
        camera.pos = vec2(*self._camera_target_point())
        self.camera_follow_speed = 14.0
        self._camera_snapped = True

        self.keys_pressed = set()
        self.event_router = EventRouter(self.window)

        self.dt = FIXED_DT
        self.running = True

        self.show_debug = True

        print("GPU Physics Demo initialized")
        print("Controls:")
        print("  A/D or Left/Right - Move")
        print("  W/Space/Up - Jump")
        print("  R - Reset position")
        print("  Mouse wheel - Zoom")
        print("  Middle mouse drag - Pan camera")
        print("  Tab - Toggle settings")
        print("  F3 - Toggle debug overlay")
        print("  F6 - Start/stop physics recording (JSONL)")
        print("  Water/slide are detected automatically from the tiles.")
        print("  ESC - Quit")

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
                    w, h = self.engine.width, self.engine.height
                    return tx * TILE + (TILE - w) / 2.0, (ty + 1) * TILE - h

        return 0.0, 0.0

    def _render_pos(self) -> tuple[float, float]:
        return self.body.x, self.body.y

    def _camera_target_point(self) -> tuple[float, float]:
        x, y = self._render_pos()
        return x + self.engine.width / 2.0, y + self.engine.height / 2.0

    def _reset_avatar(self) -> None:
        self.engine.teleport(PLAYER_NET_ID, *self.spawn)
        self.body.jump_latch = False
        self.body.double_jumped = False
        self._camera_snapped = False
        self._sync_player_entity()

    def _sync_player_entity(self) -> None:
        self.player.pos = vec2(*self._render_pos())
        self.player.flags = self.engine.build_state_packet(PLAYER_NET_ID).flags

    def handle_input(self) -> None:
        left = glfw.KEY_A in self.keys_pressed or glfw.KEY_LEFT in self.keys_pressed
        right = glfw.KEY_D in self.keys_pressed or glfw.KEY_RIGHT in self.keys_pressed
        jump = glfw.KEY_W in self.keys_pressed or glfw.KEY_SPACE in self.keys_pressed or glfw.KEY_UP in self.keys_pressed
        self.engine.set_input(PLAYER_NET_ID, left=left, right=right, jump=jump)

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
            "fixed_dt": self.engine.fixed_dt,
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
            },
            "character_state": self._state_snapshot(),
            "avatar_start": self._snapshot(),
        }
        self._write_record(header)
        print(f"Recording started: {self._recording_path}")
        print("  Press F6 again to stop and save.")

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
        st = self.body.state
        return {
            "flags": int(st.flags),
            "max_velocity": st.max_velocity,
            "horizontal_accel": st.horizontal_accel,
            "vertical_accel": st.vertical_accel,
            "velocity_in_water": st.velocity_in_water,
        }

    def _snapshot(self) -> dict:
        c = self.body
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
                "tick": int(self.engine.tick),
                "dt": round(self.engine.fixed_dt, 6),
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
                "tick": int(self.engine.tick),
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
                    elif event.key == glfw.KEY_R:
                        self._reset_avatar()
                    elif event.key == glfw.KEY_F3:
                        self.show_debug = not self.show_debug
                    elif event.key == glfw.KEY_F6:
                        self._toggle_recording()
                elif event.action == glfw.RELEASE:
                    self.keys_pressed.discard(event.key)

                if event.key in _PHYSICS_KEYS or event.key in (
                    glfw.KEY_ESCAPE,
                    glfw.KEY_R,
                    glfw.KEY_F3,
                    glfw.KEY_F6,
                ):
                    continue

            if isinstance(event, ResizeEvent):
                self.world_renderer._camera.resize(event.width, event.height)
                self.world_renderer._camera3d.resize(event.width, event.height)
                self.world_renderer._dirty = True
                continue

            self.world_renderer.handle_event(event)

    def update_physics(self, dt: float) -> None:
        self._accumulator += dt
        while self._accumulator >= self.engine.fixed_dt:
            self._accumulator -= self.engine.fixed_dt
            self.engine.step()
            self._record_tick()

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

    def render_debug_overlay(self) -> None:
        if not self.show_debug:
            return

        imgui.set_next_window_pos((10, 10), imgui.Cond_.first_use_ever)
        imgui.set_next_window_size((300, 400), imgui.Cond_.first_use_ever)

        if imgui.begin("Physics Debug", flags=imgui.WindowFlags_.always_auto_resize)[0]:
            camera = self.world_renderer._camera
            imgui.text(f"FPS: {imgui.get_io().framerate:.1f}")
            imgui.text(f"Tick: {self.engine.tick}")
            imgui.text(f"Zoom: {camera.zoom:.2f}")
            imgui.text(f"Camera: ({camera.pos.x:.1f}, {camera.pos.y:.1f})")
            c, st = self.body, self.body.state
            imgui.text(f"Pos: ({c.x:.1f}, {c.y:.1f})")
            imgui.text("Tile: " f"({math.floor((c.x + self.engine.width / 2) / TILE)}, " f"{math.floor((c.y + self.engine.height / 2) / TILE)})")
            imgui.text(f"Players drawn: {len(self.world.players)}")
            imgui.text(f"VX: {c.vx:.1f}")
            imgui.text(f"VY: {c.vy:.1f}")
            imgui.text(f"Input: L={int(c.left)} R={int(c.right)} J={int(c.jump)}")
            imgui.text(f"Jump latch: {c.jump_latch}")
            imgui.text(f"Accel H/V: {st.horizontal_accel:.1f} / {st.vertical_accel:.1f}")
            imgui.text(f"Max vel: {st.max_velocity:.1f}  Water vel: {st.velocity_in_water:.1f}")
            imgui.text(f"Grounded: {c.grounded}")
            imgui.text(f"Double Jump Used: {c.double_jumped}")
            imgui.text(f"Water: {c.in_water}")
            imgui.text(f"Slide: {c.sliding}")
            if self._recording_file is not None:
                imgui.text(f"RECORDING: {self._recording_ticks} ticks, " f"{self._recording_frames} frames")
                if self._recording_path is not None:
                    imgui.text(f"  {self._recording_path.name}")
                imgui.text("  F6 - stop and save")
            else:
                imgui.text("Recording: off (F6 to start)")
            imgui.separator()
            imgui.text("Controls:")
            imgui.text("A/D or Left/Right - Move")
            imgui.text("W/Space/Up - Jump")
            imgui.text("R - Reset position")
            imgui.text("Mouse wheel - Zoom")
            imgui.text("Middle drag - Pan")
            imgui.text("Tab - Settings")
            imgui.text("F3 - Debug overlay")
            imgui.text("F6 - Start/stop recording")
            imgui.text("Water/slide are detected from tiles")
            imgui.text("ESC - Quit")
        imgui.end()

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
            imgui.end()
            imgui.pop_style_var()

            self.render_debug_overlay()

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
