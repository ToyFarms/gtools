"""Blast renderer -- the particle trail of the Howler / Trickster blasts.

A blast has no sprite of its own: ``renderNpc`` (0x1402B6950) draws nothing for
NPC types 8 / 15, so it is visible only through the particles ``updateNPC``
spawns along its flight (``docs/blaster.md``):

* Howler (type 8) -> particle 212, ``game/particles.rttex`` cell (0, 2);
* Trickster (type 15) -> particle 276, ``game/particles2.rttex`` cell (8, 14).

Both sheets are 512x512 with 16x16 cells (``sub_1402CD700`` forces the surface
frame size to 16) and the particle record's draw scale is 1.0 for both ids, so a
particle is a 16 px quad rotated to the blast heading.

The renderer owns the :class:`~gtools.core.growtopia.blaster.BlastWorld`
instance the same way :class:`CyBotRenderer` owns its simulation: it ticks it once
per frame and the host binds the same object to ``PlayerController.blasts`` so
the kill test runs during the avatar update.
"""

from __future__ import annotations

import numpy as np

from gtools import setting
from gtools.core.growtopia.blaster import PARTICLE_SHEETS, PARTICLE_SPRITES, BlastWorld
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib import layer
from gtools.gui.lib.renderer import Renderer
from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.gui.texture import GLTex, GLTexManager

SPRITE_SIZE = 16
"""Particle cell size in px (``sub_1402CD700`` forces 16x16, scale 1.0)."""

WORLD_OFFSET = 16.0
"""Client px -> renderer world px.

NPC positions are client world pixels, where a tile's centre is ``tile * 32 + 16``
(``tileToWorldCenter``). The GUI's world space centres tile ``(x, y)`` at
``(x * 32, y * 32)``, so sprites shift left/up by half a tile -- the same
translation :class:`CyBotRenderer` applies.
"""

_INSTANCE_DTYPE = np.dtype(
    [
        ("worldPos", np.float32, 2),  # particle centre, renderer world px
        ("frameUV", np.float32, 2),  # cell top-left, normalized
        ("angle", np.float32, 1),  # degrees (the blast heading)
    ]
)


class BlasterRenderer(Renderer):
    """Draws the particle trail of every blast in flight."""

    def __init__(self) -> None:
        self.sim = BlastWorld()
        self._sheets: dict[str, GLTex] = {}
        self._mesh: Mesh | None = None

        self._tex_mgr = GLTexManager()

        self._shader = ShaderProgram.get("shaders/blaster")
        self._u_mvp = self._shader.get_uniform("u_mvp")
        self._u_texture = self._shader.get_uniform("u_texture")
        self._u_depth = self._shader.get_uniform("u_depth")
        self._u_sprite_size = self._shader.get_uniform("u_spriteSize")
        self._u_tex_layer = self._shader.get_uniform("u_texLayer")

        self._shader3d = ShaderProgram.from_files("shaders/blaster3d.vert", "shaders/blaster.frag")
        self._u_vp3d = self._shader3d.get_uniform("u_view_proj")
        self._u_texture3d = self._shader3d.get_uniform("u_texture")
        self._u_depth3d = self._shader3d.get_uniform("u_depth")
        self._u_spread3d = self._shader3d.get_uniform("u_layer_spread")
        self._u_sprite_size3d = self._shader3d.get_uniform("u_spriteSize")
        self._u_tex_layer3d = self._shader3d.get_uniform("u_texLayer")

    # -- lifecycle --------------------------------------------------------------------

    def load(self) -> None:
        """Stage both particle sheets and the shared quad mesh."""
        for sheet in PARTICLE_SHEETS:
            if sheet not in self._sheets:
                self._sheets[sheet] = self._tex_mgr.load_texture(setting.gt_path / sheet)
        self._tex_mgr.flush()

        if self._mesh is None:
            self._mesh = Mesh(
                Mesh.RECT_WITH_UV_VERTS,
                [2, 2],
                Mesh.RECT_INDICES,
                instance_data=np.zeros(256, dtype=_INSTANCE_DTYPE),
                instance_layout=[2, 2, 1],
                instance_attrib_base=2,
                instance_capacity=256,
            )

    def update(self) -> bool:
        """Tick the simulation; ``True`` while anything is animating."""
        if not self.sim.blasts and not self.sim.particles:
            return False
        self.sim.tick()
        return True

    def delete(self) -> None:
        if self._mesh is not None:
            self._mesh.delete()
            self._mesh = None

    # -- drawing ----------------------------------------------------------------------

    @property
    def particle_count(self) -> int:
        return len(self.sim.particles)

    def draw(self, camera: Camera2D) -> None:
        self._draw(camera=camera)

    def draw_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        self._draw(camera3d=camera3d, layer_spread=layer_spread)

    def _draw(self, *, camera: Camera2D | None = None, camera3d: Camera3D | None = None, layer_spread: float = 1.0) -> None:
        if self._mesh is None or not self._sheets:
            return

        shader = self._shader if camera is not None else self._shader3d
        shader.use()

        if camera is not None:
            self._u_mvp.set_mat4x4(camera.proj_as_numpy())
            self._u_sprite_size.set_float(float(SPRITE_SIZE))
            self._u_texture.set_int(0)
            depth_uniform = self._u_depth
        else:
            assert camera3d is not None
            self._u_vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
            self._u_spread3d.set_float(layer_spread)
            self._u_sprite_size3d.set_float(float(SPRITE_SIZE))
            self._u_texture3d.set_int(0)
            depth_uniform = self._u_depth3d

        layer_uniform = self._u_tex_layer if camera is not None else self._u_tex_layer3d
        drawn = False

        for sheet, tex in self._sheets.items():
            tex_size = (tex.width, tex.height)
            row_width = max(1, tex.width // SPRITE_SIZE)
            data = self.particle_instances(
                self.sim,
                sheet=sheet,
                row_width=row_width,
                tex_size=tex_size,
            )
            if len(data) == 0:
                continue

            tex.array.bind(unit=0)
            layer_uniform.set_float(float(tex.layer))
            depth_uniform.set_float(layer.BLAST)

            self._mesh.update_instance_data(data)
            self._mesh.set_instance_count(len(data))
            self._mesh.draw_instanced()
            drawn = True

        if not drawn:
            self._mesh.set_instance_count(0)

    # -- instance math (pure; tested headlessly) --------------------------------------

    @staticmethod
    def particle_instances(
        sim: BlastWorld,
        *,
        sheet: str,
        row_width: int,
        tex_size: tuple[int, int],
    ) -> np.ndarray:
        """Instance buffer for the particles drawn from ``sheet``."""
        tex_w, tex_h = tex_size
        u_step = SPRITE_SIZE / tex_w
        v_step = SPRITE_SIZE / tex_h

        sprites = [
            p
            for p in sim.particle_sprites()
            if PARTICLE_SPRITES.get(p.particle_id, (None, (0, 0)))[0] == sheet
        ]
        data = np.zeros(len(sprites), dtype=_INSTANCE_DTYPE)

        for i, particle in enumerate(sprites):
            cell_x, cell_y = PARTICLE_SPRITES[particle.particle_id][1]
            data[i]["worldPos"] = (particle.x - WORLD_OFFSET, particle.y - WORLD_OFFSET)
            data[i]["frameUV"] = (cell_x * u_step, cell_y * v_step)
            data[i]["angle"] = particle.angle

        return data
