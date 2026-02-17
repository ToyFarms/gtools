import math
from pathlib import Path
import threading
from collections import OrderedDict
import pygame
from pyglm.glm import ivec2
import numpy as np
from gtools.core.growtopia.rttex import get_image_buffer
from gtools.core.growtopia.texmgr import TexMgr
from gtools.core.growtopia.world import Tile, World
from gtools.gui.render import Renderable

Key = tuple[str, int, int, int, int, bool]


class PyGameRTTexManager(TexMgr[pygame.Surface]):
    def __init__(self, max_atlas: int | None = None, max_texture: int | None = None) -> None:
        self._atlas_cache: OrderedDict[str, pygame.Surface] = OrderedDict()
        self._tex_cache: OrderedDict[Key, pygame.Surface] = OrderedDict()

        self._atlas_lock = threading.Lock()
        self._tex_lock = threading.Lock()
        self.max_atlas = max_atlas
        self.max_texture = max_texture

    def _make_key(self, file: str, x: int, y: int, w: int, h: int, flip_x: bool) -> Key:
        return (file, x, y, w, h, flip_x)

    def _numpy_to_surface(self, arr: np.ndarray) -> pygame.Surface:
        if arr.ndim != 3 or arr.shape[2] != 4 or arr.dtype != np.uint8:
            raise ValueError("array must be shape (h, w, 4) dtype uint8")

        h, w, _ = arr.shape
        if not arr.flags["C_CONTIGUOUS"]:
            arr = np.ascontiguousarray(arr)

        try:
            mv = memoryview(arr)
            surf = pygame.image.frombuffer(mv, (w, h), "RGBA")
        except Exception:
            surf = pygame.Surface((w, h), flags=pygame.SRCALPHA, depth=32)
            try:
                surf = pygame.image.frombytes(arr.tobytes(), (w, h), "RGBA")
            except Exception:
                surf = pygame.surfarray.make_surface(arr[:, :, :3].swapaxes(0, 1))
                alpha = arr[:, :, 3]
                alpha_surf = pygame.Surface((w, h), flags=pygame.SRCALPHA, depth=32)
                alpha_surf.lock()
                pygame.surfarray.pixels_alpha(alpha_surf)[:, :] = alpha.T
                alpha_surf.unlock()
                surf = surf.convert_alpha()
                surf.blit(alpha_surf, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

        try:
            if pygame.display.get_init() and pygame.display.get_surface() is not None:
                surf = surf.convert_alpha()
        except Exception:
            pass

        return surf

    def _ensure_atlas(self, file: str) -> pygame.Surface:
        with self._atlas_lock:
            if file in self._atlas_cache:
                self._atlas_cache.move_to_end(file)
                return self._atlas_cache[file]

            arr = get_image_buffer(file)
            if arr is None:
                raise ValueError(f"failed to get texture: {file!r}")

            if arr.ndim != 3 or arr.shape[2] != 4 or arr.dtype != np.uint8:
                raise ValueError(f"get_image_buffer did not return (H,W,4) uint8 for {file!r}")

            try:
                surf = self._numpy_to_surface(arr)
            except Exception:
                arr = np.ascontiguousarray(arr)
                surf = self._numpy_to_surface(arr)

            self._atlas_cache[file] = surf

            if self.max_atlas is not None:
                while len(self._atlas_cache) > self.max_atlas:
                    self._atlas_cache.popitem(last=False)

            return self._atlas_cache[file]

    def get_nocache(self, file: str | Path, x: int, y: int, w: int = 32, h: int = 32, flip_x: bool = False, copy: bool = False) -> pygame.Surface:
        file_s = str(file)
        atlas_surf = self._ensure_atlas(file_s)

        rect = pygame.Rect(x, y, w, h)
        try:
            cropped = atlas_surf.subsurface(rect)
        except Exception as e:
            raise ValueError(f"invalid subrect {rect} for atlas {file_s}") from e

        if flip_x:
            cropped = pygame.transform.flip(cropped, True, False)

        if copy:
            return cropped.copy()

        return cropped

    def get(self, file: str | Path, x: int, y: int, w: int = 32, h: int = 32, flip_x: bool = False, copy: bool = False) -> pygame.Surface:
        file_s = str(file)
        key = self._make_key(file_s, x, y, w, h, flip_x)

        with self._tex_lock:
            if key in self._tex_cache:
                self._tex_cache.move_to_end(key)
                tex = self._tex_cache[key]
                return tex.copy() if copy else tex

        atlas_surf = self._ensure_atlas(file_s)
        rect = pygame.Rect(x, y, w, h)
        try:
            cropped = atlas_surf.subsurface(rect)
        except Exception as e:
            raise ValueError(f"invalid subrect {rect} for atlas {file_s}") from e

        if flip_x:
            cropped = pygame.transform.flip(cropped, True, False)

        with self._tex_lock:
            self._tex_cache[key] = cropped
            if self.max_texture is not None:
                while len(self._tex_cache) > self.max_texture:
                    self._tex_cache.popitem(last=False)

        return cropped.copy() if copy else cropped

    def clear_caches(self) -> None:
        with self._atlas_lock, self._tex_lock:
            self._atlas_cache.clear()
            self._tex_cache.clear()


class RenderWorld(Renderable):
    def __init__(self, world: World) -> None:
        self.world = world
        self.tex_mgr = PyGameRTTexManager(max_texture=1024)
        self.surf = pygame.Surface((self.world.width * 32, self.world.height * 32), flags=pygame.SRCALPHA).convert_alpha()

        self.pos = pygame.Vector2(0, 0)
        self.size = pygame.Vector2(self.world.width * 32, self.world.height * 32)

        self._last_view_key = None
        self._last_view_surf: pygame.Surface | None = None

    def _invalidate_view_cache(self) -> None:
        self._last_view_key = None
        self._last_view_surf = None

    def update(self, dt: float) -> None:
        if self.surf.size != (self.world.width * 32, self.world.height * 32):
            self.surf = pygame.Surface((self.world.width * 32, self.world.height * 32), flags=pygame.SRCALPHA).convert_alpha()
            self.size = pygame.Vector2(self.world.width * 32, self.world.height * 32)
            self.world.mark_all_dirty()
            self._invalidate_view_cache()

        any_dirty = False
        for tile in self.world.tiles:
            if tile.dirty:
                self.render_tile(self.surf, tile)
                tile.dirty = False
                any_dirty = True

        if any_dirty:
            self._invalidate_view_cache()

    def render_tile(self, surf: pygame.Surface, tile: Tile) -> None:
        target = (tile.pos.x * 32, tile.pos.y * 32, 32, 32)
        surf.fill((0, 0, 0, 0), target)

        if tile.bg_id != 0:
            tile_surf = tile.get_bg_texture(self.tex_mgr)
            surf.blit(tile_surf, (tile.pos.x * 32, tile.pos.y * 32))
        if tile.fg_id != 0:
            tile_surf = tile.get_fg_texture(self.tex_mgr)
            surf.blit(tile_surf, (tile.pos.x * 32, tile.pos.y * 32))

    def get_surface(self) -> pygame.Surface:
        return self.surf

    def _get_visible_world_rect(self, camera, screen_size: pygame.Vector2) -> pygame.Rect:
        screen_w = int(screen_size.x)
        screen_h = int(screen_size.y)
        w_world = int(math.ceil(screen_w / camera.zoom))
        h_world = int(math.ceil(screen_h / camera.zoom))
        x_world = int(round(camera.offset.x))
        y_world = int(round(camera.offset.y))
        return pygame.Rect(x_world, y_world, w_world, h_world)


    def get_view_surface(self, camera, screen_size: pygame.Vector2, *, smooth: bool = True) -> pygame.Surface:
        screen_w = int(screen_size.x)
        screen_h = int(screen_size.y)

        unclamped = self._get_visible_world_rect(camera, pygame.Vector2(screen_w, screen_h))
        world_bounds = pygame.Rect(0, 0, int(self.size.x), int(self.size.y))

        src = unclamped.clip(world_bounds)
        target = pygame.Surface((screen_w, screen_h), flags=pygame.SRCALPHA).convert_alpha()
        target.fill((0, 0, 0, 0))

        if src.width == 0 or src.height == 0:
            self._last_view_key = None
            self._last_view_surf = target
            return target

        dst_x = int(round((src.x - unclamped.x) * camera.zoom))
        dst_y = int(round((src.y - unclamped.y) * camera.zoom))

        dst_w = max(1, int(round(src.width * camera.zoom)))
        dst_h = max(1, int(round(src.height * camera.zoom)))

        zoom_key = int(round(camera.zoom * 1000))
        key = (unclamped.x, unclamped.y, unclamped.w, unclamped.h, zoom_key, screen_w, screen_h)

        if key == self._last_view_key and self._last_view_surf is not None:
            return self._last_view_surf

        try:
            subs = self.surf.subsurface(src).copy()
        except Exception:
            subs = self.surf.copy()

        if (dst_w, dst_h) != subs.get_size():
            if smooth:
                scaled = pygame.transform.smoothscale(subs, (dst_w, dst_h))
            else:
                scaled = pygame.transform.scale(subs, (dst_w, dst_h))
        else:
            scaled = subs

        target.blit(scaled, (dst_x, dst_y))

        self._last_view_key = key
        self._last_view_surf = target
        return target
