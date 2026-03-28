import sys
from PIL import Image
import click
import numpy as np
from pyglm.glm import ivec2

from gtools import setting
from gtools.baked.items import ANIME_MALE_HAIR, DIAMOND_ROCKET_SHOES, EDVOID_S_FIRE_NADO, INTERGALACTIC_WARRIOR_HAIR, MESSY_HAIR, SPIKEY_HAIR, STARBOARD
from gtools.core.color import Color, color_tint, composite, composite_onto
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.player import Clothing, Player
from gtools.core.growtopia.rttex import RTTexManager
from gtools.core.growtopia.variant import Variant
from scripts.utils import image_show_ansi


@click.command()
def render_player() -> None:
    player = Player(
        clothing=Clothing(
            hair=INTERGALACTIC_WARRIOR_HAIR,
            shirt=0,
            pants=344,
            shoes=EDVOID_S_FIRE_NADO,
            face=0,
            hand=0,
            back=0,
            hat=46,
            neck=7576,
            artifacts=0,
            skin_color=Color.from_int_le(2527912447),
        )
    )

    for type, cloth in player.clothing:
        print(f"{type.name:<10}: {item_database.get(cloth).name.decode() if cloth != 0 else '-'}")

    mgr = RTTexManager()
    layers: list[tuple[np.ndarray, ivec2]] = []

    base = ivec2(0, 16)

    skin_color = np.array(player.clothing.skin_color.to_tuple(), dtype=np.uint8)

    # right arm
    layers.append((color_tint(mgr.get(setting.asset_path / "game/player_arm.rttex", 0, 0, 8, 16), skin_color), base + ivec2(20, 17)))

    # left feet
    layers.append((color_tint(mgr.get(setting.asset_path / "game/player_feet.rttex", 0, 0, 32, 32), skin_color), base + ivec2(0, 0)))
    # right feet
    layers.append((color_tint(mgr.get(setting.asset_path / "game/player_feet.rttex", 0, 32, 32, 32), skin_color), base + ivec2(0, 0)))

    # leg
    layers.append((color_tint(mgr.get(setting.asset_path / "game/player_extraleg.rttex", 0, 0, 16, 16), skin_color), base + ivec2(8, 28)))
    # body
    layers.append((color_tint(mgr.get(setting.asset_path / "game/player_head.rttex", 0, 0, 32, 32), skin_color), base + ivec2(0, 0)))

    # left arm
    layers.append((color_tint(mgr.get(setting.asset_path / "game/player_arm.rttex", 0, 0, 8, 16), skin_color), base + ivec2(6, 17)))

    # eyes
    layers.append((mgr.get(setting.asset_path / "game/player_eyes.rttex", 0, 0, 32, 32), base + ivec2(0, 0)))

    if player.clothing.hair != 0:
        item = item_database.get(player.clothing.hair)
        layers.append((mgr.get(setting.asset_path / "game" / item.texture_file.decode(), item.tex_coord_x * 32, item.tex_coord_y * 32, 32, 32), base + ivec2(0, -16)))

    if player.clothing.hat != 0:
        item = item_database.get(player.clothing.hat)
        layers.append((mgr.get(setting.asset_path / "game" / item.texture_file.decode(), item.tex_coord_x * 32, item.tex_coord_y * 32, 32, 32), base + ivec2(0, -16)))

    out = np.zeros((64, 64, 4), dtype=np.uint8)
    for layer, pos in layers:
        out = composite_onto(out, layer, pos[0], pos[1])

    # Image.fromarray(out).show()
    image_show_ansi(out)
