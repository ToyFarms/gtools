"""Screen-corner cancel zones (pure logic, no GUI dependencies).

Each usable monitor corner is a quarter-disc. Letting go of the trigger while the
cursor sits inside one means "cancel". A zone only shows itself when the cursor
approaches (it grows as the cursor gets closer), and a zone the cursor was already
sitting in when the menu opened stays disarmed until the cursor leaves it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .intent import Spring, clamp


@dataclass
class CornerConfig:
    enabled: bool = True
    radius: float = 90.0   # px at scale 1.0: size of the cancel zone (quarter disc)
    reach: float = 2.6     # the indicator starts to appear at reach * radius from the corner
    rearm: float = 1.15    # a disarmed zone re-arms once the cursor is this * radius away


class CornerZones:
    """Corner order everywhere: top-left, top-right, bottom-right, bottom-left."""

    def __init__(self, cfg: Optional[CornerConfig] = None):
        self.cfg = cfg or CornerConfig()
        self.points: List[Tuple[int, int]] = [(0, 0)] * 4
        self.usable = [False] * 4
        self.armed = [False] * 4
        self.prox = [Spring(0.0, f=9.0, z=1.0) for _ in range(4)]   # indicator growth 0..1
        self.hot = [Spring(0.0, f=14.0, z=1.0) for _ in range(4)]   # cursor is inside 0..1
        self.hit: Optional[int] = None

    def set_monitor(self, x: int, y: int, w: int, h: int, usable: Sequence[bool]) -> None:
        self.points = [(x, y), (x + w - 1, y), (x + w - 1, y + h - 1), (x, y + h - 1)]
        self.usable = [bool(self.cfg.enabled and u) for u in usable]

    def reset(self, cursor, scale: float) -> None:
        """Call when the menu opens: corners the cursor is already in start disarmed."""
        r = self.cfg.radius * scale
        for i, (px, py) in enumerate(self.points):
            self.armed[i] = self.usable[i] and math.hypot(cursor[0] - px, cursor[1] - py) > r
            self.prox[i].snap(0.0)
            self.hot[i].snap(0.0)
        self.hit = None

    def update(self, cursor, dt: float, scale: float) -> Optional[int]:
        """Advance animation; returns the index of the corner zone the cursor is in."""
        cfg = self.cfg
        r = cfg.radius * scale
        span = max((cfg.reach - 1.0) * r, 1e-6)
        hit, best = None, float("inf")
        for i, (px, py) in enumerate(self.points):
            d = math.hypot(cursor[0] - px, cursor[1] - py)
            if self.usable[i] and not self.armed[i] and d > r * cfg.rearm:
                self.armed[i] = True
            on = self.armed[i]
            inside = on and d <= r
            self.prox[i].step(clamp((cfg.reach * r - d) / span) if on else 0.0, dt)
            self.hot[i].step(1.0 if inside else 0.0, dt)
            if inside and d < best:
                hit, best = i, d
        self.hit = hit
        return hit
