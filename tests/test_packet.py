import binascii
import time
from gtools.core.growtopia.create import chat, chat_seq, console_message
from gtools.core.growtopia.packet import EmptyPacket, NetPacket, NetType, TankFlags, TankPacket, TankType
import pytest
import struct

from gtools.core.growtopia.strkv import StrKV
from gtools.protogen.extension_pb2 import DIRECTION_CLIENT_TO_SERVER
from tests import verify
from thirdparty.enet.bindings import ENetPacketFlag


def _make_basic_tank() -> TankPacket:
    return TankPacket(
        type=TankType.STATE,
        object_type=1,
        jump_count=2,
        animation_type=3,
        net_id=0x10,
        target_net_id=0x20,
        flags=TankFlags.NONE,
        float_var=1.5,
        value=42,
        vector_x=0.1,
        vector_y=0.2,
        vector_x2=0.3,
        vector_y2=0.4,
        particle_rotation=0.5,
        int_x=7,
        int_y=8,
    )


def test_tankpacket_serialize_roundtrip_verify_snapshot() -> None:
    pkt = _make_basic_tank()
    pkt.flags = pkt.flags | TankFlags.EXTENDED
    pkt.extended_data = b"HELLO"

    serialized = pkt.serialize()

    verify(serialized)

    parsed = TankPacket.deserialize(serialized)

    assert parsed.type == pkt.type
    assert parsed.object_type == pkt.object_type
    assert parsed.jump_count == pkt.jump_count
    assert parsed.animation_type == pkt.animation_type
    assert parsed.net_id == pkt.net_id
    assert parsed.target_net_id == pkt.target_net_id
    assert parsed.flags == pkt.flags
    assert parsed.extended_data == pkt.extended_data


def test_serialize_extended_requires_flag() -> None:
    pkt = _make_basic_tank()
    pkt.extended_data = b"X"

    with pytest.raises(RuntimeError, match="has extended data, but the flags is not set"):
        pkt.serialize()


def test_deserialize_strict_mode_mismatch_raises() -> None:
    pkt = _make_basic_tank()
    pkt.flags = pkt.flags | TankFlags.EXTENDED
    pkt.extended_data = b"abc"
    s = pkt.serialize()

    size = TankPacket._Struct.size
    header_vals = list(TankPacket._Struct.unpack(s[:size]))
    header_vals[-1] = header_vals[-1] + 10
    new_header = TankPacket._Struct.pack(*header_vals)
    tampered = new_header + s[size:]

    with pytest.raises(RuntimeError, match="extended data size does not match"):
        TankPacket.deserialize(tampered, mode="strict")


def test_sample_deserialize_strict_mode_mismatch_raises() -> None:
    with pytest.raises(RuntimeError, match="extended data size does not match"):
        NetPacket.deserialize(
            b"\x04\x00\x00\x00\x00\x00\x00\x00@\x00\x00\x00\x00\x00\x00\x00 \x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x008E\x00\x00!C\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00",
            mode="strict",
        )


def test_deserialize_relaxed_mode_truncation_and_warning(caplog: pytest.LogCaptureFixture) -> None:
    pkt = _make_basic_tank()
    pkt.flags = pkt.flags | TankFlags.EXTENDED
    pkt.extended_data = b"ABCDEFGHIJ"
    s = pkt.serialize()

    size = TankPacket._Struct.size
    header_vals = list(TankPacket._Struct.unpack(s[:size]))

    header_vals[-1] = 4
    new_header = TankPacket._Struct.pack(*header_vals)
    tampered = new_header + s[size:]

    caplog.clear()
    caplog.set_level("WARNING")

    parsed = TankPacket.deserialize(tampered, mode="relaxed")

    assert any("extended data size does not match" in r.message for r in caplog.records)
    assert parsed.extended_data == pkt.extended_data[:4]

    verify(tampered)


def test_sample_deserialize_relaxed_mode_truncation_and_warning(caplog: pytest.LogCaptureFixture) -> None:
    caplog.clear()
    caplog.set_level("WARNING")

    sample = b"\x04\x00\x00\x00\x00\x00\x00\x00@\x00\x00\x00\x00\x00\x00\x00 \x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x008E\x00\x00!C\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    pkt = NetPacket.deserialize(sample, mode="relaxed")
    assert any("extended data size does not match" in r.message for r in caplog.records)

    serialized = pkt.serialize()
    verify(serialized)
    assert serialized[:-1] == sample[:-5]


