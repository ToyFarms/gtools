from typing import cast
from PIL import Image
import click
from pyglm.glm import ivec2, ivec4
import numpy as np

from gtools.core.growtopia.items_dat import Item, ItemInfoTextureType, item_database
from gtools.core.growtopia.renderer.world_renderer import WorldRenderer
from gtools.core.growtopia.rttex import get_image_buffer
from gtools.core.growtopia.world import Tile, TileFlags, World
from gtools.core.wsl import windows_home
from gtools.baked.items import (
    AQUA_CAVE_CRYSTAL,
    BEDROCK,
    BLANK,
    BONE_CHECKPOINT,
    CAVE_COLUMN,
    CAVE_DIRT,
    CAVE_PLATFORM,
    CLIMBING_WALL,
    DATA_BEDROCK,
    DIAMOND_REGAL_BANNISTER,
    DIAMOND_REGAL_STAIRS,
    DWARVEN_BACKGROUND,
    FISSURE,
    GREAT_TURRET_OF_GROWTOPIA,
    GUILD_FLAG_POLE_SPEAR,
    GUILD_FLAG_SHIELD_OPEN_DIVISION_CLOSE,
    GUILD_FLAG_TATTERS,
    LOVEWILLOW,
    MAGIC_INFUSED_STONE,
    MAGIC_INFUSED_VEIN,
    MANOR_HOUSE_SANDSTONE,
    MANOR_HOUSE_SANDSTONE_STEPS,
    MASTER_PENG_STONEWORK,
    MONOCHROMATIC_BEDROCK,
    MYSTERY_DOOR,
    PURE_MAGIC_ORE,
    PURPLE_CAVE_CRYSTAL,
    REGAL_BANNISTER,
    REGAL_STAIRS,
    STALACTITE,
    STALAGMITE,
    STEAM_LAUNCHER,
    STEAM_PIPE,
    STONE_PAGODA,
    STONE_PAGODA_BASE,
    TWISTED_ROOF,
    TWISTED_WINDOWS,
    WEEPING_WILLOW,
    WEEPING_WILLOW_FOLIAGE,
)


def tile_should_connect(world: World, tile_x: int, tile_y: int, item_id: int, maybe_cave_stuff: int, /) -> int:
    __goto_label = "start"
    while True:
        try:
            if __goto_label == "start":
                if tile_x < 0:
                    return 1
                if tile_y < 0:
                    return 1
                width = world.width
                if tile_x >= width:
                    return 1
                if tile_y >= world.height:
                    return 1
                tile = world.get_tile(ivec2(tile_x, tile_y))
                if not tile or (tile.front and (tile.front & 1 == 0 and tile.flags & TileFlags.GLUED != 0)):
                    return 1
                if maybe_cave_stuff and (item_id == CAVE_DIRT and tile.front == CAVE_COLUMN):
                    return 1
                while True:
                    __switch_on0 = maybe_cave_stuff
                    _switch_matched_any0 = False
                    __matched0 = False
                    if __matched0 or __switch_on0 == 2:
                        if not __matched0 and __switch_on0 == 2:
                            _switch_matched_any0 = True
                        __matched0 = True
                        if item_id == CAVE_DIRT:
                            if tile.front == STALAGMITE:
                                return 1
                            if tile.front >= PURPLE_CAVE_CRYSTAL and tile.front <= AQUA_CAVE_CRYSTAL:
                                return 1
                            __goto_label = "LABEL_31"
                            raise Exception("__GOTO_CONTINUE__")
                        if item_id == CAVE_COLUMN:
                            if tile.front == CAVE_PLATFORM:
                                return 1
                            return tile.front == item_id
                        break
                    if __matched0 or __switch_on0 == 1:
                        if not __matched0 and __switch_on0 == 1:
                            _switch_matched_any0 = True
                        __matched0 = True
                        if item_id != CAVE_DIRT:
                            __goto_label = "LABEL_35"
                            raise Exception("__GOTO_CONTINUE__")
                        if tile.front == STALACTITE:
                            return 1
                        __goto_label = "LABEL_29"
                        raise Exception("__GOTO_CONTINUE__")
                    if __matched0 or __switch_on0 == 0:
                        if not __matched0 and __switch_on0 == 0:
                            _switch_matched_any0 = True
                        __matched0 = True
                        if item_id != CAVE_DIRT:
                            __goto_label = "LABEL_35"
                            raise Exception("__GOTO_CONTINUE__")
                        if tile.front == CAVE_PLATFORM:
                            return 1
                        __goto_label = "LABEL_29"
                        raise Exception("__GOTO_CONTINUE__")
                    break
                if item_id == CAVE_DIRT:
                    __goto_label = "LABEL_29"
                    raise Exception("__GOTO_CONTINUE__")
                if not maybe_cave_stuff and item_id == CAVE_DIRT:
                    if tile.front == CLIMBING_WALL:
                        return 1
                    return tile.front == item_id
                if item_id == STEAM_PIPE:
                    if item_database.get(tile.front).is_steam():
                        return 1
                    __goto_label = "LABEL_60"
                    raise Exception("__GOTO_CONTINUE__")
                if item_id == STONE_PAGODA:
                    if tile.front == MASTER_PENG_STONEWORK:
                        return 1
                    if tile.front == STONE_PAGODA_BASE:
                        return maybe_cave_stuff != 2
                    if (
                        maybe_cave_stuff
                        and (item_id - GUILD_FLAG_POLE_SPEAR & 4294967293 == 0 and (tile.front >= GUILD_FLAG_TATTERS and tile.front <= GUILD_FLAG_SHIELD_OPEN_DIVISION_CLOSE))
                        or (item_id == MANOR_HOUSE_SANDSTONE and tile.front == MANOR_HOUSE_SANDSTONE_STEPS)
                    ):
                        return 1
                    if maybe_cave_stuff == 2:
                        while True:
                            __switch_on1 = item_id
                            _switch_matched_any1 = False
                            __matched1 = False
                            if __matched1 or __switch_on1 == 8934:
                                if not __matched1 and __switch_on1 == 8934:
                                    _switch_matched_any1 = True
                                __matched1 = True
                                if tile.front == WEEPING_WILLOW_FOLIAGE:
                                    return 1
                                return tile.front == item_id
                            if __matched1 or __switch_on1 == 9308:
                                if not __matched1 and __switch_on1 == 9308:
                                    _switch_matched_any1 = True
                                __matched1 = True
                                if tile.front == LOVEWILLOW:
                                    return 1
                                return tile.front == item_id
                            if __matched1 or __switch_on1 == 8344:
                                if not __matched1 and __switch_on1 == 8344:
                                    _switch_matched_any1 = True
                                __matched1 = True
                                if tile.front == BONE_CHECKPOINT:
                                    return 1
                                return tile.front == item_id
                            break
                    while True:
                        __switch_on2 = item_id
                        _switch_matched_any2 = False
                        __matched2 = False
                        if __matched2 or __switch_on2 == 9384:
                            if not __matched2 and __switch_on2 == 9384:
                                _switch_matched_any2 = True
                            __matched2 = True
                            if tile.front != PURE_MAGIC_ORE:
                                if tile.front == MAGIC_INFUSED_STONE:
                                    return 1
                                return tile.front == item_id
                            return 1
                        if __matched2 or __switch_on2 == 9380:
                            if not __matched2 and __switch_on2 == 9380:
                                _switch_matched_any2 = True
                            __matched2 = True
                            if tile.front == PURE_MAGIC_ORE:
                                return 1
                            break
                        if __matched2 or __switch_on2 == 9386:
                            if not __matched2 and __switch_on2 == 9386:
                                _switch_matched_any2 = True
                            __matched2 = True
                            if tile.front == MAGIC_INFUSED_STONE:
                                return 1
                            break
                        if __matched2 or not _switch_matched_any2:
                            __matched2 = True
                            if item_id == 10596 and tile.front == GREAT_TURRET_OF_GROWTOPIA:
                                return 1
                            return tile.front == item_id
                        break
                    if tile.front == MAGIC_INFUSED_VEIN:
                        return 1
                    return tile.front == item_id
                if item_id != 4202:
                    while True:
                        __switch_on3 = item_id
                        _switch_matched_any3 = False
                        __matched3 = False
                        if __matched3 or __switch_on3 == 8:
                            if not __matched3 and __switch_on3 == 8:
                                _switch_matched_any3 = True
                            __matched3 = True
                            if tile.front == DATA_BEDROCK:
                                return 1
                            break
                        if __matched3 or __switch_on3 == 3760:
                            if not __matched3 and __switch_on3 == 3760:
                                _switch_matched_any3 = True
                            __matched3 = True
                            if tile.front == BEDROCK:
                                return 1
                            if tile.front == MONOCHROMATIC_BEDROCK:
                                return 1
                            break
                        if __matched3 or __switch_on3 == 7372:
                            if not __matched3 and __switch_on3 == 7372:
                                _switch_matched_any3 = True
                            __matched3 = True
                            if tile.front == DATA_BEDROCK:
                                return 1
                            break
                        if __matched3 or __switch_on3 == 4702:
                            if not __matched3 and __switch_on3 == 4702:
                                _switch_matched_any3 = True
                            __matched3 = True
                            if tile.front == MYSTERY_DOOR:
                                return 1
                            break
                        if __matched3 or not _switch_matched_any3:
                            __matched3 = True
                            if item_id == 2 and tile.front == FISSURE:
                                return 1
                        break
                    __goto_label = "LABEL_60"
                    raise Exception("__GOTO_CONTINUE__")
                if tile.front != STONE_PAGODA_BASE:
                    __goto_label = "LABEL_60"
                    raise Exception("__GOTO_CONTINUE__")
                return maybe_cave_stuff == 0
            elif __goto_label == "LABEL_29":
                assert tile
                if tile.front >= PURPLE_CAVE_CRYSTAL and tile.front <= AQUA_CAVE_CRYSTAL:
                    return 1
                __goto_label = "LABEL_31"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_31":
                if not maybe_cave_stuff and item_id == CAVE_DIRT:
                    assert tile
                    if tile.front == CLIMBING_WALL:
                        return 1
                    return tile.front == item_id
                __goto_label = "LABEL_35"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_35":
                if item_id == STEAM_PIPE:
                    assert tile
                    if item_database.get(tile.front).is_steam():
                        return 1
                    __goto_label = "LABEL_60"
                    raise Exception("__GOTO_CONTINUE__")
                __goto_label = "LABEL_60"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_60":
                assert tile
                if (
                    maybe_cave_stuff
                    and (item_id - GUILD_FLAG_POLE_SPEAR & 4294967293 == 0 and (tile.front >= GUILD_FLAG_TATTERS and tile.front <= GUILD_FLAG_SHIELD_OPEN_DIVISION_CLOSE))
                    or (item_id == MANOR_HOUSE_SANDSTONE and tile.front == MANOR_HOUSE_SANDSTONE_STEPS)
                ):
                    return 1
                if maybe_cave_stuff == 2:
                    while True:
                        __switch_on1 = item_id
                        _switch_matched_any1 = False
                        __matched1 = False
                        if __matched1 or __switch_on1 == 8934:
                            if not __matched1 and __switch_on1 == 8934:
                                _switch_matched_any1 = True
                            __matched1 = True
                            if tile.front == WEEPING_WILLOW_FOLIAGE:
                                return 1
                            return tile.front == item_id
                        if __matched1 or __switch_on1 == 9308:
                            if not __matched1 and __switch_on1 == 9308:
                                _switch_matched_any1 = True
                            __matched1 = True
                            if tile.front == LOVEWILLOW:
                                return 1
                            return tile.front == item_id
                        if __matched1 or __switch_on1 == 8344:
                            if not __matched1 and __switch_on1 == 8344:
                                _switch_matched_any1 = True
                            __matched1 = True
                            if tile.front == BONE_CHECKPOINT:
                                return 1
                            return tile.front == item_id
                        break
                while True:
                    __switch_on2 = item_id
                    _switch_matched_any2 = False
                    __matched2 = False
                    if __matched2 or __switch_on2 == 9384:
                        if not __matched2 and __switch_on2 == 9384:
                            _switch_matched_any2 = True
                        __matched2 = True
                        if tile.front != PURE_MAGIC_ORE:
                            if tile.front == MAGIC_INFUSED_STONE:
                                return 1
                            return tile.front == item_id
                        return 1
                    if __matched2 or __switch_on2 == 9380:
                        if not __matched2 and __switch_on2 == 9380:
                            _switch_matched_any2 = True
                        __matched2 = True
                        if tile.front == PURE_MAGIC_ORE:
                            return 1
                        break
                    if __matched2 or __switch_on2 == 9386:
                        if not __matched2 and __switch_on2 == 9386:
                            _switch_matched_any2 = True
                        __matched2 = True
                        if tile.front == MAGIC_INFUSED_STONE:
                            return 1
                        break
                    if __matched2 or not _switch_matched_any2:
                        __matched2 = True
                        if item_id == 10596 and tile.front == GREAT_TURRET_OF_GROWTOPIA:
                            return 1
                        return tile.front == item_id
                    break
                if tile.front == MAGIC_INFUSED_VEIN:
                    return 1
                return tile.front == item_id
            else:
                raise Exception("__GOTO_BREAK__")
        except Exception as __goto_except:
            if "__GOTO_CONTINUE__" in str(__goto_except):
                continue
            if "__GOTO_BREAK__" in str(__goto_except):
                break
            raise __goto_except
    assert False


