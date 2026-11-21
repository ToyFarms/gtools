"""ABI v4 layout: the compiled C header must agree with the Python mirror."""

import shutil
import subprocess
from pathlib import Path

import pytest

from gtools.hooks import payload

REPO = Path(__file__).resolve().parent.parent
HOST_SRC = REPO / "tests" / "hook_abi_host.c"
CC = shutil.which("gcc") or shutil.which("clang")

pytestmark = pytest.mark.skipif(CC is None, reason="no C compiler for the ABI check")

EXPECTED_SIZES = {
    "HookPattern.size": payload.PATTERN.size,
    "HookDescriptor.size": payload.DESCRIPTOR_SIZE,
    "HookRuntime.size": payload.RUNTIME.size,
    "HookEventSlot.size": payload.EVENT_SLOT.size,
    "HookHandshakeEntry.size": payload.HANDSHAKE_ENTRY.size,
    "HookPayload.size": payload.PAYLOAD_SIZE,
    "ShimShared.size": payload.SHIM_SIZE,
}

EXPECTED_OFFSETS = {
    "desc.patterns": payload.PAYLOAD_HEAD.size * 0 + 80,
    "rt.enabled": payload.RT_OFF_ENABLED,
    "rt.status": payload.RT_OFF_STATUS,
    "rt.selfIndex": payload.RT_OFF_SELF_INDEX,
    "rt.hits": payload.RT_OFF_HITS,
    "rt.faults": payload.RT_OFF_FAULTS,
    "rt.target": payload.RT_OFF_TARGET,
    "rt.trampoline": payload.RT_OFF_TRAMPOLINE,
    "rt.detour": payload.RT_OFF_DETOUR,
    "rt.state": payload.RT_OFF_STATE,
    "rt.data": payload.RT_OFF_DATA,
    "shim.runtime": payload.SHIM_OFF_RUNTIME,
    "shim.events": payload.SHIM_OFF_EVENTS,
    "shim.payload": payload.SHIM_OFF_PAYLOAD,
    "shim.eventTicket": payload.SHIM_OFF_EVENT_TICKET,
    "shim.payloadRevision": payload.SHIM_OFF_PAYLOAD_REVISION,
    "pay.descriptors": payload.PAYLOAD_HEAD.size,
    "pay.blobs": payload.PAYLOAD_HEAD.size + payload.HOOK_MAX * payload.DESCRIPTOR_SIZE,
    "pay.targetProcess": 32,
}

EXPECTED_CONSTANTS = {
    "const.HOOK_MAX": payload.HOOK_MAX,
    "const.HOOK_KEY_MAX": payload.KEY_MAX,
    "const.HOOK_PATTERN_MAX": payload.PATTERN_MAX,
    "const.HOOK_PATTERN_BYTES": payload.PATTERN_BYTES,
    "const.HOOK_PROGRAM_MAX": payload.PROGRAM_MAX,
    "const.HOOK_DATA_MAX": payload.DATA_MAX,
    "const.HOOK_STATE_SLOTS": payload.STATE_SLOTS,
    "const.HOOK_EVENT_SLOTS": payload.EVENT_SLOTS,
    "const.HOOK_EVENT_MAX": payload.EVENT_MAX,
    "const.HOOK_PAYLOAD_MAX": payload.PAYLOAD_MAX,
    "const.HOOK_VARARGS_VARIANTS": payload.VARARGS_VARIANTS,
    "const.HOOK_ENTRY_PATCH_BYTES": payload.ENTRY_PATCH_BYTES,
    "const.HOOK_PROTOCOL_VERSION": payload.PROTOCOL_VERSION,
    "const.HOOK_PROTOCOL_MAGIC": payload.PROTOCOL_MAGIC,
    "const.HOOK_PAYLOAD_MAGIC": payload.PAYLOAD_MAGIC,
    "const.HOOK_KIND_ISA": payload.KIND_ISA,
    "const.HOOK_KIND_FAST": payload.KIND_FAST,
    "const.HOOK_KIND_VARARGS": payload.KIND_VARARGS,
    "const.HOOK_FAST_NONE": payload.FAST_NONE,
    "const.HOOK_FAST_DROP": payload.FAST_DROP,
    "const.HOOK_FAST_PACE": payload.FAST_PACE,
    "const.HOOK_FAST_RETURN": payload.FAST_RETURN,
    "const.HOOK_SRC_PATTERN": payload.SRC_PATTERN,
    "const.HOOK_SRC_EXPORT": payload.SRC_EXPORT,
    "const.HOOK_SRC_RVA": payload.SRC_RVA,
    "const.HOOK_STATUS_MISSING": payload.STATUS_MISSING,
    "const.HOOK_STATUS_READY": payload.STATUS_READY,
    "const.HOOK_STATUS_PATCHED": payload.STATUS_PATCHED,
}


@pytest.fixture(scope="module")
def abi_report() -> dict[str, int]:
    out = REPO / ".tmp_abi_report.txt"
    subprocess.run([CC, "-I", str(REPO / "gtools" / "hooks"), "-o", str(out) + ".exe", str(HOST_SRC)], check=True)
    lines = subprocess.run([str(out) + ".exe"], capture_output=True, text=True, check=True).stdout.splitlines()
    report = {}
    for line in lines:
        name, _, value = line.partition("=")
        report[name.strip()] = int(value)
    return report


def test_sizes_match(abi_report):
    for name, expected in EXPECTED_SIZES.items():
        assert abi_report.get(name) == expected, f"{name}: C={abi_report.get(name)} python={expected}"


def test_offsets_match(abi_report):
    for name, expected in EXPECTED_OFFSETS.items():
        assert abi_report.get(name) == expected, f"{name}: C={abi_report.get(name)} python={expected}"


def test_constants_match(abi_report):
    for name, expected in EXPECTED_CONSTANTS.items():
        assert abi_report.get(name) == expected, f"{name}: C={abi_report.get(name)} python={expected}"


def test_payload_size_matches_header(abi_report):
    assert abi_report["HookPayload.size"] == payload.PAYLOAD_SIZE
    assert abi_report["shim.payload"] + payload.PAYLOAD_MAX == payload.SHIM_SIZE
