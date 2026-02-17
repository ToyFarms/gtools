import sys
from typing import Callable
from pygame import Vector2
import pygame
from pygame.typing import Point

from gtools.core.growtopia.packet import NetPacket
from gtools.core.growtopia.world import World
from gtools.core.wsl import windows_home
from gtools.gui.render import Renderable
from gtools.gui.render_world import RenderWorld
from gtools.protogen.extension_pb2 import INTEREST_STATE_UPDATE, Interest
from gtools.protogen.state_pb2 import StateUpdate, StateUpdateWhat
from gtools.proxy.extension.sdk import Extension, dispatch_state


MIN_ZOOM = 0.1
MAX_ZOOM = 4.0
WHEEL_ZOOM_STEP = 1.12
KEY_PAN_SPEED = 600


class Camera:
    def __init__(self, screen_size: Vector2, offset: Vector2 | None = None, zoom: float = 1.0):
        self.size = Vector2(screen_size)
        self.offset = Vector2(offset) if offset is not None else Vector2(0, 0)
        self.zoom = float(zoom)

    def world_to_screen(self, world_pos: Vector2) -> Vector2:
        return (Vector2(world_pos) - self.offset) * self.zoom

    def screen_to_world(self, screen_pos: Vector2) -> Vector2:
        return Vector2(screen_pos) / self.zoom + self.offset

    def zoom_at(self, zoom_factor: float, screen_focus: Vector2) -> None:
        world_before = self.screen_to_world(screen_focus)
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * zoom_factor))
        self.offset = world_before - screen_focus / self.zoom

    def pan_by_screen_delta(self, delta_screen: Vector2) -> None:
        self.offset -= Vector2(delta_screen) / self.zoom

    def set_size(self, new_size: Vector2) -> None:
        self.size = Vector2(new_size)


class Gui(Extension):
    def __init__(self) -> None:
        super().__init__(name="gui", interest=[Interest(interest=INTEREST_STATE_UPDATE)])
        self.size = self.get_win_size()
        self.screen = self.setup_screen(self.size)
        self.clock = pygame.time.Clock()
        self.surf = pygame.Surface(self.size)

        self.entities: list[Renderable] = []
        self.camera = Camera(self.size, offset=Vector2(0, 0), zoom=1.0)
        self._panning = False
        self._last_mouse = Vector2(0, 0)

    def query_entity[T](self, type: type[T], where: Callable[[T], bool] = lambda _: True) -> T | None:
        for ent in self.entities:
            if isinstance(ent, type) and where(ent):
                return ent

    @dispatch_state
    def on_state_update(self, upd: StateUpdate) -> None:
        match upd.what:
            case StateUpdateWhat.STATE_MODIFY_WORLD:
                if world := self.query_entity(RenderWorld):
                    world.update(0)

    def setup_screen(self, size: Point) -> pygame.Surface:
        return pygame.display.set_mode(size, pygame.RESIZABLE | pygame.HWACCEL | pygame.DOUBLEBUF)

    def get_win_size(self) -> Vector2:
        desktop_sizes = pygame.display.get_desktop_sizes()
        return Vector2(desktop_sizes[0]).elementwise() * 0.5

    def handle_event(self, event: pygame.Event) -> None:
        match event.type:
            case pygame.VIDEORESIZE:
                self.size.x = event.w
                self.size.y = event.h
                self.screen = self.setup_screen(self.size)
                self.surf = pygame.Surface(self.size)
                self.camera.set_size(self.size)
            case pygame.QUIT:
                self.exit()
            case pygame.MOUSEWHEEL:
                mouse_screen = Vector2(pygame.mouse.get_pos())
                if event.y > 0:
                    factor = WHEEL_ZOOM_STEP**event.y
                else:
                    factor = (1.0 / WHEEL_ZOOM_STEP) ** (-event.y)
                self.camera.zoom_at(factor, mouse_screen)

            case pygame.MOUSEBUTTONDOWN:
                if event.button == pygame.BUTTON_LEFT:
                    self._panning = True
                    self._pan_button = event.button
                    self._last_mouse = Vector2(pygame.mouse.get_pos())

            case pygame.MOUSEBUTTONUP:
                if event.button == pygame.BUTTON_LEFT:
                    self._panning = False

            case pygame.MOUSEMOTION:
                if self._panning:
                    pos = Vector2(event.pos)
                    delta = pos - self._last_mouse
                    self.camera.pan_by_screen_delta(delta)
                    self._last_mouse = pos

    def exit(self) -> None:
        self.stop().wait_true()
        pygame.quit()
        sys.exit(0)

    def _draw_entity_with_camera(self, ent: Renderable) -> None:
        surf = ent.get_surface()
        if surf is None:
            return

        ent_pos_world = ent.pos
        if self.camera.zoom == 1.0:
            draw_surf = surf
        else:
            draw_surf = pygame.transform.rotozoom(surf, 0.0, self.camera.zoom)

        screen_pos = self.camera.world_to_screen(ent_pos_world)
        self.surf.blit(draw_surf, (int(screen_pos.x), int(screen_pos.y)))

    def draw(self) -> None:
        for ent in self.entities:
            if isinstance(ent, RenderWorld):
                view = ent.get_view_surface(self.camera, self.size, smooth=True)
                self.surf.blit(view, (0, 0))
            else:
                self._draw_entity_with_camera(ent)

    def run(self) -> None:
        self.start()
        while True:
            for e in pygame.event.get():
                self.handle_event(e)

            dt = self.clock.tick(60) / 1000.0
            keys = pygame.key.get_pressed()
            pan_dir = Vector2(0, 0)
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                pan_dir.x += 1
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                pan_dir.x -= 1
            if keys[pygame.K_w] or keys[pygame.K_UP]:
                pan_dir.y += 1
            if keys[pygame.K_s] or keys[pygame.K_DOWN]:
                pan_dir.y -= 1
            if pan_dir.length_squared() > 0:
                pan_dir = pan_dir.normalize()
                delta_screen = pan_dir * (KEY_PAN_SPEED * dt)
                self.camera.pan_by_screen_delta(delta_screen)

            self.surf.fill((0, 0, 0))
            self.draw()
            self.screen.blit(self.surf, (0, 0))
            pygame.display.flip()


if __name__ == "__main__":
    pygame.init()

    g = Gui()

    f = windows_home() / ".gtools/worlds" / sys.argv[1]
    pkt = NetPacket.deserialize(f.read_bytes())
    w = World.from_net(pkt.tank)
    g.entities.append(RenderWorld(w))

    if world := g.query_entity(RenderWorld):
        world.update(0)

    g.run()
