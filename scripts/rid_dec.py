import click

from gtools.core.growtopia.crypto import extract_time_from_rid

@click.command
@click.argument("rid")
def rid_dec(rid: str) -> None:
    print(extract_time_from_rid(rid).isoformat())
