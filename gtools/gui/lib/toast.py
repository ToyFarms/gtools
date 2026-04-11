from dataclasses import dataclass, field
from enum import Enum, auto
from typing import ClassVar

from imgui_bundle import imgui

_TOAST_DURATION = 4.0
_TOAST_FADE_TIME = 0.6
_TOAST_WIDTH = 300.0
_TOAST_PAD = 12.0
_TOAST_MARGIN_BETWEEN = 6.0


class ToastLevel(Enum):
    DEBUG = auto()
    INFO = auto()
    WARNING = auto()
    ERROR = auto()


_LEVEL_META: dict[ToastLevel, tuple[str, tuple[float, float, float]]] = {
    ToastLevel.DEBUG: ("DEBUG", (0.60, 0.60, 0.60)),
    ToastLevel.INFO: ("INFO", (0.40, 0.75, 1.00)),
    ToastLevel.WARNING: ("WARNING", (1.00, 0.75, 0.20)),
    ToastLevel.ERROR: ("ERROR", (1.00, 0.35, 0.35)),
}


@dataclass
class _Toast:
    title: str
    subtitle: str = ""
    description: str = ""
    level: ToastLevel = ToastLevel.INFO
    t: float = field(default_factory=lambda: _TOAST_DURATION)


class ToastManager:
    _instance: ClassVar["ToastManager | None"] = None

    def __init__(self) -> None:
        self._toasts: list[_Toast] = []

    @classmethod
    def get(cls) -> "ToastManager":
        if cls._instance is None:
            cls._instance = ToastManager()
        return cls._instance

    def push(
        self,
        title: str,
        subtitle: str = "",
        description: str = "",
        level: ToastLevel = ToastLevel.INFO,
    ) -> None:
        self._toasts.append(_Toast(title=title, subtitle=subtitle, description=description, level=level))

    def update(self, dt: float) -> None:
        for t in self._toasts:
            t.t -= dt
        self._toasts = [t for t in self._toasts if t.t > 0.0]

    def render(self) -> None:
        if not self._toasts:
            return

        viewport = imgui.get_main_viewport()
        vpos = viewport.work_pos
        vsize = viewport.work_size

        y_offset = _TOAST_PAD
        for toast in reversed(self._toasts):
            fade_in = min(1.0, (_TOAST_DURATION - toast.t) / _TOAST_FADE_TIME * 4.0)
            fade_out = min(1.0, toast.t / _TOAST_FADE_TIME)
            alpha = max(0.0, min(fade_in, fade_out))

            label, (r, g, b) = _LEVEL_META[toast.level]

            imgui.set_next_window_bg_alpha(alpha * 0.92)
            imgui.set_next_window_pos(
                (vpos.x + vsize.x - _TOAST_WIDTH - _TOAST_PAD, vpos.y + vsize.y - y_offset),
                cond=imgui.Cond_.always,
                pivot=(0.0, 1.0),
            )
            imgui.set_next_window_size((_TOAST_WIDTH, 0.0))

            flags = (
                imgui.WindowFlags_.no_docking
                | imgui.WindowFlags_.no_decoration
                | imgui.WindowFlags_.no_inputs
                | imgui.WindowFlags_.no_move
                | imgui.WindowFlags_.no_saved_settings
                | imgui.WindowFlags_.no_focus_on_appearing
                | imgui.WindowFlags_.no_nav
                | imgui.WindowFlags_.always_auto_resize
            )

            imgui.push_style_var(imgui.StyleVar_.window_rounding, 6.0)
            imgui.push_style_var(imgui.StyleVar_.window_padding, (10.0, 8.0))
            imgui.push_style_var(imgui.StyleVar_.item_spacing, (4.0, 3.0))

            imgui.begin(f"##toast_{id(toast)}", flags=flags)

            imgui.push_style_color(imgui.Col_.text, (r, g, b, alpha))
            imgui.text(f"[{label}]")
            imgui.pop_style_color()

            imgui.same_line()
            imgui.push_style_color(imgui.Col_.text, (1.0, 1.0, 1.0, alpha))
            imgui.text(toast.title)
            imgui.pop_style_color()

            if toast.subtitle:
                imgui.push_style_color(imgui.Col_.text, (0.75, 0.75, 0.75, alpha))
                imgui.text_disabled(toast.subtitle)
                imgui.pop_style_color()

            if toast.description:
                imgui.push_style_color(imgui.Col_.separator, (r, g, b, alpha * 0.4))
                imgui.separator()
                imgui.pop_style_color()

                imgui.push_style_color(imgui.Col_.text, (0.85, 0.85, 0.85, alpha * 0.9))
                imgui.text_wrapped(toast.description)
                imgui.pop_style_color()

            win_h = imgui.get_window_size().y
            imgui.end()

            imgui.pop_style_var(3)

            y_offset += win_h + _TOAST_MARGIN_BETWEEN


def push_toast(
    title: str,
    subtitle: str = "",
    description: str = "",
    level: ToastLevel = ToastLevel.INFO,
) -> None:
    ToastManager.get().push(title, subtitle, description, level)


def push_debug(title: str, subtitle: str = "", description: str = "") -> None:
    push_toast(title, subtitle, description, ToastLevel.DEBUG)


def push_info(title: str, subtitle: str = "", description: str = "") -> None:
    push_toast(title, subtitle, description, ToastLevel.INFO)


def push_warning(title: str, subtitle: str = "", description: str = "") -> None:
    push_toast(title, subtitle, description, ToastLevel.WARNING)


def push_error(title: str, subtitle: str = "", description: str = "") -> None:
    push_toast(title, subtitle, description, ToastLevel.ERROR)
