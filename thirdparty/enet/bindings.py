import ctypes
from ctypes import _Pointer
from enum import Enum, IntEnum, IntFlag
from sys import platform
from typing import cast

from gtools.core.dll_loader import DLL

enet = DLL("thirdparty/enet/enet", "enet")
if not enet.supported:
    raise RuntimeError(f"enet is not supported on {platform}")


class Pointer[T](_Pointer): ...


def byref[T: ctypes.Structure](val: T, offset: int = 0) -> Pointer[T]:
    return cast(Pointer[T], ctypes.byref(val, offset))


class ENetAddress(ctypes.Structure):
    _fields_ = [
        ("host", ctypes.c_uint32),
        ("port", ctypes.c_uint16),
    ]


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


class ENetPacket(ctypes.Structure):
    pass


ENetPacketFreeCallback = ctypes.CFUNCTYPE(None, ctypes.POINTER(ENetPacket))

ENetPacket._fields_ = [
    ("referenceCount", ctypes.c_size_t),
    ("flags", ctypes.c_uint32),  # ENetPacketFlag
    ("data", ctypes.POINTER(ctypes.c_uint8)),
    ("dataLength", ctypes.c_size_t),
    ("freeCallback", ENetPacketFreeCallback),
    ("userData", ctypes.c_void_p),
]


class ENetListNode(ctypes.Structure):
    pass


ENetListNode._fields_ = [
    ("next", ctypes.POINTER(ENetListNode)),
    ("previous", ctypes.POINTER(ENetListNode)),
]


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


class ENetList(ctypes.Structure):
    _fields_ = [
        ("sentinel", ENetListNode),
    ]


class ENetChannel(ctypes.Structure):
    _fields_ = [
        ("outgoingReliableSequenceNumber", ctypes.c_uint16),
        ("outgoingUnreliableSequenceNumber", ctypes.c_uint16),
        ("usedReliableWindows", ctypes.c_uint16),
        ("reliableWindows", ctypes.c_uint16),
        ("incomingReliableSequenceNumber", ctypes.c_uint16),
        ("incomingUnreliableSequenceNumber", ctypes.c_uint16),
        ("incomingReliableCommands", ENetList),
        ("incomingUnreliableCommands", ENetList),
    ]

class ENetHost(ctypes.Structure):
    pass


