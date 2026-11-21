/*
 * hook.c - the injected shim (feature-blind).
 *
 * v4 contract: everything that describes a hook (patterns, handler program,
 * fast op, enable flag, state, data) arrives as data in the install payload
 * written by the injector; nothing here names a game feature. The shim
 *
 *   1. waits for the payload (magic + version + crc, written by the injector),
 *   2. resolves every hook target (pattern scan with a retry window, export
 *      symbol, or rva) and validates the prologue with a length decoder,
 *   3. builds a trampoline per hook and a register-preserving stub + thunk
 *      per hook (hook_stub_x64.h),
 *   4. serves hook hits: native fast ops, or the ISA program (isa_core.h),
 *   5. publishes events into the shared ring for the agent to drain.
 *
 * BUILD_FLAGS[gcc(mingw)]: -O2 -shared -fPIC -mwindows
 * BUILD_FLAGS[msvc]: unsupported (the stub is GNU asm); mingw or clang only
 */

#ifndef _WIN32
/* hook.dll is Windows-only; keep compile_cmod.py's Linux job green */
int g_hook_windows_only;
#else

#define _CRT_SECURE_NO_WARNINGS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "hook_protocol.h"
#include "hook_prologue.h"
#include "hook_stub_x64.h"
#include "isa_core.h"

#if !defined(__GNUC__)
#error "hook.c requires a GNU-compatible compiler (mingw-w64 or clang): the stub is GNU asm"
#endif

#pragma comment(lib, "user32.lib")

#define EXPORT __attribute__((visibility("default")))

static uint64_t HookDispatchShim(struct HookCtx *ctx); /* 0 = pass, 1 = skip */

#define HOOK_LOG_LINE 512
#define HOOK_THUNK_SIZE 32
#define HOOK_THUNK_JMP_OFFSET 27
#define HOOK_PAYLOAD_WAIT_MS 30000
#define HOOK_EVENT_BACKLOG_SLOTS HOOK_EVENT_SLOTS

EXPORT struct ShimShared g_self;

/* shim-local copy of the payload descriptors (write-once before ready) */
static struct HookDescriptor g_descs[HOOK_MAX];
static int g_descCount = 0;
static uint32_t g_payloadStartDelay = 0;
static int g_payloadAllowAnyModule = 0;

static uint8_t *g_codeBase = NULL;
static size_t g_stubSize = 0;
static int g_varargsHookIndex[HOOK_VARARGS_VARIANTS];
static ULONGLONG g_lastFaultMs[HOOK_MAX];

static HANDLE g_processMutex = NULL;

/* ------------------------------------------------------------------ */
/* small helpers                                                       */

static void CopyText(char *destination, size_t destinationSize, const char *source)
{
    if (!destination || destinationSize == 0)
        return;
    if (!source)
    {
        destination[0] = 0;
        return;
    }
    size_t length = strlen(source);
    if (length >= destinationSize)
        length = destinationSize - 1;
    memcpy(destination, source, length);
    destination[length] = 0;
}

static size_t ImageSizeOf(uint8_t *base)
{
    if (!base)
        return 0;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE)
        return 0;
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE)
        return 0;
    return nt->OptionalHeader.SizeOfImage;
}

static void AcquireProcessHookMutex(void)
{
    char name[64];
    snprintf(name, sizeof(name), "%s%lu", HOOK_PID_MUTEX_PREFIX, (unsigned long)GetCurrentProcessId());

    HANDLE mutex = CreateMutexA(NULL, TRUE, name);
    if (!mutex)
        return;
    if (GetLastError() == ERROR_ALREADY_EXISTS)
    {
        CloseHandle(mutex);
        return;
    }
    g_processMutex = mutex;
}

/* ------------------------------------------------------------------ */
/* events (the shared ring the agent drains)                           */

static void HookPublishEvent(uint32_t hookIndex, uint32_t kind, const uint8_t *data, uint32_t length)
{
    LONG ticket = (LONG)(InterlockedIncrement64((volatile LONG64 *)&g_self.eventTicket) - 1);
    struct HookEventSlot *slot = &g_self.events[(size_t)((ULONG)ticket % HOOK_EVENT_SLOTS)];
    if (InterlockedCompareExchange((volatile LONG *)&slot->state, HOOK_SLOT_CLAIMED, HOOK_SLOT_EMPTY) != HOOK_SLOT_EMPTY)
        return; /* ring slot still busy: dropped, the consumer will see the gap */

    if (length > HOOK_EVENT_MAX)
        length = HOOK_EVENT_MAX;
    if (length)
        memcpy(slot->data, data, length);
    slot->size = length;
    slot->kind = kind;
    slot->hookIndex = hookIndex;
    slot->threadId = GetCurrentThreadId();
    slot->sequence = ticket;
    InterlockedExchange((volatile LONG *)&slot->state, HOOK_SLOT_READY);
}