def is_steam_or_something(a1: World, tile_x: int, tile_y: int, /) -> int:
    if tile_x < 0:
        return 0
    if tile_y < 0:
        return 0
    width = a1.width
    if tile_x >= width:
        return 0
    if tile_y >= a1.height:
        return 0
    v5 = a1.get_tile(ivec2(tile_x, tile_y))
    if not v5:
        return 0
    if v5 and (v5.front & 1 == 0 and v5.flags & TileFlags.GLUED != 0):
        return 1
    #   return isTileSteamType(v5) && *(_DWORD *)&v5->field_B[2] == 1 && getForegroundOrBackgroundId(v5) != STEAM_LAUNCHER;
    return item_database.get(v5.front).is_steam() and v5.front != STEAM_LAUNCHER


def handle_smart_edge_texture(world: World, tile: Tile, a3: int, /) -> int:
    __goto_label = "start"
    while True:
        try:
            if __goto_label == "start":
                tile_x = tile.pos.x
                v4 = 0
                tile_y = tile.pos.y
                v68 = tile_x
                tile_y_1 = tile_y
                if a3 == 1:
                    width = world.width
                    v9 = tile_x + 1
                    bg = tile.bg_id
                    if tile_x + 1 >= width:
                        __goto_label = "LABEL_10"
                        raise Exception("__GOTO_CONTINUE__")
                    if tile_y >= world.height:
                        __goto_label = "LABEL_10"
                        raise Exception("__GOTO_CONTINUE__")
                    v11 = world.get_tile(tile_x + (1 + tile_y * width))
                    if not v11:
                        __goto_label = "LABEL_10"
                        raise Exception("__GOTO_CONTINUE__")
                    v12 = v11.bg
                    if v12:
                        if v11.flags & TileFlags.GLUED != 0:
                            __goto_label = "LABEL_10"
                            raise Exception("__GOTO_CONTINUE__")
                    if bg == 8930:
                        v13 = v12 == WEEPING_WILLOW
                    else:
                        if bg != 1194:
                            if bg == 3556 and v12 == DWARVEN_BACKGROUND:
                                __goto_label = "LABEL_10"
                                raise Exception("__GOTO_CONTINUE__")
                            __goto_label = "LABEL_30"
                            raise Exception("__GOTO_CONTINUE__")
                        v13 = v12 == TWISTED_WINDOWS
                    if v13:
                        v14 = 1
                        v15 = tile_y + 1
                        if v9 >= width:
                            __goto_label = "LABEL_19"
                            raise Exception("__GOTO_CONTINUE__")
                        if v15 >= world.height:
                            __goto_label = "LABEL_19"
                            raise Exception("__GOTO_CONTINUE__")
                        v16 = world.get_tile(tile_x + (1 + v15 * width))
                        if not v16:
                            __goto_label = "LABEL_19"
                            raise Exception("__GOTO_CONTINUE__")
                        v17 = v16.bg
                        if v17:
                            if v16.flags & 2048 != 0:
                                __goto_label = "LABEL_19"
                                raise Exception("__GOTO_CONTINUE__")
                        if bg == 8930:
                            v18 = v17 == WEEPING_WILLOW
                        else:
                            if bg != 1194:
                                if bg == 3556 and v17 == DWARVEN_BACKGROUND:
                                    __goto_label = "LABEL_19"
                                    raise Exception("__GOTO_CONTINUE__")
                                __goto_label = "LABEL_35"
                                raise Exception("__GOTO_CONTINUE__")
                            v18 = v17 == TWISTED_WINDOWS
                        if v18:
                            v19 = 1
                            v70 = v19
                            if tile_x >= width:
                                __goto_label = "LABEL_39"
                                raise Exception("__GOTO_CONTINUE__")
                            if v15 >= world.height:
                                __goto_label = "LABEL_39"
                                raise Exception("__GOTO_CONTINUE__")
                            v20 = world.get_tile(tile_x + v15 * width)
                            if not v20:
                                __goto_label = "LABEL_39"
                                raise Exception("__GOTO_CONTINUE__")
                            v21 = v20.bg
                            if v21 and v20.flags & 2048 != 0:
                                v73 = 1
                                v24 = tile_x - 1
                                if tile_x - 1 < 0:
                                    __goto_label = "LABEL_50"
                                    raise Exception("__GOTO_CONTINUE__")
                                if v24 >= width:
                                    __goto_label = "LABEL_50"
                                    raise Exception("__GOTO_CONTINUE__")
                                if v15 >= world.height:
                                    __goto_label = "LABEL_50"
                                    raise Exception("__GOTO_CONTINUE__")
                                v25 = world.get_tile(v24 + v15 * width)
                                if not v25:
                                    __goto_label = "LABEL_50"
                                    raise Exception("__GOTO_CONTINUE__")
                                v26 = v25.bg
                                if v26:
                                    if v25.flags & 2048 != 0:
                                        __goto_label = "LABEL_50"
                                        raise Exception("__GOTO_CONTINUE__")
                                if bg == 8930:
                                    v27 = v26 == WEEPING_WILLOW
                                else:
                                    if bg != 1194:
                                        if bg == 3556 and v26 == DWARVEN_BACKGROUND:
                                            __goto_label = "LABEL_50"
                                            raise Exception("__GOTO_CONTINUE__")
                                        __goto_label = "LABEL_90"
                                        raise Exception("__GOTO_CONTINUE__")
                                    v27 = v26 == TWISTED_WINDOWS
                                if v27:
                                    south_west_tile = 1
                                    if v24 < 0:
                                        __goto_label = "LABEL_60"
                                        raise Exception("__GOTO_CONTINUE__")
                                    if v24 >= width:
                                        __goto_label = "LABEL_60"
                                        raise Exception("__GOTO_CONTINUE__")
                                    if tile_y >= world.height:
                                        __goto_label = "LABEL_60"
                                        raise Exception("__GOTO_CONTINUE__")
                                    v29 = world.get_tile(v24 + tile_y * width)
                                    if not v29:
                                        __goto_label = "LABEL_60"
                                        raise Exception("__GOTO_CONTINUE__")
                                    v30 = v29.bg
                                    if v30:
                                        if v29.flags & 2048 != 0:
                                            __goto_label = "LABEL_60"
                                            raise Exception("__GOTO_CONTINUE__")
                                    if bg == 8930:
                                        v31 = v30 == WEEPING_WILLOW
                                    else:
                                        if bg != 1194:
                                            if bg == 3556 and v30 == DWARVEN_BACKGROUND:
                                                __goto_label = "LABEL_60"
                                                raise Exception("__GOTO_CONTINUE__")
                                            __goto_label = "LABEL_95"
                                            raise Exception("__GOTO_CONTINUE__")
                                        v31 = v30 == TWISTED_WINDOWS
                                    if v31:
                                        west_tile = 1
                                        v33 = tile_y_1 - 1
                                        if v24 < 0:
                                            __goto_label = "LABEL_71"
                                            raise Exception("__GOTO_CONTINUE__")
                                        if v33 < 0:
                                            __goto_label = "LABEL_71"
                                            raise Exception("__GOTO_CONTINUE__")
                                        if v24 >= width:
                                            __goto_label = "LABEL_71"
                                            raise Exception("__GOTO_CONTINUE__")
                                        if v33 >= world.height:
                                            __goto_label = "LABEL_71"
                                            raise Exception("__GOTO_CONTINUE__")
                                        v34 = world.get_tile(v24 + v33 * width)
                                        if not v34:
                                            __goto_label = "LABEL_71"
                                            raise Exception("__GOTO_CONTINUE__")
                                        v35 = v34.bg
                                        if v35:
                                            if v34.flags & 2048 != 0:
                                                __goto_label = "LABEL_71"
                                                raise Exception("__GOTO_CONTINUE__")
                                        if bg == 8930:
                                            v36 = v35 == WEEPING_WILLOW
                                        else:
                                            if bg != 1194:
                                                if bg == 3556 and v35 == DWARVEN_BACKGROUND:
                                                    __goto_label = "LABEL_71"
                                                    raise Exception("__GOTO_CONTINUE__")
                                                __goto_label = "LABEL_100"
                                                raise Exception("__GOTO_CONTINUE__")
                                            v36 = v35 == TWISTED_WINDOWS
                                        if v36:
                                            north_west_tile = 1
                                            if v33 < 0:
                                                __goto_label = "LABEL_107"
                                                raise Exception("__GOTO_CONTINUE__")
                                            if tile_x >= width:
                                                __goto_label = "LABEL_107"
                                                raise Exception("__GOTO_CONTINUE__")
                                            if v33 >= world.height:
                                                __goto_label = "LABEL_107"
                                                raise Exception("__GOTO_CONTINUE__")
                                            v38 = world.get_tile(tile_x + v33 * width)
                                            if not v38:
                                                __goto_label = "LABEL_107"
                                                raise Exception("__GOTO_CONTINUE__")
                                            v39 = v38.bg
                                            if v39:
                                                if v38.flags & 2048 != 0:
                                                    __goto_label = "LABEL_107"
                                                    raise Exception("__GOTO_CONTINUE__")
                                            if bg == 8930:
                                                if v39 == WEEPING_WILLOW:
                                                    north_tile = 1
                                                    __goto_label = "LABEL_108"
                                                    raise Exception("__GOTO_CONTINUE__")
                                            elif bg == 1194:
                                                if v39 == TWISTED_WINDOWS:
                                                    __goto_label = "LABEL_107"
                                                    raise Exception("__GOTO_CONTINUE__")
                                            elif bg == 3556 and v39 == DWARVEN_BACKGROUND:
                                                __goto_label = "LABEL_107"
                                                raise Exception("__GOTO_CONTINUE__")
                                            north_tile = v39 == bg
                                            if v33 < 0:
                                                __goto_label = "LABEL_117"
                                                raise Exception("__GOTO_CONTINUE__")
                                            if v9 >= width:
                                                __goto_label = "LABEL_117"
                                                raise Exception("__GOTO_CONTINUE__")
                                            if v33 >= world.height:
                                                __goto_label = "LABEL_117"
                                                raise Exception("__GOTO_CONTINUE__")
                                            v41 = world.get_tile(width * v33 + (1 + v68))
                                            if not v41:
                                                __goto_label = "LABEL_117"
                                                raise Exception("__GOTO_CONTINUE__")
                                            v42 = v41.bg
                                            if v42:
                                                if v41.flags & 2048 != 0:
                                                    __goto_label = "LABEL_117"
                                                    raise Exception("__GOTO_CONTINUE__")
                                            if bg == 8930:
                                                v43 = v42 == WEEPING_WILLOW
                                            else:
                                                if bg != 1194:
                                                    if bg == 3556 and v42 == DWARVEN_BACKGROUND:
                                                        __goto_label = "LABEL_117"
                                                        raise Exception("__GOTO_CONTINUE__")
                                                    v47 = v42
                                                    south_east_tile_1 = v70
                                                    v13 = v47 == bg
                                                    south_tile_1 = v73
                                                    north_east_tile = v13
                                                    __goto_label = "LABEL_128"
                                                    raise Exception("__GOTO_CONTINUE__")
                                                v43 = v42 == TWISTED_WINDOWS
                                            if v43:
                                                south_east_tile_1 = v70
                                                north_east_tile = 1
                                                south_tile_1 = v73
                                                __goto_label = "LABEL_128"
                                                raise Exception("__GOTO_CONTINUE__")
                                            __goto_label = "LABEL_122"
                                            raise Exception("__GOTO_CONTINUE__")
                                        north_west_tile = v35 == bg
                                        __goto_label = "LABEL_72"
                                        raise Exception("__GOTO_CONTINUE__")
                                    west_tile = v30 == bg
                                    __goto_label = "LABEL_61"
                                    raise Exception("__GOTO_CONTINUE__")
                                south_west_tile = v26 == bg
                                __goto_label = "LABEL_51"
                                raise Exception("__GOTO_CONTINUE__")
                            if bg == 8930:
                                v22 = v21 == WEEPING_WILLOW
                            else:
                                if bg != 1194:
                                    if bg == 3556 and v21 == DWARVEN_BACKGROUND:
                                        __goto_label = "LABEL_39"
                                        raise Exception("__GOTO_CONTINUE__")
                                    __goto_label = "LABEL_85"
                                    raise Exception("__GOTO_CONTINUE__")
                                v22 = v21 == TWISTED_WINDOWS
                            if v22:
                                v23 = 1
                                v73 = v23
                                __goto_label = "LABEL_41"
                                raise Exception("__GOTO_CONTINUE__")
                            v23 = v21 == bg
                            __goto_label = "LABEL_40"
                            raise Exception("__GOTO_CONTINUE__")
                        v19 = v17 == bg
                        __goto_label = "LABEL_20"
                        raise Exception("__GOTO_CONTINUE__")
                    v14 = v12 == bg
                    __goto_label = "LABEL_11"
                    raise Exception("__GOTO_CONTINUE__")
                if a3:
                    if a3 == 2:
                        v57 = tile_x + 1
                        east_tile = is_steam_or_something(world, tile_x + 1, tile.pos.y)
                        v72 = is_steam_or_something(world, tile_x + 1, tile_y + 1)
                        v75 = is_steam_or_something(world, tile_x, tile_y + 1)
                        south_west_tile = is_steam_or_something(world, tile_x - 1, tile_y + 1)
                        west_tile = is_steam_or_something(world, tile_x - 1, tile_y)
                        north_west_tile = is_steam_or_something(world, tile_x - 1, tile_y_1 - 1)
                        north_tile = is_steam_or_something(world, tile_x, tile_y_1 - 1)
                        north_east_tile = is_steam_or_something(world, v57, tile_y_1 - 1)
                        south_east_tile_1 = v72
                        south_tile_1 = v75
                        v14 = east_tile
                    else:
                        # north_east_tile = HIBYTE(tile)
                        # north_tile = BYTE6(tile)
                        # north_west_tile = BYTE5(tile)
                        # west_tile = BYTE4(tile)
                        # south_west_tile = BYTE3(tile)
                        # south_tile_1 = BYTE2(tile)
                        # south_east_tile_1 = BYTE1(tile)
                        north_east_tile = bool(tile)
                        north_tile = bool(tile)
                        north_west_tile = bool(tile)
                        west_tile = bool(tile)
                        south_west_tile = bool(tile)
                        south_tile_1 = bool(tile)
                        south_east_tile_1 = bool(tile)
                        v14 = bool(tile)
                else:
                    tile_x__plus__one = tile_x + 1
                    foreground_or_background_id = tile.front
                    east_tile_1 = tile_should_connect(world, tile_x + 1, tile_y, foreground_or_background_id, 0)
                    v50 = tile.front
                    south_east_tile = tile_should_connect(world, tile_x + 1, tile_y + 1, v50, 0)
                    v51 = tile.front
                    south_tile = tile_should_connect(world, tile_x, tile_y + 1, v51, 0)
                    v52 = tile.front
                    south_west_tile = tile_should_connect(world, tile_x - 1, tile_y + 1, v52, 0)
                    v53 = tile.front
                    west_tile = tile_should_connect(world, tile_x - 1, tile_y, v53, 0)
                    v54 = tile.front
                    north_west_tile = tile_should_connect(world, tile_x - 1, tile_y_1 - 1, v54, 0)
                    v55 = tile.front
                    north_tile = tile_should_connect(world, tile_x, tile_y_1 - 1, v55, 0)
                    v56 = tile.front
                    north_east_tile = tile_should_connect(world, tile_x__plus__one, tile_y_1 - 1, v56, 0)
                    south_east_tile_1 = south_east_tile
                    south_tile_1 = south_tile
                    v14 = east_tile_1
                if not v14:
                    __goto_label = "LABEL_195"
                    raise Exception("__GOTO_CONTINUE__")
                if not south_tile_1:
                    if west_tile and north_tile:
                        if north_west_tile:
                            if north_east_tile:
                                return 2
                            else:
                                return 41
                        elif north_east_tile:
                            return 40
                        else:
                            return 42
                    __goto_label = "LABEL_186"
                    raise Exception("__GOTO_CONTINUE__")
                if not west_tile:
                    if not south_tile_1:
                        if v14:
                            if south_tile_1:
                                v61 = 45
                                if south_east_tile_1:
                                    return 5
                                return v61
                            elif west_tile:
                                return 28
                            elif north_tile:
                                v62 = 43
                                if north_east_tile:
                                    return 7
                                return v62
                            else:
                                return 29
                        elif south_tile_1:
                            if west_tile:
                                v63 = 46
                                if south_west_tile:
                                    return 6
                                return v63
                            elif north_tile:
                                return 9
                            else:
                                return 10
                        else:
                            if not west_tile:
                                return 12 - (north_tile != 0)
                            if north_tile:
                                v64 = 44
                                if north_west_tile:
                                    return 8
                                return v64
                            else:
                                return 30
                    if north_tile:
                        if north_east_tile:
                            if south_east_tile_1:
                                return 3
                            else:
                                return 32
                        elif south_east_tile_1:
                            return 31
                        else:
                            return 33
                    if south_tile_1 and (west_tile and north_tile):
                        if north_west_tile:
                            if south_west_tile:
                                return 4
                            else:
                                return 35
                        elif south_west_tile:
                            return 34
                        else:
                            return 36
                    __goto_label = "LABEL_205"
                    raise Exception("__GOTO_CONTINUE__")
                if north_tile:
                    if south_east_tile_1:
                        if south_west_tile:
                            if north_west_tile:
                                if not north_east_tile:
                                    return 14
                                return v4
                            if north_east_tile:
                                return 13
                        if north_west_tile and north_east_tile:
                            return 15
                    if south_west_tile and (north_west_tile and north_east_tile):
                        return 16
                    if south_east_tile_1:
                        if south_west_tile:
                            return 17
                    elif south_west_tile:
                        if north_west_tile:
                            return 20
                        if south_west_tile and north_east_tile:
                            return 21
                        if south_east_tile_1:
                            return 26
                        if south_west_tile:
                            return 25
                        if north_west_tile:
                            return 23
                        v59 = 27
                        if north_east_tile:
                            return 24
                        return v59
                    if north_west_tile and north_east_tile:
                        return 18
                    if south_east_tile_1:
                        if north_east_tile:
                            return 19
                        if north_west_tile:
                            return 22
                    __goto_label = "LABEL_160"
                    raise Exception("__GOTO_CONTINUE__")
                if not south_east_tile_1:
                    return 39 - (south_west_tile != 0)
                v60 = 37
                if south_west_tile:
                    return 1
                return v60
            elif __goto_label == "LABEL_10":
                v14 = 1
                __goto_label = "LABEL_11"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_100":
                north_west_tile = v35 == bg
                __goto_label = "LABEL_72"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_107":
                north_tile = 1
                __goto_label = "LABEL_108"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_108":
                if v33 < 0:
                    __goto_label = "LABEL_117"
                    raise Exception("__GOTO_CONTINUE__")
                if v9 >= width:
                    __goto_label = "LABEL_117"
                    raise Exception("__GOTO_CONTINUE__")
                if v33 >= world.height:
                    __goto_label = "LABEL_117"
                    raise Exception("__GOTO_CONTINUE__")
                v41 = world.get_tile(width * v33 + (1 + v68))
                if not v41:
                    __goto_label = "LABEL_117"
                    raise Exception("__GOTO_CONTINUE__")
                v42 = v41.bg
                if v42:
                    if v41.flags & 2048 != 0:
                        __goto_label = "LABEL_117"
                        raise Exception("__GOTO_CONTINUE__")
                __goto_label = "LABEL_122"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_11":
                v15 = tile_y + 1
                if v9 >= width:
                    __goto_label = "LABEL_19"
                    raise Exception("__GOTO_CONTINUE__")
                if v15 >= world.height:
                    __goto_label = "LABEL_19"
                    raise Exception("__GOTO_CONTINUE__")
                v16 = world.get_tile(tile_x + (1 + v15 * width))
                if not v16:
                    __goto_label = "LABEL_19"
                    raise Exception("__GOTO_CONTINUE__")
                v17 = v16.bg
                if v17:
                    if v16.flags & 2048 != 0:
                        __goto_label = "LABEL_19"
                        raise Exception("__GOTO_CONTINUE__")
                if bg == 8930:
                    v18 = v17 == WEEPING_WILLOW
                else:
                    if bg != 1194:
                        if bg == 3556 and v17 == DWARVEN_BACKGROUND:
                            __goto_label = "LABEL_19"
                            raise Exception("__GOTO_CONTINUE__")
                        __goto_label = "LABEL_35"
                        raise Exception("__GOTO_CONTINUE__")
                    v18 = v17 == TWISTED_WINDOWS
                __goto_label = "LABEL_19"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_117":
                south_east_tile_1 = v70
                north_east_tile = 1
                south_tile_1 = v73
                __goto_label = "LABEL_128"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_122":
                v47 = v42
                south_east_tile_1 = v70
                v13 = v47 == bg
                south_tile_1 = v73
                north_east_tile = v13
                __goto_label = "LABEL_128"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_128":
                if not v14:
                    __goto_label = "LABEL_195"
                    raise Exception("__GOTO_CONTINUE__")
                if not south_tile_1:
                    if west_tile and north_tile:
                        if north_west_tile:
                            if north_east_tile:
                                return 2
                            else:
                                return 41
                        elif north_east_tile:
                            return 40
                        else:
                            return 42
                    __goto_label = "LABEL_186"
                    raise Exception("__GOTO_CONTINUE__")
                __goto_label = "LABEL_186"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_160":
                if south_west_tile and north_east_tile:
                    return 21
                if south_east_tile_1:
                    return 26
                if south_west_tile:
                    return 25
                if north_west_tile:
                    return 23
                v59 = 27
                if north_east_tile:
                    return 24
                return v59
            elif __goto_label == "LABEL_186":
                __goto_label = "LABEL_205"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_19":
                v19 = 1
                __goto_label = "LABEL_20"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_195":
                if south_tile_1 and (west_tile and north_tile):
                    if north_west_tile:
                        if south_west_tile:
                            return 4
                        else:
                            return 35
                    elif south_west_tile:
                        return 34
                    else:
                        return 36
                __goto_label = "LABEL_205"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_20":
                v70 = v19
                if tile_x >= width:
                    __goto_label = "LABEL_39"
                    raise Exception("__GOTO_CONTINUE__")
                if v15 >= world.height:
                    __goto_label = "LABEL_39"
                    raise Exception("__GOTO_CONTINUE__")
                v20 = world.get_tile(tile_x + v15 * width)
                if not v20:
                    __goto_label = "LABEL_39"
                    raise Exception("__GOTO_CONTINUE__")
                v21 = v20.bg
                __goto_label = "LABEL_41"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_205":
                if v14:
                    if south_tile_1:
                        v61 = 45
                        if south_east_tile_1:
                            return 5
                        return v61
                    elif west_tile:
                        return 28
                    elif north_tile:
                        v62 = 43
                        if north_east_tile:
                            return 7
                        return v62
                    else:
                        return 29
                elif south_tile_1:
                    if west_tile:
                        v63 = 46
                        if south_west_tile:
                            return 6
                        return v63
                    elif north_tile:
                        return 9
                    else:
                        return 10
                else:
                    if not west_tile:
                        return 12 - (north_tile != 0)
                    if north_tile:
                        v64 = 44
                        if north_west_tile:
                            return 8
                        return v64
                    else:
                        return 30
            elif __goto_label == "LABEL_30":
                v14 = v12 == bg
                __goto_label = "LABEL_11"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_35":
                v19 = v17 == bg
                __goto_label = "LABEL_20"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_39":
                v23 = 1
                __goto_label = "LABEL_40"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_40":
                v73 = v23
                __goto_label = "LABEL_41"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_41":
                v24 = tile_x - 1
                if tile_x - 1 < 0:
                    __goto_label = "LABEL_50"
                    raise Exception("__GOTO_CONTINUE__")
                if v24 >= width:
                    __goto_label = "LABEL_50"
                    raise Exception("__GOTO_CONTINUE__")
                if v15 >= world.height:
                    __goto_label = "LABEL_50"
                    raise Exception("__GOTO_CONTINUE__")
                v25 = world.get_tile(v24 + v15 * width)
                if not v25:
                    __goto_label = "LABEL_50"
                    raise Exception("__GOTO_CONTINUE__")
                v26 = v25.bg
                if v26:
                    if v25.flags & 2048 != 0:
                        __goto_label = "LABEL_50"
                        raise Exception("__GOTO_CONTINUE__")
                if bg == 8930:
                    v27 = v26 == WEEPING_WILLOW
                else:
                    if bg != 1194:
                        if bg == 3556 and v26 == DWARVEN_BACKGROUND:
                            __goto_label = "LABEL_50"
                            raise Exception("__GOTO_CONTINUE__")
                        __goto_label = "LABEL_90"
                        raise Exception("__GOTO_CONTINUE__")
                    v27 = v26 == TWISTED_WINDOWS
                __goto_label = "LABEL_50"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_50":
                south_west_tile = 1
                __goto_label = "LABEL_51"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_51":
                if v24 < 0:
                    __goto_label = "LABEL_60"
                    raise Exception("__GOTO_CONTINUE__")
                if v24 >= width:
                    __goto_label = "LABEL_60"
                    raise Exception("__GOTO_CONTINUE__")
                if tile_y >= world.height:
                    __goto_label = "LABEL_60"
                    raise Exception("__GOTO_CONTINUE__")
                v29 = world.get_tile(v24 + tile_y * width)
                if not v29:
                    __goto_label = "LABEL_60"
                    raise Exception("__GOTO_CONTINUE__")
                v30 = v29.bg
                if v30:
                    if v29.flags & 2048 != 0:
                        __goto_label = "LABEL_60"
                        raise Exception("__GOTO_CONTINUE__")
                if bg == 8930:
                    v31 = v30 == WEEPING_WILLOW
                else:
                    if bg != 1194:
                        if bg == 3556 and v30 == DWARVEN_BACKGROUND:
                            __goto_label = "LABEL_60"
                            raise Exception("__GOTO_CONTINUE__")
                        __goto_label = "LABEL_95"
                        raise Exception("__GOTO_CONTINUE__")
                    v31 = v30 == TWISTED_WINDOWS
                __goto_label = "LABEL_60"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_60":
                west_tile = 1
                __goto_label = "LABEL_61"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_61":
                v33 = tile_y_1 - 1
                if v24 < 0:
                    __goto_label = "LABEL_71"
                    raise Exception("__GOTO_CONTINUE__")
                if v33 < 0:
                    __goto_label = "LABEL_71"
                    raise Exception("__GOTO_CONTINUE__")
                if v24 >= width:
                    __goto_label = "LABEL_71"
                    raise Exception("__GOTO_CONTINUE__")
                if v33 >= world.height:
                    __goto_label = "LABEL_71"
                    raise Exception("__GOTO_CONTINUE__")
                v34 = world.get_tile(v24 + v33 * width)
                if not v34:
                    __goto_label = "LABEL_71"
                    raise Exception("__GOTO_CONTINUE__")
                v35 = v34.bg
                if v35:
                    if v34.flags & 2048 != 0:
                        __goto_label = "LABEL_71"
                        raise Exception("__GOTO_CONTINUE__")
                if bg == 8930:
                    v36 = v35 == WEEPING_WILLOW
                else:
                    if bg != 1194:
                        if bg == 3556 and v35 == DWARVEN_BACKGROUND:
                            __goto_label = "LABEL_71"
                            raise Exception("__GOTO_CONTINUE__")
                        __goto_label = "LABEL_100"
                        raise Exception("__GOTO_CONTINUE__")
                    v36 = v35 == TWISTED_WINDOWS
                __goto_label = "LABEL_71"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_71":
                north_west_tile = 1
                __goto_label = "LABEL_72"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_72":
                if v33 < 0:
                    __goto_label = "LABEL_107"
                    raise Exception("__GOTO_CONTINUE__")
                if tile_x >= width:
                    __goto_label = "LABEL_107"
                    raise Exception("__GOTO_CONTINUE__")
                if v33 >= world.height:
                    __goto_label = "LABEL_107"
                    raise Exception("__GOTO_CONTINUE__")
                v38 = world.get_tile(tile_x + v33 * width)
                if not v38:
                    __goto_label = "LABEL_107"
                    raise Exception("__GOTO_CONTINUE__")
                v39 = v38.bg
                if v39:
                    if v38.flags & 2048 != 0:
                        __goto_label = "LABEL_107"
                        raise Exception("__GOTO_CONTINUE__")
                __goto_label = "LABEL_107"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_85":
                v23 = v21 == bg
                __goto_label = "LABEL_40"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_90":
                south_west_tile = v26 == bg
                __goto_label = "LABEL_51"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_95":
                west_tile = v30 == bg
                __goto_label = "LABEL_61"
                raise Exception("__GOTO_CONTINUE__")
            else:
                raise Exception("__GOTO_BREAK__")
        except Exception as __goto_except:
            if "__GOTO_CONTINUE__" in str(__goto_except):
                continue
            if "__GOTO_BREAK__" in str(__goto_except):
                break
            raise __goto_except
    assert False


