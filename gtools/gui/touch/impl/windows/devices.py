from abc import ABC, abstractmethod
import ctypes
import ctypes.wintypes as wt
import logging
from typing import ClassVar
import time

from gtools.gui.touch.base import TouchContactEvent
from gtools.gui.touch.impl.windows.windows_def import (
    HID_USAGE,
    HID_USAGE_PAGE,
    HIDP_BUTTON_CAPS,
    HIDP_CAPS,
    HIDP_STATUS,
    HIDP_VALUE_CAPS,
    RIDI,
    SM,
    GetRawInputDeviceInfoW,
    GetSystemMetrics,
    HidP_GetButtonCaps,
    HidP_GetCaps,
    HidP_GetUsageValue,
    HidP_GetUsages,
    HidP_GetValueCaps,
    HidP_Input,
)


class HIDDevice(ABC):
    REGISTER_HINT: ClassVar[tuple[HID_USAGE_PAGE | None, HID_USAGE | None]] = (None, None)
    logger = logging.getLogger("hid-device")

    def __init__(self, ppd_buf: ctypes.Array[ctypes.c_ubyte], ppd_ptr: ctypes.c_void_p, caps: HIDP_CAPS):
        self._ppd_buf = ppd_buf
        self.ppd_ptr = ppd_ptr
        self.caps = caps

    @abstractmethod
    @classmethod
    def deserialize(
        cls,
        h_device: int,
        ppd_buf: ctypes.Array[ctypes.c_ubyte],
        ppd_ptr: ctypes.c_void_p,
        caps: HIDP_CAPS,
        value_caps: list[HIDP_VALUE_CAPS],
        button_caps: list[HIDP_BUTTON_CAPS],
    ) -> "HIDDevice | None": ...

    @classmethod
    def from_handle(cls, h_device: int) -> "HIDDevice | None":
        cb = wt.UINT(0)
        GetRawInputDeviceInfoW(h_device, RIDI.PREPARSEDDATA, None, ctypes.byref(cb))
        if cb.value == 0:
            cls.logger.error(f"GetRawInputDeviceInfo(PREPARSED) failed for hDevice={h_device}")
            return

        ppd_buf = (ctypes.c_ubyte * cb.value)()
        ret = GetRawInputDeviceInfoW(h_device, RIDI.PREPARSEDDATA, ppd_buf, ctypes.byref(cb))
        if ret == 0xFFFFFFFF:
            cls.logger.error(f"GetRawInputDeviceInfo(PREPARSED) failed for hDevice={h_device}: {ret}")
            return

        ppd_ptr = ctypes.cast(ppd_buf, ctypes.c_void_p)
        caps = HIDP_CAPS()
        if (err := HidP_GetCaps(ppd_ptr, ctypes.byref(caps))) != HIDP_STATUS.SUCCESS:
            cls.logger.error(f"HidP_GetCaps failed: {err}")
            return

        n_vc = ctypes.c_ushort(caps.NumberInputValueCaps)
        vc_arr = (HIDP_VALUE_CAPS * max(n_vc.value, 1))()
        if (err := HidP_GetValueCaps(HidP_Input, vc_arr, ctypes.byref(n_vc), ppd_ptr)) != HIDP_STATUS.SUCCESS:
            cls.logger.error(f"HidP_GetValueCaps failed: {err}")
            return

        n_bc = ctypes.c_ushort(caps.NumberInputButtonCaps)
        bc_arr = (HIDP_BUTTON_CAPS * max(n_bc.value, 1))()
        HidP_GetButtonCaps(HidP_Input, bc_arr, ctypes.byref(n_bc), ppd_ptr)

        usage_page = HID_USAGE_PAGE(caps.UsagePage)
        usage = HID_USAGE(caps.Usage) if caps.Usage is not None else None

        device_cls = _DEVICE_REGISTRY.get((usage_page, usage))
        if device_cls is None:
            device_cls = _DEVICE_REGISTRY.get((usage_page, None))
        if device_cls is None:
            device_cls = GenericHIDDevice

        return device_cls.deserialize(h_device, ppd_buf, ppd_ptr, caps, vc_arr[:], bc_arr[:])


_DEVICE_REGISTRY: dict[tuple[HID_USAGE_PAGE, HID_USAGE | None], type[HIDDevice]] = {}


def register_device_class(usage_page: HID_USAGE_PAGE, usage: HID_USAGE | None = None):
    def _decorator[T: HIDDevice](device_cls: type[T]) -> type[T]:
        _DEVICE_REGISTRY[(usage_page, usage)] = device_cls
        device_cls.REGISTER_HINT = (usage_page, usage)
        return device_cls

    return _decorator


