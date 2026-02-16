from collections import defaultdict
from gtools.core.growtopia.create import call_function
from gtools.core.growtopia.items_dat import item_database
from gtools.core.growtopia.packet import NetPacket, NetType, PreparedPacket
from gtools.core.growtopia.strkv import StrKV
from gtools.core.growtopia.variant import Variant
from gtools.protogen.extension_pb2 import BLOCKING_MODE_BLOCK, DIRECTION_CLIENT_TO_SERVER, DIRECTION_SERVER_TO_CLIENT, INTEREST_SET_ICON_STATE, INTEREST_STATE_UPDATE, Interest, PendingPacket
from gtools.proxy.extension.sdk import Extension, dispatch
from gtools.proxy.extension.sdk_utils import helper
from thirdparty.enet.bindings import ENetPacketFlag


s = helper()


class AnalyzeDialog(Extension):
    def __init__(self) -> None:
        super().__init__(name="dialog", interest=[Interest(interest=INTEREST_STATE_UPDATE)])

    @dispatch(
        Interest(
            interest=INTEREST_SET_ICON_STATE,
            direction=DIRECTION_CLIENT_TO_SERVER,
            blocking_mode=BLOCKING_MODE_BLOCK,
            id=s.auto,
        ),
    )
    def on_set_icon_state(self, event: PendingPacket) -> PendingPacket | None:
        print("blocked set icon state", NetPacket.deserialize(event.buf).compact_repr())
        return self.cancel()

    def gs(self) -> None:
        dialog = StrKV()
        dialog.append(["set_border_color", "255,0,0,255", ""])
        dialog.append(["set_bg_color", "30,30,30,255", ""])
        dialog.append(["add_label", "small", "Growscan", "left"])
        dialog.append(["add_spacer", "big", ""])
        if self.state.world:
            all: dict[int, int] = defaultdict(int)

            for item in self.state.world.dropped.items:
                all[item.id] += item.amount

            for id, amount in all.items():
                dialog.append([f"add_label_with_icon", "small", f"`w{item_database.get(id).name.decode()} ({amount})``", "left", id, ""])
        dialog.append(["add_spacer", "big", ""])
        dialog.append(["add_quick_exit", ""])

        self.send_dialog(dialog)

    def send_dialog(self, dialog: StrKV) -> None:
        tank = call_function(b"OnDialogRequest", Variant.vstr(dialog.serialize()))
        tank.net_id = -1

        print(tank.compact_repr())

        self.push(
            PreparedPacket(
                NetPacket(NetType.TANK_PACKET, tank),
                DIRECTION_SERVER_TO_CLIENT,
                ENetPacketFlag.RELIABLE,
            )
        )

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    a = AnalyzeDialog()
    a.start()

    try:
        while True:
            x = input("> ")
            if x == "a":
                a.gs()
    except (InterruptedError, KeyboardInterrupt):
        pass
    finally:
        a.stop()
