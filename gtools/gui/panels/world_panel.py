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

    def __init__(self, dockspace_id: int, path: Path) -> None:
        super().__init__()
        pkt = NetPacket.deserialize(path.read_bytes())
        world = World.from_tank(pkt.tank)
        self._name = f"{world.name.decode()}##{next(WorldPanel._UNIQUE)}"

        self._dockspace_id = dockspace_id
        self._open = True
        self._first_render = True

        self._viewer = WorldRenderer(world)

    def delete(self) -> None:
        logger.info(f"deleting panel {self._name}")
        self._viewer.delete()

    @property
    def is_open(self) -> bool:
        return bool(self._open)

    @property
    def is_dirty(self) -> bool:
        return self._viewer.is_dirty

    def update(self, dt: float) -> None:
        self._viewer.update(dt)

    def render_control(self) -> None:
        total_w, _ = imgui.get_content_region_avail()
        sidebar_w = min(250, max(80, int(total_w * 0.2)))
        imgui.begin_child("##controls", (sidebar_w, 0), child_flags=imgui.ChildFlags_.borders)

        hovered = self._viewer.hovered_tile
        if hovered:
            if hovered.extra:
                imgui.text_wrapped(f"{hovered.extra}")
            else:
                imgui.text("-")
        else:
            imgui.text("-")

        imgui.separator()

        sheet = self._viewer.sheet
        _, sheet.bpm = imgui_knobs.knob("BPM", sheet.bpm, 20.0, 200.0, format="%.0f", size=32, variant=imgui_knobs.ImGuiKnobVariant_.wiper_only)
        imgui.same_line()
        _, self._viewer.mixer.master_gain = imgui_knobs.knob("GAIN", self._viewer.mixer.master_gain, 0.0, 1.0, format="%.2f", size=32, variant=imgui_knobs.ImGuiKnobVariant_.wiper_only)

        imgui.separator()

        _, playing = imgui.checkbox("Play", self._viewer.playing)
        self._viewer.playing = playing

        imgui.separator()

        FLAGS: list[tuple[str, TileRenderer.Flags]] = [
            ("FG", TileRenderer.Flags.RENDER_FG),
            ("BG", TileRenderer.Flags.RENDER_BG),
        ]
        for label, flag in FLAGS:
            flags = self._viewer.tile_flags
            changed, is_set = imgui.checkbox(label, flags & flag != 0)
            if changed:
                if is_set:
                    flags |= flag
                else:
                    flags &= ~flag
                self._viewer.tile_flags = flags

        imgui.separator()

        _, mode_3d = imgui.checkbox("3D", self._viewer.mode_3d)
        self._viewer.mode_3d = mode_3d

        if self._viewer.mode_3d:
            imgui.set_next_item_width(sidebar_w - 16)
            changed, spread = imgui.slider_float("##spread", self._viewer.layer_spread, 10.0, 1000.0)
            if changed:
                self._viewer.layer_spread = spread
            imgui.text("Spread")
            imgui.text(f"Spd: {self._viewer.camera3d_speed:.0f}")

        imgui.separator()

        _, wireframe = imgui.checkbox("Wireframe", self._viewer.wireframe)
        self._viewer.wireframe = wireframe

        imgui.end_child()

    def render(self, control: bool = True) -> None:
        if self._first_render and self._dockspace_id:
            imgui.set_next_window_dock_id(self._dockspace_id)

        opened, self._open = imgui.begin(self._name, self._open)
        if self._first_render:
            imgui.set_window_focus()
            self._first_render = False

        self._viewer.set_active(imgui.is_window_focused(imgui.FocusedFlags_.child_windows))

        if opened:
            if control:
                self.render_control()
                imgui.same_line()

            self._viewer.render()
        imgui.end()

    def handle_event(self, event: Event) -> bool:
        return self._viewer.handle_event(event)
