"""The render command system's scene contract (headless, no textures loaded).

Both backends consume these builders -- ``world_renderer_cpu`` rasterizes them,
the GUI translates them into GL instances (``gtests.gui.lib.sprite_batch``).
These tests pin what a world scene *is*: layers, positions, texture cells,
tints, sizes and the shadow flag, in client world space (tile top-left =
``x * 32``, sprite ``pixel_pos`` = top-left corner).
"""

from pyglm import glm
from pyglm.glm import ivec2

from gtools.baked.items import DIRT, DIRT_SEED, GEMS, VENDING_MACHINE
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.render_commands import (
    LAYER_ORDER,
    LAYER_RANK,
    RenderCommand,
    RenderLayer,
    RenderOptions,
    TextCommand,
    TileConnectionState,
    build_dropped_item_commands,
    build_tile_commands,
    build_tile_object_commands,
    build_world_commands,
)
from gtools.core.growtopia.world import (
    DisplayBlockTile,
    DroppedItem,
    SeedTile,
    ShelfTile,
    Tile,
    TileFlags,
    VendingMachineTile,
    World,
)

AMOUNT_FONT = "resources/fonts/centurygothic_bold.ttf"


def make_world(tiles: list[Tile]) -> World:
    return World.from_tiles(tiles)


def floor_tiles(n: int = 4) -> list[Tile]:
    return [Tile(fg_id=DIRT, pos=ivec2(x, 1), bg_id=DIRT) for x in range(n)]


def sprites(commands: list) -> list[RenderCommand]:
    return [cmd for cmd in commands if isinstance(cmd, RenderCommand)]


def texts(commands: list) -> list[TextCommand]:
    return [cmd for cmd in commands if isinstance(cmd, TextCommand)]


def test_layer_order_ranks_back_to_front() -> None:
    ranks = [LAYER_RANK[layer] for layer in LAYER_ORDER]
    assert ranks == sorted(ranks)
    assert LAYER_ORDER[0] == RenderLayer.BG
    assert LAYER_ORDER[-1] == RenderLayer.WATER


def test_floor_tile_emits_bg_and_fg() -> None:
    tile = Tile(fg_id=DIRT, pos=ivec2(3, 1), bg_id=DIRT)
    commands: list = []
    build_tile_commands(tile, commands=commands)

    assert [cmd.layer for cmd in commands] == [RenderLayer.BG, RenderLayer.FG]
    for cmd in commands:
        assert isinstance(cmd, RenderCommand)
        assert cmd.tile_pos == tile.pos
        assert cmd.texture_file == item_database.get(DIRT).texture_file.decode()
        assert cmd.sprite_size == 32
        assert cmd.sample_size == 32
        assert cmd.paint_index == tile.get_paint_index()
        assert cmd.pixel_pos is None  # tile-anchored, resolved against the origin
        assert cmd.shadow is False

    fg_tex_pos, fg_flipped = tile.tex_pos(DIRT, tile.fg_tex_index)
    assert commands[1].tex_pos == fg_tex_pos
    assert commands[1].is_flipped == fg_flipped


def test_connection_state_overrides_the_tex_indices() -> None:
    tile = Tile(fg_id=DIRT, pos=ivec2(0, 0), bg_id=DIRT)
    connection = TileConnectionState(fg=3, bg=2, overlay=1)

    commands: list = []
    build_tile_commands(tile, connection=connection, commands=commands)

    expected_fg, _ = tile.tex_pos(DIRT, 3)
    expected_bg, _ = tile.tex_pos(DIRT, 2)
    assert commands[0].tex_pos == expected_bg
    assert commands[1].tex_pos == expected_fg


def test_seed_tile_emits_the_base_overlay_pair() -> None:
    item = item_database.get(DIRT_SEED)
    tile = Tile(fg_id=DIRT_SEED, pos=ivec2(2, 3))
    tile.extra = SeedTile()

    commands: list = []
    build_tile_commands(tile, commands=commands)

    assert len(commands) == 2
    base, overlay = commands
    assert base.texture_file == "tiles_page1.rttex"
    assert base.tex_pos == ivec2(item.seed_base.value % 8, 19)
    assert base.get_tint().tolist() == [item.seed_color.r, item.seed_color.g, item.seed_color.b, 255]
    assert overlay.texture_file == "tiles_page1.rttex"
    assert overlay.tex_pos == ivec2(item.seed_overlay.value % 8, 18)
    assert overlay.get_tint().tolist() == [item.seed_overlay_color.r, item.seed_overlay_color.g, item.seed_overlay_color.b, 255]


