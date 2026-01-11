import click
from gtools.core.growtopia.items_dat import item_database


@click.command()
@click.argument("id", type=int)
def item(id: int) -> None:
    print(item_database.get(id))
