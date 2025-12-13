import socket
import pytest

from gtools.core.growtopia.packet import NetPacket, NetType, TankPacket
from gtools.protogen.extension_pb2 import BLOCKING_MODE_BLOCK, DIRECTION_UNSPECIFIED, INTEREST_TANK_PACKET, Event, Forward, Interest, Packet
from gtools.proxy.extension.broker import Broker
from gtools.proxy.extension.sdk import Extension


@pytest.fixture
def init_packet() -> NetPacket:
    return NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))


class SimpleExtension(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_BLOCK, direction=DIRECTION_UNSPECIFIED)])

    def process(self, event: Event) -> Packet | None:
        p = NetPacket.deserialize(event.buf)
        p.tank.net_id = (p.tank.net_id * 31 + int(self._name.split(b"-")[-1].decode())) & 0xFFFFFFFF

        return Packet(type=Packet.TYPE_FORWARD, forward=Forward(buf=p.serialize()))

    def destroy(self) -> None:
        pass


class SimpleExtensionForwardNotModified(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_BLOCK, direction=DIRECTION_UNSPECIFIED)])

    def process(self, event: Event) -> Packet | None:
        return Packet(type=Packet.TYPE_FORWARD_NOT_MODIFIED)

    def destroy(self) -> None:
        pass


def compute_state(init: int, n: int) -> int:
    s = init
    for i in range(n):
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
        ext = SimpleExtension(name)
        ext.start()
        assert ext.connected.wait(5)

        assert len(b._extension_mgr._extensions) == 1
        assert ext.connected.is_set()
        assert b._extension_mgr.get_extension(ext._name).id == ext._name

        ext.stop()
        ext.connected.unwait()
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
        extensions: list[SimpleExtension] = []
        for i in range(5):
            ext = SimpleExtension(f"{request.node.name}-{i}")
            ext.start()
            assert ext.connected.wait(5)
            extensions.append(ext)

        assert len(b._extension_mgr._extensions) == len(extensions)
        assert len(b._extension_mgr._interest_map[extensions[0]._interest[0].interest]) == len(extensions)

        for i, ext in enumerate(extensions, 1):
            assert b._extension_mgr.get_extension(ext._name).id == ext._name

            ext.stop()
            assert ext.connected.unwait(5)
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
        ext = SimpleExtension(name)
        ext.start()
        assert ext.connected.wait(5)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(pkt, pkt.serialize(), DIRECTION_UNSPECIFIED)

        assert pkt
        assert pkt[0].type == NetType.TANK_PACKET
        assert pkt[1] == DIRECTION_UNSPECIFIED
        assert pkt[0].tank.net_id == compute_state(1, 1)

        ext.stop()
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_process_multi(request: pytest.FixtureRequest) -> None:
    b = Broker()
    b.start()

    try:
        extensions: list[SimpleExtension] = []
        for i in range(10):
            name = f"{request.node.name}-{i}"
            ext = SimpleExtension(name, priority=i)
            ext.start()

            extensions.append(ext)

        for ext in extensions:
            assert ext.connected.wait(5)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(pkt, pkt.serialize(), DIRECTION_UNSPECIFIED)

        assert pkt
        assert pkt[0].type == NetType.TANK_PACKET
        assert pkt[1] == DIRECTION_UNSPECIFIED
        assert pkt[0].tank.net_id == compute_state(1, 10)

        ext.stop()
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
        ext = SimpleExtensionForwardNotModified(name)
        ext.start()
        assert ext.connected.wait(5)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(pkt, pkt.serialize(), DIRECTION_UNSPECIFIED)

        assert pkt
        assert pkt[0].type == NetType.TANK_PACKET
        assert pkt[1] == DIRECTION_UNSPECIFIED
        assert pkt[0].tank.net_id == 1

        ext.stop()
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_broker_restart(request: pytest.FixtureRequest) -> None:
    b = Broker()
    b.start()

    try:
        name = f"{request.node.name}-0"
        ext = SimpleExtension(name)
        ext.start()
        assert ext.connected.wait(5)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt = b.process_event(pkt, pkt.serialize(), DIRECTION_UNSPECIFIED)

        assert pkt
        assert pkt[0].type == NetType.TANK_PACKET
        assert pkt[1] == DIRECTION_UNSPECIFIED
        assert pkt[0].tank.net_id == compute_state(1, 1)

        b.stop()
        assert ext.connected.unwait(5)
        b = Broker()
        b.start()
        assert ext.connected.wait(5)

        pkt = b.process_event(pkt[0], pkt[0].serialize(), DIRECTION_UNSPECIFIED)

        assert pkt
        assert pkt[0].type == NetType.TANK_PACKET
        assert pkt[1] == DIRECTION_UNSPECIFIED
        assert pkt[0].tank.net_id == compute_state(compute_state(1, 1), 1)

        ext.stop()
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)
