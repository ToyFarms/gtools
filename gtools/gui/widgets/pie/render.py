import math
from dataclasses import dataclass

from imgui_bundle import imgui

from gtools.gui.widgets.pie.intent import clamp, lerp, smoothstep

RGBA = tuple[int, int, int, int]
BACK = object()


@dataclass
class Theme:
    accent: RGBA = (92, 170, 255, 255)
    bubble: RGBA = (22, 24, 30, 232)
    bubble_hot: RGBA = (38, 44, 58, 245)
    text: RGBA = (238, 242, 248, 255)
    text_dim: RGBA = (150, 158, 172, 255)
    ring: RGBA = (255, 255, 255, 46)
    shadow: RGBA = (0, 0, 0, 120)
    backdrop: bool = True  # dim the whole monitor while the menu is open
    backdrop_dim: float = 0.20  # 0..1 darkening used when `backdrop` is on
    cancel: RGBA = (255, 96, 96, 255)  # colour of the screen-corner cancel zones
    ring_radius: float = 118.0  # px at scale 1.0
    item_radius: float = 36.0
    hub_radius: float = 7.0
    max_grow: float = 0.30  # extra bubble scale when the cursor is on top of it
    font_size: float = 17.0
    panel_bg: RGBA = (20, 22, 28, 238)
    panel_accent: RGBA = (92, 170, 255, 255)
    rounding: float = 14.0


def u32(c: RGBA, a: float = 1.0) -> int:
    r, g, b, al = c
    al = int(clamp(al * a, 0, 255))
    return (al << 24) | (int(b) << 16) | (int(g) << 8) | int(r)


def mix(c1: RGBA, c2: RGBA, t: float) -> RGBA:
    return tuple(int(lerp(a, b, t)) for a, b in zip(c1, c2))  # type: ignore[return-value]


class Painter:
    def __init__(self, theme: Theme) -> None:
        self.theme = theme
        self.scale = 1.0

    def text_size(self, text: str, size: float) -> tuple[float, float]:
        s = imgui.calc_text_size(text)
        k = size / imgui.get_font_size()
        return s.x * k, s.y * k

    def text(self, dl, cx: float, cy: float, text: str, size: float, rgba: RGBA, a: float):
        if a <= 0.01:
            return
        w, h = self.text_size(text, size)
        dl.add_text(imgui.get_font(), size, imgui.ImVec2(cx - w / 2, cy - h / 2), u32(rgba, a), text)

    def fit(self, text: str, size: float, max_w: float) -> tuple[str, float]:
        w, _ = self.text_size(text, size)
        if w <= max_w:
            return text, size
        size2 = size * max(0.72, max_w / w)
        if self.text_size(text, size2)[0] <= max_w:
            return text, size2
        while len(text) > 1 and self.text_size(text + "...", size2)[0] > max_w:
            text = text[:-1]
        return text.rstrip() + "...", size2


def draw_backdrop(dl, w: float, h: float, th: Theme, amount: float) -> None:
    a = th.backdrop_dim * clamp(amount) if th.backdrop else 0.0
    if a > 0.004:
        dl.add_rect_filled(imgui.ImVec2(0, 0), imgui.ImVec2(w, h), u32((0, 0, 0, 255), a))