def handle_cling2_texture(a1: World, a2: Tile, a3: int, /) -> int:
    __goto_label = "start"
    while True:
        try:
            if __goto_label == "start":
                v3 = 0
                tile_y = a2.pos.y
                tile_x = a2.pos.x
                if not a3:
                    foreground_or_background_id = a2.front
                    east_tile = tile_should_connect(a1, tile_x + 1, tile_y, foreground_or_background_id, 0)
                    v28 = a2.front
                    south_tile = tile_should_connect(a1, tile_x, tile_y + 1, v28, 1)
                    v29 = a2.front
                    west_tile = tile_should_connect(a1, tile_x - 1, tile_y, v29, 0)
                    v30 = a2.front
                    north_tile = tile_should_connect(a1, tile_x, tile_y - 1, v30, 2)
                    __goto_label = "LABEL_59"
                    raise Exception("__GOTO_CONTINUE__")
                width = a1.width
                bg = a2.bg_id
                if tile_x + 1 >= width:
                    __goto_label = "LABEL_10"
                    raise Exception("__GOTO_CONTINUE__")
                if tile_y >= a1.height:
                    __goto_label = "LABEL_10"
                    raise Exception("__GOTO_CONTINUE__")
                v10 = a1.get_tile(ivec2(tile_x, tile_y))
                if not v10:
                    __goto_label = "LABEL_10"
                    raise Exception("__GOTO_CONTINUE__")
                v11 = v10.bg_id
                if v11:
                    if v10.flags & 2048 != 0:
                        __goto_label = "LABEL_10"
                        raise Exception("__GOTO_CONTINUE__")
                if bg == 8930:
                    v12 = v11 == WEEPING_WILLOW
                else:
                    if bg != 1194:
                        if bg == 3556 and v11 == DWARVEN_BACKGROUND:
                            __goto_label = "LABEL_10"
                            raise Exception("__GOTO_CONTINUE__")
                        east_tile = v11 == bg
                        __goto_label = "LABEL_11"
                        raise Exception("__GOTO_CONTINUE__")
                    v12 = v11 == TWISTED_WINDOWS
                if not v12:
                    __goto_label = "LABEL_40"
                    raise Exception("__GOTO_CONTINUE__")
                east_tile = 1
                v14 = tile_y + 1
                if tile_x >= width:
                    __goto_label = "LABEL_18"
                    raise Exception("__GOTO_CONTINUE__")
                if v14 >= a1.height:
                    __goto_label = "LABEL_18"
                    raise Exception("__GOTO_CONTINUE__")
                v15 = a1.get_tile(ivec2(tile_x, tile_y))
                if not v15:
                    __goto_label = "LABEL_18"
                    raise Exception("__GOTO_CONTINUE__")
                v16 = v15.bg_id
                if v16:
                    if v15.flags & 2048 != 0:
                        __goto_label = "LABEL_18"
                        raise Exception("__GOTO_CONTINUE__")
                if bg != 1194:
                    if bg == 3556 and v16 == DWARVEN_BACKGROUND:
                        __goto_label = "LABEL_18"
                        raise Exception("__GOTO_CONTINUE__")
                    __goto_label = "LABEL_43"
                    raise Exception("__GOTO_CONTINUE__")
                if v16 != TWISTED_WINDOWS:
                    __goto_label = "LABEL_43"
                    raise Exception("__GOTO_CONTINUE__")
                south_tile = 1
                v18 = tile_x - 1
                if tile_x - 1 < 0:
                    __goto_label = "LABEL_28"
                    raise Exception("__GOTO_CONTINUE__")
                if v18 >= width:
                    __goto_label = "LABEL_28"
                    raise Exception("__GOTO_CONTINUE__")
                if tile_y >= a1.height:
                    __goto_label = "LABEL_28"
                    raise Exception("__GOTO_CONTINUE__")
                v19 = a1.get_tile(ivec2(tile_x, tile_y))
                if not v19:
                    __goto_label = "LABEL_28"
                    raise Exception("__GOTO_CONTINUE__")
                v20 = v19.bg_id
                if v20:
                    if v19.flags & 2048 != 0:
                        __goto_label = "LABEL_28"
                        raise Exception("__GOTO_CONTINUE__")
                if bg == 8930:
                    v21 = v20 == WEEPING_WILLOW
                else:
                    if bg != 1194:
                        if bg == 3556 and v20 == DWARVEN_BACKGROUND:
                            __goto_label = "LABEL_28"
                            raise Exception("__GOTO_CONTINUE__")
                        __goto_label = "LABEL_48"
                        raise Exception("__GOTO_CONTINUE__")
                    v21 = v20 == TWISTED_WINDOWS
                if v21:
                    __goto_label = "LABEL_28"
                    raise Exception("__GOTO_CONTINUE__")
                west_tile = v20 == bg
                v23 = tile_y - 1
                if v23 < 0 or (
                    tile_x >= width or (v23 >= a1.height or ((v24 := a1.get_tile(ivec2(tile_x, tile_y))) == None or ((v25 := v24.bg_id) != BLANK and v24.flags & 2048 != 0)))
                ):
                    north_tile = 1
                    __goto_label = "LABEL_59"
                    raise Exception("__GOTO_CONTINUE__")
                if bg == 1194:
                    if v25 == TWISTED_ROOF:
                        north_tile = 1
                        __goto_label = "LABEL_59"
                        raise Exception("__GOTO_CONTINUE__")
                    if v25 == TWISTED_WINDOWS:
                        north_tile = 1
                        __goto_label = "LABEL_59"
                        raise Exception("__GOTO_CONTINUE__")
                elif bg == 3556 and v25 == DWARVEN_BACKGROUND:
                    north_tile = 1
                    __goto_label = "LABEL_59"
                    raise Exception("__GOTO_CONTINUE__")
                north_tile = v25 == bg
                if not east_tile:
                    __goto_label = "LABEL_70"
                    raise Exception("__GOTO_CONTINUE__")
                if south_tile:
                    if west_tile:
                        if not north_tile:
                            return 1
                        return v3
                elif west_tile and north_tile:
                    return 2
                if south_tile:
                    if north_tile:
                        return 3
                    __goto_label = "LABEL_70"
                    raise Exception("__GOTO_CONTINUE__")
                if east_tile:
                    if south_tile:
                        return 5
                    elif west_tile:
                        return 13
                    elif north_tile:
                        return 7
                    else:
                        return 14
                elif south_tile:
                    if west_tile:
                        return 6
                    elif north_tile:
                        return 9
                    else:
                        return 10
                else:
                    if not west_tile:
                        return 12 - north_tile
                    if north_tile:
                        return 8
                    else:
                        return 15
            elif __goto_label == "LABEL_10":
                east_tile = 1
                __goto_label = "LABEL_11"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_11":
                v14 = tile_y + 1
                assert tile_x and width
                if tile_x >= width:
                    __goto_label = "LABEL_18"
                    raise Exception("__GOTO_CONTINUE__")
                if v14 >= a1.height:
                    __goto_label = "LABEL_18"
                    raise Exception("__GOTO_CONTINUE__")
                v15 = a1.get_tile(ivec2(tile_x, tile_y))
                if not v15:
                    __goto_label = "LABEL_18"
                    raise Exception("__GOTO_CONTINUE__")
                v16 = v15.bg_id
                if v16:
                    if v15.flags & 2048 != 0:
                        __goto_label = "LABEL_18"
                        raise Exception("__GOTO_CONTINUE__")
                if bg != 1194:
                    if bg == 3556 and v16 == DWARVEN_BACKGROUND:
                        __goto_label = "LABEL_18"
                        raise Exception("__GOTO_CONTINUE__")
                    __goto_label = "LABEL_43"
                    raise Exception("__GOTO_CONTINUE__")
                if v16 != TWISTED_WINDOWS:
                    __goto_label = "LABEL_43"
                    raise Exception("__GOTO_CONTINUE__")
                __goto_label = "LABEL_18"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_18":
                south_tile = 1
                __goto_label = "LABEL_19"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_19":
                v18 = tile_x - 1
                if tile_x - 1 < 0:
                    __goto_label = "LABEL_28"
                    raise Exception("__GOTO_CONTINUE__")
                if v18 >= width:
                    __goto_label = "LABEL_28"
                    raise Exception("__GOTO_CONTINUE__")
                if tile_y >= a1.height:
                    __goto_label = "LABEL_28"
                    raise Exception("__GOTO_CONTINUE__")
                v19 = a1.get_tile(ivec2(tile_x, tile_y))
                if not v19:
                    __goto_label = "LABEL_28"
                    raise Exception("__GOTO_CONTINUE__")
                v20 = v19.bg_id
                if v20:
                    if v19.flags & 2048 != 0:
                        __goto_label = "LABEL_28"
                        raise Exception("__GOTO_CONTINUE__")
                if bg == 8930:
                    v21 = v20 == WEEPING_WILLOW
                else:
                    if bg != 1194:
                        if bg == 3556 and v20 == DWARVEN_BACKGROUND:
                            __goto_label = "LABEL_28"
                            raise Exception("__GOTO_CONTINUE__")
                        __goto_label = "LABEL_48"
                        raise Exception("__GOTO_CONTINUE__")
                    v21 = v20 == TWISTED_WINDOWS
                if v21:
                    __goto_label = "LABEL_28"
                    raise Exception("__GOTO_CONTINUE__")
                __goto_label = "LABEL_48"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_28":
                west_tile = 1
                __goto_label = "LABEL_29"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_29":
                v23 = tile_y - 1
                assert tile_x and width
                if v23 < 0 or (
                    tile_x >= width or (v23 >= a1.height or ((v24 := a1.get_tile(ivec2(tile_x, tile_y))) == None or ((v25 := v24.bg_id) != BLANK and v24.flags & 2048 != 0)))
                ):
                    north_tile = 1
                    __goto_label = "LABEL_59"
                    raise Exception("__GOTO_CONTINUE__")
                if bg == 1194:
                    if v25 == TWISTED_ROOF:
                        north_tile = 1
                        __goto_label = "LABEL_59"
                        raise Exception("__GOTO_CONTINUE__")
                    if v25 == TWISTED_WINDOWS:
                        north_tile = 1
                        __goto_label = "LABEL_59"
                        raise Exception("__GOTO_CONTINUE__")
                elif bg == 3556 and v25 == DWARVEN_BACKGROUND:
                    north_tile = 1
                    __goto_label = "LABEL_59"
                    raise Exception("__GOTO_CONTINUE__")
                north_tile = v25 == bg
                __goto_label = "LABEL_59"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_40":
                assert v11
                east_tile = v11 == bg
                __goto_label = "LABEL_11"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_43":
                assert v16
                south_tile = v16 == bg
                __goto_label = "LABEL_19"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_48":
                assert v20
                west_tile = v20 == bg
                __goto_label = "LABEL_29"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_59":
                if not east_tile:
                    __goto_label = "LABEL_70"
                    raise Exception("__GOTO_CONTINUE__")
                if south_tile:
                    if west_tile:
                        if not north_tile:
                            return 1
                        return v3
                elif west_tile and north_tile:
                    return 2
                if south_tile:
                    if north_tile:
                        return 3
                    __goto_label = "LABEL_70"
                    raise Exception("__GOTO_CONTINUE__")
                if east_tile:
                    if south_tile:
                        return 5
                    elif west_tile:
                        return 13
                    elif north_tile:
                        return 7
                    else:
                        return 14
                elif south_tile:
                    if west_tile:
                        return 6
                    elif north_tile:
                        return 9
                    else:
                        return 10
                else:
                    if not west_tile:
                        return 12 - north_tile
                    if north_tile:
                        return 8
                    else:
                        return 15
            elif __goto_label == "LABEL_70":
                if south_tile and (west_tile and north_tile):
                    return 4
                if east_tile:
                    if south_tile:
                        return 5
                    elif west_tile:
                        return 13
                    elif north_tile:
                        return 7
                    else:
                        return 14
                elif south_tile:
                    if west_tile:
                        return 6
                    elif north_tile:
                        return 9
                    else:
                        return 10
                else:
                    if not west_tile:
                        return 12 - north_tile
                    if north_tile:
                        return 8
                    else:
                        return 15
            else:
                raise Exception("__GOTO_BREAK__")
        except Exception as __goto_except:
            if "__GOTO_CONTINUE__" in str(__goto_except):
                continue
            if "__GOTO_BREAK__" in str(__goto_except):
                break
            raise __goto_except
    assert False