def test_tank_size() -> None:
    assert TankPacket._Struct.size == 56


def test_net_tank_size() -> None:
    assert len(NetPacket(type=NetType.TANK_PACKET, data=TankPacket()).serialize()) == TankPacket._Struct.size + 4 + 1


def test_tankpacket_serialize_minimal_appends_single_zero() -> None:
    pkt = _make_basic_tank()
    s = pkt.serialize()

    size = TankPacket._Struct.size
    assert len(s) == size

    verify(s)


def test_deserialize_too_short_raises_struct_error() -> None:
    short = b"\x01\x02\x03"
    with pytest.raises(struct.error):
        TankPacket.deserialize(short)


def test_netpacket_deserialize_unknown_enum_raises_valueerror() -> None:
    junk_type = 0xDEADBEEF
    raw = struct.pack("<I", junk_type) + b"\x00"

    with pytest.raises(ValueError):
        NetPacket.deserialize(raw)


def test_netpacket_server_hello_and_serialize_roundtrip() -> None:
    raw = struct.pack("<I", NetType.SERVER_HELLO.value) + b"\x00"
    pkt = NetPacket.deserialize(raw)
    assert isinstance(pkt.data, EmptyPacket)
    assert pkt.type == NetType.SERVER_HELLO

    assert pkt.serialize() == raw


def test_netpacket_tank_roundtrip_and_snapshot() -> None:
    tank = _make_basic_tank()
    net = NetPacket(NetType.TANK_PACKET, tank)

    raw = net.serialize()
    verify(raw)

    parsed = NetPacket.deserialize(raw)
    assert parsed.type == NetType.TANK_PACKET
    assert isinstance(parsed.data, TankPacket)

    assert parsed.data.net_id == tank.net_id
    assert parsed.data.value == tank.value


def test_netpacket_unknown_zero_type_raises_typeerror() -> None:
    raw = struct.pack("<I", NetType.UNKNOWN.value) + b"payload"
    with pytest.raises(TypeError):
        NetPacket.deserialize(raw)


def test_sample_bytes() -> None:
    sample = b"\x04\x00\x00\x00\x00\x00\x00\x00@\x00\x00\x00\x00\x00\x00\x00 \x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x008E\x00\x00!C\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xff\xff\xff\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00"

    pkt = NetPacket.deserialize(sample)
    assert pkt.type == NetType.TANK_PACKET
    assert isinstance(pkt.data, TankPacket)

    out = pkt.serialize()
    assert isinstance(out, (bytes, bytearray))


