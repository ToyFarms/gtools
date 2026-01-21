from abc import abstractmethod
from argparse import ArgumentParser
from contextlib import contextmanager
from queue import Empty
import struct
from typing import Callable, Iterator, cast
import os
import threading
import traceback
import zmq
import logging
import time

from gtools.core.growtopia.packet import PreparedPacket
from gtools.core.log import setup_logger
from gtools.core.network import increment_port
from gtools.core.signal import Signal
from gtools.core.transport.protocol import Event
from gtools.core.transport.zmq_transport import Push, Dealer
from gtools.flags import PERF
from gtools.protogen.extension_pb2 import (
    CapabilityResponse,
    Packet,
    Interest,
    PendingPacket,
)
from gtools.protogen.state_pb2 import STATE_SET_MY_TELEMETRY
from gtools.proxy.extension.sdk_utils import ExtensionUtility
from gtools.proxy.state import State, Status
from gtools import setting


def register_thread(fn: Callable) -> Callable:
    fn._mark_thread = True
    return fn


type DispatchHandle = Callable[[PendingPacket], PendingPacket | None]
type UnboundDispatchHandle[S: Extension] = Callable[[S, PendingPacket], PendingPacket | None]


def dispatch(interest: Interest) -> Callable[[UnboundDispatchHandle], UnboundDispatchHandle]:
    def wrapper(fn: UnboundDispatchHandle) -> UnboundDispatchHandle:

        interests: list[Interest] | object | None = getattr(fn, "__dispatch_interest_list", None)
        if isinstance(interests, list):
            interests.append(interest)
        else:
            setattr(fn, "__dispatch_interest_list", [interest])

        return fn

    return wrapper


def dispatch_fallback(fn: UnboundDispatchHandle) -> UnboundDispatchHandle:
    setattr(fn, "__dispatch_interest_fallback", True)
    return fn