class ENetPeer(ctypes.Structure):
    _fields_ = [
        ("dispatchList", ENetListNode),
        ("host", ctypes.POINTER(ENetHost)),
        ("outgoingPeerID", ctypes.c_uint16),
        ("incomingPeerID", ctypes.c_uint16),
        ("connectID", ctypes.c_uint32),
        ("outgoingSessionID", ctypes.c_uint8),
        ("incomingSessionID", ctypes.c_uint8),
        ("address", ENetAddress),  # Internet address of the peer
        ("data", ctypes.c_void_p),  # Application private data,   may be freely modified
        ("state", ctypes.c_int),  # EnetPeerState
        ("channels", ctypes.POINTER(ENetChannel)),
        ("channelCount", ctypes.c_size_t),  # Number of channels allocated for communication with peer
        ("incomingBandwidth", ctypes.c_uint32),  # Downstream bandwidth of the client in bytes/second
        ("outgoingBandwidth", ctypes.c_uint32),  # Upstream bandwidth of the client in bytes/second
        ("incomingBandwidthThrottleEpoch", ctypes.c_uint32),
        ("outgoingBandwidthThrottleEpoch", ctypes.c_uint32),
        ("incomingDataTotal", ctypes.c_uint32),
        ("outgoingDataTotal", ctypes.c_uint32),
        ("lastSendTime", ctypes.c_uint32),
        ("lastReceiveTime", ctypes.c_uint32),
        ("nextTimeout", ctypes.c_uint32),
        ("earliestTimeout", ctypes.c_uint32),
        ("packetLossEpoch", ctypes.c_uint32),
        ("packetsSent", ctypes.c_uint32),
        ("packetsLost", ctypes.c_uint32),
        ("packetLoss", ctypes.c_uint32),  # mean packet loss of reliable packets as a ratio with respect to the constant ENET_PEER_PACKET_LOSS_SCALE
        ("packetLossVariance", ctypes.c_uint32),
        ("packetThrottle", ctypes.c_uint32),
        ("packetThrottleLimit", ctypes.c_uint32),
        ("packetThrottleCounter", ctypes.c_uint32),
        ("packetThrottleEpoch", ctypes.c_uint32),
        ("packetThrottleAcceleration", ctypes.c_uint32),
        ("packetThrottleDeceleration", ctypes.c_uint32),
        ("packetThrottleInterval", ctypes.c_uint32),
        ("pingInterval", ctypes.c_uint32),
        ("timeoutLimit", ctypes.c_uint32),
        ("timeoutMinimum", ctypes.c_uint32),
        ("timeoutMaximum", ctypes.c_uint32),
        ("lastRoundTripTime", ctypes.c_uint32),
        ("lowestRoundTripTime", ctypes.c_uint32),
        ("lastRoundTripTimeVariance", ctypes.c_uint32),
        ("highestRoundTripTimeVariance", ctypes.c_uint32),
        ("roundTripTime", ctypes.c_uint32),  # mean round trip time (RTT), in milliseconds, between sending a reliable packet and receiving its acknowledgement
        ("roundTripTimeVariance", ctypes.c_uint32),
        ("mtu", ctypes.c_uint32),
        ("windowSize", ctypes.c_uint32),
        ("reliableDataInTransit", ctypes.c_uint32),
        ("outgoingReliableSequenceNumber", ctypes.c_uint16),
        ("acknowledgements", ENetList),
        ("sentReliableCommands", ENetList),
        ("outgoingSendReliableCommands", ENetList),
        ("outgoingCommands", ENetList),
        ("dispatchedCommands", ENetList),
        ("flags", ctypes.c_uint16),
        ("reserved", ctypes.c_uint16),
        ("incomingUnsequencedGroup", ctypes.c_uint16),
        ("outgoingUnsequencedGroup", ctypes.c_uint16),
        ("unsequencedWindow", ctypes.c_uint32 * 32),
        ("eventData", ctypes.c_uint32),
        ("totalWaitingData", ctypes.c_size_t),
    ]


class ENetEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),  # ENetEventType
        ("peer", ctypes.POINTER(ENetPeer)),
        ("channelID", ctypes.c_uint8),
        ("data", ctypes.c_uint32),
        ("packet", ctypes.POINTER(ENetPacket)),
    ]


ENET_PROTOCOL_MINIMUM_MTU = 576
ENET_PROTOCOL_MAXIMUM_MTU = 4096
ENET_PROTOCOL_MAXIMUM_PACKET_COMMANDS = 32
ENET_PROTOCOL_MINIMUM_WINDOW_SIZE = 4096
ENET_PROTOCOL_MAXIMUM_WINDOW_SIZE = 65536
ENET_PROTOCOL_MINIMUM_CHANNEL_COUNT = 1
ENET_PROTOCOL_MAXIMUM_CHANNEL_COUNT = 255
ENET_PROTOCOL_MAXIMUM_PEER_ID = 0xFFF
ENET_PROTOCOL_MAXIMUM_FRAGMENT_COUNT = 1024 * 1024

ENET_PROTOCOL_COMMAND_NONE = 0
ENET_PROTOCOL_COMMAND_ACKNOWLEDGE = 1
ENET_PROTOCOL_COMMAND_CONNECT = 2
ENET_PROTOCOL_COMMAND_VERIFY_CONNECT = 3
ENET_PROTOCOL_COMMAND_DISCONNECT = 4
ENET_PROTOCOL_COMMAND_PING = 5
ENET_PROTOCOL_COMMAND_SEND_RELIABLE = 6
ENET_PROTOCOL_COMMAND_SEND_UNRELIABLE = 7
ENET_PROTOCOL_COMMAND_SEND_FRAGMENT = 8
ENET_PROTOCOL_COMMAND_SEND_UNSEQUENCED = 9
ENET_PROTOCOL_COMMAND_BANDWIDTH_LIMIT = 10
ENET_PROTOCOL_COMMAND_THROTTLE_CONFIGURE = 11
ENET_PROTOCOL_COMMAND_SEND_UNRELIABLE_FRAGMENT = 12
ENET_PROTOCOL_COMMAND_COUNT = 13
ENET_PROTOCOL_COMMAND_MASK = 0x0F

