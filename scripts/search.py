import click
from gtools.core.growtopia.items_dat import item_database


@click.command()
@click.argument("name")
@click.option("-n", default=20, type=int, help="number of results")
def search(name: str, n: int) -> None:
    trim = lambda x, n=60: x if len(x) <= n else f"{x[:n]}..."
    for i, ent in reversed(list(enumerate(item_database.search(name, n=n), 1))):
        if i % 5 == 0:
            print(f"\x1b[2m{i:<6} {ent.id:<10} {ent.name.decode():<30} {trim(ent.info.decode()):<80} {ent.item_type.name}\x1b[0m")
        else:
            print(f"{i:<5} {ent.id:<10} {ent.name.decode():<30} {trim(ent.info.decode()):<80} {ent.item_type.name}")