def test_sample_roundtrip() -> None:
    samples = [
        b"04000000140080805400000000000000000000000000754302000000000096440000484300009b4300002f440000000000000000000000000000000077",
        b"04000000000000000000000000000000200a0000000000000000000000005d430080384400000000000000000000000008000000170000000000000000",
        b"0400000000000000000000000000000020000000000000000000000000005d4300803844000000000000000000000000ffffffffffffffff0000000000",
        b"0400000000000000000000000000000020000000000000000000000000005d4300803844000000000000000000000000ffffffffffffffff0000000000",
        b"0400000000000000000000000000000020000000000000000000000000005e4300803844003423420000000000000000ffffffffffffffff0000000000",
        b"0400000003000000000000000000000000000000000000001200000000007043008038440000000000000000000000000a000000180000000000000000",
        b"04000000000000000000000000000000200a0000000000000000000000007443008038448067604300000000000000000a000000180000000000000088",
        b"0400000000000000000000000000000020000000000000000000000000808e43008038448067ce420000000000000000ffffffffffffffff0000000000",
        b"0400000003000000000000000000000000000000000000001200000000808e430080384400000000000000000000000009000000180000000000000000",
        b"04000000000000000000000000000000200a0000000000000000000000808f4300803844809aa542000000000000000009000000180000000000000000",
        b"0400000003000000000000000000000000000000000000001200000000809043008038440000000000000000000000000a000000180000000000000000",
        b"04000000000000000000000000000000200a0000000000000000000000809043008038440000000000000000000000000a000000180000000000000000",
        b"0400000000000000000000000000000030000000000000000000000000009043008038440034a3c10000000000000000ffffffffffffffff0000000000",
        b"0400000003000000000000000000000000000000000000001200000000009043008038440000000000000000000000000a000000180000000000000000",
        b"04000000000000000000000000000000300a000000000000000000000000904300803844003423c200000000000000000a000000180000000000000000",
        b"0400000000000000000000000000000030000000000000000000000000007c430080384480cd8ec30000000000000000ffffffffffffffff0000000000",
        b"0400000003000000000000000000000010000000000000001200000000007c430080384400000000000000000000000007000000180000000000000000",
        b"04000000000000000000000000000000300a000000000000000000000000774300803844000096c3000000000000000007000000180000000000000000",
        b"04000000030000000000000000000000100000000000000012000000000056430080384400000000000000000000000006000000180000000000000000",
        b"04000000000000000000000000000000200a00000000000000000000000055430080384400fc57c2000000000000000006000000180000000000000000",
        b"040000000000000000000000000000002000000000000000000000000000654300803844c0ce3e430000000000000000ffffffffffffffff0000000000",
        b"04000000030000000000000000000000000000000000000012000000000065430080384400000000000000000000000007000000180000000000000088",
        b"04000000000000000000000000000000200a00000000000000000000000069430080384440685443000000000000000007000000180000000000000000",
        b"0400000003000000000000000000000000000000000000001200000000008f43008038440000000000000000000000000a000000180000000000000000",
        b"04000000000000000000000000000000200a000000000000000000000080914300803844c0cc8b4300000000000000000a000000180000000000000000",
        b"040000000000000000000000000000001000000000000000000000000000a5430000394480319742009a494200000000ffffffffffffffff0000000072",
        b"040000000300000000000000000000000000000000000000120000000000a543000039440000000000000000000000000c000000180000000000000000",
        b"040000000b000000000000000000000000000000000000001d0000000000a5430000394400000000000000000000000032040000000000000000000000",
        b"04000000000000000000000000000000104a000000000000000000000000a5430040394400c95c4200677242000000000c000000180000000000000000",
        b"040000000300000000000000000000001000000000000000120000000000a04300003f4400000000000000000000000009000000190000000000000000",
        b"04000000000000000000000000000000100a000000000000000000000000a043000040440034a3c1c03338430000000009000000190000000000000000",
        b"040000000000000000000000000000002000000000000000000000000080a143008040440034a3420000000000000000ffffffffffffffff0000000000",
        b"040000000300000000000000000000000000000000000000120000000080a143008040440000000000000000000000000a000000190000000000000000",
        b"04000000000000000000000000000000200a000000000000000000000080a243008040440001cc4200000000000000000a000000190000000000000000",
        b"040000000000000000000000000000008000000000000000000000000080a843004030440001cc42c0323cc300000000ffffffffffffffff0000000000",
        b"04000000000000000000000000000000000a000000000000000000000000aa430000304400cef44200ffb9c2000000000c000000170000000000000063",
        b"040000000000000000000000000000001000000000000000000000000080b743000033440034234200cfe44200000000ffffffffffffffff0000000000",
        b"040000000300000000000000000000001000000000000000120000000080b743000033440000000000000000000000000b000000180000000000000000",
        b"04000000000000000000000000000000100a000000000000000000000080b743008033440034a3418035f942000000000b000000180000000000000000",
        b"040000000000000000000000000000003000000000000000000000000000ac4300803844806760c30000000000000000ffffffffffffffff0000000000",
        b"040000000300000000000000000000001000000000000000120000000000ac43008038440000000000000000000000000a000000180000000000000000",
        b"04000000000000000000000000000000300a000000000000000000000000aa430080384400ce74c300000000000000000a000000180000000000000000",
        b"040000000000000000000000000000000000000000000000000000000000a24300403a440034a342809ab74200000000ffffffffffffffff0000000000",
        b"040000000300000000000000000000000000000000000000120000000000a24300403a440000000000000000000000000a000000190000000000000000",
        b"04000000000000000000000000000000000a000000000000000000000000a34300c03a440001cc420001cc42000000000a000000190000000000000060",
        b"040000000000000000000000000000002000000000000000000000000000a64300804044000000000000000000000000ffffffffffffffff0000000000",
        b"040000000300000000000000000000001000000000000000120000000000a643008040440000000000000000000000000a0000001a0000000000000000",
        b"04000000000000000000000000000000200a000000000000000000000000a643008040440000000000000000000000000a0000001a0000000000000000",
        b"040000000000000000000000000000008000000000000000000000000000a643000039440000000020b3d1c300000000ffffffffffffffff0000000000",
        b"040000000300000000000000000000001000000000000000120000000000a643000039440000000000000000000000000a000000190000000000000000",
        b"04000000000000000000000000000000000a000000000000000000000000a64300403744000000008099ccc3000000000a000000190000000000000088",
        b"040000000000000000000000000000000000000000000000000000000080b3430000364400ce744300340a4300000000ffffffffffffffff0000000000",
        b"040000000300000000000000000000001000000000000000120000000080b343000036440000000000000000000000000b000000180000000000000000",
        b"04000000000000000000000000000000000a000000000000000000000000b64300c03644409a844340671443000000000b000000180000000000000000",
        b"040000000000000000000000000000002000000000000000000000000080d04300803844009931430000000000000000ffffffffffffffff0000000000",
        b"040000000300000000000000000000000000000000000000120000000080d043008038440000000000000000000000000d000000190000000000000000",
        b"04000000000000000000000000000000200a000000000000000000000080d1430080384480321d4300000000000000000d000000190000000000000000",
        b"040000000300000000000000000000000000000000000000120000000080d843008038440000000000000000000000000e000000170000000000000060",
        b"04000000000000000000000000000000200a000000000000000000000000d943008038440031974200000000000000000e000000170000000000000000",
        b"040000000000000000000000000000002000000000000000000000000000da4300803844000000000000000000000000ffffffffffffffff0000000000",
        b"040000000300000000000000000000000000000000000000120000000000da43008038440000000000000000000000000e000000190000000000000000",
        b"04000000000000000000000000000000200a000000000000000000000000da43008038440000000000000000000000000e000000190000000000000000",
        b"0400000007000000000000000000000000000000000000000000000000000000000000000000000000000000000000000e000000170000000000000000",
        b"02000000616374696f6e7c696e7075740a7c746578747c61776a6961776a69646f61d5",
        b"02000000616374696f6e7c696e7075740a7c746578747c647700",
        b"02000000616374696f6e7c696e7075740a7c746578747c776401",
        b"02000000616374696f6e7c696e7075740a7c746578747c643a",
        b"02000000616374696f6e7c696e7075740a7c746578747c61b0",
        b"03000000616374696f6e7c717569745f746f5f6578697400",
        b"02000000616374696f6e7c696e7075740a7c746578747c746573737373737373737373737373737373737373737300",
        b"02000000616374696f6e7c696e7075740a7c746578747c424f4f524f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f2120",
        b"0400000001000000ffffffff000000000800000000000000ffffffff00000000000000000000000000000000000000000000000000000000a6010000020002070000004f6e537061776e010292010000737061776e7c6176617461720a6e657449447c3139330a7573657249447c3231303836373737350a6569647c3231303836373737357c434a5a6e70797966376b30433048546136644f447951594f744739547050747273566376532f50357650633d7c50793164474c49507a3842323853327a4f7a433265673d3d0a69707c6b577632614c3968454531334e6862736f77776274344b6e68586872634f6456577a6a4f3843596a7439493d0a636f6c726563747c307c307c32307c33300a706f7358597c3631347c3133300a6e616d657c6077796a67736d66726a60600a7469746c6549636f6e7c7b22506c61796572576f726c644944223a3139332c225772656e6368437573746f6d697a6174696f6e223a7b225772656e6368466f726567726f756e6443616e526f74617465223a66616c73652c225772656e6368466f726567726f756e644944223a2d312c225772656e636849636f6e4944223a2d317d7d0a636f756e7472797c75730a696e7669737c300a6d73746174657c300a736d73746174657c300a6f6e6c696e6549447c0a00",
        b"03000000616374696f6e7c7175697400",
    ]

    for i, sample in enumerate(samples):
        sample = binascii.unhexlify(sample)
        data = sample
        for _ in range(10):
            pkt = NetPacket.deserialize(data)
            data = pkt.serialize()

        verify(data, key=i)
        assert data[:-1] == sample[:-1]


