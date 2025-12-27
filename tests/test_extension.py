from queue import Empty, Queue
import socket
import time
import pytest

from extension.utils import UtilityExtension
from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.variant import Variant
from tests import verify

from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket, TankFlags, TankPacket, TankType
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    DIRECTION_UNSPECIFIED,
    INTEREST_CALL_FUNCTION,
    INTEREST_STATE,
    INTEREST_TANK_PACKET,
    INTEREST_TILE_CHANGE_REQUEST,
    Direction,
    Interest,
    InterestCallFunction,
    InterestState,
    PendingPacket,
)
from gtools.proxy.extension.broker import Broker, PacketCallback
from gtools.proxy.extension.sdk import Extension
from thirdparty.enet.bindings import ENetPacketFlag


class ExtensionNextState(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_BLOCK, direction=DIRECTION_UNSPECIFIED)])

    def process(self, event: PendingPacket) -> PendingPacket | None:
        p = NetPacket.deserialize(event.buf)
        p.tank.net_id = (p.tank.net_id * 31 + int(self._name.split(b"-")[-1].decode())) & 0xFFFFFFFF
        event.buf = p.serialize()

        return self.forward(event)

    def destroy(self) -> None:
        pass


class ExtensionNoOp(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_BLOCK, direction=DIRECTION_UNSPECIFIED)])

    def process(self, event: PendingPacket) -> PendingPacket | None:
        pass

    def destroy(self) -> None:
        pass


class ExtensionNextStateNonBlock(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(
            name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_SEND_AND_FORGET, direction=DIRECTION_UNSPECIFIED)]
        )

    def process(self, event: PendingPacket) -> PendingPacket | None:
        p = NetPacket.deserialize(event.buf)
        p.tank.net_id = (p.tank.net_id * 31 + int(self._name.split(b"-")[-1].decode())) & 0xFFFFFFFF
        event.buf = p.serialize()

        return self.forward(event)

    def destroy(self) -> None:
        pass


class ExtensionNoOpNonBlock(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(
            name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_SEND_AND_FORGET, direction=DIRECTION_UNSPECIFIED)]
        )

    def process(self, event: PendingPacket) -> PendingPacket | None:
        pass

    def destroy(self) -> None:
        pass


def compute_state(init: int, n: int | list[int]) -> int:
    s = init
    l = range(n - 1, -1, -1) if isinstance(n, int) else n
    for i in l:
        s = (s * 31 + i) & 0xFFFFFFFF

    return s


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return True
        return False


def test_connect_non_block() -> None:
    b = Broker()
    b.start()

    try:
        name = f"test-0"
        ext = ExtensionNextStateNonBlock(name)
        assert ext.start().wait_true(5)

        assert len(b._extension_mgr._extensions) == 1
        assert ext.broker_connected.get()
        assert b._extension_mgr.get_extension(ext._name).id == ext._name

        assert ext.stop().wait_true(5)
        assert len(b._extension_mgr._extensions) == 0
        with pytest.raises(KeyError):
            assert b._extension_mgr.get_extension(ext._name)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_connect_multi_non_block(request: pytest.FixtureRequest) -> None:
    b = Broker()
    b.start()

    try:
        extensions: list[ExtensionNextStateNonBlock] = []
        for i in range(5):
            ext = ExtensionNextStateNonBlock(f"{request.node.name}-{i}")
            assert ext.start().wait_true(5)
            extensions.append(ext)

        assert len(b._extension_mgr._extensions) == len(extensions)
        assert len(b._extension_mgr._interest_map[extensions[0]._interest[0].interest]) == len(extensions)

        for i, ext in enumerate(extensions, 1):
            assert b._extension_mgr.get_extension(ext._name).id == ext._name

            assert ext.stop().wait_true(5)
            time.sleep(0.2)  # ideally, it would be removed from broker at this point without specifically a delay
            assert len(b._extension_mgr._extensions) == len(extensions) - i

            with pytest.raises(KeyError):
                assert b._extension_mgr.get_extension(ext._name)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_process_non_block(request: pytest.FixtureRequest) -> None:
    b = Broker()
    b.start()

    try:
        name = f"{request.node.name}-0"
        ext = ExtensionNextStateNonBlock(name)
        assert ext.start().wait_true(5)

        ress: list[PreparedPacket] = []

        def set_res(pkt: PreparedPacket) -> None:
            nonlocal ress
            ress.append(pkt)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE), PacketCallback(any=set_res))
        assert pkt is None

        while not ress:
            time.sleep(0.1)

        res = ress[0]
        assert res is not None
        assert res.direction.value == DIRECTION_UNSPECIFIED
        assert res.flags == ENetPacketFlag.NONE
        assert res.as_net.type == NetType.TANK_PACKET
        assert res.as_net.tank.net_id == compute_state(1, 1)
        verify(res.as_raw)

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_process_forward_not_modified_non_block(request: pytest.FixtureRequest) -> None:
    b = Broker()
    b.start()

    try:
        name = f"{request.node.name}-0"
        ext = ExtensionNoOpNonBlock(name)
        assert ext.start().wait_true(5)

        ress: list[PreparedPacket] = []

        def set_res(pkt: PreparedPacket) -> None:
            nonlocal ress
            ress.append(pkt)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE), PacketCallback(any=set_res))

        time.sleep(0.5)
        assert not ress

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


class ExtensionCancelNonBlock(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(
            name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_SEND_AND_FORGET, direction=DIRECTION_UNSPECIFIED)]
        )

    def process(self, event: PendingPacket) -> PendingPacket | None:
        return self.cancel()

    def destroy(self) -> None:
        pass


def test_cancel_non_block() -> None:
    b = Broker()
    b.start()

    try:
        ext = ExtensionCancelNonBlock(f"cancel-1", 1)
        assert ext.start().wait_true(5)

        assert len(b._extension_mgr.get_all_extension()) == 1

        ress: list[PreparedPacket] = []

        def set_res(pkt: PreparedPacket) -> None:
            nonlocal ress
            ress.append(pkt)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE), PacketCallback(any=set_res))

        time.sleep(0.5)
        assert len(ress) == 0

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


class ExtensionFinishNonBlock(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(
            name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_SEND_AND_FORGET, direction=DIRECTION_UNSPECIFIED)]
        )

    def process(self, event: PendingPacket) -> PendingPacket | None:
        pkt = NetPacket.deserialize(event.buf)
        pkt.tank.int_x += 1
        event.buf = pkt.serialize()

        return self.finish(event)

    def destroy(self) -> None:
        pass


def test_finish_non_block() -> None:
    b = Broker()
    b.start()

    try:
        ext = ExtensionFinishNonBlock("finish")
        assert ext.start().wait_true(5)

        ress: list[PreparedPacket] = []

        def set_res(pkt: PreparedPacket) -> None:
            nonlocal ress
            ress.append(pkt)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE), PacketCallback(any=set_res))

        while not ress:
            time.sleep(0.1)

        res = ress[0]
        assert res is not None
        assert res.direction.value == DIRECTION_UNSPECIFIED
        assert res.flags == ENetPacketFlag.NONE
        assert res.as_net.type == NetType.TANK_PACKET
        assert res.as_net.tank.net_id == 1
        assert res.as_net.tank.int_x == 1
        verify(res.as_raw)

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


