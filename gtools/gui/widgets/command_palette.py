from dataclasses import dataclass
from typing import Callable, Optional, Union

from imgui_bundle import imgui, ImVec2, ImVec4


def fuzzy_score(query: str, text: str) -> tuple[bool, int, list[int]]:
    q = query.lower()
    t = text.lower()
    if not q:
        return True, 0, []

    indices: list[int] = []
    ti = 0
    consecutive = 0
    score = 0

    for ch in q:
        found = False
        while ti < len(t):
            if t[ti] == ch:
                indices.append(ti)
                if len(indices) > 1 and indices[-1] == indices[-2] + 1:
                    consecutive += 1
                    score += 5 * consecutive
                else:
                    consecutive = 0

                if ti == 0 or t[ti - 1] in (" ", "/", "_", "-", ".", ">"):
                    score += 10
                score += 1

                ti += 1
                found = True
                break
            ti += 1

        if not found:
            return False, 0, []

    return True, score, indices


CommandCallback = Callable[[], Optional["PaletteLevel"]]
LabelType = Union[str, Callable[[], str]]


@dataclass
class Command:
    label: LabelType
    description: str = ""
    keybind: str = ""
    callback: Optional[CommandCallback] = None

    def get_label(self) -> str:
        return self.label() if callable(self.label) else self.label


@dataclass
class PaletteLevel:
    placeholder: str
    commands: list[Command]
    prefix: str = ""


class PaletteBuilder:
    def __init__(self, placeholder: str, *, prefix: str = "") -> None:
        self._placeholder = placeholder
        self._prefix = prefix
        self._commands: list[Command] = []

    def cmd(
        self,
        label: LabelType,
        *,
        keybind: str = "",
        description: str = "",
    ) -> Callable:
        def decorator(fn: Callable[[], None]) -> Callable[[], None]:
            self._commands.append(
                Command(
                    label=label,
                    keybind=keybind,
                    description=description,
                    callback=fn,
                )
            )
            return fn

        return decorator

    def submenu(
        self,
        label: str,
        *,
        keybind: str = "",
        description: str = "",
        placeholder: str = "",
    ) -> Callable:
        def decorator(fn: Callable[[PaletteBuilder], None]) -> Callable[[PaletteBuilder], None]:
            sub_placeholder = placeholder or f"{label}..."
            sub_builder = PaletteBuilder(sub_placeholder, prefix=label)
            fn(sub_builder)

            def open_sub() -> PaletteLevel:
                return sub_builder.build()

            self._commands.append(
                Command(
                    label=label,
                    keybind=keybind,
                    description=description,
                    callback=open_sub,
                )
            )
            return fn

        return decorator

    def list_submenu(
        self,
        label: str,
        items: list[str],
        *,
        action: Callable[[str], None],
        keybind: str = "",
        description: str = "sub-menu",
        placeholder: str = "",
    ) -> "PaletteBuilder":
        sub_placeholder = placeholder or f"select {label.lower()}..."

        def open_sub() -> PaletteLevel:
            cmds = [
                Command(
                    label=item,
                    callback=lambda i=item: action(i),
                )
                for item in items
            ]
            return PaletteLevel(
                placeholder=sub_placeholder,
                commands=cmds,
                prefix=label,
            )

        self._commands.append(
            Command(
                label=label,
                keybind=keybind,
                description=description,
                callback=open_sub,
            )
        )
        return self

    def build(self) -> PaletteLevel:
        return PaletteLevel(
            placeholder=self._placeholder,
            commands=list(self._commands),
            prefix=self._prefix,
        )


C_BG = ImVec4(0.18, 0.18, 0.18, 1.00)
C_BG_INPUT = ImVec4(0.12, 0.12, 0.12, 1.00)
C_BG_HOVER = ImVec4(0.25, 0.47, 0.72, 1.00)
C_BG_SEL = ImVec4(0.20, 0.44, 0.69, 1.00)
C_SEPARATOR = ImVec4(0.30, 0.30, 0.30, 1.00)
C_TEXT = ImVec4(0.85, 0.85, 0.85, 1.00)
C_TEXT_DIM = ImVec4(0.50, 0.50, 0.50, 1.00)
C_TEXT_MATCH = ImVec4(0.90, 0.75, 0.40, 1.00)
C_KEYBIND = ImVec4(0.52, 0.52, 0.52, 1.00)
C_BREADCRUMB = ImVec4(0.45, 0.75, 0.95, 1.00)
C_ACCENT = ImVec4(0.27, 0.62, 0.94, 1.00)


