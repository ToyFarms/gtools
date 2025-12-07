from typing import Any, SupportsBytes, cast, overload
from gtools.core.protocol import Serializable


def decode_with_hex(data: bytes) -> str:
    result = []
    for b in data:
        try:
            result.append(bytes([b]).decode("utf-8"))
        except UnicodeDecodeError:
            result.append(f"\\x{b:02x}")
    return "".join(result)


type KValue = int | str | bytes


def _val(key: KValue) -> bytes:
    if isinstance(key, int):
        return str(key).encode("utf-8", errors="strict")
    elif isinstance(key, str):
        return key.encode("utf-8", errors="strict")
    else:
        return key


def _vals(keys: list[KValue]) -> list[bytes]:
    return [_val(key) for key in keys]


class StrKV(Serializable):
    def __init__(self, data: list[list[bytes]] = [], delim: str = "|") -> None:
        self.data = data
        self.delim = delim
        self._index_lookup: dict[bytes, int] = {v[0]: k for k, v in enumerate(data)}

    @overload
    def __getitem__(self, key: int | str | bytes) -> list[bytes]: ...
    @overload
    def __getitem__(self, key: tuple[int | str | bytes, int]) -> bytes: ...
    @overload
    def __getitem__(self, key: tuple[int | str | bytes, slice]) -> list[bytes]: ...

    def __getitem__(self, key: object) -> object:
        if isinstance(key, str):
            key = key.encode()

        if isinstance(key, int):
            return self.data[key]
        elif isinstance(key, bytes):
            return self.data[self._index_lookup[key]]
        elif isinstance(key, tuple):
            row_key, col = key
            if isinstance(row_key, str):
                row_key = row_key.encode()

            index = row_key if isinstance(row_key, int) else self._index_lookup[row_key]
            return self.data[index][col]

    @overload
    def __setitem__(self, key: int | str | bytes, value: list[KValue]) -> None: ...
    @overload
    def __setitem__(
        self, key: tuple[int | str | bytes, int], value: KValue
    ) -> None: ...

    def __setitem__(
        self,
        key: Any,
        value: Any,
    ) -> None:
        if isinstance(key, str):
            key = key.encode()

        if isinstance(key, int):
            self.data[key] = _vals(value)
            self._index_lookup = {v[0]: k for k, v in enumerate(self.data)}
        elif isinstance(key, bytes):
            index = self._index_lookup[key]
            self.data[index] = _vals(value)
        elif isinstance(key, tuple):
            row_key, col = key
            if isinstance(row_key, str):
                row_key = row_key.encode()

            index = row_key if isinstance(row_key, int) else self._index_lookup[row_key]
            self.data[index][col] = _val(value)

    def append(self, row: list[KValue]) -> None:
        self.data.append(_vals(row))
        self._index_lookup = {v[0]: k for k, v in enumerate(self.data)}

    def serialize(self) -> bytes:
        return b"\n".join(b"|".join(row for row in data) for data in self.data)

    @classmethod
    def deserialize(cls, data: bytes) -> "StrKV":
        body: list[list[bytes]] = []
        for part in data.split(b"\n"):
            body.append(part.split(b"|"))

        return cls(body)

    def __repr__(self) -> str:
        return f"{{{", ".join(f"'{a}'" for a in ("|".join(decode_with_hex(row) for row in data) for data in self.data))}}}"


if __name__ == "__main__":
    # sample = b"action|input|test|123\ntext|awjiawjidoa\xd5\n|test|123\n"
    # kv = StrKV.deserialize(sample)
    #
    # print(kv)
    # print(kv[0, 1])
    #
    # kv[0, 1] = b"modified"
    # print(kv)
    #
    # kv[1] = [b"i dont know", b"test", b"09128"]
    # print(kv)
    #
    # kv[-1, 0] = b"test"
    # print(kv)
    #
    # kv[-1].append(b"object")
    # print(kv[-1])
    # print(kv)
    #
    # kv[-2, 0] = b"first"
    # print(kv)
    #
    # print(kv.serialize())
    #
    # a = StrKV.deserialize(b"test|123")
    # a.set[b"test"] = b"another"
    # print(a)
    #
    # a.set[0] = 123
    # print(a)
    #
    # a.append(["new", "row no", 999999])
    # print(a)

    res = b"server|127.0.0.1\nport|16999\nloginurl|login.growtopiagame.com\ntype|1\nbeta_server|grow-main-test.growtopiagame.com\nbeta_loginurl|grow-main-test.growtopiagame.com\nbeta_port|56999\nbeta_type|1\nbeta2_server|grow-release-test.growtopiagame.com\nbeta2_loginurl|grow-release-test.growtopiagame.com\nbeta2_port|36999\nbeta2_type|1\nbeta3_server|grow-live-test.growtopiagame.com\nbeta3_loginurl|grow-live-test.growtopiagame.com\nbeta3_port|46999\nbeta3_type|1\ntype2|1\n#maint|Server is under maintenance. We will be back online shortly. Thank you for your patience!\nmeta|VOZ5jj5wgJAHsPD9EIBYrWFWJwQ4jmm4g55rtFxrBUY=\nRTENDMARKERBS1001"

    kv = StrKV.deserialize(res)
    print(kv["server", 1])
    print(kv["port", 1])

    kv["server", 1] = "test"

    print(kv["server", 1])