# TODO: since port is dynamic now, use the port from broker directly
def test_connect() -> None:
    b = Broker()
    b.start()

    try:
        name = f"test-0"
        ext = ExtensionNextState(name)
        assert ext.start().wait_true(5)

        assert len(b._extension_mgr._extensions) == 1
        assert ext.broker_connected.get()
        assert b._extension_mgr.get_extension(ext._name).id == ext._name

        assert ext.stop().wait_true(5)
        assert len(b._extension_mgr._extensions) == 0
        with pytest.raises(KeyError):
            assert b._extension_mgr.get_extension(ext._name)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_connect_multi(request: pytest.FixtureRequest) -> None:
    b = Broker()
    b.start()

    try:
        extensions: list[ExtensionNextState] = []
        for i in range(5):
            ext = ExtensionNextState(f"{request.node.name}-{i}")
            assert ext.start().wait_true(5)
            extensions.append(ext)

        assert len(b._extension_mgr._extensions) == len(extensions)
        assert len(b._extension_mgr._interest_map[extensions[0]._interest[0].interest]) == len(extensions)

        for i, ext in enumerate(extensions, 1):
            assert b._extension_mgr.get_extension(ext._name).id == ext._name

            assert ext.stop().wait_true(5)
            time.sleep(0.2)  # ideally, it would be removed from broker at this point without specifically a delay
            assert len(b._extension_mgr._extensions) == len(extensions) - i

            with pytest.raises(KeyError):
                assert b._extension_mgr.get_extension(ext._name)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_process(request: pytest.FixtureRequest) -> None:
    b = Broker()
    b.start()

    try:
        name = f"{request.node.name}-0"
        ext = ExtensionNextState(name)
        assert ext.start().wait_true(5)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))

        assert pkt
        pkt, cancelled = pkt
        assert cancelled == False
        assert pkt._hit_count == 1
        assert pkt.direction == DIRECTION_UNSPECIFIED
        assert pkt.packet_flags == ENetPacketFlag.NONE
        net = NetPacket.deserialize(pkt.buf)
        assert net.type == NetType.TANK_PACKET
        assert net.tank.net_id == compute_state(1, 1)
        verify(pkt.buf)

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_process_multi(request: pytest.FixtureRequest) -> None:
    b = Broker()
    b.start()

    try:
        extensions: list[ExtensionNextState] = []
        for i in range(10):
            name = f"{request.node.name}-{i}"
            ext = ExtensionNextState(name, priority=i)
            assert ext.start().wait_true(5)

            extensions.append(ext)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))

        assert pkt
        pkt, cancelled = pkt
        assert cancelled == False
        assert pkt._hit_count == 10
        assert pkt.direction == DIRECTION_UNSPECIFIED
        assert pkt.packet_flags == ENetPacketFlag.NONE
        net = NetPacket.deserialize(pkt.buf)
        assert net.type == NetType.TANK_PACKET
        assert net.tank.net_id == compute_state(1, 10)
        verify(pkt.buf)

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_process_forward_not_modified(request: pytest.FixtureRequest) -> None:
    b = Broker()
    b.start()

    try:
        name = f"{request.node.name}-0"
        ext = ExtensionNoOp(name)
        assert ext.start().wait_true(5)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))

        assert pkt
        pkt, cancelled = pkt
        assert cancelled == False
        assert pkt._hit_count == 1
        assert pkt.direction == DIRECTION_UNSPECIFIED
        assert pkt.packet_flags == ENetPacketFlag.NONE
        net = NetPacket.deserialize(pkt.buf)
        assert net.type == NetType.TANK_PACKET
        assert net.tank.net_id == 1
        verify(pkt.buf)

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_broker_restart(request: pytest.FixtureRequest) -> None:
    b = Broker()
    b.start()

    try:
        ext = ExtensionNextState(f"{request.node.name}-0")
        assert ext.start().wait_true(5)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))

        assert pkt
        pkt, cancelled = pkt
        assert cancelled == False
        assert pkt._hit_count == 1
        assert pkt.direction == DIRECTION_UNSPECIFIED
        assert pkt.packet_flags == ENetPacketFlag.NONE
        net = NetPacket.deserialize(pkt.buf)
        assert net.type == NetType.TANK_PACKET
        assert net.tank.net_id == compute_state(1, 1)
        verify(pkt.buf, key=1)

        b.stop()
        assert ext.broker_connected.wait_false(5)
        b = Broker()
        b.start()
        assert ext.broker_connected.wait_true(5)

        pkt = b.process_event(PreparedPacket(net, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))

        assert pkt
        pkt, cancelled = pkt
        assert cancelled == False
        assert pkt._hit_count == 1
        assert pkt.direction == DIRECTION_UNSPECIFIED
        assert pkt.packet_flags == ENetPacketFlag.NONE
        net = NetPacket.deserialize(pkt.buf)
        assert net.type == NetType.TANK_PACKET
        assert net.tank.net_id == compute_state(compute_state(1, 1), 1)
        verify(pkt.buf, key=2)

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


class ExtensionCancel(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_BLOCK, direction=DIRECTION_UNSPECIFIED)])

    def process(self, event: PendingPacket) -> PendingPacket | None:
        return self.cancel()

    def destroy(self) -> None:
        pass


def test_cancel() -> None:
    b = Broker()
    b.start()

    try:
        ext2 = ExtensionNextState("next-0")
        assert ext2.start().wait_true(5)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))

        assert pkt
        pkt, cancelled = pkt
        assert cancelled == False
        assert pkt._hit_count == 1
        assert pkt.direction == DIRECTION_UNSPECIFIED
        assert pkt.packet_flags == ENetPacketFlag.NONE
        net = NetPacket.deserialize(pkt.buf)
        assert net.type == NetType.TANK_PACKET
        assert net.tank.net_id == compute_state(1, 1)
        verify(pkt.buf, key=1)

        ext = ExtensionCancel(f"cancel-1", 1)
        assert ext.start().wait_true(5)

        assert len(b._extension_mgr.get_all_extension()) == 2

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert pkt
        pkt, cancelled = pkt
        assert cancelled
        assert pkt._hit_count == 1
        assert pkt.direction == DIRECTION_UNSPECIFIED
        assert pkt.packet_flags == ENetPacketFlag.NONE
        net = NetPacket.deserialize(pkt.buf)
        assert net.type == NetType.TANK_PACKET
        assert net.tank.net_id == 1
        verify(pkt.buf, key=2)

        assert ext.stop().wait_true(5)
        assert ext2.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


class ExtensionFinish(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_BLOCK, direction=DIRECTION_UNSPECIFIED)])

    def process(self, event: PendingPacket) -> PendingPacket | None:
        pkt = NetPacket.deserialize(event.buf)
        pkt.tank.int_x += 1
        event.buf = pkt.serialize()

        return self.finish(event)

    def destroy(self) -> None:
        pass


def test_finish() -> None:
    b = Broker()
    b.start()

    try:
        ext = ExtensionNextState("next-0", 2)
        assert ext.start().wait_true(5)

        ext2 = ExtensionFinish("finish-1", 1)
        assert ext2.start().wait_true(5)

        ext3 = ExtensionNextState("next-2", 0)
        assert ext3.start().wait_true(5)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert pkt
        pkt, cancelled = pkt
        assert cancelled == False
        assert pkt._hit_count == 2
        assert pkt.direction == DIRECTION_UNSPECIFIED
        assert pkt.packet_flags == ENetPacketFlag.NONE
        net = NetPacket.deserialize(pkt.buf)
        assert net.type == NetType.TANK_PACKET
        assert net.tank.net_id == compute_state(1, 1)
        assert net.tank.int_x == 1
        verify(pkt.buf, key=1)

        assert ext2.stop().wait_true(5)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=10))
        pkt = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert pkt
        pkt, cancelled = pkt
        assert cancelled == False
        assert pkt._hit_count == 2
        assert pkt.direction == DIRECTION_UNSPECIFIED
        assert pkt.packet_flags == ENetPacketFlag.NONE
        net = NetPacket.deserialize(pkt.buf)
        assert net.type == NetType.TANK_PACKET
        assert net.tank.net_id == compute_state(10, [0, 2])
        assert net.tank.int_x == 0
        verify(pkt.buf, key=2)

        assert ext.stop().wait_true(5)
        assert ext3.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


class ExtensionCommand(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(
            name=name,
            interest=[
                self.command("/should_work", 0),
            ],
        )

    def process(self, event: PendingPacket) -> PendingPacket | None:
        print(NetPacket.deserialize(event.buf))
        return self.cancel()

    def destroy(self) -> None:
        pass


def test_match_generic_text() -> None:
    b = Broker()
    b.start()

    try:
        ext = ExtensionCommand("command")
        assert ext.start().wait_true(5)

        opkt = NetPacket(
            type=NetType.GENERIC_TEXT,
            data=StrKV([[b"action", b"input"], [b"", b"text", b"hello"]]),
        )
        pkt = b.process_event(PreparedPacket(opkt, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.NONE))
        assert pkt is None

        opkt = NetPacket(
            type=NetType.GENERIC_TEXT,
            data=StrKV([[b"action", b"input"], [b"", b"text", b"/should_work"]]),
        )
        pkt = b.process_event(PreparedPacket(opkt, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.NONE))
        assert pkt
        pkt, cancelled = pkt
        verify(pkt.buf)
        assert cancelled == True

        opkt = NetPacket(
            type=NetType.GENERIC_TEXT,
            data=StrKV([[b"action", b"input"], [b"", b"text", b"//should_work"]]),
        )
        pkt = b.process_event(PreparedPacket(opkt, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.NONE))
        assert pkt is None

        opkt = NetPacket(
            type=NetType.GENERIC_TEXT,
            data=StrKV([[b"action", b"input"], [b"", b"text", b"//no"]]),
        )
        pkt = b.process_event(PreparedPacket(opkt, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.NONE))
        assert pkt is None

        opkt = NetPacket(
            type=NetType.GENERIC_TEXT,
            data=StrKV([[b"action", b"input"], [b"", b"text", b"/not_registered"]]),
        )
        pkt = b.process_event(PreparedPacket(opkt, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.NONE))
        assert pkt is None

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


class ExtensionPass(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_BLOCK, direction=DIRECTION_UNSPECIFIED)])

    def process(self, event: PendingPacket) -> PendingPacket | None:
        return self.pass_to_next()

    def destroy(self) -> None:
        pass


class ExtensionPassNonBlock(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(
            name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_SEND_AND_FORGET, direction=DIRECTION_UNSPECIFIED)]
        )

    def process(self, event: PendingPacket) -> PendingPacket | None:
        return self.pass_to_next()

    def destroy(self) -> None:
        pass


