import click

from gtools.core.growtopia.crypto import generate_rid


@click.command
def rid() -> None:
    print(generate_rid())
