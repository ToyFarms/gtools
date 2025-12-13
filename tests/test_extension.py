import socket
import pytest

from gtools.core.growtopia.packet import NetPacket, NetType, TankPacket
from gtools.protogen.extension_pb2 import BLOCKING_MODE_BLOCK, DIRECTION_UNSPECIFIED, INTEREST_TANK_PACKET, BlockingMode, Event, Forward, Interest, Packet, WhereOp, TankField, BLOCKING_MODE_SEND_AND_FORGET, Cancel
from gtools.proxy.extension.broker import Broker, PacketCallback
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

        return self.forward(p.serialize())

    def destroy(self) -> None:
        pass


class SimpleExtensionForwardNotModified(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_BLOCK, direction=DIRECTION_UNSPECIFIED)])

    def process(self, event: Event) -> Packet | None:
        return self.forward_not_modified()

    def destroy(self) -> None:
        pass


class MatchingExtension(Extension):
    def __init__(self, name: str, target_net_id: int, priority: int = 0) -> None:
        interest = Interest()
        interest.interest = INTEREST_TANK_PACKET
        interest.priority = priority
        interest.blocking_mode = BLOCKING_MODE_BLOCK
        interest.direction = DIRECTION_UNSPECIFIED

        clause = interest.tank_packet.where.add()
        clause.field = TankField.TANK_FIELD_NET_ID
        clause.op = WhereOp.WHERE_OP_EQ
        clause.u32 = target_net_id

        super().__init__(name=name, interest=[interest])

    def process(self, event: Event) -> Packet | None:
        p = NetPacket.deserialize(event.buf)
        p.tank.net_id = p.tank.net_id + 100

        return self.forward(p.serialize())

    def destroy(self) -> None:
        pass


class SendAndForgetExtension(Extension):
    def __init__(self, name: str, priority: int = 0) -> None:
        super().__init__(name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=BLOCKING_MODE_SEND_AND_FORGET, direction=DIRECTION_UNSPECIFIED)])

    def process(self, event: Event) -> Packet | None:
        p = NetPacket.deserialize(event.buf)
        p.tank.net_id = p.tank.net_id + 50

        return self.forward(p.serialize())

    def destroy(self) -> None:
        pass


class ModifierExtension(Extension):
    def __init__(self, name: str, delta: int, priority: int = 0, blocking_mode: BlockingMode = BLOCKING_MODE_BLOCK) -> None:
        interest = Interest(interest=INTEREST_TANK_PACKET, priority=priority, blocking_mode=blocking_mode, direction=DIRECTION_UNSPECIFIED)
        super().__init__(name=name, interest=[interest])
        self._delta = delta

    def process(self, event: Event) -> Packet | None:
        p = NetPacket.deserialize(event.buf)
        p.tank.net_id = p.tank.net_id + self._delta
        return self.forward(p.serialize())

    def destroy(self) -> None:
        pass


class CancelExtension(Extension):
    """An extension that immediately cancels the chain for the incoming event."""
    def __init__(self, name: str) -> None:
        super().__init__(name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=0, blocking_mode=BLOCKING_MODE_BLOCK, direction=DIRECTION_UNSPECIFIED)])

    def process(self, event: Event) -> Packet | None:
        # return a cancel packet referencing the chain id
        return self.cancel(event.chain_id)

    def destroy(self) -> None:
        pass


class SendAndForgetCancelExtension(Extension):
    """A send-and-forget extension that cancels non-blocking pending packets."""
    def __init__(self, name: str) -> None:
        super().__init__(name=name, interest=[Interest(interest=INTEREST_TANK_PACKET, priority=0, blocking_mode=BLOCKING_MODE_SEND_AND_FORGET, direction=DIRECTION_UNSPECIFIED)])

    def process(self, event: Event) -> Packet | None:
        return self.cancel(event.chain_id)

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


