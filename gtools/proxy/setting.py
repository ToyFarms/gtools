# TODO: general storage
# TODO: move to core


from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _Setting:
    server_data_url: str
    proxy_server: str
    proxy_port: int
    appdir_name: Path
    appdir: Path


_setting = _Setting(
    server_data_url="www.growtopia1.com",
    proxy_server="127.0.0.1",
    proxy_port=16999,
    appdir_name=Path(".gtools"),
    appdir=Path.home() / ".gtools",
)
