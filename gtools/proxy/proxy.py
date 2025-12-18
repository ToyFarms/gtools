import logging
from queue import Queue
import threading
import time
import traceback
from typing import Generator, NamedTuple, cast
from gtools.core.eventbus import listen
from gtools.core.growtopia.packet import NetType, PreparedPacket, TankType
from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.variant import Variant
from gtools.core.utils.block_sigint import block_sigint
from gtools.proxy.enet import PyENetEvent
from gtools.proxy.event import UpdateServerData
from gtools.proxy.extension.broker import Broker, PacketCallback
from gtools.proxy.proxy_client import ProxyClient
from gtools.proxy.proxy_server import ProxyServer
from gtools.proxy.setting import _setting
from thirdparty.enet.bindings import ENetEventType
from thirdparty.hexdump import hexdump


class ProxyEvent(NamedTuple):
    inner: PyENetEvent
    direction: PreparedPacket.Direction


class Proxy:
    logger = logging.getLogger("proxy")

    def __init__(self) -> None:
        self.proxy_server = ProxyServer(_setting.proxy_server, _setting.proxy_port)
        self.logger.info(f"proxy server listening on {_setting.proxy_server}:{_setting.proxy_port}")
        self.proxy_client = ProxyClient()
        self.logger.debug("proxy client initialized")

        self.server_data: UpdateServerData | None = None
        self.redirecting: bool = False
        self.running = True

        self._event_queue: Queue[ProxyEvent | None] = Queue()
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._should_reconnect = threading.Event()
        self.broker = Broker()
        self.broker.start()

        self._last_event_time = -1
        self._event_elapsed = -1.0

        listen(UpdateServerData)(lambda ch, ev: self._on_server_data(ch, ev))

    def _on_server_data(self, _channel: str, event: UpdateServerData) -> None:
        self.logger.info(f"server_data: {event.server}:{event.port}")
        self.running = True
        self.server_data = event

    def _dump_packet(self, data: bytes) -> None:
        if self.logger.level > logging.DEBUG:
            return

        if self.logger.isEnabledFor(logging.DEBUG):
            dump = cast(Generator[str, None, None], hexdump(data, result="generator"))
            self.logger.debug(f"HEXDUMP: \n\t{'\n\t'.join(dump)}")
            self.logger.debug(f"\t{data}")

    def _handle_client_to_server(self, pkt: PreparedPacket) -> None:
        self.proxy_client.send(pkt.as_raw, pkt.flags)

    def _handle_server_to_client(self, pkt: PreparedPacket) -> None:
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

                    server_data[0, 0] = _setting.proxy_server
                    v[1] = Variant.vint(_setting.proxy_port)
                    v[4] = Variant.vstr(server_data.serialize())

                    pkt.as_net.tank.extended_data = v.serialize()

                    self.redirecting = True
                    self.proxy_server.send(pkt.as_net.serialize(), pkt.flags)
                    self.proxy_client.disconnect()

                    return
                elif fn == b"OnSuperMainStartAcceptLogonHrdxs47254722215a":
                    self.redirecting = False

        self.proxy_server.send(pkt.as_raw, pkt.flags)

    def _handle(self, pkt: PreparedPacket) -> None:
        res = self.broker.process_event(
            pkt,
            callback=PacketCallback(
                send_to_server=lambda pkt: self._handle_client_to_server(pkt),
                send_to_client=lambda pkt: self._handle_server_to_client(pkt),
            ),
        )
        modified = False
        if res:
            processed, cancelled = res
            if not cancelled:
                self.logger.debug(f"[original] packet={pkt!r} flags={pkt.flags!r} from={pkt.direction.name}")
                pkt = PreparedPacket.from_pending(processed)
                self.logger.debug(f"[{processed.packet_id}] processed packet: hit={processed.hit_count} rtt={int.from_bytes(processed.rtt_ns) / 1e6}us")
                modified = True
            else:
                self.logger.debug(f"[{processed.packet_id}] packet process cancelled")

        self.logger.debug(f"{'[modified] ' if modified else ''}packet={pkt!r} flags={pkt.flags!r} from={pkt.direction.name}")
        if pkt.as_net.type == NetType.TANK_PACKET:
            if pkt.as_net.tank.type in (
                TankType.APP_CHECK_RESPONSE,
                TankType.APP_INTEGRITY_FAIL,
            ):
                self.logger.debug(f"blocked {pkt.as_net.tank} from {pkt.direction.name}")
                return
            elif pkt.as_net.tank.type == TankType.DISCONNECT:
                src_ = self.proxy_client if pkt.direction == PreparedPacket.Direction.CLIENT_TO_SERVER else self.proxy_server
                src_.disconnect_now()
        if pkt.as_net.type == NetType.GAME_MESSAGE:
            if pkt.as_net.game_message["action", 1] == b"quit":
                self.disconnect_all()
                self.running = False

                return

        if pkt.direction == PreparedPacket.Direction.CLIENT_TO_SERVER:
            self._handle_client_to_server(pkt)
        elif pkt.direction == PreparedPacket.Direction.SERVER_TO_CLIENT:
            self._handle_server_to_client(pkt)

    def disconnect_all(self) -> None:
        self.proxy_client.disconnect()
        self.proxy_server.disconnect()

        if self.proxy_server.peer:
            self.logger.debug("waiting for proxy_server to disconnect...")
            while self.proxy_server.peer:
                self.proxy_server.poll()
        if self.proxy_client.peer:
            self.logger.debug("waiting for proxy_client to disconnect...")
            while self.proxy_client.peer:
                self.proxy_client.poll()

    def _worker(self) -> None:
        self.logger.debug("starting packet worker thread")
        while not self._stop_event.is_set():
            proxy_event = self._event_queue.get()
            if proxy_event is None:
                self._event_queue.task_done()
                continue

            self._event_elapsed = 0.0 if self._last_event_time == -1 else time.monotonic() - self._last_event_time
            event = proxy_event.inner

            if proxy_event.direction == PreparedPacket.Direction.CLIENT_TO_SERVER:
                self.logger.debug(f"[T+{self._event_elapsed:.3f}] from gt client ({event.packet.flags!r}):")
            elif proxy_event.direction == PreparedPacket.Direction.SERVER_TO_CLIENT:
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
                    )
                )
                self._dump_packet(event.packet.data)

            print()

            self._last_event_time = time.monotonic()
            self._event_queue.task_done()

        self.logger.debug("packet worker thread exited")

    def run(self) -> None:
        self.logger.info("proxy running")
        if self._worker_thread is None:
            self._worker_thread = threading.Thread(target=self._worker)
            self._worker_thread.start()

        try:
            while True:
                if not self.server_data:
                    self.logger.info("waiting for server_data...")
                    while not self.server_data:
                        time.sleep(0.16)

                self.logger.info("waiting for growtopia to connect...")
                while not self.proxy_server.peer:
                    self.proxy_server.poll()
                    time.sleep(0.16)

                self.logger.info(f"proxy_client connecting to {self.server_data.server}:{self.server_data.port}")
                self.proxy_client.connect(self.server_data.server, self.server_data.port)
                self.logger.info("connected! now polling for events")

                MAX_POLL_MS = 100

                while True:
                    start = time.perf_counter()
                    while (event := self.proxy_server.poll()) and ((time.perf_counter() - start) * 1000.0 < MAX_POLL_MS):
                        self._event_queue.put(ProxyEvent(event, PreparedPacket.Direction.CLIENT_TO_SERVER))

                    start = time.perf_counter()
                    while (event := self.proxy_client.poll()) and ((time.perf_counter() - start) * 1000.0 < MAX_POLL_MS):
                        self._event_queue.put(ProxyEvent(event, PreparedPacket.Direction.SERVER_TO_CLIENT))

                    if self._should_reconnect.is_set():
                        self.disconnect_all()
                        self._should_reconnect.clear()
                        break

                with self._event_queue.mutex:
                    self._event_queue.queue.clear()
                    self._event_queue.unfinished_tasks = 0
                    self._event_queue.all_tasks_done.notify_all()

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
                self._event_queue.put(None)
                self._worker_thread.join()