def handle_smart_edge_horiz_texture(world: World, tile: Tile, a3: int, /) -> int:
    __goto_label = "start"
    while True:
        try:
            if __goto_label == "start":
                tile_x: int = 0
                width: int = 0
                bg_id: int = 0
                tile_y: int = 0
                v9: Tile | None = None
                v10: int = 0
                v11: bool | int = False
                v12: bool | int = False
                v13: int = 0
                v14: Tile | None = None
                v15: int = 0
                v16: bool | int = False
                v17: bool | int = False
                foreground_or_background_id: int = 0
                v19: int = 0
                v21: int = 0
                v22: int = 0
                v23: int = 0
                v24: int = 0
                v25: Tile | None = None
                v31: int = 0
                v32: int = 0
                v33: int = 0
                v34: int = 0
                v35: Tile | None = None
                v36: int = 0
                v37: int = 0
                v38: int = 0
                v39: int = 0
                v40: Tile | None = None
                if a3:
                    tile_x = tile.pos.x
                    width = world.width
                    bg_id = tile.bg_id
                    tile_y = tile.pos.y
                    if tile_x + 1 >= width:
                        __goto_label = "LABEL_10"
                        raise Exception("__GOTO_CONTINUE__")
                    if tile_y >= world.height:
                        __goto_label = "LABEL_10"
                        raise Exception("__GOTO_CONTINUE__")
                    v9 = world.get_tile(tile_x + 1 + tile_y * width)
                    if not v9:
                        __goto_label = "LABEL_10"
                        raise Exception("__GOTO_CONTINUE__")
                    v10 = v9.bg_id
                    if v10:
                        if v9.flags & 2048 != 0:
                            __goto_label = "LABEL_10"
                            raise Exception("__GOTO_CONTINUE__")
                    if bg_id == 8930:
                        v11 = v10 == WEEPING_WILLOW
                    else:
                        if bg_id != 1194:
                            if bg_id == 3556 and v10 == DWARVEN_BACKGROUND:
                                __goto_label = "LABEL_10"
                                raise Exception("__GOTO_CONTINUE__")
                            __goto_label = "LABEL_25"
                            raise Exception("__GOTO_CONTINUE__")
                        v11 = v10 == TWISTED_WINDOWS
                    if v11:
                        v12 = 1
                        v13 = tile_x - 1
                        if tile_x - 1 < 0:
                            __goto_label = "LABEL_20"
                            raise Exception("__GOTO_CONTINUE__")
                        if v13 >= width:
                            __goto_label = "LABEL_20"
                            raise Exception("__GOTO_CONTINUE__")
                        if tile_y >= world.height:
                            __goto_label = "LABEL_20"
                            raise Exception("__GOTO_CONTINUE__")
                        v14 = world.get_tile(tile_y * width + v13)
                        if not v14:
                            __goto_label = "LABEL_20"
                            raise Exception("__GOTO_CONTINUE__")
                        v15 = v14.bg_id
                        if v15:
                            if v14.flags & 2048 != 0:
                                __goto_label = "LABEL_20"
                                raise Exception("__GOTO_CONTINUE__")
                        if bg_id == 8930:
                            v16 = v15 == WEEPING_WILLOW
                        else:
                            if bg_id != 1194:
                                if bg_id == 3556 and v15 == DWARVEN_BACKGROUND:
                                    __goto_label = "LABEL_20"
                                    raise Exception("__GOTO_CONTINUE__")
                                __goto_label = "LABEL_30"
                                raise Exception("__GOTO_CONTINUE__")
                            v16 = v15 == TWISTED_WINDOWS
                        if v16:
                            __goto_label = "LABEL_20"
                            raise Exception("__GOTO_CONTINUE__")
                        __goto_label = "LABEL_30"
                        raise Exception("__GOTO_CONTINUE__")
                    v12 = v10 == bg_id
                    __goto_label = "LABEL_11"
                    raise Exception("__GOTO_CONTINUE__")
                foreground_or_background_id = tile.front
                v12 = tile_should_connect(world, tile.pos.x + 1, tile.pos.y, foreground_or_background_id, 0)
                v19 = tile.front
                v17 = tile_should_connect(world, tile.pos.x - 1, tile.pos.y, v19, 0)
                if v12:
                    if v17:
                        return 1
                    else:
                        if tile.front == REGAL_STAIRS:
                            v21 = tile.pos.y - 1
                            v22 = tile.pos.x
                            if v21 < 0:
                                return 4
                            v23 = world.width
                            if v22 >= v23:
                                return 4
                            if v21 >= world.height:
                                return 4
                            v24 = v22 + v21 * v23
                            v25 = world.get_tile(v24)
                            if not v25 or ((v25.front and v25.front & 1 == 0) and v25.flags & 2048 != 0):
                                return 4
                            if v25.front == REGAL_BANNISTER:
                                return 4
                        v36 = tile.pos.y - 1
                        v37 = tile.pos.x
                        v38 = world.width
                        v39 = v37 + v36 * v38
                        if v39 > 0 and v39 < len(world.tiles) - 1:
                            v40 = world.get_tile(v39)
                            if (
                                tile.front == DIAMOND_REGAL_STAIRS
                                and v40
                                and (
                                    ((((v36 < 0 or v37 >= v38) or v36 >= world.height) or v40 == 0) or ((v40.front and v40.front & 1 == 0) and v40.flags & TileFlags.GLUED != 0))
                                    or v40.front == DIAMOND_REGAL_BANNISTER
                                )
                            ):
                                return 4
                            else:
                                return 0
                        else:
                            return 0
                elif v17:
                    if tile.front == REGAL_STAIRS:
                        v31 = tile.pos.y - 1
                        v32 = tile.pos.x
                        if v31 < 0:
                            return 5
                        v33 = world.width
                        if v32 >= v33:
                            return 5
                        if v31 >= world.height:
                            return 5
                        v34 = v32 + v31 * v33
                        v35 = world.get_tile(v34)
                        if not v35 or ((v35.front and v35.front & 1 == 0) and v35.flags & TileFlags.GLUED != 0):
                            return 5
                        if v35.front == REGAL_BANNISTER:
                            return 5
                    v36 = tile.pos.y - 1
                    v37 = tile.pos.x
                    v38 = world.width
                    v39 = v37 + v36 * v38
                    if v39 > 0 and v39 < len(world.tiles) - 1:
                        v40 = world.get_tile(v39)
                        if (
                            tile.front == DIAMOND_REGAL_STAIRS
                            and v40
                            and (
                                ((((v36 < 0 or v37 >= v38) or v36 >= world.height) or v40 == 0) or ((v40.front and v40.front & 1 == 0) and v40.flags & TileFlags.GLUED != 0))
                                or v40.front == DIAMOND_REGAL_BANNISTER
                            )
                        ):
                            return 5
                        else:
                            return 2
                    else:
                        return 2
                else:
                    return 3
            elif __goto_label == "LABEL_10":
                v12 = 1
                __goto_label = "LABEL_11"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_11":
                v13 = tile_x - 1
                if tile_x - 1 < 0:
                    __goto_label = "LABEL_20"
                    raise Exception("__GOTO_CONTINUE__")
                if v13 >= width:
                    __goto_label = "LABEL_20"
                    raise Exception("__GOTO_CONTINUE__")
                if tile_y >= world.height:
                    __goto_label = "LABEL_20"
                    raise Exception("__GOTO_CONTINUE__")
                assert tile_y
                v14 = world.get_tile(tile_y * width + v13)
                if not v14:
                    __goto_label = "LABEL_20"
                    raise Exception("__GOTO_CONTINUE__")
                v15 = v14.bg_id
                if v15:
                    if v14.flags & 2048 != 0:
                        __goto_label = "LABEL_20"
                        raise Exception("__GOTO_CONTINUE__")
                if bg_id == 8930:
                    v16 = v15 == WEEPING_WILLOW
                else:
                    if bg_id != 1194:
                        if bg_id == 3556 and v15 == DWARVEN_BACKGROUND:
                            __goto_label = "LABEL_20"
                            raise Exception("__GOTO_CONTINUE__")
                        __goto_label = "LABEL_30"
                        raise Exception("__GOTO_CONTINUE__")
                    v16 = v15 == TWISTED_WINDOWS
                if v16:
                    __goto_label = "LABEL_20"
                    raise Exception("__GOTO_CONTINUE__")
                __goto_label = "LABEL_30"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_20":
                v17 = 1
                __goto_label = "LABEL_32"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_25":
                assert v10
                v12 = v10 == bg_id
                __goto_label = "LABEL_11"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_30":
                assert v15
                v17 = v15 == bg_id
                __goto_label = "LABEL_32"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_32":
                if v12:
                    if v17:
                        return 1
                    else:
                        if tile.front == REGAL_STAIRS:
                            v21 = tile.pos.y - 1
                            v22 = tile.pos.x
                            if v21 < 0:
                                return 4
                            v23 = world.width
                            if v22 >= v23:
                                return 4
                            if v21 >= world.height:
                                return 4
                            v24 = v22 + v21 * v23
                            v25 = world.get_tile(v24)
                            if not v25 or ((v25.front and v25.front & 1 == 0) and v25.flags & 2048 != 0):
                                return 4
                            if v25.front == REGAL_BANNISTER:
                                return 4
                        v36 = tile.pos.y - 1
                        v37 = tile.pos.x
                        v38 = world.width
                        v39 = v37 + v36 * v38
                        if v39 > 0 and v39 < len(world.tiles) - 1:
                            v40 = world.get_tile(v39)
                            if (
                                tile.front == DIAMOND_REGAL_STAIRS
                                and v40
                                and (
                                    ((((v36 < 0 or v37 >= v38) or v36 >= world.height) or v40 == 0) or ((v40.front and v40.front & 1 == 0) and v40.flags & TileFlags.GLUED != 0))
                                    or v40.front == DIAMOND_REGAL_BANNISTER
                                )
                            ):
                                return 4
                            else:
                                return 0
                        else:
                            return 0
                elif v17:
                    if tile.front == REGAL_STAIRS:
                        v31 = tile.pos.y - 1
                        v32 = tile.pos.x
                        if v31 < 0:
                            return 5
                        v33 = world.width
                        if v32 >= v33:
                            return 5
                        if v31 >= world.height:
                            return 5
                        v34 = v32 + v31 * v33
                        v35 = world.get_tile(v34)
                        if not v35 or ((v35.front and v35.front & 1 == 0) and v35.flags & TileFlags.GLUED != 0):
                            return 5
                        if v35.front == REGAL_BANNISTER:
                            return 5
                    v36 = tile.pos.y - 1
                    v37 = tile.pos.x
                    v38 = world.width
                    v39 = v37 + v36 * v38
                    if v39 > 0 and v39 < len(world.tiles) - 1:
                        v40 = world.get_tile(v39)
                        if (
                            tile.front == DIAMOND_REGAL_STAIRS
                            and v40
                            and (
                                ((((v36 < 0 or v37 >= v38) or v36 >= world.height) or v40 == 0) or ((v40.front and v40.front & 1 == 0) and v40.flags & TileFlags.GLUED != 0))
                                or v40.front == DIAMOND_REGAL_BANNISTER
                            )
                        ):
                            return 5
                        else:
                            return 2
                    else:
                        return 2
                else:
                    return 3
            else:
                raise Exception("__GOTO_BREAK__")
        except Exception as __goto_except:
            if "__GOTO_CONTINUE__" in str(__goto_except):
                continue
            if "__GOTO_BREAK__" in str(__goto_except):
                break
            raise __goto_except
    assert False


