import winreg


def get_machine_guid() -> bytes:
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ) as key:
        machine_guid, _ = winreg.QueryValueEx(key, r"MachineGuid")
        return machine_guid.encode()
