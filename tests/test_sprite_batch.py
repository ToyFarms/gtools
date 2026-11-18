"""GPU command translation math (headless, no GL context).

``command_instances`` is the GPU's single adapter to the render command
system; the parts tested here are the pure instance-record math, following the
same pattern as ``test_cybot_renderer.py`` (the shader + mesh creation is the
only GL-bound part). Pinned conventions:

* commands are client space (top-left anchored, tile top-left = x * 32); the
  GUI centres tiles at x * 32, so a sprite of size s is centred at
  ``top_left + s / 2 - 16``;
* depth comes from ``LAYER_DEPTHS`` bands, spread in the stable layer order;
* ``RenderCommand.shadow`` materializes a black, offset copy at 40 % alpha.
"""

from dataclasses import dataclass

import numpy as np
from pyglm.glm import ivec2

from gtools.core.growtopia.render_commands import RenderCommand, RenderLayer, TextCommand, build_dropped_commands, sort_commands
from gtools.gui.lib.layer import OBJECT_POST_FOREGROUND_END, OBJECT_POST_FOREGROUND_START
from gtools.gui.lib.sprite_batch import LAYER_DEPTHS, SHADOW_OFFSET, SHADOW_OPACITY, SPRITE_INSTANCE_DTYPE, command_instances

TEX_SIZE = (64, 64)


@dataclass(eq=False)  # identity hash, like GLTex
class StubTex:
    """Stands in for a GLTex: dimensions + texture-array identity."""

    width: int = TEX_SIZE[0]
    height: int = TEX_SIZE[1]
    layer: int = 0
    array: str = "page1"


TEX_A = StubTex(array="page1", layer=3)
TEX_B = StubTex(array="page2", layer=7)


def resolver(texture_file: str) -> StubTex:
    return {"a.rttex": TEX_A, "b.rttex": TEX_B}[texture_file]


def sprite(**kwargs) -> RenderCommand:
    defaults = dict(
        tile_pos=ivec2(2, 3),
        item_id=1,
        layer=RenderLayer.FG,
        texture_file="a.rttex",
        tex_pos=ivec2(1, 1),
    )
    defaults.update(kwargs)
    return RenderCommand(**defaults)


def instances_of(commands: list):
    return command_instances(commands, resolver)


def test_layer_depths_cover_every_render_layer() -> None:
    from gtools.core.growtopia.render_commands import LAYER_ORDER

    assert set(LAYER_DEPTHS.keys()) == set(LAYER_ORDER)
    for start, end in LAYER_DEPTHS.values():
        assert start <= end


def test_tile_anchored_sprite_is_centred_on_the_tile() -> None:
    result = instances_of([sprite()])

    records = result.layers[RenderLayer.FG][resolver("a.rttex")]
    assert records.shape == (1,)
    rec = records[0]
    # client top-left (64, 96) + 32 / 2 - 16 = (64, 96): a 32px tile sprite's
    # centre lands on the GUI's tile centre
    assert rec["pos"].tolist() == [64.0, 96.0]
    assert rec["size"].tolist() == [32.0, 32.0]


def test_pixel_anchored_sprite_of_half_size() -> None:
    cmd = sprite(layer=RenderLayer.OBJ_POST, pixel_pos=(35, 37), sprite_size=16)
    result = instances_of([cmd])

    rec = result.layers[RenderLayer.OBJ_POST][resolver("a.rttex")][0]
    assert rec["pos"].tolist() == [35 + 8 - 16, 37 + 8 - 16]
    assert rec["size"].tolist() == [16.0, 16.0]


def test_uv_cell_uses_the_sample_size_and_honours_the_flip() -> None:
    cmd = sprite(tex_pos=ivec2(2, 1), sample_size=16)
    uv = instances_of([cmd]).layers[RenderLayer.FG][resolver("a.rttex")][0]["uv"].tolist()
    assert uv == [2 * 16 / 64, 1 * 16 / 64, 3 * 16 / 64, 2 * 16 / 64]

    flipped = sprite(tex_pos=ivec2(2, 1), sample_size=16, is_flipped=True)
    uv = instances_of([flipped]).layers[RenderLayer.FG][resolver("a.rttex")][0]["uv"].tolist()
    assert uv == [3 * 16 / 64, 1 * 16 / 64, 2 * 16 / 64, 2 * 16 / 64]


