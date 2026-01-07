import math
import random
import time
from typing import Callable, Iterator
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket, TankFlags, TankPacket, TankType
from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.variant import Variant
from gtools.protogen.extension_pb2 import DIRECTION_CLIENT_TO_SERVER
from thirdparty.enet.bindings import ENetPacketFlag


def call_function(fn_name: bytes, *args: Variant.Type) -> TankPacket:
    return TankPacket(
        type=TankType.CALL_FUNCTION,
        flags=TankFlags.EXTENDED,
        extended_data=Variant([Variant.vstr(fn_name), *args]).serialize(),
    )


def console_message(text: str | bytes) -> NetPacket:
    call = call_function(b"OnConsoleMessage", Variant.vstr(text.encode() if isinstance(text, str) else text))
    call.net_id = 4294967295

    return NetPacket(NetType.TANK_PACKET, call)


def play_positioned(path: str | bytes, net_id: int) -> NetPacket:
    call = call_function(b"OnPlayPositioned", Variant.vstr(path.encode() if isinstance(path, str) else path))
    call.net_id = net_id

    return NetPacket(NetType.TANK_PACKET, call)


def chat(text: str | bytes) -> NetPacket:
    text = text if isinstance(text, bytes) else text.encode()
    return NetPacket(NetType.GENERIC_TEXT, StrKV([[b"action", b"input"], [b"", b"text", text]]))


def particle(id: int, x: float, y: float, alternate: int = 0) -> NetPacket:
    return NetPacket(
        NetType.TANK_PACKET,
        TankPacket(
            TankType.SEND_PARTICLE_EFFECT,
            vector_x=x,
            vector_y=y,
            net_id=id,
            vector_y2=id,
            vector_x2=alternate,
        ),
    )


class PacketSequence:
    VerifyCondition = Callable[[], bool]

    class Packet:
        def __init__(self, pkt: PreparedPacket, verify: list["PacketSequence.VerifyCondition"] | None = None) -> None:
            self.pkt = pkt
            self.verified = False
            self._verify = verify if verify else []

    def __init__(self) -> None:
        self._seq: list[PacketSequence.Packet] = []
        self._seq_idx = 0

        self._current: PacketSequence.Packet | None = None
        self._verify_accumulator: list[PacketSequence.VerifyCondition] = []
        self._last_verified_call = -1

    def next(self) -> "PacketSequence.Packet":
        if not self._seq and self._verify_accumulator:
            raise ValueError(f"empty sequence, {len(self._verify_accumulator)} verify function")
        elif not self._seq and not self._verify_accumulator:
            raise ValueError("empty sequence")

        if self._current is None:
            self._current = self._seq[0]

        current = self._current
        if self._current.verified:
            self._seq_idx += 1
            if self._seq_idx < len(self._seq):
                self._current = self._seq[self._seq_idx]
        return current

    def verify(self) -> None:
        print(time.monotonic(), self._last_verified_call, self._last_verified_call != -1)
        if self._current is None:
            self._current = self._seq[0]

        self._current.verified = all(x() for x in self._current._verify)
        if self._current.verified:
            self._last_verified_call = time.monotonic()

    def _send(self, pkt: PreparedPacket) -> None:
        self._seq.append(PacketSequence.Packet(pkt, self._verify_accumulator.copy()))
        self._verify_accumulator.clear()

    def _wait(self, t: float) -> None:
        self._verify_accumulator.append(
            lambda: self._last_verified_call != -1 and (time.monotonic() - self._last_verified_call) > t,
        )

    def _verify(self, fn: Callable[[], bool]) -> None:
        self._verify_accumulator.append(fn)


def rand_normal_dist(low: float, high: float, std_ratio: float = 0.15) -> float:
    mean = (low + high) / 2
    std = (high - low) * std_ratio
    return max(low, min(high, random.gauss(mean, std)))


def rand_soft(mid: float, radius: float, std_ratio: float = 0.3) -> float:
    x = random.gauss(0, std_ratio)
    return mid + radius * math.tanh(x)


def chat_seq(text: bytes, net_id: int, delay: float | tuple[float, float] | None = None) -> PacketSequence:
    seq = PacketSequence()

    d = 2
    if isinstance(delay, float):
        d = delay
    elif isinstance(delay, tuple):
        d = rand_normal_dist(delay[0], delay[1])
    else:
        # round to 8 char/s
        d = len(text) / 8
        d = rand_soft(d, d * 0.1)

    seq._send(
        PreparedPacket(
            NetPacket(
                NetType.TANK_PACKET,
                TankPacket(type=TankType.SET_ICON_STATE, net_id=net_id, int_x=1),
            ),
            DIRECTION_CLIENT_TO_SERVER,
            ENetPacketFlag.RELIABLE,
        )
    )
    seq._wait(d)
    seq._send(
        PreparedPacket(
            NetPacket(
                NetType.TANK_PACKET,
                TankPacket(
                    type=TankType.SET_ICON_STATE,
                    net_id=net_id,
                ),
            ),
            DIRECTION_CLIENT_TO_SERVER,
            ENetPacketFlag.RELIABLE,
        )
    )
    seq._send(
        PreparedPacket(
            chat(text),
            DIRECTION_CLIENT_TO_SERVER,
            ENetPacketFlag.RELIABLE,
        )
    )

    return seq
