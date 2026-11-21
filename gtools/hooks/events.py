"""Event decoding and dispatch (all policy, no mechanism).

The agent forwards two pipe event kinds:

- ``log <text>``          shim diagnostics (already level-filtered C-side)
- ``hook <key> <kind> <hex>``  hook events; kinds are Python-defined

This module turns those into log records and proxy events
(``UpdateClientVersion`` / ``UpdateServerData``).
"""

from __future__ import annotations

import binascii
import logging
from dataclasses import dataclass, field
from typing import Callable

from gtools.core.pipe import PipeEvent

logger = logging.getLogger("hook")

# must match gtools/hooks/programs.py
EVENT_TEXT = 1
EVENT_RESPONSE_SERVER = 11
EVENT_RESPONSE_PORT = 12
EVENT_POST_CAPTURE = 13

StateCallback = Callable[[dict[str, str]], None]


@dataclass
class CaptureState:
    """Last known client/server capture (from the hook events)."""

    client_version: str = ""
    client_protocol: str = ""
    client_platform: str = ""
    real_server: str = ""
    real_port: int = 0

    def as_fields(self) -> dict[str, str]:
        return {
            "client_version": self.client_version,
            "client_protocol": self.client_protocol,
            "client_platform": self.client_platform,
            "real_server": self.real_server,
            "real_port": str(self.real_port),
        }


@dataclass
class HookEventSink:
    """Consumes pipe events, maintains the capture state, publishes proxy events.

    ``on_state`` receives a fields dict whenever a capture completes (the same
    shape the old ``state`` event produced).
    """

    on_state: StateCallback | None = None
    capture: CaptureState = field(default_factory=CaptureState)

    def process(self, event: PipeEvent | None) -> None:
        if event is None:
            return
        if event.name == "log":
            # the agent's own lines already carry the [hook] tag
            logger.info("%s", event.payload.removeprefix("[hook] "))
            return
        if event.name != "hook":
            return

        parts = event.payload.split(" ", 3)
        if len(parts) != 4:
            logger.debug("malformed hook event: %r", event.payload)
            return
        key, kind_text, hex_data = parts[1], parts[2], parts[3]
        try:
            kind = int(kind_text)
            data = binascii.unhexlify(hex_data)
        except (ValueError, binascii.Error):
            logger.debug("malformed hook event payload: %r", event.payload)
            return

        if key == "net/response" and kind == EVENT_RESPONSE_SERVER:
            self._capture_line(data)
        elif key == "net/response" and kind == EVENT_RESPONSE_PORT:
            self._capture_line(data)
        elif key == "net/post" and kind == EVENT_POST_CAPTURE:
            self._capture_post(data)
        else:
            logger.debug("hook %s event kind %d (%d bytes)", key, kind, len(data))

    # -- captures ----------------------------------------------------------

    def _capture_line(self, data: bytes) -> None:
        text = data.decode("utf-8", "replace").rstrip("\r\n")
        key, separator, value = text.partition("|")
        if not separator:
            return
        if key == "server":
            self.capture.real_server = value
        elif key == "port":
            try:
                self.capture.real_port = int(value)
            except ValueError:
                logger.warning("hook returned invalid port: %r", value)
                return
        self._publish_if_complete()

    def _capture_post(self, data: bytes) -> None:
        for line in data.decode("utf-8", "replace").splitlines():
            key, separator, value = line.partition("=")
            if not separator:
                continue
            if key == "version":
                self.capture.client_version = value
            elif key == "protocol":
                self.capture.client_protocol = value
            elif key == "platform":
                self.capture.client_platform = value
        self._publish_if_complete()

    def _publish_if_complete(self) -> None:
        capture = self.capture
        version_ready = capture.client_version and capture.client_protocol
        server_ready = capture.real_server and capture.real_port
        if not (version_ready or server_ready):
            return
        if self.on_state is not None:
            self.on_state(capture.as_fields())


def publish_hook_state(fields: dict[str, str]) -> None:
    """Forward a captured state to the proxy (same as the old state event)."""
    from gtools.hooks.hook import forward_hook_state  # late import: hook.py owns the eventbus wiring

    forward_hook_state(fields)