def is_tile_flipped(world: World, tile_x: int, tile_y: int, tile_id: int, is_flipped: int, /) -> int:
    width: int = 0
    index: int = 0
    tile: Tile | None = None
    if tile_x < 0:
        return 1
    if tile_y < 0:
        return 1
    width = world.width
    if tile_x >= width:
        return 1
    if tile_y >= world.height:
        return 1
    index = tile_x + tile_y * width
    tile = world.get_tile(index)
    if not tile or ((tile.front and tile.front & 1 == 0) and tile.flags & TileFlags.GLUED != 0):
        return 1
    return tile.front == tile_id and (tile.flags & TileFlags.FLIPPED_X != 0) == is_flipped


def handle_smart_edge_horiz_seed_texture(world: World, tile: Tile, use_tile: int, /) -> int:
    __goto_label = "start"
    while True:
        try:
            if __goto_label == "start":
                tile_x: int = 0
                flags: TileFlags = TileFlags.NONE
                bg_id: int = 0
                tile_y: int = 0
                width: int = 0
                is_tile_flipped: bool | int = False
                v11: Tile | None = None
                v12: int = 0
                right_tile_flipped: bool | int = False
                v14: int = 0
                v15: Tile | None = None
                v16: int = 0
                left_tile_flipped: bool | int = False
                is_flipped: bool | int = 0
                tile_id_1: int = 0
                is_flipped_1: bool | int = 0
                tile_id: int = 0
                result: int = 0
                if use_tile:
                    tile_x = tile.pos.x
                    flags = tile.flags
                    bg_id = tile.bg_id
                    tile_y = tile.pos.y
                    width = world.width
                    is_tile_flipped = flags & TileFlags.FLIPPED_X != 0
                    right_tile_flipped = (
                        ((tile_x + 1 >= width or tile_y >= world.height) or (v11 := world.get_tile(tile_x + 1 + tile_y * width)) == None)
                        or ((v12 := v11.bg_id) != BLANK and v11.flags & TileFlags.GLUED != 0)
                    ) or (v12 == bg_id and (v11.flags & 32 != 0) == is_tile_flipped)
                    v14 = tile_x - 1
                    if tile_x - 1 < 0:
                        __goto_label = "LABEL_20"
                        raise Exception("__GOTO_CONTINUE__")
                    if v14 >= width:
                        __goto_label = "LABEL_20"
                        raise Exception("__GOTO_CONTINUE__")
                    if tile_y >= world.height:
                        __goto_label = "LABEL_20"
                        raise Exception("__GOTO_CONTINUE__")
                    v15 = world.get_tile(v14 + tile_y * width)
                    if not v15:
                        __goto_label = "LABEL_20"
                        raise Exception("__GOTO_CONTINUE__")
                    v16 = v15.bg_id
                    if v16 and v15.flags & TileFlags.GLUED != 0:
                        left_tile_flipped = 1
                        __goto_label = "LABEL_23"
                        raise Exception("__GOTO_CONTINUE__")
                    if v16 == bg_id and (v15.flags & TileFlags.FLIPPED_X != 0) == is_tile_flipped:
                        left_tile_flipped = 1
                    else:
                        left_tile_flipped = 0
                else:
                    is_flipped = tile.flags & TileFlags.FLIPPED_X != 0
                    tile_id_1 = tile.front
                    right_tile_flipped = is_tile_flipped(world, tile.pos.x + 1, tile.pos.y, tile_id_1, is_flipped)
                    is_flipped_1 = tile.flags & TileFlags.FLIPPED_X != 0
                    tile_id = tile.front
                    left_tile_flipped = is_tile_flipped(world, tile.pos.x - 1, tile.pos.y, tile_id, is_flipped_1)
                if tile.flags & TileFlags.FLIPPED_X != 0:
                    if right_tile_flipped:
                        return 2 - left_tile_flipped
                    else:
                        result = 3
                        if left_tile_flipped:
                            return 0
                elif right_tile_flipped:
                    return left_tile_flipped
                else:
                    return 3 - left_tile_flipped
                raise Exception("__GOTO_BREAK__")
            elif __goto_label == "LABEL_20":
                left_tile_flipped = 1
                __goto_label = "LABEL_23"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_23":
                if tile.flags & TileFlags.FLIPPED_X != 0:
                    if right_tile_flipped:
                        return 2 - left_tile_flipped
                    else:
                        result = 3
                        if left_tile_flipped:
                            return 0
                elif right_tile_flipped:
                    return left_tile_flipped
                else:
                    return 3 - left_tile_flipped
                raise Exception("__GOTO_BREAK__")
            else:
                raise Exception("__GOTO_BREAK__")
        except Exception as __goto_except:
            if "__GOTO_CONTINUE__" in str(__goto_except):
                continue
            if "__GOTO_BREAK__" in str(__goto_except):
                break
            raise __goto_except
    return result


