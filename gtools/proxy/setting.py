# TODO: general storage
# TODO: move to core


from dataclasses import dataclass
from pathlib import Path

from gtools.core.wsl import windows_home


@dataclass(frozen=True)
class _Setting:
    server_data_url: str
    proxy_server: str
    proxy_port: int
    appdir_name: Path
    appdir: Path
    asset_path: Path
    broker_addr: str
    spoof_mac: bool


setting = _Setting(
    server_data_url="www.growtopia1.com",
    proxy_server="127.0.0.1",
    proxy_port=16999,
    appdir_name=Path(".gtools"),
    appdir=Path.home() / ".gtools",
    asset_path=windows_home() / "AppData/Local/Growtopia/game",
    broker_addr="tcp://127.0.0.1:6712",
    spoof_mac=True,
)
