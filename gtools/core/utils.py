from pathlib import Path
import platform

from gtools.core.wsl import is_running_wsl, windows_home

sys = platform.system()
if is_running_wsl():
    get_home = windows_home
else:

    def get_home() -> Path:
        return Path.home()


if is_running_wsl() or sys == "Windows":

    def get_growtopia() -> Path:
        return get_home() / "AppData/Local/Growtopia"

elif sys == "Android":

    def get_growtopia() -> Path:
        return Path("/sdcard/Android/data/com.rtsoft.growtopia/files")

else:

    def get_growtopia() -> Path:
        return get_home() / "AppData/Local/Growtopia"