def handle_random_seed_texture(world: World, a1: Tile, a3: int, /) -> int:
    __goto_label = "start"
    while True:
        try:
            if __goto_label == "start":
                tile_y: int = 0
                bg_id: int = 0
                tile_x: int = 0
                v8: int = 0
                v9: bool | int = False
                width: int = 0
                v11: Tile | None = None
                v12: int = 0
                v13: bool | int = False
                v14: int = 0
                v15: int = 0
                v16: Tile | None = None
                v17: int = 0
                v18: bool | int = False
                is_flipped: int = 0
                foreground_or_background_id: int = 0
                v21: int = 0
                v22: int = 0
                if a3:
                    tile_y = a1.pos.y
                    bg_id = a1.bg_id
                    tile_x = a1.pos.x
                    v8 = tile_y - 1
                    v9 = a1.flags & 32 != 0
                    v13 = (
                        (((tile_y - 1 < 0 or ((width := world.width), tile_x >= width)[-1]) or v8 >= world.height) or (v11 := world.get_tile(tile_x + v8 * width)) == None)
                        or ((v12 := v11.bg_id) != BLANK and v11.flags & 2048 != 0)
                    ) or (v12 == bg_id and (v11.flags & 32 != 0) == v9)
                    v14 = world.width
                    v15 = tile_y + 1
                    if tile_x >= v14:
                        __goto_label = "LABEL_20"
                        raise Exception("__GOTO_CONTINUE__")
                    if v15 >= world.height:
                        __goto_label = "LABEL_20"
                        raise Exception("__GOTO_CONTINUE__")
                    v16 = world.get_tile(tile_x + v15 * v14)
                    if not v16:
                        __goto_label = "LABEL_20"
                        raise Exception("__GOTO_CONTINUE__")
                    v17 = v16.bg_id
                    if v17 and v16.flags & 2048 != 0:
                        v18 = 1
                        __goto_label = "LABEL_23"
                        raise Exception("__GOTO_CONTINUE__")
                    if v17 == bg_id and (v16.flags & 32 != 0) == v9:
                        v18 = 1
                    else:
                        v18 = 0
                else:
                    is_flipped = a1.flags & 32 != 0
                    foreground_or_background_id = a1.front
                    v13 = is_tile_flipped(world, a1.pos.x, a1.pos.y - 1, foreground_or_background_id, is_flipped)
                    v21 = a1.flags & 32 != 0
                    v22 = a1.front
                    v18 = is_tile_flipped(world, a1.pos.x, a1.pos.y + 1, v22, v21)
                if v13:
                    return v18
                else:
                    return 3 - v18
            elif __goto_label == "LABEL_20":
                v18 = 1
                __goto_label = "LABEL_23"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_23":
                if v13:
                    return v18
                else:
                    return 3 - v18
            else:
                raise Exception("__GOTO_BREAK__")
        except Exception as __goto_except:
            if "__GOTO_CONTINUE__" in str(__goto_except):
                continue
            if "__GOTO_BREAK__" in str(__goto_except):
                break
            raise __goto_except
    assert False


