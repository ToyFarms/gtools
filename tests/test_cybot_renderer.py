"""CyBot renderer math (headless, no GL context).

``CyBotRenderer`` is a sub-renderer of the world renderer; the parts tested here
are the pure instance-buffer / clock helpers, so they run without an OpenGL
context (the shader + mesh creation is the only GL-bound part).

Two conventions matter and are pinned here:
* the GUI's world space centres tile ``(x, y)`` at ``(x*32, y*32)`` (see
  ``highlight_renderer``), while the client/simulation uses ``tile*32 + 16``
  (``tileToWorldCenter``) -- sprites are emitted shifted by ``-16``;
* robot sprites carry the frame/flip/alpha from the client draw
  (``cybotRender`` 0x1403EB420) while projectiles also carry their ``angle``
  (-90 up / +90 down, ``cybotProjectileRender`` 0x1403E9B00).
"""

from pyglm.glm import ivec2

from gtools.baked.items import (
    COMMAND_BASIC_SHOT_LEFT,
    COMMAND_BASIC_SHOT_UP,
    COMMAND_MOVE_LEFT,
    SHOCKBOT_LEVEL_1,
    SHOOTERBOT_LEVEL_1,
)
from gtools.core.growtopia.cybot import TILE, CyBotWorld
from gtools.core.growtopia.world import CyBotCommandData, CybotTile, Tile, World
from gtools.gui.lib.cybot_renderer import SPRITE_SIZE, WORLD_OFFSET, CyBotRenderer

ROW_WIDTH = 32
TEX_SIZE = (1024, 1024)


def make_world(robots: list[tuple[int, int, list[int], int]]) -> World:
    """``robots`` = [(tile_x, tile_y, commands, anchor_ms)] on a ShooterBot."""
    tiles = []
    for x, y, commands, anchor in robots:
        tile = Tile(fg_id=SHOOTERBOT_LEVEL_1, pos=ivec2(x, y))
        tile.extra = CybotTile(
            commands=[CyBotCommandData(item_id=command, enabled=1) for command in commands],
            anchor_ms=anchor,
            activated=1,
        )
        tiles.append(tile)
    return World.from_tiles(tiles)


def test_robot_instances_convert_to_renderer_space() -> None:
    world = make_world([(5, 5, [COMMAND_MOVE_LEFT], 0)])
    sim = CyBotWorld(lambda: 0)
    sim.load(world)

    data = CyBotRenderer.robot_instances(sim, row_width=ROW_WIDTH, tex_size=TEX_SIZE, now_ms=0)

    assert len(data) == 1
    robot = sim.robots[0]
    client_x = 5 * TILE + TILE / 2
    assert data[0]["worldPos"][0] == client_x - WORLD_OFFSET
    assert data[0]["worldPos"][1] == client_x - WORLD_OFFSET
    assert WORLD_OFFSET == SPRITE_SIZE / 2
    # idle robot at its tile centre, frame 0 of the ShooterBot block
    assert data[0]["frameUV"][0] == 0.0 and data[0]["frameUV"][1] == 0.0
    assert data[0]["flip"][0] == 1.0
    assert data[0]["alpha"][0] == 1.0
    assert data[0]["angle"][0] == 0.0


def test_robot_units_of_frame_flip_and_alpha() -> None:
    world = make_world([(2, 3, [COMMAND_BASIC_SHOT_LEFT], 0)])
    sim = CyBotWorld(lambda: 0)
    sim.load(world)

    data = CyBotRenderer.robot_instances(sim, row_width=ROW_WIDTH, tex_size=TEX_SIZE, now_ms=0)
    # left shot: the shared left/right frames (base 0 + idle 3), mirrored
    assert data[0]["frameUV"][0] == 3 * SPRITE_SIZE / TEX_SIZE[0]
    assert data[0]["flip"][0] == -1.0

    sim.robots[0].activated = 0  # unarmed -> the client draws at alpha 128/255
    data = CyBotRenderer.robot_instances(sim, row_width=ROW_WIDTH, tex_size=TEX_SIZE, now_ms=0)
    assert data[0]["alpha"][0] == 0.5


def test_projectile_instances_carry_angle_and_flip() -> None:
    world = make_world([(5, 5, [COMMAND_BASIC_SHOT_UP], 0)])
    sim = CyBotWorld(lambda: 0)
    sim.load(world)
    sim.tick(2401)  # the up shot fires at the end of its 2400 ms window

    assert len(sim.projectiles) == 1
    data = CyBotRenderer.projectile_instances(sim, row_width=ROW_WIDTH, tex_size=TEX_SIZE, now_ms=2401)

    shot = sim.projectiles[0]
    expected_uv = (shot.base_frame % ROW_WIDTH) * SPRITE_SIZE / TEX_SIZE[0]
    assert data[0]["frameUV"][0] == expected_uv
    assert data[0]["angle"][0] == -90.0  # up
    assert data[0]["flip"][0] == 1.0  # up/down shots are not mirrored
    assert data[0]["worldPos"][0] == shot.x - WORLD_OFFSET


def test_resume_clock_starts_at_the_newest_anchor() -> None:
    world = make_world(
        [
            (1, 1, [COMMAND_MOVE_LEFT], 100),
            (2, 2, [COMMAND_MOVE_LEFT], 300),
        ]
    )

    clock = CyBotRenderer.resume_clock(world, now_fn=lambda: 0.0)
    assert clock() == 300

    ticking = {"now": 0.0}
    clock = CyBotRenderer.resume_clock(world, now_fn=lambda: ticking["now"])
    ticking["now"] = 50.0
    assert clock() == 350  # newest anchor + elapsed since load

    assert sorted(CyBotRenderer._anchors(world)) == [100, 300]


def test_resume_clock_gives_each_robot_its_saved_phase() -> None:
    world = make_world(
        [
            (1, 1, [COMMAND_MOVE_LEFT], 100),
            (2, 2, [COMMAND_MOVE_LEFT], 300),
        ]
    )
    sim = CyBotWorld(CyBotRenderer.resume_clock(world, now_fn=lambda: 0.0))
    sim.load(world)

    first = sim.robot_at(1, 1)
    second = sim.robot_at(2, 2)
    assert first is not None and second is not None

    assert (first.cmd_start_ms, second.cmd_start_ms) == (100, 300)
    # the older robot is 200 ms into its cycle; both cycle over 2x500 ms
    assert first.cycle_duration_ms == second.cycle_duration_ms == 1000
    assert first.index == 0 and second.index == 0


def test_anchor_list_ignores_non_robot_tiles() -> None:
    plain = Tile(fg_id=2, pos=ivec2(4, 4))
    world = World.from_tiles([plain])

    assert CyBotRenderer._anchors(world) == []


def test_unarmed_robot_still_renderable() -> None:
    world = make_world([(5, 5, [COMMAND_MOVE_LEFT], 0)])
    sim = CyBotWorld(lambda: 0)
    sim.load(world)

    # the viewer draws every robot (the client gates on lock ownership); the
    # unarmed one is just half-transparent
    assert CyBotRenderer.robot_instances(sim, row_width=ROW_WIDTH, tex_size=TEX_SIZE, now_ms=0).shape[0] == 1
