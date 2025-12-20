from enum import IntEnum, auto
import logging

from google.protobuf.any_pb2 import Any

from gtools.core.growtopia.create import console_message
from gtools.protogen.extension_pb2 import (
    BLOCKING_MODE_BLOCK,
    DIRECTION_CLIENT_TO_SERVER,
    DIRECTION_SERVER_TO_CLIENT,
    INTEREST_GENERIC_TEXT,
    Interest,
    InterestGenericText,
    PendingPacket,
)
from gtools.protogen.op_pb2 import OP_EQ, BinOp
from gtools.protogen.strkv_pb2 import Clause, FindCol, FindRow, Query
from gtools.proxy.extension.sdk import Extension
from gtools.core.growtopia.packet import PreparedPacket
from thirdparty.enet.bindings import ENetPacketFlag


class Action(IntEnum):
    TOGGLE_AUTO = auto()


class AutoFishExtension(Extension):
    def __init__(self) -> None:
        logging.basicConfig(level=logging.DEBUG)

        q = Query(where=[Clause(row=FindRow(method=FindRow.KEY_ANY, key=b"text"), col=FindCol(method=FindCol.RELATIVE, index=1))])
        query = Any()
        query.Pack(q)

        super().__init__(
            name="auto_fish",
            interest=[
                Interest(
                    interest=INTEREST_GENERIC_TEXT,
                    generic_text=InterestGenericText(where=[BinOp(lvalue=query, op=OP_EQ, buf=b"/ft")]),
                    blocking_mode=BLOCKING_MODE_BLOCK,
                    direction=DIRECTION_CLIENT_TO_SERVER,
                    id=Action.TOGGLE_AUTO,
                )
            ],
        )

        self.enabled = False

    def process(self, event: PendingPacket) -> PendingPacket | None:
        match event.interest_id:
            case Action.TOGGLE_AUTO:
                self.enabled = not self.enabled
                self.push(PreparedPacket(console_message(f"auto fish enabled: {self.enabled}"), DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))
                return self.cancel()

    def destroy(self) -> None:
        pass


if __name__ == "__main__":
    AutoFishExtension().start(block=True)
