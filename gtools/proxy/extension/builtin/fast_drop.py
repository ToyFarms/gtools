import logging
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    INTEREST_CALL_FUNCTION,
    Event,
    Forward,
    Interest,
    InterestCallFunction,
    Packet,
)
from gtools.proxy.extension.sdk import Extension
from gtools.core.growtopia.packet import NetPacket, NetType
from gtools.core.growtopia.variant import Variant
from gtools.core.growtopia.strkv import StrKV


class FastDropExtension(Extension):
    """
    the goal is to intercept dialog request from the server, and instead of letting the client
    handle it. we immediately response with a fabricated packet
    """

    def __init__(self) -> None:
        logging.basicConfig(level=logging.DEBUG)

        super().__init__(
            name="fast_drop",
            interest=[
                Interest(
                    interest=INTEREST_CALL_FUNCTION,  # the packet is using tank call function
                    blocking_mode=BLOCKING_MODE_BLOCK,  # this extension need to block (so it can replace the original packet)
                    direction=DIRECTION_SERVER_TO_CLIENT,  # the packet is from server, to the client
                    call_function=InterestCallFunction(fn_name=b"OnDialogRequest"),  # optional but highly encouraged, to cut down rtt--be as specific as possible
                    id=0,  # extension could have multiple interest, use this to identify them in process() later
                ),
            ],
        )

    def process(self, event: Event) -> Packet | None:
        match event.id or 0:  # id is optional
            case 0:
                pkt = NetPacket.deserialize(event.buf)
                var = Variant.deserialize(pkt.tank.extended_data)
                if b"How many to drop" not in var.as_string[1]:
                    return Packet(type=Packet.TYPE_FORWARD_NOT_MODIFIED)  # basically just says "act like this extension never existed and just move on the chain"

                kv = StrKV.deserialize(var.as_string[1])

                # request
                # Variant([Variant.vstr(b'OnDialogRequest'), Variant.vstr(b'set_default_color|`o\nadd_label_with_icon|big|`wDrop Sign``|left|20|\nadd_textbox|How many to drop?|left|\nadd_text_input|count||3|5|\nembed_data|itemID|20\nend_dialog|drop_item|Cancel|OK|\n')])

                # response payload
                # \x02\x00\x00\x00action|dialog_return\ndialog_name|drop_item\nitemID|4|\ncount|8\n\x00

                res = StrKV()
                res[b"action"] = b"dialog_return"
                res[b"dialog_name"] = b"drop_item"
                res[b"itemID"] = kv.relative[b"itemID", 1], b""
                res[b"count"] = kv.relative[b"count", 2]

                # never think the extension is at the end of the chain
                # always design as if other extension will build upon your response
                return Packet(
                    type=Packet.TYPE_FORWARD,  # forward will look for extension that are interested with the new parameter, if none then the chain is complete
                    forward=Forward(
                        buf=NetPacket(
                            NetType.GENERIC_TEXT,
                            data=res,
                        ).serialize(),
                        direction=DIRECTION_CLIENT_TO_SERVER,  # direction will determine where the packet will be sent to (client/server), if none use the original direction
                    ),
                )
            case _:
                return Packet(type=Packet.TYPE_FORWARD_NOT_MODIFIED)

    # this will be called when the extension is disconnected
    # of course it can be reconnected, so think of this as clearing session data
    # but its recommended to keep extension stateless
    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    FastDropExtension().start(block=True)

# DEBUG:proxy:from gt client:
# DEBUG:proxy:    <ENetEventType.RECEIVE: 3>
# DEBUG:proxy:HEXDUMP:
#         00000000: 02 00 00 00 61 63 74 69  6F 6E 7C 64 72 6F 70 0A  ....action|drop.
#         00000010: 7C 69 74 65 6D 49 44 7C  32 30 0A 64              |itemID|20.d
# DEBUG:proxy:    b'\x02\x00\x00\x00action|drop\n|itemID|20\nd'
# DEBUG:proxy:NetPacket[GENERIC_TEXT]({'action|drop', '|itemID|20', ''}) CLIENT

