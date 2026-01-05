from collections import deque
import logging
from queue import Empty
import threading
import zmq
import zmq.utils.monitor
from abc import ABC, abstractmethod
import time

from gtools.core.transport.protocol import Event, Transport


class _ZmqTransport[Send, Recv](ABC, Transport[Send, Recv]):
    def __init__(self, context: zmq.Context[zmq.SyncSocket], addr: str, socket_type: int, logger_name: str) -> None:
        self._addr = addr
        self._socket = context.socket(socket_type)
        self._socket.setsockopt(zmq.LINGER, 0)

        self._socket.setsockopt(zmq.SNDHWM, 10000)
        self._socket.setsockopt(zmq.RCVHWM, 10000)
        self._socket.setsockopt(zmq.SNDBUF, 2097152)
        self._socket.setsockopt(zmq.RCVBUF, 2097152)

        self._monitor_socket = None
        self._poller = zmq.Poller()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._inbound = deque[Recv | None]()
        self._outbound = deque[Send]()
        self._events = deque[Event]()

        self._queue_lock = threading.Lock()
        self._queue_cond = threading.Condition(self._queue_lock)

        self._inbound_max = 10000
        self._outbound_max = 10000
        self._events_max = 1000

        self.logger = logging.getLogger(logger_name)

    @abstractmethod
    def _setup_socket(self) -> None: ...
    @abstractmethod
    def _recv_message(self) -> Recv: ...
    @abstractmethod
    def _send_message(self, payload: Send) -> None: ...
    @abstractmethod
    def _get_poll_flags(self) -> int: ...

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
        with self._queue_cond:
            self._queue_cond.notify_all()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._cleanup()

    def send(self, payload: Send, block: bool = True) -> None:
        with self._queue_cond:
            if len(self._outbound) < self._outbound_max:
                self._outbound.append(payload)
                self._queue_cond.notify()
            else:
                if not block:
                    self.logger.warning("outbound queue full, dropping message")
                    return
                while len(self._outbound) >= self._outbound_max:
                    self._queue_cond.wait()
                self._outbound.append(payload)
                self._queue_cond.notify()

    def send_nowait(self, payload: Send) -> None:
        self.send(payload, block=False)

    def recv(self, block: bool = True, timeout: float | None = None) -> Recv | None:
        with self._queue_cond:
            if not block:
                if not self._inbound:
                    raise Empty()
                return self._inbound.popleft()
            else:
                if timeout is None:
                    while not self._inbound:
                        self._queue_cond.wait()
                    return self._inbound.popleft()
                else:

                    end_time = time.perf_counter() + timeout
                    while not self._inbound:
                        remaining = end_time - time.perf_counter()
                        if remaining <= 0:
                            raise Empty()
                        self._queue_cond.wait(timeout=remaining)
                    return self._inbound.popleft()

    def recv_nowait(self) -> Recv | None:
        return self.recv(block=False)

    def _map_event(self, msg: zmq.utils.monitor._MonitorMessage) -> Event:
        if msg["event"] == zmq.EVENT_CONNECTED:
            return Event.CONNECTED
        elif msg["event"] in (
            zmq.EVENT_DISCONNECTED,
            zmq.EVENT_MONITOR_STOPPED,
            zmq.EVENT_CLOSED,
            zmq.EVENT_ACCEPT_FAILED,
            zmq.EVENT_HANDSHAKE_FAILED_NO_DETAIL,
            zmq.EVENT_CONNECT_RETRIED,
        ):
            return Event.DISCONNECTED
        else:
            return Event.NONE

    def recv_event(self, block: bool = True, timeout: float | None = None) -> Event:
        with self._queue_cond:
            if not block:
                if not self._events:
                    raise Empty()
                return self._events.popleft()
            else:
                end_time = None if timeout is None else time.perf_counter() + timeout
                while not self._events:
                    if end_time is None:
                        self._queue_cond.wait()
                    else:
                        remaining = end_time - time.perf_counter()
                        if remaining <= 0:
                            raise Empty()
                        self._queue_cond.wait(timeout=remaining)
                return self._events.popleft()

    def recv_event_nowait(self) -> Event:
        return self.recv_event(block=False)

    def _poller_thread(self) -> None:
        assert self._socket

        MAX_RECV_BATCH = 100
        MAX_SEND_BATCH = 100
        POLL_TIMEOUT_MS = 1

        try:
            while not self._stop_event.is_set():
                with self._queue_cond:
                    has_outbound = bool(self._outbound)

                timeout = 0 if has_outbound else POLL_TIMEOUT_MS

                try:
                    socks = dict(self._poller.poll(timeout))
                except zmq.ZMQError as e:
                    self.logger.exception(f"poller error: {e}")
                    break

                activity = False

                if self._monitor_socket and socks.get(self._monitor_socket, 0) & zmq.POLLIN:
                    try:
                        evt = self._monitor_socket.recv_multipart(flags=zmq.NOBLOCK)
                        event = zmq.utils.monitor.parse_monitor_message(evt)
                        with self._queue_cond:
                            if len(self._events) < self._events_max:
                                self._events.append(self._map_event(event))
                                self._queue_cond.notify_all()
                    except zmq.Again:
                        pass
                    except zmq.ZMQError:
                        pass

                if socks.get(self._socket, 0) & zmq.POLLIN:
                    recv_count = 0
                    while recv_count < MAX_RECV_BATCH:
                        try:
                            msg = self._recv_message()
                            with self._queue_cond:
                                if len(self._inbound) < self._inbound_max:
                                    self._inbound.append(msg)
                                    self._queue_cond.notify_all()
                                else:
                                    self.logger.warning("inbound queue full, dropping message")
                            recv_count += 1
                            activity = True
                        except zmq.Again:
                            break
                        except zmq.ZMQError as e:
                            self.logger.warning("recv failed: %s", e)
                            break

                if socks.get(self._socket, 0) & zmq.POLLOUT:
                    send_count = 0
                    while send_count < MAX_SEND_BATCH:
                        with self._queue_cond:
                            if not self._outbound:
                                break
                            msg = self._outbound.popleft()
                            self._queue_cond.notify_all()
                        try:
                            self._send_message(msg)
                            send_count += 1
                            activity = True
                        except zmq.Again:
                            with self._queue_cond:
                                self._outbound.appendleft(msg)
                                self._queue_cond.notify_all()
                            break
                        except zmq.ZMQError as e:
                            self.logger.warning(f"send failed: {e}")
                            break

                if not activity:
                    with self._queue_cond:
                        if self._outbound:
                            continue
                        self._queue_cond.wait(timeout=POLL_TIMEOUT_MS / 1000.0)

        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        with self._queue_cond:
            self._inbound.append(None)
            self._queue_cond.notify_all()

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
                self.logger.exception(f"error closing {self.__class__.__name__} socket")
            finally:
                self._socket = None