def test_unknown_packet_serialize() -> None:
    verify(NetPacket(NetType(0), EmptyPacket()).serialize())


def test_unknown_packet_deserialize() -> None:
    payload = b"\x00\x00\x00\x00\x00"
    with pytest.raises(TypeError):
        NetPacket.deserialize(payload)


def test_server_hello_serialize() -> None:
    payload = struct.pack("<I", NetType.SERVER_HELLO) + b"\x00"
    pkt = NetPacket.deserialize(payload)
    assert pkt.type == NetType.SERVER_HELLO
    assert isinstance(pkt.data, EmptyPacket)

    assert pkt.serialize() == payload


def test_server_hello_deserialize() -> None:
    verify(NetPacket(type=NetType.SERVER_HELLO, data=EmptyPacket()).serialize())


def test_game_message_serliaze() -> None:
    payload = struct.pack("<I", NetType.GAME_MESSAGE) + b"\x00"
    pkt = NetPacket.deserialize(payload)
    assert pkt.type == NetType.GAME_MESSAGE
    assert isinstance(pkt.data, StrKV)

    assert pkt.serialize() == payload


def test_game_message_deserialize() -> None:
    verify(NetPacket(type=NetType.GAME_MESSAGE, data=StrKV()).serialize())


def test_game_message_deserialize_with_data() -> None:
    expected = struct.pack("<I", NetType.GAME_MESSAGE) + b"test|123\n\n||\x00"
    p = NetPacket(type=NetType.GAME_MESSAGE, data=StrKV([[b"test", b"123"], [b"\n", b"|"]])).serialize()
    verify(p)

    assert p == expected


