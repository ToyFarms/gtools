from __future__ import annotations

import os
import platform
import random
import re
import shutil
import subprocess
import urllib.parse
from pathlib import Path
from typing import Callable, Protocol, Sequence
import ctypes

PathResult = str | list[str] | None
Filter = tuple[str, str]


def open_file(
    title: str = "Open File",
    start_dir: str | Path | None = None,
    filters: Sequence[Filter] | None = None,
    multiple: bool = False,
    parent: int | str | None = None,
) -> PathResult:
    return _get_backend().open_file(
        title=title,
        start_dir=_resolve_dir(start_dir),
        filters=list(filters or []),
        multiple=multiple,
        parent=parent,
    )


def save_file(
    title: str = "Save File",
    start_dir: str | Path | None = None,
    filters: Sequence[Filter] | None = None,
    default_name: str = "",
    parent: int | str | None = None,
) -> str | None:
    return _get_backend().save_file(
        title=title,
        start_dir=_resolve_dir(start_dir),
        filters=list(filters or []),
        default_name=default_name,
        parent=parent,
    )


def open_directory(
    title: str = "Select Directory",
    start_dir: str | Path | None = None,
    multiple: bool = False,
    parent: int | str | None = None,
) -> PathResult:
    return _get_backend().open_directory(
        title=title,
        start_dir=_resolve_dir(start_dir),
        multiple=multiple,
        parent=parent,
    )


OFN_READONLY = 0x00000001
OFN_OVERWRITEPROMPT = 0x00000002
OFN_HIDEREADONLY = 0x00000004
OFN_NOCHANGEDIR = 0x00000008
OFN_SHOWHELP = 0x00000010
OFN_ENABLEHOOK = 0x00000020
OFN_ENABLETEMPLATE = 0x00000040
OFN_ENABLETEMPLATEHANDLE = 0x00000080
OFN_NOVALIDATE = 0x00000100
OFN_ALLOWMULTISELECT = 0x00000200
OFN_EXTENSIONDIFFERENT = 0x00000400
OFN_PATHMUSTEXIST = 0x00000800
OFN_FILEMUSTEXIST = 0x00001000
OFN_CREATEPROMPT = 0x00002000
OFN_SHAREAWARE = 0x00004000
OFN_NOREADONLYRETURN = 0x00008000
OFN_NOTESTFILECREATE = 0x00010000
OFN_NONETWORKBUTTON = 0x00020000
OFN_NOLONGNAMES = 0x00040000
OFN_EXPLORER = 0x00080000
OFN_NODEREFERENCELINKS = 0x00100000
OFN_LONGNAMES = 0x00200000
OFN_ENABLEINCLUDENOTIFY = 0x00400000
OFN_ENABLESIZING = 0x00800000
OFN_DONTADDTORECENT = 0x02000000
OFN_FORCESHOWHIDDEN = 0x10000000
RETURNONLYFSDIRS = 0x0001
NEWDIALOGSTYLE = 0x0040
EDITBOX = 0x0010

FOS_OVERWRITEPROMPT = 0x2
FOS_STRICTFILETYPES = 0x4
FOS_NOCHANGEDIR = 0x8
FOS_PICKFOLDERS = 0x20
FOS_FORCEFILESYSTEM = 0x40
FOS_ALLNONSTORAGEITEMS = 0x80
FOS_NOVALIDATE = 0x100
FOS_ALLOWMULTISELECT = 0x200
FOS_PATHMUSTEXIST = 0x800
FOS_FILEMUSTEXIST = 0x1000
FOS_CREATEPROMPT = 0x2000
FOS_SHAREAWARE = 0x4000
FOS_NOREADONLYRETURN = 0x8000
FOS_NOTESTFILECREATE = 0x10000
FOS_HIDEMRUPLACES = 0x20000
FOS_HIDEPINNEDPLACES = 0x40000
FOS_NODEREFERENCELINKS = 0x100000
FOS_OKBUTTONNEEDSINTERACTION = 0x200000
FOS_DONTADDTORECENT = 0x2000000
FOS_FORCESHOWHIDDEN = 0x10000000
FOS_DEFAULTNOMINIMODE = 0x20000000
FOS_FORCEPREVIEWPANEON = 0x40000000
FOS_SUPPORTSTREAMABLEITEMS = 0x80000000

COINIT_APARTMENTTHREADED = 0
SIGDN_FILESYSPATH = 0x80058000
ERROR_CANCELLED_HR = ctypes.c_long(0x800704C7).value
S_OK = 0
CLSCTX_INPROC = 1

BFFM_INITIALIZED = 1
BFFM_SETSELECTIONW = 1126

# IUnknown
VTBL_ADDREF = 1
VTBL_RELEASE = 2
# IModalWindow
VTBL_SHOW = 3
# IFileDialog (extends IModalWindow)
VTBL_SET_FILE_TYPES = 4
VTBL_SET_FILE_TYPE_INDEX = 5
VTBL_SET_OPTIONS = 9
VTBL_SET_FOLDER = 12
VTBL_SET_FILE_NAME = 15
VTBL_SET_TITLE = 17
VTBL_GET_RESULT = 20
VTBL_SET_DEFAULT_EXTENSION = 22
# IFileOpenDialog (extends IFileDialog)
VTBL_GET_RESULTS = 27
# IShellItemArray
VTBL_ISHELLITEMARRAY_GET_COUNT = 7
VTBL_ISHELLITEMARRAY_GET_ITEM_AT = 8
# IShellItem
VTBL_ISHELLITEM_GET_DISPLAY_NAME = 5


