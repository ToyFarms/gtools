from queue import Queue
import socket
import time
from google.protobuf.any_pb2 import Any
import pytest

from gtools.core.growtopia.strkv import StrKV
from gtools.protogen.op_pb2 import OP_EQ, BinOp
from gtools.protogen.strkv_pb2 import Clause, FindCol, FindRow, Query
from gtools.proxy.extension.builtin.fast_drop import FastDropExtension
from tests import verify

from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket, TankPacket
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    DIRECTION_UNSPECIFIED,
    INTEREST_GENERIC_TEXT,
    INTEREST_TANK_PACKET,
    Interest,
    InterestGenericText,
    PendingPacket,
)
from gtools.proxy.extension.broker import Broker
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


def test_connect() -> None:
    b = Broker()
    b.start()

    try:
        name = f"test-0"
        ext = ExtensionNextState(name)
        assert ext.start().wait_true(5)

        assert len(b._extension_mgr._extensions) == 1
        assert ext.connected.get()
        assert b._extension_mgr.get_extension(ext._name).id == ext._name

        assert ext.stop().wait_false(5)
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

            assert ext.stop().wait_false(5)
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

        assert ext.stop().wait_false(5)
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

        assert ext.stop().wait_false(5)
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

        assert ext.stop().wait_false(5)
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
        assert ext.connected.wait_false(5)
        b = Broker()
        b.start()
        assert ext.connected.wait_true(5)

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

        assert ext.stop().wait_false(5)
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
        print("second test")

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

        assert ext.stop().wait_false(5)
        assert ext2.stop().wait_false(5)
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

        assert ext2.stop().wait_false(5)

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

        assert ext.stop().wait_false(5)
        assert ext3.stop().wait_false(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


class ExtensionCommand(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        q = Query(where=[Clause(row=FindRow(method=FindRow.KEY_ANY, key=b"text"), col=FindCol(method=FindCol.RELATIVE, index=1))])
        query = Any()
        query.Pack(q)

        super().__init__(
            name=name,
            interest=[
                Interest(
                    interest=INTEREST_GENERIC_TEXT,
                    generic_text=InterestGenericText(where=[BinOp(lvalue=query, op=OP_EQ, buf=b"/should_work")]),
                    priority=priority,
                    blocking_mode=BLOCKING_MODE_BLOCK,
                    direction=DIRECTION_UNSPECIFIED,
                )
            ],
        )

    def process(self, event: PendingPacket) -> PendingPacket | None:
        return self.cancel()

    def destroy(self) -> None:
        pass


def test_generic_text_query() -> None:
    b = Broker()
    b.start()

    try:
        ext = ExtensionCommand("command")
        assert ext.start().wait_true(5)

        opkt = NetPacket(
            type=NetType.GENERIC_TEXT,
            data=StrKV([[b"action", b"input"], [b"", b"text", b"hello"]]),
        )
        pkt = b.process_event(PreparedPacket(opkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert pkt is None

        opkt = NetPacket(
            type=NetType.GENERIC_TEXT,
            data=StrKV([[b"action", b"input"], [b"", b"text", b"/should_work"]]),
        )
        pkt = b.process_event(PreparedPacket(opkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert pkt
        pkt, cancelled = pkt
        verify(pkt.buf)
        assert cancelled == True

        opkt = NetPacket(
            type=NetType.GENERIC_TEXT,
            data=StrKV([[b"action", b"input"], [b"", b"text", b"//should_work"]]),
        )
        pkt = b.process_event(PreparedPacket(opkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert pkt is None

        opkt = NetPacket(
            type=NetType.GENERIC_TEXT,
            data=StrKV([[b"action", b"input"], [b"", b"text", b"//no"]]),
        )
        pkt = b.process_event(PreparedPacket(opkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert pkt is None

        opkt = NetPacket(
            type=NetType.GENERIC_TEXT,
            data=StrKV([[b"action", b"input"], [b"", b"text", b"/not_registered"]]),
        )
        pkt = b.process_event(PreparedPacket(opkt, DIRECTION_UNSPECIFIED, ENetPacketFlag.NONE))
        assert pkt is None

        assert ext.stop().wait_false(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_fast_drop_extension() -> None:
    b = Broker()
    b.start()

    try:
        ext = FastDropExtension()
        assert ext.start().wait_true(5)

        req_buf = b"\x04\x00\x00\x00\x01\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xd4\x00\x00\x00\x02\x00\x02\x0f\x00\x00\x00OnDialogRequest\x01\x02\xb8\x00\x00\x00set_default_color|`o\nadd_label_with_icon|big|`wDrop Sign``|left|20|\nadd_textbox|How many to drop?|left|\nadd_text_input|count||12345|5|\nembed_data|itemID|1092\nend_dialog|drop_item|Cancel|OK|\n@"
        req = NetPacket.deserialize(req_buf)

        res = b.process_event(PreparedPacket(req, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))

        assert res
        pkt, cancelled = res
        assert cancelled == False
        assert pkt._hit_count == 1
        assert pkt.direction == DIRECTION_CLIENT_TO_SERVER
        assert pkt.packet_flags == ENetPacketFlag.RELIABLE
        net = NetPacket.deserialize(pkt.buf)
        assert net.type == NetType.GENERIC_TEXT
        assert net.serialize() == b"\x02\x00\x00\x00action|dialog_return\ndialog_name|drop_item\nitemID|1092|\ncount|12345\n\x00"
        verify(pkt.buf)

        assert ext.stop().wait_false(5)
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
            assert ext.stop().wait_false(5)
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
            assert ext.stop().wait_false(5)
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
            can_push=True,
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

        assert ext.stop().wait_false(5)
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

        assert ext.stop().wait_false(5)
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
            can_push=True,
        )
        self.id = id
        self.id2 = id2
        self.delay1 = delay1
        self.delay2 = delay2

    def thread_1(self) -> None:
        for i in range(100):
            self.push(
                PreparedPacket(
                    NetPacket(type=NetType.TANK_PACKET, data=TankPacket(target_net_id=self.id, net_id=i)),
                    DIRECTION_SERVER_TO_CLIENT,
                    ENetPacketFlag.NONE,
                )
            )
            if self.delay1:
                time.sleep(self.delay1)

    def thread_2(self) -> None:
        for i in range(100):
            self.push(
                PreparedPacket(
                    NetPacket(type=NetType.TANK_PACKET, data=TankPacket(target_net_id=self.id2, net_id=i)),
                    DIRECTION_SERVER_TO_CLIENT,
                    ENetPacketFlag.NONE,
                )
            )
            if self.delay2:
                time.sleep(self.delay2)

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

        assert ext.stop().wait_false(5)
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

        assert ext.stop().wait_false(5)
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

        assert ext.stop().wait_false(5)
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

        assert ext.stop().wait_false(5)
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

        assert ext.stop().wait_false(5)
        assert ext2.stop().wait_false(5)
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

        assert ext.stop().wait_false(5)
        assert ext2.stop().wait_false(5)
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)
        assert not is_port_in_use(b._pull_port)

