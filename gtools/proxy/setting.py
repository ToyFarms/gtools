# TODO: general storage


from dataclasses import dataclass


@dataclass(frozen=True)
class _Setting:
    server_data_url: str
    proxy_server: str
    proxy_port: int


_setting = _Setting(
    server_data_url="www.growtopia1.com",
    proxy_server="127.0.0.1",
    proxy_port=16999,
)
