import itertools
import logging
from pathlib import Path

from imgui_bundle import imgui

from gtools.core.growtopia.packet import NetPacket
from gtools.core.growtopia.world import World
from gtools.gui.event import Event
from gtools.gui.lib.world_renderer import WorldRenderer
from gtools.gui.panels.panel import Panel

logger = logging.getLogger("gui-world-panel")


class WorldPanel(Panel):
    _UNIQUE = itertools.count()

    def __init__(self, world: World, dock_id: int) -> None:
        super().__init__(dock_id)
        self._world = world
        self._name = f"{world.name.decode()}##{next(WorldPanel._UNIQUE)}"
        self._open = True
        self._is_docked = False
        self._first_render = True

        self._world_renderer = WorldRenderer(world)

    @classmethod
    def load(cls, file: Path | str, dock_id: int) -> "WorldPanel":
        pkt = NetPacket.deserialize(Path(file).read_bytes())
        world = World.from_tank(pkt.tank)

        return cls(world, dock_id)

    def delete(self) -> None:
        logger.info(f"deleting panel {self._name}")
        self._world_renderer.delete()

    @property
    def is_open(self) -> bool:
        return bool(self._open)

    @property
    def is_dirty(self) -> bool:
        return self._world_renderer.is_dirty

    def get_perf(self, out: dict[str, float]) -> None:
        return self._world_renderer.get_perf(out)

    def update(self, dt: float) -> None:
        self._world_renderer.update(dt)

    def render(self) -> None:
        if not self._is_docked and self.dock_id:
            imgui.set_next_window_dock_id(self.dock_id)

        opened, self._open = imgui.begin(self._name, self._open)
        if not self._is_docked and imgui.is_window_docked():
            self._is_docked = True

        if self._first_render:
            imgui.set_window_focus()
            self._first_render = False

        self._world_renderer.set_active(imgui.is_window_focused(imgui.FocusedFlags_.child_windows))

        if opened:
            self._world_renderer.render()
        imgui.end()

    def handle_event(self, event: Event) -> bool:
        return self._world_renderer.handle_event(event)