def draw_level(dl, P: Painter, lv, off, st, fade: float) -> None:
    th, sc = P.theme, P.scale
    cx, cy = lv.origin[0] - off[0], lv.origin[1] - off[1]
    op = lv.open.x
    if op <= 0.002 or fade <= 0.002:
        return

    R = lv.radius
    a = clamp(op) * fade
    centre = imgui.ImVec2(cx, cy)
    n = max(len(lv.slots), 1)

    for k in range(8, 0, -1):
        dl.add_circle_filled(centre, R * (0.5 + 0.1 * k) * clamp(op, 0, 1.1), u32(th.accent, 0.016 * a), 48)
    dl.add_circle(centre, R * op, u32(th.ring, a), 96, 1.5 * sc)

    if st is not None and st.index is not None:
        hot = clamp(lv.hot[st.index].x)
        ang = lv.angles[st.index]
        half = lv.sector * 0.5 * 0.92
        dl.path_arc_to(centre, R * op + th.item_radius * sc * 1.38, ang - half, ang + half, 24)
        dl.path_stroke(u32(th.accent, 0.8 * hot * a), thickness=3.0 * sc)

    if st is not None and st.distance > 4 * sc:
        ux, uy = st.dx / st.distance, st.dy / st.distance
        length = min(st.distance, R * 0.5)
        k = clamp(st.distance / (40 * sc))
        end = imgui.ImVec2(cx + ux * length, cy + uy * length)
        dl.add_line(centre, end, u32(th.accent, 0.55 * k * a), 2.5 * sc)
        dl.add_circle_filled(end, 3.5 * sc, u32(th.accent, 0.9 * k * a), 16)

    dl.add_circle_filled(centre, th.hub_radius * sc * 1.5 * op, u32(th.bubble, 0.9 * a), 24)
    dl.add_circle(centre, th.hub_radius * sc * 1.5 * op, u32(th.accent, 0.7 * a), 24, 1.5 * sc)

    for i, slot in enumerate(lv.slots):
        ang = lv.angles[i]
        ca, sa = math.cos(ang), math.sin(ang)
        chosen = lv.chosen == i
        eo = 1.0 if chosen else clamp(op * 1.35 - 0.35 * i / n)
        hot = clamp(lv.hot[i].x)
        s = lv.scales[i].x
        pop = eo + (0.0 if chosen else max(0.0, op - 1.0))
        Rm = R * (1.0 + 0.07 * hot) * pop
        px, py = cx + ca * Rm, cy + sa * Rm
        is_back = slot is BACK
        enabled = is_back or slot.is_enabled()
        r = th.item_radius * sc * s * (0.45 + 0.55 * eo) * (0.7 if is_back else 1.0)
        ia = (fade if chosen else a) * eo * (1.0 if enabled else 0.38)
        if ia <= 0.01:
            continue

        accent = th.accent if is_back or slot.color is None else slot.color
        p = imgui.ImVec2(px, py)

        dl.add_circle_filled(imgui.ImVec2(px, py + 4 * sc), r * 1.04, u32(th.shadow, ia), 40)
        fill = mix(th.bubble, th.bubble_hot, hot)
        dl.add_circle_filled(p, r, u32(fill, ia), 48)
        if not is_back and slot.color is not None:  # tinted wash for coloured items
            dl.add_circle_filled(p, r, u32(accent, 0.10 * ia), 48)
        dl.add_circle(p, r, u32(accent, (0.22 + 0.78 * hot) * ia), 48, (1.5 + 1.2 * hot) * sc)

        if is_back:
            tip = imgui.ImVec2(px + ca * r * 0.30, py + sa * r * 0.30)
            bx, by = px - ca * r * 0.12, py - sa * r * 0.12
            nx, ny = -sa, ca
            dl.add_line(tip, imgui.ImVec2(bx + nx * r * 0.34, by + ny * r * 0.34), u32(th.text, ia), 2.2 * sc)
            dl.add_line(tip, imgui.ImVec2(bx - nx * r * 0.34, by - ny * r * 0.34), u32(th.text, ia), 2.2 * sc)
            continue

        size = th.font_size * sc * (0.92 + 0.2 * min(s, 1.4))
        tc = th.text
        if slot.icon:
            P.text(dl, px, py - r * 0.24, slot.icon, size * 1.5, tc, ia)
            t, sz = P.fit(slot.label, size * 0.76, r * 1.7)
            P.text(dl, px, py + r * 0.46, t, sz, th.text_dim if not hot > 0.5 else tc, ia)
        else:
            t, sz = P.fit(slot.label, size, r * 1.78)
            P.text(dl, px, py, t, sz, tc, ia)

        if slot.is_branch:  # small outward arrowhead = "opens a nested pie"
            bx, by = px + ca * (r + 5 * sc), py + sa * (r + 5 * sc)
            tx, ty = px + ca * (r + 13 * sc), py + sa * (r + 13 * sc)
            nx, ny = -sa * 5.5 * sc, ca * 5.5 * sc
            dl.add_triangle_filled(imgui.ImVec2(tx, ty), imgui.ImVec2(bx + nx, by + ny), imgui.ImVec2(bx - nx, by - ny), u32(accent, (0.55 + 0.45 * hot) * ia))