def _resolve_dir(d: str | Path | None) -> str:
    if d is None:
        return os.getcwd()
    p = Path(d).expanduser().resolve()
    return str(p) if p.is_dir() else str(p.parent)


_BACKEND: _Backend | None = None


def _get_backend() -> "_Backend":
    global _BACKEND
    if _BACKEND is None:
        system = platform.system()
        if system == "Windows":
            _BACKEND = _WindowsBackend()
        elif system == "Darwin":
            _BACKEND = _MacOSBackend()
        else:
            _BACKEND = _LinuxBackend()
    return _BACKEND


class _Backend(Protocol):
    def open_file(self, *, title: str, start_dir: str, filters: list[Filter], multiple: bool, parent: int | str | None) -> PathResult:
        raise NotImplementedError

    def save_file(self, *, title: str, start_dir: str, filters: list[Filter], default_name: str, parent: int | str | None) -> str | None:
        raise NotImplementedError

    def open_directory(self, *, title: str, start_dir: str, multiple: bool, parent: int | str | None) -> PathResult:
        raise NotImplementedError


class _WindowsBackend(_Backend):
    _CLSID_FileOpenDialog = "{DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7}"
    _CLSID_FileSaveDialog = "{C0B4E2F3-BA21-4773-8DBA-335EC946EB8B}"
    _IID_IFileOpenDialog = "{D57C7288-D4AD-4768-BE02-9D969532D960}"
    _IID_IFileSaveDialog = "{84BCCD23-5FDE-4CDB-AEA4-AF64B83D78AB}"
    _IID_IShellItem = "{43826D1E-E718-42EE-BC55-A1E261C37BFE}"
    _IID_IShellItemArray = "{B63EA76D-1F85-456F-A19C-48159EFA858B}"

    def __init__(self) -> None:
        self._use_com = self._probe_com()

    @staticmethod
    def _probe_com() -> bool:
        try:
            hr = ctypes.windll.ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
            if hr in (S_OK, 1):
                ctypes.windll.ole32.CoUninitialize()
                return True
            return False
        except Exception:
            return False

    def open_file(self, *, title: str, start_dir: str, filters: list[Filter], multiple: bool, parent: int | str | None) -> PathResult:
        hwnd = int(parent) if isinstance(parent, int) else 0
        if self._use_com:
            return self._com_open_file(title, start_dir, filters, multiple, hwnd)
        return self._classic_open_file(title, start_dir, filters, multiple, hwnd)

    def save_file(self, *, title: str, start_dir: str, filters: list[Filter], default_name: str, parent: int | str | None) -> str | None:
        hwnd = int(parent) if isinstance(parent, int) else 0
        if self._use_com:
            return self._com_save_file(title, start_dir, filters, default_name, hwnd)
        return self._classic_save_file(title, start_dir, filters, default_name, hwnd)

    def open_directory(self, *, title: str, start_dir: str, multiple: bool, parent: int | str | None) -> PathResult:
        hwnd = int(parent) if isinstance(parent, int) else 0
        if self._use_com:
            return self._com_open_directory(title, start_dir, multiple, hwnd)
        return self._shell_browse_for_folder(title, start_dir, hwnd)

    @staticmethod
    def _parse_guid(s: str) -> ctypes.Structure:
        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", ctypes.c_ulong),
                ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort),
                ("Data4", ctypes.c_ubyte * 8),
            ]

        parts = s.strip("{}").split("-")
        g = GUID()
        g.Data1 = int(parts[0], 16)
        g.Data2 = int(parts[1], 16)
        g.Data3 = int(parts[2], 16)
        raw = bytes.fromhex(parts[3] + parts[4])
        g.Data4 = (ctypes.c_ubyte * 8)(*raw)
        return g

    @staticmethod
    def _vtbl(ptr: ctypes.c_void_p, index: int, restype: type, *argtypes: type) -> Callable:
        vt = ctypes.cast(
            ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0],
            ctypes.POINTER(ctypes.c_void_p),
        )
        fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vt[int(index)])

        def _bound(*args: object) -> object:
            return fn(ptr, *args)

        return _bound

    @staticmethod
    def _com_release(ptr: ctypes.c_void_p | None) -> None:
        if not ptr:
            return

        _WindowsBackend._vtbl(ptr, VTBL_RELEASE, ctypes.c_ulong)()

    def _com_create(self, clsid_str: str, iid_str: str) -> ctypes.c_void_p:
        ole32 = ctypes.windll.ole32
        ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)

        clsid = self._parse_guid(clsid_str)
        iid = self._parse_guid(iid_str)
        ptr = ctypes.c_void_p(0)

        hr = ole32.CoCreateInstance(
            ctypes.byref(clsid),
            None,
            CLSCTX_INPROC,
            ctypes.byref(iid),
            ctypes.byref(ptr),
        )
        if hr != S_OK:
            raise OSError(f"CoCreateInstance failed: HRESULT {hr:#010x}")
        return ptr

    def _make_shell_item(self, path: str) -> ctypes.c_void_p:
        iid = self._parse_guid(self._IID_IShellItem)
        ptr = ctypes.c_void_p(0)
        hr = ctypes.windll.shell32.SHCreateItemFromParsingName(path, None, ctypes.byref(iid), ctypes.byref(ptr))
        if hr != S_OK:
            raise OSError(f"SHCreateItemFromParsingName failed: {hr:#010x}")
        return ptr

    def _path_from_shell_item(self, item_ptr: ctypes.c_void_p) -> str:
        name_ptr = ctypes.c_wchar_p(None)
        hr = self._vtbl(
            item_ptr,
            VTBL_ISHELLITEM_GET_DISPLAY_NAME,
            ctypes.c_long,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_wchar_p),
        )(SIGDN_FILESYSPATH, ctypes.byref(name_ptr))
        if hr != S_OK:
            raise OSError(f"GetDisplayName failed: {hr:#010x}")
        path = name_ptr.value or ""
        ctypes.windll.ole32.CoTaskMemFree(name_ptr)
        return path

    def _set_folder(self, dialog_ptr: ctypes.c_void_p, path: str) -> None:
        try:
            si = self._make_shell_item(path)
            self._vtbl(dialog_ptr, VTBL_SET_FOLDER, ctypes.c_long, ctypes.c_void_p)(si)
            self._com_release(si)
        except OSError:
            pass

    def _apply_filters(self, dialog_ptr: ctypes.c_void_p, filters: list[Filter]) -> None:
        if not filters:
            return

        class FILTERSPEC(ctypes.Structure):
            _fields_ = [("pszName", ctypes.c_wchar_p), ("pszSpec", ctypes.c_wchar_p)]

        specs = [(lbl, ";".join(pat.split())) for lbl, pat in filters]
        arr = (FILTERSPEC * len(specs))()
        for i, (lbl, spec) in enumerate(specs):
            arr[i].pszName = lbl
            arr[i].pszSpec = spec

        self._vtbl(
            dialog_ptr,
            VTBL_SET_FILE_TYPES,
            ctypes.c_long,
            ctypes.c_uint,
            ctypes.c_void_p,
        )(len(specs), ctypes.cast(arr, ctypes.c_void_p))

        self._vtbl(dialog_ptr, VTBL_SET_FILE_TYPE_INDEX, ctypes.c_long, ctypes.c_uint)(1)

        ext = self._first_ext(filters)
        if ext:
            self._vtbl(dialog_ptr, VTBL_SET_DEFAULT_EXTENSION, ctypes.c_long, ctypes.c_wchar_p)(ext)

    def _com_open_file(self, title: str, start_dir: str, filters: list[Filter], multiple: bool, hwnd: int) -> PathResult:
        dlg = self._com_create(self._CLSID_FileOpenDialog, self._IID_IFileOpenDialog)
        try:
            self._vtbl(dlg, VTBL_SET_TITLE, ctypes.c_long, ctypes.c_wchar_p)(title)

            fos = FOS_NOCHANGEDIR | FOS_FORCEFILESYSTEM | FOS_FILEMUSTEXIST | FOS_PATHMUSTEXIST
            if multiple:
                fos |= FOS_ALLOWMULTISELECT
            self._vtbl(dlg, VTBL_SET_OPTIONS, ctypes.c_long, ctypes.c_uint)(fos)

            self._apply_filters(dlg, filters)
            self._set_folder(dlg, start_dir)

            hr = self._vtbl(dlg, VTBL_SHOW, ctypes.c_long, ctypes.c_void_p)(hwnd)
            if hr == ERROR_CANCELLED_HR:
                return None
            if hr != S_OK:
                raise OSError(f"Show() failed: {hr:#010x}")

            if multiple:
                arr_ptr = ctypes.c_void_p(0)
                hr = self._vtbl(dlg, VTBL_GET_RESULTS, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(arr_ptr))
                if hr != S_OK:
                    return None
                try:
                    count = ctypes.c_uint(0)
                    self._vtbl(arr_ptr, VTBL_ISHELLITEMARRAY_GET_COUNT, ctypes.c_long, ctypes.POINTER(ctypes.c_uint))(ctypes.byref(count))
                    paths: list[str] = []
                    for i in range(count.value):
                        item = ctypes.c_void_p(0)
                        self._vtbl(
                            arr_ptr,
                            VTBL_ISHELLITEMARRAY_GET_ITEM_AT,
                            ctypes.c_long,
                            ctypes.c_uint,
                            ctypes.POINTER(ctypes.c_void_p),
                        )(i, ctypes.byref(item))
                        if item:
                            try:
                                paths.append(self._path_from_shell_item(item))
                            finally:
                                self._com_release(item)
                    return paths or None
                finally:
                    self._com_release(arr_ptr)
            else:
                item = ctypes.c_void_p(0)
                hr = self._vtbl(dlg, VTBL_GET_RESULT, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(item))
                if hr != S_OK or not item:
                    return None
                try:
                    return self._path_from_shell_item(item) or None
                finally:
                    self._com_release(item)
        finally:
            self._com_release(dlg)
            ctypes.windll.ole32.CoUninitialize()

    def _com_save_file(self, title: str, start_dir: str, filters: list[Filter], default_name: str, hwnd: int) -> str | None:
        dlg = self._com_create(self._CLSID_FileSaveDialog, self._IID_IFileSaveDialog)
        try:
            self._vtbl(dlg, VTBL_SET_TITLE, ctypes.c_long, ctypes.c_wchar_p)(title)

            fos = FOS_OVERWRITEPROMPT | FOS_NOCHANGEDIR | FOS_FORCEFILESYSTEM
            self._vtbl(dlg, VTBL_SET_OPTIONS, ctypes.c_long, ctypes.c_uint)(fos)

            self._apply_filters(dlg, filters)

            suggested = self._suggest_name(default_name, filters)
            if suggested:
                self._vtbl(dlg, VTBL_SET_FILE_NAME, ctypes.c_long, ctypes.c_wchar_p)(suggested)

            self._set_folder(dlg, start_dir)

            hr = self._vtbl(dlg, VTBL_SHOW, ctypes.c_long, ctypes.c_void_p)(hwnd)
            if hr == ERROR_CANCELLED_HR:
                return None
            if hr != S_OK:
                raise OSError(f"Show() failed: {hr:#010x}")

            item = ctypes.c_void_p(0)
            hr = self._vtbl(dlg, VTBL_GET_RESULT, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(item))
            if hr != S_OK or not item:
                return None
            try:
                return self._path_from_shell_item(item) or None
            finally:
                self._com_release(item)
        finally:
            self._com_release(dlg)
            ctypes.windll.ole32.CoUninitialize()

    def _com_open_directory(self, title: str, start_dir: str, multiple: bool, hwnd: int) -> PathResult:
        dlg = self._com_create(self._CLSID_FileOpenDialog, self._IID_IFileOpenDialog)
        try:
            self._vtbl(dlg, VTBL_SET_TITLE, ctypes.c_long, ctypes.c_wchar_p)(title)

            fos = FOS_PICKFOLDERS | FOS_NOCHANGEDIR | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST
            if multiple:
                fos |= FOS_ALLOWMULTISELECT
            self._vtbl(dlg, VTBL_SET_OPTIONS, ctypes.c_long, ctypes.c_uint)(fos)

            self._set_folder(dlg, start_dir)

            hr = self._vtbl(dlg, VTBL_SHOW, ctypes.c_long, ctypes.c_void_p)(hwnd)
            if hr == ERROR_CANCELLED_HR:
                return None
            if hr != S_OK:
                raise OSError(f"Show() failed: {hr:#010x}")

            if multiple:
                arr_ptr = ctypes.c_void_p(0)
                hr = self._vtbl(dlg, VTBL_GET_RESULTS, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(arr_ptr))
                if hr != S_OK:
                    return None
                try:
                    count = ctypes.c_uint(0)
                    self._vtbl(arr_ptr, VTBL_ISHELLITEMARRAY_GET_COUNT, ctypes.c_long, ctypes.POINTER(ctypes.c_uint))(ctypes.byref(count))
                    paths: list[str] = []
                    for i in range(count.value):
                        item = ctypes.c_void_p(0)
                        self._vtbl(
                            arr_ptr,
                            VTBL_ISHELLITEMARRAY_GET_ITEM_AT,
                            ctypes.c_long,
                            ctypes.c_uint,
                            ctypes.POINTER(ctypes.c_void_p),
                        )(i, ctypes.byref(item))
                        if item:
                            try:
                                paths.append(self._path_from_shell_item(item))
                            finally:
                                self._com_release(item)
                    return paths or None
                finally:
                    self._com_release(arr_ptr)
            else:
                item = ctypes.c_void_p(0)
                hr = self._vtbl(dlg, VTBL_GET_RESULT, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(item))
                if hr != S_OK or not item:
                    return None
                try:
                    return self._path_from_shell_item(item) or None
                finally:
                    self._com_release(item)
        finally:
            self._com_release(dlg)
            ctypes.windll.ole32.CoUninitialize()

    def _classic_open_file(self, title: str, start_dir: str, filters: list[Filter], multiple: bool, hwnd: int) -> PathResult:
        buf_size = 65536
        buf = ctypes.create_unicode_buffer(buf_size)
        OFN = self._make_ofn_class()

        flags = OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_NOCHANGEDIR
        if multiple:
            flags |= OFN_ALLOWMULTISELECT

        ofn = OFN()
        ofn.lStructSize = ctypes.sizeof(OFN)
        ofn.hwndOwner = hwnd
        ofn.lpstrFilter = self._win32_filter(filters)
        ofn.nFilterIndex = 1
        ofn.lpstrFile = ctypes.cast(buf, ctypes.c_wchar_p)
        ofn.nMaxFile = buf_size
        ofn.lpstrInitialDir = start_dir
        ofn.lpstrTitle = title
        ofn.lpstrDefExt = self._first_ext(filters)
        ofn.Flags = flags

        if not ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn)):
            return None

        if multiple:
            raw_bytes = (ctypes.c_char * (buf_size * 2)).from_buffer(buf).raw
            raw = raw_bytes.decode("utf-16-le")
            parts = [p for p in raw.split("\x00") if p]
            if not parts:
                return None
            if len(parts) == 1:
                return [parts[0]]
            directory, *names = parts
            return [os.path.join(directory, n) for n in names]
        return buf.value or None

    def _classic_save_file(self, title: str, start_dir: str, filters: list[Filter], default_name: str, hwnd: int) -> str | None:

        buf_size = 32768
        suggested = self._suggest_name(default_name, filters)
        buf = ctypes.create_unicode_buffer(suggested, buf_size)
        OFN = self._make_ofn_class()

        ofn = OFN()
        ofn.lStructSize = ctypes.sizeof(OFN)
        ofn.hwndOwner = hwnd
        ofn.lpstrFilter = self._win32_filter(filters)
        ofn.nFilterIndex = 1
        ofn.lpstrFile = ctypes.cast(buf, ctypes.c_wchar_p)
        ofn.nMaxFile = buf_size
        ofn.lpstrInitialDir = start_dir
        ofn.lpstrTitle = title
        ofn.lpstrDefExt = self._first_ext(filters)
        ofn.Flags = OFN_EXPLORER | OFN_NOCHANGEDIR | OFN_OVERWRITEPROMPT

        if not ctypes.windll.comdlg32.GetSaveFileNameW(ctypes.byref(ofn)):
            return None
        return buf.value or None

    def _shell_browse_for_folder(self, title: str, start_dir: str, hwnd: int) -> str | None:
        import ctypes.wintypes as wt

        class BROWSEINFOW(ctypes.Structure):
            _fields_ = [
                ("hwndOwner", wt.HWND),
                ("pidlRoot", ctypes.c_void_p),
                ("pszDisplayName", ctypes.c_wchar_p),
                ("lpszTitle", ctypes.c_wchar_p),
                ("ulFlags", wt.UINT),
                ("lpfn", ctypes.c_void_p),
                ("lParam", wt.LPARAM),
                ("iImage", ctypes.c_int),
            ]

        BFFCALLBACK = ctypes.WINFUNCTYPE(ctypes.c_int, wt.HWND, wt.UINT, wt.LPARAM, wt.LPARAM)

        def _callback(hwnd, msg, lparam, lpdata):
            _ = lparam
            _ = lpdata
            if msg == BFFM_INITIALIZED:
                ctypes.windll.user32.SendMessageW(
                    hwnd,
                    BFFM_SETSELECTIONW,
                    1,
                    ctypes.addressof(ctypes.create_unicode_buffer(start_dir)),
                )
            return 0

        disp = ctypes.create_unicode_buffer(260)
        bi = BROWSEINFOW()
        bi.hwndOwner = hwnd
        bi.pszDisplayName = ctypes.cast(disp, ctypes.c_wchar_p)
        bi.lpszTitle = title
        bi.ulFlags = RETURNONLYFSDIRS | NEWDIALOGSTYLE | EDITBOX
        _cb_ref = BFFCALLBACK(_callback)
        bi.lpfn = ctypes.cast(_cb_ref, ctypes.c_void_p)
        bi.lParam = 0

        shell32 = ctypes.windll.shell32
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
        if not pidl:
            return None

        path_buf = ctypes.create_unicode_buffer(32768)
        shell32.SHGetPathFromIDListW(pidl, path_buf)
        ctypes.windll.ole32.CoTaskMemFree(pidl)

        return path_buf.value or None

    @staticmethod
    def _make_ofn_class() -> type:
        import ctypes.wintypes as wt

        class OPENFILENAMEW(ctypes.Structure):
            _fields_ = [
                ("lStructSize", wt.DWORD),
                ("hwndOwner", wt.HWND),
                ("hInstance", wt.HINSTANCE),
                ("lpstrFilter", ctypes.c_wchar_p),
                ("lpstrCustomFilter", ctypes.c_wchar_p),
                ("nMaxCustFilter", wt.DWORD),
                ("nFilterIndex", wt.DWORD),
                ("lpstrFile", ctypes.c_wchar_p),
                ("nMaxFile", wt.DWORD),
                ("lpstrFileTitle", ctypes.c_wchar_p),
                ("nMaxFileTitle", wt.DWORD),
                ("lpstrInitialDir", ctypes.c_wchar_p),
                ("lpstrTitle", ctypes.c_wchar_p),
                ("Flags", wt.DWORD),
                ("nFileOffset", wt.WORD),
                ("nFileExtension", wt.WORD),
                ("lpstrDefExt", ctypes.c_wchar_p),
                ("lCustData", wt.LPARAM),
                ("lpfnHook", ctypes.c_void_p),
                ("lpTemplateName", ctypes.c_wchar_p),
                ("pvReserved", ctypes.c_void_p),
                ("dwReserved", wt.DWORD),
                ("FlagsEx", wt.DWORD),
            ]

        return OPENFILENAMEW

    @staticmethod
    def _win32_filter(filters: list[Filter]) -> str:
        if not filters:
            filters = [("All Files", "*.*")]
        parts = []
        for label, pattern in filters:
            spec = ";".join(pattern.split())
            parts.append(f"{label}\x00{spec}\x00")
        return "".join(parts) + "\x00"

    @staticmethod
    def _first_ext(filters: list[Filter]) -> str | None:
        for _, pattern in filters:
            for tok in pattern.split():
                m = re.match(r"\*\.([a-zA-Z0-9]+)$", tok)
                if m:
                    return m.group(1)
        return None

    @staticmethod
    def _suggest_name(name: str, filters: list[Filter]) -> str:
        if name and "." in Path(name).name:
            return name
        for _, pattern in filters:
            for tok in pattern.split():
                m = re.match(r"\*\.([a-zA-Z0-9]+)$", tok)
                if m:
                    return f"{name or 'untitled'}.{m.group(1)}"
        return name or ""