def test_meta_is_preserved_pass() -> None:
    b = Broker()
    b.start()

    extension: list[Extension] = []

    try:
        for i in range(10):
            ext = ExtensionPass(f"pass-{i}")
            assert ext.start().wait_true(5)

            extension.append(ext)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))

        assert res
        pkt, cancelled = res
        assert cancelled == False
        assert pkt._hit_count == len(extension)
        assert pkt.direction == DIRECTION_SERVER_TO_CLIENT
        assert pkt.packet_flags == ENetPacketFlag.RELIABLE
        net = NetPacket.deserialize(pkt.buf)
        assert net.type == NetType.TANK_PACKET
        assert net.tank.net_id == 1
        verify(pkt.buf)

        for ext in extension:
            assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_meta_is_preserved_process() -> None:
    b = Broker()
    b.start()

    extension: list[Extension] = []

    try:
        for i in range(10):
            ext = ExtensionNextState(f"state-{i}", i)
            assert ext.start().wait_true(5)

            extension.append(ext)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))

        assert res
        pkt, cancelled = res
        assert cancelled == False
        assert pkt._hit_count == len(extension)
        assert pkt.direction == DIRECTION_SERVER_TO_CLIENT
        assert pkt.packet_flags == ENetPacketFlag.RELIABLE
        net = NetPacket.deserialize(pkt.buf)
        assert net.type == NetType.TANK_PACKET
        assert net.tank.net_id == compute_state(1, 10)
        verify(pkt.buf)

        for ext in extension:
            assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_meta_is_preserved_pass_non_block() -> None:
    b = Broker()
    b.start()

    try:
        ext = ExtensionPassNonBlock(f"pass")
        assert ext.start().wait_true(5)

        ress: dict[Direction, PreparedPacket] = {}

        def set_res(d: Direction, pkt: PreparedPacket) -> None:
            nonlocal ress
            ress[d] = pkt

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        res = b.process_event(
            PreparedPacket(pkt, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE),
            PacketCallback(send_to_server=lambda x: set_res(DIRECTION_CLIENT_TO_SERVER, x), send_to_client=lambda x: set_res(DIRECTION_SERVER_TO_CLIENT, x)),
        )
        assert not res

        time.sleep(0.5)
        assert not ress

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_meta_is_preserved_process_non_block() -> None:
    b = Broker()
    b.start()

    try:
        ext = ExtensionNextStateNonBlock(f"state-0")
        assert ext.start().wait_true(5)

        ress: dict[Direction, PreparedPacket] = {}

        def set_res(d: Direction, pkt: PreparedPacket) -> None:
            nonlocal ress
            ress[d] = pkt

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        res = b.process_event(
            PreparedPacket(pkt, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE),
            PacketCallback(send_to_server=lambda x: set_res(DIRECTION_CLIENT_TO_SERVER, x), send_to_client=lambda x: set_res(DIRECTION_SERVER_TO_CLIENT, x)),
        )
        assert not res

        while not ress:
            time.sleep(0.1)

        assert DIRECTION_SERVER_TO_CLIENT in ress
        assert ress[DIRECTION_SERVER_TO_CLIENT].flags == ENetPacketFlag.RELIABLE
        assert ress[DIRECTION_SERVER_TO_CLIENT].as_net.tank.net_id == compute_state(1, 1)

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


class ExtensionPush(Extension):
    def __init__(self, name: str, priority: int = 0, id: int = 0, delay: float | None = None) -> None:
        super().__init__(
            name=name,
            interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_BLOCK, direction=DIRECTION_UNSPECIFIED)],
        )
        self.delay = delay
        self.id = id

    def thread_1(self) -> None:
        for i in range(100):
            self.push(
                PreparedPacket(
                    NetPacket(type=NetType.TANK_PACKET, data=TankPacket(target_net_id=self.id, net_id=i)),
                    DIRECTION_SERVER_TO_CLIENT,
                    ENetPacketFlag.NONE,
                )
            )
            if self.delay:
                time.sleep(self.delay)

    def process(self, event: PendingPacket) -> PendingPacket | None:
        pass

    def destroy(self) -> None:
        pass


def test_push_pull() -> None:
    queue: Queue[PreparedPacket | None] = Queue()
    b = Broker(queue)
    b.start()

    try:
        ext = ExtensionPush(f"push")
        assert ext.start().wait_true(5)

        for i in range(100):
            pkt = queue.get()
            if not pkt:
                break

            assert pkt.direction.value == DIRECTION_SERVER_TO_CLIENT
            assert pkt.flags == ENetPacketFlag.NONE
            assert pkt.as_net.tank.net_id == i

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)
        assert not is_port_in_use(b._pull_port)


def test_push_pull_with_delay() -> None:
    queue: Queue[PreparedPacket | None] = Queue()
    b = Broker(queue)
    b.start()

    try:
        ext = ExtensionPush(f"push", delay=0.01)
        assert ext.start().wait_true(5)

        for i in range(100):
            pkt = queue.get()
            if not pkt:
                break

            assert pkt.direction.value == DIRECTION_SERVER_TO_CLIENT
            assert pkt.flags == ENetPacketFlag.NONE
            assert pkt.as_net.tank.net_id == i

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)
        assert not is_port_in_use(b._pull_port)


class ExtensionPushMulti(Extension):
    def __init__(self, name: str, priority: int = 0, id: int = 0, id2: int = 0, delay1: float | None = None, delay2: float | None = None) -> None:
        super().__init__(
            name=name,
            interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_BLOCK, direction=DIRECTION_UNSPECIFIED)],
        )
        self.id = id
        self.id2 = id2
        self.delay1 = delay1
        self.delay2 = delay2

    def thread_1(self) -> None:
        for i in range(100):
            print(f"thread_1: {i} {self.broker_connected.get()}")
            self.push(
                PreparedPacket(
                    NetPacket(type=NetType.TANK_PACKET, data=TankPacket(target_net_id=self.id, net_id=i)),
                    DIRECTION_SERVER_TO_CLIENT,
                    ENetPacketFlag.NONE,
                )
            )
            if self.delay1:
                time.sleep(self.delay1)
            print(f"thread_1_end: {i}")

    def thread_2(self) -> None:
        for i in range(100):
            print(f"thread_2: {i} {self.broker_connected.get()}")
            self.push(
                PreparedPacket(
                    NetPacket(type=NetType.TANK_PACKET, data=TankPacket(target_net_id=self.id2, net_id=i)),
                    DIRECTION_SERVER_TO_CLIENT,
                    ENetPacketFlag.NONE,
                )
            )
            if self.delay2:
                time.sleep(self.delay2)
            print(f"thread_2_end: {i}")

    def process(self, event: PendingPacket) -> PendingPacket | None:
        pass

    def destroy(self) -> None:
        pass


def test_push_pull_multi() -> None:
    queue: Queue[PreparedPacket | None] = Queue()
    b = Broker(queue)
    b.start()

    try:
        ext = ExtensionPushMulti(f"push-multi", id=0, id2=1)
        assert ext.start().wait_true(5)

        n1 = iter(range(100))
        n2 = iter(range(100))
        for _ in range(200):
            pkt = queue.get()
            if not pkt:
                break

            assert pkt.direction.value == DIRECTION_SERVER_TO_CLIENT
            assert pkt.flags == ENetPacketFlag.NONE
            if pkt.as_net.tank.target_net_id == 0:
                assert pkt.as_net.tank.net_id == next(n1)
            elif pkt.as_net.tank.target_net_id == 1:
                assert pkt.as_net.tank.net_id == next(n2)

        with pytest.raises(StopIteration):
            _ = next(n1)
            _ = next(n2)

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)
        assert not is_port_in_use(b._pull_port)


def test_push_pull_multi_one_delay() -> None:
    queue: Queue[PreparedPacket | None] = Queue()
    b = Broker(queue)
    b.start()

    try:
        ext = ExtensionPushMulti(f"push-multi", id=0, id2=1, delay1=0.01)
        assert ext.start().wait_true(5)

        n1 = iter(range(100))
        n2 = iter(range(100))
        for _ in range(200):
            pkt = queue.get()
            if not pkt:
                break

            assert pkt.direction.value == DIRECTION_SERVER_TO_CLIENT
            assert pkt.flags == ENetPacketFlag.NONE
            if pkt.as_net.tank.target_net_id == 0:
                assert pkt.as_net.tank.net_id == next(n1)
            elif pkt.as_net.tank.target_net_id == 1:
                assert pkt.as_net.tank.net_id == next(n2)

        with pytest.raises(StopIteration):
            _ = next(n1)
            _ = next(n2)

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)
        assert not is_port_in_use(b._pull_port)


