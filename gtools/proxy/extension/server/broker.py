from bisect import insort
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
import heapq
import itertools
import logging
from queue import Queue
import random
import threading
import time
from traceback import print_exc
from typing import Any, Callable, Iterator
import zmq

from gtools.core.auto_call import auto_call
from gtools.core.growtopia.packet import NetType, PreparedPacket
from gtools.core.network import increment_port
from gtools.core.signal import Signal
from gtools.core.transport.zmq_transport import Pull, Router
from gtools.flags import BENCHMARK, PERF, TRACE
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    BlockingMode,
    CapabilityRequest,
    Packet,
    Interest,
    InterestType,
    PendingPacket,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
)
from gtools import setting
from gtools.proxy.extension.server.handler import NETPACKET_TO_INTEREST_TYPE, TANKPACKET_TO_INTEREST_TYPE, ExtensionHandler, Extension, hash_interest


class ExtensionManager:
    logger = logging.getLogger("extension_mgr")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._extensions: dict[bytes, Extension] = {}
        self._interest_map: defaultdict[InterestType, list[ExtensionHandler]] = defaultdict(list)

    def beat(self, id: bytes) -> None:
        if id not in self._extensions:
            return

        self._extensions[id].last_heartbeat = time.time()

    def sweep(self) -> None:
        to_remove: set[bytes] = set()
        for id, ext in self._extensions.items():
            if ext.last_heartbeat != 0.0 and time.time() - ext.last_heartbeat > setting.heartbeat_threshold:
                to_remove.add(id)

        for ext in to_remove:
            self.logger.info(f"extension {ext} flatline, removing...")
            self.remove_extension(ext)

    def add_extension(self, ext: Extension) -> None:
        self.logger.info(f"extension {ext.id} connected")
        with self._lock:
            if ext.id in self._extensions:
                self.logger.warning(f"extension {ext.id} already exists, overwriting")
            self._extensions[ext.id] = ext
            for interest in ext.interest:
                ent = self._interest_map[interest.interest]
                insort(ent, ExtensionHandler(ext, interest), key=lambda x: -x.interest.priority)

    def remove_extension(self, id: bytes) -> None:
        self.logger.info(f"extension {id} disconnected")
        with self._lock:
            if id not in self._extensions:
                self.logger.warning(f"extension {id} does not exists to be removed")
                return

            extension = self._extensions[id]
            for interest in extension.interest:
                ent = self._interest_map[interest.interest]
                ent.remove(ExtensionHandler(extension, interest))

            del self._extensions[id]

    def get_interested_extension_any(self, interest_type: InterestType) -> Iterator[ExtensionHandler]:
        for client in self._interest_map[interest_type]:
            yield client

    def get_interested_extension(self, interest_type: InterestType, pkt: PreparedPacket) -> Iterator[ExtensionHandler]:
        for client in self._interest_map[interest_type]:
            if client.interested(pkt):
                yield client

    def get_extension(self, id: bytes) -> Extension:
        return self._extensions[id]

    def get_all_extension(self) -> list[Extension]:
        return list(self._extensions.values())


class PacketCallback:
    def __init__(
        self,
        send_to_server: Callable[[PreparedPacket], Any] | None = None,
        send_to_client: Callable[[PreparedPacket], Any] | None = None,
        any: Callable[[PreparedPacket], Any] | None = None,
    ) -> None:
        self.send_to_server = send_to_server
        self.send_to_client = send_to_client
        self.any = any


class PendingChain:
    def __init__(self, id: bytes, chain: deque[ExtensionHandler], current: PendingPacket) -> None:
        self.id = id
        self.chain = chain
        self.processed_chain: dict[bytes, int] = {}  # ext_id: interest hash
        self.finished_event = threading.Event()
        self.current = current
        self.cancelled = False

    def __repr__(self) -> str:
        return f"PendingChain(size={len(self.chain)}, chain={self.chain}, processed={self.processed_chain}, pkt={self.current!r}), finished={self.finished_event.is_set()}"


class _PendingPacket:
    def __init__(self, callback: PacketCallback | None, current: PendingPacket) -> None:
        self.current = current
        self.callback = callback


