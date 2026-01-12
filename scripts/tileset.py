from typing import cast
from PIL import Image
import click
from pyglm.glm import ivec2, ivec4
import numpy as np

from gtools.core.growtopia.items_dat import ItemInfoTextureType, item_database
from gtools.core.growtopia.rttex import get_image_buffer
from gtools.core.growtopia.world import Tile, TileFlags, World
from gtools.core.wsl import windows_home
from gtools.baked.items import (
    AQUA_CAVE_CRYSTAL,
    BEDROCK,
    BONE_CHECKPOINT,
    CAVE_COLUMN,
    CAVE_DIRT,
    CAVE_PLATFORM,
    CLIMBING_WALL,
    DATA_BEDROCK,
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
    STALACTITE,
    STALAGMITE,
    STEAM_LAUNCHER,
    STEAM_PIPE,
    STONE_PAGODA,
    STONE_PAGODA_BASE,
    TWISTED_WINDOWS,
    WEEPING_WILLOW,
    WEEPING_WILLOW_FOLIAGE,
)


def check_if_tile_is_empty(world: World, tile_x: int, tile_y: int, item_id: int, maybe_cave_stuff: int, /) -> int:
    tile: Tile
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
                tile = cast(Tile, world.get_tile(ivec2(tile_x, tile_y)))
                assert tile
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
                if tile.front >= PURPLE_CAVE_CRYSTAL and tile.front <= AQUA_CAVE_CRYSTAL:
                    return 1
                __goto_label = "LABEL_31"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_31":
                if not maybe_cave_stuff and item_id == CAVE_DIRT:
                    if tile.front == CLIMBING_WALL:
                        return 1
                    return tile.front == item_id
                __goto_label = "LABEL_35"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_35":
                if item_id == STEAM_PIPE:
                    if item_database.get(tile.front).is_steam():
                        return 1
                    __goto_label = "LABEL_60"
                    raise Exception("__GOTO_CONTINUE__")
                __goto_label = "LABEL_60"
                raise Exception("__GOTO_CONTINUE__")
            elif __goto_label == "LABEL_60":
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
    return 0


def sub_140565_df0(a1: World, tile_x: int, tile_y: int, /) -> int:
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


def determine_tile_index_from_neighbor(world: World, tile: Tile, a3: int, /) -> int:
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
                    bg = tile.bg
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
                        east_tile = sub_140565_df0(world, tile_x + 1, tile.pos.y)
                        v72 = sub_140565_df0(world, tile_x + 1, tile_y + 1)
                        v75 = sub_140565_df0(world, tile_x, tile_y + 1)
                        south_west_tile = sub_140565_df0(world, tile_x - 1, tile_y + 1)
                        west_tile = sub_140565_df0(world, tile_x - 1, tile_y)
                        north_west_tile = sub_140565_df0(world, tile_x - 1, tile_y_1 - 1)
                        north_tile = sub_140565_df0(world, tile_x, tile_y_1 - 1)
                        north_east_tile = sub_140565_df0(world, v57, tile_y_1 - 1)
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
                        north_east_tile   = bool(tile)
                        north_tile        = bool(tile)
                        north_west_tile   = bool(tile)
                        west_tile         = bool(tile)
                        south_west_tile   = bool(tile)
                        south_tile_1      = bool(tile)
                        south_east_tile_1 = bool(tile)
                        v14 = bool(tile)
                else:
                    tile_x__plus__one = tile_x + 1
                    foreground_or_background_id = tile.front
                    east_tile_1 = check_if_tile_is_empty(world, tile_x + 1, tile_y, foreground_or_background_id, 0)
                    v50 = tile.front
                    south_east_tile = check_if_tile_is_empty(world, tile_x + 1, tile_y + 1, v50, 0)
                    v51 = tile.front
                    south_tile = check_if_tile_is_empty(world, tile_x, tile_y + 1, v51, 0)
                    v52 = tile.front
                    south_west_tile = check_if_tile_is_empty(world, tile_x - 1, tile_y + 1, v52, 0)
                    v53 = tile.front
                    west_tile = check_if_tile_is_empty(world, tile_x - 1, tile_y, v53, 0)
                    v54 = tile.front
                    north_west_tile = check_if_tile_is_empty(world, tile_x - 1, tile_y_1 - 1, v54, 0)
                    v55 = tile.front
                    north_tile = check_if_tile_is_empty(world, tile_x, tile_y_1 - 1, v55, 0)
                    v56 = tile.front
                    north_east_tile = check_if_tile_is_empty(world, tile_x__plus__one, tile_y_1 - 1, v56, 0)
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


