"""Payload (de)serialization: registry -> wire bytes -> registry."""

import pytest

from gtools.hooks import isa, payload
from gtools.hooks.isa import Program
from gtools.hooks.payload import Descriptor, Pattern, Payload


def simple_payload() -> Payload:
    program = Program()
    program.movi(isa.R0, 1)
    program.ret()
    return Payload(
        descriptors=[
            Descriptor(
                key="render/submit",
                kind=payload.KIND_FAST,
                source=payload.SRC_PATTERN,
                stolen_bytes=14,
                fast_op=payload.FAST_DROP,
                fast_slot=0,
                patterns=[Pattern(SUBMIT_PAT)],
            ),
            Descriptor(
                key="test/sleep",
                source=payload.SRC_EXPORT,
                module="kernel32",
                symbol="Sleep",
                stolen_bytes=16,
                scratch_bytes=512,
                program=program.assemble(),
                data=b"\x01\x02",
                event_kind=5,
            ),
            Descriptor(
                key="log/printf",
                kind=payload.KIND_VARARGS,
                source=payload.SRC_PATTERN,
                stolen_bytes=27,
                varargs_variant=0,
                event_kind=1,
                patterns=[Pattern(LOG_PAT)],
            ),
        ],
        start_delay_ms=1500,
        allow_any_module=False,
        target_process="Growtopia.exe",
    )


SUBMIT_PAT = "40 53 57 48 83 EC 28 80 B9 E1 01 00 00 00 41 0F B7 D9"
LOG_PAT = "48 89 4C 24 08 48 89 54 24 10 ?? ?? ?? ?? E8"


def test_pack_size_is_exact():
    blob = simple_payload().pack()
    assert len(blob) == payload.PAYLOAD_SIZE


def test_roundtrip():
    original = simple_payload()
    blob = original.pack()
    parsed = payload.unpack_payload(blob)

    assert parsed.start_delay_ms == 1500
    assert parsed.target_process == "Growtopia.exe"
    assert parsed.allow_any_module is False
    assert [d.key for d in parsed.descriptors] == ["render/submit", "test/sleep", "log/printf"]

    submit, sleep_hook, log_hook = parsed.descriptors
    assert submit.kind == payload.KIND_FAST
    assert submit.fast_op == payload.FAST_DROP
    assert submit.patterns[0].signature == SUBMIT_PAT

    assert sleep_hook.source == payload.SRC_EXPORT
    assert (sleep_hook.module, sleep_hook.symbol) == ("kernel32", "Sleep")
    assert sleep_hook.data == b"\x01\x02"
    assert sleep_hook.event_kind == 5
    assert len(sleep_hook.program) == 32

    assert log_hook.kind == payload.KIND_VARARGS
    assert log_hook.varargs_variant == 0
    assert log_hook.patterns[0].signature == LOG_PAT


def test_pattern_wildcards_roundtrip():
    p = Pattern("FF E7 ?? ?? 48 8B ??")
    values, mask = p.compile()
    assert values == bytes.fromhex("FFE70000488B00")
    assert mask == bytes.fromhex("FFFF0000FFFF00")
    packed = p.pack()
    length, values2, mask2 = payload.PATTERN.unpack(packed)
    assert length == 7
    assert values2[:7] == values and mask2[:7] == mask
    assert values2[7:] == b"\0" * (payload.PATTERN_BYTES - 7)


def test_pattern_rejects_bad_tokens():
    with pytest.raises(ValueError):
        Pattern("FF X7").compile()
    with pytest.raises(ValueError):
        Pattern("FF F").compile()  # single nibble
    with pytest.raises(ValueError):
        Pattern(" ".join(["48"] * 65)).compile()


def test_validation_errors():
    p = Payload()
    assert "no hooks" in " ".join(p.validate())

    p = Payload(descriptors=[Descriptor(key="", patterns=[Pattern("48 90")])])
    assert any("key" in e for e in p.validate())

    p = Payload(descriptors=[Descriptor(key="a", stolen_bytes=8, patterns=[Pattern("48 90")])])
    assert any("stolen" in e for e in p.validate())

    p = Payload(descriptors=[Descriptor(key="a", patterns=[Pattern("48 90")]),
                             Descriptor(key="a", patterns=[Pattern("48 90")])])
    assert any("duplicate" in e for e in p.validate())

    p = Payload(descriptors=[Descriptor(key="a", patterns=[Pattern("48 90")], program=b"\x00" * 17)])
    assert any("multiple of 16" in e for e in p.validate())

    p = Payload(descriptors=[Descriptor(key="a" * 40, patterns=[Pattern("48 90")])])
    assert any("key" in e for e in p.validate())


def test_pack_rejects_invalid():
    with pytest.raises(ValueError, match="invalid payload"):
        Payload(descriptors=[]).pack()


def test_crc_is_stable():
    blob = simple_payload().pack()
    assert payload.Payload.crc(blob) == payload.Payload.crc(blob)


def test_many_hooks_fill_caps():
    descriptors = [
        Descriptor(key=f"hook/{i:02d}", patterns=[Pattern("48 90")], stolen_bytes=14)
        for i in range(payload.HOOK_MAX)
    ]
    blob = Payload(descriptors=descriptors).pack()
    parsed = payload.unpack_payload(blob)
    assert len(parsed.descriptors) == payload.HOOK_MAX


def test_too_many_hooks_rejected():
    descriptors = [
        Descriptor(key=f"hook/{i:02d}", patterns=[Pattern("48 90")], stolen_bytes=14)
        for i in range(payload.HOOK_MAX + 1)
    ]
    with pytest.raises(ValueError, match="more than"):
        Payload(descriptors=descriptors).pack()