ENET_PROTOCOL_COMMAND_FLAG_ACKNOWLEDGE = 1 << 7
ENET_PROTOCOL_COMMAND_FLAG_UNSEQUENCED = 1 << 6
ENET_PROTOCOL_HEADER_FLAG_COMPRESSED = 1 << 14
ENET_PROTOCOL_HEADER_FLAG_SENT_TIME = 1 << 15
ENET_PROTOCOL_HEADER_FLAG_MASK = ENET_PROTOCOL_HEADER_FLAG_COMPRESSED | ENET_PROTOCOL_HEADER_FLAG_SENT_TIME
ENET_PROTOCOL_HEADER_SESSION_MASK = 3 << 12
ENET_PROTOCOL_HEADER_SESSION_SHIFT = 12


ENetSocket = ctypes.c_int


class _ENetSocks5Ipv4InnerStruct(ctypes.Structure):
    _fields_ = [
        ("part4", ctypes.c_uint8),
        ("part3", ctypes.c_uint8),
        ("part2", ctypes.c_uint8),
        ("part1", ctypes.c_uint8),
    ]


class _ENetSocks5Ipv4Union(ctypes.Union):
    _fields_ = [
        ("addr", ctypes.c_uint32),
        ("parts", ctypes.c_uint8 * 4),
        ("s", _ENetSocks5Ipv4InnerStruct),
    ]


class ENetSocks5Ipv4(ctypes.Structure):
    _pack_ = 1
    _anonymous_ = ("u",)
    _fields_ = [
        ("u", _ENetSocks5Ipv4Union),
        ("port", ctypes.c_uint16),
    ]


class ENetSocks5Header(ctypes.Structure):
    _fields_ = [
        ("reserved", ctypes.c_uint16),
        ("fragment", ctypes.c_uint8),
        ("addressType", ctypes.c_uint8),
        ("ipv4", ENetSocks5Ipv4),
    ]


class ENetSocks5Authentication(ctypes.Structure):
    _fields_ = [
        ("username", ctypes.c_char_p),
        ("password", ctypes.c_char_p),
    ]


class ENetSocks5Info(ctypes.Structure):
    _fields_ = [
        ("ip", ctypes.c_char_p),
        ("port", ctypes.c_uint16),
        ("auth", ENetSocks5Authentication),
    ]


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


class ENetProtocolHeader(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("peerID", ctypes.c_uint16),
        ("sentTime", ctypes.c_uint16),
    ]


class ENetNewProtocolHeader(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("integrity", ctypes.c_uint16 * 3),
        ("peerID", ctypes.c_uint16),
        ("sentTime", ctypes.c_uint16),
    ]


class ENetProtocolCommandHeader(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("command", ctypes.c_uint8),
        ("channelID", ctypes.c_uint8),
        ("reliableSequenceNumber", ctypes.c_uint16),
    ]


class ENetProtocolAcknowledge(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("header", ENetProtocolCommandHeader),
        ("receivedReliableSequenceNumber", ctypes.c_uint16),
        ("receivedSentTime", ctypes.c_uint16),
    ]


class ENetProtocolConnect(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("header", ENetProtocolCommandHeader),
        ("outgoingPeerID", ctypes.c_uint16),
        ("incomingSessionID", ctypes.c_uint8),
        ("outgoingSessionID", ctypes.c_uint8),
        ("mtu", ctypes.c_uint32),
        ("windowSize", ctypes.c_uint32),
        ("channelCount", ctypes.c_uint32),
        ("incomingBandwidth", ctypes.c_uint32),
        ("outgoingBandwidth", ctypes.c_uint32),
        ("packetThrottleInterval", ctypes.c_uint32),
        ("packetThrottleAcceleration", ctypes.c_uint32),
        ("packetThrottleDeceleration", ctypes.c_uint32),
        ("connectID", ctypes.c_uint32),
        ("data", ctypes.c_uint32),
    ]


