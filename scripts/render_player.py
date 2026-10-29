import random
import sys

import click
import numpy as np

from gtools.baked.items import (
    ANCESTRAL_TESSERACT_OF_DIMENSIONS,
    DA_VINCI_WINGS,
    INTERGALACTIC_WARRIOR_HAIR,
    LEGENDARY_KATANA,
    NEON_NERVES,
    NO_FACE,
    SKELETAL_HORSIE,
)
from gtools.core.color import Color
from gtools.core.growtopia.items_dat import ItemInfoClothingType, ItemInfoType, item_database
from gtools.core.growtopia.player import Clothing, Player
from gtools.core.growtopia.renderer.player_renderer import PlayerRenderer, RenderOptions
from scripts.utils import image_show_ansi


def clothing_candidates() -> dict[ItemInfoClothingType, list[int]]:
    candidates: dict[ItemInfoClothingType, list[int]] = {}
    for item in item_database.items.values():
        if item.item_type == ItemInfoType.CLOTHES:
            candidates.setdefault(item.clothing_type, []).append(item.id)

    return candidates


def randomize_clothing(clothing: Clothing) -> None:
    candidates = clothing_candidates()
    for clothing_type, _ in clothing:
        ids = candidates.get(clothing_type)
        if ids:
            setattr(clothing, clothing_type.name.lower(), random.choice(ids))


@click.command()
@click.option("--out", type=click.Path(dir_okay=False, path_type=str), default=None, help="Write the render to a PNG file.")
@click.option("--facing", type=click.IntRange(-1, 1), default=1, show_default=True, help="1 = right, -1 = left.")
@click.option("--random", "randomize", is_flag=True, help="Pick a random item for every clothing slot.")
def render_player(out: str | None, facing: int, randomize: bool) -> None:
    clothing = Clothing(
        hair=INTERGALACTIC_WARRIOR_HAIR,
        shirt=NEON_NERVES,
        pants=344,
        shoes=SKELETAL_HORSIE,
        face=NO_FACE,
        hand=LEGENDARY_KATANA,
        back=DA_VINCI_WINGS,
        hat=46,
        neck=7576,
        artifacts=ANCESTRAL_TESSERACT_OF_DIMENSIONS,
        skin_color=Color(120, 92, 80, 255),
    )

    if randomize:
        randomize_clothing(clothing)

    player = Player(clothing=clothing)

    for type, cloth in player.clothing:
        print(f"{type.name:<10}: {item_database.get(cloth).name.decode() if cloth != 0 else '-'}")

    image = PlayerRenderer().render(player, RenderOptions(facing=facing))

    if out is not None:
        image.save(out)
        print(f"wrote {out}")

    image_show_ansi(np.array(image))


if __name__ == "__main__":
    sys.exit(render_player())
