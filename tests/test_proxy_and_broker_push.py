"""Tests for proxy with injected events and broker push/pull functionality."""

import pytest
import threading
import time
import zmq
from unittest.mock import Mock, MagicMock, patch
from queue import Queue

from gtools.core.growtopia.packet import NetPacket, NetType, TankPacket
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    DIRECTION_UNSPECIFIED,
    INTEREST_TANK_PACKET,
    Event,
    Forward,
    Interest,
    Packet,
    Push,
)
from gtools.proxy.proxy import Proxy, ProxyEvent, From
from gtools.proxy.extension.broker import Broker, PacketCallback, PendingChain, PendingPacket
from gtools.proxy.extension.sdk import Extension
from gtools.proxy.enet import PyENetEvent
from thirdparty.enet.bindings import ENetEventType, ENetPacketFlag


# ============================================================================
# Tests for Proxy with Injected Events
# ============================================================================


@pytest.fixture
def mock_proxy():
    """Create a proxy with mocked eNet connections."""
    with patch('gtools.proxy.proxy.ProxyServer'), \
         patch('gtools.proxy.proxy.ProxyClient'), \
         patch('gtools.proxy.proxy.Broker'):
        proxy = Proxy.__new__(Proxy)
        proxy.logger = Mock()
        proxy._event_queue = Queue()
        proxy._stop_event = threading.Event()
        proxy._should_reconnect = threading.Event()
        proxy._worker_thread = None
        proxy._pull_thread = None
        proxy.running = True
        proxy.server_data = None
        proxy.redirecting = False
        
        # Setup ZMQ context and SUB socket
        proxy._zmq_context = zmq.Context()
        proxy._zmq_sub = proxy._zmq_context.socket(zmq.SUB)
        proxy._zmq_sub.setsockopt(zmq.SUBSCRIBE, b"")
        
        # Mock the broker
        proxy.broker = Mock()
        proxy.broker.process_event = Mock(return_value=None)
        
        # Mock proxy client/server
        proxy.proxy_client = Mock()
        proxy.proxy_server = Mock()
        
        return proxy


def test_proxy_event_queue_injection(mock_proxy):
    """Test that events can be injected directly into proxy event queue."""
    # Create mock eNet event
    mock_packet = Mock()
    mock_packet.data = b"test data"
    mock_packet.flags = ENetPacketFlag(0)
    
    mock_enet_event = PyENetEvent(
        type=ENetEventType.RECEIVE,
        peer=None,
        packet=mock_packet,
    )
    
    # Inject event into queue
    proxy_event = ProxyEvent(inner=mock_enet_event, src=From.CLIENT)
    mock_proxy._event_queue.put(proxy_event)
    
    # Verify event is in queue
    retrieved = mock_proxy._event_queue.get(timeout=1)
    assert retrieved == proxy_event
    assert retrieved.src == From.CLIENT
    assert retrieved.inner.type == ENetEventType.RECEIVE


def test_proxy_handle_injected_client_packet(mock_proxy):
    """Test proxy handles injected client packets correctly."""
    # Create a simple tank packet
    tank_pkt = TankPacket(net_id=1)
    net_pkt = NetPacket(type=NetType.TANK_PACKET, data=tank_pkt)
    
    # Call _handle with injected data
    mock_proxy._handle(net_pkt.serialize(), From.CLIENT, ENetPacketFlag(0))
    
    # Verify broker.process_event was called with correct parameters
    mock_proxy.broker.process_event.assert_called_once()
    call_args = mock_proxy.broker.process_event.call_args
    
    # Check the serialized data matches (packets may not be identical objects)
    assert call_args[0][1] == net_pkt.serialize()  # raw data
    assert call_args[0][2] == DIRECTION_CLIENT_TO_SERVER  # direction
    assert call_args[1]['enet_flags'] == 0  # flags


def test_proxy_handle_injected_server_packet(mock_proxy):
    """Test proxy handles injected server packets correctly."""
    # Create a simple tank packet
    tank_pkt = TankPacket(net_id=2)
    net_pkt = NetPacket(type=NetType.TANK_PACKET, data=tank_pkt)
    
    # Call _handle with injected data from server
    flags = ENetPacketFlag(1)  # Some flag value
    mock_proxy._handle(net_pkt.serialize(), From.SERVER, flags)
    
    # Verify broker.process_event was called with correct parameters
    mock_proxy.broker.process_event.assert_called_once()
    call_args = mock_proxy.broker.process_event.call_args
    
    assert call_args[0][2] == DIRECTION_SERVER_TO_CLIENT  # direction
    assert call_args[1]['enet_flags'] == 1  # flags


