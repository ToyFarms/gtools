import itertools
import shutil
from pathlib import Path
from pprint import pprint
import click


@click.command()
def clean_test() -> None:
    snapshots = Path("tests/snapshots")
    out = list(itertools.chain(snapshots.glob("*.out"), snapshots.glob("*.snap")))
    pprint(out)
    print(f"\x1b[31mREMOVING \x1b[4;1m{len(out)}\x1b[0m files from {snapshots}!, are you sure? ", end="")

    if click.confirm("(y/N)", default=False):
        shutil.rmtree(snapshots)
