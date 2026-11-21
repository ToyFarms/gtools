"""Scan the live game image for the hook signatures (Windows, stdlib only).

The client is packed: the on-disk exe has no .text, so signatures can only be
verified against the *unpacked in-memory image*. This probe attaches to a
running game (read-only), scans every registered pattern and reports
unique/ambiguous/missing per variant with the resulting RVA.

Usage:
    powershell> python scripts\\pattern_probe.py [--name Growtopia.exe] [--json]

Run it a few seconds after launching the game so the packer has unpacked.
"""

import argparse
import ctypes
import struct
import sys
import types
from ctypes import wintypes
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _stub_import() -> None:
    for name, path in (
        ("gtools", REPO / "gtools"),
        ("gtools.core", REPO / "gtools" / "core"),
        ("gtools.hooks", REPO / "gtools" / "hooks"),
    ):
        module = types.ModuleType(name)
        module.__path__ = [str(path)]
        module.__package__ = name
        sys.modules[name] = module
    import gtools.hooks.programs as programs  # noqa: F401


_stub_import()

from gtools.hooks import registry, payload  # noqa: E402

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400


def find_pid(name: str) -> int:
    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        return 0
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    pid = 0
    if kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
        while True:
            if entry.szExeFile.lower() == name.lower():
                pid = entry.th32ProcessID
                break
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snapshot)
    return pid


def module_base(pid: int, name: str) -> int:
    class MODULEENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("th32ModuleID", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("GlblcntUsage", wintypes.DWORD),
            ("ProccntUsage", wintypes.DWORD),
            ("modBaseAddr", ctypes.POINTER(ctypes.c_ubyte)),
            ("modBaseSize", wintypes.DWORD),
            ("hModule", ctypes.c_void_p),
            ("szModule", ctypes.c_wchar * 256),
            ("szExePath", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Module32FirstW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    kernel32.Module32NextW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x8 | 0x10, pid)  # SNAPMODULE | SNAPMODULE32
    if snapshot in (0, ctypes.c_void_p(-1).value):
        return 0
    entry = MODULEENTRY32W()
    entry.dwSize = ctypes.sizeof(entry)
    base = 0
    if kernel32.Module32FirstW(snapshot, ctypes.byref(entry)):
        while True:
            if entry.szModule.lower() == name.lower():
                base = ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value or 0
                break
            if not kernel32.Module32NextW(snapshot, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snapshot)
    return base


def read_image(pid: int, name: str) -> tuple[int, bytes] | None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.ReadProcessMemory.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t),
    ]
    process = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not process:
        print(f"cannot open pid {pid} (err={ctypes.get_last_error()}); run elevated if access is denied")
        return None

    image_base = module_base(pid, name)
    if not image_base:
        print(f"cannot resolve the module base of {name} in pid {pid}")
        return None

    header_buf = (ctypes.c_ubyte * 0x1000)()
    got = ctypes.c_size_t()
    if not kernel32.ReadProcessMemory(process, ctypes.c_void_p(image_base), header_buf, len(header_buf), ctypes.byref(got)):
        print(f"cannot read the PE header at {image_base:#x} (err={ctypes.get_last_error()})")
        return None
    header = bytes(header_buf)
    e_lfanew = struct.unpack_from("<I", header, 0x3C)[0]
    if header[e_lfanew:e_lfanew + 4] != b"PE\0\0":
        print("bad PE signature")
        return None
    opt_off = e_lfanew + 0x18
    image_size = struct.unpack_from("<I", header, opt_off + 0x38)[0]

    image = (ctypes.c_ubyte * image_size)()
    if not kernel32.ReadProcessMemory(process, ctypes.c_void_p(image_base), image, image_size, ctypes.byref(got)):
        print(f"cannot read the image at {image_base:#x} size {image_size:#x} (err={ctypes.get_last_error()})")
        return None
    return image_base, bytes(image)


def compile_pattern(signature: str) -> tuple[bytes, bytes]:
    values = bytearray()
    mask = bytearray()
    for token in signature.replace(",", " ").split():
        if token == "??":
            values.append(0)
            mask.append(0)
        else:
            values.append(int(token, 16))
            mask.append(0xFF)
    return bytes(values), bytes(mask)


def scan(image: bytes, signature: str) -> list[int]:
    values, mask = compile_pattern(signature)
    matches = []
    first = values.find(bytes(values[0:1]))
    end = len(image) - len(values)
    start = 0
    while start <= end:
        index = image.find(values[:1], start, end + 1)
        if index < 0:
            break
        chunk = image[index:index + len(values)]
        if all(mask[i] == 0 or chunk[i] == values[i] for i in range(len(values))):
            matches.append(index)
            if len(matches) > 8:
                break
        start = index + 1
    return matches


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="Growtopia.exe")
    parser.add_argument("--pid", type=int, default=0, help="probe this pid instead of the first match")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    pid = args.pid or find_pid(args.name)
    if not pid:
        print(f"{args.name} is not running")
        return 1
    print(f"{args.name} pid {pid}")

    loaded = read_image(pid, args.name)
    if loaded is None:
        return 1
    image_base, image = loaded
    print(f"image base {image_base:#x} size {len(image):#x}")

    report = {}
    failures = 0
    for hook in registry.all_hooks():
        if not hook.patterns:
            continue
        entry = {}
        for variant, signature in enumerate(hook.patterns):
            matches = scan(image, signature)
            entry[f"variant{variant}"] = {
                "matches": len(matches),
                "rvas": [f"{m:#x}" for m in matches[:8]],
            }
            status = "unique" if len(matches) == 1 else ("ambiguous" if matches else "missing")
            if len(matches) != 1:
                failures += 1
            if not args.json:
                rva = f"{matches[0]:#x}" if len(matches) == 1 else ",".join(f"{m:#x}" for m in matches[:4])
                print(f"  {hook.key:16} v{variant}: {status:9} {rva}")
        report[hook.key] = entry

    if args.json:
        import json

        print(json.dumps({"pid": pid, "image_base": f"{image_base:#x}", "hooks": report}, indent=2))
    print(f"{failures} unresolved variant(s)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