def update_tile_connectivity(world: World, tile: Tile, /) -> None:
    __goto_label = "start"
    while True:
        try:
            if __goto_label == "start":
                foreground_or_background_id: int = 0
                item_by_id: Item | None = None
                bg_id: int = 0
                v8: Item | None = None
                v10: World | None = None
                v11: bool | int = False
                v12: Tile | None = None
                if tile:
                    foreground_or_background_id = tile.front
                    item_by_id = item_database.get(foreground_or_background_id)
                    while True:
                        __switch_on0 = item_by_id.texture_type
                        _switch_matched_any0 = False
                        __matched0 = False
                        if __matched0 or (
                            __switch_on0 == ItemInfoTextureType.SINGLE_FRAME_ALONE
                            or __switch_on0 == ItemInfoTextureType.SINGLE_FRAME
                            or __switch_on0 == ItemInfoTextureType.SMART_OUTER
                        ):
                            if not __matched0 and (
                                __switch_on0 == ItemInfoTextureType.SINGLE_FRAME_ALONE
                                or __switch_on0 == ItemInfoTextureType.SINGLE_FRAME
                                or __switch_on0 == ItemInfoTextureType.SMART_OUTER
                            ):
                                _switch_matched_any0 = True
                            __matched0 = True
                            tile.fg_tex_index = 0
                            break
                        if __matched0 or __switch_on0 == ItemInfoTextureType.SMART_EDGE:
                            if not __matched0 and __switch_on0 == ItemInfoTextureType.SMART_EDGE:
                                _switch_matched_any0 = True
                            __matched0 = True
                            tile.fg_tex_index = handle_smart_edge_texture(world, tile, 0)
                            break
                        if __matched0 or __switch_on0 == ItemInfoTextureType.SMART_EDGE_HORIZ:
                            if not __matched0 and __switch_on0 == ItemInfoTextureType.SMART_EDGE_HORIZ:
                                _switch_matched_any0 = True
                            __matched0 = True
                            if item_by_id.flags2 & 1 != 0:
                                tile.fg_tex_index = handle_smart_edge_horiz_seed_texture(world, tile, 0)
                            else:
                                tile.fg_tex_index = handle_smart_edge_horiz_texture(world, tile, 0)
                            break
                        if __matched0 or __switch_on0 == ItemInfoTextureType.SMART_CLING2:
                            if not __matched0 and __switch_on0 == ItemInfoTextureType.SMART_CLING2:
                                _switch_matched_any0 = True
                            __matched0 = True
                            tile.fg_tex_index = handle_cling2_texture(world, tile, 0)
                            break
                        if __matched0 or __switch_on0 == ItemInfoTextureType.RANDOM:
                            if not __matched0 and __switch_on0 == ItemInfoTextureType.RANDOM:
                                _switch_matched_any0 = True
                            __matched0 = True
                            if item_by_id.flags2 & 1 != 0:
                                tile.fg_tex_index = handle_random_seed_texture(world, tile, 0)
                            else:
                                tile.fg_tex_index = sub_140564120(world, tile, 0)
                            break
                        if __matched0 or __switch_on0 == ItemInfoTextureType.SMART_EDGE_VERT:
                            if not __matched0 and __switch_on0 == ItemInfoTextureType.SMART_EDGE_VERT:
                                _switch_matched_any0 = True
                            __matched0 = True
                            tile.fg_tex_index = sub_1405637_d0(world, tile, 0)
                            break
                        if __matched0 or __switch_on0 == ItemInfoTextureType.SMART_EDGE_DIAGON:
                            if not __matched0 and __switch_on0 == ItemInfoTextureType.SMART_EDGE_DIAGON:
                                _switch_matched_any0 = True
                            __matched0 = True
                            tile.fg_tex_index = sub_1405630_e0(world, tile, 0)
                            break
                        if __matched0 or not _switch_matched_any0:
                            __matched0 = True
                            pass
                        break
                    bg_id = tile.bg_id
                    v8 = item_database.get(bg_id)
                    while True:
                        __switch_on1 = v8.texture_type
                        _switch_matched_any1 = False
                        __matched1 = False
                        if __matched1 or (
                            __switch_on1 == ItemInfoTextureType.SINGLE_FRAME_ALONE
                            or __switch_on1 == ItemInfoTextureType.SINGLE_FRAME
                            or __switch_on1 == ItemInfoTextureType.SMART_OUTER
                        ):
                            if not __matched1 and (
                                __switch_on1 == ItemInfoTextureType.SINGLE_FRAME_ALONE
                                or __switch_on1 == ItemInfoTextureType.SINGLE_FRAME
                                or __switch_on1 == ItemInfoTextureType.SMART_OUTER
                            ):
                                _switch_matched_any1 = True
                            __matched1 = True
                            tile.bg_tex_index = 0
                            break
                        if __matched1 or __switch_on1 == ItemInfoTextureType.SMART_EDGE:
                            if not __matched1 and __switch_on1 == ItemInfoTextureType.SMART_EDGE:
                                _switch_matched_any1 = True
                            __matched1 = True
                            tile.bg_tex_index = handle_smart_edge_texture(world, tile, 1)
                            break
                        if __matched1 or __switch_on1 == ItemInfoTextureType.SMART_EDGE_HORIZ:
                            if not __matched1 and __switch_on1 == ItemInfoTextureType.SMART_EDGE_HORIZ:
                                _switch_matched_any1 = True
                            __matched1 = True
                            v10 = world
                            v11 = v8.flags2 & 1 == 0
                            v12 = tile
                            if not v11:
                                __goto_label = "LABEL_19"
                                raise Exception("__GOTO_CONTINUE__")
                            tile.bg_tex_index = handle_smart_edge_horiz_texture(world, tile, 1)
                            break
                        if __matched1 or __switch_on1 == ItemInfoTextureType.SMART_CLING2:
                            if not __matched1 and __switch_on1 == ItemInfoTextureType.SMART_CLING2:
                                _switch_matched_any1 = True
                            __matched1 = True
                            tile.bg_tex_index = handle_cling2_texture(world, tile, 1)
                            break
                        if __matched1 or __switch_on1 == ItemInfoTextureType.RANDOM:
                            if not __matched1 and __switch_on1 == ItemInfoTextureType.RANDOM:
                                _switch_matched_any1 = True
                            __matched1 = True
                            tile.bg_tex_index = sub_140564120(world, tile, 1)
                            break
                        if __matched1 or __switch_on1 == ItemInfoTextureType.SMART_EDGE_VERT:
                            if not __matched1 and __switch_on1 == ItemInfoTextureType.SMART_EDGE_VERT:
                                _switch_matched_any1 = True
                            __matched1 = True
                            tile.bg_tex_index = sub_1405637_d0(world, tile, 1)
                            break
                        if __matched1 or __switch_on1 == ItemInfoTextureType.SMART_EDGE_DIAGON:
                            if not __matched1 and __switch_on1 == ItemInfoTextureType.SMART_EDGE_DIAGON:
                                _switch_matched_any1 = True
                            __matched1 = True
                            v12 = tile
                            v10 = world
                            __goto_label = "LABEL_19"
                            raise Exception("__GOTO_CONTINUE__")
                        if __matched1 or not _switch_matched_any1:
                            __matched1 = True
                            return
                        break
                raise Exception("__GOTO_BREAK__")
            elif __goto_label == "LABEL_19":
                tile.bg_tex_index = handle_smart_edge_horiz_for_seed(v10, v12, 1)
                breakhandle_smart_edge_horiz_seed_texture
            else:
                raise Exception("__GOTO_BREAK__")
        except Exception as __goto_except:
            if "__GOTO_CONTINUE__" in str(__goto_except):
                continue
            if "__GOTO_BREAK__" in str(__goto_except):
                break
            raise __goto_except


