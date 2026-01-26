import ctypes
from pathlib import Path
import platform


class DLL(ctypes.CDLL):
    def __init__(self, path: str | Path, name: str) -> None:
        self.name = self._make_name(name)
        self.path = Path(path, self.name)
        self._supported = False
        if self.path.exists():
            self._supported = True
            super().__init__(self.path)

    def _make_name(self, name: str) -> str:
        p = platform.system()
        if p == "Windows":
            return f"{name}.dll"
        elif p == "Darwin":
            return f"lib{name}.dylib"
        else:
            return f"lib{name}.so"

    @property
    def supported(self) -> bool:
        return self._supported
