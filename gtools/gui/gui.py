from pygame import Vector2
import pygame
from pygame.typing import Point


class Gui:
    def __init__(self) -> None:
        self.size = self.get_win_size()
        self.screen = self.setup_screen(self.size)
        self.clock = pygame.time.Clock()
        self.surf = pygame.Surface(self.size)

    def setup_screen(self, size: Point) -> pygame.Surface:
        return pygame.display.set_mode(size, pygame.RESIZABLE | pygame.HWACCEL | pygame.DOUBLEBUF)

    def get_win_size(self) -> Vector2:
        desktop_sizes = pygame.display.get_desktop_sizes()
        return Vector2(desktop_sizes[0]).elementwise() * 0.5

    def handle_event(self, event: pygame.Event) -> None:
        match event.type:
            case pygame.VIDEORESIZE:
                self.screen = self.setup_screen((event.w, event.h))

                real_size = self.screen.get_size()
                self.size = Vector2(real_size)
                self.surf = pygame.Surface(real_size)

    def run(self) -> None:
        while True:
            for e in pygame.event.get():
                self.handle_event(e)

            self.surf.fill((0, 0, 0))
            self.screen.blit(self.surf)
            self.clock.tick(60)


if __name__ == "__main__":
    pygame.init()

    g = Gui()
    g.run()