def test_tree_fruit_icons_per_planted_seed() -> None:
    tile = Tile(fg_id=DIRT_SEED, pos=ivec2(2, 3))
    tile.extra = SeedTile(item_on_tree=3)

    commands: list = []
    build_tile_object_commands(tile, commands=commands)

    assert len(commands) == 3
    offsets = [(8, 5), (18, 5), (2, 14)]
    for cmd, offset in zip(sprites(commands), offsets):
        assert cmd.layer == RenderLayer.OBJ_POST
        assert cmd.item_id == DIRT  # the seed's fruit is the item itself
        assert cmd.pixel_pos == (2 * 32 + offset[0], 3 * 32 + offset[1])
        assert cmd.sprite_size == 8  # icon_scale 0.25
        assert cmd.shadow is False


def test_vending_machine_stocked_and_empty() -> None:
    item = item_database.get(VENDING_MACHINE)

    stocked = Tile(fg_id=VENDING_MACHINE, pos=ivec2(4, 5))
    stocked.extra = VendingMachineTile(item_id=DIRT, price=10)
    commands: list = []
    build_tile_commands(stocked, commands=commands)
    build_tile_object_commands(stocked, commands=commands)

    main = sprites(commands)
    assert main[0].layer == RenderLayer.FG
    assert main[0].tex_pos == ivec2(item.tex_coord_x, item.tex_coord_y)
    content = [cmd for cmd in main if cmd.layer == RenderLayer.OBJ_POST]
    assert len(content) == 1
    assert content[0].pixel_pos == (4 * 32 + 6, 5 * 32 + 5)
    assert content[0].sprite_size == 16  # icon_scale 0.5
    assert content[0].item_id == DIRT

    empty = Tile(fg_id=VENDING_MACHINE, pos=ivec2(4, 5))
    empty.extra = VendingMachineTile(item_id=0, price=0)
    commands: list = []
    build_tile_commands(empty, commands=commands)
    assert len(commands) == 2
    assert commands[0].tex_pos == ivec2(item.tex_coord_x + 1, item.tex_coord_y)  # "empty" frame
    assert commands[0].layer == RenderLayer.FG
    assert commands[1].tex_pos == ivec2(item.tex_coord_x + 2, item.tex_coord_y)  # warning sign
    assert commands[1].layer == RenderLayer.FG_AFTER


def test_vending_machine_alt_mode_overlays_the_wl_frame() -> None:
    item = item_database.get(VENDING_MACHINE)
    tile = Tile(fg_id=VENDING_MACHINE, pos=ivec2(0, 0))
    tile.flags |= TileFlags.FG_ALT_MODE
    tile.extra = VendingMachineTile(item_id=0, price=0)

    commands: list = []
    build_tile_commands(tile, commands=commands)

    after = [cmd for cmd in sprites(commands) if cmd.layer == RenderLayer.FG_AFTER]
    assert [cmd.tex_pos.x for cmd in after] == [item.tex_coord_x + 3, item.tex_coord_x + 2]


def test_display_block_draws_the_block_before_and_the_item_on_top() -> None:
    tile = Tile(fg_id=VENDING_MACHINE, pos=ivec2(5, 5))
    tile.extra = DisplayBlockTile(item_id=DIRT)

    commands: list = []
    build_tile_commands(tile, commands=commands)
    build_tile_object_commands(tile, commands=commands)

    item = item_database.get(VENDING_MACHINE)
    before = sprites(commands)[0]
    assert before.layer == RenderLayer.FG_BEFORE
    assert before.tex_pos == ivec2(item.tex_coord_x, item.tex_coord_y + 1)

    icon = [cmd for cmd in sprites(commands) if cmd.layer == RenderLayer.OBJ_PRE]
    assert len(icon) == 1
    assert icon[0].item_id == DIRT
    assert icon[0].pixel_pos == (5 * 32, 5 * 32)
    assert icon[0].sprite_size == 32


def test_shelf_icons_in_the_four_corners() -> None:
    tile = Tile(fg_id=VENDING_MACHINE, pos=ivec2(0, 0))
    tile.extra = ShelfTile(top_left_item_id=DIRT, bottom_right_item_id=DIRT)

    commands: list = []
    build_tile_object_commands(tile, commands=commands)

    assert [cmd.pixel_pos for cmd in sprites(commands)] == [(3, 0), (15, 15)]
    assert all(cmd.sprite_size == 9 for cmd in sprites(commands))  # icon_scale 0.3