class ENetProtocolVerifyConnect(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("header", ENetProtocolCommandHeader),
        ("outgoingPeerID", ctypes.c_uint16),
        ("incomingSessionID", ctypes.c_uint8),
        ("outgoingSessionID", ctypes.c_uint8),
        ("mtu", ctypes.c_uint32),
        ("windowSize", ctypes.c_uint32),
        ("channelCount", ctypes.c_uint32),
        ("incomingBandwidth", ctypes.c_uint32),
        ("outgoingBandwidth", ctypes.c_uint32),
        ("packetThrottleInterval", ctypes.c_uint32),
        ("packetThrottleAcceleration", ctypes.c_uint32),
        ("packetThrottleDeceleration", ctypes.c_uint32),
        ("connectID", ctypes.c_uint32),
    ]


class ENetProtocolBandwidthLimit(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("header", ENetProtocolCommandHeader),
        ("incomingBandwidth", ctypes.c_uint32),
        ("outgoingBandwidth", ctypes.c_uint32),
    ]


class ENetProtocolThrottleConfigure(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("header", ENetProtocolCommandHeader),
        ("packetThrottleInterval", ctypes.c_uint32),
        ("packetThrottleAcceleration", ctypes.c_uint32),
        ("packetThrottleDeceleration", ctypes.c_uint32),
    ]


class ENetProtocolDisconnect(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("header", ENetProtocolCommandHeader),
        ("data", ctypes.c_uint32),
    ]


class ENetProtocolPing(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("header", ENetProtocolCommandHeader),
    ]


class ENetProtocolSendReliable(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("header", ENetProtocolCommandHeader),
        ("dataLength", ctypes.c_uint16),
    ]


class ENetProtocolSendUnreliable(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("header", ENetProtocolCommandHeader),
        ("unreliableSequenceNumber", ctypes.c_uint16),
        ("dataLength", ctypes.c_uint16),
    ]


class ENetProtocolSendUnsequenced(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("header", ENetProtocolCommandHeader),
        ("unsequencedGroup", ctypes.c_uint16),
        ("dataLength", ctypes.c_uint16),
    ]


class ENetProtocolSendFragment(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("header", ENetProtocolCommandHeader),
        ("startSequenceNumber", ctypes.c_uint16),
        ("dataLength", ctypes.c_uint16),
        ("fragmentCount", ctypes.c_uint32),
        ("fragmentNumber", ctypes.c_uint32),
        ("totalLength", ctypes.c_uint32),
        ("fragmentOffset", ctypes.c_uint32),
    ]


class ENetProtocol(ctypes.Union):
    _pack_ = 1
    _fields_ = [
        ("header", ENetProtocolCommandHeader),
        ("acknowledge", ENetProtocolAcknowledge),
        ("connect", ENetProtocolConnect),
        ("verifyConnect", ENetProtocolVerifyConnect),
        ("disconnect", ENetProtocolDisconnect),
        ("ping", ENetProtocolPing),
        ("sendReliable", ENetProtocolSendReliable),
        ("sendUnreliable", ENetProtocolSendUnreliable),
        ("sendUnsequenced", ENetProtocolSendUnsequenced),
        ("sendFragment", ENetProtocolSendFragment),
        ("bandwidthLimit", ENetProtocolBandwidthLimit),
        ("throttleConfigure", ENetProtocolThrottleConfigure),
    ]


class ENetBuffer(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.c_void_p),
        ("dataLength", ctypes.c_size_t),
    ]


ENET_BUFFER_MAXIMUM = 1 + 2 * ENET_PROTOCOL_MAXIMUM_PACKET_COMMANDS

ENetChecksumCallback = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.POINTER(ENetBuffer), ctypes.c_size_t)

# size_t (ENET_CALLBACK * compress) (void * context, const ENetBuffer * inBuffers, size_t inBufferCount, size_t inLimit, enet_uint8 * outData, size_t outLimit);
# size_t (ENET_CALLBACK * decompress) (void * context, const enet_uint8 * inData, size_t inLimit, enet_uint8 * outData, size_t outLimit);
# void (ENET_CALLBACK * destroy) (void * context);

CompressorCompressCallback = ctypes.CFUNCTYPE(ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ENetBuffer), ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint8, ctypes.c_size_t)
CompressorDecompressCallback = ctypes.CFUNCTYPE(ctypes.c_size_t, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t, ctypes.c_uint8, ctypes.c_size_t)
CompressorDestroyCallback = ctypes.CFUNCTYPE(None, ctypes.c_void_p)


