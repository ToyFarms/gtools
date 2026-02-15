import random
import time
from gtools.baked.items import GOLDEN_BOOTY_CHEST
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket
from gtools.core.growtopia.strkv import StrKV
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_SEND_AND_FORGET,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    INTEREST_CALL_FUNCTION,
    INTEREST_STATE_UPDATE,
    Interest,
    InterestCallFunction,
    PendingPacket,
)
from gtools.proxy.extension.sdk import Extension, dispatch, register_thread
from gtools.proxy.extension.sdk_utils import helper
from thirdparty.enet.bindings import ENetPacketFlag


s = helper()


class Buyer(Extension):
    def __init__(self) -> None:
        super().__init__(name="Buyer", interest=[Interest(interest=INTEREST_STATE_UPDATE)])
        self.enabled = False
        self.confirmed = False
        self.last_nb = 0

    @dispatch(
        Interest(
            id=s.auto,
            interest=INTEREST_CALL_FUNCTION,
            call_function=InterestCallFunction(where=[s.variant[0] == b"OnStorePurchaseResult"]),
            direction=DIRECTION_SERVER_TO_CLIENT,
            blocking_mode=BLOCKING_MODE_SEND_AND_FORGET,
        )
    )
    def on_result(self, _event: PendingPacket) -> PendingPacket | None:
        if item := self.state.inventory.get(GOLDEN_BOOTY_CHEST):
            print("gbc: ", item.amount)
        self.confirmed = True

    @register_thread
    def buy_thread(self) -> None:
        while True:
            if not self.enabled:
                time.sleep(0.5)
                continue

            print("buying...")
            self.buy()
            while not self.confirmed:
                time.sleep(0.1)
            self.confirmed = False

            item = self.state.inventory.get(GOLDEN_BOOTY_CHEST)
            amt = item.amount if item else 0
            if self.last_nb == amt:
                self.enabled = False
                print("disabling because purchase is unsuccessful")

            self.last_nb = amt

            time.sleep(random.uniform(1.2, 1.5))

    def buy(self) -> None:
        kv = StrKV()
        kv[b"action"] = b"buy"
        kv[b"item"] = b"valentines"
        kv.append_nl()

        self.push(PreparedPacket(NetPacket(NetType.GENERIC_TEXT, kv), DIRECTION_CLIENT_TO_SERVER, ENetPacketFlag.RELIABLE))

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    b = Buyer()
    b.start()

    while True:
        x = input("> ")
        if x == "b":
            b.buy()
        else:
            b.enabled = not b.enabled
