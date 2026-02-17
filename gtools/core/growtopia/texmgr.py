from pathlib import Path
from typing import Protocol


class TexMgr[T](Protocol):
    def get(self, file: str | Path, x: int, y: int, w: int = 32, h: int = 32, flip_x: bool = False, copy: bool = False) -> T: ...
    def get_nocache(self, file: str | Path, x: int, y: int, w: int = 32, h: int = 32, flip_x: bool = False, copy: bool = False) -> T: ...
