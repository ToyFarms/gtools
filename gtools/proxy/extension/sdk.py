from abc import ABC, abstractmethod
import threading
import traceback
import zmq
import logging
import time
from zmq.utils.monitor import recv_monitor_message

from gtools.flags import PERF
from gtools.protogen.extension_pb2 import (
    DIRECTION_UNSPECIFIED,
    CapabilityResponse,
    Direction,
    Packet,
    Interest,
    PendingPacket,
)
from gtools.proxy.extension.common import Waitable
from thirdparty.enet.bindings import ENetPacketFlag


class Extension(ABC):
    logger = logging.getLogger("extension")

    def __init__(self, name: str, interest: list[Interest], broker_addr: str = "tcp://127.0.0.1:6712") -> None:
        self._name = name.encode()
        self._interest = interest
        self._broker_addr = broker_addr

        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.DEALER)
        self._socket.setsockopt(zmq.IDENTITY, self._name)
        self._socket.setsockopt(zmq.LINGER, 0)

        self._worker_thread_id: threading.Thread | None = None
        self._monitor_thread_id: threading.Thread | None = None

        self._stop_event: Waitable[bool] = Waitable(False)
        self.connected: Waitable[bool] = Waitable(False)

    def _send(self, pkt: Packet) -> None:
        if self._stop_event.get():
            return

        self.logger.debug(f"   send \x1b[31m-->>\x1b[0m \x1b[31m>>\x1b[0m{pkt!r}\x1b[31m>>\x1b[0m")
        try:
            if self._socket.poll(100, zmq.POLLOUT):
                self._socket.send(pkt.SerializeToString(), zmq.NOBLOCK)
        except zmq.error.ZMQError as e:
            if not self._stop_event.get():
                self.logger.debug(f"send error: {e}")

    def _recv(self, expected: Packet.Type | None = None) -> Packet | None:
        if self._stop_event.get():
            return None

        try:
            events = self._socket.poll(100, zmq.POLLIN)

            if events == 0:
                return None

            data = self._socket.recv(zmq.NOBLOCK)
        except zmq.error.Again:
            return None
        except zmq.error.ZMQError as e:
            if self._stop_event.get():
                return None
            self.logger.debug(f"recv error: {e}")
            return None

        pkt = Packet()
        pkt.ParseFromString(data)

        if expected and pkt.type != expected:
            raise TypeError(f"expected type {expected!r} got {pkt.type!r}")

        self.logger.debug(f"\x1b[32m<<--\x1b[0m recv    \x1b[32m<<\x1b[0m{pkt!r}\x1b[32m<<\x1b[0m")

        return pkt

    def _connect(self) -> None:
        self._socket.connect(self._broker_addr)

    # TODO: the extension should be able to send more than one packet in one process
    @abstractmethod
    def process(self, event: PendingPacket) -> PendingPacket | None: ...

    @abstractmethod
    def destroy(self) -> None: ...

    def start(self, block: bool = False) -> Waitable[bool]:
        self._monitor_thread_id = threading.Thread(target=self._monitor_thread, daemon=True)
        self._monitor_thread_id.start()

        self._connect()

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

    def stop(self) -> Waitable[bool]:
        if self._stop_event.get():
            return self.connected

        self.logger.debug("stopping extension...")

        try:
            self._send(Packet(type=Packet.TYPE_DISCONNECT))
        except Exception:
            pass

        self._stop_event.set(True)

        try:
            self._socket.close()
        except Exception as e:
            self.logger.debug(f"socket close error: {e}")

        if self._worker_thread_id and self._worker_thread_id.is_alive():
            self._worker_thread_id.join(timeout=2.0)
            if self._worker_thread_id.is_alive():
                self.logger.warning("main thread did not stop in time")

        if self._monitor_thread_id and self._monitor_thread_id.is_alive():
            self._monitor_thread_id.join(timeout=0.5)

        try:
            self._context.term()
        except Exception as e:
            self.logger.debug(f"context term error: {e}")

        self.logger.debug("extension stopped")

        return self.connected

    def _monitor_thread(self) -> None:
        mon = None
        try:
            mon = self._socket.get_monitor_socket()

            if not mon:
                return

            while not self._stop_event.get():
                try:
                    if mon.poll(100):
                        evt = recv_monitor_message(mon, zmq.NOBLOCK)
                        if evt and evt["event"] == zmq.EVENT_CONNECTED:
                            self._send(Packet(type=Packet.TYPE_HANDSHAKE))
                        elif evt["event"] in (zmq.EVENT_DISCONNECTED, zmq.EVENT_MONITOR_STOPPED):
                            self.connected.set(False)
                except zmq.error.Again:
                    continue
                except zmq.error.ZMQError:
                    break
        except Exception as e:
            self.logger.debug(f"monitor thread error: {e}")
        finally:
            if mon:
                try:
                    mon.close()
                except:
                    pass

    def forward(self, buf: bytes, direction: Direction = DIRECTION_UNSPECIFIED, flags: ENetPacketFlag = ENetPacketFlag.NONE) -> PendingPacket:
        return PendingPacket(
            op=PendingPacket.OP_FORWARD,
            buf=buf,
            direction=direction,
            packet_flags=int(flags),
        )

    def pass_to_next(self) -> PendingPacket:
        return PendingPacket(op=PendingPacket.OP_PASS)

    def cancel(self) -> PendingPacket:
        return PendingPacket(op=PendingPacket.OP_CANCEL)

    def finish(self) -> PendingPacket:
        return PendingPacket(op=PendingPacket.OP_FINISH)

    def _worker_thread(self) -> None:
        try:
            while not self._stop_event.get():
                pkt = self._recv()

                if pkt is None:
                    if self._stop_event.get():
                        break

                    continue

                match pkt.type:
                    case Packet.TYPE_PENDING_PACKET:
                        start = time.perf_counter_ns()
                        response: PendingPacket | None = None

                        try:
                            response = self.process(pkt.pending_packet)
                        except:
                            traceback.print_exc()

                        if not response:
                            response = self.pass_to_next()

                        response.packet_id = pkt.pending_packet.packet_id
                        if response.direction == DIRECTION_UNSPECIFIED:
                            response.direction = pkt.pending_packet.direction
                        if response.packet_flags == ENetPacketFlag.NONE:
                            response.packet_flags = pkt.pending_packet.packet_flags
                        response.rtt_ns = pkt.pending_packet.rtt_ns
                        response.hit_count = pkt.pending_packet.hit_count + 1
                        if PERF:
                            self.logger.debug(f"extension processing time: {(time.perf_counter_ns() - start) / 1e6}us")
                        self._send(Packet(type=Packet.TYPE_PENDING_PACKET, pending_packet=response))
                    case Packet.TYPE_CONNECTED:
                        self.connected.set(True)
                    case Packet.TYPE_DISCONNECT:
                        pass
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
        except zmq.error.ZMQError as e:
            if not self._stop_event.get():
                self.logger.debug(f"ZMQ error in main loop: {e}")
        finally:
            self.logger.debug("worker thread exiting")

