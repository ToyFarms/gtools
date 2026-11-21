/*
 * hook_protocol.h - ABI v4 between Python (payload + pipe) and the C runtime.
 *
 * Self-contained: stdint only, no windows.h, so the Python payload serializer
 * (gtools/hooks/payload.py) and the ABI tests can consume it directly. The
 * layout below is pinned by static asserts here and mirrored field-for-field
 * in payload.py; tests/test_hook_abi.py compiles this header and compares the
 * printed offsets against the Python table.
 *
 * Ownership (v4): C owns mechanism only. Hook names, patterns, handler
 * programs, enable/state/data all arrive as data from Python; nothing in this
 * header or in hook.c/agent.c/injector.c may name a game feature.
 */
#ifndef __HOOK_PROTOCOL_H
#define __HOOK_PROTOCOL_H

#include <stdint.h>

#define HOOK_PROTOCOL_VERSION 4u
#define HOOK_PROTOCOL_MAGIC   0x4B485447u /* "GTHK" */
#define HOOK_PAYLOAD_MAGIC    0x50544847u /* "GTHP" */

#define HOOK_PIPE_NAME        "\\\\.\\pipe\\gtools_hook"
#define HOOK_AGENT_MUTEX_NAME "Global\\gtools_hook_agent"
#define HOOK_PID_MUTEX_PREFIX "Global\\gtools_hook_pid_"
#define HOOK_LOCK_MUTEX_PREFIX "Global\\gtools_hook_lock_"

#define HOOK_EXPORT_NAME "g_self"

/* capabilities */
#define HOOK_MAX              32u
#define HOOK_KEY_MAX          32u
#define HOOK_MODULE_MAX       16u
#define HOOK_SYMBOL_MAX       40u
#define HOOK_PATTERN_MAX      4u
#define HOOK_PATTERN_BYTES    64u
#define HOOK_PROGRAM_MAX      8192u
#define HOOK_DATA_MAX         1024u
#define HOOK_STATE_SLOTS      8u
#define HOOK_EVENT_SLOTS      128u
#define HOOK_EVENT_MAX        768u
#define HOOK_PAYLOAD_MAX      (512u * 1024u)
#define HOOK_VARARGS_VARIANTS 8u

/* patching */
#define HOOK_ENTRY_PATCH_BYTES 14u
#define HOOK_PATTERN_SCAN_TIMEOUT_MS 10000u
#define HOOK_PATTERN_SCAN_RETRY_MS   250u

enum HookKind
{
    HOOK_KIND_ISA = 0,     /* register-preserving stub + interpreter */
    HOOK_KIND_FAST = 1,    /* native fast op, no interpreter */
    HOOK_KIND_VARARGS = 2, /* compiled printf-style detour */
};

enum HookFastOp
{
    HOOK_FAST_NONE = 0,
    HOOK_FAST_DROP = 1,   /* state[fastSlot] != 0 -> skip call */
    HOOK_FAST_PACE = 2,   /* state[fastSlot] = fps -> pace the frame */
    HOOK_FAST_RETURN = 3, /* state[fastSlot] != 0 -> skip with state as return */
};

enum HookSource
{
    HOOK_SRC_PATTERN = 0, /* scan the image for pattern variants */
    HOOK_SRC_EXPORT = 1,  /* module + symbol */
    HOOK_SRC_RVA = 2,     /* rva relative to the image base */
};

enum HookEntryStatus
{
    HOOK_STATUS_MISSING = 0,
    HOOK_STATUS_READY = 1,
    HOOK_STATUS_PATCHED = 2,
};

enum HookSlotState
{
    HOOK_SLOT_EMPTY = 0,
    HOOK_SLOT_CLAIMED = 1,
    HOOK_SLOT_READY = 2,
};

/* log levels for the shim's own diagnostics (system events, kind ignored by C) */
#define HOOK_LOG_ERROR 0
#define HOOK_LOG_INFO  1
#define HOOK_LOG_TRACE 2

#define HOOK_HOOK_INDEX_SYSTEM 0xFFFFFFFFu

struct HookPattern
{
    uint32_t length; /* valid bytes; 0 ends the variant list */
    uint8_t bytes[HOOK_PATTERN_BYTES];
    uint8_t mask[HOOK_PATTERN_BYTES]; /* 0 = wildcard */
}; /* 132 bytes */

struct HookDescriptor
{
    char key[HOOK_KEY_MAX];
    uint32_t kind;
    uint32_t source;
    uint32_t stolenBytes;      /* >= HOOK_ENTRY_PATCH_BYTES, whole instructions */
    uint32_t fastOp;
    uint32_t fastSlot;
    uint32_t varargsVariant;   /* HOOK_KIND_VARARGS only, 0..7 */
    uint32_t eventKind;        /* Python-defined; C never interprets it */
    uint32_t scratchBytes;     /* <= 4096, rounded up to 16 */
    uint32_t programOffset;    /* into blobs[index] */
    uint32_t programLength;    /* bytes, multiple of 16 */
    uint32_t dataLength;       /* initial data bytes in blobs[index] */
    uint32_t patternCount;
    struct HookPattern patterns[HOOK_PATTERN_MAX];
    char module[HOOK_MODULE_MAX];  /* HOOK_SRC_EXPORT / HOOK_SRC_RVA */
    char symbol[HOOK_SYMBOL_MAX];  /* HOOK_SRC_EXPORT */
    uint64_t rva;                  /* HOOK_SRC_RVA */
    uint64_t targetHint;           /* reserved for RE use */
    uint32_t flags;
    uint32_t reserved;
}; /* 688 bytes */

