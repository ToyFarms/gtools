"""CyBot renderer -- robots and their projectiles for the world renderer.

A sub-renderer of :class:`gtools.gui.lib.world_renderer.WorldRenderer`
specialized for cybots: it owns a :class:`~gtools.core.growtopia.cybot.CyBotWorld`,
ticks it once per frame and draws each robot/projectile from ``game/npc1.rttex``
with the client's frame selection, flip and alpha (``docs/cybot.md`` §8):

- sprite centred on the simulated position (the client's ``tileToWorldCenter``),
- frame from the current command's direction and the 200/400 ms animation steps,
- horizontal mirroring per direction / facing,
- alpha 1.0 armed / 0.5 unarmed (client 255 / 128).

The viewer intentionally draws unactivated robots too (at half alpha); the client
only draws them for the tile's lock owner / build overrides.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from gtools import setting
from gtools.core.growtopia.cybot import SPRITE_SIZE, CyBotWorld, monotonic_ms
from gtools.core.growtopia.world import CybotTile, World
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib import layer
from gtools.gui.lib.renderer import Renderer
from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.gui.texture import GLTex, GLTexManager

SHEET = "game/npc1.rttex"
"""The client's robot sprite sheet (1024x1024, 32x32 frames)."""

_INSTANCE_DTYPE = np.dtype(
    [
        ("worldPos", np.float32, 2),  # sprite centre, renderer world px
        ("frameUV", np.float32, 2),  # frame top-left, normalized
        ("flip", np.float32, 1),  # -1 mirrored / +1 normal
        ("alpha", np.float32, 1),  # 1.0 armed / 0.5 unarmed
        ("angle", np.float32, 1),  # degrees (projectiles only)
    ]
)

WORLD_OFFSET = SPRITE_SIZE / 2
"""Client px -> renderer world px.

The GUI's world space centres tile ``(x, y)`` at ``(x * 32, y * 32)`` (see
``highlight_renderer``: ``tile * 32 - 16 + width / 2`` and the tile meshes that
place ``RECT_WITH_UV_VERTS`` at ``tile.pos * 32``). The client instead puts the
tile's centre at ``tile * 32 + 16`` (``tileToWorldCenter``), which is the space
the cybot simulation runs in -- so sprites are shifted by half a tile here.
"""