type RouterSend = tuple[bytes, bytes]
type RouterRecv = tuple[bytes, bytes]


class Router(_ZmqTransport[RouterSend, RouterRecv]):
    def __init__(self, context: zmq.Context[zmq.SyncSocket], addr: str) -> None:
        super().__init__(context, addr, zmq.ROUTER, "router")

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


type DealerSend = bytes
type DealerRecv = bytes


class Dealer(_ZmqTransport[DealerSend, DealerRecv]):
    def __init__(self, context: zmq.Context[zmq.SyncSocket], id: bytes, addr: str) -> None:
        self.id = id
        super().__init__(context, addr, zmq.DEALER, "dealer")

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
        return zmq.POLLIN | zmq.POLLOUT


type PushSend = bytes
type PushRecv = bytes


class Push(_ZmqTransport[PushSend, PushRecv]):
    def __init__(self, context: zmq.Context[zmq.SyncSocket], addr: str) -> None:
        super().__init__(context, addr, zmq.PUSH, "push")

    def _setup_socket(self) -> None:
        assert self._socket
        self._socket.connect(self._addr)

    def _recv_message(self) -> PushRecv:
        raise Exception("push socket cannot ever recv")

    def _send_message(self, payload: PushSend) -> None:
        assert self._socket
        self._socket.send(payload, flags=zmq.NOBLOCK)

    def _get_poll_flags(self) -> int:
        return zmq.POLLOUT


type PullSend = bytes
type PullRecv = bytes


class Pull(_ZmqTransport[PullSend, PullRecv]):
    def __init__(self, context: zmq.Context[zmq.SyncSocket], addr: str) -> None:
        super().__init__(context, addr, zmq.PULL, "pull")

    def _setup_socket(self) -> None:
        assert self._socket
        self._socket.bind(self._addr)

    def _recv_message(self) -> PullRecv:
        assert self._socket
        return self._socket.recv(zmq.NOBLOCK)

    def _send_message(self) -> PushRecv:
        raise Exception("pull socket cannot ever send")

    def _get_poll_flags(self) -> int:
        return zmq.POLLIN
