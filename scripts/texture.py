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

    if path.is_file():
        arr = RTTex.from_file(path)
        Image.fromarray(arr.get_mip(0).pixels).show()
    else:
        for file in path.glob("**/*.rttex"):
            if file.is_dir():
                file.mkdir(exist_ok=True)
                continue

            arr = RTTex.from_file(file)
            out = "out" / file.relative_to(path).with_suffix(".png")
            out.parent.mkdir(exist_ok=True)
            Image.fromarray(arr.get_mip(0).pixels).save(out)
            print(f"saved to {out}")