class PacketScheduler:
    def __init__(self, out_queue: Queue[PreparedPacket | None] | Callable[[PreparedPacket | None], Any]) -> None:
        self._out_queue = out_queue

        self._heap: list[tuple[int, int, PendingPacket]] = []
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._seq = itertools.count()

        self._first_src_ts_ns: int | None = None
        self._playback_start_wall_ns: int | None = None

        self._stopped = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._cond:
            self._stopped = True
            self._cond.notify_all()

        if self._thread.is_alive():
            self._thread.join()

    def _put(self, pending: PendingPacket) -> None:
        prepared = PreparedPacket.from_pending(pending)
        if callable(self._out_queue):
            self._out_queue(prepared)
        else:
            self._out_queue.put(prepared)

    def push(self, pkt: PendingPacket) -> None:
        if pkt._rtt_ns == 0:
            self._put(pkt)
            return

        seq = next(self._seq)
        with self._cond:
            heapq.heappush(self._heap, (pkt._rtt_ns, seq, pkt))
            self._cond.notify()

    def _run(self) -> None:
        while True:
            with self._cond:
                if self._stopped:
                    break

                if not self._heap:
                    self._cond.wait()
                    continue

                send_ts_ns, _, pkt = self._heap[0]

                if self._first_src_ts_ns is None:
                    heapq.heappop(self._heap)
                    self._first_src_ts_ns = send_ts_ns
                    self._playback_start_wall_ns = time.monotonic_ns()
                    packet_to_send = pkt
                else:
                    assert self._playback_start_wall_ns is not None and self._first_src_ts_ns is not None
                    target_wall_ns = self._playback_start_wall_ns + (send_ts_ns - self._first_src_ts_ns)
                    now_ns = time.monotonic_ns()
                    wait_ns = target_wall_ns - now_ns

                    if wait_ns > 0:
                        self._cond.wait(timeout=wait_ns / 1e9)
                        continue

                    heapq.heappop(self._heap)
                    packet_to_send = pkt

            try:
                self._put(packet_to_send)
            except Exception:
                pass


@dataclass
class BrokerFunction:
    reply: Callable[[Packet], None]
    send_to: Callable[[bytes, Packet], None]
    send_to_interested: Callable[[InterestType, Packet], None]


HandleFunction = Callable[[bytes, Packet, BrokerFunction], Any]