def test_generic_text_serialize() -> None:
    payload = struct.pack("<I", NetType.GENERIC_TEXT) + b"\x00"
    pkt = NetPacket.deserialize(payload)
    assert pkt.type == NetType.GENERIC_TEXT
    assert isinstance(pkt.data, StrKV)

    assert pkt.serialize() == payload


def test_generic_text_deserialize() -> None:
    verify(NetPacket(type=NetType.GENERIC_TEXT, data=StrKV()).serialize())


def test_generic_text_deserialize_with_data() -> None:
    expected = struct.pack("<I", NetType.GENERIC_TEXT) + b"test|123\n\n||\x00"
    p = NetPacket(type=NetType.GENERIC_TEXT, data=StrKV([[b"test", b"123"], [b"\n", b"|"]])).serialize()
    verify(p)

    assert p == expected


def test_track_serialize() -> None:
    payload = struct.pack("<I", NetType.TRACK) + b"\x00"
    pkt = NetPacket.deserialize(payload)
    assert pkt.type == NetType.TRACK
    assert isinstance(pkt.data, StrKV)

    assert pkt.serialize() == payload


def test_track_deserialize() -> None:
    verify(NetPacket(type=NetType.TRACK, data=StrKV()).serialize())


def test_track_deserialize_with_data() -> None:
    expected = struct.pack("<I", NetType.TRACK) + b"test|123\n\n||\x00"
    p = NetPacket(type=NetType.TRACK, data=StrKV([[b"test", b"123"], [b"\n", b"|"]])).serialize()
    verify(p)

    assert p == expected


def test_error_serialize() -> None:
    payload = struct.pack("<I", NetType.ERROR) + b"\x00"
    pkt = NetPacket.deserialize(payload)
    assert pkt.type == NetType.ERROR
    assert isinstance(pkt.data, EmptyPacket)

    assert pkt.serialize() == payload


def test_error_deserialize() -> None:
    verify(NetPacket(type=NetType.ERROR, data=EmptyPacket()).serialize())


def test_client_log_request_serialize() -> None:
    payload = struct.pack("<I", NetType.CLIENT_LOG_REQUEST) + b"\x00"
    pkt = NetPacket.deserialize(payload)
    assert pkt.type == NetType.CLIENT_LOG_REQUEST
    assert isinstance(pkt.data, EmptyPacket)

    assert pkt.serialize() == payload


def test_client_log_request_deserialize() -> None:
    verify(NetPacket(type=NetType.CLIENT_LOG_REQUEST, data=EmptyPacket()).serialize())


