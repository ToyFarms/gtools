import colorsys
from dataclasses import dataclass, field
from enum import Enum, auto
import math

import pygame
from pygame import Vector2


class Align(Enum):
    START = auto()
    CENTER = auto()
    END = auto()


class Sizing(Enum):
    ABS = auto()
    GROW = auto()
    FIT = auto()
    PERCENT = auto()


class Axis(Enum):
    HORIZONTAL = auto()
    VERTICAL = auto()


@dataclass(slots=True)
class Unit:
    type: Sizing = Sizing.ABS
    value: float = 0


@dataclass(slots=True)
class BaseElement:
    computed_pos: Vector2 = field(default_factory=Vector2)
    computed_size: Vector2 = field(default_factory=Vector2)

    width: Unit = field(default_factory=Unit)
    height: Unit = field(default_factory=Unit)
    min: tuple[float, float] = field(default_factory=lambda: (0, 0))
    max: tuple[float, float] = field(default_factory=lambda: (math.inf, math.inf))
    axis: Axis = Axis.VERTICAL
    main_align: Align = Align.START
    cross_align: Align = Align.START
    gap: float = 0

    children: list["BaseElement"] = field(default_factory=list)

    def compute(self) -> None:
        main_is_horizontal = self.axis == Axis.HORIZONTAL
        avail_main = self.computed_size.x if main_is_horizontal else self.computed_size.y
        avail_cross = self.computed_size.y if main_is_horizontal else self.computed_size.x

        n = len(self.children)
        if n == 0:
            return

        fixed_main_sizes = [0.0] * n
        grow_weights = [0.0] * n
        cross_sizes = [0.0] * n

        for i, c in enumerate(self.children):
            main_const = c.width if main_is_horizontal else c.height
            cross_const = c.height if main_is_horizontal else c.width

            fixed_main_sizes[i] = c.resolve_unit(main_const, avail_main, Axis.HORIZONTAL if main_is_horizontal else Axis.VERTICAL)

            if main_const.type == Sizing.GROW:
                grow_weights[i] = main_const.value if main_const.value > 0 else 1.0

            cs = c.resolve_unit(cross_const, avail_cross, Axis.VERTICAL if main_is_horizontal else Axis.HORIZONTAL)
            cross_sizes[i] = cs

        total_fixed_main = sum(fixed_main_sizes) + max(0, (n - 1)) * self.gap
        remaining = max(0.0, avail_main - total_fixed_main)

        total_grow_weight = sum(grow_weights)
        if total_grow_weight == 0 and any((c.width.type == Sizing.GROW if main_is_horizontal else c.height.type == Sizing.GROW) for c in self.children):
            count_grow = sum(1 for c in self.children if (c.width.type == Sizing.GROW if main_is_horizontal else c.height.type == Sizing.GROW))
            if count_grow > 0:
                for i, c in enumerate(self.children):
                    main_const = c.width if main_is_horizontal else c.height
                    if main_const.type == Sizing.GROW:
                        grow_weights[i] = 1.0
                total_grow_weight = sum(grow_weights) or 1.0

        sizes_main = [0.0] * n
        for i, c in enumerate(self.children):
            main_const = c.width if main_is_horizontal else c.height
            if main_const.type == Sizing.GROW:
                weight = grow_weights[i]
                sizes_main[i] = remaining * (weight / total_grow_weight) if total_grow_weight > 0 else remaining / max(1, sum(1 for w in grow_weights if w > 0))
            else:
                sizes_main[i] = fixed_main_sizes[i]

        for i, c in enumerate(self.children):
            cross_const = c.height if main_is_horizontal else c.width
            if cross_const.type == Sizing.GROW:
                cross_sizes[i] = avail_cross

        for i, c in enumerate(self.children):
            if main_is_horizontal:
                w = sizes_main[i]
                h = cross_sizes[i]
            else:
                w = cross_sizes[i]
                h = sizes_main[i]

            w = max(c.min[0], min(w, c.max[0]))
            h = max(c.min[1], min(h, c.max[1]))

            c.computed_size = Vector2(w, h)

        total_main = sum(sizes_main) + max(0, (n - 1)) * self.gap
        if self.main_align == Align.START:
            offset = 0.0
        elif self.main_align == Align.CENTER:
            offset = (avail_main - total_main) / 2.0
        else:
            offset = avail_main - total_main

        for i, c in enumerate(self.children):
            if main_is_horizontal:
                x = self.computed_pos.x + offset
                if self.cross_align == Align.START:
                    y = self.computed_pos.y
                elif self.cross_align == Align.CENTER:
                    y = self.computed_pos.y + (avail_cross - c.computed_size.y) / 2
                else:
                    y = self.computed_pos.y + (avail_cross - c.computed_size.y)
                c.computed_pos = Vector2(x, y)
                offset += c.computed_size.x + self.gap
            else:
                y = self.computed_pos.y + offset
                if self.cross_align == Align.START:
                    x = self.computed_pos.x
                elif self.cross_align == Align.CENTER:
                    x = self.computed_pos.x + (avail_cross - c.computed_size.x) / 2
                else:
                    x = self.computed_pos.x + (avail_cross - c.computed_size.x)
                c.computed_pos = Vector2(x, y)
                offset += c.computed_size.y + self.gap

        for c in self.children:
            c.compute()

    def resolve_unit(self, unit: Unit, avail: float, axis: Axis) -> float:
        if unit.type == Sizing.ABS:
            return unit.value
        elif unit.type == Sizing.FIT:
            return self.compute_intrinsic(axis)
        elif unit.type == Sizing.PERCENT:
            return avail * unit.value
        elif unit.type == Sizing.GROW:
            return 0.0
        return 0.0

    def compute_intrinsic(self, axis: Axis) -> float:
        if self.axis == Axis.HORIZONTAL:
            if axis == Axis.HORIZONTAL:
                return sum(c.compute_intrinsic(Axis.HORIZONTAL) for c in self.children) + max(0, (len(self.children) - 1)) * self.gap
            else:
                return max((c.compute_intrinsic(Axis.VERTICAL) for c in self.children), default=0.0)
        else:
            if axis == Axis.VERTICAL:
                return sum(c.compute_intrinsic(Axis.VERTICAL) for c in self.children) + max(0, (len(self.children) - 1)) * self.gap
            else:
                return max((c.compute_intrinsic(Axis.HORIZONTAL) for c in self.children), default=0.0)


