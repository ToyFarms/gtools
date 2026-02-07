import ctypes
import logging
import os
from queue import Queue
import threading
import time
import traceback
from typing import Generator, NamedTuple, cast

from gtools.core.eventbus import listen
from gtools.core.growtopia.packet import NetType, PreparedPacket, TankType
from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.variant import Variant
from gtools.core.block_sigint import block_sigint
from gtools.protogen.extension_pb2 import DIRECTION_CLIENT_TO_SERVER, DIRECTION_SERVER_TO_CLIENT, Direction, Packet, StateResponse
from gtools.proxy.accountmgr import AccountManager
from gtools.proxy.enet import PyENetEvent
from gtools.proxy.event import UpdateServerData
from gtools.proxy.extension.broker import Broker, BrokerFunction, PacketCallback
from gtools.proxy.proxy_client import ProxyClient
from gtools.proxy.proxy_server import ProxyServer
from gtools import setting
from gtools.proxy.state import State, Status
from thirdparty.enet.bindings import ENetEventType, ENetPeer, enet_host_flush
from thirdparty.hexdump import hexdump


class ProxyEvent(NamedTuple):
    inner: PyENetEvent
    direction: Direction


class Proxy:
    logger = logging.getLogger("proxy")

    def __init__(self) -> None:
        self.proxy_server = ProxyServer(setting.proxy_server, setting.proxy_port)
        self.logger.info(f"proxy server listening on {setting.proxy_server}:{setting.proxy_port}")
        self.proxy_client = ProxyClient()
        self.logger.debug("proxy client initialized")

        self.server_data: UpdateServerData | None = None
        self.redirecting: bool = False
        self.running = True

        self._event_queue: Queue[tuple[ProxyEvent | None, int]] = Queue()
        self._worker_thread_id: threading.Thread | None = None
        self._channel_thread_id: threading.Thread | None = None
        self._worker_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._should_reconnect = threading.Event()
        self._worker_should_process = threading.Event()
        self._packet_version = 0  # this is used to invalidate old packets that is left behind when restarting application

        self._channel_queue: Queue[tuple[PreparedPacket | None, int]] = Queue()
        addr = f"tcp://127.0.0.1:{os.getenv('PORT', 6712)}"
        self.broker = Broker(lambda pkt: self._channel_queue.put((pkt, self._packet_version)), addr)
        self.logger.debug(f"starting broker on {addr}")
        self.broker.start()
        self.broker.set_handler(Packet.TYPE_STATE_REQUEST, self._state_request)

        self._last_event_time = -1
        self._event_elapsed = -1.0

        self.state = State()
        self._last_telemetry_update: float = 0.0
        self._telemetry_update_interval: float = 0.1
        self._in_dialog = False

        listen(UpdateServerData)(lambda ch, ev: self._on_server_data(ch, ev))

    def _state_request(self, _id: bytes, _pkt: Packet, fn: BrokerFunction) -> None:
        fn.reply(
            Packet(
                type=Packet.TYPE_STATE_RESPONSE,
                state_response=StateResponse(state=self.state.to_proto()),
            )
        )

    def _on_server_data(self, _channel: str, event: UpdateServerData) -> None:
        self.logger.info(f"server_data: {event.server}:{event.port}")
        self.running = True
        self.server_data = event

    def _dump_packet(self, data: bytes) -> None:
        if self.logger.isEnabledFor(logging.DEBUG):
            dump = cast(Generator[str, None, None], hexdump(data, result="generator"))
            self.logger.debug(f"HEXDUMP: \n\t{'\n\t'.join(dump)}")
            self.logger.debug(f"\t{data}")

    def _handle_client_to_server(self, pkt: PreparedPacket) -> None:
        self.proxy_client.send(pkt.as_raw, pkt.flags)

    def _handle_server_to_client(self, pkt: PreparedPacket) -> None:
        try:
            if pkt.as_net.type == NetType.TANK_PACKET:
                if pkt.as_net.tank.type == TankType.CALL_FUNCTION:
                    v = Variant.deserialize(pkt.as_net.tank.extended_data)
                    fn = v.as_string[0]
                    if fn == b"OnSendToServer":
                        port = v.as_int[1]
                        server_data = StrKV.deserialize(v.as_string[4])

                        self.server_data = UpdateServerData(
                            server=server_data[0, 0].decode(),
                            port=port,
                        )
                        self.logger.info(f"redirecting to {self.server_data.server}:{self.server_data.port}")

                        server_data[0, 0] = setting.proxy_server
                        v[1] = Variant.vint(setting.proxy_port)
                        v[4] = Variant.vstr(server_data.serialize())

                        pkt.as_net.tank.extended_data = v.serialize()

                        self.redirecting = True
                        self.proxy_server.send(pkt.as_net.serialize(), pkt.flags)
                        enet_host_flush(self.proxy_server.host)
                        self.proxy_client.disconnect()
                        self.proxy_server.disconnect()
                        self._should_reconnect.set()

                        return
                    elif fn == b"OnSuperMainStartAcceptLogonHrdxs47254722215a":
                        self.redirecting = False
                        self.state.update_status(self.broker, Status.LOGGED_IN)
        except:
            self.logger.exception("error handling server_to_client")
            if setting.panic_on_packet_error:
                raise

            # last effort
            if b"OnSendToServer" in pkt.as_raw:
                self.redirecting = True
                self.proxy_server.send(pkt.as_raw, pkt.flags)
                enet_host_flush(self.proxy_server.host)

                self.proxy_client.disconnect()
                self.proxy_server.disconnect()
                self._should_reconnect.set()
                return

        self.proxy_server.send(pkt.as_raw, pkt.flags)

    def _handle(self, pkt: PreparedPacket, *, fabricated: bool) -> None:
        modified = False
        if not fabricated:
            try:
                _pkt_replace: PreparedPacket | None = None
                res = self.broker.process_event(
                    pkt,
                    callback=PacketCallback(any=lambda pkt: self._handle(pkt, fabricated=True)),
                )
                if res:
                    processed, cancelled = res
                    if cancelled:
                        self.logger.debug(f"[{processed._packet_id}] packet process cancelled")
                        return

                    self.logger.debug(f"[original] packet={pkt!r} flags={pkt.flags!r} from={Direction.Name(pkt.direction)}")
                    _pkt_replace = PreparedPacket.from_pending(processed)
                    self.logger.debug(f"[{processed._packet_id}] processed packet: hit={processed._hit_count} rtt={processed._rtt_ns / 1e6}us")
                    modified = True

                if _pkt_replace:
                    pkt = _pkt_replace
            except Exception as e:
                self.logger.error(f"process_event failed: {e}")

        try:
            self.state.emit_event(self.broker, pkt)
        except Exception as e:
            self.logger.error(f"FAILED UPDATING STATE: {e}")

        try:
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"{'[modified] ' if modified else '[fabricated] ' if fabricated else ''}packet={pkt!r} flags={pkt.flags!r} from={Direction.Name(pkt.direction)}")
            else:
                self.logger.info(
                    f"from {'\x1b[32mserver\x1b[0m' if pkt.direction == DIRECTION_SERVER_TO_CLIENT else '\x1b[31mclient\x1b[0m'} ({pkt.as_net.type.name}) {pkt.as_net.compact_repr()}"
                )
            if pkt.as_net.type == NetType.TANK_PACKET:
                if pkt.as_net.tank.type in (
                    TankType.APP_CHECK_RESPONSE,
                    TankType.APP_INTEGRITY_FAIL,
                ):
                    self.logger.info(f"blocked {pkt.as_net.tank} from {Direction.Name(pkt.direction)}")
                    return
                elif pkt.as_net.tank.type == TankType.DISCONNECT:
                    src_ = self.proxy_client if pkt.direction == DIRECTION_CLIENT_TO_SERVER else self.proxy_server
                    src_.disconnect_now()
            elif pkt.as_net.type == NetType.GENERIC_TEXT:
                if (
                    setting.spoof_hwident
                    and pkt.direction == DIRECTION_CLIENT_TO_SERVER
                    and pkt.as_net.type == NetType.GENERIC_TEXT
                    and (b"mac" in pkt.as_net.generic_text or b"hash" in pkt.as_net.generic_text or b"hash2" in pkt.as_net.generic_text or b"wk" in pkt.as_net.generic_text)
                ):
                    orig = pkt.as_net.generic_text.copy()
                    try:
                        name = bytes(orig["tankIDName", 1])
                        acc = AccountManager.get(name) if name else AccountManager.last()
                    except KeyError:
                        pass

                    if not acc:
                        acc = AccountManager.default()

                    for field, value in acc["ident"].items():
                        if field not in pkt.as_net.generic_text:
                            self.logger.warning(f"skipping spoof for {field} because it does not exists originally")
                            continue

                        self.logger.info(f"spoofing {field} for {acc['name']}, {orig[field]} -> {value}")
                        pkt.as_net.generic_text[field] = value

                    self.logger.info(f"spoofed login: {pkt.as_net.generic_text}")
            elif pkt.as_net.type == NetType.GAME_MESSAGE:
                if pkt.as_net.game_message["action", 1] == b"quit":
                    self.disconnect_all()
                    self.running = False
                    self._should_reconnect.set()

                    return
            elif pkt.as_net.type == NetType.SERVER_HELLO:
                self.state.update_status(self.broker, Status.LOGGING_IN)

            if (
                pkt.as_net.type == NetType.TANK_PACKET
                and pkt.as_net.tank.type == TankType.CALL_FUNCTION
                and Variant.get(pkt.as_net.tank.extended_data, 0).value == b"OnDialogRequest"
            ):
                self.logger.debug("dialog enter")
                self._in_dialog = True
            elif pkt.as_net.type == NetType.GENERIC_TEXT and b"action" in pkt.as_net.generic_text and pkt.as_net.generic_text[b"action"] == b"dialog_return":
                self.logger.debug("dialog exit")
                self._in_dialog = False
        except:
            self.logger.exception("something failed")
            if setting.panic_on_packet_error:
                raise

        if pkt.direction == DIRECTION_CLIENT_TO_SERVER:
            self._handle_client_to_server(pkt)
        elif pkt.direction == DIRECTION_SERVER_TO_CLIENT:
            self._handle_server_to_client(pkt)

    def disconnect_all(self) -> None:
        self.proxy_client.disconnect_now()
        self.proxy_server.disconnect_now()
        self._should_reconnect.set()
        self.logger.info("gt client disconnected")

    def _worker(self) -> None:
        self.logger.debug("starting packet worker thread")
        while not self._stop_event.is_set():
            self._worker_should_process.wait()
            proxy_event, ver = self._event_queue.get()
            if proxy_event is None or ver != self._packet_version:
                continue

            with self._worker_lock:
                self._event_elapsed = 0.0 if self._last_event_time == -1 else time.monotonic() - self._last_event_time
                event = proxy_event.inner

                if self.logger.isEnabledFor(logging.DEBUG):
                    if proxy_event.direction == DIRECTION_CLIENT_TO_SERVER:
                        self.logger.debug(f"[T+{self._event_elapsed:.3f}] from gt client ({event.packet.flags!r}):")
                    elif proxy_event.direction == DIRECTION_SERVER_TO_CLIENT:
                        self.logger.debug(f"[T+{self._event_elapsed:.3f}] from gt server ({event.packet.flags!r}):")

                if event.type == ENetEventType.DISCONNECT:
                    self._should_reconnect.set()

                self.logger.debug(f"\t{ENetEventType(event.type)!r}")
                if event.type == ENetEventType.RECEIVE and event.packet.data:
                    self._handle(
                        PreparedPacket(
                            packet=event.packet.data,
                            direction=proxy_event.direction,
                            flags=event.packet.flags,
                        ),
                        fabricated=False,
                    )
                    self._dump_packet(event.packet.data)

                if self.logger.isEnabledFor(logging.DEBUG):
                    print()

                self._last_event_time = time.monotonic()

        self.logger.debug("packet worker thread exited")

    def _channel_worker(self) -> None:
        while not self._stop_event.is_set():
            self._worker_should_process.wait()
            pkt, ver = self._channel_queue.get()
            if pkt is None or ver != self._packet_version:
                continue

            with self._worker_lock:
                self._event_elapsed = 0.0 if self._last_event_time == -1 else time.monotonic() - self._last_event_time

                if self.logger.isEnabledFor(logging.DEBUG):
                    if pkt.direction == DIRECTION_CLIENT_TO_SERVER:
                        self.logger.debug(f"[T+{self._event_elapsed:.3f}] from gt client ({pkt.flags!r}):")
                    elif pkt.direction == DIRECTION_SERVER_TO_CLIENT:
                        self.logger.debug(f"[T+{self._event_elapsed:.3f}] from gt server ({pkt.flags!r}):")

                self._handle(pkt, fabricated=True)
                if self.logger.isEnabledFor(logging.DEBUG):
                    self._dump_packet(pkt.as_raw)
                    print()

                self._last_event_time = time.monotonic()

        self.logger.debug("channel worker thread exited")

    def run(self) -> None:
        self.logger.info("proxy running")
        if self._worker_thread_id is None:
            self._worker_thread_id = threading.Thread(target=self._worker)
            self._worker_thread_id.start()

        if self._channel_thread_id is None:
            self._channel_thread_id = threading.Thread(target=self._channel_worker)
            self._channel_thread_id.start()

        try:
            while True:
                self.state.update_status(self.broker, Status.CONNECTING)
                if not self.server_data:
                    self.logger.info("waiting for server_data...")
                    while not self.server_data:
                        time.sleep(0.16)

                self.proxy_client.disconnect_now()
                self.proxy_client = ProxyClient()

                self.logger.info("waiting for growtopia to connect...")
                while not self.proxy_server.peer:
                    self.proxy_server.poll()
                    time.sleep(0.16)

                self.logger.info(f"proxy_client connecting to {self.server_data.server}:{self.server_data.port}")
                self.proxy_client.connect(self.server_data.server, self.server_data.port)
                self.logger.info("all connected! now polling for events")
                self.state.update_status(self.broker, Status.CONNECTED)

                MAX_POLL_MS = 100

                self._worker_should_process.set()
                while True:
                    start = time.perf_counter()
                    while (event := self.proxy_server.poll()) and ((time.perf_counter() - start) * 1000.0 < MAX_POLL_MS):
                        self._event_queue.put((ProxyEvent(event, DIRECTION_CLIENT_TO_SERVER), self._packet_version))

                    start = time.perf_counter()
                    while (event := self.proxy_client.poll()) and ((time.perf_counter() - start) * 1000.0 < MAX_POLL_MS):
                        self._event_queue.put((ProxyEvent(event, DIRECTION_SERVER_TO_CLIENT), self._packet_version))

                    if time.time() - self._last_telemetry_update > self._telemetry_update_interval:
                        self.state.telemetry.server_ping = ctypes.cast(self.proxy_client.peer, ctypes.POINTER(ENetPeer)).contents.roundTripTime if self.proxy_client.peer else 0
                        self.state.telemetry.client_ping = ctypes.cast(self.proxy_server.peer, ctypes.POINTER(ENetPeer)).contents.roundTripTime if self.proxy_server.peer else 0
                        with self.broker.suppressed_log():
                            self.state.emit_telemetry(self.broker)

                    if self._should_reconnect.is_set():
                        self.disconnect_all()
                        self._should_reconnect.clear()
                        with self.broker.suppressed_log():
                            self.state.emit_telemetry(self.broker)
                        break

                self._worker_should_process.clear()
                self._packet_version += 1

        except (InterruptedError, KeyboardInterrupt):
            pass
        except Exception as e:
            traceback.print_exc()
            self.logger.error(f"failed: {e}")
        finally:
            with block_sigint():
                self.broker.stop()

                self.proxy_server.disconnect_now()
                self.proxy_client.disconnect_now()

                self.proxy_server.destroy()
                self.proxy_client.destroy()

                self._stop_event.set()
                self._worker_should_process.set()
                self._event_queue.put((None, 0))
                self._worker_thread_id.join()
                self._channel_queue.put((None, 0))
                self._channel_thread_id.join()
