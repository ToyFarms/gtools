"""
Pygame visualizer for a sequence of character events (file-driven).

Usage:
    python pygame_sequence_visualizer.py [path_to_sequence_file]

If no path is provided the script will look for `sequence.txt` in the same folder.

File format (each line):
    <time> <STATE_FLAGS>, <x>, <y>
Example:
    2.8371810913085938e-05 STANDING, 1911.0, 514.0
    1.6325459480285645 FACING_LEFT|STANDING, 2184.0, 770.0
"""
import math
import re
import sys
import pygame
from pygame import Surface

# === Configuration ===
TILE_SZ = 32
CHAR_W, CHAR_H = 20, 30
MARGIN = 100
BG_COLOR = (30, 30, 30)
GRID_COLOR = (50, 50, 50)
HUD_COLOR = (230, 230, 230)
CHAR_COLOR = (120, 180, 240)  # single fixed color for the character
TRAIL_COLOR = (80, 140, 200)  # color for past trail
FUTURE_COLOR = (60, 100, 140)  # dimmer color for future path
TRAIL_WIDTH = 2
FUTURE_WIDTH = 1
FUTURE_LOOKAHEAD = 2.0  # seconds to look ahead
FPS = 60

# === Parse file ===
LINE_RE = re.compile(r"^\s*([0-9eE+\-\.]+)\s+([^,]+),\s*([0-9eE+\-\.]+),\s*([0-9eE+\-\.]+)\s*$")