def test_client_log_response_serialize() -> None:
    payload = struct.pack("<I", NetType.CLIENT_LOG_RESPONSE) + b"\x00"
    pkt = NetPacket.deserialize(payload)
    assert pkt.type == NetType.CLIENT_LOG_RESPONSE
    assert isinstance(pkt.data, EmptyPacket)

    assert pkt.serialize() == payload


def test_client_log_response_deserialize() -> None:
    verify(NetPacket(type=NetType.CLIENT_LOG_RESPONSE, data=EmptyPacket()).serialize())


def test_tankpacket_with_different_types() -> None:
    for tank_type in [TankType.CALL_FUNCTION, TankType.UPDATE_STATUS, TankType.TILE_CHANGE_REQUEST]:
        pkt = _make_basic_tank()
        pkt.type = tank_type
        serialized = pkt.serialize()
        verify(serialized, key=tank_type.name)
        parsed = TankPacket.deserialize(serialized)
        assert parsed.type == tank_type


def test_tankpacket_with_various_flags() -> None:
    pkt = _make_basic_tank()
    flags_list = [
        TankFlags.WALK | TankFlags.JUMP,
        TankFlags.FACING_LEFT | TankFlags.STANDING,
        TankFlags.PUNCH | TankFlags.PLACE,
    ]
    for flags in flags_list:
        pkt.flags = flags
        serialized = pkt.serialize()
        verify(serialized, key=flags)
        parsed = TankPacket.deserialize(serialized)
        assert parsed.flags == flags


def close(a: float, b: float, eps: float = 0.01) -> bool:
    return a - b <= eps


def test_tankpacket_with_negative_values() -> None:
    pkt = _make_basic_tank()
    pkt.float_var = -1.5
    pkt.vector_x = -0.1
    pkt.int_x = -7
    serialized = pkt.serialize()
    verify(serialized)
    parsed = TankPacket.deserialize(serialized)
    assert close(parsed.float_var, -1.5)
    assert close(parsed.vector_x, -0.1)
    assert close(parsed.int_x, -7)


def test_tankpacket_extended_data_variations() -> None:
    pkt = _make_basic_tank()
    pkt.flags |= TankFlags.EXTENDED
    extended_datas = [
        b"",
        b"A" * 1,
        b"B" * 100,
        b"C" * 1024,
        b"\x00\xff\xaa",
    ]
    for i, ext in enumerate(extended_datas):
        pkt.extended_data = ext
        serialized = pkt.serialize()
        verify(serialized, key=i)
        parsed = TankPacket.deserialize(serialized)
        assert parsed.extended_data == ext


def test_deserialize_relaxed_mode_extra_data(caplog: pytest.LogCaptureFixture) -> None:
    pkt = _make_basic_tank()
    pkt.flags |= TankFlags.EXTENDED
    pkt.extended_data = b"abc"
    s = pkt.serialize()
    tampered = s + b"extra"
    caplog.clear()
    caplog.set_level("WARNING")
    parsed = TankPacket.deserialize(tampered, mode="relaxed")
    assert any("extended data size does not match" in r.message for r in caplog.records)
    assert parsed.extended_data == b"abc"
    assert len(parsed.extended_data) == 3


def test_netpacket_more_samples_roundtrip() -> None:
    samples = [
        b"01000000",
        b"03000000616374696f6e7c746573740a746578747c76616c75650a7c7c0a",
        b"020000007c7c5c7866660a746573747c7465737400",
        b"06000000747261636b7c310a6576656e747c7472696767657200",
        b"05000000",
        b"07000000",
        b"08000000",
        b"04000000010000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000",
    ]
    for i, sample in enumerate(samples):
        sample = binascii.unhexlify(sample)
        data = sample
        for _ in range(5):
            pkt = NetPacket.deserialize(data)
            data = pkt.serialize()
        verify(data, key=i)


def test_strkv_access_and_modification() -> None:
    kv = StrKV([[b"action", b"input"], [b"text", b"test"]])
    assert kv["action", 1] == b"input"
    kv["text", 1] = b"modified"
    assert kv["text", 1] == b"modified"
    kv.append([b"new", b"row"])
    assert kv[-1, 0] == b"new"
    with pytest.raises(KeyError):
        _ = kv["nonexistent"]