static void HookLog(int level, const char *format, ...)
{
    char text[HOOK_LOG_LINE];
    va_list args;
    va_start(args, format);
    int written = vsnprintf(text, sizeof(text), format, args);
    va_end(args);
    if (written < 0)
        return;
    if ((size_t)written >= sizeof(text))
        text[sizeof(text) - 1] = 0;
    HookPublishEvent(HOOK_HOOK_INDEX_SYSTEM, (uint32_t)level, (const uint8_t *)text, (uint32_t)strlen(text));
}

/* ------------------------------------------------------------------ */
/* pattern scanning                                                    */

struct PatternBytes
{
    uint8_t bytes[HOOK_PATTERN_BYTES];
    uint8_t mask[HOOK_PATTERN_BYTES];
    size_t length;
};

static int HexNibble(char c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}

static int ParsePattern(const uint8_t *serialized, uint32_t length, const uint8_t *mask, struct PatternBytes *out)
{
    if (length == 0 || length > HOOK_PATTERN_BYTES)
        return 0;
    memcpy(out->bytes, serialized, length);
    memcpy(out->mask, mask, length);
    out->length = length;
    return 1;
}

static int PatternMatches(const uint8_t *memory, const struct PatternBytes *pattern)
{
    for (size_t i = 0; i < pattern->length; i++)
    {
        if (pattern->mask[i] && memory[i] != pattern->bytes[i])
            return 0;
    }
    return 1;
}

static uint8_t *FindUniquePattern(const struct PatternBytes *pattern, uint8_t *imageBase, size_t imageSize,
                                  int *matchCount)
{
    if (matchCount)
        *matchCount = 0;
    if (!imageBase || !imageSize || pattern->length == 0)
        return NULL;

    uint8_t *end = imageBase + imageSize;
    uint8_t *found = NULL;
    int count = 0;
    for (uint8_t *cursor = imageBase; cursor + pattern->length <= end; ++cursor)
    {
        if (!PatternMatches(cursor, pattern))
            continue;
        count++;
        if (!found)
            found = cursor;
        if (count > 1)
            break;
    }
    if (matchCount)
        *matchCount = count;
    return count == 1 ? found : NULL;
}

/* ------------------------------------------------------------------ */
/* trampolines + the stub/thunk code block                             */

static void write_abs_jump(unsigned char *buffer, uint64_t destination)
{
    buffer[0] = 0xFF;
    buffer[1] = 0x25;
    buffer[2] = 0;
    buffer[3] = 0;
    buffer[4] = 0;
    buffer[5] = 0;
    memcpy(buffer + 6, &destination, sizeof(destination));
}