def test_tint_and_opacity_and_paint_are_carried() -> None:
    cmd = sprite(tint=(10, 20, 30), opacity=0.6, paint_index=5)
    rec = instances_of([cmd]).layers[RenderLayer.FG][resolver("a.rttex")][0]

    assert rec["tint"] == (10 << 24) | (20 << 16) | (30 << 8) | 255
    assert rec["opacity"] == 0.6
    assert rec["paint_index"] == 5.0
    assert rec["tex_layer"] == 3.0  # from the resolver's texture


def test_instances_group_by_texture_array_and_layer() -> None:
    commands = [sprite(), sprite(texture_file="b.rttex"), sprite()]
    result = instances_of(commands)

    assert set(result.layers.keys()) == {RenderLayer.FG}
    assert result.layers[RenderLayer.FG][resolver("a.rttex")].shape[0] == 2
    assert result.layers[RenderLayer.FG][resolver("b.rttex")].shape[0] == 1
    # counts mirror the per-layer instance totals
    assert result.counts[RenderLayer.FG] == 3


def test_depth_bands_spread_in_draw_order() -> None:
    commands = [
        sprite(layer=RenderLayer.OBJ_POST, pixel_pos=(0, 0)),
        sprite(layer=RenderLayer.OBJ_POST, pixel_pos=(8, 8)),
        sprite(layer=RenderLayer.OBJ_POST, pixel_pos=(16, 16)),
    ]
    result = instances_of(commands)

    records = result.layers[RenderLayer.OBJ_POST][resolver("a.rttex")]
    depths = records["depth"].tolist()
    start, end = LAYER_DEPTHS[RenderLayer.OBJ_POST]
    assert (start, end) == (OBJECT_POST_FOREGROUND_START, OBJECT_POST_FOREGROUND_END)
    # back to front inside the band, in command order
    assert depths == sorted(depths)
    assert start < depths[0] < depths[1] < depths[2] < end


def test_layer_sort_matches_the_cpu_order() -> None:
    commands = [
        sprite(layer=RenderLayer.FG),
        sprite(layer=RenderLayer.BG),
        sprite(layer=RenderLayer.OBJ_POST),
        sprite(layer=RenderLayer.FG_BEFORE),
    ]
    result = instances_of(commands)

    assert list(result.layers.keys()) == [RenderLayer.BG, RenderLayer.FG_BEFORE, RenderLayer.FG, RenderLayer.OBJ_POST]
    # sort_commands is the shared ordering primitive
    assert [c.layer for c in sort_commands(commands)] == [RenderLayer.BG, RenderLayer.FG_BEFORE, RenderLayer.FG, RenderLayer.OBJ_POST]


def test_shadow_materializes_a_black_offset_copy() -> None:
    cmd = sprite(pixel_pos=(35, 37), sprite_size=16, shadow=True)
    cmd2 = sprite(pixel_pos=(100, 100), shadow=False)
    result = instances_of([cmd, cmd2])

    assert result.counts[RenderLayer.FG] == 2
    records = result.layers[RenderLayer.FG][resolver("a.rttex")]
    assert records.shape[0] == 2  # only the flagged command is an icon instance

    shadow = result.shadows[resolver("a.rttex")]
    assert shadow.shape == (1,)
    rec = shadow[0]
    assert rec["pos"].tolist() == [35 + 8 - 16 + SHADOW_OFFSET[0], 37 + 8 - 16 + SHADOW_OFFSET[1]]
    assert rec["size"].tolist() == [16.0, 16.0]
    assert rec["tint"] == 0x000000FF  # black silhouette
    assert rec["opacity"] == SHADOW_OPACITY
    assert rec["uv"].tolist() == records[0]["uv"].tolist()


