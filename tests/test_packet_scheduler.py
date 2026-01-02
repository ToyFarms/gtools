import struct
import time

from gtools.core.growtopia.packet import NetPacket, NetType, TankPacket
from gtools.protogen.extension_pb2 import PendingPacket
from gtools.proxy.extension.broker import PacketScheduler


def test_packet_scheduler_delta_time() -> None:
    output_packets: list[tuple[int, PendingPacket]] = []

    def capture_output(pkt):
        output_packets.append((time.monotonic_ns(), pkt))

    scheduler = PacketScheduler(capture_output)

    try:
        # Create properly serialized NetPacket for packet A
        net_pkt_a = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt_a = PendingPacket()
        pkt_a._rtt_ns = struct.pack("<Q", 10_000_000)
        pkt_a.buf = net_pkt_a.serialize()
        scheduler.push(pkt_a)

        # Create properly serialized NetPacket for packet B
        net_pkt_b = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=2))
        pkt_b = PendingPacket()
        pkt_b._rtt_ns = struct.pack("<Q", 10_000_000)
        pkt_b.buf = net_pkt_b.serialize()
        scheduler.push(pkt_b)

        time.sleep(0.05) 

        scheduler.stop()

        assert len(output_packets) >= 2, f"Expected at least 2 packets, got {len(output_packets)}"

        time_a = output_packets[0][0]
        time_b = output_packets[1][0]

        actual_delta_ns = time_b - time_a
        expected_delta_ns = 10_000_000  # 10ms

        tolerance_ns = 5_000_000

        assert abs(actual_delta_ns - expected_delta_ns) < tolerance_ns, (
            f"Delta time mismatch: expected {expected_delta_ns}ns, got {actual_delta_ns}ns " f"(diff: {abs(actual_delta_ns - expected_delta_ns)}ns)"
        )

    finally:
        scheduler.stop()


def test_packet_scheduler_multiple_delta_times() -> None:
    output_packets: list[tuple[int, PendingPacket]] = []

    def capture_output(pkt):
        output_packets.append((time.monotonic_ns(), pkt))

    scheduler = PacketScheduler(capture_output)

    try:
        deltas_ms = [5, 10, 15]
        packets = []

        for i, delta_ms in enumerate(deltas_ms):
            # Create properly serialized NetPacket
            net_pkt = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=i))
            pkt = PendingPacket()
            pkt._rtt_ns = struct.pack("<Q", delta_ms * 1_000_000)
            pkt.buf = net_pkt.serialize()
            packets.append(pkt)
            scheduler.push(pkt)

        time.sleep(0.1)
        scheduler.stop()

        assert len(output_packets) >= 3, f"Expected at least 3 packets, got {len(output_packets)}"

        tolerance_ms = 5

        for i in range(1, len(output_packets)):
            actual_delta_ms = (output_packets[i][0] - output_packets[i - 1][0]) / 1_000_000
            expected_delta_ms = deltas_ms[i]
            assert abs(actual_delta_ms - expected_delta_ms) < tolerance_ms, (
                f"Packet {i} delta mismatch: expected {expected_delta_ms}ms, " f"got {actual_delta_ms:.2f}ms (diff: {abs(actual_delta_ms - expected_delta_ms):.2f}ms)"
            )

    finally:
        scheduler.stop()
