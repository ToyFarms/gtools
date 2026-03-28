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


def _blend_rgba_over_bg(rgba: np.ndarray, bg=(0, 0, 0)) -> np.ndarray:
    rgba = rgba.astype(np.float32)
    rgb = rgba[..., :3]
    a = rgba[..., 3:4] / 255.0
    bg = np.array(bg, dtype=np.float32)
    out = rgb * a + bg * (1.0 - a)
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def image_show_ansi(img: np.ndarray, bg=(0, 0, 0), file=sys.stdout) -> None:
    if img.ndim != 3 or img.shape[-1] != 4:
        raise ValueError("Expected an array of shape (H, W, 4)")

    h, w, _ = img.shape

    rgb = _blend_rgba_over_bg(img, bg=bg)

    if h % 2 == 1:
        pad = np.full((1, w, 3), np.array(bg, dtype=np.uint8), dtype=np.uint8)
        rgb = np.concatenate([rgb, pad], axis=0)
        h += 1

    for y in range(0, h, 2):
        top = rgb[y]
        bottom = rgb[y + 1]

        parts = []
        for x in range(w):
            tr, tg, tb = top[x]
            br, bg_, bb = bottom[x]
            parts.append(f"\x1b[38;2;{tr};{tg};{tb}m" f"\x1b[48;2;{br};{bg_};{bb}m▀")
        parts.append("\x1b[0m")
        file.write("".join(parts) + "\n")


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
