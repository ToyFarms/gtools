import logging
from queue import Empty, Queue
import threading
import zmq
import zmq.utils.monitor
from abc import ABC, abstractmethod

from gtools.core.transport.protocol import Transport


class _ZmqTransport[Send, Recv](ABC, Transport[Send, Recv]):
    def __init__(self, context: zmq.Context[zmq.SyncSocket], addr: str, socket_type: int, logger_name: str) -> None:
        self._addr = addr
        self._socket = context.socket(socket_type)
        self._socket.setsockopt(zmq.LINGER, 0)

        self._monitor_socket = None

        self._poller = zmq.Poller()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._inbound = Queue[Recv | None]()
        self._outbound = Queue[Send]()
        self._events = Queue[zmq.utils.monitor._MonitorMessage]()

        self.logger = logging.getLogger(logger_name)

    @abstractmethod
    def _setup_socket(self) -> None: ...
    @abstractmethod
    def _recv_message(self) -> Recv: ...
    @abstractmethod
    def _send_message(self, payload: Send) -> None: ...
    @abstractmethod
    def _get_poll_flags(self) -> int: ...
    @abstractmethod
    def _get_poll_timeout(self) -> int: ...

    def start(self, block: bool = False) -> None:
        self._setup_socket()
        assert self._socket

        self._monitor_socket = self._socket.get_monitor_socket()

        self._poller.register(self._socket, self._get_poll_flags())
        self._poller.register(self._monitor_socket, zmq.POLLIN)

        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        if block:
            self._poller_thread()
        else:
            self._thread = threading.Thread(target=self._poller_thread, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

        self._cleanup()

    def send(self, payload: Send) -> None:
        self._outbound.put(payload)

    def recv(self, block: bool = True, timeout: float | None = None) -> Recv | None:
        return self._inbound.get(block=block, timeout=timeout)

    def recv_event(self, block: bool = True, timeout: float | None = None) -> zmq.utils.monitor._MonitorMessage:
        return self._events.get(block=block, timeout=timeout)

    def _poller_thread(self) -> None:
        assert self._socket

        try:
            while not self._stop_event.is_set():
                try:
                    socks = dict(self._poller.poll(self._get_poll_timeout()))
                except zmq.ZMQError as e:
                    self.logger.exception(f"poller error: {e}")
                    break

                if self._monitor_socket and socks.get(self._monitor_socket, 0) & zmq.POLLIN:
                    try:
                        evt = self._monitor_socket.recv_multipart(flags=zmq.NOBLOCK)
                        event = zmq.utils.monitor.parse_monitor_message(evt)
                        self._events.put(event)
                    except zmq.ZMQError as e:
                        self.logger.warning("monitor recv failed: %s", e)

                if socks.get(self._socket, 0) & zmq.POLLIN:
                    try:
                        msg = self._recv_message()
                    except zmq.ZMQError as e:
                        self.logger.warning("recv_multipart failed: %s", e)
                        break

                    self._inbound.put(msg)

                while True:
                    try:
                        msg = self._outbound.get_nowait()
                    except Empty:
                        break

                    try:
                        self._send_message(msg)
                    except zmq.Again:
                        try:
                            self._outbound.put(msg)
                        except Exception:
                            self.logger.exception("failed to re-queue frames after EAGAIN")
                        break
                    except zmq.ZMQError as e:
                        self.logger.warning("dropped outbound frames: %s -> %r", e, msg)
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        self._inbound.put(None)
        if self._monitor_socket:
            try:
                self._poller.unregister(self._monitor_socket)
            except Exception:
                pass
            try:
                self._monitor_socket.close()
            except Exception:
                pass
            finally:
                self._monitor_socket = None
        if self._socket:
            try:
                self._poller.unregister(self._socket)
            except Exception:
                pass
            try:
                self._socket.close()
            except Exception:
                self.logger.exception("error closing dealer socket")
            finally:
                self._socket = None


type RouterSend = tuple[bytes, bytes]
type RouterRecv = tuple[bytes, bytes]


class Router(_ZmqTransport[RouterSend, RouterRecv]):
    def __init__(self, context: zmq.Context[zmq.SyncSocket], addr: str) -> None:
        _ZmqTransport.__init__(self, context, addr, zmq.ROUTER, "router")

    def _setup_socket(self) -> None:
        assert self._socket
        self._socket.bind(self._addr)

    def _recv_message(self) -> RouterRecv:
        assert self._socket
        frames = self._socket.recv_multipart(flags=zmq.NOBLOCK)
        return (frames[0], frames[1])

    def _send_message(self, payload: RouterSend) -> None:
        assert self._socket
        self._socket.send_multipart(payload, flags=zmq.NOBLOCK)

    def _get_poll_flags(self) -> int:
        return zmq.POLLIN | zmq.POLLOUT

    def _get_poll_timeout(self) -> int:
        return 10


type DealerSend = bytes
type DealerRecv = bytes


class Dealer(_ZmqTransport[DealerSend, DealerRecv]):
    def __init__(self, context: zmq.Context[zmq.SyncSocket], id: bytes, addr: str) -> None:
        self.id = id
        _ZmqTransport.__init__(self, context, addr, zmq.DEALER, "dealer")

    def _setup_socket(self) -> None:
        assert self._socket
        self._socket.setsockopt(zmq.IDENTITY, self.id)
        self._socket.connect(self._addr)

    def _recv_message(self) -> DealerRecv:
        assert self._socket
        return self._socket.recv(zmq.NOBLOCK)

    def _send_message(self, payload: DealerSend) -> None:
        assert self._socket
        self._socket.send(payload, flags=zmq.NOBLOCK)

    def _get_poll_flags(self) -> int:
        return zmq.POLLIN

    def _get_poll_timeout(self) -> int:
        return 10