class CyBotRenderer(Renderer):
    """Draws every cybot of a world plus its projectiles."""

    def __init__(self) -> None:
        self.sim = CyBotWorld()
        self._world: World | None = None
        self._tex: GLTex | None = None
        self._mesh: Mesh | None = None

        self._tex_mgr = GLTexManager()

        self._shader = ShaderProgram.get("shaders/cybot")
        self._u_mvp = self._shader.get_uniform("u_mvp")
        self._u_texture = self._shader.get_uniform("u_texture")
        self._u_depth = self._shader.get_uniform("u_depth")
        self._u_sprite_size = self._shader.get_uniform("u_spriteSize")
        self._u_tex_layer = self._shader.get_uniform("u_texLayer")

        self._shader3d = ShaderProgram.from_files("shaders/cybot3d.vert", "shaders/cybot.frag")
        self._u_vp3d = self._shader3d.get_uniform("u_view_proj")
        self._u_texture3d = self._shader3d.get_uniform("u_texture")
        self._u_depth3d = self._shader3d.get_uniform("u_depth")
        self._u_spread3d = self._shader3d.get_uniform("u_layer_spread")
        self._u_sprite_size3d = self._shader3d.get_uniform("u_spriteSize")
        self._u_tex_layer3d = self._shader3d.get_uniform("u_texLayer")

    # -- lifecycle --------------------------------------------------------------------

    def load(self, world: World) -> None:
        """Bind to a world: load the sheet and register its robots."""
        self._world = world

        self._tex = self._tex_mgr.load_texture(setting.gt_path / SHEET)
        self._tex_mgr.flush()

        if self._mesh is None:
            self._mesh = Mesh(
                Mesh.RECT_WITH_UV_VERTS,
                [2, 2],
                Mesh.RECT_INDICES,
                instance_data=np.zeros(64, dtype=_INSTANCE_DTYPE),
                instance_layout=[2, 2, 1, 1, 1],
                instance_attrib_base=2,
                instance_capacity=64,
            )

        self.sim.clock = self.resume_clock(world)
        self.sim.load(world)

    @staticmethod
    def _anchors(world: World) -> list[int]:
        return [
            int(tile.extra.anchor_ms)
            for tile in world.tiles.values()
            if isinstance(tile.extra, CybotTile) and tile.extra.commands
        ]

    @staticmethod
    def resume_clock(world: World, now_fn: Callable[[], float] = monotonic_ms) -> Callable[[], float]:
        """A clock that resumes the world's saved cycle phases.

        The wire anchors are server-ms timestamps from an epoch this viewer does
        not share, so treating the newest anchor as "now" at load gives every
        robot the phase ``(newest_anchor - its_anchor) % cycle`` -- the phase the
        world was saved with -- and then advances in real time.
        """
        anchors = CyBotRenderer._anchors(world)
        offset = (max(anchors) if anchors else 0) - now_fn()
        return lambda: offset + now_fn()

    def sync_tiles(self, tiles: list[tuple[int, int]]) -> None:
        """Refresh robots for tile positions that changed."""
        if self._world is None:
            return
        for x, y in tiles:
            self.sim.sync_tile(self._world, x, y)

    def update(self) -> bool:
        """Advance the simulation by one frame (robots + projectiles).

        Returns ``True`` while anything is animating, so the host can keep the
        world view dirty (robots and shots move continuously).
        """
        if not self.sim.robots and not self.sim.projectiles:
            return False
        self.sim.tick()
        return True

    def delete(self) -> None:
        if self._mesh is not None:
            self._mesh.delete()
            self._mesh = None

    # -- drawing ----------------------------------------------------------------------

    @property
    def robot_count(self) -> int:
        return len(self.sim.robots)

    @property
    def projectile_count(self) -> int:
        return len(self.sim.projectiles)

    def draw(self, camera: Camera2D) -> None:
        self._draw(camera=camera)

    def draw_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        self._draw(camera3d=camera3d, layer_spread=layer_spread)

    def _draw(self, *, camera: Camera2D | None = None, camera3d: Camera3D | None = None, layer_spread: float = 1.0) -> None:
        if self._tex is None or self._mesh is None:
            return

        row_width = max(1, self._tex.width // SPRITE_SIZE)
        tex_size = (self._tex.width, self._tex.height)
        shader = self._shader if camera is not None else self._shader3d

        # two passes so projectiles land above the robots even at equal depth
        robot_data = self.robot_instances(self.sim, row_width=row_width, tex_size=tex_size)
        projectile_data = self.projectile_instances(self.sim, row_width=row_width, tex_size=tex_size)

        if len(robot_data) == 0 and len(projectile_data) == 0:
            self._mesh.set_instance_count(0)
            return

        shader.use()
        if camera is not None:
            self._u_mvp.set_mat4x4(camera.proj_as_numpy())
            self._u_sprite_size.set_float(float(SPRITE_SIZE))
            self._u_tex_layer.set_float(float(self._tex.layer))
            self._u_texture.set_int(0)
            depth_uniform = self._u_depth
        else:
            assert camera3d is not None
            self._u_vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
            self._u_spread3d.set_float(layer_spread)
            self._u_sprite_size3d.set_float(float(SPRITE_SIZE))
            self._u_tex_layer3d.set_float(float(self._tex.layer))
            self._u_texture3d.set_int(0)
            depth_uniform = self._u_depth3d

        self._tex.array.bind(unit=0)

        for data, depth in ((robot_data, layer.CYBOT), (projectile_data, layer.CYBOT_PROJECTILE)):
            if len(data) == 0:
                continue
            self._mesh.update_instance_data(data)
            self._mesh.set_instance_count(len(data))
            depth_uniform.set_float(depth)
            self._mesh.draw_instanced()

    # -- instance math (pure; tested headlessly) --------------------------------------

    @staticmethod
    def robot_instances(sim: CyBotWorld, *, row_width: int, tex_size: tuple[int, int], now_ms: int | None = None) -> np.ndarray:
        """Instance buffer for the robots at a simulation snapshot."""
        return _build_instances(
            [(s.frame, s.x, s.y, s.flip, s.alpha, 0.0) for s in sim.robot_sprites(now_ms)],
            row_width=row_width,
            tex_size=tex_size,
        )

    @staticmethod
    def projectile_instances(sim: CyBotWorld, *, row_width: int, tex_size: tuple[int, int], now_ms: int | None = None) -> np.ndarray:
        """Instance buffer for the projectiles at a simulation snapshot."""
        return _build_instances(
            [(p.frame, p.x, p.y, p.flip, 1.0, p.angle) for p in sim.projectile_sprites(now_ms)],
            row_width=row_width,
            tex_size=tex_size,
        )


def _build_instances(
    sprites: list[tuple[int, float, float, bool, float, float]],
    *,
    row_width: int,
    tex_size: tuple[int, int],
) -> np.ndarray:
    data = np.zeros(len(sprites), dtype=_INSTANCE_DTYPE)
    tex_w, tex_h = tex_size
    u_step = SPRITE_SIZE / tex_w
    v_step = SPRITE_SIZE / tex_h

    for i, (frame, x, y, flip, alpha, angle) in enumerate(sprites):
        col, row = frame % row_width, frame // row_width
        data[i]["worldPos"] = (x - WORLD_OFFSET, y - WORLD_OFFSET)
        data[i]["frameUV"] = (col * u_step, row * v_step)
        data[i]["flip"] = -1.0 if flip else 1.0
        data[i]["alpha"] = alpha
        data[i]["angle"] = angle

    return data
