"""The proxy State layer: server ``Call(OnSetPos, (x, y))`` handling.

Client evidence: ``NetAvatar::onSetPos`` (0x140501290) is the callback
``NetAvatar::initFromJoinData`` registers for the "OnSetPos" call variant; the
server sends it on world entry, after a teleport and on a door use. The proxy
maps it to the self position update (net_id 0, the client STATE convention).
"""

from pyglm.glm import ivec2

from gtools.baked.items import DIRT
from gtools.core.growtopia.packet import NetPacket, PreparedPacket
from gtools.core.growtopia.variant import Variant
from gtools.core.growtopia.world import Tile, World
from gtools.proxy.state import State
from gtools.protogen.extension_pb2 import DIRECTION_SERVER_TO_CLIENT
from gtools.protogen.state_pb2 import STATE_PLAYER_UPDATE
from thirdparty.enet.bindings import ENetPacketFlag


class _Broker:
    def __init__(self) -> None:
        self.events = []

    def process_event_any(self, interest, packet) -> None:
        self.events.append((interest, packet))


def test_on_set_pos_call_updates_the_local_player_position() -> None:
    state = State()
    state.world = World.from_tiles([Tile(fg_id=DIRT, pos=ivec2(0, 0))])
    state.me.net_id = 1

    broker = _Broker()
    packet = NetPacket.variant(Variant([Variant.vstr(b"OnSetPos"), Variant.vvec2((1632.0, 1152.0))]))
    state.emit_event(broker, PreparedPacket(packet, DIRECTION_SERVER_TO_CLIENT, ENetPacketFlag.RELIABLE))

    assert (state.me.pos.x, state.me.pos.y) == (1632.0, 1152.0)
    assert broker.events, "the parsed update must be broadcast"
    update = broker.events[-1][1].state_update
    assert update.what == STATE_PLAYER_UPDATE
    assert update.player_update.net_id == 0  # self, like a client STATE
    assert (update.player_update.x, update.player_update.y) == (1632.0, 1152.0)