class Extension(ExtensionUtility):
    logger = logging.getLogger("extension")

    def __init__(self, name: str | bytes, interest: list[Interest], broker_addr: str | None = None) -> None:
        self._name = name.encode() if isinstance(name, str) else name
        self._interest = interest
        self._broker_addr = broker_addr if broker_addr else f"tcp://127.0.0.1:{os.getenv("PORT", 6712)}"

        self._context = zmq.Context()
        self._dealer = Dealer(self._context, self._name, self._broker_addr)
        self._push = Push(self._context, increment_port(self._broker_addr))

        self._worker_thread_id: threading.Thread | None = None

        self._stop_event = Signal(False)
        self.broker_connected = Signal(False)
        self.push_connected = Signal(False)
        self.connected = Signal.derive(lambda: self.broker_connected.get() and self.push_connected.get(), self.broker_connected, self.push_connected)
        self.disconnected = Signal.derive(lambda: not self.broker_connected.get() and not self.push_connected.get(), self.broker_connected, self.push_connected)

        self._job_threads: dict[str, threading.Thread] = {}
        self._dispatch_routes: dict[int, DispatchHandle] = {}
        self._dispatch_fallback: DispatchHandle | None = None
        self.state = State()
        self._last_heartbeat = 0

        self._suppress_log = False
        self.__push_fallback_called = 0
        self.__push_fallback_warned = 0
        self._running = False

    def push(self, pkt: PreparedPacket) -> None:
        self.push_connected.wait_true(timeout=5.0)
        # self.logger.debug(f"   push \x1b[35m-->>\x1b[0m \x1b[35m>>\x1b[0m{pkt!r}\x1b[35m>>\x1b[0m")
        pending = pkt.to_pending()
        pending._rtt_ns = time.monotonic_ns()

        if not self.push_connected:
            if not self.__push_fallback_called and self.__push_fallback_warned > 10:
                self.logger.warning("push/pull socket is not enabled, fallback to a slower path using broker")
                self.__push_fallback_called = True
            self.__push_fallback_called += 1

            self._send(Packet(type=Packet.TYPE_PUSH_PACKET, push_packet=pending))
        else:
            self._push.send(pending.SerializeToString())

    def _send(self, pkt: Packet) -> None:
        if self._stop_event.get():
            return

        if not self._suppress_log:
            self.logger.debug(f"   send \x1b[31m-->>\x1b[0m \x1b[31m>>\x1b[0m{pkt!r}\x1b[31m>>\x1b[0m")
        self._dealer.send(pkt.SerializeToString())

    def _recv(self, expected: Packet.Type | None = None, timeout: float | None = None) -> Packet | None:
        if self._stop_event.get():
            return None

        payload = self._dealer.recv(timeout=timeout)
        if payload is None:
            return

        pkt = Packet()
        pkt.ParseFromString(payload)

        if expected and pkt.type != expected:
            raise TypeError(f"expected type {expected!r} got {pkt.type!r}")

        if self.logger.isEnabledFor(logging.DEBUG):
            suppress = False
            if pkt.HasField("state_update") and pkt.state_update.what == STATE_SET_MY_TELEMETRY:
                suppress = True

            if not suppress:
                self.logger.debug(f"\x1b[32m<<--\x1b[0m recv    \x1b[32m<<\x1b[0m{pkt!r}\x1b[32m<<\x1b[0m")

        return pkt

    @abstractmethod
    def destroy(self) -> None: ...

    def _resolve_decorator(self) -> None:
        seen_id: set[int] = set()

        for name, obj in vars(type(self)).items():
            if not callable(obj):
                continue

            if dispatch := getattr(obj, "__dispatch_interest_list", []):
                dispatch: list[Interest]
                for interest in dispatch:
                    assert interest.id not in seen_id, "duplicate id detected, something's wrong with the auto id system"
                    seen_id.add(interest.id)

                    self._dispatch_routes[interest.id] = cast(DispatchHandle, getattr(self, name))
                    self._interest.append(interest)
            elif getattr(obj, "__dispatch_interest_fallback", False):
                self._dispatch_fallback = cast(DispatchHandle, getattr(self, name))
            elif getattr(obj, "_mark_thread", False):
                bound_method = getattr(self, name)

                self.logger.debug(f"extension {self._name} starting job: {name}")

                t = threading.Thread(target=bound_method, daemon=True)
                t.start()
                self._job_threads[name] = t

    def start(self, block: bool = False) -> Signal[bool]:
        self._monitor_thread_id = threading.Thread(target=self._monitor_thread, daemon=True)
        self._monitor_thread_id.start()
        self._resolve_decorator()

        self._dealer.start()
        self._push.start()

        if block:
            try:
                self._worker_thread()
            except (KeyboardInterrupt, InterruptedError):
                pass
            finally:
                self.stop()
        else:
            self._worker_thread_id = threading.Thread(target=self._worker_thread, daemon=False)
            self._worker_thread_id.start()

        return self.connected

    def stop(self) -> Signal[bool]:
        if self._stop_event:
            return self.disconnected

        self.logger.debug("stopping extension...")

        try:
            self._send(Packet(type=Packet.TYPE_DISCONNECT))
        except Exception:
            pass

        if not self._running and self.connected:
            self.logger.debug("waiting for disconnect ack")
            try:
                while pkt := self._recv(timeout=0.5):
                    if pkt.type == Packet.TYPE_DISCONNECT_ACK:
                        break
            except Empty:
                pass

            self.logger.debug("got disconnect ack")
            self.broker_connected.set(False)
            self.push_connected.set(False)
        else:
            self.logger.debug("waiting for disconnection")
            self.broker_connected.wait_false(timeout=2.0)
            self.push_connected.wait_false(timeout=2.0)

        self.logger.debug("stopping dealer")
        try:
            self._dealer.stop()
        except Exception as e:
            self.logger.debug(f"dealer close error: {e}")
        self.logger.debug("stopping push")
        try:
            self._push.stop()
        except Exception as e:
            self.logger.debug(f"push close error: {e}")

        self._stop_event.set(True)

        self.broker_connected.set(False)
        self.push_connected.set(False)

        self.logger.debug("stopping worker thread")
        if self._worker_thread_id and self._worker_thread_id.is_alive():
            self._worker_thread_id.join(timeout=2.0)
            if self._worker_thread_id.is_alive():
                self.logger.warning("main thread did not stop in time")

        self.logger.debug("stopping monitor thread")
        if self._monitor_thread_id and self._monitor_thread_id.is_alive():
            self._monitor_thread_id.join(timeout=0.5)

        self.logger.debug("terminating zmq context")
        try:
            self._context.term()
        except Exception as e:
            self.logger.debug(f"context term error: {e}")

        self.logger.debug("extension stopped")

        return self.disconnected

    def _monitor_thread(self) -> None:
        def handle(source: str, event: Event) -> None:
            if event == Event.CONNECTED:
                self.logger.debug(f" {source} connected")
                if source == "broker":
                    self._send(Packet(type=Packet.TYPE_HANDSHAKE))
                elif source == "push":
                    self.push_connected.set(True)
            elif event == Event.DISCONNECTED:
                if source == "broker":
                    self.logger.info("lost connection to broker")
                    self.broker_connected.set(False)
                if source == "push":
                    self.push_connected.set(False)

        last_heartbeat = 0

        try:
            while not self._stop_event:
                event = None
                try:
                    if event := self._dealer.recv_event(block=False, timeout=0.1):
                        handle("broker", event)
                except Empty:
                    pass

                event = None
                try:
                    if event := self._push.recv_event(block=False, timeout=0.1):
                        handle("push", event)
                except Empty:
                    pass

                now = time.time()
                if now - last_heartbeat > setting.heartbeat_interval:
                    with self.suppressed_log():
                        self._send(Packet(type=Packet.TYPE_HEARTBEAT))
                    last_heartbeat = now

                time.sleep(0.1)
        except Exception as e:
            self.logger.debug(f"monitor thread error: {e}")

    @contextmanager
    def suppressed_log(self) -> Iterator["Extension"]:
        orig = self._suppress_log
        try:
            self._suppress_log = True
            yield self
        finally:
            self._suppress_log = orig

    def forward(self, new: PendingPacket) -> PendingPacket:
        new._op = PendingPacket.OP_FORWARD
        return new

    def pass_to_next(self) -> PendingPacket:
        return PendingPacket(_op=PendingPacket.OP_PASS)

    def cancel(self) -> PendingPacket:
        return PendingPacket(_op=PendingPacket.OP_CANCEL)

    def finish(self, new: PendingPacket) -> PendingPacket:
        new._op = PendingPacket.OP_FINISH
        return new

    def _copy_meta_fields(self, dst: PendingPacket, src: PendingPacket) -> None:
        dst._packet_id = src._packet_id
        dst._hit_count = src._hit_count
        dst._rtt_ns = src._rtt_ns

    def _worker_thread(self) -> None:
        self._running = True
        try:
            while not self._stop_event.get():
                pkt = self._recv()
                if pkt is None:
                    break

                match pkt.type:
                    case Packet.TYPE_HEARTBEAT:
                        self._last_heartbeat = time.time()
                    case Packet.TYPE_PENDING_PACKET:
                        start = time.monotonic_ns()
                        response: PendingPacket | None = None

                        id = pkt.pending_packet.interest_id
                        response = None

                        if not id in self._dispatch_routes:
                            if self._dispatch_fallback:
                                try:
                                    response = self._dispatch_fallback(pkt.pending_packet)
                                except:
                                    traceback.print_exc()
                            else:
                                self.logger.warning(f"unhandled interest id: {id}, available {self._dispatch_routes.keys()}")
                        else:
                            try:
                                response = self._dispatch_routes[id](pkt.pending_packet)
                            except:
                                traceback.print_exc()

                        if not response:
                            response = self.pass_to_next()

                        self._copy_meta_fields(response, pkt.pending_packet)
                        response._hit_count += 1
                        if PERF:
                            self.logger.debug(f"extension processing time: {(time.monotonic_ns() - start) / 1e6}us")
                        self._send(Packet(type=Packet.TYPE_PENDING_PACKET, pending_packet=response))
                    case Packet.TYPE_CONNECTED:
                        self.logger.info("connected to broker")
                        self.broker_connected.set(True)
                        self._send(Packet(type=Packet.TYPE_STATE_REQUEST))
                    case Packet.TYPE_DISCONNECT | Packet.TYPE_DISCONNECT_ACK:
                        self.broker_connected.set(False)
                        self.push_connected.set(False)
                    case Packet.TYPE_HANDSHAKE_ACK:
                        pass
                    case Packet.TYPE_CAPABILITY_REQUEST:
                        self._send(
                            Packet(
                                type=Packet.TYPE_CAPABILITY_RESPONSE,
                                capability_response=CapabilityResponse(
                                    interest=self._interest,
                                ),
                            )
                        )
                    case Packet.TYPE_STATE_RESPONSE:
                        self.state = State.from_proto(pkt.state_response.state)
                        if self.state.status == Status.CONNECTED or self.state.status == Status.IN_WORLD:
                            self.console_log(f"extension {self._name.decode(errors='backslashreplace')} connected")
                            self.play_sound("audio/hit.wav")
                    case Packet.TYPE_STATE_UPDATE:
                        self.state.update(pkt.state_update)
        except zmq.error.ZMQError as e:
            if not self._stop_event.get():
                self.logger.debug(f"ZMQ error in main loop: {e}")
        finally:
            self.logger.debug("worker thread exiting")
            self._running = False

    # helper
    def standalone(self) -> None:
        """call this only in `if __name__ == '__main__'`"""
        parser = ArgumentParser()
        parser.add_argument("-v", action="store_true", help="verbose")

        args = parser.parse_args()

        level = logging.DEBUG if args.v else logging.INFO
        setup_logger(
            self._name.decode(errors="surrogateescape"),
            log_dir=setting.appdir / "logs" / "extension",
            level=level,
        )

        try:
            self.start(block=True)
        except:
            raise