struct HookRuntime
{
    char key[HOOK_KEY_MAX];
    volatile int32_t enabled;
    volatile int32_t status;
    int32_t selfIndex;
    int32_t reserved;
    volatile uint64_t hits;
    volatile uint64_t faults;
    uint64_t target;
    uint64_t trampoline;
    uint64_t detour;
    volatile uint64_t state[HOOK_STATE_SLOTS];
    uint8_t data[HOOK_DATA_MAX]; /* Python-owned; written via the pipe */
}; /* 1176 bytes */

struct HookEventSlot
{
    volatile int32_t state;
    int32_t sequence;
    uint32_t threadId;
    uint32_t hookIndex; /* HOOK_HOOK_INDEX_SYSTEM = shim diagnostics */
    uint32_t kind;
    uint32_t size;
    uint8_t data[HOOK_EVENT_MAX];
}; /* 792 bytes */

/*
 * Saved register context, built by the stub and consumed by ISA programs via
 * r15. Programs read game registers at ctx+8*i; writes into the context are
 * rejected by the memory guard up to (and excluding) the scratch area.
 */
struct HookCtx
{
    uint64_t gpr[16];      /* 0x000: rax rcx rdx rbx rsp rbp rsi rdi r8..r15 (entry values) */
    uint64_t xmm[12];      /* 0x080: xmm0..xmm5 as two u64 each */
    uint64_t entryRip;     /* 0x0E0: return address of the hooked call */
    uint64_t entryRsp;     /* 0x0E8: rsp at entry ([entryRsp] = return address) */
    uint64_t runtimePtr;   /* 0x0F0: &HookRuntime */
    uint32_t hookIndex;    /* 0x0F8 */
    uint32_t action;       /* 0x0FC: 0 = pass, 1 = skip */
    uint64_t retValue;     /* 0x100: used when action == 1 */
    uint64_t vm[16];       /* 0x108: ISA registers (r12..r15 preloaded by dispatch) */
    uint64_t reserved;     /* 0x188 */
    uint8_t scratch[4096]; /* 0x190 */
}; /* 4496 bytes, 16-aligned */

#define HOOK_CTX_FRAME_SIZE 4496
#define HOOK_CTX_SCRATCH_OFF 400u /* offsetof(struct HookCtx, scratch) */

struct HookPayload
{
    uint32_t magic;
    uint32_t version;
    uint32_t descriptorCount;
    uint32_t startDelayMs;
    uint32_t allowAnyModule;
    uint32_t reserved0;
    uint32_t payloadBytes; /* total size, sanity check */
    uint32_t reserved1;
    char targetProcess[HOOK_KEY_MAX]; /* agent/injector target, e.g. Growtopia.exe */
    struct HookDescriptor descriptors[HOOK_MAX];
    uint8_t blobs[HOOK_MAX][HOOK_PROGRAM_MAX + HOOK_DATA_MAX];
}; /* 316992 bytes */

struct HookHandshakeEntry
{
    char key[HOOK_KEY_MAX];
    uint32_t status;
    uint32_t index;
    uint64_t target;
    uint64_t trampoline;
}; /* 56 bytes */

struct HookHandshake
{
    uint32_t magic;
    uint32_t version;
    uint32_t descriptorCount;
    uint32_t reserved;
    uint64_t processId;
    uint64_t imageBase;
    uint64_t imageSize;
    uint64_t dllBase;
    struct HookHandshakeEntry entries[HOOK_MAX];
};

/*
 * The control block exported as g_self. The payload (descriptors + programs)
 * is delivered through this struct by the injector, then copied into
 * shim-local memory; only HookRuntime and the event ring stay live in the
 * shared block afterwards.
 */
struct ShimShared
{
    volatile int32_t magic;
    uint32_t version;
    volatile int32_t ready;
    volatile int32_t payloadRevision; /* != 0 releases the shim worker */
    uint32_t payloadCrc;
    uint32_t descriptorCount;
    uint64_t processId;
    uint64_t imageBase;
    uint64_t imageSize;
    uint64_t dllBase;
    uint64_t bootTick;
    volatile uint64_t eventTicket;
    struct HookRuntime runtime[HOOK_MAX];
    struct HookEventSlot events[HOOK_EVENT_SLOTS];
    uint8_t payload[HOOK_PAYLOAD_MAX];
};

/* pin the wire layout (also asserted from Python via test_hook_abi.py) */
_Static_assert(sizeof(struct HookCtx) == HOOK_CTX_FRAME_SIZE, "HookCtx layout");
_Static_assert(HOOK_CTX_FRAME_SIZE % 16 == 0, "HookCtx is 16-aligned for the stub");
_Static_assert(sizeof(struct HookPattern) == 132, "HookPattern layout");
_Static_assert(sizeof(struct HookDescriptor) == 688, "HookDescriptor layout");
_Static_assert(sizeof(struct HookRuntime) == 1176, "HookRuntime layout");
_Static_assert(sizeof(struct HookEventSlot) == 792, "HookEventSlot layout");
_Static_assert(sizeof(struct HookHandshakeEntry) == 56, "HookHandshakeEntry layout");

_Static_assert(sizeof(struct HookPayload) == 316992, "HookPayload layout");
_Static_assert(sizeof(struct HookPayload) <= HOOK_PAYLOAD_MAX, "payload fits the shared block");
_Static_assert(sizeof(struct ShimShared) == 663368, "ShimShared layout");

#endif /* __HOOK_PROTOCOL_H */