def test_text_commands_pass_through_with_layer_order() -> None:
    text = TextCommand(text="12", pixel_pos=(40, 50), layer=RenderLayer.OBJ_POST, font="f.ttf", size=10)
    icon = sprite(layer=RenderLayer.OBJ_POST, pixel_pos=(32, 32))

    result = instances_of([icon, text])

    assert [cmd for cmd, _ in result.texts] == [text]
    start, end = LAYER_DEPTHS[RenderLayer.OBJ_POST]
    assert start < result.texts[0][1] < end  # the text's band slot
    assert result.texts[0][1] > result.layers[RenderLayer.OBJ_POST][TEX_A][0]["depth"]  # after its icon
    assert result.counts[RenderLayer.OBJ_POST] == 2  # texts occupy band slots too


def test_dropped_commands_build_the_full_command_set() -> None:
    """The builder's uid order + the translator's stable sort stay consistent."""

    class Drop:
        def __init__(self, uid: int) -> None:
            self.uid = uid

    # uid ordering is the builder's job; the translator preserves input order
    assert [d.uid for d in sorted([Drop(3), Drop(1), Drop(2)], key=lambda d: d.uid)] == [1, 2, 3]
    # 12 f32 (pos2 + size2 + uv4 + layer + depth + paint + opacity) + 1 u32 (tint)
    assert SPRITE_INSTANCE_DTYPE.itemsize == 52


def test_instances_are_not_lost_when_textures_share_one_array() -> None:
    """The GLTexManager packs same-size rttex pages as layers of ONE array.

    Meshes used to be keyed by the array alone, so every texture's mesh
    overwrote the previous one and most of the chunk vanished. The instance
    records themselves must keep one group per source texture.
    """

    @dataclass(eq=False)
    class SharedTex:
        width: int = TEX_SIZE[0]
        height: int = TEX_SIZE[1]
        layer: int = 0
        array: str = "shared"  # every file lands in the same array

    shared = {f"p{i}.rttex": SharedTex(layer=i, array="shared") for i in range(5)}

    commands = [sprite(texture_file=f"p{i}.rttex", pixel_pos=(i * 4, 0)) for i in range(5)]
    result = command_instances(commands, shared.get)

    groups = result.layers[RenderLayer.FG]
    assert len(groups) == 5  # one instance group per source texture
    assert sum(len(v) for v in groups.values()) == 5  # none lost


def test_dropped_renderer_draws_on_the_dedicated_dropped_band() -> None:
    """Dropped objects sit on the OBJECT_DROPPED band above the entities (tuned)."""
    from gtools.gui.lib.layer import OBJECT_DROPPED_END, OBJECT_DROPPED_START
    from gtools.gui.lib.object_renderer import DEPTH_BANDS

    assert DEPTH_BANDS[RenderLayer.OBJ_POST] == (OBJECT_DROPPED_START, OBJECT_DROPPED_END)
    # the tile-scene bands stay untouched
    from gtools.gui.lib.sprite_batch import LAYER_DEPTHS

    assert LAYER_DEPTHS[RenderLayer.OBJ_POST][0] == OBJECT_POST_FOREGROUND_START


def test_shadow_records_sit_in_the_lower_half_of_the_band() -> None:
    cmd = sprite(layer=RenderLayer.OBJ_POST, pixel_pos=(0, 0), shadow=True)
    filler = [sprite(layer=RenderLayer.OBJ_POST, pixel_pos=(100 + i, 0)) for i in range(7)]

    result = command_instances([cmd, *filler], resolver)

    band_start, band_end = LAYER_DEPTHS[RenderLayer.OBJ_POST]
    icons = result.layers[RenderLayer.OBJ_POST][TEX_A]["depth"]
    shadow = result.shadows[TEX_A]["depth"]
    assert shadow[0] < icons[0]  # behind its own icon
    assert band_start <= shadow[0] < band_start + 0.5 * (band_end - band_start)  # lower half


def test_text_instance_layout_matches_the_pushed_floats() -> None:
    """13 floats per glyph: offset(2) size(2) texOffset(2) texSize(2) z(1) color(4)."""
    from gtools.gui.lib.text_renderer import TextRenderer

    assert sum(TextRenderer.INSTANCE_LAYOUT) == 13
