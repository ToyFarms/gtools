from abc import ABC, abstractmethod
from argparse import ArgumentParser
from dataclasses import dataclass
from urllib.parse import urlparse
import os
import threading
import traceback
from pyglm.glm import ivec2, vec2
from google.protobuf.any_pb2 import Any
from typing import Any as TAny
import zmq
import logging
import time
from zmq.utils.monitor import recv_monitor_message

from gtools.core.growtopia.create import console_message, particle
from gtools.core.growtopia.packet import PreparedPacket
from gtools.core.log import setup_logger
from gtools.core.signal import Signal
from gtools.flags import PERF
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    INTEREST_GENERIC_TEXT,
    CapabilityResponse,
    InterestGenericText,
    Packet,
    Interest,
    PendingPacket,
)
from gtools.protogen.op_pb2 import OP_EQ, OP_STARTSWITH, BinOp, Op
from gtools.protogen.state_pb2 import STATE_SET_MY_TELEMETRY
from gtools.protogen.strkv_pb2 import Clause, FindCol, FindRow, Query
from gtools.protogen.tank_pb2 import Field, FieldValue
from gtools.proxy.state import State, Status
from gtools.proxy.setting import _setting
from thirdparty.enet.bindings import ENetPacketFlag


@dataclass
class SocketStatus:
    name: str
    connected: Signal[bool]


