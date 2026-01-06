from dataclasses import dataclass, field
from enum import IntFlag

from pyglm.glm import vec2, vec4

from gtools.core.growtopia.packet import TankFlags
from gtools.protogen import growtopia_pb2


@dataclass(slots=True)
class Player:
    net_id: int = 0
    user_id: int = 0
    eid: bytes = b""
    ip: bytes = b""
    colrect: vec4 = field(default_factory=vec4)
    pos: vec2 = field(default_factory=vec2)
    name: bytes = b""
    titleIcon: bytes = b""
    country: bytes = b""
    invis: int = 0
    mstate: int = 0
    smstate: int = 0
    online_id: bytes = b""
    state: TankFlags = TankFlags.NONE

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.Player) -> "Player":
        return cls(
            net_id=proto.netID,
            user_id=proto.userID,
            eid=proto.eid,
            ip=proto.ip,
            colrect=vec4(
                proto.colrect.x,
                proto.colrect.y,
                proto.colrect.w,
                proto.colrect.h,
            ),
            pos=vec2(proto.posXY.x, proto.posXY.y),
            name=proto.name,
            titleIcon=proto.titleIcon,
            country=proto.country,
            invis=proto.invis,
            mstate=proto.mstate,
            smstate=proto.smstate,
            online_id=proto.onlineID,
            state=TankFlags(proto.state),
        )

    def to_proto(self) -> growtopia_pb2.Player:
        return growtopia_pb2.Player(
            netID=self.net_id,
            userID=self.user_id,
            eid=self.eid,
            ip=self.ip,
            colrect=growtopia_pb2.Vec4I(
                x=int(self.colrect.x),
                y=int(self.colrect.y),
                w=int(self.colrect.w),
                h=int(self.colrect.z),
            ),
            posXY=growtopia_pb2.Vec2F(
                x=self.pos.x,
                y=self.pos.y,
            ),
            name=self.name,
            titleIcon=self.titleIcon,
            country=self.country,
            invis=self.invis,
            mstate=self.mstate,
            smstate=self.smstate,
            onlineID=self.online_id,
            state=self.state,
        )


class HackType(IntFlag):
    NONE = 0
    UNK1 = 1 << 0
    UNK2 = 1 << 1
    UNK3 = 1 << 2
    UNK4 = 1 << 3
    UNK5 = 1 << 4
    UNK6 = 1 << 5
    UNK7 = 1 << 6
    UNK8 = 1 << 7
    UNK9 = 1 << 8
    UNK10 = 1 << 9
    UNK11 = 1 << 10
    CHARACTER_FROZEN = 1 << 11  # because of ghost
    # there's probably more, but idk


@dataclass(slots=True)
class CharacterState:
    build_range: int = 0
    punch_range: int = 0
    hack_type: int = 0
    gravity: float = 0.0
    velocity: float = 0.0

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.CharacterState) -> "CharacterState":
        return cls(
            build_range=proto.build_range,
            punch_range=proto.punch_range,
            hack_type=proto.hack_type,
            gravity=proto.gravity,
            velocity=proto.velocity,
        )

    def to_proto(self) -> growtopia_pb2.CharacterState:
        return growtopia_pb2.CharacterState(
            build_range=self.build_range,
            punch_range=self.punch_range,
            hack_type=self.hack_type,
            gravity=self.gravity,
            velocity=self.velocity,
        )