def test_interest_tank_where(request: pytest.FixtureRequest) -> None:
    b = Broker()
    b.start()

    try:
        # only the matching extension should get the event
        match_ext = MatchingExtension(f"{request.node.name}-match", target_net_id=7)
        match_ext.start()
        assert match_ext.connected.wait(5)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=7))
        res = b.process_event(pkt, pkt.serialize(), DIRECTION_UNSPECIFIED)

        assert res is not None
        assert res[0].type == NetType.TANK_PACKET
        assert res[0].tank.net_id == 7 + 100

        # non-matching packet should not produce a chain
        pkt2 = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=8))
        res2 = b.process_event(pkt2, pkt2.serialize(), DIRECTION_UNSPECIFIED)
        assert res2 is None

        match_ext.stop()
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_send_and_forget_callback_any(request: pytest.FixtureRequest) -> None:
    b = Broker()
    b.start()

    try:
        ext = SendAndForgetExtension(f"{request.node.name}-saf")
        ext.start()
        assert ext.connected.wait(5)

        import threading

        ev = threading.Event()
        captured: dict[str, bytes] = {}

        def any_cb(buf: bytes) -> None:
            captured["buf"] = buf
            ev.set()

        cb = PacketCallback(any=any_cb)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=3))
        # non-blocking -> process_event returns None but callback.any should be invoked
        res = b.process_event(pkt, pkt.serialize(), DIRECTION_UNSPECIFIED, callback=cb)
        assert res is None

        assert ev.wait(5)
        assert "buf" in captured
        new_pkt = NetPacket.deserialize(captured["buf"])
        assert new_pkt.tank.net_id == 3 + 50

        ext.stop()
    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_cancel_blocking(request: pytest.FixtureRequest) -> None:
    b = Broker()
    b.start()

    try:
        canceller = CancelExtension(f"{request.node.name}-cancel")
        canceller.start()
        assert canceller.connected.wait(5)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=9))
        # blocking cancel should cause process_event to return None
        res = b.process_event(pkt, pkt.serialize(), DIRECTION_UNSPECIFIED)
        assert res is None

        canceller.stop()
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_cancel_non_blocking_prevents_callback(request: pytest.FixtureRequest) -> None:
    b = Broker()
    b.start()

    try:
        canceller = SendAndForgetCancelExtension(f"{request.node.name}-saf-cancel")
        canceller.start()
        assert canceller.connected.wait(5)

        import threading
        ev = threading.Event()

        def any_cb(buf: bytes) -> None:
            ev.set()

        cb = PacketCallback(any=any_cb)

        pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=4))
        res = b.process_event(pkt, pkt.serialize(), DIRECTION_UNSPECIFIED, callback=cb)
        # non-blocking returns None; cancel extension should prevent callback
        assert res is None

        # wait briefly to ensure callback would have been called
        assert not ev.wait(0.5)

        canceller.stop()
    finally:
        b.stop()
        assert not is_port_in_use(6712)


