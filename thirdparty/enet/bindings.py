import ctypes
from ctypes import _Pointer
from enum import IntEnum, IntFlag
from pathlib import Path
from sys import platform
from typing import cast

if platform == "linux" or platform == "linux2":
    lib_name = "libenet.so"
elif platform == "darwin":
    lib_name = "enet.dylib"
elif platform == "win32":
    lib_name = "enet.dll"
else:
    raise RuntimeError(f"unhandled platform: {platform}")

enet = ctypes.CDLL(Path(__file__).parent / "enet" / lib_name)


class __Pointer[T](_Pointer): ...


def byref[T: ctypes.Structure](val: T, offset: int = 0) -> _Pointer[T]:
    return cast(__Pointer[T], ctypes.byref(val, offset))


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


class ENetPeer(ctypes.Structure):
    _fields_ = [
        ("dispatchList", ENetListNode),
        ("host", ctypes.c_void_p),
        ("outgoingPeerID", ctypes.c_uint16),
        ("incomingPeerID", ctypes.c_uint16),
        ("connectID", ctypes.c_uint32),
        ("outgoingSessionID", ctypes.c_uint8),
        ("incomingSessionID", ctypes.c_uint8),
        ("address", ENetAddress),  # Internet address of the peer
        ("data", ctypes.c_void_p),  # Application private data,   may be freely modified
        ("state", ctypes.c_int),  # EnetPeerState
        ("channels", ctypes.POINTER(ENetChannel)),
        (
            "channelCount",
            ctypes.c_size_t,
        ),  # Number of channels allocated for communication with peer
        (
            "incomingBandwidth",
            ctypes.c_uint32,
        ),  # Downstream bandwidth of the client in bytes/second
        (
            "outgoingBandwidth",
            ctypes.c_uint32,
        ),  # Upstream bandwidth of the client in bytes/second
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
        (
            "packetLoss",
            ctypes.c_uint32,
        ),  # mean packet loss of reliable packets as a ratio with respect to the constant ENET_PEER_PACKET_LOSS_SCALE
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
        (
            "roundTripTime",
            ctypes.c_uint32,
        ),  # mean round trip time (RTT), in milliseconds, between sending a reliable packet and receiving its acknowledgement
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
enet_host_create.restype = ctypes.c_void_p

enet_host_service = enet.enet_host_service
enet_host_service.argtypes = [
    ctypes.c_void_p,
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
    ctypes.c_void_p,
    ctypes.POINTER(ENetAddress),
    ctypes.c_size_t,
    ctypes.c_uint32,
]
enet_host_connect.restype = ctypes.POINTER(ENetPeer)

enet_host_use_new_packet = enet.enet_host_use_new_packet
enet_host_use_new_packet.argtypes = [ctypes.c_void_p]
enet_host_use_new_packet.restype = None

enet_host_use_new_packet_for_server = enet.enet_host_use_new_packet_for_server
enet_host_use_new_packet_for_server.argtypes = [ctypes.c_void_p]
enet_host_use_new_packet_for_server.restype = None

enet_host_use_crc32 = enet.enet_host_use_crc32
enet_host_use_crc32.argtypes = [ctypes.c_void_p]
enet_host_use_crc32.restype = None

enet_host_compress_with_range_coder = enet.enet_host_compress_with_range_coder
enet_host_compress_with_range_coder.argtypes = [ctypes.c_void_p]
enet_host_compress_with_range_coder.restype = ctypes.c_int

enet_host_flush = enet.enet_host_flush
enet_host_flush.argtypes = [ctypes.c_void_p]
enet_host_flush.restype = None

enet_host_destroy = enet.enet_host_destroy
enet_host_destroy.argtypes = [ctypes.c_void_p]
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