autotile_47 = [
    [
        [0, 0, 0],
        [0, 1, 0],
        [0, 0, 0],
    ],
    [
        [0, 1, 0],
        [0, 1, 0],
        [0, 0, 0],
    ],
    [
        [0, 0, 0],
        [0, 1, 1],
        [0, 0, 0],
    ],
    [
        [0, 0, 0],
        [0, 1, 0],
        [0, 1, 0],
    ],
    [
        [0, 0, 0],
        [1, 1, 0],
        [0, 0, 0],
    ],
    [
        [0, 1, 0],
        [0, 1, 0],
        [0, 1, 0],
    ],
    [
        [0, 0, 0],
        [1, 1, 1],
        [0, 0, 0],
    ],
    [
        [0, 1, 0],
        [0, 1, 1],
        [0, 0, 0],
    ],
    [
        [0, 1, 0],
        [1, 1, 0],
        [0, 0, 0],
    ],
    [
        [0, 0, 0],
        [1, 1, 0],
        [0, 1, 0],
    ],
    [
        [0, 0, 0],
        [0, 1, 1],
        [0, 1, 0],
    ],
    [
        [0, 1, 0],
        [1, 1, 1],
        [0, 0, 0],
    ],
    [
        [0, 0, 0],
        [1, 1, 1],
        [0, 1, 0],
    ],
    [
        [0, 1, 0],
        [0, 1, 1],
        [0, 1, 0],
    ],
    [
        [0, 1, 0],
        [1, 1, 0],
        [0, 1, 0],
    ],
    [
        [0, 1, 0],
        [1, 1, 1],
        [0, 1, 0],
    ],
    [
        [1, 1, 0],
        [1, 1, 0],
        [0, 0, 0],
    ],
    [
        [0, 1, 1],
        [0, 1, 1],
        [0, 0, 0],
    ],
    [
        [0, 0, 0],
        [1, 1, 0],
        [1, 1, 0],
    ],
    [
        [0, 0, 0],
        [0, 1, 1],
        [0, 1, 1],
    ],
    [
        [0, 1, 0],
        [1, 1, 1],
        [1, 0, 0],
    ],
    [
        [0, 1, 0],
        [1, 1, 1],
        [0, 0, 1],
    ],
    [
        [1, 0, 0],
        [1, 1, 1],
        [0, 1, 0],
    ],
    [
        [0, 0, 1],
        [1, 1, 1],
        [0, 1, 0],
    ],
    [
        [0, 1, 1],
        [1, 1, 1],
        [1, 1, 1],
    ],
    [
        [1, 1, 0],
        [1, 1, 1],
        [1, 1, 1],
    ],
    [
        [1, 1, 1],
        [1, 1, 1],
        [0, 1, 1],
    ],
    [
        [1, 1, 1],
        [1, 1, 1],
        [1, 1, 0],
    ],
    [
        [1, 1, 1],
        [1, 1, 1],
        [1, 1, 1],
    ],
]


@click.command()
@click.argument("id", type=int)
def tileset(id: int) -> None:
    item = item_database.get(id)
    tex_file = windows_home() / "AppData/Local/Growtopia/game" / item.texture_file.decode()

    world = World()
    for c, conf in enumerate(autotile_47):
        for y, row in enumerate(conf):
            for x, col in enumerate(row):
                pos = ivec2(x + c * 4, y)
                world.width = max(world.width, pos.x)
                world.height = max(world.height, pos.y)
                if not col:
                    world.tiles.append(Tile(0, pos=pos))
                else:
                    world.tiles.append(Tile(id, pos=pos))

    world.fix()

    arr = get_image_buffer(str(tex_file))
    if arr is None:
        return

    for tile in world.tiles:
        update_tile_connectivity(world, tile)

    renderer = WorldRenderer()
    img = np.zeros((world.height * 32, world.width * 32, 4), dtype=np.uint8)
    for tile in world.tiles:
        for cmd in renderer.get_render_cmd(tile):
            for dst in cmd.dst:
                dst = ivec4(dst)
                alpha_mask = cmd.buffer[:, :, 3] > 4
                dst_slice = img[dst.y : dst.y + dst.z, dst.x : dst.x + dst.w, :]
                dst_slice[alpha_mask] = cmd.buffer[:, :, : dst_slice.shape[2]][alpha_mask]

    Image.fromarray(img).show()
