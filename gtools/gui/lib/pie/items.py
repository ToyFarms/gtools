import enum
from typing import Any, Callable, Sequence

from imgui_bundle import imgui

from gtools.gui.lib.pie.intent import Spring

RGBA = tuple[int, int, int, int]
Flag = bool | Callable[[], bool]


class Activation(enum.Enum):
    CLOSE = 0  # close the menu (default)
    KEEP = 1  # stay open (menu becomes "latched": click to choose, Esc to cancel)


def _resolve(v: Flag) -> bool:
    return bool(v() if callable(v) else v)


class PieItem:
    is_branch = False

    def __init__(
        self,
        label: str,
        *,
        icon: str | None = None,
        enabled: Flag = True,
        visible: Flag = True,
        color: RGBA | None = None,
        on_hover: Callable[[], Any] | None = None,
        data: Any = None,
    ):
        self.label, self.icon, self.color = label, icon, color
        self.enabled, self.visible, self.on_hover, self.data = enabled, visible, on_hover, data

    def is_enabled(self) -> bool:
        return _resolve(self.enabled)

    def is_visible(self) -> bool:
        return _resolve(self.visible)

    def activate(self, menu) -> Activation | None:
        return Activation.CLOSE


class Button(PieItem):
    def __init__(self, label: str, on_select: Callable[[], Any] | None = None, **kw):
        super().__init__(label, **kw)
        self.on_select = on_select

    def __call__(self, fn: Callable[[], Any]) -> Callable[[], Any]:
        self.on_select = fn
        return fn

    def activate(self, menu):
        if self.on_select:
            menu._call(self.on_select)
        return Activation.CLOSE


class TextInput(PieItem):
    def __init__(
        self,
        label: str,
        on_submit: Callable[[str], Any] | None = None,
        *,
        on_change: Callable[[str], Any] | None = None,
        on_cancel: Callable[[], Any] | None = None,
        placeholder: str = "",
        width: float = 300.0,
        keep_text: bool = False,
        close_on_submit: bool = True,
        **kw,
    ):
        super().__init__(label, **kw)
        self.on_submit, self.on_change, self.on_cancel = on_submit, on_change, on_cancel
        self.placeholder = placeholder or label
        self.width, self.keep_text, self.close_on_submit = width, keep_text, close_on_submit
        self.text = ""

    def activate(self, menu):
        menu._begin_input(self)
        return Activation.KEEP


class Panel:
    _next_id = 0

    def __init__(
        self,
        title: str,
        draw: Callable[["Panel"], Any] | None = None,
        *,
        size: tuple[float, float] = (360, 260),
        anchor: Any = "origin",
        closable: bool = True,
        on_close: Callable[[], Any] | None = None,
        data: Any = None,
    ):
        Panel._next_id += 1
        self.id = Panel._next_id
        self.title, self.draw, self.size, self.anchor = title, draw, size, anchor
        self.closable, self.on_close, self.data = closable, on_close, data
        self.open = True
        self._placed = False
        self._fade: Spring | None = None

    def close(self) -> None:
        self.open = False

    @staticmethod
    def list(title: str, rows: Sequence[Any] | Callable[[], Sequence[Any]], on_pick: Callable[[Any], Any] | None = None, *, empty_text: str = "No results", **kw) -> "Panel":
        panel = Panel(title, **kw)

        def draw(p: Panel):
            data = rows() if callable(rows) else rows
            if not data:
                imgui.text_disabled(empty_text)
                return

            for i, row in enumerate(data):
                res = imgui.selectable(f"{row}##{i}", False)
                if res[0] if isinstance(res, tuple) else res:
                    if on_pick:
                        on_pick(row)
                    p.close()

        panel.draw = draw
        return panel


class PanelItem(PieItem):
    def __init__(self, label: str, panel: Panel | Callable[[], Panel], **kw):
        super().__init__(label, **kw)
        self.panel = panel

    def activate(self, menu):
        p = self.panel() if callable(self.panel) else self.panel
        menu.show_panel(p)
        return Activation.CLOSE


class MenuBuilder:
    def _init_builder(self) -> None:
        self.children: list[PieItem] = []

    def add[T: PieItem](self, item: T) -> T:
        self.children.append(item)
        return item

    def clear(self) -> None:
        self.children.clear()

    def button(self, label: str, on_select: Callable[[], Any] | None = None, **kw):
        return self.add(Button(label, on_select, **kw))

    def submenu(self, label: str, **kw) -> "SubMenu":
        return self.add(SubMenu(label, **kw))

    def text_input(self, label: str, on_submit=None, **kw) -> TextInput:
        return self.add(TextInput(label, on_submit, **kw))

    def panel(self, label: str, panel: Panel | Callable[[], Panel], **kw) -> PanelItem:
        return self.add(PanelItem(label, panel, **kw))


class SubMenu(PieItem, MenuBuilder):
    is_branch = True

    def __init__(self, label: str, **kw):
        PieItem.__init__(self, label, **kw)
        self._init_builder()

    def is_enabled(self) -> bool:
        return super().is_enabled() and any(c.is_visible() for c in self.children)