@auto_call("stop")
class Broker:
    logger = logging.getLogger("broker")

    def __init__(self, pull_queue: Queue[PreparedPacket | None] | Callable[[PreparedPacket | None], Any] | None = None, addr: str = setting.broker_addr) -> None:
        self._suppress_log = False

        self._context = zmq.Context()
        self._router = Router(self._context, addr)

        self._extension_mgr = ExtensionManager()
        self._pending_chain: dict[bytes, PendingChain] = {}
        self._pending_packet: dict[bytes, _PendingPacket] = {}

        self._stop_event = threading.Event()
        self._worker_thread_id: threading.Thread | None = None
        self.extension_len = Signal(0)

        self._pull_queue = pull_queue
        if self._pull_queue:
            self._scheduler = PacketScheduler(self._pull_queue)
        else:
            self._scheduler = None

        pull_addr = increment_port(addr)
        self._pull = Pull(self._context, pull_addr)
        self.logger.debug(f"starting pull thread on {pull_addr}")
        self._pull_thread_id = threading.Thread(target=self._pull_thread)
        self._pull_thread_id.start()
        self._handler: dict[Packet.Type, HandleFunction] = {}
        self._monitor_thread_id = threading.Thread(target=self._monitor_thread)
        self._monitor_thread_id.start()

    def _monitor_thread(self) -> None:
        try:
            while not self._stop_event.is_set():
                self._extension_mgr.sweep()
                time.sleep(0.1)
        except Exception as e:
            self.logger.debug(f"monitor thread error: {e}")

    @contextmanager
    def suppressed_log(self) -> Iterator["Broker"]:
        orig = self._suppress_log
        try:
            self._suppress_log = True
            yield self
        finally:
            self._suppress_log = orig

    def _pull_one(self) -> bool:
        if self._stop_event.is_set():
            return False

        payload = self._pull.recv()
        if not payload:
            return False

        pkt = PendingPacket()
        pkt.ParseFromString(payload)

        if self._scheduler:
            self._scheduler.push(pkt)
        else:
            self.logger.warning(f"pull unhandled: {pkt}")

        # TODO: this thing gets in the middle of normal logging, same with push on sdk
        # if not self._suppress_log and self.logger.isEnabledFor(logging.DEBUG):
        #     pkt = PreparedPacket.from_pending(pkt)
        #     self.logger.debug(f"\x1b[34m<<--\x1b[0m pull    \x1b[34m<<\x1b[0m{pkt!r}\x1b[34m<<\x1b[0m")

        return True

    def _pull_thread(self) -> None:
        if BENCHMARK:
            _last = time.monotonic_ns()
            i = 0
            prev_i = 0
            elapsed_total = 0

            while not self._stop_event.is_set():
                if not self._pull_one():
                    break

                elapsed_total += time.monotonic_ns() - _last
                if elapsed_total >= 1e9:
                    print(f"packet rate: {i - prev_i} / s")
                    elapsed_total = 0
                    prev_i = i
                i += 1
                _last = time.monotonic_ns()
        else:
            while not self._stop_event.is_set():
                if not self._pull_one():
                    break

        self.logger.debug("pull thread exiting")

    def _recv(self) -> tuple[bytes, Packet | None]:
        if self._stop_event.is_set():
            return b"", None

        payload = self._router.recv()
        if payload is None:
            return b"", None

        id, data = payload
        pkt = Packet()
        pkt.ParseFromString(data)

        if not self._suppress_log and not pkt.type == Packet.TYPE_HEARTBEAT:
            self.logger.debug(f"\x1b[31m<<--\x1b[0m recv    \x1b[31m<<\x1b[0m{pkt!r}\x1b[31m<<\x1b[0m")

        return id, pkt

    def _send(self, extension: bytes, pkt: Packet) -> None:
        if self._stop_event.is_set():
            return

        self._router.send((extension, pkt.SerializeToString()))

    def broadcast(self, pkt: Packet) -> None:
        for ext in self._extension_mgr.get_all_extension():
            try:
                self._send(ext.id, pkt)
            except Exception as e:
                self.logger.error(f"failed to send packet to {ext.id}: {e}")
                continue

    def _get_interested_extension(self, pkt: PreparedPacket) -> Iterator[ExtensionHandler]:
        interest_type = NETPACKET_TO_INTEREST_TYPE[pkt.as_net.type]

        # match any subpacket of INTEREST_TANK_PACKET such as INTEREST_STATE
        tank_specific: list[ExtensionHandler] = []
        if pkt.as_net.type == NetType.TANK_PACKET:
            tank_specific.extend(
                self._extension_mgr.get_interested_extension(
                    TANKPACKET_TO_INTEREST_TYPE[pkt.as_net.tank.type],
                    pkt,
                )
            )

        for client in itertools.chain(
            self._extension_mgr.get_interested_extension(interest_type, pkt),
            tank_specific,
        ):
            yield client

    def _build_chain(
        self,
        pkt: PreparedPacket,
        out: deque[ExtensionHandler],
        pred: Callable[[Extension, Interest], bool] | None = None,
    ) -> None:
        for client in self._get_interested_extension(pkt):
            if client.interest.blocking_mode == BLOCKING_MODE_BLOCK:
                if pred and pred(client.ext, client.interest):
                    if TRACE:
                        print(f"\t\tinterested for {pkt}:\n\t{client.ext.id}\n\t{repr(client.interest).replace('\n', '\n\t')}")
                    out.append(client)

    def process_event(self, pkt: PreparedPacket, callback: PacketCallback | None = None) -> tuple[PendingPacket, bool] | None:
        """returns the (processed packet, cancelled) or None
        None can mean there is no extension, no extension matched,
        or the blocking mode is non-blocking or expects no reply
        """
        start = time.monotonic_ns()
        chain: deque[ExtensionHandler] = deque()
        for client in self._get_interested_extension(pkt):
            if TRACE:
                print(f"\t\tMATCHING CLIENT (MODE={BlockingMode.Name(client.interest.blocking_mode)}) FOR {pkt}: {client}")

            match client.interest.blocking_mode:
                case BlockingMode.BLOCKING_MODE_BLOCK:
                    chain.append(client)
                case BlockingMode.BLOCKING_MODE_SEND_AND_FORGET:
                    pkt_id = random.randbytes(16)
                    pending_pkt = PendingPacket(
                        _op=PendingPacket.OP_FORWARD,
                        _packet_id=pkt_id,
                        buf=pkt.as_raw,
                        direction=pkt.direction,
                        packet_flags=pkt.flags,
                        _rtt_ns=time.monotonic_ns(),
                        interest_id=client.interest.id,
                    )
                    self._send(
                        client.ext.id,
                        Packet(type=Packet.TYPE_PENDING_PACKET, pending_packet=pending_pkt),
                    )
                    self._pending_packet[pkt_id] = _PendingPacket(
                        callback,
                        pending_pkt,
                    )
                    if not callback:
                        self.logger.warning(f"no callback defined for {pkt}")
                case BlockingMode.BLOCKING_MODE_SEND_AND_CANCEL:
                    pkt_id = random.randbytes(16)
                    pending_pkt = PendingPacket(
                        _op=PendingPacket.OP_FORWARD,
                        _packet_id=pkt_id,
                        buf=pkt.as_raw,
                        direction=pkt.direction,
                        packet_flags=pkt.flags,
                        _rtt_ns=time.monotonic_ns(),
                        interest_id=client.interest.id,
                    )
                    self._send(
                        client.ext.id,
                        Packet(type=Packet.TYPE_PENDING_PACKET, pending_packet=pending_pkt),
                    )
                    self._pending_packet[pkt_id] = _PendingPacket(
                        callback,
                        pending_pkt,
                    )
                    if not callback:
                        self.logger.warning(f"no callback defined for {pkt}")

                    # since we dont use the packet if cancelled is true, this should be safe
                    return PendingPacket(), True
                case BlockingMode.BLOCKING_MODE_ONESHOT:
                    pending_pkt = PendingPacket(
                        _op=PendingPacket.OP_FORWARD,
                        _packet_id=None,
                        buf=pkt.as_raw,
                        direction=pkt.direction,
                        packet_flags=pkt.flags,
                        interest_id=client.interest.id,
                    )
                    self._send(
                        client.ext.id,
                        Packet(type=Packet.TYPE_PENDING_PACKET, pending_packet=pending_pkt),
                    )
                case BlockingMode.BLOCKING_MODE_ONESHOT_AND_CANCEL:
                    pending_pkt = PendingPacket(
                        _op=PendingPacket.OP_FORWARD,
                        _packet_id=None,
                        buf=pkt.as_raw,
                        direction=pkt.direction,
                        packet_flags=pkt.flags,
                        interest_id=client.interest.id,
                    )
                    self._send(
                        client.ext.id,
                        Packet(type=Packet.TYPE_PENDING_PACKET, pending_packet=pending_pkt),
                    )
                    return PendingPacket(), True

        if TRACE:
            print(
                f"\t\tSTATE PROCESS_EVENT NOBLOCK (ext={len(self._extension_mgr._extensions)}, pending_chain={len(self._pending_chain)}, pending_packet={len(self._pending_packet)}):\n"
                f"\tchain={self._pending_chain}\n",
                f"\tpacket={self._pending_packet}\n",
            )

        if chain:
            chain_id = random.randbytes(16)
            pending_pkt = PendingPacket(
                _op=PendingPacket.OP_FORWARD,
                _packet_id=chain_id,
                buf=pkt.as_raw,
                direction=pkt.direction,
                packet_flags=pkt.flags,
                _rtt_ns=time.monotonic_ns(),
                interest_id=chain[0].interest.id,
            )

            pending = PendingChain(chain_id, chain, pending_pkt)
            pending.processed_chain[chain[0].ext.id] = hash_interest(chain[0].interest)
            self._pending_chain[chain_id] = pending
            self._send(
                chain[0].ext.id,
                Packet(type=Packet.TYPE_PENDING_PACKET, pending_packet=pending_pkt),
            )

            if TRACE:
                print(
                    f"\t\tSTATE PROCESS_EVENT BLOCK (ext={len(self._extension_mgr._extensions)}, pending_chain={len(self._pending_chain)}, pending_packet={len(self._pending_packet)}):\n"
                    f"\tchain={self._pending_chain}\n",
                    f"\tpacket={self._pending_packet}\n",
                )

            if PERF:
                self.logger.debug(f"broker processing: {(time.monotonic_ns() - start) / 1e6}us")
            self._pending_chain[chain_id].finished_event.wait()
            finished = self._pending_chain.pop(chain_id)
            finished.current._rtt_ns = time.monotonic_ns() - finished.current._rtt_ns
            return finished.current, finished.cancelled

    # this version of process_event doesn't work with prepared packet, but with arbitrary packet, thus
    # it can only send block and doesn't chain
    def process_event_any(self, interest: InterestType, pkt: Packet) -> None:
        for client in self._extension_mgr.get_interested_extension_any(interest):
            self._send(client.ext.id, pkt)

    def start(self, block: bool = False) -> None:
        self._router.start(block=False)
        self._pull.start(block=False)
        if block:
            self._worker_thread()
        else:
            self._worker_thread_id = threading.Thread(target=lambda: self._worker_thread())
            self._worker_thread_id.start()

    def stop(self) -> None:
        if self._stop_event.is_set():
            return

        self.logger.debug("stopping extension...")

        self.broadcast(Packet(type=Packet.TYPE_DISCONNECT))
        self._stop_event.set()

        try:
            self.logger.debug("stopping router")
            self._router.stop()
        except Exception as e:
            self.logger.debug(f"router error: {e}")

        try:
            self.logger.debug("stopping pull")
            self._pull.stop()
        except Exception as e:
            self.logger.debug(f"pull error: {e}")

        if self._scheduler:
            self.logger.debug(f"stopping packet scheduler")
            self._scheduler.stop()

        if self._worker_thread_id and self._worker_thread_id.is_alive():
            self._worker_thread_id.join(timeout=2.0)
            self.logger.debug("worker thread exited")

        try:
            self.logger.debug("closing zmq context")
            self._context.destroy(linger=0)
        except Exception as e:
            self.logger.debug(f"context term error: {e}")

        if self._pull_thread_id and self._pull_thread_id.is_alive():
            self._pull_thread_id.join(timeout=2.0)
            self.logger.debug("pull thread exited")

        if self._monitor_thread_id and self._monitor_thread_id.is_alive():
            self._monitor_thread_id.join(timeout=2.0)
            self.logger.debug("monitor thread exited")

        self.logger.debug("broker has stopped")

    def _forward(self, chain: PendingChain, new_packet: PendingPacket) -> None:
        chain.current = new_packet
        chain.chain.clear()
        self._build_chain(
            PreparedPacket.from_pending(new_packet),
            chain.chain,
            pred=lambda ext, interest: not bool(chain and (ext.id in chain.processed_chain and chain.processed_chain[ext.id] == hash_interest(interest))),
        )
        if len(chain.chain) == 0:
            chain.finished_event.set()
        else:
            next_client = chain.chain.popleft()
            new_packet.interest_id = next_client.interest.id
            chain.processed_chain[next_client.ext.id] = hash_interest(next_client.interest)
            self._send(
                next_client.ext.id,
                Packet(
                    type=Packet.TYPE_PENDING_PACKET,
                    pending_packet=new_packet,
                ),
            )

    def _finish(self, pending: _PendingPacket, new_packet: PendingPacket) -> None:
        if not pending.callback:
            return

        pending.current = new_packet
        if pending.current.direction == DIRECTION_CLIENT_TO_SERVER and pending.callback.send_to_server:
            pending.callback.send_to_server(PreparedPacket.from_pending(pending.current))
        elif pending.current.direction == DIRECTION_SERVER_TO_CLIENT and pending.callback.send_to_client:
            pending.callback.send_to_client(PreparedPacket.from_pending(pending.current))
        else:
            self.logger.warning(f"packet direction is unspecified: {pending}")

        if pending.callback.any:
            pending.callback.any(PreparedPacket.from_pending(pending.current))

    # TODO: don't have these if TRACE, create utils

    def _handle_packet(self, pkt: PendingPacket) -> None:
        assert pkt._packet_id, "invalid packet id"
        if (chain := self._pending_chain.get(pkt._packet_id)) is not None:
            if TRACE:
                print(f"\t\t\tPACKET {PendingPacket.Op.Name(pkt._op)} IS {chain.current}")
            match pkt._op:
                case PendingPacket.OP_FINISH:
                    chain.current = pkt
                    chain.finished_event.set()
                case PendingPacket.OP_CANCEL:
                    chain.current._hit_count = pkt._hit_count
                    chain.cancelled = True
                    chain.finished_event.set()
                case PendingPacket.OP_FORWARD:
                    self._forward(chain, pkt)
                case PendingPacket.OP_PASS:
                    chain.current._hit_count = pkt._hit_count
                    self._forward(chain, chain.current)
                    pass
                case _:
                    raise ValueError(f"invalid op: {pkt._op}")
        elif (pending := self._pending_packet.pop(pkt._packet_id, None)) is not None:
            if TRACE:
                print(f"\t\t\tPACKET {PendingPacket.Op.Name(pkt._op)} IS {pending.current}")
            match pkt._op:
                case PendingPacket.OP_FINISH:
                    self._finish(pending, pkt)
                case PendingPacket.OP_CANCEL:
                    pass
                case PendingPacket.OP_FORWARD:
                    self._finish(pending, pkt)
                case PendingPacket.OP_PASS:
                    pass
                case _:
                    raise ValueError(f"invalid op: {pkt._op}")
        else:
            raise ValueError(f"packet is not in any pending state: {pkt}")

    def _worker_thread(self) -> None:
        try:
            while not self._stop_event.is_set():
                id, pkt = self._recv()
                if pkt is None:
                    break

                match pkt.type:
                    case Packet.TYPE_HEARTBEAT:
                        self._extension_mgr.beat(id)
                    case Packet.TYPE_PUSH_PACKET:
                        if self._scheduler:
                            self._scheduler.push(pkt.push_packet)
                    case Packet.TYPE_HANDSHAKE:
                        self._send(id, Packet(type=Packet.TYPE_HANDSHAKE_ACK))
                        self._send(id, Packet(type=Packet.TYPE_CAPABILITY_REQUEST, capability_request=CapabilityRequest()))
                    case Packet.TYPE_CAPABILITY_RESPONSE:
                        self._extension_mgr.add_extension(
                            Extension(
                                id=id,
                                interest=list(pkt.capability_response.interest),
                            ),
                        )
                        self._send(id, Packet(type=Packet.TYPE_CONNECTED))
                        self.extension_len.update(lambda x: x + 1)
                    case Packet.TYPE_DISCONNECT:
                        self._extension_mgr.remove_extension(id)
                        self.extension_len.update(lambda x: x - 1)
                        self._send(id, Packet(type=Packet.TYPE_DISCONNECT_ACK))
                    case Packet.TYPE_PENDING_PACKET:
                        if TRACE:
                            print(f"\t\trecv from {id}: {pkt}")
                            print(
                                f"\t\tSTATE (ext={len(self._extension_mgr._extensions)}, pending_chain={len(self._pending_chain)}, pending_packet={len(self._pending_packet)}):\n"
                                f"\tchain={self._pending_chain}\n",
                                f"\tpacket={self._pending_packet}\n",
                            )
                        self._handle_packet(pkt.pending_packet)
                    case _:
                        if handler := self._handler.get(pkt.type):
                            if TRACE:
                                print(f"\t\t{Packet.Type.Name(pkt.type)} handled by external handler")

                            try:
                                handler(
                                    id,
                                    pkt,
                                    BrokerFunction(
                                        lambda pkt, id=id: self._send(id, pkt),
                                        self._send,
                                        self.process_event_any,
                                    ),
                                )
                            except Exception as e:
                                self.logger.error(f"error in handler: {e}")
                                print_exc()
        except (KeyboardInterrupt, InterruptedError):
            pass
        except zmq.error.ZMQError as e:
            if not self._stop_event.is_set():
                self.logger.debug(f"ZMQ error in main loop: {e}")
        finally:
            self.logger.debug("worker thread exiting")

    def set_handler(self, type: Packet.Type, handler: HandleFunction) -> None:
        self._handler[type] = handler
