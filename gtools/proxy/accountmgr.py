import copy
import hashlib
import importlib
import json
import pkgutil
from typing import TypedDict
import uuid

from gtools.core.fake.mac import generate_random_mac
from gtools.core.fake.volume_serial import generate_volume_serial
from gtools.core.growtopia.crypto import generate_rid, proton_hash
from gtools import setting


class AccountIdent(TypedDict):
    mac: str
    hash: str
    hash2: str
    wk: str
    rid: str


class Account(TypedDict):
    name: str
    ident: AccountIdent
    _version: int


class AccountManager:
    _FILE = setting.appdir / "accounts.json"
    _MIGRATIONS_DIR = "migration"
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
            json.dump(data, f)

    @classmethod
    def create_account(cls, name: str) -> Account:
        migrations = _discover_migration_files()
        latest_version = migrations[-1][0] if migrations else 0

        return {
            "name": name,
            "_version": latest_version,
            "ident": {
                "mac": generate_random_mac(),
                "hash": str(proton_hash(f"{generate_volume_serial()}RT".encode())),
                "hash2": str(proton_hash(f"{generate_random_mac()}RT".encode())),
                "wk": hashlib.md5(str(uuid.uuid4()).encode()).hexdigest().upper(),
                "rid": generate_rid(),
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
        else:
            migrated, changed = _migrate_account(acc)
            if changed:
                accounts[name_str] = migrated
                cls._write(accounts)
            acc = migrated

        cls._last = acc
        return acc

    @classmethod
    def remove(cls, name: bytes) -> Account:
        name_str = name.decode()

        accounts = cls._read()
        if name_str not in accounts:
            raise KeyError(f"no account named {name}")

        acc = accounts.pop(name_str)
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

    @classmethod
    def default(cls) -> Account:
        return cls.get(b"default")


def _discover_migration_files() -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for _finder, name, _ispkg in pkgutil.iter_modules([AccountManager._MIGRATIONS_DIR]):
        prefix = name.split("_")[0]
        if prefix.isdigit():
            found.append((int(prefix), name))
    return sorted(found)


def _migrate_account(acc: Account) -> tuple[Account, bool]:
    current_version: int = acc.get("_version", 0)

    pending = [(version, module_name) for version, module_name in _discover_migration_files() if version > current_version]

    if not pending:
        return acc, False

    acc = copy.copy(acc)
    for version, module_name in pending:
        module = importlib.import_module(f"migration.{module_name}")
        acc = module.up(acc)
        print(f"[migration] applied {module_name} to account '{acc.get('name')}'")

    acc["_version"] = pending[-1][0]
    return acc, True
