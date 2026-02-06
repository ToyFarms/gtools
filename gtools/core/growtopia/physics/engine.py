import pygame
import sys
import math
import keyboard

from pyglm.glm import vec2
from gtools.core.growtopia.packet import NetPacket
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    INTEREST_STATE,
    INTEREST_STATE_UPDATE,
    Interest,
    PendingPacket,
)
from gtools.proxy.extension.sdk import Extension, dispatch
from gtools.proxy.extension.sdk_utils import helper


class GlobalKeys:
    @staticmethod
    def pressed(key):
        return keyboard.is_pressed(key)


pygame.init()

SCREEN_WIDTH = 1200
SCREEN_HEIGHT = 800
FPS = 60
TPS = 60

GRAVITY = 1000.0
MAX_HORIZONTAL_SPEED = 250.0
HORIZONTAL_ACCELERATION = 1200.0
HORIZONTAL_DECELERATION = 1800.0
AIR_CONTROL_MULTIPLIER = 1

JUMP_FORCE = -450.0
MAX_FALL_SPEED = 800.0

GROUND_Y = 700


class Player:
    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.width = 20
        self.height = 30

        self.velocity_x = 0.0
        self.velocity_y = 0.0

        self.facing_left = False
        self.on_ground = False
        self.has_double_jump = False

        self.trail = []
        self.trail_max_length = 20

        self.prev_x = x
        self.prev_y = y
        self.color: tuple[int, int, int] = (255, 255, 255)

    def update(self, dt):
        self.prev_x = self.x
        self.prev_y = self.y

        acceleration_x = 0.0

        moving_left = GlobalKeys.pressed("left") or GlobalKeys.pressed("a")
        moving_right = GlobalKeys.pressed("right") or GlobalKeys.pressed("d")

        if moving_left:
            self.facing_left = True
        elif moving_right:
            self.facing_left = False

        control_multiplier = 1.0 if self.on_ground else AIR_CONTROL_MULTIPLIER

        if moving_left and not moving_right:
            acceleration_x = -HORIZONTAL_ACCELERATION * control_multiplier
        elif moving_right and not moving_left:
            acceleration_x = HORIZONTAL_ACCELERATION * control_multiplier
        else:
            if abs(self.velocity_x) > 0:
                decel = HORIZONTAL_DECELERATION * dt
                if abs(self.velocity_x) <= decel:
                    self.velocity_x = 0
                else:
                    self.velocity_x -= math.copysign(decel, self.velocity_x)

        self.velocity_x += acceleration_x * dt

        if abs(self.velocity_x) > MAX_HORIZONTAL_SPEED:
            self.velocity_x = math.copysign(MAX_HORIZONTAL_SPEED, self.velocity_x)

        if not self.on_ground:
            if not GlobalKeys.pressed("space"):
                if self.velocity_y < 0:
                    self.velocity_y = 0

            self.velocity_y += GRAVITY * dt

            if self.velocity_y > MAX_FALL_SPEED:
                self.velocity_y = MAX_FALL_SPEED

        self.x += self.velocity_x * dt
        self.y += self.velocity_y * dt

        if self.y + self.height >= GROUND_Y:
            self.y = GROUND_Y - self.height
            self.velocity_y = 0
            self.on_ground = True
            self.has_double_jump = True
        else:
            self.on_ground = False

        if self.x < -self.width:
            self.x = SCREEN_WIDTH
        elif self.x > SCREEN_WIDTH:
            self.x = -self.width

        self.trail.append((self.x + self.width // 2, self.y + self.height // 2))
        if len(self.trail) > self.trail_max_length:
            self.trail.pop(0)

    def get_interpolated_position(self, alpha):
        interp_x = self.prev_x + (self.x - self.prev_x) * alpha
        interp_y = self.prev_y + (self.y - self.prev_y) * alpha
        return interp_x, interp_y

    def jump(self):
        if self.on_ground:
            self.velocity_y = JUMP_FORCE
            self.on_ground = False
        elif self.has_double_jump:
            self.velocity_y = JUMP_FORCE
            self.has_double_jump = False

    def draw(self, screen, alpha=1.0):
        # draw_x, draw_y = self.get_interpolated_position(alpha)
        draw_x, draw_y = self.x, self.y

        for i, (tx, ty) in enumerate(self.trail):
            alpha_val = int(255 * (i / len(self.trail)))
            size = 2 + i // 5
            pygame.draw.circle(screen, (0, 0, 255, alpha_val), (int(tx), int(ty)), size)

        rect = pygame.Rect(int(draw_x), int(draw_y), self.width, self.height)
        pygame.draw.rect(screen, self.color, rect)

        indicator_x = draw_x + (5 if self.facing_left else self.width - 5)
        indicator_y = draw_y + self.height // 2
        color = (255, 0, 0) if self.facing_left else (0, 0, 255)
        pygame.draw.circle(screen, (color), (int(indicator_x), int(indicator_y)), 5)

        vector_scale = 0.3
        end_x = draw_x + self.width // 2 + self.velocity_x * vector_scale
        end_y = draw_y + self.height // 2 + self.velocity_y * vector_scale
        pygame.draw.line(screen, (0, 255, 0), (draw_x + self.width // 2, draw_y + self.height // 2), (int(end_x), int(end_y)), 2)


def draw_hud(screen, player, font, clock, tick_count, physics_ticks_per_second):
    y_offset = 10
    line_height = 25

    hud_rect = pygame.Rect(10, 10, 400, 250)
    pygame.draw.rect(screen, (0, 0, 0, 128), hud_rect)

    info_lines = [
        f"Render FPS: {int(clock.get_fps())}",
        f"Physics TPS: {physics_ticks_per_second:.1f} (target: {TPS})",
        f"Total Ticks: {tick_count}",
        f"Position: ({int(player.x)}, {int(player.y)})",
        f"Velocity X: {player.velocity_x:.1f} px/s",
        f"Velocity Y: {player.velocity_y:.1f} px/s",
        f"On Ground: {player.on_ground}",
        f"Has Double Jump: {player.has_double_jump}",
        f"Facing: {'Left' if player.facing_left else 'Right'}",
    ]

    for i, line in enumerate(info_lines):
        text = font.render(line, True, (255, 255, 255))
        screen.blit(text, (20, y_offset + i * line_height))


gt_player = Player(SCREEN_WIDTH // 2, GROUND_Y - 60)
player = Player(SCREEN_WIDTH // 2, GROUND_Y - 60)


def main():
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Movement Engine")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 24)

    tick_interval = 1.0 / TPS
    accumulator = 0.0
    tick_count = 0

    current_fps_cap = FPS

    tps_timer = 0.0
    tps_tick_count = 0
    actual_tps = TPS

    running = True
    last_time = pygame.time.get_ticks() / 1000.0

    while running:
        current_time = pygame.time.get_ticks() / 1000.0
        frame_time = current_time - last_time
        last_time = current_time

        if frame_time > 0.25:
            frame_time = 0.25

        accumulator += frame_time

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_c:
                    current_fps_cap = 60 if current_fps_cap == 5 else 5 if current_fps_cap == 60 else 60
        if GlobalKeys.pressed("space"):
            player.jump()

        while accumulator >= tick_interval:
            player.update(tick_interval)
            accumulator -= tick_interval
            tick_count += 1
            tps_tick_count += 1

        alpha = accumulator / tick_interval

        tps_timer += frame_time
        if tps_timer >= 1.0:
            actual_tps = tps_tick_count / tps_timer
            tps_tick_count = 0
            tps_timer = 0.0

        screen.fill((0, 0, 0))

        pygame.draw.line(screen, (200, 200, 200), (0, GROUND_Y), (SCREEN_WIDTH, GROUND_Y), 3)

        grid_spacing = 32
        for x in range(0, SCREEN_WIDTH, grid_spacing):
            pygame.draw.line(screen, (40, 40, 40), (x, 0), (x, SCREEN_HEIGHT), 1)
        for y in range(0, SCREEN_HEIGHT, grid_spacing):
            pygame.draw.line(screen, (40, 40, 40), (0, y), (SCREEN_WIDTH, y), 1)

        player.draw(screen, alpha)
        gt_player.color = (255, 100, 100)
        gt_player.draw(screen, alpha)

        draw_hud(screen, player, font, clock, tick_count, actual_tps)

        fps_text = f"FPS Cap: {'Uncapped' if current_fps_cap == 0 else current_fps_cap}"
        fps_render = font.render(fps_text, True, (0, 255, 255))
        screen.blit(fps_render, (SCREEN_WIDTH - 200, 20))

        pygame.display.flip()

        if current_fps_cap > 0:
            clock.tick(current_fps_cap)
        else:
            clock.tick()

    pygame.quit()
    sys.exit()


s = helper()


class MovementTest(Extension):
    def __init__(self) -> None:
        super().__init__(name="movement-test", interest=[Interest(interest=INTEREST_STATE_UPDATE)])
        self.origin = vec2(0, 0)
        self.pos = vec2(0, 0)
        self.offset = vec2(0, 0)

    @dispatch(
        Interest(
            interest=INTEREST_STATE,
            direction=DIRECTION_CLIENT_TO_SERVER,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
            id=s.auto,
        ),
    )
    def on_move(self, event: PendingPacket) -> PendingPacket | None:
        pkt = NetPacket.deserialize(event.buf)
        self.pos = vec2(pkt.tank.vector_x, pkt.tank.vector_x)
        gt_player.x = self.origin.x - pkt.tank.vector_x + self.offset.x
        gt_player.y = self.origin.y - pkt.tank.vector_y + self.offset.y

    @dispatch(s.command_toggle("/set", s.auto))
    def set_origin(self, _event: PendingPacket) -> PendingPacket | None:
        self.origin = self.pos
        self.offset = vec2(player.x, player.y)

        return self.cancel()

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    MovementTest().start(block=False)
    main()
