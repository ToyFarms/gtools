import hashlib
import json
from typing import TypedDict
import uuid

from gtools.core.fake.mac import generate_random_mac
from gtools.core.fake.volume_serial import generate_volume_serial
from gtools.core.growtopia.crypto import proton_hash
from gtools import setting


class AccountIdent(TypedDict):
    mac: str
    hash: str
    hash2: str
    wk: str


class Account(TypedDict):
    name: str
    ident: AccountIdent


class AccountManager:
    _FILE = setting.appdir / "accounts.json"
    _last: Account | None = None

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
    def create_account(cls, name: str) -> Account:
        return {
            "name": name,
            "ident": {
                "mac": generate_random_mac(),
                "hash": str(proton_hash(f"{generate_volume_serial()}RT".encode())),
                "hash2": str(proton_hash(f"{generate_random_mac()}RT".encode())),
                "wk": hashlib.md5(str(uuid.uuid4()).encode()).hexdigest().upper(),
            },
        }

    @classmethod
    def last(cls) -> Account | None:
        return cls._last

    @classmethod
    def get(cls, name: bytes) -> Account:
        name_str = name.decode()

        accounts = cls._read()
        acc: Account | None = accounts.get(name_str)
        if acc is None:
            acc = cls.create_account(name_str)
            accounts[name_str] = acc
            cls._write(accounts)

        cls._last = acc
        return acc

    @classmethod
    def remove(cls, name: bytes) -> Account:
        name_str = name.decode()

        accounts = cls._read()
        if name_str not in accounts:
            raise KeyError(f"no account named {name}")

        acc = accounts.pop(name.decode())
        cls._write(accounts)

        return acc

    @classmethod
    def renew(cls, name: bytes) -> Account:
        name_str = name.decode()
        new_ident = cls.create_account(name_str)["ident"]

        accounts = cls._read()
        accounts[name_str]["ident"] = new_ident

        cls._write(accounts)

        return accounts[name_str]

    @classmethod
    def exists(cls, name: bytes) -> bool:
        return name.decode() in cls._read()

    @classmethod
    def get_all(cls) -> list[Account]:
        return list(cls._read().values())
