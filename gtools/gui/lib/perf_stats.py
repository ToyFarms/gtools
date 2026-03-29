from collections import defaultdict, deque
from dataclasses import dataclass, field

SHOW_DEBUG_OVERLAY: bool = False


@dataclass(slots=True)
class PerfStats:
    stats: defaultdict[str, deque[float]] = field(default_factory=lambda: defaultdict(lambda: deque(maxlen=200)))
    idle: bool = False
    idle_timer: float = 0.0

    def record_frame(self, **stats: float) -> None:
        for k, v in stats.items():
            self.stats[k].append(v)