def load_sequence_from_file(path):
    samples = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for ln_idx, line in enumerate(f, start=1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = LINE_RE.match(line)
                if not m:
                    print(f"Warning: couldn't parse line {ln_idx}: {line}")
                    continue
                t_s, state_s, x_s, y_s = m.groups()
                try:
                    t = float(t_s)
                    x = float(x_s)
                    y = float(y_s)
                except ValueError:
                    print(f"Warning: numeric parse failed on line {ln_idx}: {line}")
                    continue
                samples.append({"t": t, "state": state_s.strip(), "x": x, "y": y})
    except FileNotFoundError:
        print(f"Error: file not found: {path}")
        sys.exit(1)
    if not samples:
        print(f"Error: no valid samples found in {path}")
        sys.exit(1)
    # sort by time (just in case)
    samples.sort(key=lambda s: s["t"])
    return samples


def parse_flags(state_str: str):
    return set(s.strip().upper() for s in state_str.split("|") if s.strip())


# === Interpolation helpers ===
def find_segment_index(samples, t):
    if t <= samples[0]["t"]:
        return 0
    for i in range(len(samples) - 1):
        if samples[i]["t"] <= t <= samples[i + 1]["t"]:
            return i
    return len(samples) - 1


def lerp(a, b, u):
    return a + (b - a) * u


def get_state_at_time(samples, t, interpolate=True):
    if t <= samples[0]["t"]:
        s = samples[0]
        return s["x"], s["y"], parse_flags(s["state"])
    if t >= samples[-1]["t"]:
        s = samples[-1]
        return s["x"], s["y"], parse_flags(s["state"])
    i = find_segment_index(samples, t)
    s0 = samples[i]
    s1 = samples[i + 1]
    dt = s1["t"] - s0["t"]
    if dt == 0 or not interpolate:
        return s0["x"], s0["y"], parse_flags(s0["state"])
    u = (t - s0["t"]) / dt
    x = lerp(s0["x"], s1["x"], u)
    y = lerp(s0["y"], s1["y"], u)
    flags = parse_flags(s1["state"]) if u > 0.5 else parse_flags(s0["state"])
    return x, y, flags


def get_trail_points(samples, end_time, interpolate=True, step=0.05):
    """Generate list of (x, y) points for the trail up to end_time"""
    points = []
    t = samples[0]["t"]
    while t <= end_time:
        x, y, _ = get_state_at_time(samples, t, interpolate)
        points.append((x, y))
        t += step
    # Add the exact end point
    x, y, _ = get_state_at_time(samples, end_time, interpolate)
    points.append((x, y))
    return points


def get_future_points(samples, start_time, lookahead, interpolate=True, step=0.1):
    """Generate list of (x, y) points for future path"""
    points = []
    end_time = samples[-1]["t"]
    t = start_time + step
    while t <= min(start_time + lookahead, end_time):
        x, y, _ = get_state_at_time(samples, t, interpolate)
        points.append((x, y))
        t += step
    return points


# === Drawing helpers ===
def draw_grid(surf: Surface, tile_sz: int):
    w, h = surf.get_size()
    for x in range(0, w, tile_sz):
        pygame.draw.line(surf, GRID_COLOR, (x, 0), (x, h))
    for y in range(0, h, tile_sz):
        pygame.draw.line(surf, GRID_COLOR, (0, y), (w, y))


def draw_trail(surf: Surface, points, color, width):
    """Draw a trail through the given points"""
    if len(points) < 2:
        return
    # Convert to integer coordinates for drawing
    int_points = [(int(x), int(y)) for x, y in points]
    pygame.draw.lines(surf, color, False, int_points, width)


def draw_character(surf: Surface, x: float, y_bottom: float, flags: set, font):
    # Character bottom-centered at (x,y_bottom)
    top = y_bottom - CHAR_H
    left = x - CHAR_W / 2
    rect = pygame.Rect(int(left), int(top), CHAR_W, CHAR_H)
    # draw fixed-color character (no color for state)
    pygame.draw.rect(surf, CHAR_COLOR, rect)

    # draw facing indicator (triangle) kept as requested
    if "FACING_LEFT" in flags:
        pygame.draw.polygon(
            surf,
            (10, 10, 10),
            [
                (left, top + CHAR_H * 0.5),
                (left - 8, top + CHAR_H * 0.35),
                (left - 8, top + CHAR_H * 0.65),
            ],
        )
    else:
        pygame.draw.polygon(
            surf,
            (10, 10, 10),
            [
                (left + CHAR_W, top + CHAR_H * 0.5),
                (left + CHAR_W + 8, top + CHAR_H * 0.35),
                (left + CHAR_W + 8, top + CHAR_H * 0.65),
            ],
        )

    # small eye/dot for orientation
    eye_x = int(left + (CHAR_W * 0.25 if "FACING_LEFT" in flags else CHAR_W * 0.75))
    eye_y = int(top + CHAR_H * 0.35)
    pygame.draw.rect(surf, (10, 10, 10), (eye_x, eye_y, 4, 4))

    # draw state text above the character (explicit textual state)
    state_text = ",".join(sorted(flags)) if flags else "NONE"
    txt_surf = font.render(state_text, True, HUD_COLOR)
    txt_rect = txt_surf.get_rect(center=(x, top - 10))
    surf.blit(txt_surf, txt_rect)


# === Main ===
def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "sequence.txt"
    samples = load_sequence_from_file(path)

    for s in samples:
        s["state"] = s.get("state", "").strip()

    START_T = samples[0]["t"]
    END_T = samples[-1]["t"]

    # Compute world bounds
    min_x = min(s["x"] for s in samples)
    max_x = max(s["x"] for s in samples)
    min_y = min(s["y"] for s in samples)
    max_y = max(s["y"] for s in samples)

    world_w = int(math.ceil((max_x + MARGIN) / TILE_SZ) * TILE_SZ)
    world_h = int(math.ceil((max_y + MARGIN) / TILE_SZ) * TILE_SZ)
    WINDOW_W = max(world_w, 640)
    WINDOW_H = max(world_h, 480)

    pygame.init()
    screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
    pygame.display.set_caption("Sequence Visualizer (file)")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, 20)

    playing = True
    interpolate = True
    play_speed = 1.0
    t_play = START_T

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    running = False
                elif ev.key == pygame.K_SPACE:
                    playing = not playing
                elif ev.key == pygame.K_RIGHT:
                    t_play = min(END_T, t_play + 0.1)
                    playing = False
                elif ev.key == pygame.K_LEFT:
                    t_play = max(START_T, t_play - 0.1)
                    playing = False
                elif ev.key == pygame.K_UP:
                    play_speed *= 1.25
                elif ev.key == pygame.K_DOWN:
                    play_speed /= 1.25
                elif ev.key == pygame.K_i:
                    interpolate = not interpolate
                elif ev.key == pygame.K_r:
                    t_play = START_T
                    playing = True
                    play_speed = 1.0

        if playing:
            t_play += dt * play_speed
            if t_play > END_T:
                t_play = END_T
                playing = False

        # Render
        screen.fill(BG_COLOR)
        draw_grid(screen, TILE_SZ)

        # Draw past trail
        trail_points = get_trail_points(samples, t_play, interpolate)
        draw_trail(screen, trail_points, TRAIL_COLOR, TRAIL_WIDTH)

        # Draw future path (dimmer)
        future_points = get_future_points(samples, t_play, FUTURE_LOOKAHEAD, interpolate)
        if future_points:
            # Add current position as start of future path
            x, y, flags = get_state_at_time(samples, t_play, interpolate)
            future_points_with_start = [(x, y)] + future_points
            draw_trail(screen, future_points_with_start, FUTURE_COLOR, FUTURE_WIDTH)

        # Draw character on top of trails
        x, y, flags = get_state_at_time(samples, t_play, interpolate)
        draw_character(screen, x, y, flags, font)

        # HUD
        hud_lines = [
            f"file: {path}",
            f"time: {t_play:.3f}s  / {END_T:.3f}s",
            f"state: {','.join(sorted(flags)) or 'NONE'}",
            f"speed: {play_speed:.2f}x  interpolate: {interpolate}",
            "Space: pause  Left/Right: seek  Up/Down: speed  I: toggle interpolation  R: restart",
        ]
        for i, ln in enumerate(hud_lines):
            surf = font.render(ln, True, HUD_COLOR)
            screen.blit(surf, (8, 8 + i * 20))

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