class GenericHIDDevice(HIDDevice):
    __slots__ = ["value_caps", "button_caps"]

    def __init__(
        self,
        ppd_buf: ctypes.Array[ctypes.c_ubyte],
        ppd_ptr: ctypes.c_void_p,
        caps: HIDP_CAPS,
        value_caps: list[HIDP_VALUE_CAPS],
        button_caps: list[HIDP_BUTTON_CAPS],
    ) -> None:
        super().__init__(ppd_buf, ppd_ptr, caps)
        self.value_caps = value_caps
        self.button_caps = button_caps

    @classmethod
    def deserialize(
        cls,
        h_device: int,
        ppd_buf: ctypes.Array[ctypes.c_ubyte],
        ppd_ptr: ctypes.c_void_p,
        caps: HIDP_CAPS,
        value_caps: list[HIDP_VALUE_CAPS],
        button_caps: list[HIDP_BUTTON_CAPS],
    ) -> "GenericHIDDevice":
        inst = cls(ppd_buf, ppd_ptr, caps, value_caps, button_caps)
        return inst


@register_device_class(HID_USAGE_PAGE.DIGITIZER, None)
class TouchDevice(HIDDevice):
    __slots__ = ["is_touchpad", "usage", "contact_lcs", "x_range", "y_range", "has_tip_lc", "count_lc", "scr_w", "scr_h"]
    logger = logging.getLogger("touch-device")

    def __init__(self, ppd_buf: ctypes.Array[ctypes.c_ubyte], ppd_ptr: ctypes.c_void_p, caps: HIDP_CAPS) -> None:
        super().__init__(ppd_buf, ppd_ptr, caps)

        self.is_touchpad: bool = False
        self.usage = 0
        self.contact_lcs: list[int] = []
        self.x_range = (0, 0)
        self.y_range = (0, 0)
        self.has_tip_lc: set[int] = set()
        self.count_lc = -1
        self.scr_w = 0
        self.scr_h = 0

    @classmethod
    def deserialize(
        cls,
        h_device: int,
        ppd_buf: ctypes.Array[ctypes.c_ubyte],
        ppd_ptr: ctypes.c_void_p,
        caps: HIDP_CAPS,
        value_caps: list[HIDP_VALUE_CAPS],
        button_caps: list[HIDP_BUTTON_CAPS],
    ) -> "TouchDevice | None":
        if caps.UsagePage != HID_USAGE_PAGE.DIGITIZER:
            got = HID_USAGE_PAGE(caps.UsagePage)
            cls.logger.warning(f"expected usage page DIGITIZER, got {got.name} ({hex(got.value)})")
            return

        if caps.Usage == HID_USAGE.DIGITIZER_TOUCH_SCREEN:
            is_touchpad = False
        elif caps.Usage == HID_USAGE.DIGITIZER_TOUCH_PAD:
            is_touchpad = True
        else:
            got = HID_USAGE(caps.Usage)
            cls.logger.warning(f"expected usage DIGITIZER_TOUCH_SCREEN or DIGITIZER_TOUCH_PAD, got {got.name} ({hex(got.value)})")
            return

        x_lc: dict[int, tuple[int, int]] = {}
        y_lc: dict[int, tuple[int, int]] = {}
        cid_lc: dict[int, tuple[int, int]] = {}
        count_lc: int = -1

        for vc in value_caps:
            lc = int(vc.LinkCollection)
            page = int(vc.UsagePage)

            if bool(vc.IsRange):
                continue

            usage = int(vc.u.NotRange.Usage)
            if page == HID_USAGE_PAGE.GENERIC:
                if usage == HID_USAGE.GENERIC_X:
                    x_lc[lc] = (int(vc.LogicalMin), int(vc.LogicalMax))
                elif usage == HID_USAGE.GENERIC_Y:
                    y_lc[lc] = (int(vc.LogicalMin), int(vc.LogicalMax))
            elif page == HID_USAGE_PAGE.DIGITIZER:
                if usage == HID_USAGE.DIGITIZER_CONTACT_IDENTIFIER:
                    cid_lc[lc] = (int(vc.LogicalMin), int(vc.LogicalMax))
                elif usage == HID_USAGE.DIGITIZER_CONTACT_COUNT:
                    count_lc = lc

        has_tip_lc: set[int] = set()
        for bc in button_caps:
            if int(bc.UsagePage) != HID_USAGE_PAGE.DIGITIZER:
                continue
            if bool(bc.IsRange):
                if int(bc.u.Range.UsageMin) <= HID_USAGE.DIGITIZER_TIP_SWITCH <= int(bc.u.Range.UsageMax):
                    has_tip_lc.add(int(bc.LinkCollection))
            else:
                if int(bc.u.NotRange.Usage) == HID_USAGE.DIGITIZER_TIP_SWITCH:
                    has_tip_lc.add(int(bc.LinkCollection))

        contact_lcs = sorted(set(x_lc.keys()) & set(y_lc.keys()) & set(cid_lc.keys()))
        if not contact_lcs:
            cls.logger.warning(f"device is a digitizer but it doesn't support contant touch")
            return

        first = contact_lcs[0]
        x_range = x_lc[first]
        y_range = y_lc[first]

        scr_w = GetSystemMetrics(SM.CXVIRTUALSCREEN or GetSystemMetrics(0))
        scr_h = GetSystemMetrics(SM.CYVIRTUALSCREEN or GetSystemMetrics(1))

        inst = cls(ppd_buf, ppd_ptr, caps)
        inst.is_touchpad = is_touchpad
        inst.usage = int(caps.Usage)
        inst.contact_lcs = contact_lcs
        inst.x_range = x_range
        inst.y_range = y_range
        inst.has_tip_lc = has_tip_lc
        inst.count_lc = count_lc
        inst.scr_w = scr_w
        inst.scr_h = scr_h

        return inst

    def parse_report(self, report: bytes) -> list[TouchContactEvent]:
        contacts: list[TouchContactEvent] = []
        report_len = ctypes.c_ulong(len(report))

        for lc in self.contact_lcs:
            raw_cid = ctypes.c_ulong(0)
            status = HidP_GetUsageValue(
                HidP_Input,
                HID_USAGE_PAGE.DIGITIZER,
                lc,
                HID_USAGE.DIGITIZER_CONTACT_IDENTIFIER,
                ctypes.byref(raw_cid),
                self.ppd_ptr,
                report,
                report_len,
            )
            if status != HIDP_STATUS.SUCCESS:
                self.logger.debug(f"HidP_GetUsageValue(CONTACT_IDENTIFIER) lc={lc}: {status!r}")
                continue

            raw_x = ctypes.c_ulong(0)
            status = HidP_GetUsageValue(
                HidP_Input,
                HID_USAGE_PAGE.GENERIC,
                lc,
                HID_USAGE.GENERIC_X,
                ctypes.byref(raw_x),
                self.ppd_ptr,
                report,
                report_len,
            )
            if status != HIDP_STATUS.SUCCESS:
                self.logger.debug(f"HidP_GetUsageValue(X) lc={lc}: {status!r}")
                continue

            raw_y = ctypes.c_ulong(0)
            status = HidP_GetUsageValue(
                HidP_Input,
                HID_USAGE_PAGE.GENERIC,
                lc,
                HID_USAGE.GENERIC_Y,
                ctypes.byref(raw_y),
                self.ppd_ptr,
                report,
                report_len,
            )
            if status != HIDP_STATUS.SUCCESS:
                self.logger.debug(f"HidP_GetUsageValue(Y) lc={lc}: {status!r}")
                continue

            tip_active = False
            if lc in self.has_tip_lc:
                n_usages = ctypes.c_ulong(self.caps.NumberInputButtonCaps or 16)
                usage_list = (ctypes.c_ushort * n_usages.value)()
                status = HidP_GetUsages(
                    HidP_Input,
                    HID_USAGE_PAGE.DIGITIZER,
                    lc,
                    usage_list,
                    ctypes.byref(n_usages),
                    self.ppd_ptr,
                    report,
                    report_len,
                )
                if status == HIDP_STATUS.SUCCESS:
                    pressed = set(usage_list[: n_usages.value])
                    tip_active = int(HID_USAGE.DIGITIZER_TIP_SWITCH) in pressed
                elif status == HIDP_STATUS.BUFFER_TOO_SMALL:
                    self.logger.warning(f"HidP_GetUsages buffer too small for lc={lc}")
                    tip_active = True

            x_min, x_max = self.x_range
            y_min, y_max = self.y_range

            def _signed(raw: int, lo: int, hi: int) -> int:
                if lo < 0:
                    span = hi - lo + 1
                    bits = span.bit_length()
                    if raw >= (1 << (bits - 1)):
                        raw -= 1 << bits

                return raw

            lx = _signed(raw_x.value, x_min, x_max)
            ly = _signed(raw_y.value, y_min, y_max)

            x_span = x_max - x_min
            y_span = y_max - y_min

            norm_x = (lx - x_min) / x_span if x_span else 0.0
            norm_y = (ly - y_min) / y_span if y_span else 0.0

            norm_x = max(0.0, min(1.0, norm_x))
            norm_y = max(0.0, min(1.0, norm_y))

            x_px = int(norm_x * self.scr_w)
            y_px = int(norm_y * self.scr_h)

            contacts.append(
                TouchContactEvent(
                    contact_id=raw_cid.value,
                    norm_x=norm_x,
                    norm_y=norm_y,
                    x=x_px,
                    y=y_px,
                    tip_active=tip_active,
                    timestamp=time.monotonic(),
                )
            )

        return contacts
