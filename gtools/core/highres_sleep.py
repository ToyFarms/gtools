from __future__ import annotations
import errno
import sys
import time
import ctypes
import ctypes.util
import atexit


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def _is_darwin() -> bool:
    return sys.platform.startswith("darwin")


if _is_linux() or _is_darwin():
    libc_name = ctypes.util.find_library("c") or "libc.so.6"
    _libc = ctypes.CDLL(libc_name, use_errno=True)

    class _timespec(ctypes.Structure):
        _fields_ = [("tv_sec", ctypes.c_long), ("tv_nsec", ctypes.c_long)]

    _clock_nanosleep = getattr(_libc, "clock_nanosleep", None)
    if _clock_nanosleep is not None:
        _clock_nanosleep.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.POINTER(_timespec), ctypes.POINTER(_timespec)]
        _clock_nanosleep.restype = ctypes.c_int

    _nanosleep = getattr(_libc, "nanosleep", None)
    if _nanosleep is not None:
        _nanosleep.argtypes = [ctypes.POINTER(_timespec), ctypes.POINTER(_timespec)]
        _nanosleep.restype = ctypes.c_int

if _is_windows():
    import ctypes.wintypes as wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _winmm = ctypes.WinDLL("winmm", use_last_error=True)

    try:
        _timeBeginPeriod = _winmm.timeBeginPeriod
        _timeBeginPeriod.argtypes = [wintypes.UINT]
        _timeBeginPeriod.restype = wintypes.UINT

        _timeEndPeriod = _winmm.timeEndPeriod
        _timeEndPeriod.argtypes = [wintypes.UINT]
        _timeEndPeriod.restype = wintypes.UINT
    except Exception:
        _timeBeginPeriod = None
        _timeEndPeriod = None

    _CreateWaitableTimer = _kernel32.CreateWaitableTimerW
    _CreateWaitableTimer.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    _CreateWaitableTimer.restype = wintypes.HANDLE

    _SetWaitableTimer = _kernel32.SetWaitableTimer
    _SetWaitableTimer.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_longlong), wintypes.LONG, wintypes.LPVOID, wintypes.LPVOID, wintypes.BOOL]
    _SetWaitableTimer.restype = wintypes.BOOL

    _WaitForSingleObject = _kernel32.WaitForSingleObject
    _WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _WaitForSingleObject.restype = wintypes.DWORD

    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _CloseHandle.restype = wintypes.BOOL

    if _timeBeginPeriod is not None:
        try:
            _timeBeginPeriod(1)

            def _restore_time_end_period():
                try:
                    if _timeEndPeriod:
                        _timeEndPeriod(1)
                except Exception:
                    pass

            atexit.register(_restore_time_end_period)
        except Exception:
            pass

    def sleep_ns(ns: float) -> None:
        intervals_100ns = (ns + 99) // 100
        due_100ns = -int(intervals_100ns)
        li = ctypes.c_longlong(due_100ns)

        h = _CreateWaitableTimer(None, True, None)
        if not h:
            err = ctypes.get_last_error()
            raise OSError(err, "CreateWaitableTimer failed")

        try:
            ok = _SetWaitableTimer(h, ctypes.byref(li), 0, None, None, False)
            if not ok:
                err = ctypes.get_last_error()
                raise OSError(err, "SetWaitableTimer failed")

            INFINITE = 0xFFFFFFFF
            _WaitForSingleObject(h, INFINITE)
            return
        finally:
            try:
                _CloseHandle(h)
            except Exception:
                pass

elif _is_linux():

    def sleep_ns(ns: float) -> None:
        CLOCK_MONOTONIC = 1
        TIMER_ABSTIME = 1

        target_ns = time.monotonic_ns() + int(ns)
        ts = _timespec()
        ts.tv_sec = int(target_ns // 1e9)
        ts.tv_nsec = int(target_ns % 1e9)

        if _clock_nanosleep is not None:
            while True:
                err = _clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, ctypes.byref(ts), None)
                if err == 0:
                    return
                if err == errno.EINTR:
                    target_ns = time.monotonic_ns() + int(ns)
                    ts.tv_sec = int(target_ns // 1e9)
                    ts.tv_nsec = int(target_ns % 1e9)
                    continue
                raise OSError(err, "clock_nanosleep failed")

        elif _nanosleep is not None:
            rem = _timespec()
            tv = _timespec()
            tv.tv_sec = int(ns // 1e9)
            tv.tv_nsec = int(ns % 1e9)
            while True:
                rv = _nanosleep(ctypes.byref(tv), ctypes.byref(rem))
                if rv == 0:
                    return
                e = ctypes.get_errno()
                if e == errno.EINTR:
                    tv.tv_sec = rem.tv_sec
                    tv.tv_nsec = rem.tv_nsec
                    continue
                raise OSError(e, "nanosleep failed")

elif _is_darwin():

    def sleep_ns(ns: float) -> None:
        if _nanosleep is None:
            time.sleep(ns / 1e9)
            return

        rem = _timespec()
        tv = _timespec()
        tv.tv_sec = int(ns // 1e9)
        tv.tv_nsec = int(ns % 1e9)
        while True:
            rv = _nanosleep(ctypes.byref(tv), ctypes.byref(rem))
            if rv == 0:
                return
            e = ctypes.get_errno()
            if e == errno.EINTR:
                tv.tv_sec = rem.tv_sec
                tv.tv_nsec = rem.tv_nsec
                continue
            raise OSError(e, "nanosleep failed")

else:

    def sleep_ns(ns: float) -> None:
        time.sleep(ns / 1e9)


if __name__ == "__main__":
    ns = 1000000
    i = 0
    while True:
        start = time.perf_counter_ns()
        sleep_ns(ns)
        end = time.perf_counter_ns()
        print(f"requested {ns}ns, elapsed = {end - start}ns, error={(ns-(end-start)) / 1e6}ms")
