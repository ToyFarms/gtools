from argparse import ArgumentParser
import sys
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket, TankPacket, TankType
from gtools.core.growtopia.world import World
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    INTEREST_STATE,
    INTEREST_STATE_UPDATE,
    Interest,
    InterestState,
    PendingPacket,
)
from gtools.proxy.extension.client.sdk import Extension, dispatch
from gtools.proxy.extension.client.sdk_utils import helper
from thirdparty.enet.bindings import ENetPacketFlag

s = helper()


class FakeWorld(Extension):
    def __init__(self) -> None:
        super().__init__(name="FakeWorld", interest=[Interest(interest=INTEREST_STATE_UPDATE)])

    def on_connect(self) -> None:
        self.push(
            PreparedPacket(
                NetPacket(NetType.TANK_PACKET, TankPacket(TankType.SEND_MAP_DATA, extended_data=World.from_file(args.world).serialize())),
                DIRECTION_SERVER_TO_CLIENT,
                ENetPacketFlag.RELIABLE,
            )
        )


if __name__ == "__main__":
    input("this will send fake world data to client, you sure?")
    parser = ArgumentParser()
    parser.add_argument("world")

    args = parser.parse_args()
    FakeWorld().start(block=True)