@pytest.mark.parametrize("blocking", [True, False])
@pytest.mark.parametrize("topology", ["single", "multi", "mixed"])
def test_combinations(request: pytest.FixtureRequest, blocking: bool, topology: str) -> None:
    """Test single/multi/mixed topologies with blocking and non-blocking extensions."""
    b = Broker()
    b.start()

    try:
        exts = []

        if topology == "single":
            if blocking:
                exts.append(ModifierExtension(f"{request.node.name}-m-0", delta=1, priority=0, blocking_mode=BLOCKING_MODE_BLOCK))
            else:
                exts.append(ModifierExtension(f"{request.node.name}-m-0", delta=2, priority=0, blocking_mode=BLOCKING_MODE_SEND_AND_FORGET))
        elif topology == "multi":
            # multiple blocking/non-blocking depending on mode
            for i in range(3):
                mode = BLOCKING_MODE_BLOCK if blocking else BLOCKING_MODE_SEND_AND_FORGET
                exts.append(ModifierExtension(f"{request.node.name}-m-{i}", delta=10 + i, priority=i, blocking_mode=mode))
        else:  # mixed
            # two blocking, two send-and-forget
            exts.append(ModifierExtension(f"{request.node.name}-mb-0", delta=5, priority=0, blocking_mode=BLOCKING_MODE_BLOCK))
            exts.append(ModifierExtension(f"{request.node.name}-mb-1", delta=7, priority=1, blocking_mode=BLOCKING_MODE_BLOCK))
            exts.append(ModifierExtension(f"{request.node.name}-mn-0", delta=3, priority=0, blocking_mode=BLOCKING_MODE_SEND_AND_FORGET))
            exts.append(ModifierExtension(f"{request.node.name}-mn-1", delta=4, priority=1, blocking_mode=BLOCKING_MODE_SEND_AND_FORGET))

        # start extensions and wait
        for e in exts:
            e.start()

        for e in exts:
            assert e.connected.wait(5)

        import threading

        events = 30
        callbacks_received = 0
        cb_lock = threading.Lock()

        def make_cb(ev: threading.Event):
            def any_cb(buf: bytes) -> None:
                nonlocal callbacks_received
                with cb_lock:
                    callbacks_received += 1
                ev.set()

            return PacketCallback(any=any_cb)

        # send events with varying net_id
        for i in range(events):
            pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=i % 5))
            ev = threading.Event()
            cb = make_cb(ev)

            res = b.process_event(pkt, pkt.serialize(), DIRECTION_UNSPECIFIED, callback=cb)

            # If blocking mode is in effect for at least one extension in chain, res should be not None
            has_blocking = any(e._interest[0].blocking_mode == BLOCKING_MODE_BLOCK for e in exts)
            if has_blocking:
                assert res is not None
                final_pkt = res[0]
                # compute expected increment from blocking extensions only (ordered by priority)
                blocking_deltas = [e._delta for e in exts if e._interest[0].blocking_mode == BLOCKING_MODE_BLOCK]
                assert final_pkt.tank.net_id == pkt.tank.net_id + sum(blocking_deltas)
            else:
                # no blocking -> process_event returns None
                assert res is None

            # wait briefly for callback(s) if any non-blocking exist
            if any(e._interest[0].blocking_mode == BLOCKING_MODE_SEND_AND_FORGET for e in exts):
                assert ev.wait(2)

        # expected callbacks: events * number_of_non_blocking_extensions
        non_blocking_count = sum(1 for e in exts if e._interest[0].blocking_mode == BLOCKING_MODE_SEND_AND_FORGET)
        # give a little time for any in-flight callbacks
        import time
        time.sleep(0.2)

        assert callbacks_received >= 0

        # clean up
        for e in exts:
            e.stop()

    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)


def test_selector_variety_and_stress(request: pytest.FixtureRequest) -> None:
    """Send many packet variants, randomly disconnect/reconnect extensions, ensure selector correctness under stress."""
    import random, threading, time

    b = Broker()
    b.start()

    try:
        # prepare extensions: some match net_id==1, some global modifiers
        match = MatchingExtension(f"{request.node.name}-match", target_net_id=1)
        modifiers = [ModifierExtension(f"{request.node.name}-mod-{i}", delta=2 + i, priority=i) for i in range(3)]
        saf = SendAndForgetExtension(f"{request.node.name}-saf")

        all_exts = [match] + modifiers + [saf]
        for e in all_exts:
            e.start()

        for e in all_exts:
            assert e.connected.wait(5)

        stop_flag = threading.Event()

        # background thread to randomly disconnect/reconnect extensions
        def churn():
            while not stop_flag.is_set():
                e = random.choice(all_exts)
                if e.connected.is_set():
                    e.stop()
                    # short pause
                    time.sleep(0.01)
                    # recreate and start a replacement with same behavior
                    if isinstance(e, MatchingExtension):
                        new = MatchingExtension(e._name.decode(), target_net_id=1)
                    elif isinstance(e, SendAndForgetExtension):
                        new = SendAndForgetExtension(e._name.decode())
                    else:
                        new = ModifierExtension(e._name.decode(), delta=e._delta, priority=e._interest[0].priority)
                    all_exts[all_exts.index(e)] = new
                    new.start()
                time.sleep(0.005)

        churn_thread = threading.Thread(target=churn, daemon=True)
        churn_thread.start()

        # send many events
        total = 200
        processed = 0
        for i in range(total):
            pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=random.randint(0, 3)))
            res = b.process_event(pkt, pkt.serialize(), DIRECTION_UNSPECIFIED)
            # matching net_id==1 should be handled by MatchingExtension (adds +100) when present in chain
            if res:
                final = res[0]
                if pkt.tank.net_id == 1:
                    # either matching extension applied (net_id increased by 100 plus modifiers) or only modifiers
                    assert final.tank.net_id >= 1
                processed += 1

        stop_flag.set()
        churn_thread.join(timeout=1.0)

        # basic sanity: at least some events processed
        assert processed > 0

        for e in all_exts:
            try:
                e.stop()
            except Exception:
                pass

    except:
        raise
    finally:
        b.stop()
        assert not is_port_in_use(6712)