def test_push_pull_multi_one_delay_the_other_one() -> None:
    queue: Queue[PreparedPacket | None] = Queue()
    b = Broker(queue)
    b.start()

    try:
        ext = ExtensionPushMulti(f"push-multi", id=0, id2=1, delay2=0.01)
        assert ext.start().wait_true(5)

        n1 = iter(range(100))
        n2 = iter(range(100))
        for _ in range(200):
            pkt = queue.get()
            if not pkt:
                break

            assert pkt.direction.value == DIRECTION_SERVER_TO_CLIENT
            assert pkt.flags == ENetPacketFlag.NONE
            if pkt.as_net.tank.target_net_id == 0:
                assert pkt.as_net.tank.net_id == next(n1)
            elif pkt.as_net.tank.target_net_id == 1:
                assert pkt.as_net.tank.net_id == next(n2)

        with pytest.raises(StopIteration):
            _ = next(n1)
            _ = next(n2)

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)
        assert not is_port_in_use(b._pull_port)


def test_push_pull_multi_both_delay() -> None:
    queue: Queue[PreparedPacket | None] = Queue()
    b = Broker(queue)
    b.start()

    try:
        ext = ExtensionPushMulti(f"push-multi", id=0, id2=1, delay1=0.02, delay2=0.01)
        assert ext.start().wait_true(5)

        n1 = iter(range(100))
        n2 = iter(range(100))
        for _ in range(200):
            pkt = queue.get()
            if not pkt:
                break

            assert pkt.direction.value == DIRECTION_SERVER_TO_CLIENT
            assert pkt.flags == ENetPacketFlag.NONE
            if pkt.as_net.tank.target_net_id == 0:
                assert pkt.as_net.tank.net_id == next(n1)
            elif pkt.as_net.tank.target_net_id == 1:
                assert pkt.as_net.tank.net_id == next(n2)

        with pytest.raises(StopIteration):
            _ = next(n1)
            _ = next(n2)

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)
        assert not is_port_in_use(b._pull_port)


def test_push_pull_multi_extension() -> None:
    queue: Queue[PreparedPacket | None] = Queue()
    b = Broker(queue)
    b.start()

    try:
        ext = ExtensionPushMulti(f"push-1", id=0, id2=1)
        assert ext.start().wait_true(5)

        ext2 = ExtensionPush(f"push-2", id=2)
        assert ext2.start().wait_true(5)

        n = {
            0: iter(range(100)),
            1: iter(range(100)),
            2: iter(range(100)),
        }
        for _ in range(300):
            pkt = queue.get()
            if not pkt:
                break

            assert pkt.direction.value == DIRECTION_SERVER_TO_CLIENT
            assert pkt.flags == ENetPacketFlag.NONE
            assert next(n[pkt.as_net.tank.target_net_id]) == pkt.as_net.tank.net_id

        for _, v in n.items():
            with pytest.raises(StopIteration):
                _ = next(v)

        assert ext.stop().wait_true(5)
        assert ext2.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)
        assert not is_port_in_use(b._pull_port)


def test_push_pull_multi_extension_wih_delay() -> None:
    queue: Queue[PreparedPacket | None] = Queue()
    b = Broker(queue)
    b.start()

    try:
        ext = ExtensionPushMulti(f"push-1", id=0, id2=1, delay1=0.01, delay2=0.02)
        assert ext.start().wait_true(5)

        ext2 = ExtensionPush(f"push-2", id=2, delay=0.03)
        assert ext2.start().wait_true(5)

        n = {
            0: iter(range(100)),
            1: iter(range(100)),
            2: iter(range(100)),
        }
        for _ in range(300):
            pkt = queue.get()
            if not pkt:
                break

            assert pkt.direction.value == DIRECTION_SERVER_TO_CLIENT
            assert pkt.flags == ENetPacketFlag.NONE
            assert next(n[pkt.as_net.tank.target_net_id]) == pkt.as_net.tank.net_id

        for i in n.values():
            with pytest.raises(StopIteration):
                _ = next(i)

        assert ext.stop().wait_true(5)
        assert ext2.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)
        assert not is_port_in_use(b._pull_port)


def test_push_pull_restart() -> None:
    queue: Queue[PreparedPacket | None] = Queue()
    b = Broker(queue)
    b.start()

    try:
        ext = ExtensionNoOp(f"push-1")
        assert ext.start().wait_true(5)

        p = PreparedPacket(
            NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1)),
            DIRECTION_SERVER_TO_CLIENT,
            ENetPacketFlag.NONE,
        )

        ext.push(p)
        e = queue.get()
        assert e
        assert e.as_net.tank.net_id == p.as_net.tank.net_id
        assert e.direction == p.direction
        assert e.flags == p.flags

        b.stop()
        assert ext.connected.wait_false(5)
        time.sleep(1)
        b = Broker(queue)
        b.start()
        assert ext.connected.wait_true(5)

        ext.push(p)
        e = queue.get()
        assert e
        assert e.as_net.tank.net_id == p.as_net.tank.net_id
        assert e.direction == p.direction
        assert e.flags == p.flags

        with pytest.raises(Empty):
            queue.get_nowait()

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)
        assert not is_port_in_use(b._pull_port)


class ExtensionMatch(Extension):
    def __init__(self) -> None:
        super().__init__(
            name="match",
            interest=[
                Interest(
                    interest=INTEREST_STATE,
                    state=InterestState(
                        where=[
                            self.tank_flags.bit_test(self.uint(TankFlags.PUNCH)),
                        ]
                    ),
                    blocking_mode=BLOCKING_MODE_BLOCK,
                    direction=DIRECTION_CLIENT_TO_SERVER,
                ),
            ],
        )

    def process(self, event: PendingPacket) -> PendingPacket | None:
        pkt = NetPacket.deserialize(event.buf)
        pkt.tank.net_id += 1

        event.buf = pkt.serialize()
        return self.forward(event)

    def destroy(self) -> None:
        pass


def test_match() -> None:
    b = Broker()
    b.start()

    try:
        ext = ExtensionMatch()
        assert ext.start().wait_true(5)

        p = PreparedPacket(
            NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1)),
            DIRECTION_CLIENT_TO_SERVER,
            ENetPacketFlag.NONE,
        )
        res = b.process_event(p)
        assert not res

        p = PreparedPacket(
            NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1, flags=TankFlags.PUNCH)),
            DIRECTION_CLIENT_TO_SERVER,
            ENetPacketFlag.NONE,
        )
        res = b.process_event(p)
        assert res
        assert PreparedPacket.from_pending(res[0]).as_net.tank.net_id == 2

        p = PreparedPacket(
            NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1, flags=TankFlags.PUNCH | TankFlags.FACING_LEFT)),
            DIRECTION_CLIENT_TO_SERVER,
            ENetPacketFlag.NONE,
        )
        res = b.process_event(p)
        assert res
        assert PreparedPacket.from_pending(res[0]).as_net.tank.net_id == 2

        p = PreparedPacket(
            NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1, flags=TankFlags.FACING_LEFT)),
            DIRECTION_CLIENT_TO_SERVER,
            ENetPacketFlag.NONE,
        )
        res = b.process_event(p)
        assert not res

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)
        assert not is_port_in_use(b._pull_port)


def test_non_block_pass_should_cancel() -> None:
    b = Broker()
    b.start()

    try:
        ext = ExtensionPassNonBlock("pass")
        assert ext.start().wait_true(5)

        ress: list[PreparedPacket] = []

        def set_res(pkt: PreparedPacket) -> None:
            nonlocal ress
            ress.append(pkt)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE), PacketCallback(any=set_res))

        time.sleep(1)
        assert not ress

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_non_block_finish_should_continue() -> None:
    b = Broker()
    b.start()

    try:
        ext = ExtensionFinishNonBlock("finish")
        assert ext.start().wait_true(5)

        ress: list[PreparedPacket] = []

        def set_res(pkt: PreparedPacket) -> None:
            nonlocal ress
            ress.append(pkt)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE), PacketCallback(any=set_res))

        while not ress:
            time.sleep(0.1)

        assert ress[0].direction.value == DIRECTION_UNSPECIFIED
        assert ress[0].flags == ENetPacketFlag.NONE
        assert ress[0].as_net.tank.net_id == 1

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_non_block_cancel_should_cancel() -> None:
    b = Broker()
    b.start()

    try:
        ext = ExtensionCancelNonBlock("cancel")
        assert ext.start().wait_true(5)

        ress: list[PreparedPacket] = []

        def set_res(pkt: PreparedPacket) -> None:
            nonlocal ress
            ress.append(pkt)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE), PacketCallback(any=set_res))

        time.sleep(1)
        assert not ress

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


