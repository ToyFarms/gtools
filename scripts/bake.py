from pathlib import Path
import click

from gtools.core.c import IdentifierRegistry, to_c_ident
from gtools.core.growtopia.items_dat import item_database


@click.command()
@click.option("--path", default=None, help="items.dat path")
def bake(path: str | None) -> None:
    if path:
        db = item_database.deserialize(path)
    else:
        db = item_database.db()

    p = Path("gtools/baked/items.py")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.unlink(missing_ok=True)
    with open(p, "w") as f:
        ctx = IdentifierRegistry()
        for id, item in db.items.items():
            # its not c but it should be fine
            f.write(f"{to_c_ident(item.name.decode(), ctx).upper()} = {id}\n")
