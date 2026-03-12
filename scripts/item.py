import click
from gtools.core.growtopia.items_dat import item_database


@click.command()
@click.argument("id", type=str)
def item(id: str) -> None:
    if id.isnumeric():
        print(item_database.get(int(id)))
    else:
        print(item_database.search(id)[0])

