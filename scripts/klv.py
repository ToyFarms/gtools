import click

from gtools.core.growtopia.crypto import generate_klv, generate_klv_android


@click.command
@click.argument("protocol")
@click.argument("version")
@click.argument("rid")
def klv(protocol: str, version: str, rid: str) -> None:
    print(f"windows: {generate_klv(protocol.encode(), version.encode(), rid.encode())}")
    print(f"android: {generate_klv_android(protocol.encode(), rid.encode())}")
