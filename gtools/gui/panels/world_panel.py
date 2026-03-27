import itertools
import logging
from pathlib import Path

from imgui_bundle import imgui, imgui_knobs  # pyright: ignore[reportMissingModuleSource]

from gtools.core.growtopia.packet import NetPacket
from gtools.core.growtopia.world import World
from gtools.gui.event import Event
from gtools.gui.lib.tile_renderer import TileRenderer
from gtools.gui.lib.world_renderer import WorldRenderer
from gtools.gui.panels.panel import Panel

logger = logging.getLogger("gui-world-panel")


class WorldPanel(Panel):
    _UNIQUE = itertools.count()

    def __init__(self, world: World, dockspace_id: int) -> None:
        super().__init__()
        self._world = world
        self._name = f"{world.name.decode()}##{next(WorldPanel._UNIQUE)}"

        self._dockspace_id = dockspace_id
        self._open = True
        self._first_render = True

        self._world_renderer = WorldRenderer(world)

    @classmethod
    def load(cls, file: Path | str, dockspace_id: int) -> "WorldPanel":
        pkt = NetPacket.deserialize(Path(file).read_bytes())
        world = World.from_tank(pkt.tank)

        return cls(world, dockspace_id)

    def delete(self) -> None:
        logger.info(f"deleting panel {self._name}")
        self._world_renderer.delete()

    @property
    def is_open(self) -> bool:
        return bool(self._open)

    @property
    def is_dirty(self) -> bool:
        return self._world_renderer.is_dirty

    def update(self, dt: float) -> None:
        self._world_renderer.update(dt)

    def render_control(self) -> None:
        total_w, _ = imgui.get_content_region_avail()
        sidebar_w = min(250, max(80, int(total_w * 0.2)))
        imgui.begin_child("##controls", (sidebar_w, 0), child_flags=imgui.ChildFlags_.borders)

        hovered = self._world_renderer.hovered_tile
        if hovered:
            if hovered.extra:
                imgui.text_wrapped(f"{hovered.extra}")
            else:
                imgui.text("-")
        else:
            imgui.text("-")

        imgui.separator()

        sheet = self._world_renderer.sheet
        _, sheet.bpm = imgui_knobs.knob("BPM", sheet.bpm, 20.0, 200.0, format="%.0f", size=32, variant=imgui_knobs.ImGuiKnobVariant_.wiper_only)
        imgui.same_line()
        _, self._world_renderer.mixer.master_gain = imgui_knobs.knob(
            "GAIN", self._world_renderer.mixer.master_gain, 0.0, 1.0, format="%.2f", size=32, variant=imgui_knobs.ImGuiKnobVariant_.wiper_only
        )

        imgui.separator()

        _, playing = imgui.checkbox("Play", self._world_renderer.playing)
        self._world_renderer.playing = playing

        imgui.separator()

        FLAGS: list[tuple[str, TileRenderer.Flags]] = [
            ("FG", TileRenderer.Flags.RENDER_FG),
            ("BG", TileRenderer.Flags.RENDER_BG),
        ]
        for label, flag in FLAGS:
            flags = self._world_renderer.tile_flags
            changed, is_set = imgui.checkbox(label, flags & flag != 0)
            if changed:
                if is_set:
                    flags |= flag
                else:
                    flags &= ~flag
                self._world_renderer.tile_flags = flags

        imgui.separator()

        _, mode_3d = imgui.checkbox("3D", self._world_renderer.mode_3d)
        self._world_renderer.mode_3d = mode_3d

        if self._world_renderer.mode_3d:
            imgui.set_next_item_width(sidebar_w - 16)
            changed, spread = imgui.slider_float("##spread", self._world_renderer.layer_spread, 10.0, 1000.0)
            if changed:
                self._world_renderer.layer_spread = spread
            imgui.text("Spread")
            imgui.text(f"Spd: {self._world_renderer.camera3d_speed:.0f}")

        imgui.separator()

        _, wireframe = imgui.checkbox("Wireframe", self._world_renderer.wireframe)
        self._world_renderer.wireframe = wireframe

        imgui.separator()

        imgui.set_next_item_width(sidebar_w - 16)
        changed, debug_zoom = imgui.slider_float("##debug_zoom", self._world_renderer.culling_debug_zoom, 1.0, 10.0)
        if changed:
            self._world_renderer.culling_debug_zoom = debug_zoom
        imgui.text("Culling Debug")

        imgui.end_child()

    def render(self, control: bool = True) -> None:
        if self._first_render and self._dockspace_id:
            imgui.set_next_window_dock_id(self._dockspace_id)

        opened, self._open = imgui.begin(self._name, self._open)
        if self._first_render:
            imgui.set_window_focus()
            self._first_render = False

        self._world_renderer.set_active(imgui.is_window_focused(imgui.FocusedFlags_.child_windows))

        if opened:
            if control:
                self.render_control()
                imgui.same_line()

            self._world_renderer.render()
        imgui.end()

    def handle_event(self, event: Event) -> bool:
        return self._world_renderer.handle_event(event)
