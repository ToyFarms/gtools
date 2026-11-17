"""Blast renderer math (headless, no GL context).

The renderer draws only the particle trail -- ``renderNpc`` draws nothing for NPC
types 8 / 15 -- from two 512x512 sheets with 16x16 cells (``sub_1402CD700``
forces the particle surface frame size to 16, and the record's draw scale is 1.0
for 212/276). Two conventions are pinned here:

* particles are 16 px quads rotated to the blast heading;
* client world px are shifted by ``-16`` (half a tile) into the GUI's world
  space, which centres tile ``(x, y)`` at ``(x*32, y*32)``.
"""

import pytest
from pyglm.glm import vec2

from gtools.core.growtopia.blaster import BlastWorld, PARTICLE_SHEETS, PARTICLE_SPRITES
from gtools.core.growtopia.world import Npc, NpcType
from gtools.gui.lib.blaster_renderer import SPRITE_SIZE, WORLD_OFFSET, BlasterRenderer

SHEET_A = "game/particles.rttex"
SHEET_B = "game/particles2.rttex"
TEX_SIZE = (512, 512)
ROW_WIDTH = TEX_SIZE[0] // SPRITE_SIZE


class Clock:
    def __init__(self, ms: int = 0) -> None:
        self.ms = ms

    def __call__(self) -> float:
        return self.ms


def spawn_trail(npc_type: NpcType, *, angle: float = 0.0) -> BlastWorld:
    clock = Clock(0)
    sim = BlastWorld(clock)
    sim.add(
        Npc(
            type=npc_type,
            id=1,
            pos=vec2(0.0, 0.0),
            target_pos=vec2(0.0, 0.0),
            param2=0,
            param3=angle,
        )
    )
    sim.tick()  # prime the clock
    clock.ms = 100
    sim.tick()  # one trail particle
    assert len(sim.particles) == 1
    return sim


def instances(sim: BlastWorld, sheet: str):
    return BlasterRenderer.particle_instances(sim, sheet=sheet, row_width=ROW_WIDTH, tex_size=TEX_SIZE)


def test_particle_sheets_are_the_two_particle_textures() -> None:
    assert PARTICLE_SHEETS == (SHEET_A, SHEET_B)
    assert PARTICLE_SPRITES[212] == (SHEET_A, (0, 2))
    assert PARTICLE_SPRITES[276] == (SHEET_B, (8, 14))
    assert SPRITE_SIZE == 16
    assert WORLD_OFFSET == 16.0


def test_howler_particle_converts_to_renderer_space() -> None:
    sim = spawn_trail(NpcType.BLAST)

    data = instances(sim, SHEET_A)

    assert len(data) == 1
    assert data[0]["worldPos"][0] == pytest.approx(0.0 - WORLD_OFFSET)
    assert data[0]["worldPos"][1] == pytest.approx(0.0 - WORLD_OFFSET)
    # cell (0, 2) of a 32-column sheet
    assert data[0]["frameUV"][0] == pytest.approx(0.0)
    assert data[0]["frameUV"][1] == pytest.approx(2 * SPRITE_SIZE / TEX_SIZE[1])
    assert data[0]["angle"][0] == pytest.approx(0.0)


def test_trickster_particle_uses_its_own_sheet_and_cell() -> None:
    sim = spawn_trail(NpcType.TRICKSTER, angle=90.0)

    assert len(instances(sim, SHEET_A)) == 0  # nothing from the wrong sheet
    data = instances(sim, SHEET_B)

    assert len(data) == 1
    assert data[0]["frameUV"][0] == pytest.approx(8 * SPRITE_SIZE / TEX_SIZE[0])
    assert data[0]["frameUV"][1] == pytest.approx(14 * SPRITE_SIZE / TEX_SIZE[1])
    assert data[0]["angle"][0] == pytest.approx(90.0)
