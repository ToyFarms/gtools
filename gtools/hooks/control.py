from dataclasses import dataclass

from gtools.core.pipe import PipeClient, PipeError, PipeEvent, PipeUnavailable

PIPE_NAME = r"\\.\pipe\gtools_hook"


@dataclass(frozen=True)
class HookState:
    client_version: str = ""
    client_protocol: str = ""
    client_platform: str = ""
    real_server: str = ""
    real_port: int = 0

    @classmethod
    def from_fields(cls, fields: dict[str, str]) -> "HookState":
        try:
            port = int(fields.get("real_port", "") or 0)
        except ValueError:
            port = 0
        return cls(
            client_version=fields.get("client_version", ""),
            client_protocol=fields.get("client_protocol", ""),
            client_platform=fields.get("client_platform", ""),
            real_server=fields.get("real_server", ""),
            real_port=port,
        )


def _parse_pairs(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in text.split(" "):
        key, separator, value = part.partition("=")
        if separator:
            result[key] = value

    return result


class HookControl:
    def __init__(self, timeout: float = 2.0) -> None:
        self.timeout = timeout
        self._client = PipeClient(PIPE_NAME, connect_timeout=timeout, io_timeout=timeout)

    def connect(self, timeout: float | None = None) -> bool:
        try:
            self._client.connect(timeout)
            return True
        except PipeUnavailable:
            return False

    def close(self) -> None:
        self._client.close()

    @property
    def connected(self) -> bool:
        return self._client.connected

    def ping(self, timeout: float | None = None) -> bool:
        try:
            return self._client.request("PING", timeout).ok
        except (PipeError, PipeUnavailable):
            return False

    def status(self, timeout: float | None = None) -> dict[str, str]:
        response = self._client.request("STATUS", timeout)
        if response.kind != "DATA":
            raise PipeError(f"unexpected status reply: {response.kind} {response.text}")

        return _parse_pairs(response.text)

    def get(self, key: str, timeout: float | None = None) -> str | None:
        response = self._client.request(f"GET {key}", timeout)
        if response.kind != "VALUE":
            return None
        _, separator, value = response.text.partition(" ")
        if not separator:
            return ""

        return value

    def set(self, key: str, value: str, timeout: float | None = None) -> bool:
        response = self._client.request(f"SET {key} {value}", timeout)

        return response.ok

    def handshake(self, timeout: float | None = None) -> bytes | None:
        response = self._client.request("HANDSHAKE", timeout)
        if response.kind != "HANDSHAKE":
            return

        try:
            return bytes.fromhex(response.text.strip())
        except ValueError:
            return

    def wait_event(self, timeout: float | None = None) -> PipeEvent | None:
        return self._client.wait_event(timeout)

    def wait_state(self, timeout: float | None = None) -> HookState | None:
        while True:
            event = self._client.wait_event(timeout)
            if event is None:
                return None
            if event.name == "state":
                return HookState.from_fields(event.fields)