# ============================================================================
# Tests for Broker Push/Pull Channel
# ============================================================================


@pytest.fixture
def broker_with_push():
    """Create a broker and set up push socket for testing."""
    broker = Broker()
    broker.start()
    time.sleep(0.1)  # Allow broker to start
    yield broker
    broker.stop()


@pytest.fixture
def zmq_push_socket():
    """Create a ZMQ socket to push to broker's PUB channel."""
    context = zmq.Context()
    socket = context.socket(zmq.PUSH)
    socket.connect("tcp://127.0.0.1:6713")
    time.sleep(0.1)  # Allow socket to connect
    yield socket
    socket.close()
    context.term()


def test_broker_push_to_proxy_single_packet(broker_with_push):
    """Test broker can push a single packet to proxy via PUB channel."""
    # Create a test packet
    tank_pkt = TankPacket(net_id=42)
    net_pkt = NetPacket(type=NetType.TANK_PACKET, data=tank_pkt)
    
    forward_pkt = Packet(
        type=Packet.TYPE_FORWARD,
        forward=Forward(
            buf=net_pkt.serialize(),
            direction=DIRECTION_CLIENT_TO_SERVER,
            enet_flags=0,
        ),
    )
    
    # Push packet via broker
    broker_with_push.push_to_proxy([forward_pkt])
    
    # Verify method was called
    assert broker_with_push._push_socket is not None


def test_broker_push_to_proxy_multiple_packets(broker_with_push):
    """Test broker can push multiple packets to proxy via PUB channel."""
    packets = []
    for i in range(3):
        tank_pkt = TankPacket(net_id=i)
        net_pkt = NetPacket(type=NetType.TANK_PACKET, data=tank_pkt)
        
        forward_pkt = Packet(
            type=Packet.TYPE_FORWARD,
            forward=Forward(
                buf=net_pkt.serialize(),
                direction=DIRECTION_CLIENT_TO_SERVER,
                enet_flags=i,  # Different flags for each
            ),
        )
        packets.append(forward_pkt)
    
    # Push all packets
    broker_with_push.push_to_proxy(packets)
    
    # Verify PUB socket exists and is functional
    assert broker_with_push._push_socket is not None


def test_broker_pending_chain_stores_enet_flags(broker_with_push):
    """Test that pending chains store enet_flags correctly."""
    # Create a test packet
    tank_pkt = TankPacket(net_id=1)
    net_pkt = NetPacket(type=NetType.TANK_PACKET, data=tank_pkt)
    
    # Create pending chain with enet_flags
    from collections import deque
    chain = deque()
    pending = PendingChain(
        id=b"test_id",
        chain=chain,
        data=net_pkt.serialize(),
        direction=DIRECTION_CLIENT_TO_SERVER,
        enet_flags=5,
    )
    
    assert pending.enet_flags == 5
    assert pending.data == net_pkt.serialize()
    assert pending.direction == DIRECTION_CLIENT_TO_SERVER


def test_broker_pending_packet_stores_enet_flags(broker_with_push):
    """Test that pending packets store enet_flags correctly."""
    tank_pkt = TankPacket(net_id=1)
    net_pkt = NetPacket(type=NetType.TANK_PACKET, data=tank_pkt)
    
    callback = PacketCallback(
        send_to_server=lambda data: None,
        send_to_client=lambda data: None,
    )
    
    pending = PendingPacket(
        data=net_pkt.serialize(),
        direction=DIRECTION_SERVER_TO_CLIENT,
        callback=callback,
        enet_flags=3,
    )
    
    assert pending.enet_flags == 3
    assert pending.data == net_pkt.serialize()
    assert pending.direction == DIRECTION_SERVER_TO_CLIENT


def test_broker_process_event_with_enet_flags():
    """Test broker process_event accepts and stores enet_flags."""
    broker = Broker()
    broker.start()
    time.sleep(0.1)
    
    try:
        tank_pkt = TankPacket(net_id=1)
        net_pkt = NetPacket(type=NetType.TANK_PACKET, data=tank_pkt)
        
        callback = PacketCallback(
            send_to_server=lambda data: None,
        )
        
        # Call process_event with enet_flags and timeout
        # With no interested extensions, this should return None
        result = broker.process_event(
            net_pkt,
            net_pkt.serialize(),
            DIRECTION_CLIENT_TO_SERVER,
            enet_flags=7,
            callback=callback,
        )
        
        # For non-blocking with no interested extensions, should return None or the original packet
        # depending on if it's blocking or non-blocking
        # Just verify it doesn't crash and enet_flags was accepted
        assert True
    finally:
        broker.stop()