def test_netpacket_with_strkv_roundtrip() -> None:
    for net_type in [NetType.GAME_MESSAGE, NetType.GENERIC_TEXT, NetType.TRACK]:
        kv = StrKV([[b"key1", b"value1"], [b"key2", b"value2"]])
        net = NetPacket(net_type, kv)
        raw = net.serialize()
        verify(raw, key=net_type.name)
        parsed = NetPacket.deserialize(raw)
        assert parsed.type == net_type
        assert isinstance(parsed.data, StrKV)
        assert parsed.data._data == kv._data


def test_empty_packet_variations() -> None:
    for net_type in [NetType.SERVER_HELLO, NetType.ERROR, NetType.CLIENT_LOG_REQUEST, NetType.CLIENT_LOG_RESPONSE]:
        net = NetPacket(net_type, EmptyPacket())
        raw = net.serialize()
        verify(raw, key=net_type.name)
        parsed = NetPacket.deserialize(raw)
        assert parsed.type == net_type
        assert isinstance(parsed.data, EmptyPacket)


def test_invalid_nettype_deserialize() -> None:
    raw = struct.pack("<I", 999) + b"\x00"
    with pytest.raises(ValueError):
        NetPacket.deserialize(raw)


def test_tankpacket_maximal_values() -> None:
    pkt = TankPacket(
        type=TankType.STATE,
        object_type=255,
        jump_count=255,
        animation_type=255,
        net_id=0xFFFFFFFF,
        target_net_id=0x7FFFFFFF,
        flags=0xFFFF,
        float_var=3.4028234663852886e38,
        value=0x7FFFFFFF,
        vector_x=3.4028234663852886e38,
        vector_y=3.4028234663852886e38,
        vector_x2=3.4028234663852886e38,
        vector_y2=3.4028234663852886e38,
        particle_rotation=3.4028234663852886e38,
        int_x=0x7FFFFFFF,
        int_y=0x7FFFFFFF,
    )
    serialized = pkt.serialize()
    verify(serialized)
    parsed = TankPacket.deserialize(serialized)
    assert parsed.net_id == pkt.net_id
    assert parsed.flags == pkt.flags


def test_netpacket_property_accessors() -> None:
    tank_net = NetPacket(NetType.TANK_PACKET, _make_basic_tank())
    assert isinstance(tank_net.tank, TankPacket)
    with pytest.raises(TypeError):
        _ = tank_net.game_message

    strkv_net = NetPacket(NetType.GAME_MESSAGE, StrKV([[b"test", b"123"]]))
    assert isinstance(strkv_net.game_message, StrKV)
    with pytest.raises(TypeError):
        _ = strkv_net.tank


def test_create_console_message() -> None:
    msg = b"`3Today is Farmer Day!`` Your first Farming quest will give 1 `2Growtoken`` and all Farmer quests will give 25% bonus points!"

    expected = b"\x04\x00\x00\x00\x01\x00\x00\x00\xff\xff\xff\xff\x00\x00\x00\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x9a\x00\x00\x00\x02\x00\x02\x10\x00\x00\x00OnConsoleMessage\x01\x02}\x00\x00\x00`3Today is Farmer Day!`` Your first Farming quest will give 1 `2Growtoken`` and all Farmer quests will give 25% bonus points!\x00"

    pkt = console_message(msg).serialize()
    assert pkt == expected
    verify(pkt)


def test_create_chat() -> None:
    text = b"lol"
    expected = b"\x02\x00\x00\x00action|input\n|text|lol\x00"

    pkt = chat(text).serialize()
    assert pkt == expected
    verify(pkt)


def test_create_seq_realtime() -> None:
    text = b"smaller text"

    expected = iter(
        [
            b"\x04\x00\x00\x00\x12\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
            b"\x04\x00\x00\x00\x12\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
            b"\x02\x00\x00\x00action|input\n|text|smaller text\x00",
        ]
    )

    seq = chat_seq(text, 1)
    print(seq._seq)

    seq.verify()  # single thread
    pkt = seq.next()
    assert pkt.verified
    assert pkt.pkt.as_raw == next(expected)
    assert pkt.pkt.flags == ENetPacketFlag.RELIABLE
    assert pkt.pkt.direction == DIRECTION_CLIENT_TO_SERVER
    verify(pkt.pkt.as_raw, key=1)

    start = time.monotonic()
    # in another part of the code
    while True:
        seq.verify()

        # this would not be here if its not a single thread
        if (pkt := seq.next()).verified:
            break

        time.sleep(0.1)

    assert pkt.verified
    assert pkt.pkt.as_raw == next(expected)
    assert pkt.pkt.flags == ENetPacketFlag.RELIABLE
    assert pkt.pkt.direction == DIRECTION_CLIENT_TO_SERVER
    elapsed = time.monotonic() - start
    assert 0.5 < elapsed < 2
    verify(pkt.pkt.as_raw, key=2)

    seq.verify()  # single thread
    pkt = seq.next()
    assert pkt.verified
    assert pkt.pkt.as_raw == next(expected)
    assert pkt.pkt.flags == ENetPacketFlag.RELIABLE
    assert pkt.pkt.direction == DIRECTION_CLIENT_TO_SERVER
    verify(pkt.pkt.as_raw, key=3)


