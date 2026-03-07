import logging


try:
    import winreg

    _has_winreg = True
except ImportError:
    _has_winreg = False


logger = logging.getLogger("guid")


def get_machine_guid() -> bytes:
    if _has_winreg:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ) as key:
            machine_guid, _ = winreg.QueryValueEx(key, r"MachineGuid")
            return machine_guid.encode()
    else:
        logger.warning("cannot get windows registry, because winreg does not exists")
        return b""
