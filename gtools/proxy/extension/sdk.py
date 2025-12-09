r"""
extension runs in a different process
it will extend the functionality of the main app and allows for uninterrupted
development integration, aka you don't have to restart shit.

the main purpose of extension is listen on event, then decide to either:
- forward
    process the packet as you like, then forward to the next extension, or just return
    if you think no extension should modify the packet further.
- cancel
    return nothing

it will talk using zeromq, thats it really

main -> ext_1 -> ext_2 -> ext_3 -> ext_4 -\
  \--------------------------------------/
                        complete chain

main -> ext_1 -> ext_2 -> ext_3 -\ ext_4
  \------------------------------/
                        ext_3 decides to return

main -> ext_1 -> ext_2 -> ext_3 -x ext_4
                        ext_3 decides to cancel

setup:
the main orchestrator will query every every extension for capabilities, it is:
- modify
- cancel
- listen
- priority

listen capabilities will allow the extension to bypass the chain entirely,
listen extension is read-only.

      /-> ext_6 (listen)
     |/-> ext_5 (listen)
main +--> ext_1 -> ext_2 -> ext_3 -> ext_4 -\
  \-----------------------------------------/

when the extension reply with the requested capabilities,
main will send a unique id for this extension and will start sending state packet.

state packet will include the list of host and their id sorted by their priority,
and is updated if there is a new extension joining. the first host is always main

so the way you determine the next extension is through this state packet,
you find your host, and i+1 is the next destination.

the packet will hold a unique id, if the extension wants to return or cancel,
you need to send the packet or cancel packet to the first host with the unique id.

actually scrap that, the above is for p2p. using a router is simpler.
this means the extension doesnt have to track all the extension (the orchestrator will handle it)
every packet will need 1 extra hop through the orchestrator (router)

    /-------------c-------------\
   /----------b---------\        \
  /------a------\        \        \
main -> ext_1 -\ ext_2 -\ ext_3 -\ ext_4 -\
  \-----a------/        |        |        |
   \----------b---------/        |        |
    \--------------c-------------/        |
     \------------------d-----------------/
"""

import argparse
import zmq
import logging

from gtools.protogen.extension_pb2 import CAPABILITY_LISTEN, Capability, CapabilityResponse, Disconnect, Handshake, Packet
from gtools.protogen.growtopia_pb2 import (
    DTYPE_I32,
    DTYPE_U32,
    INTEREST_PEER_CONNECT,
    INTEREST_PEER_DISCONNECT,
    INTEREST_TANK_PACKET,
    WHERE_OP_EQ,
    WHERE_OP_GT,
    Interest,
    InterestTankPacket,
    WhereSpecifier,
)


class Extension:
    logger = logging.getLogger("extension")

    def __init__(self, name: str, capability: list[Capability], interest: list[Interest], broker_addr: str = "tcp://127.0.0.1:6712") -> None:
        self.name = name.encode()
        self.capability = capability
        self.interest = interest
        self.broker_addr = broker_addr

        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.DEALER)
        self.socket.setsockopt(zmq.IDENTITY, self.name)

        self._connect()
        self._start()

    def _send(self, pkt: Packet) -> None:
        self.logger.debug(f"send {pkt!r}")
        self.socket.send(pkt.SerializeToString())

    def _recv(self, expected: Packet.Type | None = None) -> Packet:
        data = self.socket.recv()
        pkt = Packet()
        pkt.ParseFromString(data)

        if expected and pkt.type != expected:
            raise TypeError(f"expected type {expected!r} got {pkt.type!r}")

        self.logger.debug(f"recv {pkt!r}")

        return pkt

    def disconnect(self) -> None:
        self._send(Packet(type=Packet.TYPE_DISCONNECT, disconnect=Disconnect()))
        self.context.destroy()

    def _connect(self) -> None:
        self.socket.connect(self.broker_addr)

        self._send(Packet(type=Packet.TYPE_HANDSHAKE, handshake=Handshake()))
        self._recv(Packet.TYPE_CAPABILITY_REQUEST)
        self._send(
            Packet(
                type=Packet.TYPE_CAPABILITY_RESPONSE,
                capability_response=CapabilityResponse(
                    capability=self.capability,
                    interest=self.interest,
                ),
            )
        )

    def _start(self) -> None:
        try:
            while True:
                pkt = self._recv()
                match pkt.type:
                    case Packet.TYPE_EVENT:
                        pass
        finally:
            self.disconnect()


if __name__ == "__main__":
    from gtools.proxy.extension.broker import Broker
    import logging
    import time

    logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser()
    parser.add_argument("--broker", action="store_true")

    args = parser.parse_args()

    if args.broker:
        Broker()
    else:
        Extension(
            f"test-{time.time_ns()}",
            [CAPABILITY_LISTEN],
            [
                Interest(interest=INTEREST_PEER_CONNECT, priority=-100),
                Interest(interest=INTEREST_PEER_DISCONNECT, priority=-100),
                Interest(
                    interest=INTEREST_TANK_PACKET,
                    tank_packet=InterestTankPacket(
                        where=[
                            WhereSpecifier(field="net_id", type=DTYPE_I32, op=WHERE_OP_EQ, i32=2),
                            WhereSpecifier(field="jump_count", type=DTYPE_U32, op=WHERE_OP_GT, u32=20),
                        ]
                    ),
                    priority=9999,
                ),
                Interest(
                    interest=INTEREST_TANK_PACKET,
                    tank_packet=InterestTankPacket(
                        where=[
                            WhereSpecifier(field="net_id", type=DTYPE_I32, op=WHERE_OP_EQ, i32=-1),
                        ]
                    ),
                    priority=9999,
                ),
            ],
        )