class Layout:
    def __init__(self, root: BaseElement):
        self.root = root

    def compute(self, size):
        if not isinstance(size, Vector2):
            size = Vector2(size[0], size[1])
        self.root.computed_pos = Vector2(0, 0)
        self.root.computed_size = Vector2(size.x, size.y)
        self.root.compute()


if __name__ == "__main__":

    def build_demo():
        root = BaseElement()
        root.axis = Axis.VERTICAL
        root.gap = 8
        root.main_align = Align.CENTER
        root.cross_align = Align.CENTER

        root.children = [
            BaseElement(
                width=Unit(Sizing.PERCENT, 0.9),
                height=Unit(Sizing.GROW),
                axis=Axis.HORIZONTAL,
                cross_align=Align.CENTER,
                gap=10,
                children=[
                    BaseElement(width=Unit(Sizing.GROW, 0.5), height=Unit(Sizing.PERCENT, 0.5)),
                    BaseElement(width=Unit(Sizing.GROW, 0.5), height=Unit(Sizing.PERCENT, 0.9), children=[
                        BaseElement(width=Unit(Sizing.GROW), height=Unit(Sizing.PERCENT, 0.25)),
                        BaseElement(width=Unit(Sizing.GROW), height=Unit(Sizing.GROW)),
                        BaseElement(width=Unit(Sizing.GROW), height=Unit(Sizing.GROW)),
                        BaseElement(width=Unit(Sizing.GROW), height=Unit(Sizing.GROW)),
                        BaseElement(width=Unit(Sizing.GROW), height=Unit(Sizing.GROW)),
                        BaseElement(width=Unit(Sizing.GROW), height=Unit(Sizing.GROW)),
                        BaseElement(width=Unit(Sizing.GROW), height=Unit(Sizing.PERCENT, 0.25)),
                    ]),
                    BaseElement(width=Unit(Sizing.GROW, 0.5), height=Unit(Sizing.PERCENT, 0.5)),
                ],
            ),
        ]

        return root

    def element_color(elem_id: int) -> tuple[int, int, int]:
        hue = (elem_id * 137.508) % 360 / 360.0
        r, g, b = colorsys.hsv_to_rgb(hue, 0.65, 0.95)
        return int(r * 255), int(g * 255), int(b * 255)

    def contrast_color(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
        r, g, b = rgb
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        return (0, 0, 0) if luminance > 140 else (255, 255, 255)

    def draw_element(surface, elem, level: str = ""):
        rect = pygame.Rect(
            int(elem.computed_pos.x),
            int(elem.computed_pos.y),
            int(elem.computed_size.x),
            int(elem.computed_size.y),
        )

        if rect.width <= 0 or rect.height <= 0:
            for i, c in enumerate(elem.children):
                draw_element(surface, c, level=f"{level}.{i}")
            return

        fill = element_color(id(elem))
        text_color = contrast_color(fill)

        pygame.draw.rect(surface, fill, rect)
        pygame.draw.rect(surface, text_color, rect, 2)

        min_dim = min(rect.width, rect.height)
        if min_dim >= 18:
            font_size = max(2, int(min_dim * 0.1))
            font = pygame.font.SysFont(None, font_size)

            text_surf = font.render(level, True, text_color)
            text_rect = text_surf.get_rect(center=rect.center)
            surface.blit(text_surf, text_rect)

        for i, c in enumerate(elem.children):
            draw_element(surface, c, level=f"{level}.{i}")

    def run_app():
        pygame.init()
        screen = pygame.display.set_mode((900, 600), pygame.RESIZABLE)
        clock = pygame.time.Clock()
        root = build_demo()
        layout = Layout(root)

        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.VIDEORESIZE:
                    screen = pygame.display.set_mode((event.w, event.h), pygame.RESIZABLE)
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    elif event.key == pygame.K_EQUALS:
                        pass
                    elif event.key == pygame.K_MINUS:
                        pass

            w, h = screen.get_size()
            layout.compute((w, h))

            screen.fill((30, 30, 30))
            draw_element(screen, root)
            pygame.display.flip()
            clock.tick(60)

        pygame.quit()

    run_app()
