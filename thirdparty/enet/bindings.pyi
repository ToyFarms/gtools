from __future__ import annotations
import ctypes
from enum import Enum, IntEnum, IntFlag
from ctypes import (
    _Pointer,
    Array,
    Structure,
    Union,
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

class Pointer[T](_Pointer): ...
def byref[T: Structure](val: T, offset: int = 0) -> Pointer[T]: ...

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
    NONE = 0
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
    def __call__(self, pkt: Pointer[ENetPacket]) -> None: ...

class ENetPacket(Structure):
    referenceCount: c_size_t
    flags: c_uint32  # ENetPacketFlag
    data: Pointer[ctypes.c_uint8]
    dataLength: c_size_t
    freeCallback: ENetPacketFreeCallback
    userData: c_void_p

class ENetListNode(Structure):
    next: Pointer[ENetListNode]
    previous: Pointer[ENetListNode]

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
    host: Pointer[ENetHost]
    outgoingPeerID: c_uint16
    incomingPeerID: c_uint16
    connectID: c_uint32
    outgoingSessionID: c_uint8
    incomingSessionID: c_uint8
    address: ENetAddress  # Internet address of the peer
    data: c_void_p  # Application private data,   may be freely modified
    state: c_int  # EnetPeerState
    channels: Pointer[ENetChannel]
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
    peer: Pointer[ENetPeer]
    channelID: c_uint8
    data: c_uint32
    packet: Pointer[ENetPacket]

ENET_PROTOCOL_MINIMUM_MTU = Literal[576]
ENET_PROTOCOL_MAXIMUM_MTU = Literal[4096]
ENET_PROTOCOL_MAXIMUM_PACKET_COMMANDS = Literal[32]
ENET_PROTOCOL_MINIMUM_WINDOW_SIZE = Literal[4096]
ENET_PROTOCOL_MAXIMUM_WINDOW_SIZE = Literal[65536]
ENET_PROTOCOL_MINIMUM_CHANNEL_COUNT = Literal[1]
ENET_PROTOCOL_MAXIMUM_CHANNEL_COUNT = Literal[255]
ENET_PROTOCOL_MAXIMUM_PEER_ID = Literal[0xFFF]
ENET_PROTOCOL_MAXIMUM_FRAGMENT_COUNT = Literal[1024 * 1024]

ENET_PROTOCOL_COMMAND_NONE = Literal[0]
ENET_PROTOCOL_COMMAND_ACKNOWLEDGE = Literal[1]
ENET_PROTOCOL_COMMAND_CONNECT = Literal[2]
ENET_PROTOCOL_COMMAND_VERIFY_CONNECT = Literal[3]
ENET_PROTOCOL_COMMAND_DISCONNECT = Literal[4]
ENET_PROTOCOL_COMMAND_PING = Literal[5]
ENET_PROTOCOL_COMMAND_SEND_RELIABLE = Literal[6]
ENET_PROTOCOL_COMMAND_SEND_UNRELIABLE = Literal[7]
ENET_PROTOCOL_COMMAND_SEND_FRAGMENT = Literal[8]
ENET_PROTOCOL_COMMAND_SEND_UNSEQUENCED = Literal[9]
ENET_PROTOCOL_COMMAND_BANDWIDTH_LIMIT = Literal[10]
ENET_PROTOCOL_COMMAND_THROTTLE_CONFIGURE = Literal[11]
ENET_PROTOCOL_COMMAND_SEND_UNRELIABLE_FRAGMENT = Literal[12]
ENET_PROTOCOL_COMMAND_COUNT = Literal[13]
ENET_PROTOCOL_COMMAND_MASK = Literal[0x0F]

ENET_PROTOCOL_COMMAND_FLAG_ACKNOWLEDGE = Literal[128]  # 1 << 7
ENET_PROTOCOL_COMMAND_FLAG_UNSEQUENCED = Literal[64]  # 1 << 6
ENET_PROTOCOL_HEADER_FLAG_COMPRESSED = Literal[16384]  # 1 << 14
ENET_PROTOCOL_HEADER_FLAG_SENT_TIME = Literal[32768]  # 1 << 15
ENET_PROTOCOL_HEADER_FLAG_MASK = ENET_PROTOCOL_HEADER_FLAG_COMPRESSED | ENET_PROTOCOL_HEADER_FLAG_SENT_TIME
ENET_PROTOCOL_HEADER_SESSION_MASK = Literal[12288]  # 3 << 12
ENET_PROTOCOL_HEADER_SESSION_SHIFT = Literal[12]

ENetSocket = c_int

class _ENetSocks5Ipv4InnerStruct(Structure):
    part4: c_uint8
    part3: c_uint8
    part2: c_uint8
    part1: c_uint8

class _ENetSocks5Ipv4Union(Union):
    addr: c_uint32
    parts: STATIC_ARRAY[c_uint8, Literal[4]]
    s: _ENetSocks5Ipv4InnerStruct

class ENetSocks5Ipv4(Structure):
    u: _ENetSocks5Ipv4Union
    port: c_uint16

class ENetSocks5Header(Structure):
    reserved: c_uint16
    fragment: c_uint8
    addressType: c_uint8
    ipv4: ENetSocks5Ipv4

class ENetSocks5Authentication(Structure):
    username: c_char_p
    password: c_char_p

class ENetSocks5Info(Structure):
    ip: c_char_p
    port: c_uint16
    auth: ENetSocks5Authentication

class ENetSocks5State(Enum):
    ENET_SOCKS5_STATE_NONE = 0
    ENET_SOCKS5_STATE_SEND_AUTH_REQUEST = 1
    ENET_SOCKS5_STATE_RECEIVE_AUTH_RESPONSE = 2
    ENET_SOCKS5_STATE_SEND_AUTH_REQUEST_USERNAME = 3
    ENET_SOCKS5_STATE_RECEIVE_AUTH_RESPONSE_USERNAME = 4
    ENET_SOCKS5_STATE_SEND_REQUEST = 5
    ENET_SOCKS5_STATE_RECEIVE_RESPONSE = 6
    ENET_SOCKS5_STATE_CONNECTION_FAILED = 7
    ENET_SOCKS5_STATE_CONNECTED = 8

class ENetProtocolHeader(Structure):
    peerID: c_uint16
    sentTime: c_uint16

class ENetNewProtocolHeader(Structure):
    integrity: STATIC_ARRAY[c_uint16, Literal[3]]
    peerID: c_uint16
    sentTime: c_uint16

class ENetProtocolCommandHeader(Structure):
    command: c_uint8
    channelID: c_uint8
    reliableSequenceNumber: c_uint16

class ENetProtocolAcknowledge(Structure):
    header: ENetProtocolCommandHeader
    receivedReliableSequenceNumber: c_uint16
    receivedSentTime: c_uint16

class ENetProtocolConnect(Structure):
    header: ENetProtocolCommandHeader
    outgoingPeerID: c_uint16
    incomingSessionID: c_uint8
    outgoingSessionID: c_uint8
    mtu: c_uint32
    windowSize: c_uint32
    channelCount: c_uint32
    incomingBandwidth: c_uint32
    outgoingBandwidth: c_uint32
    packetThrottleInterval: c_uint32
    packetThrottleAcceleration: c_uint32
    packetThrottleDeceleration: c_uint32
    connectID: c_uint32
    data: c_uint32

class ENetProtocolVerifyConnect(Structure):
    header: ENetProtocolCommandHeader
    outgoingPeerID: c_uint16
    incomingSessionID: c_uint8
    outgoingSessionID: c_uint8
    mtu: c_uint32
    windowSize: c_uint32
    channelCount: c_uint32
    incomingBandwidth: c_uint32
    outgoingBandwidth: c_uint32
    packetThrottleInterval: c_uint32
    packetThrottleAcceleration: c_uint32
    packetThrottleDeceleration: c_uint32
    connectID: c_uint32

class ENetProtocolBandwidthLimit(Structure):
    header: ENetProtocolCommandHeader
    incomingBandwidth: c_uint32
    outgoingBandwidth: c_uint32

class ENetProtocolThrottleConfigure(Structure):
    header: ENetProtocolCommandHeader
    packetThrottleInterval: c_uint32
    packetThrottleAcceleration: c_uint32
    packetThrottleDeceleration: c_uint32

class ENetProtocolDisconnect(Structure):
    header: ENetProtocolCommandHeader
    data: c_uint32

class ENetProtocolPing(Structure):
    header: ENetProtocolCommandHeader

class ENetProtocolSendReliable(Structure):
    header: ENetProtocolCommandHeader
    dataLength: c_uint16

class ENetProtocolSendUnreliable(Structure):
    header: ENetProtocolCommandHeader
    unreliableSequenceNumber: c_uint16
    dataLength: c_uint16

class ENetProtocolSendUnsequenced(Structure):
    header: ENetProtocolCommandHeader
    unsequencedGroup: c_uint16
    dataLength: c_uint16

class ENetProtocolSendFragment(Structure):
    header: ENetProtocolCommandHeader
    startSequenceNumber: c_uint16
    dataLength: c_uint16
    fragmentCount: c_uint32
    fragmentNumber: c_uint32
    totalLength: c_uint32
    fragmentOffset: c_uint32

class ENetProtocol(Union):
    header: ENetProtocolCommandHeader
    acknowledge: ENetProtocolAcknowledge
    connect: ENetProtocolConnect
    verifyConnect: ENetProtocolVerifyConnect
    disconnect: ENetProtocolDisconnect
    ping: ENetProtocolPing
    sendReliable: ENetProtocolSendReliable
    sendUnreliable: ENetProtocolSendUnreliable
    sendUnsequenced: ENetProtocolSendUnsequenced
    sendFragment: ENetProtocolSendFragment
    bandwidthLimit: ENetProtocolBandwidthLimit
    throttleConfigure: ENetProtocolThrottleConfigure

class ENetBuffer(Structure):
    data: c_void_p
    dataLength: c_size_t

ENET_BUFFER_MAXIMUM = Literal[65]

class ENetChecksumCallback(Protocol):
    def __call__(self, buffer: Pointer[ENetBuffer], bufferCount: c_size_t) -> c_uint32: ...

class CompressorCompressCallback(Protocol):
    def __call__(
        self,
        context: c_void_p,
        inBuffers: Pointer[ENetBuffer],
        inBufferCount: c_size_t,
        inLimit: c_size_t,
        outData: Pointer[ctypes.c_uint8],
        outLimit: c_size_t,
    ) -> c_size_t: ...

class CompressorDecompressCallback(Protocol):
    def __call__(
        self,
        context: c_void_p,
        inData: Pointer[ctypes.c_uint8],
        inLimit: c_size_t,
        outData: Pointer[ctypes.c_uint8],
        outLimit: c_size_t,
    ) -> c_size_t: ...

class CompressorDestroyCallback(Protocol):
    def __call__(self, context: c_void_p) -> None: ...

class ENetInterceptCallback(Protocol):
    def __call__(self, host: Pointer[ENetHost], event: Pointer[ENetEvent]) -> c_int: ...

class ENetCompressor(Structure):
    context: c_void_p
    compress: CompressorCompressCallback
    decompress: CompressorDecompressCallback
    destroy: CompressorDestroyCallback

class ENetHost(Structure):
    socket: ENetSocket
    proxySocket: ENetSocket
    address: ENetAddress
    proxyAddress: ENetAddress
    proxyHeader: ENetSocks5Header
    proxyInfo: ENetSocks5Info
    proxyState: c_int  # ENetSocks5State
    incomingBandwidth: c_uint32
    outgoingBandwidth: c_uint32
    bandwidthThrottleEpoch: c_uint32
    mtu: c_uint32
    randomSeed: c_uint32
    recalculateBandwidthLimits: c_int
    peers: Pointer[ENetPeer]
    peerCount: c_size_t
    channelLimit: c_size_t
    serviceTime: c_uint32
    dispatchQueue: ENetList
    totalQueued: c_uint32
    packetSize: c_size_t
    headerFlags: c_uint16
    commands: STATIC_ARRAY[ENetProtocol, ENET_PROTOCOL_MAXIMUM_PACKET_COMMANDS]
    commandCount: c_size_t
    buffers: STATIC_ARRAY[ENetBuffer, ENET_BUFFER_MAXIMUM]
    bufferCount: c_size_t
    checksum: ENetChecksumCallback
    compressor: ENetCompressor
    packetData: STATIC_ARRAY[STATIC_ARRAY[c_uint8, Literal[2]], Literal[ENET_PROTOCOL_MAXIMUM_MTU]]
    receivedAddress: ENetAddress
    receivedData: Pointer[ctypes.c_uint8]
    receivedDataLength: c_size_t
    totalSentData: c_uint32
    totalSentPackets: c_uint32
    totalReceivedData: c_uint32
    totalReceivedPackets: c_uint32
    intercept: ENetInterceptCallback
    connectedPeers: c_size_t
    bandwidthLimitedPeers: c_size_t
    duplicatePeers: c_size_t
    maximumPacketSize: c_size_t
    maximumWaitingData: c_size_t
    usingNewPacket: c_int
    usingNewPacketForServer: c_int
    usingProxy: c_int

def enet_initialize() -> c_int: ...
def enet_host_create(
    address: Pointer[ENetAddress],
    peerCount: c_size_t,
    channelLimit: c_size_t,
    incomingBandwidth: c_int,
    outgoingBandwidth: c_int,
) -> Pointer[ENetHost]: ...
def enet_host_service(host: Pointer[ENetHost], event: Pointer[ENetEvent], timeout: c_uint32) -> c_int: ...
def enet_address_set_host(
    address: Pointer[ENetAddress],
    hostName: c_char_p,
) -> c_int: ...
def enet_address_set_host_ip(
    address: Pointer[ENetAddress],
    hostName: c_char_p,
) -> c_int: ...
def enet_host_connect(
    host: Pointer[ENetHost],
    address: Pointer[ENetAddress],
    channelCount: c_size_t,
    data: c_uint32,
) -> Pointer[ENetPeer]: ...
def enet_host_use_new_packet(host: Pointer[ENetHost]) -> None: ...
def enet_host_use_new_packet_for_server(host: Pointer[ENetHost]) -> None: ...
def enet_host_use_crc32(host: Pointer[ENetHost]) -> None: ...
def enet_host_compress_with_range_coder(host: Pointer[ENetHost]) -> c_int: ...
def enet_host_flush(host: Pointer[ENetHost]) -> None: ...
def enet_host_destroy(host: Pointer[ENetHost]) -> None: ...
def enet_packet_destroy(packet: Pointer[ENetPacket]) -> None: ...
def enet_peer_send(
    peer: Pointer[ENetPeer],
    channelID: c_uint8,
    packet: Pointer[ENetPacket],
) -> c_int: ...
def enet_packet_create(
    data: c_void_p,
    dataLength: c_size_t,
    flags: c_uint32,
) -> Pointer[ENetPacket]: ...
def enet_peer_disconnect(peer: Pointer[ENetPeer], data: c_uint32) -> None: ...
def enet_peer_disconnect_now(peer: Pointer[ENetPeer], data: c_uint32) -> None: ...
def enet_peer_timeout(
    peer: Pointer[ENetPeer],
    timeoutLimit: c_uint32,
    timeoutMinimum: c_uint32,
    timeoutMaximum: c_uint32,
) -> None: ...