# DEBUG:proxy:from gt server:
# DEBUG:proxy:    <ENetEventType.RECEIVE: 3>
# DEBUG:proxy:HEXDUMP:
#         00000000: 04 00 00 00 01 00 00 00  FF FF FF FF 00 00 00 00  ................
#         00000010: 08 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00  ................
#         00000020: 00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00  ................
#         00000030: 00 00 00 00 00 00 00 00  D4 00 00 00 02 00 02 0F  ................
#         00000040: 00 00 00 4F 6E 44 69 61  6C 6F 67 52 65 71 75 65  ...OnDialogReque
#         00000050: 73 74 01 02 B8 00 00 00  73 65 74 5F 64 65 66 61  st......set_defa
#         00000060: 75 6C 74 5F 63 6F 6C 6F  72 7C 60 6F 0A 61 64 64  ult_color|`o.add
#         00000070: 5F 6C 61 62 65 6C 5F 77  69 74 68 5F 69 63 6F 6E  _label_with_icon
#         00000080: 7C 62 69 67 7C 60 77 44  72 6F 70 20 53 69 67 6E  |big|`wDrop Sign
#         00000090: 60 60 7C 6C 65 66 74 7C  32 30 7C 0A 61 64 64 5F  ``|left|20|.add_
#         000000A0: 74 65 78 74 62 6F 78 7C  48 6F 77 20 6D 61 6E 79  textbox|How many
#         000000B0: 20 74 6F 20 64 72 6F 70  3F 7C 6C 65 66 74 7C 0A   to drop?|left|.
#         000000C0: 61 64 64 5F 74 65 78 74  5F 69 6E 70 75 74 7C 63  add_text_input|c
#         000000D0: 6F 75 6E 74 7C 7C 33 7C  35 7C 0A 65 6D 62 65 64  ount||3|5|.embed
#         000000E0: 5F 64 61 74 61 7C 69 74  65 6D 49 44 7C 32 30 0A  _data|itemID|20.
#         000000F0: 65 6E 64 5F 64 69 61 6C  6F 67 7C 64 72 6F 70 5F  end_dialog|drop_
#         00000100: 69 74 65 6D 7C 43 61 6E  63 65 6C 7C 4F 4B 7C 0A  item|Cancel|OK|.
#         00000110: 80                                                .
# DEBUG:proxy:    b'\x04\x00\x00\x00\x01\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xd4\x00\x00\x00\x02\x00\x02\x0f\x00\x00\x00OnDialogRequest\x01\x02\xb8\x00\x00\x00set_default_color|`o\nadd_label_with_icon|big|`wDrop Sign``|left|20|\nadd_textbox|How many to drop?|left|\nadd_text_input|count||3|5|\nembed_data|itemID|20\nend_dialog|drop_item|Cancel|OK|\n\x80'
# DEBUG:proxy:NetPacket[TANK_PACKET](TankPacket(type=<TankType.CALL_FUNCTION: 1>, object_type=0, jump_count=0, animation_type=0, net_id=4294967295, target_net_id=0, flags=<TankFlags.EXTENDED: 8>, float_var=0.0, value=0, vector_x=0.0, vector_y=0.0, vector_x2=0.0, vector_y2=0.0, particle_rotation=0.0, int_x=0, int_y=0, extended_len=212, extended_data=b'\x02\x00\x02\x0f\x00\x00\x00OnDialogRequest\x01\x02\xb8\x00\x00\x00set_default_color|`o\nadd_label_with_icon|big|`wDrop Sign``|left|20|\nadd_textbox|How many to drop?|left|\nadd_text_input|count||3|5|\nembed_data|itemID|20\nend_dialog|drop_item|Cancel|OK|\n')) SERVER

# DEBUG:proxy:from gt client:
# DEBUG:proxy:    <ENetEventType.RECEIVE: 3>
# DEBUG:proxy:HEXDUMP:
#         00000000: 04 00 00 00 12 00 00 00  01 00 00 00 00 00 00 00  ................
#         00000010: 00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00  ................
#         00000020: 00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00  ................
#         00000030: 02 00 00 00 00 00 00 00  00 00 00 00 00           .............
# DEBUG:proxy:    b'\x04\x00\x00\x00\x12\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
# DEBUG:proxy:NetPacket[TANK_PACKET](TankPacket(type=<TankType.SET_ICON_STATE: 18>, object_type=0, jump_count=0, animation_type=0, net_id=1, target_net_id=0, flags=<TankFlags.NONE: 0>, float_var=0.0, value=0, vector_x=0.0, vector_y=0.0, vector_x2=0.0, vector_y2=0.0, particle_rotation=0.0, int_x=2, int_y=0, extended_len=0, extended_data=b'')) CLIENT


# DEBUG:proxy:from gt client:
# DEBUG:proxy:    <ENetEventType.RECEIVE: 3>
# DEBUG:proxy:HEXDUMP:
#         00000000: 04 00 00 00 12 00 00 00  01 00 00 00 00 00 00 00  ................
#         00000010: 00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00  ................
#         00000020: 00 00 00 00 00 00 00 00  00 00 00 00 00 00 00 00  ................
#         00000030: 00 00 00 00 00 00 00 00  00 00 00 00 00           .............
# DEBUG:proxy:    b'\x04\x00\x00\x00\x12\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
# DEBUG:proxy:NetPacket[TANK_PACKET](TankPacket(type=<TankType.SET_ICON_STATE: 18>, object_type=0, jump_count=0, animation_type=0, net_id=1, target_net_id=0, flags=<TankFlags.NONE: 0>, float_var=0.0, value=0, vector_x=0.0, vector_y=0.0, vector_x2=0.0, vector_y2=0.0, particle_rotation=0.0, int_x=0, int_y=0, extended_len=0, extended_data=b'')) CLIENT

# DEBUG:proxy:from gt client:
# DEBUG:proxy:    <ENetEventType.RECEIVE: 3>
# DEBUG:proxy:HEXDUMP:
#         00000000: 02 00 00 00 61 63 74 69  6F 6E 7C 64 69 61 6C 6F  ....action|dialo
#         00000010: 67 5F 72 65 74 75 72 6E  0A 64 69 61 6C 6F 67 5F  g_return.dialog_
#         00000020: 6E 61 6D 65 7C 64 72 6F  70 5F 69 74 65 6D 0A 69  name|drop_item.i
#         00000030: 74 65 6D 49 44 7C 32 30  7C 0A 63 6F 75 6E 74 7C  temID|20|.count|
#         00000040: 33 0A 00                                          3..
# DEBUG:proxy:    b'\x02\x00\x00\x00action|dialog_return\ndialog_name|drop_item\nitemID|20|\ncount|3\n\x00'
# DEBUG:proxy:NetPacket[GENERIC_TEXT]({'action|dialog_return', 'dialog_name|drop_item', 'itemID|20|', 'count|3', ''}) CLIENT