static void *HookAllocExecutable(size_t size)
{
    void *block = VirtualAlloc(NULL, size, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (block)
        return block;
    DWORD error = GetLastError();
    block = VirtualAlloc(NULL, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!block)
    {
        HookLog(HOOK_LOG_ERROR, "[hook] cannot allocate the code block (err=%lu)", error);
        return NULL;
    }
    DWORD old = 0;
    if (!VirtualProtect(block, size, PAGE_EXECUTE_READWRITE, &old))
    {
        HookLog(HOOK_LOG_ERROR, "[hook] cannot make the code block executable (err=%lu)", GetLastError());
        VirtualFree(block, 0, MEM_RELEASE);
        return NULL;
    }
    HookLog(HOOK_LOG_INFO, "[hook] rwx allocation denied (%lu), using rw plus promote", error);
    return block;
}

static void *HookBuildTrampoline(const char *key, uint8_t *target, size_t stolenBytes)
{
    size_t size = stolenBytes + HOOK_ENTRY_PATCH_BYTES;
    void *trampoline = HookAllocExecutable(size);
    if (!trampoline)
        return NULL;

    memcpy(trampoline, target, stolenBytes);
    write_abs_jump((unsigned char *)trampoline + stolenBytes, (uint64_t)(uintptr_t)(target + stolenBytes));
    FlushInstructionCache(GetCurrentProcess(), trampoline, size);
    HookLog(HOOK_LOG_INFO, "[hook] %s: trampoline at %p for %p (%zu bytes)", key, trampoline, (void *)(uintptr_t)target,
            stolenBytes);
    return trampoline;
}

/*
 * Thunk layout (32 bytes), built here because the immediates depend on the
 * runtime block address of each hook:
 *
 *   49 BB <imm64>          mov r11, &runtime[i]
 *   41 83 BB <disp32> 00   cmp dword [r11+HOOK_RUNTIME_OFF_ENABLED], 0
 *   75 07                  jne enabled
 *   41 FF A3 <disp32>      jmp qword [r11+HOOK_RUNTIME_OFF_TRAMPOLINE]
 *   E9 <rel32>             jmp hook_stub_template
 */
static void HookWriteThunk(uint8_t *out, uint64_t runtimeAddress, int32_t relToStub)
{
    uint32_t enabledOffset = (uint32_t)offsetof(struct HookRuntime, enabled);
    uint32_t trampOffset = (uint32_t)offsetof(struct HookRuntime, trampoline);

    out[0] = 0x49;
    out[1] = 0xBB;
    memcpy(out + 2, &runtimeAddress, 8);
    out[10] = 0x41;
    out[11] = 0x83;
    out[12] = 0xBB;
    memcpy(out + 13, &enabledOffset, 4);
    out[17] = 0;
    out[18] = 0x75;
    out[19] = 0x07;
    out[20] = 0x41;
    out[21] = 0xFF;
    out[22] = 0xA3;
    memcpy(out + 23, &trampOffset, 4);
    out[27] = 0xE9;
    memcpy(out + 28, &relToStub, 4);
}

static int HookPatchCallMarker(uint8_t *block, size_t size)
{
    uint8_t marker[8];
    uint64_t dispatch = (uint64_t)(uintptr_t)&HookDispatchShim;
    memcpy(marker, &(uint64_t){HOOK_STUB_CALL_MARKER}, 8);
    for (size_t i = 0; i + 8 <= size; i++)
    {
        if (memcmp(block + i, marker, 8) != 0)
            continue;
        memcpy(block + i, &dispatch, 8);
        return 1;
    }
    return 0;
}

static int HookBuildCodeBlock(int descCount)
{
    g_stubSize = (size_t)(hook_stub_template_end - hook_stub_template);
    size_t total = g_stubSize + (size_t)descCount * HOOK_THUNK_SIZE;
    uint8_t *block = (uint8_t *)HookAllocExecutable(total);
    if (!block)
        return 0;

    memcpy(block, hook_stub_template, g_stubSize);
    if (!HookPatchCallMarker(block, g_stubSize))
    {
        HookLog(HOOK_LOG_ERROR, "[hook] the stub call marker is missing from the template");
        VirtualFree(block, 0, MEM_RELEASE);
        return 0;
    }

    uint8_t *thunks = block + g_stubSize;
    for (int i = 0; i < descCount; i++)
    {
        uint8_t *thunk = thunks + (size_t)i * HOOK_THUNK_SIZE;
        int64_t rel = (int64_t)(uintptr_t)block - (int64_t)(uintptr_t)(thunk + HOOK_THUNK_JMP_OFFSET + 5);
        if (rel > 0x7FFFFFFF || rel < -0x80000000LL)
        {
            HookLog(HOOK_LOG_ERROR, "[hook] thunk %d cannot reach the stub", i);
            VirtualFree(block, 0, MEM_RELEASE);
            return 0;
        }
        HookWriteThunk(thunk, (uint64_t)(uintptr_t)&g_self.runtime[i], (int32_t)rel);
    }

    FlushInstructionCache(GetCurrentProcess(), block, total);
    DWORD old = 0;
    VirtualProtect(block, total, PAGE_EXECUTE_READ, &old);
    g_codeBase = block;
    return 1;
}

/* ------------------------------------------------------------------ */
/* varargs detours (printf-style hooks; the only way to forward varargs) */

typedef long long (*FnVarargs)(const char *format, ...);

static void HookVarargsEmit(int index, const char *line)
{
    if (index < 0 || index >= g_descCount)
        return;
    struct HookRuntime *rt = &g_self.runtime[index];
    if (!rt->enabled || rt->status != HOOK_STATUS_PATCHED)
        return;
    HookPublishEvent((uint32_t)index, g_descs[index].eventKind, (const uint8_t *)line, (uint32_t)strlen(line));
}

static long long HookVarargsForward(int index, const char *line)
{
    FnVarargs trampoline = (FnVarargs)(uintptr_t)g_self.runtime[index].trampoline;
    return trampoline ? trampoline("%s", line) : 0;
}

#define HOOK_VARARGS_DETOUR(n)                                                           \
    static long long HookVarargs##n(const char *format, ...)                             \
    {                                                                                    \
        char line[HOOK_EVENT_MAX];                                                       \
        va_list args;                                                                    \
        int index = g_varargsHookIndex[n];                                               \
        va_start(args, format);                                                          \
        int written = vsnprintf(line, sizeof(line), format, args);                       \
        va_end(args);                                                                    \
        if (written < 0)                                                                 \
            line[0] = 0;                                                                 \
        else if ((size_t)written >= sizeof(line))                                        \
            line[sizeof(line) - 1] = 0;                                                  \
        if (index < 0)                                                                   \
            return 0;                                                                    \
        HookVarargsEmit(index, line);                                                    \
        return HookVarargsForward(index, line);                                          \
    }

HOOK_VARARGS_DETOUR(0)
HOOK_VARARGS_DETOUR(1)
HOOK_VARARGS_DETOUR(2)
HOOK_VARARGS_DETOUR(3)
HOOK_VARARGS_DETOUR(4)
HOOK_VARARGS_DETOUR(5)
HOOK_VARARGS_DETOUR(6)
HOOK_VARARGS_DETOUR(7)

static const void *const g_varargsDetours[HOOK_VARARGS_VARIANTS] = {
    (const void *)&HookVarargs0, (const void *)&HookVarargs1, (const void *)&HookVarargs2,
    (const void *)&HookVarargs3, (const void *)&HookVarargs4, (const void *)&HookVarargs5,
    (const void *)&HookVarargs6, (const void *)&HookVarargs7,
};

static uint64_t HookDetourFor(int index)
{
    const struct HookDescriptor *desc = &g_descs[index];
    if (desc->kind == HOOK_KIND_VARARGS && desc->varargsVariant < HOOK_VARARGS_VARIANTS &&
        g_varargsHookIndex[desc->varargsVariant] == index)
        return (uint64_t)(uintptr_t)g_varargsDetours[desc->varargsVariant];
    return (uint64_t)(uintptr_t)(g_codeBase + g_stubSize + (size_t)index * HOOK_THUNK_SIZE);
}

/* ------------------------------------------------------------------ */
/* ISA host callbacks                                                  */

struct IsaEnv
{
    struct HookCtx *ctx;
    struct HookRuntime *rt;
};

static int HookMemRead(void *raw, uint64_t address, uint32_t length, void *out)
{
    SIZE_T got = 0;
    if (length == 0)
        return 1;
    if (length > ISA_MEMCPY_MAX)
        return 0;
    if (!ReadProcessMemory(GetCurrentProcess(), (LPCVOID)(uintptr_t)address, out, length, &got) || got != length)
        return 0;
    return 1;
}

static int HookMemWrite(void *raw, uint64_t address, uint32_t length, const void *in)
{
    struct IsaEnv *env = (struct IsaEnv *)raw;
    SIZE_T written = 0;
    uint64_t base = (uint64_t)(uintptr_t)env->ctx;
    uint64_t scratch = base + HOOK_CTX_SCRATCH_OFF;

    if (length == 0)
        return 1;
    if (length > ISA_MEMCPY_MAX)
        return 0;
    /* the context's metadata (registers, rsp, action) is read-only for programs */
    if (address < scratch && address + length > base)
        return 0;

    MEMORY_BASIC_INFORMATION info;
    if (!VirtualQuery((LPCVOID)(uintptr_t)address, &info, sizeof(info)))
        return 0;
    if (info.State != MEM_COMMIT)
        return 0;
    switch (info.Protect & 0xFF)
    {
    case PAGE_READWRITE:
    case PAGE_WRITECOPY:
    case PAGE_EXECUTE_READWRITE:
    case PAGE_EXECUTE_WRITECOPY:
        break;
    default:
        return 0;
    }
    if (!WriteProcessMemory(GetCurrentProcess(), (LPVOID)(uintptr_t)address, in, length, &written) ||
        written != length)
        return 0;
    return 1;
}

static int HookEmit(void *raw, uint32_t kind, uint64_t address, uint32_t length)
{
    struct IsaEnv *env = (struct IsaEnv *)raw;
    uint8_t buffer[HOOK_EVENT_MAX];
    if (length > HOOK_EVENT_MAX)
        return 0;
    if (length && !HookMemRead(raw, address, length, buffer))
        return 0;
    HookPublishEvent((uint32_t)env->rt->selfIndex, kind, buffer, length);
    return 1;
}

static uint64_t HookNow(void *raw)
{
    (void)raw;
    return (uint64_t)GetTickCount64();
}

static void HookSleepUs(void *raw, uint64_t us)
{
    (void)raw;
    if (us)
        Sleep((DWORD)(us / 1000) + 1);
}

static uint64_t HookCall(void *raw, uint64_t fn, uint64_t a, uint64_t b, uint64_t c)
{
    typedef uint64_t (*FnCall)(uint64_t, uint64_t, uint64_t, uint64_t);
    (void)raw;
    FnCall call = (FnCall)(uintptr_t)fn;
    return call(a, b, c, 0);
}

static uint64_t HookDataPtr(void *raw)
{
    struct IsaEnv *env = (struct IsaEnv *)raw;
    return (uint64_t)(uintptr_t)env->rt->data;
}

static const uint8_t *HookProgramBytes(const struct HookDescriptor *desc, int index)
{
    size_t blobBase = offsetof(struct HookPayload, blobs) + (size_t)index * (HOOK_PROGRAM_MAX + HOOK_DATA_MAX);
    return g_self.payload + blobBase + desc->programOffset;
}

static void HookReportFault(struct HookRuntime *rt, enum IsaRunResult result)
{
    InterlockedIncrement64((volatile LONG64 *)&rt->faults);
    ULONGLONG now = GetTickCount64();
    int index = rt->selfIndex;
    if (index < 0 || index >= HOOK_MAX)
        return;
    if (g_lastFaultMs[index] && now - g_lastFaultMs[index] < 1000)
        return; /* rate limit: one fault event per second per hook */
    g_lastFaultMs[index] = now;
    char text[64];
    int written = snprintf(text, sizeof(text), "program fault result=%d", (int)result);
    if (written > 0)
        HookPublishEvent((uint32_t)index, 0, (const uint8_t *)text, (uint32_t)written);
}

/* ------------------------------------------------------------------ */
/* dispatch (called from the stub on the game's thread)                */

/* dispatch returns 0 = pass to the trampoline, 1 = skip the call; the skip
 * return value travels through ctx->retValue (a 16-byte struct return would
 * take the hidden-pointer slot in rcx and break the ctx argument) */

static void HookPass(struct HookCtx *ctx)
{
    ctx->action = 0;
}

static void HookSkip(struct HookCtx *ctx, uint64_t value)
{
    ctx->action = 1;
    ctx->retValue = value;
}

static void HookPaceFrame(int fps)
{
    static LARGE_INTEGER frequency;
    if (!frequency.QuadPart)
        QueryPerformanceFrequency(&frequency);
    if (frequency.QuadPart <= 0)
        return;

    static volatile LONG64 deadline = 0;
    LARGE_INTEGER counter;
    QueryPerformanceCounter(&counter);

    LONG64 period = (LONG64)(frequency.QuadPart / fps);
    if (period <= 0)
        period = 1;

    LONG64 current = (LONG64)counter.QuadPart;
    LONG64 previous = (LONG64)InterlockedCompareExchange64(&deadline, 0, 0);
    if (previous <= current)
        previous = current;
    InterlockedExchange64(&deadline, previous + period);

    LONG64 remaining = previous - current;
    if (remaining <= 0)
        return;
    DWORD milliseconds = (DWORD)((remaining * 1000) / frequency.QuadPart);
    if (milliseconds > 0)
        Sleep(milliseconds);
}

static void HookFastDispatch(struct HookRuntime *rt, const struct HookDescriptor *desc, struct HookCtx *ctx)
{
    uint64_t value = rt->state[desc->fastSlot % HOOK_STATE_SLOTS];
    switch (desc->fastOp)
    {
    case HOOK_FAST_DROP:
        if (value)
        {
            HookSkip(ctx, 0);
            return;
        }
        break;
    case HOOK_FAST_RETURN:
        if (value)
        {
            HookSkip(ctx, value);
            return;
        }
        break;
    case HOOK_FAST_PACE:
        if (value)
            HookPaceFrame((int)(value > 240 ? 240 : value));
        break;
    default:
        break;
    }
    HookPass(ctx);
}

static void HookIsaDispatch(struct HookRuntime *rt, const struct HookDescriptor *desc, struct HookCtx *ctx)
{
    struct IsaEnv env = {ctx, rt};
    struct IsaHost host = {&env, HookMemRead,  HookMemWrite, HookEmit, HookNow,
                           HookSleepUs, HookCall, HookDataPtr};

    ctx->vm[15] = (uint64_t)(uintptr_t)ctx;
    ctx->vm[14] = (uint64_t)(uintptr_t)rt;
    ctx->vm[13] = (uint64_t)(uintptr_t)ctx->scratch;
    ctx->vm[12] = sizeof(ctx->scratch);

    enum IsaRunResult result =
        isa_run(&host, HookProgramBytes(desc, rt->selfIndex), desc->programLength, ctx->vm, ISA_MAX_STEPS);
    if (result == ISA_RUN_SKIP)
    {
        HookSkip(ctx, ctx->vm[0]);
        return;
    }
    if (result != ISA_RUN_PASS)
        HookReportFault(rt, result);
    HookPass(ctx);
}

__attribute__((noinline)) uint64_t HookDispatchShim(struct HookCtx *ctx)
{
    struct HookRuntime *rt = (struct HookRuntime *)(uintptr_t)ctx->runtimePtr;
    if (!rt || rt->selfIndex < 0 || rt->selfIndex >= HOOK_MAX)
    {
        HookSkip(ctx, 0);
        return 1;
    }

    ctx->hookIndex = (uint32_t)rt->selfIndex;
    InterlockedIncrement64((volatile LONG64 *)&rt->hits);

    if (!rt->enabled || rt->status != HOOK_STATUS_PATCHED)
    {
        HookPass(ctx);
        return 0;
    }

    const struct HookDescriptor *desc = &g_descs[rt->selfIndex];
    switch (desc->kind)
    {
    case HOOK_KIND_FAST:
        HookFastDispatch(rt, desc, ctx);
        break;
    case HOOK_KIND_ISA:
        HookIsaDispatch(rt, desc, ctx);
        break;
    default:
        HookPass(ctx);
        break;
    }
    return ctx->action ? 1 : 0;
}

/* ------------------------------------------------------------------ */
/* target resolution + publish                                         */

static int HookResolvePattern(const struct HookDescriptor *desc, int index, uint8_t *image, size_t imageSize,
                              uint8_t **outTarget, size_t *outStolen)
{
    int ambiguous = 0;
    for (uint32_t v = 0; v < desc->patternCount && v < HOOK_PATTERN_MAX; v++)
    {
        struct PatternBytes pattern;
        if (!ParsePattern(desc->patterns[v].bytes, desc->patterns[v].length, desc->patterns[v].mask, &pattern))
        {
            HookLog(HOOK_LOG_ERROR, "[hook] %s: pattern variant %u failed to parse", desc->key, v);
            continue;
        }
        int matchCount = 0;
        uint8_t *target = FindUniquePattern(&pattern, image, imageSize, &matchCount);
        if (target)
        {
            size_t stolen = hook_prologue_length(target, imageSize - (size_t)(target - image), HOOK_ENTRY_PATCH_BYTES);
            if (!stolen)
            {
                HookLog(HOOK_LOG_ERROR, "[hook] %s: the prologue at %p cannot be stolen safely, skipping",
                        desc->key, (void *)(uintptr_t)target);
                continue;
            }
            if (stolen != desc->stolenBytes)
                HookLog(HOOK_LOG_INFO, "[hook] %s: decoded prologue is %zu bytes (descriptor said %u)", desc->key,
                        stolen, desc->stolenBytes);
            *outTarget = target;
            *outStolen = stolen;
            return 1;
        }
        if (matchCount > 1)
        {
            ambiguous = 1;
            HookLog(HOOK_LOG_ERROR, "[hook] %s: variant %u matches %d places", desc->key, v, matchCount);
        }
    }
    if (ambiguous)
        HookLog(HOOK_LOG_ERROR, "[hook] %s: no unambiguous signature, refusing to patch", desc->key);
    return 0;
}

static int HookResolveExport(const struct HookDescriptor *desc, uint8_t **outTarget)
{
    HMODULE module = GetModuleHandleA(desc->module[0] ? desc->module : "kernel32.dll");
    if (!module)
        return 0;
    FARPROC address = GetProcAddress(module, desc->symbol);
    if (!address)
        return 0;
    *outTarget = (uint8_t *)(uintptr_t)address;
    return 1;
}

static int HookPublishEntry(int index, uint8_t *target, size_t stolenBytes)
{
    struct HookRuntime *rt = &g_self.runtime[index];
    void *trampoline = HookBuildTrampoline(g_descs[index].key, target, stolenBytes);
    if (!trampoline)
        return 0;

    rt->target = (uint64_t)(uintptr_t)target;
    rt->trampoline = (uint64_t)(uintptr_t)trampoline;
    rt->detour = HookDetourFor(index);
    rt->status = HOOK_STATUS_READY;
    HookLog(HOOK_LOG_INFO, "[hook] %s: resolved at %p (stolen %zu bytes)", g_descs[index].key,
            (void *)(uintptr_t)target, stolenBytes);
    return 1;
}

static int HookResolveOne(const struct HookDescriptor *desc, int index, uint8_t *image, size_t imageSize)
{
    uint8_t *target = NULL;
    size_t stolen = 0;

    switch (desc->source)
    {
    case HOOK_SRC_PATTERN:
        if (!HookResolvePattern(desc, index, image, imageSize, &target, &stolen))
            return 0;
        break;
    case HOOK_SRC_EXPORT:
        if (!HookResolveExport(desc, &target))
            return 0;
        stolen = hook_prologue_length(target, 256, HOOK_ENTRY_PATCH_BYTES);
        if (!stolen)
        {
            HookLog(HOOK_LOG_ERROR, "[hook] %s: export prologue cannot be stolen safely", desc->key);
            return 0;
        }
        break;
    case HOOK_SRC_RVA:
        if (!image)
            return 0;
        target = image + desc->rva;
        stolen = hook_prologue_length(target, 256, HOOK_ENTRY_PATCH_BYTES);
        if (!stolen)
        {
            HookLog(HOOK_LOG_ERROR, "[hook] %s: rva prologue cannot be stolen safely", desc->key);
            return 0;
        }
        break;
    default:
        return 0;
    }

    return HookPublishEntry(index, target, stolen);
}

/* ------------------------------------------------------------------ */
/* payload + worker                                                    */

static uint32_t crc32_of(const uint8_t *data, size_t length)
{
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < length; i++)
    {
        crc ^= data[i];
        for (int bit = 0; bit < 8; bit++)
            crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1)));
    }
    return crc ^ 0xFFFFFFFFu;
}

