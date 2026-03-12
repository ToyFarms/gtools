from typing import Protocol

from gtools.gui.camera import Camera2D


class Renderer(Protocol):
    def draw(self, camera: Camera2D) -> None: ...
    def delete(self) -> None: ...