def test_create_seq_delay_range() -> None:
    text = b"Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam"

    expected = iter(
        [
            b"\x04\x00\x00\x00\x12\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
            b"\x04\x00\x00\x00\x12\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
            b"\x02\x00\x00\x00action|input\n|text|Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam\x00",
        ]
    )

    delay = (1.0, 2.0)

    seq = chat_seq(text, 1, delay)
    print(seq._seq)

    seq.verify()  # single thread
    pkt = seq.next()
    assert pkt.verified
    assert pkt.pkt.as_raw == next(expected)
    assert pkt.pkt.flags == ENetPacketFlag.RELIABLE
    assert pkt.pkt.direction == DIRECTION_CLIENT_TO_SERVER
    verify(pkt.pkt.as_raw, key=1)

    start = time.monotonic()
    # in another part of the code
    while True:
        seq.verify()

        # this would not be here if its not a single thread
        if (pkt := seq.next()).verified:
            break

        time.sleep(0.1)

    assert pkt.verified
    assert pkt.pkt.as_raw == next(expected)
    assert pkt.pkt.flags == ENetPacketFlag.RELIABLE
    assert pkt.pkt.direction == DIRECTION_CLIENT_TO_SERVER
    elapsed = time.monotonic() - start
    assert delay[0] <= elapsed <= delay[1]
    verify(pkt.pkt.as_raw, key=2)

    seq.verify()  # single thread
    pkt = seq.next()
    assert pkt.verified
    assert pkt.pkt.as_raw == next(expected)
    assert pkt.pkt.flags == ENetPacketFlag.RELIABLE
    assert pkt.pkt.direction == DIRECTION_CLIENT_TO_SERVER
    verify(pkt.pkt.as_raw, key=3)


def test_create_seq_delay_const() -> None:
    text = b"Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam"

    expected = iter(
        [
            b"\x04\x00\x00\x00\x12\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
            b"\x04\x00\x00\x00\x12\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00",
            b"\x02\x00\x00\x00action|input\n|text|Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam\x00",
        ]
    )

    delay = 1.0

    seq = chat_seq(text, 1, delay)
    print(seq._seq)

    seq.verify()  # single thread
    pkt = seq.next()
    assert pkt.verified
    assert pkt.pkt.as_raw == next(expected)
    assert pkt.pkt.flags == ENetPacketFlag.RELIABLE
    assert pkt.pkt.direction == DIRECTION_CLIENT_TO_SERVER
    verify(pkt.pkt.as_raw, key=1)

    start = time.monotonic()
    # in another part of the code
    while True:
        seq.verify()

        # this would not be here if its not a single thread
        if (pkt := seq.next()).verified:
            break

        time.sleep(0.1)

    assert pkt.verified
    assert pkt.pkt.as_raw == next(expected)
    assert pkt.pkt.flags == ENetPacketFlag.RELIABLE
    assert pkt.pkt.direction == DIRECTION_CLIENT_TO_SERVER
    elapsed = time.monotonic() - start
    assert delay - 0.1 < elapsed < delay + 0.1
    verify(pkt.pkt.as_raw, key=2)

    seq.verify()  # single thread
    pkt = seq.next()
    assert pkt.verified
    assert pkt.pkt.as_raw == next(expected)
    assert pkt.pkt.flags == ENetPacketFlag.RELIABLE
    assert pkt.pkt.direction == DIRECTION_CLIENT_TO_SERVER
    verify(pkt.pkt.as_raw, key=3)
