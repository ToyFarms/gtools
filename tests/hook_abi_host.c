/*
 * Prints the ABI v4 layout (sizes + field offsets) as "name=value" lines so
 * tests/test_hook_abi.py can compare the Python mirror (payload.py) against
 * the real compiled struct layout.
 */
#include <stdio.h>
#include <stddef.h>

#include "hook_protocol.h"

#define OFF(type, field) #field "=" , (long long)offsetof(type, field)

static void line(const char *name, long long value)
{
    printf("%s=%lld\n", name, value);
}

int main(void)
{
    line("HookPattern.size", (long long)sizeof(struct HookPattern));
    line("HookDescriptor.size", (long long)sizeof(struct HookDescriptor));
    line("HookRuntime.size", (long long)sizeof(struct HookRuntime));
    line("HookEventSlot.size", (long long)sizeof(struct HookEventSlot));
    line("HookHandshakeEntry.size", (long long)sizeof(struct HookHandshakeEntry));
    line("HookHandshake.size", (long long)sizeof(struct HookHandshake));
    line("HookPayload.size", (long long)sizeof(struct HookPayload));
    line("ShimShared.size", (long long)sizeof(struct ShimShared));

    line("desc.patterns", (long long)offsetof(struct HookDescriptor, patterns));
    line("desc.module", (long long)offsetof(struct HookDescriptor, module));
    line("desc.symbol", (long long)offsetof(struct HookDescriptor, symbol));
    line("desc.rva", (long long)offsetof(struct HookDescriptor, rva));
    line("desc.targetHint", (long long)offsetof(struct HookDescriptor, targetHint));
    line("desc.flags", (long long)offsetof(struct HookDescriptor, flags));

    line("rt.enabled", (long long)offsetof(struct HookRuntime, enabled));
    line("rt.status", (long long)offsetof(struct HookRuntime, status));
    line("rt.selfIndex", (long long)offsetof(struct HookRuntime, selfIndex));
    line("rt.hits", (long long)offsetof(struct HookRuntime, hits));
    line("rt.faults", (long long)offsetof(struct HookRuntime, faults));
    line("rt.target", (long long)offsetof(struct HookRuntime, target));
    line("rt.trampoline", (long long)offsetof(struct HookRuntime, trampoline));
    line("rt.detour", (long long)offsetof(struct HookRuntime, detour));
    line("rt.state", (long long)offsetof(struct HookRuntime, state));
    line("rt.data", (long long)offsetof(struct HookRuntime, data));

    line("shim.runtime", (long long)offsetof(struct ShimShared, runtime));
    line("shim.events", (long long)offsetof(struct ShimShared, events));
    line("shim.payload", (long long)offsetof(struct ShimShared, payload));
    line("shim.eventTicket", (long long)offsetof(struct ShimShared, eventTicket));
    line("shim.payloadRevision", (long long)offsetof(struct ShimShared, payloadRevision));

    line("pay.descriptors", (long long)offsetof(struct HookPayload, descriptors));
    line("pay.blobs", (long long)offsetof(struct HookPayload, blobs));
    line("pay.targetProcess", (long long)offsetof(struct HookPayload, targetProcess));

    line("const.HOOK_MAX", HOOK_MAX);
    line("const.HOOK_KEY_MAX", HOOK_KEY_MAX);
    line("const.HOOK_PATTERN_MAX", HOOK_PATTERN_MAX);
    line("const.HOOK_PATTERN_BYTES", HOOK_PATTERN_BYTES);
    line("const.HOOK_PROGRAM_MAX", HOOK_PROGRAM_MAX);
    line("const.HOOK_DATA_MAX", HOOK_DATA_MAX);
    line("const.HOOK_STATE_SLOTS", HOOK_STATE_SLOTS);
    line("const.HOOK_EVENT_SLOTS", HOOK_EVENT_SLOTS);
    line("const.HOOK_EVENT_MAX", HOOK_EVENT_MAX);
    line("const.HOOK_PAYLOAD_MAX", HOOK_PAYLOAD_MAX);
    line("const.HOOK_VARARGS_VARIANTS", HOOK_VARARGS_VARIANTS);
    line("const.HOOK_ENTRY_PATCH_BYTES", HOOK_ENTRY_PATCH_BYTES);
    line("const.HOOK_PROTOCOL_VERSION", HOOK_PROTOCOL_VERSION);
    line("const.HOOK_PROTOCOL_MAGIC", HOOK_PROTOCOL_MAGIC);
    line("const.HOOK_PAYLOAD_MAGIC", HOOK_PAYLOAD_MAGIC);
    line("const.HOOK_KIND_ISA", HOOK_KIND_ISA);
    line("const.HOOK_KIND_FAST", HOOK_KIND_FAST);
    line("const.HOOK_KIND_VARARGS", HOOK_KIND_VARARGS);
    line("const.HOOK_FAST_NONE", HOOK_FAST_NONE);
    line("const.HOOK_FAST_DROP", HOOK_FAST_DROP);
    line("const.HOOK_FAST_PACE", HOOK_FAST_PACE);
    line("const.HOOK_FAST_RETURN", HOOK_FAST_RETURN);
    line("const.HOOK_SRC_PATTERN", HOOK_SRC_PATTERN);
    line("const.HOOK_SRC_EXPORT", HOOK_SRC_EXPORT);
    line("const.HOOK_SRC_RVA", HOOK_SRC_RVA);
    line("const.HOOK_STATUS_MISSING", HOOK_STATUS_MISSING);
    line("const.HOOK_STATUS_READY", HOOK_STATUS_READY);
    line("const.HOOK_STATUS_PATCHED", HOOK_STATUS_PATCHED);
    return 0;
}