class Extension(ABC):
    logger = logging.getLogger("extension")

    def __init__(self, name: str, interest: list[Interest], broker_addr: str | None = None) -> None:
        self._name = name.encode()
        self._interest = interest
        self._broker_addr = broker_addr if broker_addr else f"tcp://127.0.0.1:{os.getenv("PORT", 6712)}"

        self._context = zmq.Context()
        self._socket = self._context.socket(zmq.DEALER)
        self._socket.setsockopt(zmq.IDENTITY, self._name)
        self._socket.setsockopt(zmq.LINGER, 0)

        self._push_socket = self._context.socket(zmq.PUSH)
        self._push_socket.setsockopt(zmq.LINGER, 0)

        self._worker_thread_id: threading.Thread | None = None
        self._monitor_thread_id: threading.Thread | None = None

        self._monitors: dict[zmq.SyncSocket, SocketStatus] = {}
        self._monitor_poller = zmq.Poller()

        self._stop_event = Signal(False)
        self.broker_connected = Signal(False)
        self.push_connected = Signal(False)
        self.connected = Signal.derive(lambda: self.broker_connected.get() and self.push_connected.get(), self.broker_connected, self.push_connected)
        self.disconnected = Signal.derive(lambda: (not self.broker_connected.get()) and (not self.push_connected.get()), self.broker_connected, self.push_connected)

        self._job_threads: dict[str, threading.Thread] = {}
        self.state = State()

    # NOTE: because we set linger to 0, any messages queued when broker restarts will be dropped.
    # so either each extension needs to know the connectivity states, so it can reset it states as to not
    # send out of state packet.
    # or, we set the linger to -1 again, but then there may be issues with cleanup,
    def push(self, pkt: PreparedPacket) -> None:
        self.push_connected.wait_true()
        # NOTE: to_pending().SerializeToString() makes us go from 1.5m to 500k packet/s,
        # AND hooking with the whole infra pushed it to 50k packet/s.
        # is that normal? its still way overkill for this use case,
        # but i might want to start thinking switching capnproto and shared memory ring buffer,
        # just for the fun of it
        self.logger.debug(f"   push \x1b[35m-->>\x1b[0m \x1b[35m>>\x1b[0m{pkt!r}\x1b[35m>>\x1b[0m")
        self._push_socket.send(pkt.to_pending().SerializeToString())

    # TODO: try pytest-xdist rather than pytest-forked
    # TODO: have a send_to() possibly?

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

        if self.logger.isEnabledFor(logging.DEBUG):
            suppress = False
            if pkt.HasField("state_update") and pkt.state_update.what == STATE_SET_MY_TELEMETRY:
                suppress = True

            if not suppress:
                self.logger.debug(f"\x1b[32m<<--\x1b[0m recv    \x1b[32m<<\x1b[0m{pkt!r}\x1b[32m<<\x1b[0m")

        return pkt

    @abstractmethod
    def process(self, event: PendingPacket) -> PendingPacket | None: ...

    @abstractmethod
    def destroy(self) -> None: ...

    def start(self, block: bool = False) -> Signal[bool]:
        self._monitor_thread_id = threading.Thread(target=self._monitor_thread, daemon=True)
        self._monitor_thread_id.start()

        for name in dir(self):
            if not name.startswith("thread_"):
                continue

            attr = getattr(self, name)
            if callable(attr):
                self.logger.debug(f"extension {self._name} starting job: {name}")
                t = threading.Thread(target=attr, daemon=True)
                t.start()
                self._job_threads[name] = t

        self._socket.connect(self._broker_addr)
        mon = self._socket.get_monitor_socket()
        self._monitors[mon] = SocketStatus("broker", self.broker_connected)
        self._monitor_poller.register(mon)

        addr = urlparse(self._broker_addr)
        addr = addr._replace(netloc=f"{addr.hostname}:{(addr.port or 18192) + 1}")
        self.logger.debug(f"push socket connecting to {addr.geturl()}")
        self._push_socket.connect(addr.geturl())
        mon = self._push_socket.get_monitor_socket()
        self._monitors[mon] = SocketStatus("push", self.push_connected)
        self._monitor_poller.register(mon)

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

        self._stop_event.set(True)

        try:
            self._socket.close()
        except Exception as e:
            self.logger.debug(f"socket close error: {e}")
        self.broker_connected.set(False)
        try:
            self._push_socket.close()
        except Exception as e:
            self.logger.debug(f"socket close error: {e}")
        self.push_connected.set(False)

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

        return self.disconnected

    def _monitor_thread(self) -> None:
        try:
            while not self._stop_event.get():
                events = dict(self._monitor_poller.poll(100))

                for mon, _ in events.items():
                    try:
                        evt = recv_monitor_message(mon, zmq.NOBLOCK)
                    except zmq.error.Again:
                        continue

                    if not evt:
                        continue

                    event = evt["event"]
                    source = self._monitors[mon]

                    # print(source, zmq.Event(event).name)
                    if event == zmq.EVENT_CONNECTED:
                        self.logger.debug(f"{source.name} connected")
                        if source.name == "broker":
                            self._send(Packet(type=Packet.TYPE_HANDSHAKE))
                        elif source.name == "push":
                            source.connected.set(True)

                    elif event in (
                        zmq.EVENT_DISCONNECTED,
                        zmq.EVENT_MONITOR_STOPPED,
                        zmq.EVENT_CLOSED,
                    ):
                        self.logger.debug(f"{source.name} disconnected")
                        source.connected.set(False)

        except Exception as e:
            self.logger.debug(f"monitor thread error: {e}")

        finally:
            for mon in self._monitors:
                try:
                    self._monitor_poller.unregister(mon)
                    mon.close()
                except Exception:
                    pass
            self.logger.debug("monitor thread exiting")

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

                        self._copy_meta_fields(response, pkt.pending_packet)
                        response._hit_count += 1
                        if PERF:
                            self.logger.debug(f"extension processing time: {(time.perf_counter_ns() - start) / 1e6}us")
                        self._send(Packet(type=Packet.TYPE_PENDING_PACKET, pending_packet=response))
                    case Packet.TYPE_CONNECTED:
                        self.broker_connected.set(True)
                        self._send(Packet(type=Packet.TYPE_STATE_REQUEST))
                    case Packet.TYPE_DISCONNECT:
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
                        print(pkt.state_response.state)
                        self.state = State.from_proto(pkt.state_response.state)
                        if self.state.status == Status.IN_WORLD:
                            self.console_log(f"extension {self._name} connected")
                    case Packet.TYPE_STATE_UPDATE:
                        self.state.update(pkt.state_update)
        except zmq.error.ZMQError as e:
            if not self._stop_event.get():
                self.logger.debug(f"ZMQ error in main loop: {e}")
        finally:
            self.logger.debug("worker thread exiting")

    # helper

    def any(self, obj: object) -> Any:
        ret = Any()
        ret.Pack(obj)

        return ret

    class Type:
        x: TAny
        name: str

        def make(self) -> dict[str, TAny]:
            return {self.name: self.x}

    class uint32_t(Type):
        def __init__(self, x: int) -> None:
            self.x = x
            self.name = "u32"

    class int32_t(Type):
        def __init__(self, x: int) -> None:
            self.x = x
            self.name = "i32"

    class float_t(Type):
        def __init__(self, x: float) -> None:
            self.x = x
            self.name = "flt"

    class string_t(Type):
        def __init__(self, x: str) -> None:
            self.x = x
            self.name = "str"

    class bytes_t(Type):
        def __init__(self, x: bytes) -> None:
            self.x = x
            self.name = "buf"

    class TankFieldSelector:
        def __init__(self, lvalue: Any) -> None:
            self.lvalue = lvalue

        def _binop(self, other: "Extension.Type", op: Op) -> BinOp:
            return BinOp(
                lvalue=self.lvalue,
                op=op,
                **other.make(),
            )

        def __eq__(self, other: "Extension.Type") -> BinOp:
            return self._binop(other, Op.OP_EQ)

        def __ne__(self, other: "Extension.Type") -> BinOp:
            return self._binop(other, Op.OP_NEQ)

        def __gt__(self, other: "Extension.Type") -> BinOp:
            return self._binop(other, Op.OP_GT)

        def __ge__(self, other: "Extension.Type") -> BinOp:
            return self._binop(other, Op.OP_GTE)

        def __lt__(self, other: "Extension.Type") -> BinOp:
            return self._binop(other, Op.OP_LT)

        def __le__(self, other: "Extension.Type") -> BinOp:
            return self._binop(other, Op.OP_LTE)

        def __contains__(self, other: "Extension.Type") -> BinOp:
            return self._binop(other, Op.OP_CONTAINS)

        def eq_eps(self, other: "Extension.Type") -> BinOp:
            return self._binop(other, Op.OP_EQ_EPS)

        def bit_test(self, other: "Extension.Type") -> BinOp:
            return self._binop(other, Op.OP_BIT_TEST)

        def startswith(self, other: "Extension.Type") -> BinOp:
            return self._binop(other, Op.OP_STARTSWITH)

        def endswith(self, other: "Extension.Type") -> BinOp:
            return self._binop(other, Op.OP_ENDSWITH)

        def like(self, other: "Extension.Type") -> BinOp:
            return self._binop(other, Op.OP_LIKE)

    @property
    def tank_type(self) -> TankFieldSelector:
        return Extension.TankFieldSelector(self.any(FieldValue(v=Field.TANK_FIELD_TYPE)))

    @property
    def tank_object_type(self) -> TankFieldSelector:
        return Extension.TankFieldSelector(self.any(FieldValue(v=Field.TANK_FIELD_OBJECT_TYPE)))

    @property
    def tank_jump_count(self) -> TankFieldSelector:
        return Extension.TankFieldSelector(self.any(FieldValue(v=Field.TANK_FIELD_JUMP_COUNT)))

    @property
    def tank_animation_type(self) -> TankFieldSelector:
        return Extension.TankFieldSelector(self.any(FieldValue(v=Field.TANK_FIELD_ANIMATION_TYPE)))

    @property
    def tank_net_id(self) -> TankFieldSelector:
        return Extension.TankFieldSelector(self.any(FieldValue(v=Field.TANK_FIELD_NET_ID)))

    @property
    def tank_target_net_id(self) -> TankFieldSelector:
        return Extension.TankFieldSelector(self.any(FieldValue(v=Field.TANK_FIELD_TARGET_NET_ID)))

    @property
    def tank_flags(self) -> TankFieldSelector:
        return Extension.TankFieldSelector(self.any(FieldValue(v=Field.TANK_FIELD_FLAGS)))

    @property
    def tank_float_var(self) -> TankFieldSelector:
        return Extension.TankFieldSelector(self.any(FieldValue(v=Field.TANK_FIELD_FLOAT_VAR)))

    @property
    def tank_value(self) -> TankFieldSelector:
        return Extension.TankFieldSelector(self.any(FieldValue(v=Field.TANK_FIELD_VALUE)))

    @property
    def tank_vector_x(self) -> TankFieldSelector:
        return Extension.TankFieldSelector(self.any(FieldValue(v=Field.TANK_FIELD_VECTOR_X)))

    @property
    def tank_vector_y(self) -> TankFieldSelector:
        return Extension.TankFieldSelector(self.any(FieldValue(v=Field.TANK_FIELD_VECTOR_Y)))

    @property
    def tank_vector_x2(self) -> TankFieldSelector:
        return Extension.TankFieldSelector(self.any(FieldValue(v=Field.TANK_FIELD_VECTOR_X2)))

    @property
    def tank_vector_y2(self) -> TankFieldSelector:
        return Extension.TankFieldSelector(self.any(FieldValue(v=Field.TANK_FIELD_VECTOR_Y2)))

    @property
    def tank_particle_rotation(self) -> TankFieldSelector:
        return Extension.TankFieldSelector(self.any(FieldValue(v=Field.TANK_FIELD_PARTICLE_ROTATION)))

    @property
    def tank_int_x(self) -> TankFieldSelector:
        return Extension.TankFieldSelector(self.any(FieldValue(v=Field.TANK_FIELD_INT_X)))

    @property
    def tank_int_y(self) -> TankFieldSelector:
        return Extension.TankFieldSelector(self.any(FieldValue(v=Field.TANK_FIELD_INT_Y)))

    def console_log(self, msg: str) -> None:
        self.push(PreparedPacket(console_message(msg), DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))

    def send_particle(self, id: int, f: int = 0, f2: int = 0, *, abs: vec2 | None = None, tile: ivec2 | None = None) -> None:
        pos = abs if abs else tile * 32 + 16 if tile else None
        pos = abs if abs else (tile[0] * 32.0 + 16, tile[1] * 32.0 + 16) if tile else None
        if not pos:
            return

        self.push(PreparedPacket(particle(id, pos[0], pos[1], f, f2), DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))

    # TODO: improve command
    def command_toggle(self, cmd: str | bytes, id: int) -> Interest:
        """match all text"""
        cmd = cmd.encode() if isinstance(cmd, str) else cmd
        return Interest(
            interest=INTEREST_GENERIC_TEXT,
            generic_text=InterestGenericText(
                where=[
                    BinOp(
                        lvalue=self.any(Query(where=[Clause(row=FindRow(method=FindRow.KEY_ANY, key=b"text"), col=FindCol(method=FindCol.RELATIVE, index=1))])),
                        op=OP_EQ,
                        buf=cmd,
                    )
                ]
            ),
            blocking_mode=BLOCKING_MODE_BLOCK,
            direction=DIRECTION_CLIENT_TO_SERVER,
            id=id,
        )

    def command(self, cmd: str | bytes, id: int) -> Interest:
        """match startswith"""
        cmd = cmd.encode() if isinstance(cmd, str) else cmd
        return Interest(
            interest=INTEREST_GENERIC_TEXT,
            generic_text=InterestGenericText(
                where=[
                    BinOp(
                        lvalue=self.any(Query(where=[Clause(row=FindRow(method=FindRow.KEY_ANY, key=b"text"), col=FindCol(method=FindCol.RELATIVE, index=1))])),
                        op=OP_STARTSWITH,
                        buf=cmd,
                    )
                ]
            ),
            blocking_mode=BLOCKING_MODE_BLOCK,
            direction=DIRECTION_CLIENT_TO_SERVER,
            id=id,
        )

    def standalone(self) -> None:
        """call this only in `if __name__ == '__main__'`"""
        parser = ArgumentParser()
        parser.add_argument("-v", action="store_true", help="verbose")

        args = parser.parse_args()

        level = logging.DEBUG if args.v else logging.INFO
        setup_logger(
            self._name.decode(errors="surrogateescape"),
            log_dir=_setting.appdir / "logs" / "extension",
            level=level,
        )

        try:
            self.start(block=True)
        except:
            pass