class ExtensionTileChangeRequest(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(
            name=name,
            interest=[
                Interest(
                    interest=INTEREST_TILE_CHANGE_REQUEST,
                    blocking_mode=BLOCKING_MODE_BLOCK,
                    direction=DIRECTION_CLIENT_TO_SERVER,
                ),
            ],
        )

    def process(self, event: PendingPacket) -> PendingPacket | None:
        pass

    def destroy(self) -> None:
        pass


def test_match_tile_change_request() -> None:
    b = Broker()
    b.start()

    try:
        ext = ExtensionTileChangeRequest("tilechange")
        assert ext.start().wait_true(5)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert not res

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.NONE))
        assert not res

        pkt = NetPacket(type=NetType.GAME_MESSAGE, data=StrKV([[b"something", b"123"]]))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert not res

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(type=TankType.ITEM_ACTIVATE_OBJECT_REQUEST))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert not res

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(type=TankType.ITEM_ACTIVATE_OBJECT_REQUEST))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.NONE))
        assert not res

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(type=TankType.TILE_CHANGE_REQUEST))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.NONE))
        assert res

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(type=TankType.TILE_CHANGE_REQUEST))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert not res

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


class ExtensionTileMatchAnyDirection(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(
            name=name,
            interest=[
                Interest(
                    interest=INTEREST_TANK_PACKET,
                    blocking_mode=BLOCKING_MODE_BLOCK,
                    direction=DIRECTION_UNSPECIFIED,
                ),
            ],
        )

    def process(self, event: PendingPacket) -> PendingPacket | None:
        pass

    def destroy(self) -> None:
        pass


def test_match_any_direction() -> None:
    b = Broker()
    b.start()

    try:
        ext = ExtensionTileMatchAnyDirection("match_any")
        assert ext.start().wait_true(5)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert res

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.NONE))
        assert res

        pkt = NetPacket(type=NetType.GAME_MESSAGE, data=StrKV([[b"something", b"123"]]))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert not res

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(type=TankType.ITEM_ACTIVATE_OBJECT_REQUEST))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert res

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(type=TankType.ITEM_ACTIVATE_OBJECT_REQUEST))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.NONE))
        assert res

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(type=TankType.TILE_CHANGE_REQUEST))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.NONE))
        assert res

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(type=TankType.TILE_CHANGE_REQUEST))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert res

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


class ExtensionBlockGazette(Extension):
    def __init__(self) -> None:
        super().__init__(
            name="block_gazette",
            interest=[
                Interest(
                    interest=INTEREST_CALL_FUNCTION,
                    blocking_mode=BLOCKING_MODE_BLOCK,
                    direction=DIRECTION_SERVER_TO_CLIENT,
                    call_function=InterestCallFunction(
                        where=[
                            self.variant[0] == b"OnDialogRequest",
                            self.variant[1].contains(b"The Growtopia Gazette"),
                        ]
                    ),
                ),
            ],
        )

    def process(self, event: PendingPacket) -> PendingPacket | None:
        return self.forward(
            PendingPacket(
                buf=NetPacket(
                    type=NetType.GENERIC_TEXT,
                    data=StrKV(
                        [
                            [b"action", b"dialog_return"],
                            [b"dialog_name", b"gazette"],
                            [b"buttonClicked", b"banner"],
                        ]
                    )
                    .append_nl()
                    .append_nl(),
                ).serialize(),
                direction=DIRECTION_CLIENT_TO_SERVER,
                packet_flags=ENetPacketFlag.RELIABLE,
            )
        )

    def destroy(self) -> None:
        pass


