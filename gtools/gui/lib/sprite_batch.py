"""The GPU's single adapter to the core render command system.

The commands (``gtools.core.growtopia.render_commands``) describe the scene in
client world space: a tile's top-left corner is ``(x * 32, y * 32)`` and a
sprite's ``pixel_pos`` is its top-left corner. This module converts them into
instanced GL meshes:

* :data:`LAYER_DEPTHS` maps each :class:`RenderLayer` onto the GUI depth bands
  (:mod:`gtools.gui.lib.layer`, bigger = closer to the camera);
* :func:`command_instances` is the pure conversion (no GL, unit-tested
  headlessly): stable layer sort, depth fractions, UV cells, tint/opacity
  packing and drop-shadow materialization;
* :class:`SpriteBatch` owns the textures + shader and builds/draws the meshes;
* :class:`TextBatch` routes :class:`TextCommand` through the SDF text pipeline.

The space conversion happens exactly once, in :func:`command_instances`: the
GUI centres tile ``(x, y)`` at ``(x * 32, y * 32)``, so a top-left anchored
sprite of size ``s`` becomes a quad centred at ``top_left + s / 2 - 16``.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable, ClassVar, Sequence

import numpy as np
from OpenGL.GL import GL_FALSE, GL_STATIC_DRAW, GL_TRUE, GL_UNSIGNED_INT, glDepthMask

from gtools import setting
from gtools.core.growtopia.render_commands import Command, RenderCommand, RenderLayer, TextCommand, sort_commands
from gtools.gui.camera import Camera2D
from gtools.gui.camera3d import Camera3D
from gtools.gui.lib import layer
from gtools.gui.lib.text_renderer import TextRenderer, parse_colored_text
from gtools.gui.opengl import Mesh, ShaderProgram
from gtools.gui.texture import GLTex, GLTexManager, TextureArray

TILE_SIZE = 32
# the GUI centres tile (x, y) at (x * 32, y * 32) while commands anchor sprites
# at their top-left corner: a sprite of size s shifts by s / 2 - 16
WORLD_OFFSET = TILE_SIZE / 2

# drop shadows are materialized from RenderCommand.shadow: a black, offset copy
# of the sprite drawn in the depth-masked shadow pass
SHADOW_OFFSET = (-5.0, 5.0)
SHADOW_OPACITY = 0.4
SHADOW_TINT = 0x000000FF

DEFAULT_TINT = 0xFFFFFFFF

# every RenderLayer maps onto a GUI depth band; a band spreads its instances
# across (start, end) in draw order, single-value layers are fixed
LAYER_DEPTHS: dict[RenderLayer, tuple[float, float]] = {
    RenderLayer.BG: (layer.WORLD_BACKGROUND, layer.WORLD_BACKGROUND),
    RenderLayer.FG_BEFORE: (layer.WORLD_PRE_FOREGROUND, layer.WORLD_PRE_FOREGROUND),
    RenderLayer.OBJ_PRE: (layer.OBJECT_PRE_FOREGROUND_START, layer.OBJECT_PRE_FOREGROUND_END),
    RenderLayer.FG: (layer.WORLD_FOREGROUND, layer.WORLD_FOREGROUND),
    RenderLayer.FG_AFTER: (layer.WORLD_POST_FOREGROUND, layer.WORLD_POST_FOREGROUND),
    RenderLayer.OBJ_POST: (layer.OBJECT_POST_FOREGROUND_START, layer.OBJECT_POST_FOREGROUND_END),
    RenderLayer.OBJ_TEXT: (layer.WORLD_POST_FOREGROUND, layer.WORLD_POST_FOREGROUND),
    RenderLayer.FIRE: (layer.WORLD_FIRE, layer.WORLD_FIRE),
    RenderLayer.WATER: (layer.WORLD_WATER, layer.WORLD_WATER),
}

# translucent tile overlays must not punch depth holes for the layers above them
LAYER_DEPTH_WRITE: dict[RenderLayer, bool] = {layer_name: True for layer_name in LAYER_DEPTHS}
LAYER_DEPTH_WRITE[RenderLayer.FG_AFTER] = False

# single-value layers spread their instances across this much depth in command
# order: overlapping same-layer sprites (the seed base/overlay pair, ...) must
# compose like the CPU does (later command wins), which the strict GL_LESS
# depth test only gives them through distinct depth values. Far below the
# smallest gap between two layer slots (1.0), so the tuned layer order holds.
LAYER_EPSILON = 0.001

TextureResolver = Callable[[str], GLTex]

SPRITE_INSTANCE_DTYPE = np.dtype(
    [
        ("pos", np.float32, (2,)),
        ("size", np.float32, (2,)),
        ("uv", np.float32, (4,)),
        ("tex_layer", np.float32),
        ("depth", np.float32),
        ("paint_index", np.float32),
        ("tint", np.uint32),
        ("opacity", np.float32),
    ]
)


def _pack_rgba_u32(r: int, g: int, b: int, a: int = 255) -> int:
    return ((r & 0xFF) << 24) | ((g & 0xFF) << 16) | ((b & 0xFF) << 8) | (a & 0xFF)


def _world_top_left(cmd: RenderCommand) -> tuple[float, float]:
    if cmd.pixel_pos is not None:
        return (float(cmd.pixel_pos[0]), float(cmd.pixel_pos[1]))
    return (cmd.tile_pos.x * TILE_SIZE, cmd.tile_pos.y * TILE_SIZE)


def _sprite_uv(cmd: RenderCommand, tex: GLTex) -> tuple[float, float, float, float]:
    cell = max(1, cmd.sample_size)
    u0 = cmd.tex_pos.x * cell / tex.width
    v0 = cmd.tex_pos.y * cell / tex.height
    u1 = (cmd.tex_pos.x + 1) * cell / tex.width
    v1 = (cmd.tex_pos.y + 1) * cell / tex.height
    if cmd.is_flipped:
        u0, u1 = u1, u0
    return (u0, v0, u1, v1)


def _tint_u32(cmd: RenderCommand) -> int:
    tint = cmd.get_tint()
    if tint is None:
        return DEFAULT_TINT
    if len(tint) == 3:  # the tuple form carries RGB only
        return _pack_rgba_u32(int(tint[0]), int(tint[1]), int(tint[2]))
    return _pack_rgba_u32(int(tint[0]), int(tint[1]), int(tint[2]), int(tint[3]))


def _layer_depth(bands: dict[RenderLayer, tuple[float, float]], layer_name: RenderLayer, index: int, count: int) -> float:
    start, end = bands[layer_name]
    span = end - start if end != start else LAYER_EPSILON
    return start + (index + 0.5) / max(count, 1) * span


def _sprite_record(cmd: RenderCommand, tex: GLTex, depth: float) -> tuple:
    left, top = _world_top_left(cmd)
    size = float(cmd.sprite_size)
    centre = (left + size / 2 - WORLD_OFFSET, top + size / 2 - WORLD_OFFSET)
    return (
        centre,
        (size, size),
        _sprite_uv(cmd, tex),
        float(tex.layer),
        depth,
        float(cmd.paint_index),
        _tint_u32(cmd),
        float(cmd.opacity),
    )


def _shadow_record(cmd: RenderCommand, tex: GLTex, depth: float, band: tuple[float, float]) -> tuple:
    left, top = _world_top_left(cmd)
    size = float(cmd.sprite_size)
    centre = (left + size / 2 - WORLD_OFFSET + SHADOW_OFFSET[0], top + size / 2 - WORLD_OFFSET + SHADOW_OFFSET[1])
    # the tuned shadow pass keeps the silhouette copies in the lower half of
    # their object band (drawn first with the depth mask off)
    start, end = band
    shadow_depth = start + (depth - start) * 0.5 if end != start else start
    return (
        centre,
        (size, size),
        _sprite_uv(cmd, tex),
        float(tex.layer),
        shadow_depth,
        0.0,
        SHADOW_TINT,
        SHADOW_OPACITY,
    )


@dataclass(slots=True)
class CommandInstances:
    """The backend-neutral conversion result, ready for mesh building."""

    layers: dict[RenderLayer, dict[GLTex, np.ndarray]]
    shadows: dict[GLTex, np.ndarray]
    texts: list[tuple[TextCommand, float]]  # (command, assigned depth)
    counts: dict[RenderLayer, int]


def command_instances(commands: Sequence[Command], textures: TextureResolver, *, depth_bands: dict[RenderLayer, tuple[float, float]] | None = None) -> CommandInstances:
    """Convert commands (builder order) into per-layer instance records.

    Instances within a band keep the command order (the stable layer sort of
    :func:`sort_commands`), so both backends draw the same scene. ``depth_bands``
    overrides :data:`LAYER_DEPTHS` per layer (the dropped-object renderer draws
    its OBJ_POST commands on the dedicated dropped band above the entities).
    """
    bands = depth_bands or LAYER_DEPTHS
    ordered = sort_commands(commands)
    counts = Counter(cmd.layer for cmd in ordered)
    index_in_layer: defaultdict[RenderLayer, int] = defaultdict(int)

    layers: defaultdict[RenderLayer, defaultdict[GLTex, list[tuple]]] = defaultdict(lambda: defaultdict(list))
    shadows: defaultdict[GLTex, list[tuple]] = defaultdict(list)
    texts: list[tuple[TextCommand, float]] = []

    for cmd in ordered:
        layer_index = index_in_layer[cmd.layer]
        index_in_layer[cmd.layer] += 1
        depth = _layer_depth(bands, cmd.layer, layer_index, counts[cmd.layer])

        if isinstance(cmd, RenderCommand):
            tex = textures(cmd.texture_file)
            layers[cmd.layer][tex].append(_sprite_record(cmd, tex, depth))
            if cmd.shadow:
                shadows[tex].append(_shadow_record(cmd, tex, depth, bands[cmd.layer]))
        elif isinstance(cmd, TextCommand):
            texts.append((cmd, depth))

    return CommandInstances(
        layers={layer_name: {tex: np.array(records, dtype=SPRITE_INSTANCE_DTYPE) for tex, records in per_tex.items()} for layer_name, per_tex in layers.items()},
        shadows={tex: np.array(records, dtype=SPRITE_INSTANCE_DTYPE) for tex, records in shadows.items()},
        texts=texts,
        counts=dict(counts),
    )


def _place_top_left(renderer: TextRenderer, cmd: TextCommand) -> tuple[float, float]:
    """Convert the command's client-space ink-box top-left anchor into the text pipeline's baseline (GUI space).

    The SDF glyph bitmaps carry ``sdf_pixel_range`` px of padding per edge,
    which the bearing values already include: the ink starts at
    ``bearing + pad`` right of the pen and ``bearing - pad`` below the baseline.
    """
    first_ink_offset: float | None = None
    max_ink_top = 0.0
    pad = renderer.font.sdf_pixel_range
    for char, _ in parse_colored_text(cmd.text):
        glyph = renderer.font.get_char(char)
        if glyph.size[0] == 0:
            continue
        if first_ink_offset is None:
            first_ink_offset = glyph.bearing[0] + pad  # ink left, from the pen
        max_ink_top = max(max_ink_top, glyph.bearing[1] - pad)  # ink top, below the baseline

    # client space -> GUI space (the -16 shift every sprite goes through)
    x = cmd.pixel_pos[0] + cmd.offset[0] - (first_ink_offset or 0.0) - WORLD_OFFSET
    y = cmd.pixel_pos[1] + cmd.offset[1] + max_ink_top - WORLD_OFFSET
    return x, y


class TextBatch:
    """Builds and draws :class:`TextCommand` runs through the SDF text pipeline."""

    def __init__(self, texts: Sequence[tuple[TextCommand, float]]) -> None:
        self._renderers: dict[tuple[str, int], TextRenderer] = {}
        for cmd, depth in texts:
            key = (cmd.font, cmd.size)
            renderer = self._renderers.get(key)
            if renderer is None:
                renderer = TextRenderer(cmd.font, size=cmd.size)
                self._renderers[key] = renderer

            x, y = _place_top_left(renderer, cmd)
            color = tuple(c / 255.0 for c in cmd.color)
            renderer.build_text(cmd.text, x, y, depth, color=color)

        for renderer in self._renderers.values():
            renderer.build()

    def draw(self, camera: Camera2D) -> None:
        for renderer in self._renderers.values():
            renderer.draw(camera)

    def draw_3d(self, camera3d: Camera3D, layer_spread: float) -> None:
        for renderer in self._renderers.values():
            renderer.draw_3d(camera3d, layer_spread)

    def delete(self) -> None:
        for renderer in self._renderers.values():
            renderer.delete()
        self._renderers.clear()

@dataclass(slots=True)
class SpriteMeshes:
    """The GL meshes built from one command batch (typically one chunk).

    The GLTexManager packs same-size textures (every rttex page) as *layers*
    of one shared TextureArray, so meshes are stored per array as a list --
    one mesh per source texture -- and drawing binds the array once and draws
    the list, like the tuned world pipeline did.
    """

    layers: dict[RenderLayer, dict[TextureArray, list[tuple[str, Mesh]]]] = field(default_factory=dict)
    shadows: dict[TextureArray, list[tuple[str, Mesh]]] = field(default_factory=dict)
    texts: TextBatch | None = None
    counts: dict[RenderLayer, int] = field(default_factory=dict)

    def instance_count(self, layer_names: frozenset[RenderLayer] | set[RenderLayer]) -> int:
        return sum(self.counts.get(layer_name, 0) for layer_name in layer_names)

    def delete(self) -> None:
        for meshes in self.layers.values():
            for entries in meshes.values():
                for _, mesh in entries:
                    mesh.delete()
        self.layers.clear()

        for entries in self.shadows.values():
            for _, mesh in entries:
                mesh.delete()
        self.shadows.clear()

        if self.texts is not None:
            self.texts.delete()
            self.texts = None


class SpriteBatch:
    """Builds and draws :class:`SpriteMeshes` from render commands."""

    INSTANCE_LAYOUT: ClassVar[list] = [2, 2, 4, 1, 1, 1, (1, GL_UNSIGNED_INT), 1]

    def __init__(self) -> None:
        self._tex_mgr = GLTexManager()

        self._shader = ShaderProgram.get("shaders/sprite")
        self._mvp = self._shader.get_uniform("u_mvp")
        self._tex = self._shader.get_uniform("texArray")

        self._shader3d = ShaderProgram.from_files("shaders/sprite3d.vert", "shaders/sprite.frag")
        self._vp3d = self._shader3d.get_uniform("u_view_proj")
        self._tex3d = self._shader3d.get_uniform("texArray")
        self._spread3d = self._shader3d.get_uniform("u_layer_spread")

    @property
    def texture_count(self) -> int:
        return self._tex_mgr.texture_count

    def _texture(self, texture_file: str) -> GLTex:
        return self._tex_mgr.load_texture(setting.gt_path / "game" / texture_file)

    def build(self, commands: Sequence[Command], *, existing: SpriteMeshes | None = None, usage: int = GL_STATIC_DRAW, depth_bands: dict[RenderLayer, tuple[float, float]] | None = None) -> SpriteMeshes:
        """Translate commands into meshes; with ``existing`` meshes are updated in place."""
        instances = command_instances(commands, self._texture, depth_bands=depth_bands)
        self._tex_mgr.flush()

        existing_layers = existing.layers if existing is not None else {}
        layers: dict[RenderLayer, dict[TextureArray, list[tuple[str, Mesh]]]] = {}
        for layer_name, per_tex in instances.layers.items():
            layers[layer_name] = self._make_meshes(per_tex, existing_layers.get(layer_name, {}), usage)
        # drop meshes whose texture vanished from the rebuilt batch
        for layer_name, per_array in existing_layers.items():
            new_per_array = layers.get(layer_name, {})
            for arr, entries in per_array.items():
                kept = {key for key, _ in new_per_array.get(arr, [])}
                for key, mesh in entries:
                    if key not in kept:
                        mesh.delete()

        existing_shadows = existing.shadows if existing is not None else {}
        shadows = self._make_meshes(instances.shadows, existing_shadows, usage)
        for arr, entries in existing_shadows.items():
            kept = {key for key, _ in shadows.get(arr, [])}
            for key, mesh in entries:
                if key not in kept:
                    mesh.delete()

        texts = TextBatch(instances.texts) if instances.texts else None
        if existing is not None and existing.texts is not None:
            existing.texts.delete()

        return SpriteMeshes(layers=layers, shadows=shadows, texts=texts, counts=instances.counts)

    def _make_meshes(self, src: dict[GLTex, np.ndarray], existing: dict[TextureArray, list[tuple[str, Mesh]]], usage: int) -> dict[TextureArray, list[tuple[str, Mesh]]]:
        result: dict[TextureArray, list[tuple[str, Mesh]]] = {}
        reused: set[str] = set()

        for tex, data in src.items():
            match = next((entry for entries in existing.values() for entry in entries if entry[0] == tex.key), None)
            if match is not None:
                key, mesh = match
                mesh.update_instance_data(data)
                mesh.set_instance_count(len(data))
                reused.add(key)
            else:
                key, mesh = tex.key, Mesh(
                    Mesh.RECT_WITH_UV_VERTS,
                    [2, 2],
                    Mesh.RECT_INDICES,
                    usage=usage,
                    instance_data=data,
                    instance_layout=self.INSTANCE_LAYOUT,
                    instance_attrib_base=2,
                    instance_capacity=max(len(data), 16),
                )
            result.setdefault(tex.array, []).append((key, mesh))

        return result

    def draw(self, camera: Camera2D, meshes: SpriteMeshes, layer_name: RenderLayer) -> None:
        per_array = meshes.layers.get(layer_name)
        if not per_array:
            return

        self._shader.use()
        self._mvp.set_mat4x4(camera.proj_as_numpy())

        depth_write = LAYER_DEPTH_WRITE[layer_name]
        if not depth_write:
            glDepthMask(GL_FALSE)

        for arr, entries in per_array.items():
            arr.bind(unit=0)
            self._tex.set_int(0)
            for _, mesh in entries:
                mesh.draw_instanced()

        if not depth_write:
            glDepthMask(GL_TRUE)

        if meshes.texts is not None and layer_name == RenderLayer.OBJ_POST:
            meshes.texts.draw(camera)

    def draw_shadows(self, camera: Camera2D, meshes: SpriteMeshes) -> None:
        if not meshes.shadows:
            return

        glDepthMask(GL_FALSE)
        self._shader.use()
        self._mvp.set_mat4x4(camera.proj_as_numpy())

        for arr, entries in meshes.shadows.items():
            arr.bind(unit=0)
            self._tex.set_int(0)
            for _, mesh in entries:
                mesh.draw_instanced()

        glDepthMask(GL_TRUE)

    def draw_3d(self, camera3d: Camera3D, layer_spread: float, meshes: SpriteMeshes, layer_name: RenderLayer) -> None:
        per_array = meshes.layers.get(layer_name)
        if not per_array:
            return

        self._shader3d.use()
        self._vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self._spread3d.set_float(layer_spread)

        depth_write = LAYER_DEPTH_WRITE[layer_name]
        if not depth_write:
            glDepthMask(GL_FALSE)

        for arr, entries in per_array.items():
            arr.bind(unit=0)
            self._tex3d.set_int(0)
            for _, mesh in entries:
                mesh.draw_instanced()

        if not depth_write:
            glDepthMask(GL_TRUE)

        if meshes.texts is not None and layer_name == RenderLayer.OBJ_POST:
            meshes.texts.draw_3d(camera3d, layer_spread)

    def draw_shadows_3d(self, camera3d: Camera3D, layer_spread: float, meshes: SpriteMeshes) -> None:
        if not meshes.shadows:
            return

        glDepthMask(GL_FALSE)
        self._shader3d.use()
        self._vp3d.set_mat4x4(camera3d.view_proj_as_numpy())
        self._spread3d.set_float(layer_spread)

        for arr, entries in meshes.shadows.items():
            arr.bind(unit=0)
            self._tex3d.set_int(0)
            for _, mesh in entries:
                mesh.draw_instanced()

        glDepthMask(GL_TRUE)