def test_dropped_item_icon_overlay_and_amount_text() -> None:
    dropped = DroppedItem(pos=glm.vec2(3 * 32, 4 * 32), id=DIRT, amount=3)

    commands: list = []
    build_dropped_item_commands(dropped, commands=commands)

    icon, overlay = sprites(commands)
    assert icon.layer == RenderLayer.OBJ_POST
    assert icon.texture_file == item_database.get(DIRT).get_icon_texture() or icon.texture_file == item_database.get(DIRT).texture_file.decode()
    assert icon.pixel_pos == (3 * 32 + 2, 4 * 32 + 2)
    assert icon.sprite_size == 16  # icon_scale 0.5
    assert icon.shadow is True

    assert overlay.texture_file == "pickup_box.rttex"
    assert overlay.tex_pos == ivec2(0, 0)  # PICKUP_BOX_BLUE for a tradeable block
    assert overlay.pixel_pos == (3 * 32, 4 * 32)
    assert overlay.sprite_size == 20
    assert overlay.sample_size == 20
    assert overlay.shadow is True

    shadow, white = texts(commands)
    assert shadow.layer == RenderLayer.OBJ_POST
    assert shadow.text == "3" and white.text == "3"
    assert shadow.color == (0, 0, 0, 150) and white.color == (255, 255, 255, 255)
    assert shadow.offset == (1, 1) and white.offset == (0, 0)
    assert shadow.font == AMOUNT_FONT == white.font
    assert shadow.size == white.size


def test_dropped_gems_scale_the_tex_cell_and_skip_overlay_and_text() -> None:
    dropped = DroppedItem(pos=glm.vec2(0, 0), id=GEMS, amount=50)

    commands: list = []
    build_dropped_item_commands(dropped, commands=commands)

    assert len(sprites(commands)) == 1
    gem = sprites(commands)[0]
    assert gem.tex_pos == ivec2(item_database.get(GEMS).tex_coord_x + 3, item_database.get(GEMS).tex_coord_y)  # amount 50 cell (stride 5)
    assert gem.shadow is True
    assert texts(commands) == []


def test_dropped_seed_pair_has_no_shadow() -> None:
    item = item_database.get(DIRT_SEED)
    dropped = DroppedItem(pos=glm.vec2(32, 32), id=DIRT_SEED, amount=2)

    commands: list = []
    build_dropped_item_commands(dropped, commands=commands)

    base, overlay = sprites(commands)
    assert base.texture_file == "seed.rttex"
    assert base.tex_pos == ivec2(item.seed_base.value, 0)
    assert base.pixel_pos == (32, 32)
    assert base.sprite_size == 16
    assert base.shadow is False
    assert overlay.tex_pos == ivec2(item.seed_overlay.value, 1)
    assert overlay.shadow is False
    assert len(texts(commands)) == 2


def test_fire_and_water_overlays_carry_the_layer_opacity() -> None:
    tile = Tile(fg_id=DIRT, pos=ivec2(1, 1))
    tile.flags |= TileFlags.ON_FIRE

    commands: list = []
    build_tile_commands(tile, commands=commands)
    fire = commands[-1]
    assert fire.layer == RenderLayer.FIRE
    assert fire.texture_file == "fire.rttex"
    assert fire.opacity == 0.6

    tile.flags &= ~TileFlags.ON_FIRE
    tile.flags |= TileFlags.IS_WET
    commands = []
    build_tile_commands(tile, commands=commands)
    water = commands[-1]
    assert water.layer == RenderLayer.WATER
    assert water.texture_file == "water.rttex"
    assert water.opacity == 0.6


def test_render_options_gate_the_overlays_and_objects() -> None:
    tile = Tile(fg_id=DIRT, pos=ivec2(0, 0))
    tile.flags |= TileFlags.ON_FIRE

    commands: list = []
    build_tile_commands(tile, options=RenderOptions(include_elemental_overlays=False), commands=commands)
    assert all(cmd.layer != RenderLayer.FIRE for cmd in commands)

    world = make_world(floor_tiles(2))
    world.dropped.add_item(DroppedItem(pos=glm.vec2(0, 0), id=DIRT, amount=1))
    commands = build_world_commands(world, options=RenderOptions(include_objects=False))
    assert all(cmd.layer not in (RenderLayer.OBJ_PRE, RenderLayer.OBJ_POST) for cmd in commands)


def test_build_world_commands_stops_at_the_garbage_start() -> None:
    world = make_world(floor_tiles(4))
    # the tiles sit on row y=1 of a 4-wide world: flat indices 4..7
    world.garbage_start = 6

    commands = build_world_commands(world)

    assert len(commands) == 4  # two tiles, fg + bg each
    assert all(cmd.tile_pos.x < 2 for cmd in commands)


def test_build_world_commands_orders_tiles_then_objects() -> None:
    world = make_world(floor_tiles(2))
    world.dropped.add_item(DroppedItem(pos=glm.vec2(8, 8), id=DIRT, amount=1))

    commands = build_world_commands(world)

    # tile sprites are tile-anchored; object icons carry an explicit pixel_pos and
    # are emitted after every tile
    tile_indices = [i for i, cmd in enumerate(commands) if cmd.pixel_pos is None]
    object_indices = [i for i, cmd in enumerate(commands) if cmd.pixel_pos is not None]
    assert tile_indices and object_indices
    assert max(tile_indices) < min(object_indices)
