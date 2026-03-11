from dataclasses import dataclass, field
from enum import IntFlag

from pyglm.glm import vec2, vec4

from gtools.core.growtopia.packet import TankFlags
from gtools.protogen import growtopia_pb2


# https://github.com/trailyy/morphine/blob/d3e7c841f633a37699ca9f2ac48ccdb8ed461af2/gt-internal/sdk/enums.hpp#L537
class CharacterFlags(IntFlag):
    NONE = 0x0
    NOCLIP = 0x1
    DOUBLE_JUMP = 0x2
    INVISIBLE = 0x4
    NO_HANDS = 0x8
    NO_FACE = 0x10
    NO_BODY = 0x20
    DEVIL_HORNS = 0x40
    GOLDEN_HALO = 0x80
    RESPAWN_EFFECT = 0x100
    IGNORE_LAVA = 0x200
    IGNORE_SPIKES = 0x400
    FROZEN = 0x800
    CURSED = 0x1000
    DUCT_TAPE = 0x2000
    SMOKE = 0x4000
    SHINY = 0x8000
    ZOMBIE = 0x10000
    SPICY = 0x20000
    SHADOWS = 0x40000
    RADIOACTIVE = 0x80000
    SPOTLIGHT = 0x100000
    PINEAPPLE_SKIN = 0x200000
    PINEAPPLE_FLAG = 0x400000
    SUPPORTER = 0x800000
    SUPER_SUPPORTER = 0x1000000
    PINEAPPLE_AURA = 0x2000000
    WATER_RING = 0x4000000
    WET = 0x8000000


@dataclass(slots=True)
class CharacterState:
    build_range: int = 2  # tank.jump_count - 126
    punch_range: int = 2  # tank.animation_type - 126
    flags: CharacterFlags = CharacterFlags.NONE  # tank.value
    velocity: float = 250.0  # tank.vector_x2
    gravity: float = 1000.0  # tank.vector_y2
    acceleration: float = 1200.0  # tank.vector_x
    velocity_in_water: float = 125.0  # tank.float_var
    jump_strength: float = 200.0  # tank.vector_y
    # TODO: unknown values: tank.target_net_id, tank.value, tank.int_x, tank.int_y

    @classmethod
    def from_proto(cls, proto: growtopia_pb2.CharacterState) -> "CharacterState":
        return cls(
            build_range=proto.build_range,
            punch_range=proto.punch_range,
            flags=CharacterFlags(proto.flags),
            gravity=proto.gravity,
            velocity=proto.velocity,
            acceleration=proto.acceleration,
            velocity_in_water=proto.velocity_in_water,
            jump_strength=proto.jump_strength,
        )

    def to_proto(self) -> growtopia_pb2.CharacterState:
        return growtopia_pb2.CharacterState(
            build_range=self.build_range,
            punch_range=self.punch_range,
            flags=self.flags,
            gravity=self.gravity,
            velocity=self.velocity,
            acceleration=self.acceleration,
            velocity_in_water=self.velocity_in_water,
            jump_strength=self.jump_strength,
        )


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
    flags: TankFlags = TankFlags.NONE
    state: CharacterState = field(default_factory=CharacterState)

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
            flags=TankFlags(proto.flags),
            state=CharacterState.from_proto(proto.state),
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
            flags=self.flags,
            state=self.state.to_proto(),
        )