class ENetCompressor(ctypes.Structure):
    _fields_ = [
        ("context", ctypes.c_void_p),  # Context data for the compressor. Must be non-NULL.
        (
            "compress",
            CompressorCompressCallback,
        ),  # Compresses from inBuffers[0:inBufferCount-1], containing inLimit bytes, to outData, outputting at most outLimit bytes. Should return 0 on failure.
        (
            "decompress",
            CompressorDecompressCallback,
        ),  # Decompresses from inData, containing inLimit bytes, to outData, outputting at most outLimit bytes. Should return 0 on failure.
        ("destroy", CompressorDestroyCallback),  # Destroys the context when compression is disabled or the host is destroyed. May be NULL.
    ]


# typedef int (ENET_CALLBACK * ENetInterceptCallback) (struct _ENetHost * host, struct _ENetEvent * event);
ENetInterceptCallback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ENetHost), ctypes.POINTER(ENetEvent))

ENetHost._fields_ = [
    ("socket", ENetSocket),
    ("proxySocket", ENetSocket),
    ("address", ENetAddress),  # Internet address of the host
    ("proxyAddress", ENetAddress),
    ("proxyHeader", ENetSocks5Header),
    ("proxyInfo", ENetSocks5Info),
    ("proxyState", ctypes.c_int),  # ENetSocks5State
    ("incomingBandwidth", ctypes.c_uint32),  # downstream bandwidth of the host
    ("outgoingBandwidth", ctypes.c_uint32),  # upstream bandwidth of the host
    ("bandwidthThrottleEpoch", ctypes.c_uint32),
    ("mtu", ctypes.c_uint32),
    ("randomSeed", ctypes.c_uint32),
    ("recalculateBandwidthLimits", ctypes.c_int),
    ("peers", ctypes.POINTER(ENetPeer)),  # array of peers allocated for this host
    ("peerCount", ctypes.c_size_t),  # number of peers allocated for this host
    ("channelLimit", ctypes.c_size_t),  # maximum number of channels allowed for connected peers
    ("serviceTime", ctypes.c_uint32),
    ("dispatchQueue", ENetList),
    ("totalQueued", ctypes.c_uint32),
    ("packetSize", ctypes.c_size_t),
    ("headerFlags", ctypes.c_uint16),
    ("commands", ENetProtocol * ENET_PROTOCOL_MAXIMUM_PACKET_COMMANDS),
    ("commandCount", ctypes.c_size_t),
    ("buffers", ENetBuffer * ENET_BUFFER_MAXIMUM),
    ("bufferCount", ctypes.c_size_t),
    ("checksum", ENetChecksumCallback),  # callback the user can set to enable packet checksums for this host
    ("compressor", ENetCompressor),
    ("packetData", (ctypes.c_uint8 * ENET_PROTOCOL_MAXIMUM_MTU) * 2),
    ("receivedAddress", ENetAddress),
    ("receivedData", ctypes.POINTER(ctypes.c_uint8)),
    ("receivedDataLength", ctypes.c_size_t),
    ("totalSentData", ctypes.c_uint32),  # total data sent, user should reset to 0 as needed to prevent overflow
    ("totalSentPackets", ctypes.c_uint32),  # total UDP packets sent, user should reset to 0 as needed to prevent overflow
    ("totalReceivedData", ctypes.c_uint32),  # total data received, user should reset to 0 as needed to prevent overflow
    ("totalReceivedPackets", ctypes.c_uint32),  # total UDP packets received, user should reset to 0 as needed to prevent overflow
    ("intercept", ENetInterceptCallback),  # callback the user can set to intercept received raw UDP packets
    ("connectedPeers", ctypes.c_size_t),
    ("bandwidthLimitedPeers", ctypes.c_size_t),
    ("duplicatePeers", ctypes.c_size_t),  # optional number of allowed peers from duplicate IPs, defaults to ENET_PROTOCOL_MAXIMUM_PEER_ID
    ("maximumPacketSize", ctypes.c_size_t),  # the maximum allowable packet size that may be sent or received on a peer
    ("maximumWaitingData", ctypes.c_size_t),  # the maximum aggregate amount of buffer space a peer may use waiting for packets to be delivered
    ("usingNewPacket", ctypes.c_int),
    ("usingNewPacketForServer", ctypes.c_int),
    ("usingProxy", ctypes.c_int),
]


