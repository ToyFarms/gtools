import json
from typing import TypedDict

from gtools.core.mac import generate_random_mac
from gtools.proxy.setting import setting


class Account(TypedDict):
    mac: str


class AccountManager:
    _FILE = setting.appdir / "accounts.json"

    @classmethod
    def _read(cls) -> dict[str, Account]:
        if not cls._FILE.exists():
            return {}

        with open(cls._FILE, "r") as f:
            return json.load(f)

    @classmethod
    def _write(cls, data: dict[str, Account]) -> None:
        with open(cls._FILE, "w") as f:
            return json.dump(data, f)

    @classmethod
    def get(cls, name: bytes) -> Account:
        name_str = name.decode()

        accounts = cls._read()
        acc: Account | None = accounts.get(name_str)
        if acc is None:
            acc = {"mac": generate_random_mac()}
            accounts[name_str] = acc

        cls._write(accounts)
        return acc
