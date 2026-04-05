import ctypes
import logging
import threading
import time
from gtools.core.growtopia.packet import EmptyPacket, NetPacket, NetType, TankType
from gtools.core.growtopia.variant import Variant
from gtools.core.protocol import Serializable
from thirdparty.enet.bindings import (
    ENetAddress,
    ENetEvent,
    ENetEventType,
    ENetPacket,
    ENetPacketFlag,
    ENetPeer,
    Pointer,
    byref,
    enet_address_set_host,
    enet_host_compress_with_range_coder,
    enet_host_create,
    enet_host_service,
    enet_host_use_crc32,
    enet_host_use_new_packet_for_server,
    enet_packet_create,
    enet_packet_destroy,
    enet_peer_disconnect,
    enet_peer_send,
)


class Peer:
    logger = logging.getLogger("peer")

    def __init__(self, id: int, peer: Pointer[ENetPeer]) -> None:
        self.id = id
        self.peer = peer
        self.want_to_disconnect: bool = False

    def on_connect(self) -> None:
        self.logger.debug(f"peer {self.id} connected")
        self.send(NetPacket(NetType.SERVER_HELLO, EmptyPacket()))
        self.send(NetPacket(NetType.CLIENT_LOG_REQUEST, EmptyPacket()))
        self.send(
            NetPacket.variant(
                Variant(
                    [
                        Variant.vstr(b"OnSetNpcXMLIndexes"),
                        Variant.vstr(
                            b"Axebeak|AxebeaksBoss|BladeofRevolt|Chest|CrystalTurret|DiamondDestructoBoss|DragonsBreath|DreadGazerBoss|FlippingSpikesHorizontal|FlippingSpikesHorizontalDown|FlippingSpikesVertical|FlippingSpikesVerticalRight|HealingAura|HiddenObject|IceGolemBoss|Jelatinous|JelatinousChunkBoss|MagicCrystalBallBoss|MimicChest|PlayerShield|PoisonStatusEffect|Portal|Servant Of K'Tesh|Shield|ShieldCrystal|Shriekgazer|Swordsman|TerraShark|Viper|WindGuardian|WindGuardianShield"
                        ),
                    ]
                )
            )
        )

    def on_receive(self, data: bytes, flags: ENetPacketFlag) -> None:
        pkt = NetPacket.deserialize(data)

        if pkt.type == NetType.GENERIC_TEXT and pkt.generic_text.get(b"action") == b"quit":
            self.want_to_disconnect = True
        if pkt.type == NetType.TANK_PACKET and pkt.tank.type == TankType.DISCONNECT:
            self.want_to_disconnect = True

        self.logger.debug(f"peer {self.id}: {pkt.compact_repr()}")

    def on_disconnect(self) -> None:
        self.logger.debug(f"peer {self.id} disconnected")

    def send(self, data: bytes | Serializable, flags: ENetPacketFlag = ENetPacketFlag.RELIABLE) -> None:
        if not self.peer:
            return

        data = data if isinstance(data, bytes) else data.serialize()
        buf = ctypes.create_string_buffer(data)
        pkt = enet_packet_create(ctypes.cast(buf, ctypes.c_void_p), len(data), flags)
        enet_peer_send(self.peer, 0, pkt)

    def disconnect(self) -> None:
        enet_peer_disconnect(self.peer, 0)


class Server:
    logger = logging.getLogger("server")

    def __init__(self, host: str, port: int) -> None:
        self.addr = ENetAddress(port=port)
        enet_address_set_host(byref(self.addr), host.encode())

        self.host = enet_host_create(byref(self.addr), 50, 2, 0, 0)
        if not self.host:
            raise RuntimeError("host is null")
        enet_host_compress_with_range_coder(self.host)
        enet_host_use_crc32(self.host)
        enet_host_use_new_packet_for_server(self.host)

        self._thread_id: threading.Thread | None = None
        self.peers: dict[int, Peer] = {}

    def start(self, block: bool = False) -> None:
        if block:
            try:
                self._thread()
            except (InterruptedError, KeyboardInterrupt):
                pass
        else:
            self._thread_id = threading.Thread(target=self._thread)
            self._thread_id.start()

    def get_peer(self, id: int | Pointer[ENetPeer]) -> Peer:
        if isinstance(id, int):
            return self.peers[id]

        id = ctypes.cast(id, ctypes.POINTER(ENetPeer)).contents.connectID
        return self.peers[id]

    def _thread(self) -> None:
        while True:
            event = ENetEvent()
            if enet_host_service(self.host, byref(event), 0) > 0:
                try:
                    if event.type == ENetEventType.CONNECT:
                        enet_peer = ctypes.cast(event.peer, ctypes.POINTER(ENetPeer)).contents
                        id = enet_peer.connectID
                        peer = Peer(id, event.peer)
                        self.peers[id] = peer

                        peer.on_connect()

                    elif event.type == ENetEventType.RECEIVE:
                        peer = self.get_peer(event.peer)

                        packet = ctypes.cast(event.packet, ctypes.POINTER(ENetPacket)).contents
                        data = ctypes.string_at(packet.data, int(packet.dataLength))
                        flags = ENetPacketFlag(packet.flags)

                        peer.on_receive(data, flags)

                        if peer.want_to_disconnect:
                            peer.on_disconnect()
                            self.peers.pop(peer.id, None)
                            peer.disconnect()

                        enet_packet_destroy(event.packet)
                    elif event.type == ENetEventType.DISCONNECT:
                        peer = self.get_peer(event.peer)
                        peer.on_disconnect()

                        self.peers.pop(peer.id)
                except Exception as e:
                    self.logger.error(f"exception in service: {e}")

            time.sleep(0.01)
