from pathlib import Path
from PIL import Image
import click

from gtools.core.growtopia.rttex import RTTex
from gtools.core.wsl import windows_home


@click.command()
@click.argument("path", type=Path)
def texture(path: Path) -> None:
    if not path.is_absolute():
        path = windows_home() / "AppData/Local/Growtopia/game" / path

    arr = RTTex.from_file(path)
    if arr is not None:
        Image.fromarray(arr.get_mip(0).pixels).show()