def v4_to_u32(v: ImVec4) -> int:
    r = int(v.x * 255) & 0xFF
    g = int(v.y * 255) & 0xFF
    b = int(v.z * 255) & 0xFF
    a = int(v.w * 255) & 0xFF
    return (a << 24) | (b << 16) | (g << 8) | r


FilteredCommand = tuple[Command, int, list[int], str]


class CommandPalette:
    def __init__(self) -> None:
        self.visible = False
        self._stack: list[PaletteLevel] = []
        self._query: str = ""
        self._selected_idx: int = 0
        self._focus_input = False
        self._filtered: list[FilteredCommand] = []
        self._scroll_to_selected = False
        self._dirty = True
        self._filter_dirty = True

    def is_dirty(self) -> bool:
        return self._dirty

    def clear_dirty(self) -> None:
        self._dirty = False

    def open(self, level: PaletteLevel) -> None:
        self._stack = [level]
        self._query = ""
        self._selected_idx = 0
        self._focus_input = True
        self.visible = True
        self._filter_dirty = True
        self._dirty = True

    def close(self) -> None:
        self.visible = False
        self._stack.clear()

    def push_level(self, level: PaletteLevel) -> None:
        self._stack.append(level)
        self._query = ""
        self._selected_idx = 0
        self._focus_input = True
        self._rebuild_filter()

    def pop_level(self) -> None:
        if len(self._stack) > 1:
            self._stack.pop()
            self._query = ""
            self._selected_idx = 0
            self._focus_input = True
            self._rebuild_filter()
        else:
            self.close()

    def _current_level(self) -> Optional[PaletteLevel]:
        return self._stack[-1] if self._stack else None

    def _rebuild_filter(self) -> None:
        level = self._current_level()
        if level is None:
            self._filtered = []
            return

        results: list[FilteredCommand] = []
        q = self._query
        for cmd in level.commands:
            label = cmd.get_label()
            matched, score, idxs = fuzzy_score(q, label)
            if matched:
                results.append((cmd, score, idxs, label))

        results.sort(key=lambda x: -x[1])
        self._filtered = results
        self._selected_idx = max(0, min(self._selected_idx, len(results) - 1))

    def _ensure_filter(self) -> None:
        if not self._filter_dirty:
            return
        self._rebuild_filter()
        self._filter_dirty = False

    def _execute_selected(self) -> None:
        if not self._filtered:
            return

        idx = self._selected_idx
        if idx < 0 or idx >= len(self._filtered):
            return

        cmd, _, _, _ = self._filtered[idx]
        if cmd.callback:
            result = cmd.callback()
            if isinstance(result, PaletteLevel):
                self.push_level(result)
            else:
                self.close()
        else:
            self.close()

        self._dirty = True

    def render(self) -> None:
        if not self.visible:
            return

        self._ensure_filter()

        io = imgui.get_io()
        vp = imgui.get_main_viewport()

        imgui.set_next_window_pos(ImVec2(0, 0))
        imgui.set_next_window_size(vp.size)
        imgui.set_next_window_bg_alpha(0.45)

        overlay_flags = imgui.WindowFlags_.no_decoration | imgui.WindowFlags_.no_inputs | imgui.WindowFlags_.no_saved_settings | imgui.WindowFlags_.no_focus_on_appearing
        imgui.begin("##palette_overlay", None, overlay_flags)
        imgui.end()

        palette_w = min(620.0, vp.size.x * 0.55)
        palette_x = (vp.size.x - palette_w) * 0.5
        palette_y = vp.size.y * 0.15

        imgui.set_next_window_pos(ImVec2(palette_x, palette_y), imgui.Cond_.always)
        imgui.set_next_window_size(ImVec2(palette_w, 0), imgui.Cond_.always)

        imgui.push_style_color(imgui.Col_.window_bg, C_BG)
        imgui.push_style_color(imgui.Col_.border, C_SEPARATOR)
        imgui.push_style_color(imgui.Col_.frame_bg, C_BG_INPUT)
        imgui.push_style_color(imgui.Col_.frame_bg_hovered, C_BG_INPUT)
        imgui.push_style_color(imgui.Col_.frame_bg_active, C_BG_INPUT)
        imgui.push_style_color(imgui.Col_.text, C_TEXT)
        imgui.push_style_color(imgui.Col_.header, C_BG_SEL)
        imgui.push_style_color(imgui.Col_.header_hovered, C_BG_HOVER)
        imgui.push_style_color(imgui.Col_.header_active, C_BG_SEL)
        imgui.push_style_color(imgui.Col_.scrollbar_bg, C_BG)
        imgui.push_style_color(imgui.Col_.scrollbar_grab, C_SEPARATOR)
        imgui.push_style_color(imgui.Col_.scrollbar_grab_hovered, C_TEXT_DIM)
        imgui.push_style_color(imgui.Col_.scrollbar_grab_active, C_TEXT)

        imgui.push_style_var(imgui.StyleVar_.window_rounding, 6.0)
        imgui.push_style_var(imgui.StyleVar_.window_padding, ImVec2(0, 0))
        imgui.push_style_var(imgui.StyleVar_.item_spacing, ImVec2(0, 0))
        imgui.push_style_var(imgui.StyleVar_.frame_padding, ImVec2(12, 8))

        win_flags = (
            imgui.WindowFlags_.no_title_bar
            | imgui.WindowFlags_.no_resize
            | imgui.WindowFlags_.no_move
            | imgui.WindowFlags_.no_scrollbar
            | imgui.WindowFlags_.no_saved_settings
            | imgui.WindowFlags_.always_auto_resize
        )

        imgui.begin("##command_palette", None, win_flags)

        level = self._current_level()
        if level is None:
            imgui.end()
            imgui.pop_style_var(4)
            imgui.pop_style_color(13)
            return

        if len(self._stack) > 1:
            imgui.push_style_var(imgui.StyleVar_.frame_padding, ImVec2(12, 5))
            imgui.push_style_color(imgui.Col_.child_bg, ImVec4(0.13, 0.13, 0.13, 1.0))
            imgui.begin_child("##breadcrumbs", ImVec2(-1, 24), False, imgui.WindowFlags_.no_scrollbar)
            imgui.set_cursor_pos_y((24 - imgui.get_text_line_height()) * 0.5)
            for i, lvl in enumerate(self._stack):
                imgui.push_style_color(imgui.Col_.text, C_BREADCRUMB)
                imgui.text(lvl.prefix if lvl.prefix else lvl.placeholder)
                imgui.pop_style_color()
                if i < len(self._stack) - 1:
                    imgui.same_line()
                    imgui.push_style_color(imgui.Col_.text, C_TEXT_DIM)
                    imgui.text(" > ")
                    imgui.pop_style_color()
                    imgui.same_line()
            imgui.end_child()
            imgui.pop_style_color()
            imgui.pop_style_var()

            dl = imgui.get_window_draw_list()
            p = imgui.get_cursor_screen_pos()
            dl.add_line(ImVec2(p.x, p.y), ImVec2(p.x + palette_w, p.y), v4_to_u32(C_SEPARATOR), 1.0)

        imgui.push_style_var(imgui.StyleVar_.frame_padding, ImVec2(14, 10))
        imgui.push_style_color(imgui.Col_.frame_bg, C_BG_INPUT)
        imgui.set_next_item_width(-1)

        if self._focus_input:
            imgui.set_keyboard_focus_here()
            self._focus_input = False

        display_text = self._query if self._query else ""
        changed, new_query = imgui.input_text(
            "##palette_search",
            display_text,
            imgui.InputTextFlags_.callback_always | imgui.InputTextFlags_.no_undo_redo,
        )

        if not self._query:
            dl = imgui.get_window_draw_list()
            item_min = imgui.get_item_rect_min()
            pad = 14.0
            txt_y = item_min.y + (imgui.get_item_rect_size().y - imgui.get_text_line_height()) * 0.5
            dl.add_text(ImVec2(item_min.x + pad, txt_y), v4_to_u32(C_TEXT_DIM), level.placeholder)

        imgui.pop_style_color()
        imgui.pop_style_var()

        if changed and new_query != self._query:
            self._query = new_query
            self._selected_idx = 0
            self._filter_dirty = True
            self._dirty = True

        if imgui.is_key_pressed(imgui.Key.escape):
            self.pop_level()
        if imgui.is_key_pressed(imgui.Key.enter) or imgui.is_key_pressed(imgui.Key.keypad_enter):
            self._focus_input = True
            self._execute_selected()
        if imgui.is_key_pressed(imgui.Key.down_arrow):
            self._selected_idx = (self._selected_idx + 1) % max(1, len(self._filtered))
            self._scroll_to_selected = True
            self._dirty = True
        if imgui.is_key_pressed(imgui.Key.up_arrow):
            self._selected_idx = (self._selected_idx - 1) % max(1, len(self._filtered))
            self._scroll_to_selected = True
            self._dirty = True

        dl = imgui.get_window_draw_list()
        p = imgui.get_cursor_screen_pos()
        dl.add_line(ImVec2(p.x, p.y), ImVec2(p.x + palette_w, p.y), v4_to_u32(C_SEPARATOR), 1.0)
        imgui.dummy(ImVec2(0, 1))

        max_visible = 16
        item_h = min(36, imgui.get_text_line_height() + 8)
        list_h = min(len(self._filtered), max_visible) * item_h + 2

        if self._filtered:
            imgui.push_style_var(imgui.StyleVar_.item_spacing, ImVec2(0, 0))
            imgui.begin_child("##results", ImVec2(-1, list_h), False)

            total = len(self._filtered)
            scroll_y = imgui.get_scroll_y()

            visible_start = max(0, int(scroll_y // item_h) - 1)
            visible_end = min(total, int((scroll_y + list_h) // item_h) + 2)

            if self._scroll_to_selected:
                target = max(0.0, self._selected_idx * item_h - list_h * 0.5)
                imgui.set_scroll_y(target)
                self._scroll_to_selected = False

            if visible_start > 0:
                imgui.dummy(ImVec2(0, visible_start * item_h))

            for i in range(visible_start, visible_end):
                cmd, _score, match_idx, label = self._filtered[i]
                is_selected = i == self._selected_idx

                row_start = imgui.get_cursor_screen_pos()
                row_w = imgui.get_content_region_avail().x
                dl = imgui.get_window_draw_list()

                if is_selected:
                    dl.add_rect_filled(
                        ImVec2(row_start.x, row_start.y),
                        ImVec2(row_start.x + row_w, row_start.y + item_h),
                        v4_to_u32(C_BG_SEL),
                    )
                    dl.add_rect_filled(
                        ImVec2(row_start.x, row_start.y),
                        ImVec2(row_start.x + 2, row_start.y + item_h),
                        v4_to_u32(C_ACCENT),
                    )

                imgui.push_style_color(imgui.Col_.header, ImVec4(0, 0, 0, 0))
                imgui.push_style_color(imgui.Col_.header_hovered, ImVec4(0.25, 0.47, 0.72, 0.30))
                imgui.push_style_color(imgui.Col_.header_active, ImVec4(0, 0, 0, 0))
                clicked, _ = imgui.selectable(
                    f"##cmd_{i}",
                    is_selected,
                    imgui.SelectableFlags_.allow_overlap,
                    ImVec2(row_w, item_h),
                )
                imgui.pop_style_color(3)

                if clicked:
                    self._selected_idx = i
                    self._execute_selected()

                if (io.mouse_delta.x != 0 or io.mouse_delta.y != 0 or io.mouse_wheel != 0) and imgui.is_item_hovered() and not is_selected:
                    self._selected_idx = i
                    self._dirty = True

                text_h = imgui.get_text_line_height()
                content_y = row_start.y + (item_h - text_h) * 0.5
                x = row_start.x + 16.0

                idx_set = set(match_idx)
                for ci, ch in enumerate(label):
                    color = v4_to_u32(C_TEXT_MATCH) if ci in idx_set else v4_to_u32(C_TEXT)
                    dl.add_text(ImVec2(x, content_y), color, ch)
                    x += imgui.calc_text_size(ch).x

                if cmd.description:
                    desc = f" - {cmd.description}"
                    dl.add_text(ImVec2(x, content_y), v4_to_u32(C_TEXT_DIM), desc)

                if cmd.keybind:
                    kb_w = imgui.calc_text_size(cmd.keybind).x
                    kb_x = row_start.x + row_w - kb_w - 18
                    kb_y = row_start.y + (item_h - text_h) * 0.5
                    pill_pad_x, pill_pad_y = 5.0, 2.0
                    dl.add_rect_filled(
                        ImVec2(kb_x - pill_pad_x, kb_y - pill_pad_y),
                        ImVec2(kb_x + kb_w + pill_pad_x, kb_y + text_h + pill_pad_y),
                        v4_to_u32(ImVec4(0.08, 0.08, 0.08, 1.0)),
                        3.0,
                    )
                    dl.add_text(ImVec2(kb_x, kb_y), v4_to_u32(C_KEYBIND), cmd.keybind)

            if visible_end < total:
                imgui.dummy(ImVec2(0, (total - visible_end) * item_h))

            imgui.end_child()
            imgui.pop_style_var()

        elif self._query:
            imgui.push_style_color(imgui.Col_.text, C_TEXT_DIM)
            imgui.set_cursor_pos_x(14)
            imgui.dummy(ImVec2(0, 6))
            imgui.set_cursor_pos_x(14)
            imgui.text(f'no commands matching "{self._query}"')
            imgui.dummy(ImVec2(0, 8))
            imgui.pop_style_color()

        imgui.end()
        imgui.pop_style_var(4)
        imgui.pop_style_color(13)