def draw_ghost(dl, P: Painter, lv, off, child_origin, amount: float, fade: float) -> None:
    th, sc = P.theme, P.scale
    a = clamp(amount) * fade
    if a <= 0.01:
        return

    cx, cy = lv.origin[0] - off[0], lv.origin[1] - off[1]
    centre = imgui.ImVec2(cx, cy)
    k = 0.5
    dl.add_line(centre, imgui.ImVec2(child_origin[0] - off[0], child_origin[1] - off[1]), u32(th.accent, 0.28 * a), 2.0 * sc)
    dl.add_circle(centre, lv.radius * k, u32(th.ring, 0.55 * a), 64, 1.2 * sc)
    for i, slot in enumerate(lv.slots):
        ang = lv.angles[i]
        pos = imgui.ImVec2(cx + math.cos(ang) * lv.radius * k, cy + math.sin(ang) * lv.radius * k)
        if i == lv.entered:
            dl.add_circle_filled(pos, 8 * sc, u32(th.accent, 0.9 * a), 20)
        else:
            dl.add_circle_filled(pos, 4.5 * sc, u32(th.text_dim, 0.5 * a), 16)
    dl.add_circle_filled(centre, 4 * sc, u32(th.accent, 0.8 * a), 16)


_CORNER_ARCS = ((0.0, math.pi / 2), (math.pi / 2, math.pi), (math.pi, 1.5 * math.pi), (1.5 * math.pi, math.tau))  # TL, TR, BR, BL
_CORNER_IN = ((1, 1), (-1, 1), (-1, -1), (1, -1))  # unit step into the screen


def draw_corners(dl, P: Painter, zones, off, fade: float) -> None:
    th, sc = P.theme, P.scale
    if fade <= 0.01:
        return

    R = zones.cfg.radius * sc
    for i, (px, py) in enumerate(zones.points):
        e = smoothstep(zones.prox[i].x)
        r = R * e
        if r < 2.0:
            continue
        hot = clamp(zones.hot[i].x)
        a = fade * e
        c = imgui.ImVec2(px - off[0], py - off[1])
        a0, a1 = _CORNER_ARCS[i]
        dl.path_line_to(c)
        dl.path_arc_to(c, r, a0, a1, 32)
        dl.path_fill_convex(u32(th.cancel, (0.10 + 0.32 * hot) * a))
        dl.path_arc_to(c, r, a0, a1, 32)
        dl.path_stroke(u32(th.cancel, (0.35 + 0.55 * hot) * a), thickness=2.0 * sc)
        if r > 24 * sc:
            sx, sy = _CORNER_IN[i]
            d = r * 0.52 * 0.7071
            mx, my = c.x + sx * d, c.y + sy * d
            k = r * 0.13 * (0.8 + 0.4 * hot)
            col = u32(th.cancel, (0.5 + 0.5 * hot) * a)
            dl.add_line(imgui.ImVec2(mx - k, my - k), imgui.ImVec2(mx + k, my + k), col, 2.4 * sc)
            dl.add_line(imgui.ImVec2(mx - k, my + k), imgui.ImVec2(mx + k, my - k), col, 2.4 * sc)
