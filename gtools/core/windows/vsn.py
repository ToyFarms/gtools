import ctypes


def get_vsn(drive: str) -> str | None:
    volume_serial_number = ctypes.c_uint32()
    max_component_length = ctypes.c_uint32()
    file_system_flags = ctypes.c_uint32()

    res = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(drive),
        None,
        0,
        ctypes.byref(volume_serial_number),
        ctypes.byref(max_component_length),
        ctypes.byref(file_system_flags),
        None,
        0,
    )
    if res == 0:
        return
    return f"{volume_serial_number.value:08X}"


def get_any_vsn() -> str:
    for drive in "CDEFG":
        if vsn := get_vsn(f"{drive}:\\"):
            return vsn

    return ""
