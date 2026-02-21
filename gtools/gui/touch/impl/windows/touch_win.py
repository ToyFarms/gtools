import ctypes
import logging
import glfw
from gtools.gui.touch.base import TouchRouterBase
from gtools.gui.touch.impl.windows.devices import HIDDevice, TouchDevice
from gtools.gui.touch.impl.windows.windows_def import (
    GWLP,
    HID_USAGE,
    RAWINPUT,
    RAWINPUTDEVICE,
    HID_USAGE_PAGE,
    RAWINPUTHEADER,
    RID,
    RIDEV,
    RIM,
    WM,
    WNDPROC,
    CallWindowProcW,
    GetRawInputData,
    RegisterRawInputDevices,
    SetWindowLongPtrW,
)
import ctypes.wintypes as wt


class WindowsTouchRouter(TouchRouterBase):
    logger = logging.getLogger("windows-touch-router")

    def __init__(self, window) -> None:
        super().__init__(window)

        self._hwnd = glfw.get_win32_window(window)
        self._dev_cache: dict[int, HIDDevice] = {}
        self._devices = [
            RAWINPUTDEVICE(
                usUsagePage=HID_USAGE_PAGE.DIGITIZER,
                usUsage=HID_USAGE.DIGITIZER_TOUCH_SCREEN,
                dwFlags=0,
                hwndTarget=self._hwnd,
            ),
            RAWINPUTDEVICE(
                usUsagePage=HID_USAGE_PAGE.DIGITIZER,
                usUsage=HID_USAGE.DIGITIZER_TOUCH_PAD,
                dwFlags=0,
                hwndTarget=self._hwnd,
            ),
        ]

        self._new_wndproc: ctypes._CFunctionType | None = None
        self._wndproc_ref: ctypes._CFunctionType | None = None
        self._old_wndproc: int | None = None

    def install(self) -> None:
        if not RegisterRawInputDevices(
            (RAWINPUTDEVICE * len(self._devices))(*self._devices),
            len(self._devices),
            ctypes.sizeof(RAWINPUTDEVICE),
        ):
            raise OSError(f"RegisterRawInputDevices failed: {ctypes.get_last_error()}")

        self.logger.debug(f"registered {len(self._devices)} devices on HWND {hex(self._hwnd)}")

        self._new_wndproc = WNDPROC(self._wndproc)
        self._wndproc_ref = self._new_wndproc

        old = SetWindowLongPtrW(self._hwnd, GWLP.WNDPROC, ctypes.cast(self._new_wndproc, ctypes.c_void_p).value)
        if old == 0 and (err := ctypes.get_last_error()) != 0:
            raise OSError(f"SetWindowLongPtrW failed: {err}")

        self._old_wndproc = old
        self.logger.debug(f"installed wndproc on HWND {self._hwnd} (old_wndproc={old})")

    def uninstall(self) -> None:
        devices: list[RAWINPUTDEVICE] = []
        for orig_dev in self._devices:
            dev = RAWINPUTDEVICE.from_buffer_copy(orig_dev)
            dev.dwFlags |= RIDEV.REMOVE
            dev.hwndTarget = None
            devices.append(dev)

        RegisterRawInputDevices(
            (RAWINPUTDEVICE * len(devices))(*devices),
            len(devices),
            ctypes.sizeof(RAWINPUTDEVICE),
        )

        SetWindowLongPtrW(self._hwnd, GWLP.WNDPROC, self._old_wndproc)
        self.logger.debug(f"uninstalled {len(devices)} devices from HWND {self._hwnd}")

    def _on_wm_input(self, lparam: int) -> None:
        handle = wt.HANDLE(lparam)

        cb_size = wt.UINT(0)
        GetRawInputData(
            handle,
            RID.INPUT,
            None,
            ctypes.byref(cb_size),
            ctypes.sizeof(RAWINPUTHEADER),
        )
        if cb_size.value == 0:
            return

        buf = (ctypes.c_ubyte * cb_size.value)()
        ret = GetRawInputData(
            handle,
            RID.INPUT,
            buf,
            ctypes.byref(cb_size),
            ctypes.sizeof(RAWINPUTHEADER),
        )
        if ret in (0, 0xFFFFFFFF):
            return

        ri = ctypes.cast(buf, ctypes.POINTER(RAWINPUT)).contents
        if ri.header.dwType != RIM.TYPEHID:
            return

        dev = self._get_device(int(ri.header.hDevice), TouchDevice)
        if dev is None:
            return

        report_size = ri.data.hid.dwSizeHid
        report_count = ri.data.hid.dwCount
        if report_size == 0 or report_count == 0:
            return

        for r in range(report_count):
            offset = ctypes.sizeof(RAWINPUTHEADER) + 8 + r * report_size
            for touch in dev.parse_report(bytes(buf[offset : offset + report_size])):
                self._queue.put(touch)

    def _get_device[T: HIDDevice](self, h_device: int, expected: type[T]) -> T | None:
        if h_device in self._dev_cache:
            dev = self._dev_cache[h_device]
        else:
            dev = HIDDevice.from_handle(h_device)
            if dev is None:
                self.logger.error(f"failed to parse hid device {h_device}")
                return

            self._dev_cache[h_device] = dev

        if isinstance(dev, expected):
            return dev
        else:
            self.logger.warning(f"type mismatch for hDevice {h_device}: expected {expected.__name__} but got {dev.__class__.__name__}")

    def _wndproc(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        if msg == WM.INPUT:
            try:
                self._on_wm_input(lparam)
            except Exception:
                self.logger.exception("unhandled exception in WM_INPUT handler")

        return CallWindowProcW(self._old_wndproc, hwnd, msg, wparam, lparam)
