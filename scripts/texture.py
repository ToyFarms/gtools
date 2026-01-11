from pathlib import Path
from PIL import Image
import click

from gtools.core.growtopia.rttex import get_image_buffer
from gtools.core.wsl import windows_home


@click.command()
@click.argument("path", type=Path)
def texture(path: Path) -> None:
    if not path.is_absolute():
        path = windows_home() / "AppData/Local/Growtopia/game" / path

    arr = get_image_buffer(str(path))
    if arr is not None:
        Image.fromarray(arr).show()