def update_tile_connectivity(world: World, tile: Tile, /):
    __goto_label = 'start'
    while True:
        try:
            if __goto_label == 'start':
                'ItemID ForegroundOrBackgroundId'
                'ItemManager * ItemManager'
                'ItemDat * ItemById'
                '__int64 bg'
                'ItemDat * v8'
                '__int64 v9'
                'WorldView * v10'
                'bool v11'
                'Tile * v12'
                if tile:
                    foreground_or_background_id = tile.front
                    item_by_id = item_database.get(foreground_or_background_id)
                    while True:
                        __switch_on0 = item_by_id.texture_type
                        _switch_matched_any0 = False
                        __matched0 = False
                        if __matched0 or (__switch_on0 == ItemInfoTextureType.SINGLE_FRAME_ALONE or __switch_on0 == ItemInfoTextureType.SINGLE_FRAME or __switch_on0 == ItemInfoTextureType.SMART_OUTER):
                            if not __matched0 and (__switch_on0 == ItemInfoTextureType.SINGLE_FRAME_ALONE or __switch_on0 == ItemInfoTextureType.SINGLE_FRAME or __switch_on0 == ItemInfoTextureType.SMART_OUTER):
                                _switch_matched_any0 = True
                            __matched0 = True
                            tile.fg_tex_index = 0
                            break
                        if __matched0 or __switch_on0 == ItemInfoTextureType.SMART_EDGE:
                            if not __matched0 and __switch_on0 == ItemInfoTextureType.SMART_EDGE:
                                _switch_matched_any0 = True
                            __matched0 = True
                            tile.fg_tex_index = determine_tile_index_from_neighbor(world, tile, 0)
                            break
                        if __matched0 or __switch_on0 == ItemInfoTextureType.SMART_EDGE_HORIZ:
                            if not __matched0 and __switch_on0 == ItemInfoTextureType.SMART_EDGE_HORIZ:
                                _switch_matched_any0 = True
                            __matched0 = True
                            if item_by_id.flags2 & 1 != 0:
                                tile.fg_tex_index = check_tile_connectivity_left_and_right_for_seed(world, tile, 0)
                            else:
                                tile.fg_tex_index = sub_1405633_c0(world, tile, 0)
                            break
                        if __matched0 or __switch_on0 == ItemInfoTextureType.SMART_CLING2:
                            if not __matched0 and __switch_on0 == ItemInfoTextureType.SMART_CLING2:
                                _switch_matched_any0 = True
                            __matched0 = True
                            tile.fg_tex_index = sub_140563_ca0(world, tile, 0)
                            break
                        if __matched0 or __switch_on0 == ItemInfoTextureType.RANDOM:
                            if not __matched0 and __switch_on0 == ItemInfoTextureType.RANDOM:
                                _switch_matched_any0 = True
                            __matched0 = True
                            if item_by_id.flags2 & 1 != 0:
                                tile.fg_tex_index = sub_1405642_f0(world, tile, 0)
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
                    bg = tile.bg_id
                    v8 = item_database.get(bg)
                    while True:
                        __switch_on1 = v8.texture_type
                        _switch_matched_any1 = False
                        __matched1 = False
                        if __matched1 or (__switch_on1 == ItemInfoTextureType.SINGLE_FRAME_ALONE or __switch_on1 == ItemInfoTextureType.SINGLE_FRAME or __switch_on1 == ItemInfoTextureType.SMART_OUTER):
                            if not __matched1 and (__switch_on1 == ItemInfoTextureType.SINGLE_FRAME_ALONE or __switch_on1 == ItemInfoTextureType.SINGLE_FRAME or __switch_on1 == ItemInfoTextureType.SMART_OUTER):
                                _switch_matched_any1 = True
                            __matched1 = True
                            tile.bg_tex_index = 0
                            break
                        if __matched1 or __switch_on1 == ItemInfoTextureType.SMART_EDGE:
                            if not __matched1 and __switch_on1 == ItemInfoTextureType.SMART_EDGE:
                                _switch_matched_any1 = True
                            __matched1 = True
                            tile.bg_tex_index = determine_tile_index_from_neighbor(world, tile, 1)
                            break
                        if __matched1 or __switch_on1 == ItemInfoTextureType.SMART_EDGE_HORIZ:
                            if not __matched1 and __switch_on1 == ItemInfoTextureType.SMART_EDGE_HORIZ:
                                _switch_matched_any1 = True
                            __matched1 = True
                            v10 = world
                            v11 = v8.flags2 & 1 == 0
                            v12 = tile
                            if not v11:
                                __goto_label = 'LABEL_19'
                                raise Exception('__GOTO_CONTINUE__')
                            tile.bg_tex_index = sub_1405633_c0(world, tile, 1)
                            break
                        if __matched1 or __switch_on1 == ItemInfoTextureType.SMART_CLING2:
                            if not __matched1 and __switch_on1 == ItemInfoTextureType.SMART_CLING2:
                                _switch_matched_any1 = True
                            __matched1 = True
                            # (LOBYTE(v9) := 1)
                            tile.bg_tex_index = sub_140563_ca0(world, tile, v9)
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
                            # (LOBYTE(v9) := 1)
                            tile.bg_tex_index = sub_1405637_d0(world, tile, v9)
                            break
                        if __matched1 or __switch_on1 == ItemInfoTextureType.SMART_EDGE_DIAGON:
                            if not __matched1 and __switch_on1 == ItemInfoTextureType.SMART_EDGE_DIAGON:
                                _switch_matched_any1 = True
                            __matched1 = True
                            v12 = tile
                            v10 = world
                            tile.bg_tex_index = check_tile_connectivity_left_and_right_for_seed(v10, v12, 1)
                            break
                        if __matched1 or not _switch_matched_any1:
                            __matched1 = True
                            return
                        break
                raise Exception('__GOTO_BREAK__')
            elif __goto_label == 'LABEL_19':
                tile.bg_tex_index = check_tile_connectivity_left_and_right_for_seed(v10, v12, 1)
                break
            else:
                raise Exception('__GOTO_BREAK__')
        except Exception as __goto_except:
            if '__GOTO_CONTINUE__' in str(__goto_except):
                continue
            if '__GOTO_BREAK__' in str(__goto_except):
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

    tile_configuration = len(autotile_47)
    img_width = tile_configuration * 32 * 3 + (tile_configuration - 1) * 32
    img_height = 32 * 3

    img = np.zeros((img_height, img_width, 4), dtype=np.uint8)
    for tile in world.tiles:
        update_tile_connectivity(world, tile)
        off = ivec2(tile.fg_tex_index % 8, tile.fg_tex_index // 8)

        item = item_database.get(tile.front)
        base = (ivec2(item.tex_coord_x, item.tex_coord_y) + off) * 32
        tile_tex = arr[base.y : base.y + 32, base.x : base.x + 32, :]

        x, y = tile.pos.xy
        dst = ivec4(x * 32, y * 32, 32, 32)

        img[dst.y : dst.y + 32, dst.x : dst.x + 32, :] = tile_tex

    Image.fromarray(img).show()