class _MacOSBackend(_Backend):
    def open_file(self, *, title: str, start_dir: str, filters: list[Filter], multiple: bool, parent: int | str | None) -> PathResult:
        ext_clause = self._type_clause(filters)
        multi_clause = "with multiple selections allowed" if multiple else ""
        loc_clause = f"default location {self._posix_path(start_dir)}" if start_dir else ""

        script = f"""
set theResult to (choose file with prompt {self._as_str(title)}{ext_clause} ¬
    {loc_clause} {multi_clause})
set posixPaths to {{}}
if class of theResult is list then
    repeat with aFile in theResult
        set end of posixPaths to POSIX path of aFile
    end repeat
else
    set posixPaths to {{POSIX path of theResult}}
end if
set AppleScript's text item delimiters to "\\n"
posixPaths as text
"""
        result = self._run(script)
        if result is None:
            return None
        paths = [p.rstrip("/") for p in result.splitlines() if p]
        if not paths:
            return None
        return paths if multiple else paths[0]

    def save_file(self, *, title: str, start_dir: str, filters: list[Filter], default_name: str, parent: int | str | None) -> str | None:
        suggested = default_name or "untitled"
        if "." not in Path(suggested).name:
            ext = self._first_ext(filters)
            if ext:
                suggested = f"{suggested}.{ext}"

        name_clause = f"default name {self._as_str(suggested)}"
        loc_clause = f"default location {self._posix_path(start_dir)}" if start_dir else ""

        script = f"""
POSIX path of (choose file name with prompt {self._as_str(title)} ¬
    {name_clause} {loc_clause})
"""
        return self._run(script)

    def open_directory(self, *, title: str, start_dir: str, multiple: bool, parent: int | str | None) -> PathResult:
        loc_clause = f"default location {self._posix_path(start_dir)}" if start_dir else ""
        multi_clause = "with multiple selections allowed" if multiple else ""
        script = f"""
set theResult to (choose folder with prompt {self._as_str(title)} {loc_clause} {multi_clause})
set posixPaths to {{}}
if class of theResult is list then
    repeat with aFolder in theResult
        set end of posixPaths to POSIX path of aFolder
    end repeat
else
    set posixPaths to {{POSIX path of theResult}}
end if
set AppleScript's text item delimiters to "\\n"
posixPaths as text
"""
        result = self._run(script)
        if result is None:
            return None
        paths = [p.rstrip("/") for p in result.splitlines() if p]
        if not paths:
            return None
        return paths if multiple else paths[0]

    @staticmethod
    def _as_str(value: str) -> str:
        parts = value.split('"')
        fragments = [f'"{p}"' for p in parts]
        return " & quote & ".join(fragments)

    @staticmethod
    def _posix_path(path: str) -> str:
        escaped = path.replace("\\", "\\\\").replace('"', '\\"')
        return f'(POSIX file "{escaped}")'

    @staticmethod
    def _collect_exts(filters: list[Filter]) -> list[str]:
        exts: list[str] = []
        for _, pattern in filters:
            for tok in pattern.split():
                m = re.match(r"\*\.([a-zA-Z0-9]+)$", tok)
                if m and m.group(1) not in exts:
                    exts.append(m.group(1))
        return exts

    @staticmethod
    def _first_ext(filters: list[Filter]) -> str | None:
        for _, pattern in filters:
            for tok in pattern.split():
                m = re.match(r"\*\.([a-zA-Z0-9]+)$", tok)
                if m:
                    return m.group(1)
        return None

    def _type_clause(self, filters: list[Filter]) -> str:
        exts = self._collect_exts(filters)
        if not exts:
            return ""
        quoted = ", ".join(f'"{e}"' for e in exts)
        return f" of type {{{quoted}}}"

    @staticmethod
    def _run(script: str) -> str | None:
        try:
            r = subprocess.run(
                ["osascript", "-e", script.strip()],
                capture_output=True,
                text=True,
                check=False,
            )
            if r.returncode != 0:
                return None
            return r.stdout.strip() or None
        except FileNotFoundError:
            raise RuntimeError("osascript not found, are you on macOS?")


