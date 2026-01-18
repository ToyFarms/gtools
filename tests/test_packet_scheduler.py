import time

from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket, TankPacket
from gtools.core.highres_sleep import sleep_ns
from gtools.protogen.extension_pb2 import PendingPacket
from gtools.proxy.extension.broker import PacketScheduler


def test_packet_scheduler_delta_time() -> None:
    output_packets: list[tuple[int, PreparedPacket | None]] = []
    scheduler = PacketScheduler(lambda pkt: output_packets.append((time.monotonic_ns(), pkt)))

    try:
        sleep = 10 * 1e6  # 10ms
        net_pkt_a = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=1))
        pkt_a = PendingPacket()
        pkt_a._rtt_ns = time.monotonic_ns()
        pkt_a.buf = net_pkt_a.serialize()
        scheduler.push(pkt_a)

        sleep_ns(sleep)

        net_pkt_b = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=2))
        pkt_b = PendingPacket()
        pkt_b._rtt_ns = time.monotonic_ns()
        pkt_b.buf = net_pkt_b.serialize()
        scheduler.push(pkt_b)

        time.sleep(0.1)

        scheduler.stop()

        assert len(output_packets) >= 2, f"expected at least 2 packets, got {len(output_packets)}"

        time_a = output_packets[0][0]
        time_b = output_packets[1][0]

        actual_delta_ns = time_b - time_a
        expected_delta_ns = sleep
        tolerance_ns = 2 * 1e6

        assert abs(actual_delta_ns - expected_delta_ns) < tolerance_ns, (
            f"delta time mismatch: expected {expected_delta_ns}ns, got {actual_delta_ns}ns " f"(diff: {abs(actual_delta_ns - expected_delta_ns)}ns)"
        )

    finally:
        scheduler.stop()


def test_packet_scheduler_multiple_delta_times() -> None:
    output_packets: list[tuple[int, PreparedPacket | None]] = []
    scheduler = PacketScheduler(lambda pkt: output_packets.append((time.monotonic_ns(), pkt)))

    try:
        deltas = [5, 10, 15, 20, 50, 100, 1000]

        for i, delta in enumerate(deltas):
            pkt = PendingPacket()
            pkt._rtt_ns = time.monotonic_ns()
            pkt.buf = NetPacket(type=NetType.TANK_PACKET, data=TankPacket(net_id=i)).serialize()
            scheduler.push(pkt)

            sleep_ns(delta * 1e6)

        time.sleep(0.5)

        scheduler.stop()

        assert len(output_packets) >= len(deltas), f"expected at least {len(deltas)} packets, got {len(output_packets)}"

        tolerance_ns = 2 * 1e6
        for i in range(1, len(deltas)):
            actual_delta_ns = output_packets[i][0] - output_packets[i - 1][0]
            expected_delta_ns = int(deltas[i - 1] * 1e6)
            diff = abs(actual_delta_ns - expected_delta_ns)
            assert diff < tolerance_ns, f"packet {i} delta mismatch: expected {expected_delta_ns}ns, " f"got {actual_delta_ns:.2f}ns (diff: {diff:.2f}ns)"

    finally:
        scheduler.stop()
