from abc import ABC, abstractmethod
import argparse
import threading
import traceback
import zmq
import logging
import time
from zmq.utils.monitor import recv_monitor_message

from gtools.protogen.extension_pb2 import (
    CapabilityResponse,
    Event,
    ForwardNotModified,
    Packet,
    Interest,
)


class ThreadEvent:
    def __init__(self) -> None:
        self._flag = False
        self._cond = threading.Condition()

    def set(self) -> None:
        with self._cond:
            self._flag = True
            self._cond.notify_all()

    def is_set(self) -> bool:
        with self._cond:
            return self._flag

    def clear(self) -> None:
        with self._cond:
            self._flag = False
            self._cond.notify_all()

    def wait(self, timeout: float | None = None) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: self._flag, timeout)

    def unwait(self, timeout=None) -> bool:
        with self._cond:
            return self._cond.wait_for(lambda: not self._flag, timeout)


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
        self._stop_event = ThreadEvent()

        self.connected = ThreadEvent()

    def _send(self, pkt: Packet) -> None:
        if self._stop_event.is_set():
            return

        self.logger.debug(f"   send \x1b[31m-->>\x1b[0m \x1b[31m>>\x1b[0m{pkt!r}\x1b[31m>>\x1b[0m")
        try:
            if self._socket.poll(100, zmq.POLLOUT):
                self._socket.send(pkt.SerializeToString(), zmq.NOBLOCK)
        except zmq.error.ZMQError as e:
            if not self._stop_event.is_set():
                self.logger.debug(f"send error: {e}")

    def _recv(self, expected: Packet.Type | None = None) -> Packet | None:
        if self._stop_event.is_set():
            return None

        try:
            events = self._socket.poll(100, zmq.POLLIN)

            if events == 0:
                return None

            data = self._socket.recv(zmq.NOBLOCK)
        except zmq.error.Again:
            return None
        except zmq.error.ZMQError as e:
            if self._stop_event.is_set():
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
    def process(self, event: Event) -> Packet | None: ...

    @abstractmethod
    def destroy(self) -> None: ...

    def start(self, block: bool = False) -> None:
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

    def stop(self) -> None:
        if self._stop_event.is_set():
            return

        self.logger.debug("stopping extension...")

        try:
            self._send(Packet(type=Packet.TYPE_DISCONNECT))
        except Exception:
            pass

        self._stop_event.set()
        # self.connected.clear()

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

    def _monitor_thread(self) -> None:
        mon = None
        try:
            mon = self._socket.get_monitor_socket()

            if not mon:
                return

            while not self._stop_event.is_set():
                try:
                    if mon.poll(100):
                        evt = recv_monitor_message(mon, zmq.NOBLOCK)
                        if evt and evt["event"] == zmq.EVENT_CONNECTED:
                            self._send(Packet(type=Packet.TYPE_HANDSHAKE))
                        elif evt["event"] in (zmq.EVENT_DISCONNECTED, zmq.EVENT_MONITOR_STOPPED):
                            self.connected.clear()
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

    def _worker_thread(self) -> None:
        try:
            while not self._stop_event.is_set():
                pkt = self._recv()

                if pkt is None:
                    if self._stop_event.is_set():
                        break

                    continue

                match pkt.type:
                    case Packet.TYPE_EVENT:
                        try:
                            response = self.process(pkt.event)
                        except:
                            traceback.print_exc()
                            response = Packet(
                                type=Packet.TYPE_FORWARD_NOT_MODIFIED,
                                forward_not_modified=ForwardNotModified(chain_id=pkt.event.chain_id),
                            )

                        if response:
                            if response.type == Packet.TYPE_FORWARD:
                                response.forward.chain_id = pkt.event.chain_id
                            elif response.type == Packet.TYPE_FORWARD_NOT_MODIFIED:
                                response.forward_not_modified.chain_id = pkt.event.chain_id
                            else:
                                raise NotImplementedError(f"response type {response.type} not handled")
                            self._send(response)
                    case Packet.TYPE_CONNECTED:
                        self.connected.set()
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
            if not self._stop_event.is_set():
                self.logger.debug(f"ZMQ error in main loop: {e}")
        finally:
            # self.connected.clear()
            self.logger.debug("worker thread exiting")


if __name__ == "__main__":
    from gtools.proxy.extension.broker import Broker
    import logging
    import time
    from gtools.proxy.extension.builtin.fast_drop import FastDropExtension
    from gtools.protogen.extension_pb2 import DIRECTION_SERVER_TO_CLIENT
    from gtools.core.growtopia.packet import NetPacket

    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", action="store_true")

    args = parser.parse_args()

    if args.broker:
        b = Broker()
        time.sleep(5)
        buf = b"\x04\x00\x00\x00\x01\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xd2\x00\x00\x00\x02\x00\x02\x0f\x00\x00\x00OnDialogRequest\x01\x02\xb6\x00\x00\x00set_default_color|`o\nadd_label_with_icon|big|`wDrop Lava``|left|4|\nadd_textbox|How many to drop?|left|\nadd_text_input|count||8|5|\nembed_data|itemID|4\nend_dialog|drop_item|Cancel|OK|\n\x00"
        pkt = NetPacket.deserialize(buf)
        b.process_event(pkt, buf, DIRECTION_SERVER_TO_CLIENT)
    else:
        FastDropExtension()