class _LinuxBackend(_Backend):
    _CLI_TOOLS = ("zenity", "kdialog", "qarma")

    def __init__(self) -> None:
        self._portal_ok: bool = self._probe_portal()
        self._tool: str | None = self._detect_tool()

    @staticmethod
    def _probe_portal() -> bool:
        try:
            r = subprocess.run(
                [
                    "gdbus",
                    "introspect",
                    "--session",
                    "--dest",
                    "org.freedesktop.portal.Desktop",
                    "--object-path",
                    "/org/freedesktop/portal/desktop",
                ],
                capture_output=True,
                text=True,
                timeout=3,
            )
            return r.returncode == 0 and "FileChooser" in r.stdout
        except Exception:
            return False

    @staticmethod
    def _detect_tool() -> str | None:
        for t in _LinuxBackend._CLI_TOOLS:
            if shutil.which(t):
                return t
        return None

    def open_file(self, *, title: str, start_dir: str, filters: list[Filter], multiple: bool, parent: int | str | None) -> PathResult:
        if self._portal_ok:
            try:
                return self._portal_open_file(title, start_dir, filters, multiple, parent)
            except Exception:
                pass
        if self._tool == "zenity":
            return self._zenity_open_file(title, start_dir, filters, multiple, parent)
        if self._tool in ("kdialog", "qarma"):
            return self._kdialog_open_file(title, start_dir, filters, multiple, parent)
        return self._tk_open_file(title, start_dir, filters, multiple)

    def save_file(self, *, title: str, start_dir: str, filters: list[Filter], default_name: str, parent: int | str | None) -> str | None:
        if self._portal_ok:
            try:
                return self._portal_save_file(title, start_dir, filters, default_name, parent)
            except Exception:
                pass
        if self._tool == "zenity":
            return self._zenity_save_file(title, start_dir, filters, default_name, parent)
        if self._tool in ("kdialog", "qarma"):
            return self._kdialog_save_file(title, start_dir, filters, default_name, parent)
        return self._tk_save_file(title, start_dir, filters, default_name)

    def open_directory(self, *, title: str, start_dir: str, multiple: bool, parent: int | str | None) -> PathResult:
        if self._portal_ok:
            return self._portal_open_directory(title, start_dir, multiple, parent)
        if self._tool == "zenity":
            return self._zenity_open_directory(title, start_dir, multiple, parent)
        if self._tool in ("kdialog", "qarma"):
            return self._kdialog_open_directory(title, start_dir, multiple, parent)
        return self._tk_open_directory(title, start_dir, multiple)

    @staticmethod
    def _portal_window(parent: int | str | None) -> str:
        if parent is None:
            return ""
        if isinstance(parent, int) and parent:
            return f"x11:{hex(parent)}"
        return str(parent)

    def _portal_open_file(self, title: str, start_dir: str, filters: list[Filter], multiple: bool, parent: int | str | None) -> PathResult:
        return self._portal_dispatch(
            "OpenFile",
            title=title,
            start_dir=start_dir,
            filters=filters,
            multiple=multiple,
            directory=False,
            default_name="",
            parent=parent,
        )

    def _portal_save_file(self, title: str, start_dir: str, filters: list[Filter], default_name: str, parent: int | str | None) -> str | None:
        result = self._portal_dispatch(
            "SaveFile",
            title=title,
            start_dir=start_dir,
            filters=filters,
            multiple=False,
            directory=False,
            default_name=default_name,
            parent=parent,
        )
        return result if isinstance(result, str) else None

    def _portal_open_directory(self, title: str, start_dir: str, multiple: bool, parent: int | str | None) -> PathResult:
        return self._portal_dispatch(
            "OpenFile",
            title=title,
            start_dir=start_dir,
            filters=[],
            multiple=multiple,
            directory=True,
            default_name="",
            parent=parent,
        )

    def _portal_dispatch(
        self,
        method: str,
        *,
        title: str,
        start_dir: str,
        filters: list[Filter],
        multiple: bool,
        directory: bool,
        default_name: str,
        parent: int | str | None,
    ) -> PathResult:
        import dbus  # pyright: ignore[reportMissingImports]
        import dbus.mainloop.glib  # pyright: ignore[reportMissingImports]
        from gi.repository import GLib  # pyright: ignore[reportMissingImports]

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SessionBus()

        token = f"nd_{os.getpid()}_{random.randint(0, 0xFFFFFF):06x}"
        sender_safe = bus.get_unique_name().lstrip(":").replace(".", "_")
        handle_path = f"/org/freedesktop/portal/desktop/request/{sender_safe}/{token}"

        loop = GLib.MainLoop()
        result: dict[str, list[str] | None] = {"paths": None}

        def on_response(response_code: int, results: dict) -> None:
            if response_code == 0:
                result["paths"] = [urllib.parse.unquote(uri.removeprefix("file://")) for uri in results.get("uris", [])]
            loop.quit()

        bus.add_signal_receiver(
            on_response,
            signal_name="Response",
            dbus_interface="org.freedesktop.portal.Request",
            path=handle_path,
        )

        portal = dbus.Interface(
            bus.get_object("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop"),
            "org.freedesktop.portal.FileChooser",
        )

        opts: dict = {"handle_token": dbus.String(token)}

        if method == "OpenFile":
            if multiple:
                opts["multiple"] = dbus.Boolean(True)
            if directory:
                opts["directory"] = dbus.Boolean(True)

        if method == "SaveFile":
            if default_name:
                opts["current_name"] = dbus.String(default_name)
            if start_dir and os.path.isdir(start_dir):
                opts["current_folder"] = dbus.Array((start_dir + "\x00").encode(), signature="y")

        if filters:
            opts["filters"] = dbus.Array(
                [
                    (
                        dbus.String(label),
                        dbus.Array(
                            [(dbus.UInt32(0), dbus.String(g)) for g in pattern.split()],
                            signature="(us)",
                        ),
                    )
                    for label, pattern in filters
                ],
                signature="(sa(us))",
            )

        window_handle = self._portal_window(parent)

        try:
            getattr(portal, method)(window_handle, title, opts)
        except dbus.DBusException as exc:
            raise RuntimeError(f"portal {method} failed: {exc}") from exc

        GLib.timeout_add_seconds(300, loop.quit)
        loop.run()

        paths = result["paths"]
        if paths is None:
            return None
        if method == "OpenFile" and multiple:
            return paths or None
        return paths[0] if paths else None

    def _zenity_attach(self, parent: int | str | None) -> list[str]:
        if isinstance(parent, int) and parent:
            return [f"--attach={parent}"]
        return []

    def _zenity_open_file(self, title: str, start_dir: str, filters: list[Filter], multiple: bool, parent: int | str | None) -> PathResult:
        cmd = [
            "zenity",
            "--file-selection",
            f"--title={title}",
            f"--filename={start_dir}/",
        ]
        if multiple:
            cmd += ["--multiple", "--separator=\n"]
        for label, pattern in filters:
            cmd += ["--file-filter", f"{label} | {pattern}"]
        cmd += self._zenity_attach(parent)

        out = self._run(cmd)
        if out is None:
            return None
        paths = [p for p in out.splitlines() if p]
        return (paths or None) if multiple else (paths[0] if paths else None)

    def _zenity_save_file(self, title: str, start_dir: str, filters: list[Filter], default_name: str, parent: int | str | None) -> str | None:
        filename = os.path.join(start_dir, default_name) if default_name else f"{start_dir}/"
        cmd = [
            "zenity",
            "--file-selection",
            "--save",
            "--confirm-overwrite",
            f"--title={title}",
            f"--filename={filename}",
        ]
        for label, pattern in filters:
            cmd += ["--file-filter", f"{label} | {pattern}"]
        cmd += self._zenity_attach(parent)
        return self._run(cmd)

    def _zenity_open_directory(self, title: str, start_dir: str, multiple: bool, parent: int | str | None) -> PathResult:
        cmd = [
            "zenity",
            "--file-selection",
            "--directory",
            f"--title={title}",
            f"--filename={start_dir}/",
        ]
        if multiple:
            cmd += ["--multiple", "--separator=\n"]
        cmd += self._zenity_attach(parent)
        out = self._run(cmd)
        if out is None:
            return None
        paths = [p for p in out.splitlines() if p]
        return (paths or None) if multiple else (paths[0] if paths else None)

    def _kdialog_attach(self, parent: int | str | None) -> list[str]:
        if isinstance(parent, int) and parent:
            return ["--attach", str(parent)]
        return []

    def _kdialog_open_file(self, title: str, start_dir: str, filters: list[Filter], multiple: bool, parent: int | str | None) -> PathResult:
        cmd = [
            self._tool,
            "--getopenfilename",
            start_dir,
            self._kdialog_filter(filters),
            "--title",
            title,
        ]
        if multiple:
            cmd += ["--multiple", "--separate-output"]
        cmd += self._kdialog_attach(parent)

        out = self._run(cmd)
        if out is None:
            return None
        paths = [p for p in out.splitlines() if p]
        return (paths or None) if multiple else (paths[0] if paths else None)

    def _kdialog_save_file(self, title: str, start_dir: str, filters: list[Filter], default_name: str, parent: int | str | None) -> str | None:
        filename = os.path.join(start_dir, default_name) if default_name else start_dir
        cmd = [
            self._tool,
            "--getsavefilename",
            filename,
            self._kdialog_filter(filters),
            "--title",
            title,
        ] + self._kdialog_attach(parent)
        return self._run(cmd)

    def _kdialog_open_directory(self, title: str, start_dir: str, multiple: bool, parent: int | str | None) -> str | None:
        _ = multiple
        cmd = [
            self._tool,
            "--getexistingdirectory",
            start_dir,
            "--title",
            title,
        ] + self._kdialog_attach(parent)
        return self._run(cmd)

    @staticmethod
    def _kdialog_filter(filters: list[Filter]) -> str:
        if not filters:
            return "All Files (*)"
        parts = [f"{label} ({pattern})" for label, pattern in filters]
        return ";;".join(parts)

    @staticmethod
    def _make_tk():
        try:
            import tkinter as tk

            root = tk.Tk()
            root.withdraw()
            root.call("wm", "attributes", ".", "-topmost", True)
            return root
        except ImportError:
            raise RuntimeError("no dialog backend found.  Install python-dbus + python-gobject " "(portal), zenity, kdialog, qarma, or tkinter.")

    def _tk_open_file(self, title: str, start_dir: str, filters: list[Filter], multiple: bool) -> PathResult:
        from tkinter import filedialog

        root = self._make_tk()
        tf = self._tk_filters(filters)
        if multiple:
            paths = filedialog.askopenfilenames(title=title, initialdir=start_dir, filetypes=tf, parent=root)
            root.destroy()
            return list(paths) if paths else None
        path = filedialog.askopenfilename(title=title, initialdir=start_dir, filetypes=tf, parent=root)
        root.destroy()
        return path or None

    def _tk_save_file(self, title: str, start_dir: str, filters: list[Filter], default_name: str) -> str | None:
        from tkinter import filedialog

        root = self._make_tk()
        path = filedialog.asksaveasfilename(
            title=title,
            initialdir=start_dir,
            initialfile=default_name,
            filetypes=self._tk_filters(filters),
            parent=root,
        )
        root.destroy()
        return path or None

    def _tk_open_directory(self, title: str, start_dir: str, multiple: bool) -> PathResult:
        from tkinter import filedialog
        _ = multiple

        root = self._make_tk()
        path = filedialog.askdirectory(title=title, initialdir=start_dir, parent=root)
        root.destroy()
        return path or None

    @staticmethod
    def _tk_filters(filters: list[Filter]) -> list[tuple[str, str]]:
        return list(filters) if filters else [("All Files", "*")]

    @staticmethod
    def _run(cmd: list[str]) -> str | None:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, check=False)
            return r.stdout.strip() if r.returncode == 0 else None
        except FileNotFoundError:
            return None
