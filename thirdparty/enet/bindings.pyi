from __future__ import annotations
import ctypes
from enum import IntEnum, IntFlag
from ctypes import (
    _Pointer,
    Array,
    Structure,
)
from typing import Literal, Protocol

class STATIC_ARRAY[T, N](Array): ...

c_char_p = bytes
c_int = int
c_size_t = int
c_uint8 = int
c_uint16 = int
c_uint32 = int
c_void_p = ctypes.c_void_p | None

def byref[T: Structure](val: T, offset: int = 0) -> _Pointer[T]: ...

class ENetAddress(Structure):
    host: c_uint32
    port: c_uint16

class ENetEventType(IntEnum):
    NONE = 0
    CONNECT = 1
    DISCONNECT = 2
    RECEIVE = 3
    DISCONNECT_TIMEOUT = 4

class ENetPacketFlag(IntFlag):
    # packet must be received by the target peer and resend attempts should be
    # made until the packet is delivered
    RELIABLE = 1 << 0

    # packet will not be sequenced with other packets
    UNSEQUENCED = 1 << 1

    # packet will not allocate data, and user must supply it instead */
    NO_ALLOCATE = 1 << 2

    # packet will be fragmented using unreliable (instead of reliable) sends
    # if it exceeds the MTU */
    UNRELIABLE_FRAGMENT = 1 << 3

    # whether the packet has been sent from all queues it has been entered into */
    SENT = 1 << 8

class ENetPacketFreeCallback(Protocol):
    def __call__(self, pkt: _Pointer[ENetPacket]) -> None: ...

class ENetPacket(Structure):
    referenceCount: c_size_t
    flags: c_uint32  # ENetPacketFlag
    data: _Pointer[ctypes.c_uint8]
    dataLength: c_size_t
    freeCallback: ENetPacketFreeCallback
    userData: c_void_p

class ENetListNode(Structure):
    next: _Pointer[ENetListNode]
    previous: _Pointer[ENetListNode]

class ENetList(Structure):
    sentinel: ENetListNode

class EnetPeerState(IntEnum):
    ENET_PEER_STATE_DISCONNECTED = 0
    ENET_PEER_STATE_CONNECTING = 1
    ENET_PEER_STATE_ACKNOWLEDGING_CONNECT = 2
    ENET_PEER_STATE_CONNECTION_PENDING = 3
    ENET_PEER_STATE_CONNECTION_SUCCEEDED = 4
    ENET_PEER_STATE_CONNECTED = 5
    ENET_PEER_STATE_DISCONNECT_LATER = 6
    ENET_PEER_STATE_DISCONNECTING = 7
    ENET_PEER_STATE_ACKNOWLEDGING_DISCONNECT = 8
    ENET_PEER_STATE_ZOMBIE = 9

class ENetChannel(Structure):
    outgoingReliableSequenceNumber: c_uint16
    outgoingUnreliableSequenceNumber: c_uint16
    usedReliableWindows: c_uint16
    reliableWindows: c_uint16
    incomingReliableSequenceNumber: c_uint16
    incomingUnreliableSequenceNumber: c_uint16
    incomingReliableCommands: ENetList
    incomingUnreliableCommands: ENetList

