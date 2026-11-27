import string
from typing import Set

from gtools.gui.lib.pie import win32

_NAMED = {
    "ctrl": 0x11,
    "control": 0x11,
    "lctrl": 0xA2,
    "rctrl": 0xA3,
    "shift": 0x10,
    "lshift": 0xA0,
    "rshift": 0xA1,
    "alt": 0x12,
    "lalt": 0xA4,
    "ralt": 0xA5,
    "win": 0x5B,
    "space": 0x20,
    "tab": 0x09,
    "capslock": 0x14,
    "backtick": 0xC0,
    "mouse_left": 0x01,
    "mouse_right": 0x02,
    "mouse_middle": 0x04,
    "mouse_x1": 0x05,
    "mouse_x2": 0x06,
}
_NAMED.update({c: ord(c.upper()) for c in string.ascii_lowercase + string.digits})
_NAMED.update({f"f{i}": 0x6F + i for i in range(1, 25)})

_FAMILY = {
    0x11: (0x11, 0xA2, 0xA3),
    0xA2: (0xA2, 0x11),
    0xA3: (0xA3, 0x11),
    0x10: (0x10, 0xA0, 0xA1),
    0xA0: (0xA0, 0x10),
    0xA1: (0xA1, 0x10),
    0x12: (0x12, 0xA4, 0xA5),
    0xA4: (0xA4, 0x12),
    0xA5: (0xA5, 0x12),
    0x5B: (0x5B, 0x5C),
}


def vk(key: str | int) -> int:
    if isinstance(key, int):
        return key
    try:
        return _NAMED[key.lower()]
    except KeyError:
        raise ValueError(f"Unknown key name {key!r}; use a VK code or one of {sorted(_NAMED)[:12]}...")


class Hold:
    def __init__(self, *keys: str | int, delay: float = 0, cancel_on_other_input: bool = True) -> None:
        if not keys:
            raise ValueError("Hold needs at least one key")

        self.codes = tuple(vk(k) for k in keys)
        self.delay = delay
        self.cancel_on_other_input = cancel_on_other_input
        self._excluded: Set[int] = set()
        for c in self.codes:
            self._excluded.update(_FAMILY.get(c, (c,)))

        self._scan = [c for c in range(0x01, 0xFF) if c not in self._excluded]

    def is_down(self) -> bool:
        return all(win32.key_down(c) for c in self.codes)

    def interference(self) -> bool:
        if not self.cancel_on_other_input:
            return False

        return any(win32.key_down(c) for c in self._scan)
