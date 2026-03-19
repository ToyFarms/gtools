from PIL import Image
import click

from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.seed_renderer import SeedRenderer


@click.command()
@click.argument("id", type=int)
def seed(id: int) -> None:
    if not item_database.get(id).is_seed():
        id += 1
    item = item_database.get(id)

    r = SeedRenderer()
    tex = r.get(item.seed_base, item.seed_color, item.seed_overlay, item.seed_overlay_color)
    Image.fromarray(tex).show()