def test_variant_match_and_extension_block_gazette() -> None:
    b = Broker()
    b.start()

    try:
        ext = ExtensionBlockGazette()
        assert ext.start().wait_true(5)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert not res

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.NONE))
        assert not res

        pkt = NetPacket(type=NetType.GAME_MESSAGE, data=StrKV([[b"something", b"123"]]))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert not res

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(type=TankType.ITEM_ACTIVATE_OBJECT_REQUEST))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert not res

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(type=TankType.ITEM_ACTIVATE_OBJECT_REQUEST))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.NONE))
        assert not res

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(type=TankType.TILE_CHANGE_REQUEST))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.NONE))
        assert not res

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(type=TankType.TILE_CHANGE_REQUEST))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert not res

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(type=TankType.CALL_FUNCTION))
        res = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert not res

        pkt = NetPacket(
            type=NetType.TANK_PACKET,
            data=TankPacket(
                type=TankType.CALL_FUNCTION,
                flags=TankFlags.EXTENDED,
                extended_data=Variant(
                    [Variant.vstr(b"OnDialogRequest")],
                ).serialize(),
            ),
        )
        res = b.process_event(PreparedPacket(pkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert not res

        original_pkt_raw = b"\x04\x00\x00\x00\x01\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x8f\x1c\x00\x00\x02\x00\x02\x0f\x00\x00\x00OnDialogRequest\x01\x02s\x1c\x00\x00\xef\xbb\xbfset_default_color|`o\nadd_label_with_icon|big|`wThe Growtopia Gazette``|left|5016|\nadd_spacer|small|\nadd_image_button|banner|interface/large/wtr_lvl11_xualqu.rttex|bannerlayout||\nadd_spacer|small|\nadd_textbox|`wDecember 25th: `5Merry Christmas!``|left|\nadd_spacer|small|\nadd_image_button|iotm_layout|interface/large/gazette/gazette_3columns_feature_btn11.rttex|3imageslayout|OPENSTORE|main/rt_grope_brand_bundle01|\nadd_image_button|iotm_layout|interface/large/gazette/gazette_3columns_feature_btn12.rttex|3imageslayout|OPENSTORE|main/gems_bundle06|\nadd_image_button|iotm_layout|interface/large/gazette/gazette_3columns_feature_btn13.rttex|3imageslayout|OPENSTORE|main/gems_bundle05|\nadd_spacer|small|\nadd_textbox|Merry Christmas, Growtopians! The holiday magic is here, and we've got something truly special just for you, the `8WinterFest Big Day Bundle``! Available only for `2the next 24 hours``, check it out in the Store now!|left|\nadd_spacer|small|\nadd_textbox|This year's `2WinterFest`` rewards are bigger, brighter, and cooler than ever! Spend your `1Royal Winter Seals`` across all our `2Rewards Branches`` and work your way up to unlocking festive goodies galore! And because it's the season of giving, we've added a `2brand new fifth rewards branch`` packed with fresh rewards! The final reward of this new branch is the ultimate flex, the brand new `2Royal Winter Title``, perfect for spreading that holiday spirit wherever you go!|left|\nadd_spacer|small|\nadd_textbox|`cWinterfest Bingo`` is also making a merry return! Complete your `2Bingo Card`` by collecting items from various `2WinterFest`` activities and claim rewards along the way! Not vibing with the prizes on your card? No worries, you can reset your `2Bingo Card`` to roll for rewards that are more your style! After all, it's your holiday wish list!|left|\nadd_spacer|small|\nadd_textbox|`wGROWCH's`` heart has officially grown to its fullest and it's safe to say he's feeling extra warm and fuzzy (don't tell him we said that)! While his heart can't grow any bigger, you can still keep the holiday spirit alive by gifting `wGROWCH`` if you'd like, because spreading cheer is always in season, even when the heart is already full!|left|\nadd_spacer|small|\nadd_textbox|Learn more about the coldest event of the year by reading ThePsyborg's Dev Diary!|left|\nadd_spacer|small|\nadd_image_button|gazette_GrowtopiaForumUpdates|interface/large/gazette/gazette_3columns_forum_btn01.rttex|3imageslayout|https://www.growtopiagame.com/forums/forum/general/announcements/7274287-winterfest-2025|Do you want to open the Growtopia Forum and check out the latest update?|\nadd_layout_spacer|3imageslayout|\nadd_layout_spacer|3imageslayout|\nadd_spacer|small|\nadd_textbox|Take things to the next level and zoom through the Growtopian worlds with the December Grow Pass items!|left|\nadd_spacer|small|\nadd_label_with_icon|small|Item of the Season: `2Maverick Armor``|left|24|\nadd_label_with_icon|small|Royal Item of the Season: `2Royal Maverick Armor``|left|24|\nadd_label_with_icon|small|Subscriber Item: `8Molten Mining Tool`` chosen by BTKY!|left|24|\nadd_spacer|small|\nadd_textbox|Please make sure to check our announcement to find out more!|left|\nadd_spacer|small|\nadd_image_button|gazette_GrowtopiaForumUpdates|interface/large/gazette/gazette_3columns_forum_btn01.rttex|3imageslayout|https://www.growtopiagame.com/forums/forum/general/announcements/7274284-december-update-2025|Do you want to open the Growtopia Forum and check out the latest update?|\nadd_layout_spacer|3imageslayout|\nadd_layout_spacer|3imageslayout|\nadd_spacer|small|\nadd_textbox|The Growtopia survey for the November Update is still open! By completing the survey, you will receive `22 Growtokens`` if you have Advanced Account Protection enabled. Complete the survey and claim your reward on your mobile device to let us know what you think!|left|\nadd_spacer|small|\nadd_url_button|survey|`wGive us your opinion!``|noflags|OPENSURVEY||\nadd_spacer|small|\nadd_textbox|Don't forget to join our `2Official Growtopia Discord Server`` on `2discord.gg/growtopia`` or click the link below!|left|\nadd_spacer|small|\nadd_image_button|iotm_layout|interface/large/gazette/gazette_3columns_community_btn01.rttex|3imageslayout|OPENCOMMUNITY|community_growtorials/TUTORIAL_DOORS|\nadd_image_button|gazette_DiscordServer|interface/large/gazette/gazette_3columns_community_btn04.rttex|3imageslayout|https://discord.gg/growtopia|Would you like to join our Discord Server?|\nadd_image_button|gazette_Youtube|interface/large/gazette/gazette_3columns_community_btn03.rttex|3imageslayout|https://tiktok.com/@growtopia|Would you like to open this in TikTok?|\nadd_spacer|small|\nadd_textbox|Visit our Social Media pages for more Content!|left|\nadd_spacer|small|\nadd_image_button|gazette_DiscordServer|interface/large/gazette/gazette_5columns_social_btn01.rttex|7imageslayout20|https://discord.gg/growtopia|Would you like to join our Discord Server?|\nadd_image_button|gazette_Instagram|interface/large/gazette/gazette_5columns_social_btn02.rttex|7imageslayout20|https://www.instagram.com/growtopia|Would you like to open this in Instagram?|\nadd_image_button|gazette_TikTok|interface/large/gazette/gazette_5columns_social_btn03.rttex|7imageslayout20|https://tiktok.com/@growtopia|Would you like to open this in TikTok?|\nadd_image_button|gazette_Twitch|interface/large/gazette/gazette_5columns_social_btn04.rttex|7imageslayout20|https://www.twitch.tv/growtopiagameofficial|Would you like to open this in Twitch?|\nadd_image_button|gazette_Twitter|interface/large/gazette/gazette_5columns_social_btn06.rttex|7imageslayout20|https://twitter.com/growtopiagame|Would you like to open this in X?|\nadd_image_button|gazette_Youtube|interface/large/gazette/gazette_5columns_btn04.rttex|7imageslayout20|https://www.youtube.com/growtopia_official|Would you like to open this in Youtube?|\nadd_image_button|gazette_Facebook|interface/large/gazette/gazette_5columns_btn05.rttex|7imageslayout20|https://www.facebook.com/growtopia|Would you like to open this in Facebook?|\nadd_spacer|small|\nadd_image_button|gazette_PrivacyPolicy|interface/large/gazette/gazette_3columns_policy_btn02.rttex|3imageslayout|https://legal.ubi.com/privacypolicy/en-INTL|Do you want to read the Privacy Policy?|\nadd_image_button|gazette_GrowtopianCode|interface/large/gazette/gazette_3columns_policy_btn01.rttex|3imageslayout|https://ubisoft-mobile.helpshift.com/hc/en/26-growtopia/section/337-the-growtopian-code/|Do you want to read the Growtopian Code?|\nadd_image_button|gazette_TermsofUse|interface/large/gazette/gazette_3columns_policy_btn03.rttex|3imageslayout|https://legal.ubi.com/termsofuse/en-INTL|Do you want to read the Terms of Use?|\nadd_spacer|small|\nadd_spacer|small|\n\nadd_quick_exit|add_spacer|small|\nadd_url_button|gazette_visitforum|`wVisit Growtopia Forums``|noflags|https://www.growtopiagame.com/forums|Visit the Growtopia forums?|0|0|\nadd_spacer|small|\nadd_url_button||`wWOTD: `1SNOWMANPRESENT`` by `#PR4GOS````|NOFLAGS|OPENWORLD|SNOWMANPRESENT|0|0|\nadd_spacer|small|\nadd_url_button||`wVOTW: `1A Wonderful Gift - Growtopia Animation!``|NOFLAGS|https://www.youtube.com/watch?v=C3mdPmVzbdQ|Watch 'A Wonderful Gift - Growtopia Animation!' by amwy on YouTube?|0|0|\nset_survey_enabled|1\nend_dialog|gazette||OK|\n\x00"
        pkt = NetPacket.deserialize(original_pkt_raw)
        res = b.process_event(PreparedPacket(pkt, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.NONE))
        assert res

        processed, cancelled = res
        assert not cancelled
        prepared = PreparedPacket.from_pending(processed)
        assert prepared.direction.value == DIRECTION_CLIENT_TO_SERVER
        assert prepared.flags == ENetPacketFlag.RELIABLE
        assert prepared.as_net.type == NetType.GENERIC_TEXT
        assert prepared.as_raw == b"\x02\x00\x00\x00action|dialog_return\ndialog_name|gazette\nbuttonClicked|banner\n\n\x00"

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_utility_extension() -> None:
    q: Queue[PreparedPacket | None] = Queue()
    b = Broker(q)
    b.start()

    try:
        ext = UtilityExtension()
        assert ext.start().wait_true(5)

        # gazette dialog
        req_buf = b"\x04\x00\x00\x00\x01\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x8f\x1c\x00\x00\x02\x00\x02\x0f\x00\x00\x00OnDialogRequest\x01\x02s\x1c\x00\x00\xef\xbb\xbfset_default_color|`o\nadd_label_with_icon|big|`wThe Growtopia Gazette``|left|5016|\nadd_spacer|small|\nadd_image_button|banner|interface/large/wtr_lvl11_xualqu.rttex|bannerlayout||\nadd_spacer|small|\nadd_textbox|`wDecember 25th: `5Merry Christmas!``|left|\nadd_spacer|small|\nadd_image_button|iotm_layout|interface/large/gazette/gazette_3columns_feature_btn11.rttex|3imageslayout|OPENSTORE|main/rt_grope_brand_bundle01|\nadd_image_button|iotm_layout|interface/large/gazette/gazette_3columns_feature_btn12.rttex|3imageslayout|OPENSTORE|main/gems_bundle06|\nadd_image_button|iotm_layout|interface/large/gazette/gazette_3columns_feature_btn13.rttex|3imageslayout|OPENSTORE|main/gems_bundle05|\nadd_spacer|small|\nadd_textbox|Merry Christmas, Growtopians! The holiday magic is here, and we've got something truly special just for you, the `8WinterFest Big Day Bundle``! Available only for `2the next 24 hours``, check it out in the Store now!|left|\nadd_spacer|small|\nadd_textbox|This year's `2WinterFest`` rewards are bigger, brighter, and cooler than ever! Spend your `1Royal Winter Seals`` across all our `2Rewards Branches`` and work your way up to unlocking festive goodies galore! And because it's the season of giving, we've added a `2brand new fifth rewards branch`` packed with fresh rewards! The final reward of this new branch is the ultimate flex, the brand new `2Royal Winter Title``, perfect for spreading that holiday spirit wherever you go!|left|\nadd_spacer|small|\nadd_textbox|`cWinterfest Bingo`` is also making a merry return! Complete your `2Bingo Card`` by collecting items from various `2WinterFest`` activities and claim rewards along the way! Not vibing with the prizes on your card? No worries, you can reset your `2Bingo Card`` to roll for rewards that are more your style! After all, it's your holiday wish list!|left|\nadd_spacer|small|\nadd_textbox|`wGROWCH's`` heart has officially grown to its fullest and it's safe to say he's feeling extra warm and fuzzy (don't tell him we said that)! While his heart can't grow any bigger, you can still keep the holiday spirit alive by gifting `wGROWCH`` if you'd like, because spreading cheer is always in season, even when the heart is already full!|left|\nadd_spacer|small|\nadd_textbox|Learn more about the coldest event of the year by reading ThePsyborg's Dev Diary!|left|\nadd_spacer|small|\nadd_image_button|gazette_GrowtopiaForumUpdates|interface/large/gazette/gazette_3columns_forum_btn01.rttex|3imageslayout|https://www.growtopiagame.com/forums/forum/general/announcements/7274287-winterfest-2025|Do you want to open the Growtopia Forum and check out the latest update?|\nadd_layout_spacer|3imageslayout|\nadd_layout_spacer|3imageslayout|\nadd_spacer|small|\nadd_textbox|Take things to the next level and zoom through the Growtopian worlds with the December Grow Pass items!|left|\nadd_spacer|small|\nadd_label_with_icon|small|Item of the Season: `2Maverick Armor``|left|24|\nadd_label_with_icon|small|Royal Item of the Season: `2Royal Maverick Armor``|left|24|\nadd_label_with_icon|small|Subscriber Item: `8Molten Mining Tool`` chosen by BTKY!|left|24|\nadd_spacer|small|\nadd_textbox|Please make sure to check our announcement to find out more!|left|\nadd_spacer|small|\nadd_image_button|gazette_GrowtopiaForumUpdates|interface/large/gazette/gazette_3columns_forum_btn01.rttex|3imageslayout|https://www.growtopiagame.com/forums/forum/general/announcements/7274284-december-update-2025|Do you want to open the Growtopia Forum and check out the latest update?|\nadd_layout_spacer|3imageslayout|\nadd_layout_spacer|3imageslayout|\nadd_spacer|small|\nadd_textbox|The Growtopia survey for the November Update is still open! By completing the survey, you will receive `22 Growtokens`` if you have Advanced Account Protection enabled. Complete the survey and claim your reward on your mobile device to let us know what you think!|left|\nadd_spacer|small|\nadd_url_button|survey|`wGive us your opinion!``|noflags|OPENSURVEY||\nadd_spacer|small|\nadd_textbox|Don't forget to join our `2Official Growtopia Discord Server`` on `2discord.gg/growtopia`` or click the link below!|left|\nadd_spacer|small|\nadd_image_button|iotm_layout|interface/large/gazette/gazette_3columns_community_btn01.rttex|3imageslayout|OPENCOMMUNITY|community_growtorials/TUTORIAL_DOORS|\nadd_image_button|gazette_DiscordServer|interface/large/gazette/gazette_3columns_community_btn04.rttex|3imageslayout|https://discord.gg/growtopia|Would you like to join our Discord Server?|\nadd_image_button|gazette_Youtube|interface/large/gazette/gazette_3columns_community_btn03.rttex|3imageslayout|https://tiktok.com/@growtopia|Would you like to open this in TikTok?|\nadd_spacer|small|\nadd_textbox|Visit our Social Media pages for more Content!|left|\nadd_spacer|small|\nadd_image_button|gazette_DiscordServer|interface/large/gazette/gazette_5columns_social_btn01.rttex|7imageslayout20|https://discord.gg/growtopia|Would you like to join our Discord Server?|\nadd_image_button|gazette_Instagram|interface/large/gazette/gazette_5columns_social_btn02.rttex|7imageslayout20|https://www.instagram.com/growtopia|Would you like to open this in Instagram?|\nadd_image_button|gazette_TikTok|interface/large/gazette/gazette_5columns_social_btn03.rttex|7imageslayout20|https://tiktok.com/@growtopia|Would you like to open this in TikTok?|\nadd_image_button|gazette_Twitch|interface/large/gazette/gazette_5columns_social_btn04.rttex|7imageslayout20|https://www.twitch.tv/growtopiagameofficial|Would you like to open this in Twitch?|\nadd_image_button|gazette_Twitter|interface/large/gazette/gazette_5columns_social_btn06.rttex|7imageslayout20|https://twitter.com/growtopiagame|Would you like to open this in X?|\nadd_image_button|gazette_Youtube|interface/large/gazette/gazette_5columns_btn04.rttex|7imageslayout20|https://www.youtube.com/growtopia_official|Would you like to open this in Youtube?|\nadd_image_button|gazette_Facebook|interface/large/gazette/gazette_5columns_btn05.rttex|7imageslayout20|https://www.facebook.com/growtopia|Would you like to open this in Facebook?|\nadd_spacer|small|\nadd_image_button|gazette_PrivacyPolicy|interface/large/gazette/gazette_3columns_policy_btn02.rttex|3imageslayout|https://legal.ubi.com/privacypolicy/en-INTL|Do you want to read the Privacy Policy?|\nadd_image_button|gazette_GrowtopianCode|interface/large/gazette/gazette_3columns_policy_btn01.rttex|3imageslayout|https://ubisoft-mobile.helpshift.com/hc/en/26-growtopia/section/337-the-growtopian-code/|Do you want to read the Growtopian Code?|\nadd_image_button|gazette_TermsofUse|interface/large/gazette/gazette_3columns_policy_btn03.rttex|3imageslayout|https://legal.ubi.com/termsofuse/en-INTL|Do you want to read the Terms of Use?|\nadd_spacer|small|\nadd_spacer|small|\n\nadd_quick_exit|add_spacer|small|\nadd_url_button|gazette_visitforum|`wVisit Growtopia Forums``|noflags|https://www.growtopiagame.com/forums|Visit the Growtopia forums?|0|0|\nadd_spacer|small|\nadd_url_button||`wWOTD: `1SNOWMANPRESENT`` by `#PR4GOS````|NOFLAGS|OPENWORLD|SNOWMANPRESENT|0|0|\nadd_spacer|small|\nadd_url_button||`wVOTW: `1A Wonderful Gift - Growtopia Animation!``|NOFLAGS|https://www.youtube.com/watch?v=C3mdPmVzbdQ|Watch 'A Wonderful Gift - Growtopia Animation!' by amwy on YouTube?|0|0|\nset_survey_enabled|1\nend_dialog|gazette||OK|\n\x00"
        req = NetPacket.deserialize(req_buf)
        res = b.process_event(PreparedPacket(req, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))
        assert res
        pkt, cancelled = res
        assert not cancelled
        prepared = PreparedPacket.from_pending(pkt)
        assert prepared.direction.value == DIRECTION_CLIENT_TO_SERVER
        assert prepared.flags == ENetPacketFlag.RELIABLE
        assert prepared.as_net.type == NetType.GENERIC_TEXT
        assert prepared.as_raw == b"\x02\x00\x00\x00action|dialog_return\ndialog_name|gazette\nbuttonClicked|banner\n\n\x00"
        verify(prepared.as_raw, key="gazette_block")

        # player dropping, normal because fast drop is disabled
        req_buf = b"\x04\x00\x00\x00\x01\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xdf\x00\x00\x00\x02\x00\x02\x0f\x00\x00\x00OnDialogRequest\x01\x02\xc3\x00\x00\x00set_default_color|`o\nadd_label_with_icon|big|`wDrop Water Bucket``|left|822|\nadd_textbox|How many to drop?|left|\nadd_text_input|count||17|5|\nembed_data|itemID|822\nend_dialog|drop_item|Cancel|OK|\n\x00"
        req = NetPacket.deserialize(req_buf)
        res = b.process_event(PreparedPacket(req, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))
        assert res
        pkt, cancelled = res
        assert not cancelled
        assert pkt.buf == req_buf

        # toggle fast drop
        req_buf = b"\x02\x00\x00\x00action|input\n|text|/fd\x00"
        req = NetPacket.deserialize(req_buf)
        res = b.process_event(PreparedPacket(req, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.RELIABLE))
        assert res
        pkt, cancelled = res
        assert cancelled
        assert ext.fast_drop == True
        # console log
        res = q.get(timeout=1.0)
        assert res and res.as_net.type == NetType.TANK_PACKET
        verify(res.as_raw, key="fast_drop_console_log")
        # player dropping item
        req_buf = b"\x04\x00\x00\x00\x01\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xdf\x00\x00\x00\x02\x00\x02\x0f\x00\x00\x00OnDialogRequest\x01\x02\xc3\x00\x00\x00set_default_color|`o\nadd_label_with_icon|big|`wDrop Water Bucket``|left|822|\nadd_textbox|How many to drop?|left|\nadd_text_input|count||17|5|\nembed_data|itemID|822\nend_dialog|drop_item|Cancel|OK|\n\x00"
        req = NetPacket.deserialize(req_buf)
        res = b.process_event(PreparedPacket(req, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))
        assert res
        pkt, cancelled = res
        assert cancelled
        pkt = q.get(timeout=1.0)
        assert pkt
        assert pkt.direction.value == DIRECTION_CLIENT_TO_SERVER
        assert pkt.flags == ENetPacketFlag.RELIABLE
        assert pkt.as_net.type == NetType.GENERIC_TEXT
        assert pkt.as_net.serialize() == b"\x02\x00\x00\x00action|dialog_return\ndialog_name|drop_item\nitemID|822|\ncount|17\n\x00"
        verify(pkt.as_raw, key="fast_drop")

        # player exiting to main menu, it should not do anything
        req_buf = b"\x03\x00\x00\x00action|quit_to_exit\x00"
        req = NetPacket.deserialize(req_buf)
        res = b.process_event(PreparedPacket(req, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.RELIABLE))
        assert res
        pkt, cancelled = res
        assert not cancelled
        prepared = PreparedPacket.from_pending(pkt)
        assert prepared.as_raw == req_buf
        verify(prepared.as_raw, key="quit_to_exit")
        assert ext.should_block == False

        # /exit command
        req_buf = b"\x02\x00\x00\x00action|input\n|text|/exit\x00"
        req = NetPacket.deserialize(req_buf)
        res = b.process_event(PreparedPacket(req, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.RELIABLE))
        assert res
        pkt, cancelled = res
        assert cancelled
        assert ext.should_block == True
        res = q.get(timeout=1.0)
        assert res
        assert res.direction.value == DIRECTION_CLIENT_TO_SERVER
        assert res.flags == ENetPacketFlag.RELIABLE
        assert res.as_net.type == NetType.GAME_MESSAGE
        assert res.as_net.serialize() == b"\x03\x00\x00\x00action|quit_to_exit\x00"
        assert res.as_raw == b"\x03\x00\x00\x00action|quit_to_exit\x00"
        verify(res.as_raw, key="exit_command")

        # simulate client sending extra quit_to_exit
        time.sleep(0.5)
        req_buf = b"\x03\x00\x00\x00action|quit_to_exit\x00"
        req = NetPacket.deserialize(req_buf)
        res = b.process_event(PreparedPacket(req, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.RELIABLE))
        assert res
        pkt, cancelled = res
        assert cancelled
        assert ext.should_block == False

        # only the first one will be blocked
        req_buf = b"\x03\x00\x00\x00action|quit_to_exit\x00"
        req = NetPacket.deserialize(req_buf)
        res = b.process_event(PreparedPacket(req, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.RELIABLE))
        assert res
        pkt, cancelled = res
        assert not cancelled
        assert ext.should_block == False
        pkt = PreparedPacket.from_pending(pkt)
        assert pkt.as_raw == req_buf
        verify(pkt.as_raw, key="quit_to_exit2")

        # warp
        req_buf = b"\x02\x00\x00\x00action|input\n|text|/warp MALISE\x00"
        req = NetPacket.deserialize(req_buf)
        res = b.process_event(PreparedPacket(req, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.RELIABLE))
        assert res
        pkt, cancelled = res
        assert cancelled
        ext.should_block = True
        # console log
        res = q.get(timeout=1.0)
        assert res and res.as_net.type == NetType.TANK_PACKET
        verify(res.as_raw, key="warp_seq0")
        # quit packet
        res = q.get(timeout=1.0)
        assert res
        assert res.as_net.type == NetType.GAME_MESSAGE
        assert res.direction.value == DIRECTION_CLIENT_TO_SERVER
        assert res.flags == ENetPacketFlag.RELIABLE
        assert res.as_raw == b"\x03\x00\x00\x00action|quit_to_exit\x00"
        verify(res.as_raw, key="warp_seq1")
        time.sleep(0.5)
        # client sending extra quit_to_exit
        req_buf = b"\x03\x00\x00\x00action|quit_to_exit\x00"
        req = NetPacket.deserialize(req_buf)
        res = b.process_event(PreparedPacket(req, DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.RELIABLE))
        assert res
        pkt, cancelled = res
        assert cancelled
        assert ext.should_block == False
        # join_request packet
        time.sleep(0.5)
        assert q.qsize() == 0  # nothing should come because we didnt send the exited packet yet
        # try sending bogus packet
        req_buf = b'\x04\x00\x00\x00\x01\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00]\x02\x00\x00\x03\x00\x02\x18\x00\x00\x00OnRequestWorldSelectMena\x01\x022\x02\x00\x00add_filter|\nadd_heading|Top Worlds<ROW2>|\nadd_floater|START|START|0|0.5|3529161471\nadd_heading|My Worlds<CR>|\nadd_floater|FOOBAR1234|0|0.5|2147418367\nadd_heading|Recently Visited Worlds<CR>|\nadd_floater|FOOBAR1234|0|0.5|3417414143\nadd_floater|MALISE|0|0.5|3417414143\nadd_floater|1234TESTS|0|0.5|3417414143\nadd_floater|AUCS|37|0.55|3417414143\nadd_floater|BUYPLOW|0|0.5|3417414143\nadd_floater|GROWCH|0|0.5|3417414143\nadd_floater|QWERTY|0|0.5|3417414143\nadd_floater|GYUIOOOOP|0|0.5|3417414143\nadd_floater|SURG|44|0.55|3417414143\nadd_floater|BLOCKU|0|0.5|3417414143\n\x02\t\x00\x00\x00\x00\x00'
        req = NetPacket.deserialize(req_buf)
        res = b.process_event(PreparedPacket(req, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))
        assert not res
        time.sleep(0.5)
        assert q.qsize() == 0  # nothing should come because we didnt send the exited packet yet
        # send exited packet
        req_buf = b'\x04\x00\x00\x00\x01\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00]\x02\x00\x00\x03\x00\x02\x18\x00\x00\x00OnRequestWorldSelectMenu\x01\x022\x02\x00\x00add_filter|\nadd_heading|Top Worlds<ROW2>|\nadd_floater|START|START|0|0.5|3529161471\nadd_heading|My Worlds<CR>|\nadd_floater|FOOBAR1234|0|0.5|2147418367\nadd_heading|Recently Visited Worlds<CR>|\nadd_floater|FOOBAR1234|0|0.5|3417414143\nadd_floater|MALISE|0|0.5|3417414143\nadd_floater|1234TESTS|0|0.5|3417414143\nadd_floater|AUCS|37|0.55|3417414143\nadd_floater|BUYPLOW|0|0.5|3417414143\nadd_floater|GROWCH|0|0.5|3417414143\nadd_floater|QWERTY|0|0.5|3417414143\nadd_floater|GYUIOOOOP|0|0.5|3417414143\nadd_floater|SURG|44|0.55|3417414143\nadd_floater|BLOCKU|0|0.5|3417414143\n\x02\t\x00\x00\x00\x00\x00'
        req = NetPacket.deserialize(req_buf)
        res = b.process_event(PreparedPacket(req, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))
        assert not res
        res = q.get(timeout=2.0)
        assert res
        assert res.as_net.type == NetType.GAME_MESSAGE
        assert res.direction.value == DIRECTION_CLIENT_TO_SERVER
        assert res.flags == ENetPacketFlag.RELIABLE
        assert res.as_raw == b"\x03\x00\x00\x00action|join_request\nname|MALISE\ninvitedWorld|0\n\x00"
        verify(res.as_raw, key="warp_seq3")
        assert ext.should_block == False

        assert ext.stop().wait_true(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


class MatchVariant(Extension):
    def __init__(self) -> None:
        super().__init__(
            name="match",
            interest=[
                Interest(
                    interest=INTEREST_CALL_FUNCTION,
                    blocking_mode=BLOCKING_MODE_BLOCK,
                    direction=DIRECTION_SERVER_TO_CLIENT,
                    call_function=InterestCallFunction(
                        where=[
                            self.variant[0] == b"Test",
                            self.variant[1] == b"Test2",
                        ]
                    ),
                ),
            ],
        )

    def process(self, event: PendingPacket) -> PendingPacket | None:
        pass

    def destroy(self) -> None:
        pass


class MatchVariantContains(Extension):
    def __init__(self) -> None:
        super().__init__(
            name="match",
            interest=[
                Interest(
                    interest=INTEREST_CALL_FUNCTION,
                    blocking_mode=BLOCKING_MODE_BLOCK,
                    direction=DIRECTION_SERVER_TO_CLIENT,
                    call_function=InterestCallFunction(
                        where=[
                            self.variant[0] == b"Test",
                            self.variant[1].contains(b"Hello World"),
                        ]
                    ),
                ),
            ],
        )

    def process(self, event: PendingPacket) -> PendingPacket | None:
        pass

    def destroy(self) -> None:
        pass


def test_match_variant_contains() -> None:
    b = Broker()
    b.start()

    try:
        ext = MatchVariantContains()
        assert ext.start().wait_true(5)

        req = NetPacket(NetType.TANK_PACKET, TankPacket(flags=TankFlags.EXTENDED, extended_data=Variant([Variant.vstr(b"Test")]).serialize()))
        res = b.process_event(PreparedPacket(req, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))
        assert not res

        req = NetPacket(NetType.TANK_PACKET, TankPacket(flags=TankFlags.EXTENDED, extended_data=Variant([Variant.vstr(b"Test"), Variant.vstr(b"Test")]).serialize()))
        res = b.process_event(PreparedPacket(req, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))
        assert not res

        req = NetPacket(
            NetType.TANK_PACKET, TankPacket(TankType.CALL_FUNCTION, flags=TankFlags.EXTENDED, extended_data=Variant([Variant.vstr(b"Test"), Variant.vstr(b"Test2")]).serialize())
        )
        res = b.process_event(PreparedPacket(req, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))
        assert not res

        req = NetPacket(
            NetType.TANK_PACKET, TankPacket(TankType.CALL_FUNCTION, flags=TankFlags.EXTENDED, extended_data=Variant([Variant.vstr(b"Test"), Variant.vstr(b"Hello")]).serialize())
        )
        res = b.process_event(PreparedPacket(req, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))
        assert not res

        req = NetPacket(
            NetType.TANK_PACKET,
            TankPacket(
                TankType.CALL_FUNCTION,
                flags=TankFlags.EXTENDED,
                extended_data=Variant([Variant.vstr(b"Test"), Variant.vstr(b"jaiwodjaiwjdoi Hello World oaiwjdoaiwjdoiaww")]).serialize(),
            ),
        )
        res = b.process_event(PreparedPacket(req, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))
        assert res
        pkt, cancelled = res
        assert not cancelled

        req = NetPacket(
            NetType.TANK_PACKET,
            TankPacket(
                TankType.CALL_FUNCTION,
                flags=TankFlags.EXTENDED,
                extended_data=Variant([Variant.vstr(b"Test"), Variant.vstr(b"jaiwodjaiwjdoi ello World oaiwjdoaiwjdoiaww")]).serialize(),
            ),
        )
        res = b.process_event(PreparedPacket(req, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))
        assert not res
    except:
        raise
    finally:
        assert ext.stop().wait_true(5)
        b.stop()
        assert not is_port_in_use(6712)