class ENetPeer(Structure):
    dispatchList: ENetListNode
    host: c_void_p
    outgoingPeerID: c_uint16
    incomingPeerID: c_uint16
    connectID: c_uint32
    outgoingSessionID: c_uint8
    incomingSessionID: c_uint8
    address: ENetAddress  # Internet address of the peer
    data: c_void_p  # Application private data,   may be freely modified
    state: c_int  # EnetPeerState
    channels: _Pointer[ENetChannel]
    channelCount: c_size_t  # Number of channels allocated for communication with peer
    incomingBandwidth: c_uint32  # Downstream bandwidth of the client in bytes/second
    outgoingBandwidth: c_uint32  # Upstream bandwidth of the client in bytes/second
    incomingBandwidthThrottleEpoch: c_uint32
    outgoingBandwidthThrottleEpoch: c_uint32
    incomingDataTotal: c_uint32
    outgoingDataTotal: c_uint32
    lastSendTime: c_uint32
    lastReceiveTime: c_uint32
    nextTimeout: c_uint32
    earliestTimeout: c_uint32
    packetLossEpoch: c_uint32
    packetsSent: c_uint32
    packetsLost: c_uint32
    packetLoss: c_uint32  # mean packet loss of reliable packets as a ratio with respect to the constant ENET_PEER_PACKET_LOSS_SCALE
    packetLossVariance: c_uint32
    packetThrottle: c_uint32
    packetThrottleLimit: c_uint32
    packetThrottleCounter: c_uint32
    packetThrottleEpoch: c_uint32
    packetThrottleAcceleration: c_uint32
    packetThrottleDeceleration: c_uint32
    packetThrottleInterval: c_uint32
    pingInterval: c_uint32
    timeoutLimit: c_uint32
    timeoutMinimum: c_uint32
    timeoutMaximum: c_uint32
    lastRoundTripTime: c_uint32
    lowestRoundTripTime: c_uint32
    lastRoundTripTimeVariance: c_uint32
    highestRoundTripTimeVariance: c_uint32
    roundTripTime: c_uint32  # mean round trip time (RTT), in milliseconds, between sending a reliable packet and receiving its acknowledgement
    roundTripTimeVariance: c_uint32
    mtu: c_uint32
    windowSize: c_uint32
    reliableDataInTransit: c_uint32
    outgoingReliableSequenceNumber: c_uint16
    acknowledgements: ENetList
    sentReliableCommands: ENetList
    outgoingSendReliableCommands: ENetList
    outgoingCommands: ENetList
    dispatchedCommands: ENetList
    flags: c_uint16
    reserved: c_uint16
    incomingUnsequencedGroup: c_uint16
    outgoingUnsequencedGroup: c_uint16
    unsequencedWindow: STATIC_ARRAY[c_uint32, Literal[32]]
    eventData: c_uint32
    totalWaitingData: c_size_t

class ENetEvent(Structure):
    type: c_int  # ENetEventType
    peer: _Pointer[ENetPeer]
    channelID: c_uint8
    data: c_uint32
    packet: _Pointer[ENetPacket]

def enet_initialize() -> c_int: ...
def enet_host_create(
    address: _Pointer[ENetAddress],
    peerCount: c_size_t,
    channelLimit: c_size_t,
    incomingBandwidth: c_int,
    outgoingBandwidth: c_int,
) -> c_void_p: ...
def enet_host_service(
    host: c_void_p, event: _Pointer[ENetEvent], timeout: c_uint32
) -> c_int: ...
def enet_address_set_host(
    address: _Pointer[ENetAddress],
    hostName: c_char_p,
) -> c_int: ...
def enet_address_set_host_ip(
    address: _Pointer[ENetAddress],
    hostName: c_char_p,
) -> c_int: ...
def enet_host_connect(
    host: c_void_p,
    address: _Pointer[ENetAddress],
    channelCount: c_size_t,
    data: c_uint32,
) -> _Pointer[ENetPeer]: ...
def enet_host_use_new_packet(host: c_void_p) -> None: ...
def enet_host_use_new_packet_for_server(host: c_void_p) -> None: ...
def enet_host_use_crc32(host: c_void_p) -> None: ...
def enet_host_compress_with_range_coder(host: c_void_p) -> c_int: ...
def enet_host_flush(host: c_void_p) -> None: ...
def enet_host_destroy(host: c_void_p) -> None: ...
def enet_packet_destroy(packet: _Pointer[ENetPacket]) -> None: ...
def enet_peer_send(
    peer: _Pointer[ENetPeer],
    channelID: c_uint8,
    packet: _Pointer[ENetPacket],
) -> c_int: ...
def enet_packet_create(
    data: c_void_p,
    dataLength: c_size_t,
    flags: c_uint32,
) -> _Pointer[ENetPacket]: ...
def enet_peer_disconnect(peer: _Pointer[ENetPeer], data: c_uint32) -> None: ...
def enet_peer_disconnect_now(peer: _Pointer[ENetPeer], data: c_uint32) -> None: ...
def enet_peer_timeout(
    peer: _Pointer[ENetPeer],
    timeoutLimit: c_uint32,
    timeoutMinimum: c_uint32,
    timeoutMaximum: c_uint32,
) -> None: ...