static int HookPayloadValid(void)
{
    struct HookPayload *payload = (struct HookPayload *)g_self.payload;
    if (payload->magic != HOOK_PAYLOAD_MAGIC)
        return 0;
    if (payload->version != HOOK_PROTOCOL_VERSION)
        return 0;
    if (payload->payloadBytes != sizeof(struct HookPayload))
        return 0;
    if (payload->descriptorCount > HOOK_MAX)
        return 0;
    if (g_self.payloadCrc != crc32_of(g_self.payload, sizeof(struct HookPayload)))
    {
        HookLog(HOOK_LOG_ERROR, "[hook] payload crc mismatch (got 0x%08X, expected 0x%08X)", crc32_of(g_self.payload, sizeof(struct HookPayload)),
                (unsigned)g_self.payloadCrc);
        return 0;
    }
    return 1;
}

static DWORD WINAPI ShimWorker(LPVOID unused)
{
    (void)unused;

    InterlockedExchange((volatile LONG *)&g_self.magic, (LONG)HOOK_PROTOCOL_MAGIC);
    g_self.version = HOOK_PROTOCOL_VERSION;

    AcquireProcessHookMutex();

    for (int attempt = 0; attempt < HOOK_PAYLOAD_WAIT_MS / 100 && g_self.payloadRevision == 0; attempt++)
        Sleep(100);
    if (g_self.payloadRevision == 0)
    {
        HookLog(HOOK_LOG_ERROR, "[hook] no install payload arrived, the shim stays idle");
        return 0;
    }
    if (!HookPayloadValid())
    {
        HookLog(HOOK_LOG_ERROR, "[hook] the install payload is invalid, the shim stays idle");
        return 0;
    }

    struct HookPayload *payload = (struct HookPayload *)g_self.payload;
    g_descCount = (int)payload->descriptorCount;
    g_payloadStartDelay = payload->startDelayMs;
    g_payloadAllowAnyModule = payload->allowAnyModule;

    memcpy(g_descs, payload->descriptors, sizeof(struct HookDescriptor) * (size_t)g_descCount);
    for (int i = 0; i < HOOK_VARARGS_VARIANTS; i++)
        g_varargsHookIndex[i] = -1;

    for (int i = 0; i < g_descCount; i++)
    {
        struct HookRuntime *rt = &g_self.runtime[i];
        struct HookDescriptor *desc = &g_descs[i];
        CopyText(rt->key, sizeof(rt->key), desc->key);
        rt->selfIndex = i;
        rt->status = HOOK_STATUS_MISSING;
        rt->enabled = 0;
        rt->hits = 0;
        rt->faults = 0;
        rt->target = 0;
        rt->trampoline = 0;
        rt->detour = 0;

        if (desc->kind == HOOK_KIND_VARARGS)
        {
            if (desc->varargsVariant >= HOOK_VARARGS_VARIANTS || g_varargsHookIndex[desc->varargsVariant] != -1)
            {
                HookLog(HOOK_LOG_ERROR, "[hook] %s: varargs variant %u is taken or invalid", desc->key,
                        desc->varargsVariant);
                continue;
            }
            g_varargsHookIndex[desc->varargsVariant] = i;
        }

        /* seed the Python-owned data blob */
        size_t blobBase = offsetof(struct HookPayload, blobs) + (size_t)i * (HOOK_PROGRAM_MAX + HOOK_DATA_MAX);
        uint32_t dataLength = desc->dataLength > HOOK_DATA_MAX ? HOOK_DATA_MAX : desc->dataLength;
        if (dataLength)
            memcpy(rt->data, g_self.payload + blobBase + HOOK_PROGRAM_MAX, dataLength);
    }

    if (g_payloadStartDelay)
        Sleep(g_payloadStartDelay);

    HMODULE self = NULL;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       (LPCWSTR)&ShimWorker, &self);

    uint8_t *image = (uint8_t *)GetModuleHandleA(payload->targetProcess);
    if (!image && g_payloadAllowAnyModule)
        image = (uint8_t *)GetModuleHandleA(NULL);
    size_t imageSize = ImageSizeOf(image);
    if (!image)
    {
        HookLog(HOOK_LOG_ERROR, "[hook] the target image could not be resolved, the shim stays idle");
        return 0;
    }

    if (!HookBuildCodeBlock(g_descCount))
        return 0;

    ULONGLONG deadline = GetTickCount64() + HOOK_PATTERN_SCAN_TIMEOUT_MS;
    for (;;)
    {
        int pending = 0;
        for (int i = 0; i < g_descCount; i++)
        {
            if (g_self.runtime[i].status != HOOK_STATUS_MISSING)
                continue;
            if (HookResolveOne(&g_descs[i], i, image, imageSize))
                continue;
            pending++;
        }
        if (!pending || GetTickCount64() >= deadline)
            break;
        Sleep(HOOK_PATTERN_SCAN_RETRY_MS);
    }

    int resolved = 0;
    for (int i = 0; i < g_descCount; i++)
    {
        if (g_self.runtime[i].status != HOOK_STATUS_MISSING)
            resolved++;
    }
    if (resolved < g_descCount)
        HookLog(HOOK_LOG_ERROR, "[hook] %d/%d hooks resolved after the scan window", resolved, g_descCount);
    else
        HookLog(HOOK_LOG_INFO, "[hook] %d/%d hooks resolved", resolved, g_descCount);

    g_self.processId = (uint64_t)GetCurrentProcessId();
    g_self.imageBase = (uint64_t)(uintptr_t)image;
    g_self.imageSize = (uint64_t)imageSize;
    g_self.dllBase = (uint64_t)(uintptr_t)self;
    g_self.bootTick = (uint64_t)GetTickCount64();

    InterlockedExchange((volatile LONG *)&g_self.ready, 1);
    HookLog(HOOK_LOG_INFO, "[hook] shim ready: pid %lu image %p (size 0x%zX) dll %p",
            (unsigned long)GetCurrentProcessId(), (void *)(uintptr_t)image, imageSize, (void *)(uintptr_t)self);
    return 0;
}

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH)
    {
        DisableThreadLibraryCalls(module);
        if (!CreateThread(NULL, 0, ShimWorker, NULL, 0, NULL))
            OutputDebugStringA("[hook] cannot start the shim worker\n");
    }
    else if (reason == DLL_PROCESS_DETACH)
    {
        if (g_processMutex)
            CloseHandle(g_processMutex);
    }
    return TRUE;
}

#endif /* _WIN32 */