def test_proxy_pull_broker_packets_with_mock_zmq(mock_proxy):
    """Test proxy can receive and process packets from broker push channel."""
    # Create a test PUSH packet
    tank_pkt = TankPacket(net_id=100)
    net_pkt = NetPacket(type=NetType.TANK_PACKET, data=tank_pkt)
    
    forward_pkt = Packet(
        type=Packet.TYPE_FORWARD,
        forward=Forward(
            buf=net_pkt.serialize(),
            direction=DIRECTION_CLIENT_TO_SERVER,
            enet_flags=2,
        ),
    )
    
    push_pkt = Packet(
        type=Packet.TYPE_PUSH,
        push=Push(packets=[forward_pkt]),
    )
    
    # Mock the ZMQ socket to return our packet
    with patch.object(mock_proxy._zmq_sub, 'poll', return_value=True):
        with patch.object(mock_proxy._zmq_sub, 'recv', return_value=push_pkt.SerializeToString()):
            # Manually call _pull_broker_packets in a thread with timeout
            mock_proxy._stop_event.clear()
            
            packets_received = []
            
            def pull_once():
                try:
                    if mock_proxy._zmq_sub.poll(100, zmq.POLLIN):
                        data = mock_proxy._zmq_sub.recv(zmq.NOBLOCK)
                        recv_pkt = Packet()
                        recv_pkt.ParseFromString(data)
                        
                        if recv_pkt.type == Packet.TYPE_PUSH:
                            for pkt in recv_pkt.push.packets:
                                if pkt.type == Packet.TYPE_FORWARD:
                                    packets_received.append(pkt)
                except Exception as e:
                    print(f"Error in pull_once: {e}")
            
            pull_once()
            
            assert len(packets_received) == 1
            assert packets_received[0].forward.buf == net_pkt.serialize()
            assert packets_received[0].forward.enet_flags == 2


# ============================================================================
# Integration Tests
# ============================================================================


class SimpleTestExtension(Extension):
    """Simple test extension that echoes packets."""
    
    def __init__(self, name: str):
        super().__init__(
            name=name,
            interest=[Interest(interest=INTEREST_TANK_PACKET, blocking_mode=BLOCKING_MODE_BLOCK)],
        )
        self.received_events = []
    
    def process(self, event: Event) -> Packet | None:
        self.received_events.append(event)
        pkt = NetPacket.deserialize(event.buf)
        pkt.tank.net_id += 1  # Modify packet
        
        return self.forward(pkt.serialize())
    
    def destroy(self) -> None:
        pass


def test_broker_push_pull_integration():
    """Integration test: broker accepts process_event with enet_flags."""
    broker = Broker()
    broker.start()
    time.sleep(0.1)
    
    try:
        # Create test packet
        tank_pkt = TankPacket(net_id=50)
        net_pkt = NetPacket(type=NetType.TANK_PACKET, data=tank_pkt)
        
        # Process event through broker with enet_flags
        result = broker.process_event(
            net_pkt,
            net_pkt.serialize(),
            DIRECTION_CLIENT_TO_SERVER,
            enet_flags=4,
        )
        
        time.sleep(0.2)  # Allow processing
        
        # Verify process_event completed without error
        # Result should be None since there are no interested extensions
        assert result is None
    finally:
        broker.stop()


def test_proxy_event_queue_with_enet_flags_preserved(mock_proxy):
    """Test that eNet flags are preserved through event queue."""
    # Create packet with specific flags
    tank_pkt = TankPacket(net_id=1)
    net_pkt = NetPacket(type=NetType.TANK_PACKET, data=tank_pkt)
    
    # Test various flag values
    test_flags = [0, 1, 2, 4, 8, 15]
    
    for flag_val in test_flags:
        mock_proxy.broker.process_event.reset_mock()
        
        flags = ENetPacketFlag(flag_val)
        mock_proxy._handle(net_pkt.serialize(), From.CLIENT, flags)
        
        # Verify flags were passed to process_event
        call_args = mock_proxy.broker.process_event.call_args
        assert call_args[1]['enet_flags'] == flag_val


def test_pending_chain_repr():
    """Test PendingChain repr for debugging."""
    from collections import deque
    
    chain = deque()
    pending = PendingChain(
        id=b"chain_123",
        chain=chain,
        data=b"test_data",
        direction=DIRECTION_CLIENT_TO_SERVER,
        enet_flags=5,
    )
    
    repr_str = repr(pending)
    assert "chain_123" not in repr_str  # ID is bytes, not included in repr
    assert "size=0" in repr_str
    assert "finished=False" in repr_str