enet_initialize = enet.enet_initialize
enet_initialize.argtypes = []
enet_initialize.restype = ctypes.c_int

enet_host_create = enet.enet_host_create
enet_host_create.argtypes = [
    ctypes.POINTER(ENetAddress),
    ctypes.c_size_t,
    ctypes.c_size_t,
    ctypes.c_int,
    ctypes.c_int,
]
enet_host_create.restype = ctypes.POINTER(ENetHost)

enet_host_service = enet.enet_host_service
enet_host_service.argtypes = [
    ctypes.POINTER(ENetHost),
    ctypes.POINTER(ENetEvent),
    ctypes.c_uint32,
]
enet_host_service.restype = ctypes.c_int

enet_address_set_host = enet.enet_address_set_host
enet_address_set_host.argtypes = [ctypes.POINTER(ENetAddress), ctypes.c_char_p]
enet_address_set_host.restype = ctypes.c_int

enet_address_set_host_ip = enet.enet_address_set_host_ip
enet_address_set_host_ip.argtypes = [ctypes.POINTER(ENetAddress), ctypes.c_char_p]
enet_address_set_host_ip.restype = ctypes.c_int

enet_host_connect = enet.enet_host_connect
enet_host_connect.argtypes = [
    ctypes.POINTER(ENetHost),
    ctypes.POINTER(ENetAddress),
    ctypes.c_size_t,
    ctypes.c_uint32,
]
enet_host_connect.restype = ctypes.POINTER(ENetPeer)

enet_host_use_new_packet = enet.enet_host_use_new_packet
enet_host_use_new_packet.argtypes = [ctypes.POINTER(ENetHost)]
enet_host_use_new_packet.restype = None

enet_host_use_new_packet_for_server = enet.enet_host_use_new_packet_for_server
enet_host_use_new_packet_for_server.argtypes = [ctypes.POINTER(ENetHost)]
enet_host_use_new_packet_for_server.restype = None

enet_host_use_crc32 = enet.enet_host_use_crc32
enet_host_use_crc32.argtypes = [ctypes.POINTER(ENetHost)]
enet_host_use_crc32.restype = None

enet_host_compress_with_range_coder = enet.enet_host_compress_with_range_coder
enet_host_compress_with_range_coder.argtypes = [ctypes.POINTER(ENetHost)]
enet_host_compress_with_range_coder.restype = ctypes.c_int

enet_host_flush = enet.enet_host_flush
enet_host_flush.argtypes = [ctypes.POINTER(ENetHost)]
enet_host_flush.restype = None

enet_host_destroy = enet.enet_host_destroy
enet_host_destroy.argtypes = [ctypes.POINTER(ENetHost)]
enet_host_destroy.restype = None

enet_packet_destroy = enet.enet_packet_destroy
enet_packet_destroy.argtypes = [ctypes.POINTER(ENetPacket)]
enet_packet_destroy.restype = None

enet_peer_send = enet.enet_peer_send
enet_peer_send.argtypes = [
    ctypes.POINTER(ENetPeer),
    ctypes.c_uint8,
    ctypes.POINTER(ENetPacket),
]
enet_peer_send.restype = ctypes.c_int

enet_packet_create = enet.enet_packet_create
enet_packet_create.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
enet_packet_create.restype = ctypes.POINTER(ENetPacket)

enet_peer_disconnect = enet.enet_peer_disconnect
enet_peer_disconnect.argtypes = [ctypes.POINTER(ENetPeer), ctypes.c_uint32]
enet_peer_disconnect.restype = None

enet_peer_disconnect_now = enet.enet_peer_disconnect_now
enet_peer_disconnect_now.argtypes = [ctypes.POINTER(ENetPeer), ctypes.c_uint32]
enet_peer_disconnect_now.restype = None

enet_peer_timeout = enet.enet_peer_timeout
enet_peer_timeout.argtypes = [
    ctypes.POINTER(ENetPeer),
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_uint32,
]
enet_peer_timeout.restype = None
