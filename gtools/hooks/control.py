"""Control pipe client for the hook agent (generic v4 commands)."""

from __future__ import annotations

import binascii
import struct
from dataclasses import dataclass

from gtools.core.pipe import PipeClient, PipeError, PipeEvent, PipeUnavailable
from gtools.hooks.payload import (
    DATA_MAX,
    EVENT_SLOTS,
    HOOK_MAX,
    STATE_SLOTS,
    HANDSHAKE_ENTRY,
    PIPE_NAME,
    PROTOCOL_MAGIC,
    PROTOCOL_VERSION,
)

MAX_DATA_CHUNK = 1024  # hex-encoded: fits the 4096-byte pipe line


@dataclass(frozen=True)
class HookHandshakeEntry:
    key: str
    status: int
    index: int
    target: int
    trampoline: int


@dataclass(frozen=True)
class HookHandshake:
    process_id: int
    image_base: int
    image_size: int
    dll_base: int
    entries: tuple[HookHandshakeEntry, ...]


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

    def hooks(self, timeout: float | None = None) -> dict[str, dict[str, int]]:
        """Per-hook summary: key -> {status, enabled, hits, state0}."""
        response = self._client.request("HOOKS", timeout)
        if response.kind != "DATA":
            raise PipeError(f"unexpected hooks reply: {response.kind} {response.text}")
        result: dict[str, dict[str, int]] = {}
        for part in response.text.split(" ")[1:]:
            fields = part.split(":")
            if len(fields) != 5:
                continue
            key = fields[0]
            try:
                result[key] = {
                    "status": int(fields[1]),
                    "enabled": int(fields[2]),
                    "hits": int(fields[3]),
                    "state0": int(fields[4]),
                }
            except ValueError:
                continue
        return result

    def handshake(self, timeout: float | None = None) -> HookHandshake | None:
        response = self._client.request("HANDSHAKE", timeout)
        if response.kind != "HANDSHAKE":
            return None
        try:
            blob = binascii.unhexlify(response.text.strip())
        except (ValueError, binascii.Error):
            return None
        magic, version, count, _reserved = struct.unpack_from("<IIII", blob, 0)
        if magic != PROTOCOL_MAGIC or version != PROTOCOL_VERSION:
            return None
        process_id, image_base, image_size, dll_base = struct.unpack_from("<QQQQ", blob, 16)
        entries: list[HookHandshakeEntry] = []
        offset = 48
        for index in range(min(count, HOOK_MAX)):
            key, status, entry_index, target, trampoline = HANDSHAKE_ENTRY.unpack_from(blob, offset)
            entries.append(
                HookHandshakeEntry(
                    key=key.rstrip(b"\0").decode(),
                    status=status,
                    index=entry_index,
                    target=target,
                    trampoline=trampoline,
                )
            )
            offset += HANDSHAKE_ENTRY.size
        return HookHandshake(
            process_id=process_id,
            image_base=image_base,
            image_size=image_size,
            dll_base=dll_base,
            entries=tuple(entries),
        )

    def enable(self, key: str, on: bool, timeout: float | None = None) -> bool:
        response = self._client.request(f"ENABLE {key} {1 if on else 0}", timeout)
        return response.ok

    def state(self, key: str, slot: int, value: int, timeout: float | None = None) -> bool:
        if not 0 <= slot < STATE_SLOTS:
            raise ValueError(f"state slot {slot} out of range")
        response = self._client.request(f"STATE {key} {slot} {int(value) & 0xFFFFFFFFFFFFFFFF}", timeout)
        return response.ok

    def data(self, key: str, offset: int, blob: bytes, timeout: float | None = None) -> bool:
        """Write bytes into a hook's runtime data blob (chunked)."""
        if offset < 0 or offset + len(blob) > DATA_MAX:
            raise ValueError("data write out of range")
        for chunk_start in range(0, max(len(blob), 1), MAX_DATA_CHUNK):
            chunk = blob[chunk_start:chunk_start + MAX_DATA_CHUNK]
            if not chunk:
                break
            hex_data = binascii.hexlify(chunk).decode()
            response = self._client.request(f"DATA {key} {offset + chunk_start} {hex_data}", timeout)
            if not response.ok:
                return False
        return True

    def log_level(self, level: int, timeout: float | None = None) -> bool:
        response = self._client.request(f"LOGLEVEL {int(level)}", timeout)
        return response.ok

    def wait_event(self, timeout: float | None = None) -> PipeEvent | None:
        return self._client.wait_event(timeout)
