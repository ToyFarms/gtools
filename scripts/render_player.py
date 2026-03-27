import click

from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.player import Clothing, Player
from gtools.core.growtopia.variant import Variant

@click.command()
def render_player() -> None:
    clothing = Variant([Variant.vstr(b""), Variant.vvec3((7278.0, 0.0, 344.0)), Variant.vvec3((11494.0, 0.0, 0.0)), Variant.vvec3((0.0, 0.0, 7576.0)), Variant.vuint(2190853119), Variant.vvec3((0.0, 0.0, 0.0))])
    player = Player(clothing=Clothing.from_variant(clothing))

    for type, cloth in player.clothing:
        print(f"{type.name:<10}: {item_database.get(cloth).name.decode() if cloth != 0 else '-'}")
