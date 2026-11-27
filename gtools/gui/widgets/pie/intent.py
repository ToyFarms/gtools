import math
from dataclasses import dataclass
from typing import Sequence


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def smoothstep(t: float) -> float:
    t = clamp(t)
    return t * t * (3.0 - 2.0 * t)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def ang_diff(a: float, b: float) -> float:
    return abs((a - b + math.pi) % math.tau - math.pi)


class Spring:
    __slots__ = ("x", "v", "f", "z")

    def __init__(self, x: float = 0.0, f: float = 9.0, z: float = 0.8):
        self.x, self.v, self.f, self.z = x, 0.0, f, z

    def step(self, target: float, dt: float) -> float:
        dt = min(dt, 0.05)
        n = max(1, int(dt / 0.004) + 1)
        h = dt / n
        w = math.tau * self.f
        for _ in range(n):
            a = w * w * (target - self.x) - 2.0 * self.z * w * self.v
            self.v += a * h
            self.x += self.v * h
        return self.x

    def snap(self, x: float) -> None:
        self.x, self.v = x, 0.0


@dataclass
class IntentConfig:
    dead_zone: float = 26.0  # inside this radius: nothing selected
    dead_zone_exit: float = 0.6  # once selected, dead zone shrinks to this fraction
    lookahead: float = 0.09  # seconds of cursor velocity added to displacement
    lookahead_cap: float = 90.0  # max look-ahead contribution (px)
    tangential_weight: float = 0.35  # how much sideways velocity counts toward look-ahead
    velocity_smoothing: float = 18.0  # higher = snappier velocity estimate
    hysteresis: float = 0.24  # selected slot's sector widens by this fraction (sticky)
    push_ratio: float = 1.50  # reach this fraction of the ring radius -> enter submenu
    dwell_time: float = 0.85  # ...or dwell this long on a submenu item
    grace_dead_mult: float = 1.7  # dead zone multiplier right after a level change


@dataclass
class IntentState:
    index: int | None
    distance: float
    angle: float
    dwell: float
    speed: float
    dx: float
    dy: float


class IntentTracker:
    def __init__(self, cfg: IntentConfig | None = None) -> None:
        self.cfg = cfg or IntentConfig()
        self.reset((0.0, 0.0), (0.0, 0.0))

    def reset(self, origin, cursor, grace: float = 0.0) -> None:
        self.origin = (float(origin[0]), float(origin[1]))
        self._prev = (float(cursor[0]), float(cursor[1]))
        self.vx = self.vy = 0.0
        self.index: int | None = None
        self.dwell = 0.0
        self.grace = grace

    def update(self, cursor, dt: float, angles: Sequence[float], sector: float, scale: float = 1.0) -> IntentState:
        cfg = self.cfg
        dx, dy = cursor[0] - self.origin[0], cursor[1] - self.origin[1]
        dist = math.hypot(dx, dy)

        if dt > 1e-4:
            a = 1.0 - math.exp(-dt * cfg.velocity_smoothing)
            self.vx += ((cursor[0] - self._prev[0]) / dt - self.vx) * a
            self.vy += ((cursor[1] - self._prev[1]) / dt - self.vy) * a
        self._prev = (float(cursor[0]), float(cursor[1]))

        in_grace = self.grace > 0.0
        self.grace = max(0.0, self.grace - dt)
        dead = cfg.dead_zone * scale * (cfg.grace_dead_mult if in_grace else 1.0)

        lx = ly = 0.0
        if not in_grace:
            ramp = clamp(dist / (0.5 * dead))
            vx, vy = self.vx, self.vy
            if dist > 1e-6:
                ux, uy = dx / dist, dy / dist
                vr = vx * ux + vy * uy
                vx, vy = vr * ux + cfg.tangential_weight * (vx - vr * ux), vr * uy + cfg.tangential_weight * (vy - vr * uy)
            lx, ly = vx * cfg.lookahead * ramp, vy * cfg.lookahead * ramp
            cap = cfg.lookahead_cap * scale
            ll = math.hypot(lx, ly)
            if ll > cap:
                lx, ly = lx * cap / ll, ly * cap / ll
        wx, wy = dx + lx, dy + ly
        wlen = math.hypot(wx, wy)
        ang = math.atan2(wy, wx) if wlen > 1e-6 else 0.0

        thr = dead * (cfg.dead_zone_exit if self.index is not None else 1.0)
        new: int | None = None
        if wlen >= thr and angles:
            best = float("inf")
            for i, ai in enumerate(angles):
                d = ang_diff(ang, ai)
                if i == self.index:
                    d -= cfg.hysteresis * sector
                if d < best:
                    best, new = d, i

        if new != self.index:
            self.index, self.dwell = new, 0.0
        else:
            self.dwell += dt

        return IntentState(self.index, dist, ang, self.dwell, math.hypot(self.vx, self.vy), dx, dy)
