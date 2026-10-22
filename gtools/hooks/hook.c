// BUILD_FLAGS[gcc, clang]: -O3 -march=native -ffast-math -funroll-loops -shared -fPIC
// BUILD_FLAGS[gcc]: -fopenmp -fomit-frame-pointer -falign-functions=32 -falign-loops=32
// BUILD_FLAGS[msvc]: /O2 /arch:AVX2 /fp:fast /openmp /GL /Gy /TC
// BUILD_FLAGS[gcc(mingw)]: -O2 -shared -fPIC -mwindows

#define _CRT_SECURE_NO_WARNINGS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <sddl.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <tlhelp32.h>

#include "hook_protocol.h"

#pragma comment(lib, "user32.lib")
#pragma comment(lib, "advapi32.lib")

#if defined(_MSC_VER)
#  define FASTCALL __fastcall
#else
#  define FASTCALL
#endif

#define RESPONSE_STATUS_OFFSET 0xE0
#define RESPONSE_BODY_OFFSET   0x60

#define DICT_SENTINEL_OFFSET   0x08
#define DICT_NODE_KEY_OFFSET   0x10
#define DICT_NODE_VALUE_OFFSET 0x30

#define STOLEN_LOG_BYTES       27
#define STOLEN_RESPONSE_BYTES  17
#define STOLEN_HTTP_POST_BYTES 21

#define GAME_STRING_INLINE_CAPACITY 16

#define MAX_LOG_LINE          8192
#define MAX_LOG_MESSAGE       1024
#define MAX_EVENT_TEXT        512
#define MAX_PIPE_LINE         4096
#define PIPE_POLL_INTERVAL_MS 20
#define MAX_CONFIG_LINE       1024
#define MAX_HOST_LENGTH       128
#define MAX_VERSION_LENGTH    64
#define MAX_SERVER_LENGTH     64

#define MAX_PIPE_CLIENTS      4
#define CLIENT_EVENT_CAPACITY 64

#define LOG_BACKLOG_CAPACITY 128
#define LOG_BACKLOG_LINE     512

enum LogLevel
{
    LOG_LEVEL_ERROR = 0,
    LOG_LEVEL_INFO = 1,
    LOG_LEVEL_TRACE = 2,
};

static uint8_t *g_imageBase = NULL;
static size_t g_imageSize = 0;
static uint8_t *g_selfBase = NULL;
static size_t g_selfSize = 0;
static HMODULE g_selfModule = NULL;
static ULONGLONG g_startTick = 0;

static struct HookHandshake g_handshake;
static volatile LONG g_handshakeReady = 0;

static void QueueEvent(const char *name, const char *text);

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

static char g_logBacklog[LOG_BACKLOG_CAPACITY][LOG_BACKLOG_LINE];
static size_t g_logBacklogHead = 0;
static size_t g_logBacklogCount = 0;
static CRITICAL_SECTION g_logLock;
static volatile LONG g_logLockReady = 0;
static volatile LONG g_logLevel = LOG_LEVEL_INFO;

static int CurrentLogLevel(void)
{
    return (int)InterlockedCompareExchange(&g_logLevel, 0, 0);
}

static void LogEmit(const char *message, int keep)
{
    if (!message)
        return;

    char line[MAX_LOG_MESSAGE + 128];
    SYSTEMTIME st;
    GetLocalTime(&st);
    int written = snprintf(line, sizeof(line), "[%02u:%02u:%02u.%03u][tid %5lu] %s\n", st.wHour, st.wMinute, st.wSecond,
                           st.wMilliseconds, (unsigned long)GetCurrentThreadId(), message);
    if (written < 0)
        return;
    if ((size_t)written >= sizeof(line))
        line[sizeof(line) - 1] = 0;

    OutputDebugStringA(line);

    if (keep && g_logLockReady)
    {
        EnterCriticalSection(&g_logLock);
        CopyText(g_logBacklog[g_logBacklogHead], LOG_BACKLOG_LINE, line);
        g_logBacklogHead = (g_logBacklogHead + 1) % LOG_BACKLOG_CAPACITY;
        if (g_logBacklogCount < LOG_BACKLOG_CAPACITY)
            g_logBacklogCount++;
        LeaveCriticalSection(&g_logLock);
    }

    QueueEvent("log", message);
}

static void LogError(const char *format, ...)
{
    char message[MAX_LOG_MESSAGE];
    va_list args;
    va_start(args, format);
    int written = vsnprintf(message, sizeof(message), format, args);
    va_end(args);
    if (written < 0)
        return;
    if ((size_t)written >= sizeof(message))
        message[sizeof(message) - 1] = 0;
    LogEmit(message, 1);
}

static void LogInfo(const char *format, ...)
{
    if (CurrentLogLevel() < LOG_LEVEL_INFO)
        return;

    char message[MAX_LOG_MESSAGE];
    va_list args;
    va_start(args, format);
    int written = vsnprintf(message, sizeof(message), format, args);
    va_end(args);
    if (written < 0)
        return;
    if ((size_t)written >= sizeof(message))
        message[sizeof(message) - 1] = 0;
    LogEmit(message, 1);
}

static void LogTrace(const char *format, ...)
{
    if (CurrentLogLevel() < LOG_LEVEL_TRACE)
        return;

    char message[MAX_LOG_MESSAGE];
    va_list args;
    va_start(args, format);
    int written = vsnprintf(message, sizeof(message), format, args);
    va_end(args);
    if (written < 0)
        return;
    if ((size_t)written >= sizeof(message))
        message[sizeof(message) - 1] = 0;
    LogEmit(message, 0);
}

struct SSO
{
    char *buffer;
    uint64_t padding;
    uint64_t size;
    uint64_t capacity;
};

static const char *SSOData(const struct SSO *value)
{
    if (!value)
        return NULL;

    return (value->capacity > 0xF) ? value->buffer : (const char *)value;
}

static void CopyGameString(char *destination, size_t destinationSize, const struct SSO *source)
{
    if (!destination || destinationSize == 0)
        return;
    destination[0] = 0;
    if (!source || !source->size)
        return;
    const char *data = SSOData(source);
    if (!data)
        return;
    size_t length = source->size;
    if (length >= destinationSize)
        length = destinationSize - 1;
    memcpy(destination, data, length);
    destination[length] = 0;
}

static int ApplySSO(struct SSO *target, const char *data, size_t length)
{
    if (!target || !data)
        return 0;

    if (target->capacity > 0xF)
    {
        if (length + 1 > target->capacity)
        {
            size_t capacity = length + 0x40;
            char *buffer = (char *)malloc(capacity);
            if (!buffer)
                return 0;
            memcpy(buffer, data, length + 1);
            free(target->buffer);
            target->buffer = buffer;
            target->capacity = capacity;
        }
        else
        {
            memcpy(target->buffer, data, length + 1);
        }
        target->size = length;
        return 1;
    }

    if (length + 1 <= GAME_STRING_INLINE_CAPACITY)
    {
        memcpy(target, data, length + 1);
        target->size = length;
        return 1;
    }

    size_t capacity = length + 0x40;
    char *buffer = (char *)malloc(capacity);
    if (!buffer)
        return 0;

    memcpy(buffer, data, length + 1);
    target->buffer = buffer;
    target->capacity = capacity;
    target->size = length;

    return 1;
}

struct TextBuffer
{
    char *data;
    size_t length;
    size_t capacity;
};

static void BufferReserve(struct TextBuffer *buffer, size_t extra)
{
    if (buffer->length + extra + 1 <= buffer->capacity)
        return;
    size_t capacity = buffer->capacity ? buffer->capacity : 256;
    while (capacity < buffer->length + extra + 1)
        capacity *= 2;
    char *data = (char *)realloc(buffer->data, capacity);
    if (!data)
        return;
    buffer->data = data;
    buffer->capacity = capacity;
}

static void BufferAppend(struct TextBuffer *buffer, const char *text, size_t length)
{
    if (!text || length == 0)
        return;
    BufferReserve(buffer, length);
    if (!buffer->data)
        return;
    memcpy(buffer->data + buffer->length, text, length);
    buffer->length += length;
    buffer->data[buffer->length] = 0;
}

static void BufferAppendText(struct TextBuffer *buffer, const char *text)
{
    if (!text)
        return;
    BufferAppend(buffer, text, strlen(text));
}

static void BufferAppendFormat(struct TextBuffer *buffer, const char *format, ...)
{
    char scratch[MAX_LOG_MESSAGE];
    va_list args;
    va_start(args, format);
    int written = vsnprintf(scratch, sizeof(scratch), format, args);
    va_end(args);
    if (written < 0)
        return;
    if ((size_t)written >= sizeof(scratch))
        written = (int)sizeof(scratch) - 1;
    BufferAppend(buffer, scratch, (size_t)written);
}

static void BufferFree(struct TextBuffer *buffer)
{
    free(buffer->data);
    buffer->data = NULL;
    buffer->length = 0;
    buffer->capacity = 0;
}

struct HookState
{
    char proxyHost[MAX_HOST_LENGTH];
    int proxyPort;
    int startDelayMs;
    int logLevel;
    int allowAnyModule;
    int streamGameLogs;

    char clientVersion[MAX_VERSION_LENGTH];
    char clientProtocol[MAX_VERSION_LENGTH];
    char clientPlatform[MAX_VERSION_LENGTH];
    char realServer[MAX_SERVER_LENGTH];
    int realPort;
};

enum SettingKind
{
    SETTING_TEXT,
    SETTING_NUMBER,
};

struct SettingDescriptor
{
    const char *name;
    enum SettingKind kind;
    size_t offset;
    size_t capacity;
    long minimum;
    long maximum;
    int writable;
};

#define TEXT_FIELD(field) offsetof(struct HookState, field), sizeof(((struct HookState *)0)->field), 0, 0

#define NUMBER_FIELD(field, low, high) offsetof(struct HookState, field), 0, (low), (high)

static const struct SettingDescriptor g_settings[] = {
    {"proxy_host", SETTING_TEXT, TEXT_FIELD(proxyHost), 1},
    {"proxy_port", SETTING_NUMBER, NUMBER_FIELD(proxyPort, 1, 65535), 1},
    {"start_delay_ms", SETTING_NUMBER, NUMBER_FIELD(startDelayMs, 0, 600000), 1},
    {"log_level", SETTING_NUMBER, NUMBER_FIELD(logLevel, 0, 2), 1},
    {"allow_any_module", SETTING_NUMBER, NUMBER_FIELD(allowAnyModule, 0, 1), 1},
    {"stream_game_logs", SETTING_NUMBER, NUMBER_FIELD(streamGameLogs, 0, 1), 1},

    {"client_version", SETTING_TEXT, TEXT_FIELD(clientVersion), 0},
    {"client_protocol", SETTING_TEXT, TEXT_FIELD(clientProtocol), 0},
    {"client_platform", SETTING_TEXT, TEXT_FIELD(clientPlatform), 0},
    {"real_server", SETTING_TEXT, TEXT_FIELD(realServer), 0},
    {"real_port", SETTING_NUMBER, NUMBER_FIELD(realPort, 0, 65535), 0},
};

#define SETTING_COUNT ((int)(sizeof(g_settings) / sizeof(g_settings[0])))

static CRITICAL_SECTION g_stateLock;
static volatile LONG g_stateLockReady = 0;

static struct HookState g_state;

static void LockState(void)
{
    if (g_stateLockReady)
        EnterCriticalSection(&g_stateLock);
}

static void UnlockState(void)
{
    if (g_stateLockReady)
        LeaveCriticalSection(&g_stateLock);
}

static const struct SettingDescriptor *FindSetting(const char *name)
{
    if (!name)
        return NULL;

    for (int i = 0; i < SETTING_COUNT; i++)
    {
        if (_stricmp(g_settings[i].name, name) == 0)
            return &g_settings[i];
    }

    return NULL;
}

static void *SettingPointer(const struct SettingDescriptor *descriptor)
{
    return (char *)&g_state + descriptor->offset;
}

static void FormatSetting(const struct SettingDescriptor *descriptor, char *out, size_t outSize)
{
    if (!descriptor || !out || outSize == 0)
        return;
    void *pointer = SettingPointer(descriptor);
    if (descriptor->kind == SETTING_NUMBER)
        snprintf(out, outSize, "%d", *(int *)pointer);
    else
        CopyText(out, outSize, (const char *)pointer);
}

static int ApplySetting(const struct SettingDescriptor *descriptor, const char *value, char *error, size_t errorSize)
{
    if (!descriptor)
        return 0;

    if (!descriptor->writable)
    {
        snprintf(error, errorSize, "%s is read only", descriptor->name);
        return 0;
    }
    if (!value)
    {
        snprintf(error, errorSize, "missing value");
        return 0;
    }

    void *pointer = SettingPointer(descriptor);
    if (descriptor->kind == SETTING_NUMBER)
    {
        char *end = NULL;
        long parsed = strtol(value, &end, 10);
        if (!end || *end != 0 || parsed < descriptor->minimum || parsed > descriptor->maximum)
        {
            snprintf(error, errorSize, "%s expects a number between %ld and %ld", descriptor->name, descriptor->minimum,
                     descriptor->maximum);
            return 0;
        }
        *(int *)pointer = (int)parsed;
        return 1;
    }

    if (strlen(value) >= descriptor->capacity)
    {
        snprintf(error, errorSize, "%s is too long", descriptor->name);
        return 0;
    }
    memcpy(pointer, value, strlen(value) + 1);

    return 1;
}

static void ApplyLogLevelSetting(void)
{
    InterlockedExchange(&g_logLevel, g_state.logLevel);
}

struct QueuedEvent
{
    char name[32];
    char text[MAX_EVENT_TEXT];
};

struct PipeReader
{
    char buffer[MAX_PIPE_LINE * 2];
    size_t length;
    size_t position;
};

struct PipeClient
{
    HANDLE pipe;
    struct PipeReader reader;
    struct QueuedEvent events[CLIENT_EVENT_CAPACITY];
    size_t head;
    size_t tail;
    size_t count;
    volatile LONG active;
};

static struct PipeClient g_clients[MAX_PIPE_CLIENTS];
static CRITICAL_SECTION g_clientLock;
static volatile LONG g_clientLockReady = 0;

static void QueueEvent(const char *name, const char *text)
{
    if (!name || !text || !g_clientLockReady)
        return;

    EnterCriticalSection(&g_clientLock);
    for (int i = 0; i < MAX_PIPE_CLIENTS; i++)
    {
        struct PipeClient *client = &g_clients[i];
        if (!client->active)
            continue;
        if (client->count == CLIENT_EVENT_CAPACITY)
        {
            client->tail = (client->tail + 1) % CLIENT_EVENT_CAPACITY;
            client->count--;
        }
        struct QueuedEvent *slot = &client->events[client->head];
        CopyText(slot->name, sizeof(slot->name), name);
        CopyText(slot->text, sizeof(slot->text), text);
        client->head = (client->head + 1) % CLIENT_EVENT_CAPACITY;
        client->count++;
    }
    LeaveCriticalSection(&g_clientLock);
}

static int PopEvent(struct PipeClient *client, struct QueuedEvent *out)
{
    if (!client || !out || !g_clientLockReady)
        return 0;

    EnterCriticalSection(&g_clientLock);
    if (client->count == 0)
    {
        LeaveCriticalSection(&g_clientLock);
        return 0;
    }
    *out = client->events[client->tail];
    client->tail = (client->tail + 1) % CLIENT_EVENT_CAPACITY;
    client->count--;
    LeaveCriticalSection(&g_clientLock);
    return 1;
}

typedef long long(FASTCALL *FnGameLog)(const char *format, ...);
typedef void(FASTCALL *FnServerDataResponse)(void *closure, void *response);
typedef uintptr_t(FASTCALL *FnHttpClientPost)(void *client, void *url, int isTls, void *dictionary, void *callback);

static FnGameLog g_trampolineLogPrintf = NULL;
static FnGameLog g_trampolineLogRaw = NULL;
static FnServerDataResponse g_trampolineServerDataResponse = NULL;
static FnHttpClientPost g_trampolineHttpClientPost = NULL;

enum HookStatus
{
    HOOK_STATUS_MISSING = 0,
    HOOK_STATUS_READY = 1,
    HOOK_STATUS_PATCHED = 2,
};

struct HookSpec
{
    const char *name;
    const char *key;
    char signature[256];
    uint32_t stolenBytes;
    void *detour;
    void (*bindTrampoline)(void *address);
};

struct HookRuntime
{
    uint8_t *target;
    void *trampoline;
    enum HookStatus status;
};

static long long FASTCALL Hook_GameLogPrintf(const char *format, ...);
static long long FASTCALL Hook_GameLogRaw(const char *format, ...);
static void FASTCALL Hook_ServerDataResponse(void *closure, void *response);
static uintptr_t FASTCALL Hook_HttpClientPost(void *client, void *url, int isTls, void *dictionary, void *callback);

static void BindLogPrintfTrampoline(void *address);
static void BindLogRawTrampoline(void *address);
static void BindServerDataResponseTrampoline(void *address);
static void BindHttpClientPostTrampoline(void *address);

static struct HookSpec g_hookSpecs[] = {
    {"GameLog_Printf",       "game_log_printf",
     "48 89 4C 24 08 48 89 54 24 10 4C 89 44 24 18 4C 89 4C 24 20 53 57 B8 88 10 00 00 E8 ?? ?? ?? ?? 48 2B E0 48 8B "
     "05 ?? ?? ?? ?? 48 33 C4 48 89 84 24 70 10 00 00 48 8B D9 33 D2 48 8D 4C 24 70 41", STOLEN_LOG_BYTES,       NULL, BindLogPrintfTrampoline         },
    {"GameLog_Raw",          "game_log_raw",
     "48 89 4C 24 08 48 89 54 24 10 4C 89 44 24 18 4C 89 4C 24 20 53 57 B8 68 28 00 00 E8 ?? ?? ?? ?? 48 2B E0 48 8B "
     "05 ?? ?? ?? ?? 48 33 C4 48 89 84 24 50 28 00 00 48 8B D9 33 D2 48 8D 4C 24 40 41", STOLEN_LOG_BYTES,       NULL, BindLogRawTrampoline            },
    {"OnServerDataResponse", "server_data_response",
     "40 55 56 48 83 EC 28 81 BA ?? ?? ?? ?? C8 00 00 00 48 8B EA 48 8B 41 08 48 8B F1 75 1D C7 80 ?? ?? ?? ?? 00 "
     "00 00 00",                                                                         STOLEN_RESPONSE_BYTES,  NULL, BindServerDataResponseTrampoline},
    {"HttpClient_Post",      "http_client_post",
     "40 55 53 56 57 41 54 41 55 41 56 41 57 48 8D AC 24 48 FD FF FF 48 81 EC B8 03 00 00 48 8B 05 ?? ?? ?? ?? 48 "
     "33 C4 48 89 85 A0 02 00 00 4C 89 4C 24 40 45 8B E0 4C 8B FA 4C 8B E9",             STOLEN_HTTP_POST_BYTES, NULL, BindHttpClientPostTrampoline    },
};

#define HOOK_COUNT ((int)(sizeof(g_hookSpecs) / sizeof(g_hookSpecs[0])))

static struct HookRuntime g_hookRuntime[HOOK_COUNT];

static void InitializeHookSpecs(void)
{
    g_hookSpecs[0].detour = (void *)(uintptr_t)Hook_GameLogPrintf;
    g_hookSpecs[1].detour = (void *)(uintptr_t)Hook_GameLogRaw;
    g_hookSpecs[2].detour = (void *)(uintptr_t)Hook_ServerDataResponse;
    g_hookSpecs[3].detour = (void *)(uintptr_t)Hook_HttpClientPost;
}

struct PatternBytes
{
    uint8_t bytes[512];
    uint8_t mask[512];
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

static int ParsePattern(const char *pattern, struct PatternBytes *out)
{
    out->length = 0;
    if (!pattern)
        return 0;

    const char *cursor = pattern;
    while (*cursor)
    {
        while (*cursor == ' ' || *cursor == '\t' || *cursor == '\n' || *cursor == '\r')
            cursor++;
        if (!*cursor)
            break;
        if (out->length >= sizeof(out->bytes))
            return 0;
        if (cursor[0] == '?' && cursor[1] == '?')
        {
            out->mask[out->length] = 0;
            out->bytes[out->length] = 0;
            cursor += 2;
        }
        else
        {
            int high = HexNibble(cursor[0]);
            int low = (high >= 0) ? HexNibble(cursor[1]) : -1;
            if (high < 0 || low < 0)
                return 0;

            out->mask[out->length] = 0xFF;
            out->bytes[out->length] = (uint8_t)((high << 4) | low);
            cursor += 2;
        }
        out->length++;
    }

    return out->length > 0;
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

static uint8_t *FindUniquePattern(const char *pattern, int *matchCount)
{
    if (matchCount)
        *matchCount = 0;
    if (!g_imageBase || !g_imageSize)
        return NULL;

    struct PatternBytes parsed;
    if (!ParsePattern(pattern, &parsed))
        return NULL;

    uint8_t *end = g_imageBase + g_imageSize;
    uint8_t *found = NULL;
    int count = 0;
    for (uint8_t *cursor = g_imageBase; cursor + parsed.length <= end; ++cursor)
    {
        if (!PatternMatches(cursor, &parsed))
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

static void *BuildTrampoline(const struct HookSpec *spec, uint8_t *target)
{
    size_t length = spec->stolenBytes;
    size_t size = length + HOOK_ENTRY_PATCH_BYTES;

    uint8_t *trampoline = (uint8_t *)VirtualAlloc(NULL, size, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!trampoline)
    {
        DWORD error = GetLastError();
        trampoline = (uint8_t *)VirtualAlloc(NULL, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!trampoline)
        {
            LogError("[hook] %s: cannot allocate a trampoline (err=%lu)", spec->name, error);
            return NULL;
        }
        DWORD oldProtection = 0;
        if (!VirtualProtect(trampoline, size, PAGE_EXECUTE_READ, &oldProtection))
        {
            LogError("[hook] %s: cannot make the trampoline executable (err=%lu)", spec->name, GetLastError());
            VirtualFree(trampoline, 0, MEM_RELEASE);
            return NULL;
        }
        LogInfo("[hook] %s: rwx allocation denied (%lu), using rw plus promote", spec->name, error);
    }

    memcpy(trampoline, target, length);

    /* jump back to the original function, the same 14 byte absolute jump the injector uses for the entry point */
    trampoline[length + 0] = 0xFF;
    trampoline[length + 1] = 0x25;
    trampoline[length + 2] = 0;
    trampoline[length + 3] = 0;
    trampoline[length + 4] = 0;
    trampoline[length + 5] = 0;
    uint64_t returnAddress = (uint64_t)(uintptr_t)(target + length);
    memcpy(trampoline + length + 6, &returnAddress, sizeof(returnAddress));

    FlushInstructionCache(GetCurrentProcess(), trampoline, size);
    return trampoline;
}

static void ReplaceSpaces(char *text)
{
    for (char *cursor = text; *cursor; cursor++)
    {
        if (*cursor == ' ')
            *cursor = '_';
    }
}

static void PublishStateEvent(void)
{
    char version[MAX_VERSION_LENGTH];
    char protocol[MAX_VERSION_LENGTH];
    char platform[MAX_VERSION_LENGTH];
    char server[MAX_SERVER_LENGTH];
    int port = 0;

    LockState();
    CopyText(version, sizeof(version), g_state.clientVersion);
    CopyText(protocol, sizeof(protocol), g_state.clientProtocol);
    CopyText(platform, sizeof(platform), g_state.clientPlatform);
    CopyText(server, sizeof(server), g_state.realServer);
    port = g_state.realPort;
    UnlockState();

    ReplaceSpaces(version);
    ReplaceSpaces(protocol);
    ReplaceSpaces(platform);
    ReplaceSpaces(server);

    char text[MAX_EVENT_TEXT];
    snprintf(text, sizeof(text),
             "client_version=%s client_protocol=%s client_platform=%s "
             "real_server=%s real_port=%d",
             version, protocol, platform, server, port);
    QueueEvent("state", text);
}

static long long FASTCALL Hook_GameLogPrintf(const char *format, ...)
{
    char line[MAX_LOG_LINE];
    va_list args;
    va_start(args, format);
    int written = vsnprintf(line, sizeof(line), format, args);
    va_end(args);
    if (written < 0)
        return 0;
    if ((size_t)written >= sizeof(line))
        line[sizeof(line) - 1] = 0;

    LockState();
    int streaming = g_state.streamGameLogs;
    UnlockState();
    if (streaming)
        LogEmit(line, 0);
    else if (CurrentLogLevel() >= LOG_LEVEL_TRACE)
        OutputDebugStringA(line);

    if (g_trampolineLogPrintf)
        return g_trampolineLogPrintf("%s", line);

    return 0;
}

static long long FASTCALL Hook_GameLogRaw(const char *format, ...)
{
    char line[MAX_LOG_LINE];
    va_list args;
    va_start(args, format);
    int written = vsnprintf(line, sizeof(line), format, args);
    va_end(args);
    if (written < 0)
        return 0;
    if ((size_t)written >= sizeof(line))
        line[sizeof(line) - 1] = 0;

    LockState();
    int streaming = g_state.streamGameLogs;
    UnlockState();
    if (streaming)
        LogEmit(line, 0);
    else if (CurrentLogLevel() >= LOG_LEVEL_TRACE)
        OutputDebugStringA(line);

    if (g_trampolineLogRaw)
        return g_trampolineLogRaw("%s", line);

    return 0;
}

static void HandleServerDataBody(struct SSO *body)
{
    const char *source = SSOData(body);
    if (!source || body->size == 0)
        return;

    char proxyHost[MAX_HOST_LENGTH];
    int proxyPort = 0;
    LockState();
    CopyText(proxyHost, sizeof(proxyHost), g_state.proxyHost);
    proxyPort = g_state.proxyPort;
    UnlockState();

    char realServer[MAX_SERVER_LENGTH];
    int realPort = 0;
    int captured = 0;

    struct TextBuffer output;
    memset(&output, 0, sizeof(output));

    size_t offset = 0;
    size_t size = body->size;
    while (offset < size)
    {
        size_t start = offset;
        while (offset < size && source[offset] != '\n')
            offset++;
        size_t lineLength = offset - start;
        int hasNewline = offset < size;
        if (hasNewline)
            offset++;

        if (lineLength >= 7 && memcmp(source + start, "server|", 7) == 0)
        {
            size_t valueLength = lineLength - 7;
            if (valueLength && source[start + 7 + valueLength - 1] == '\r')
                valueLength--;
            if (valueLength >= sizeof(realServer))
                valueLength = sizeof(realServer) - 1;
            memcpy(realServer, source + start + 7, valueLength);
            realServer[valueLength] = 0;
            captured = 1;
            BufferAppendFormat(&output, "server|%s\n", proxyHost);
        }
        else if (lineLength >= 5 && memcmp(source + start, "port|", 5) == 0)
        {
            char value[16];
            size_t valueLength = lineLength - 5;
            if (valueLength >= sizeof(value))
                valueLength = sizeof(value) - 1;
            memcpy(value, source + start + 5, valueLength);
            value[valueLength] = 0;
            realPort = atoi(value);
            captured = 1;
            BufferAppendFormat(&output, "port|%d\n", proxyPort);
        }
        else
        {
            BufferAppend(&output, source + start, lineLength);
            if (hasNewline)
                BufferAppend(&output, "\n", 1);
        }
    }

    if (captured)
    {
        LockState();
        CopyText(g_state.realServer, sizeof(g_state.realServer), realServer);
        g_state.realPort = realPort;
        UnlockState();
        PublishStateEvent();
    }

    if (output.data)
    {
        if (ApplySSO(body, output.data, output.length))
            LogTrace("[hook] server_data rewritten: server|%s port|%d (%zu bytes)", proxyHost, proxyPort,
                     output.length);
        else
            LogError("[hook] the server_data rewrite failed, the game will connect to the real server");
    }
    BufferFree(&output);
}

static void FASTCALL Hook_ServerDataResponse(void *closure, void *response)
{
    if (!response)
    {
        if (g_trampolineServerDataResponse)
            g_trampolineServerDataResponse(closure, response);
        return;
    }

    uint32_t status = *(uint32_t *)((uint8_t *)response + RESPONSE_STATUS_OFFSET);
    LogTrace("[hook] server_data response status=%u", status);

    if (status == 200)
    {
        struct SSO *body = (struct SSO *)((uint8_t *)response + RESPONSE_BODY_OFFSET);
        HandleServerDataBody(body);
    }
    else
    {
        LogInfo("[hook] server_data response status=%u, nothing to rewrite", status);
    }

    if (g_trampolineServerDataResponse)
        g_trampolineServerDataResponse(closure, response);
}

static void CaptureRequestParameters(void *dictionary)
{
    if (!dictionary)
        return;

    uint8_t *sentinel = *(uint8_t **)((uint8_t *)dictionary + DICT_SENTINEL_OFFSET);
    if (!sentinel)
        return;

    char version[MAX_VERSION_LENGTH];
    char protocol[MAX_VERSION_LENGTH];
    char platform[MAX_VERSION_LENGTH];
    version[0] = 0;
    protocol[0] = 0;
    platform[0] = 0;

    struct TextBuffer dump;
    memset(&dump, 0, sizeof(dump));

    uint8_t *node = *(uint8_t **)sentinel;
    while (node && node != sentinel)
    {
        struct SSO *key = (struct SSO *)(node + DICT_NODE_KEY_OFFSET);
        struct SSO *value = (struct SSO *)(node + DICT_NODE_VALUE_OFFSET);
        if (key && key->size)
        {
            const char *keyText = SSOData(key);
            if (keyText)
            {
                size_t keyLength = key->size;
                if (keyLength == 7 && memcmp(keyText, "version", 7) == 0)
                    CopyGameString(version, sizeof(version), value);
                else if (keyLength == 8 && memcmp(keyText, "protocol", 8) == 0)
                    CopyGameString(protocol, sizeof(protocol), value);
                else if (keyLength == 8 && memcmp(keyText, "platform", 8) == 0)
                    CopyGameString(platform, sizeof(platform), value);

                if (dump.length)
                    BufferAppendText(&dump, " ");
                BufferAppend(&dump, keyText, keyLength);
                BufferAppendText(&dump, "=");
                if (value && value->size)
                {
                    const char *valueText = SSOData(value);
                    if (valueText)
                        BufferAppend(&dump, valueText, value->size);
                }
            }
        }
        node = *(uint8_t **)node;
    }

    LockState();
    CopyText(g_state.clientVersion, sizeof(g_state.clientVersion), version);
    CopyText(g_state.clientProtocol, sizeof(g_state.clientProtocol), protocol);
    CopyText(g_state.clientPlatform, sizeof(g_state.clientPlatform), platform);
    UnlockState();

    LogInfo("[hook] request parameters: %s", dump.data ? dump.data : "(none)");
    BufferFree(&dump);

    PublishStateEvent();
}

static uintptr_t FASTCALL Hook_HttpClientPost(void *client, void *url, int isTls, void *dictionary, void *callback)
{
    struct SSO *urlString = (struct SSO *)url;
    const char *urlText = (urlString && urlString->size) ? SSOData(urlString) : NULL;
    if (urlText && strstr(urlText, "server_data.php"))
    {
        LogTrace("[hook] server_data request captured");
        CaptureRequestParameters(dictionary);
    }

    if (g_trampolineHttpClientPost)
        return g_trampolineHttpClientPost(client, url, isTls, dictionary, callback);

    LogError("[hook] http post called before the trampoline was ready");
    return 0;
}

static void BindLogPrintfTrampoline(void *address)
{
    g_trampolineLogPrintf = (FnGameLog)address;
}

static void BindLogRawTrampoline(void *address)
{
    g_trampolineLogRaw = (FnGameLog)address;
}

static void BindServerDataResponseTrampoline(void *address)
{
    g_trampolineServerDataResponse = (FnServerDataResponse)address;
}

static void BindHttpClientPostTrampoline(void *address)
{
    g_trampolineHttpClientPost = (FnHttpClientPost)address;
}

struct PipeReader
{
    char buffer[MAX_PIPE_LINE * 2];
    size_t length;
    size_t position;
};

static void WritePipeLine(HANDLE pipe, const char *text)
{
    if (!pipe || !text)
        return;
    char line[MAX_PIPE_LINE + 2];
    int written = snprintf(line, sizeof(line), "%s\n", text);
    if (written < 0)
        return;
    if ((size_t)written >= sizeof(line))
        written = (int)sizeof(line) - 1;
    DWORD writtenBytes = 0;
    if (!WriteFile(pipe, line, (DWORD)written, &writtenBytes, NULL))
        LogTrace("[pipe] the write failed, the client is gone");
}

static int PipeFill(HANDLE pipe, struct PipeReader *reader)
{
    DWORD available = 0;
    if (!PeekNamedPipe(pipe, NULL, 0, NULL, &available, NULL))
        return -1;
    if (available == 0)
        return 0;

    size_t space = sizeof(reader->buffer) - reader->length;
    if (space == 0)
        return 1;
    DWORD toRead = available < space ? available : (DWORD)space;
    DWORD readBytes = 0;
    if (!ReadFile(pipe, reader->buffer + reader->length, toRead, &readBytes, NULL) || readBytes == 0)
        return -1;
    reader->length += readBytes;
    return 1;
}

static int ReadPipeLine(HANDLE pipe, struct PipeReader *reader, char *out, size_t outSize)
{
    size_t position = 0;
    ULONGLONG deadline = GetTickCount64() + PIPE_POLL_INTERVAL_MS;
    for (;;)
    {
        while (reader->position < reader->length)
        {
            char c = reader->buffer[reader->position++];
            if (c == '\n')
            {
                out[position] = 0;
                return 1;
            }
            if (c == '\r' || c == '\0')
                continue;
            if (position + 1 < outSize)
                out[position++] = c;
        }
        reader->position = 0;
        reader->length = 0;

        int filled = PipeFill(pipe, reader);
        if (filled < 0)
            return -1;
        if (filled == 0)
        {
            if (GetTickCount64() >= deadline)
            {
                out[position] = 0;
                return 0;
            }
            Sleep(5);
        }
    }
}

static void AppendSanitized(struct TextBuffer *buffer, const char *text)
{
    for (const char *cursor = text; *cursor; cursor++)
        BufferAppend(buffer, (*cursor == ' ') ? "_" : cursor, 1);
}

static void AppendSingleLine(struct TextBuffer *buffer, const char *text)
{
    for (const char *cursor = text; *cursor; cursor++)
    {
        char c = *cursor;
        if (c == '\r' || c == '\n' || c == '\t')
            c = ' ';
        BufferAppend(buffer, &c, 1);
    }
}

static void BuildStatusLine(struct TextBuffer *buffer)
{
    BufferAppendText(buffer, "DATA");

    LockState();
    for (int i = 0; i < SETTING_COUNT; i++)
    {
        char value[MAX_LOG_MESSAGE];
        FormatSetting(&g_settings[i], value, sizeof(value));
        BufferAppendText(buffer, " ");
        BufferAppendText(buffer, g_settings[i].name);
        BufferAppendText(buffer, "=");
        AppendSanitized(buffer, value);
    }
    UnlockState();

    char scratch[64];
    snprintf(scratch, sizeof(scratch), " pid=%lu", (unsigned long)GetCurrentProcessId());
    BufferAppendText(buffer, scratch);

    snprintf(scratch, sizeof(scratch), " image_base=0x%llX", (unsigned long long)(uintptr_t)g_imageBase);
    BufferAppendText(buffer, scratch);

    snprintf(scratch, sizeof(scratch), " image_size=0x%llX", (unsigned long long)g_imageSize);
    BufferAppendText(buffer, scratch);

    snprintf(scratch, sizeof(scratch), " dll_base=0x%llX", (unsigned long long)(uintptr_t)g_selfBase);
    BufferAppendText(buffer, scratch);

    ULONGLONG uptime = 0;
    if (g_startTick && GetTickCount64() >= g_startTick)
        uptime = GetTickCount64() - g_startTick;
    snprintf(scratch, sizeof(scratch), " uptime_ms=%llu", (unsigned long long)uptime);
    BufferAppendText(buffer, scratch);

    for (int i = 0; i < HOOK_COUNT; i++)
    {
        const char *status = "missing";
        if (g_hookRuntime[i].status == HOOK_STATUS_PATCHED)
            status = "patched";
        else if (g_hookRuntime[i].status == HOOK_STATUS_READY)
            status = "ready";

        snprintf(scratch, sizeof(scratch), " hook_%s=%s", g_hookSpecs[i].key, status);
        BufferAppendText(buffer, scratch);

        snprintf(scratch, sizeof(scratch), " target_%s=0x%llX", g_hookSpecs[i].key,
                 (unsigned long long)(uintptr_t)g_hookRuntime[i].target);
        BufferAppendText(buffer, scratch);
    }
}

static void HexEncode(const uint8_t *data, size_t length, char *out, size_t outSize)
{
    static const char digits[] = "0123456789abcdef";
    size_t position = 0;
    for (size_t i = 0; i < length && position + 2 < outSize; i++)
    {
        out[position++] = digits[data[i] >> 4];
        out[position++] = digits[data[i] & 0xF];
    }
    if (position < outSize)
        out[position] = 0;
}

static int HandlePipeCommand(HANDLE pipe, const char *line)
{
    char command[64];
    char argument[MAX_PIPE_LINE];
    argument[0] = 0;

    const char *cursor = line;
    while (*cursor == ' ' || *cursor == '\t')
        cursor++;
    size_t index = 0;
    while (cursor[index] && cursor[index] != ' ' && cursor[index] != '\t' && index + 1 < sizeof(command))
    {
        command[index] = cursor[index];
        index++;
    }
    command[index] = 0;

    cursor += index;
    while (*cursor == ' ' || *cursor == '\t')
        cursor++;
    CopyText(argument, sizeof(argument), cursor);

    if (_stricmp(command, "PING") == 0)
    {
        WritePipeLine(pipe, "OK pong");
        return 0;
    }
    if (_stricmp(command, "QUIT") == 0)
    {
        WritePipeLine(pipe, "OK bye");
        return -1;
    }
    if (_stricmp(command, "STATUS") == 0)
    {
        struct TextBuffer status;
        memset(&status, 0, sizeof(status));
        BuildStatusLine(&status);
        WritePipeLine(pipe, status.data ? status.data : "DATA");
        BufferFree(&status);
        return 0;
    }
    if (_stricmp(command, "HANDSHAKE") == 0)
    {
        if (!InterlockedCompareExchange(&g_handshakeReady, 0, 0))
        {
            WritePipeLine(pipe, "ERR the hooks are not installed yet");
            return 0;
        }
        char hex[MAX_PIPE_LINE];
        HexEncode((const uint8_t *)&g_handshake, sizeof(g_handshake), hex, sizeof(hex));
        struct TextBuffer reply;
        memset(&reply, 0, sizeof(reply));
        BufferAppendText(&reply, "HANDSHAKE ");
        BufferAppendText(&reply, hex);
        WritePipeLine(pipe, reply.data ? reply.data : "HANDSHAKE");
        BufferFree(&reply);
        return 0;
    }
    if (_stricmp(command, "GET") == 0)
    {
        const struct SettingDescriptor *descriptor = FindSetting(argument);
        if (!descriptor)
        {
            WritePipeLine(pipe, "ERR unknown key");
            return 0;
        }
        char value[MAX_LOG_MESSAGE];
        LockState();
        FormatSetting(descriptor, value, sizeof(value));
        UnlockState();
        struct TextBuffer reply;
        memset(&reply, 0, sizeof(reply));
        BufferAppendText(&reply, "VALUE ");
        BufferAppendText(&reply, descriptor->name);
        BufferAppendText(&reply, " ");
        BufferAppendText(&reply, value);
        WritePipeLine(pipe, reply.data ? reply.data : "VALUE");
        BufferFree(&reply);
        return 0;
    }
    if (_stricmp(command, "SET") == 0)
    {
        char *separator = strchr(argument, ' ');
        if (!separator)
        {
            WritePipeLine(pipe, "ERR missing value");
            return 0;
        }
        *separator = 0;
        char *value = separator + 1;
        while (*value == ' ' || *value == '\t')
            value++;

        const struct SettingDescriptor *descriptor = FindSetting(argument);
        if (!descriptor)
        {
            WritePipeLine(pipe, "ERR unknown key");
            return 0;
        }
        char error[128];
        LockState();
        int applied = ApplySetting(descriptor, value, error, sizeof(error));
        if (applied && strcmp(descriptor->name, "log_level") == 0)
            ApplyLogLevelSetting();
        UnlockState();
        if (!applied)
        {
            WritePipeLine(pipe, error[0] ? error : "ERR invalid value");
            return 0;
        }
        WritePipeLine(pipe, "OK");
        return 0;
    }

    WritePipeLine(pipe, "ERR unknown command");
    return 0;
}

static void SendLogBacklog(HANDLE pipe)
{
    if (!g_logLockReady)
        return;

    char lines[LOG_BACKLOG_CAPACITY][LOG_BACKLOG_LINE];
    size_t count = 0;

    EnterCriticalSection(&g_logLock);
    count = g_logBacklogCount;
    size_t start = (g_logBacklogHead + LOG_BACKLOG_CAPACITY - count) % LOG_BACKLOG_CAPACITY;
    for (size_t i = 0; i < count; i++)
        CopyText(lines[i], LOG_BACKLOG_LINE, g_logBacklog[(start + i) % LOG_BACKLOG_CAPACITY]);
    LeaveCriticalSection(&g_logLock);

    for (size_t i = 0; i < count; i++)
    {
        struct TextBuffer message;
        memset(&message, 0, sizeof(message));
        BufferAppendText(&message, "EVENT log ");
        AppendSingleLine(&message, lines[i]);
        WritePipeLine(pipe, message.data ? message.data : "EVENT");
        BufferFree(&message);
    }
}

static DWORD WINAPI PipeClientThread(LPVOID raw)
{
    int slot = (int)(intptr_t)raw;
    if (slot < 0 || slot >= MAX_PIPE_CLIENTS)
        return 0;

    struct PipeClient *client = &g_clients[slot];
    HANDLE pipe = client->pipe;

    SendLogBacklog(pipe);
    PublishStateEvent();

    char line[MAX_PIPE_LINE];
    for (;;)
    {
        struct QueuedEvent event;
        while (PopEvent(client, &event))
        {
            struct TextBuffer message;
            memset(&message, 0, sizeof(message));
            BufferAppendText(&message, "EVENT ");
            BufferAppendText(&message, event.name);
            if (event.text[0])
            {
                BufferAppendText(&message, " ");
                AppendSingleLine(&message, event.text);
            }
            WritePipeLine(pipe, message.data ? message.data : "EVENT");
            BufferFree(&message);
        }

        int result = ReadPipeLine(pipe, &client->reader, line, sizeof(line));
        if (result < 0)
            break;
        if (result == 0)
            continue;
        if (HandlePipeCommand(pipe, line) < 0)
            break;
    }

    EnterCriticalSection(&g_clientLock);
    client->active = 0;
    client->pipe = NULL;
    LeaveCriticalSection(&g_clientLock);

    DisconnectNamedPipe(pipe);
    CloseHandle(pipe);
    return 0;
}

static int RegisterClient(HANDLE pipe)
{
    int slot = -1;
    EnterCriticalSection(&g_clientLock);
    for (int i = 0; i < MAX_PIPE_CLIENTS; i++)
    {
        if (!g_clients[i].active)
        {
            g_clients[i].active = 1;
            g_clients[i].pipe = pipe;
            g_clients[i].head = 0;
            g_clients[i].tail = 0;
            g_clients[i].count = 0;
            g_clients[i].reader.length = 0;
            g_clients[i].reader.position = 0;
            slot = i;
            break;
        }
    }
    LeaveCriticalSection(&g_clientLock);
    return slot;
}

static DWORD WINAPI PipeServerThread(LPVOID unused)
{
    (void)unused;

    SECURITY_ATTRIBUTES attributes;
    PSECURITY_DESCRIPTOR descriptor = NULL;
    ZeroMemory(&attributes, sizeof(attributes));
    attributes.nLength = sizeof(attributes);
    if (ConvertStringSecurityDescriptorToSecurityDescriptorA("D:(A;;GA;;;IU)(A;;GA;;;SY)(A;;GA;;;BA)S:(ML;;NW;;;ME)",
                                                             SDDL_REVISION_1, &descriptor, NULL))
    {
        attributes.lpSecurityDescriptor = descriptor;
    }
    else
    {
        LogError("[pipe] cannot create the security descriptor, using the process default");
    }

    LogInfo("[pipe] listening on %s", HOOK_PIPE_NAME);

    for (;;)
    {
        HANDLE pipe = CreateNamedPipeA(HOOK_PIPE_NAME, PIPE_ACCESS_DUPLEX,
                                       PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                                       PIPE_UNLIMITED_INSTANCES, 8192, 8192, 0, descriptor ? &attributes : NULL);
        if (pipe == INVALID_HANDLE_VALUE)
        {
            LogError("[pipe] cannot create the pipe (err=%lu)", GetLastError());
            Sleep(1000);
            continue;
        }

        BOOL connected = ConnectNamedPipe(pipe, NULL);
        if (!connected && GetLastError() == ERROR_PIPE_CONNECTED)
            connected = TRUE;

        if (!connected)
        {
            CloseHandle(pipe);
            continue;
        }

        int slot = RegisterClient(pipe);
        if (slot < 0)
        {
            LogInfo("[pipe] too many clients, refusing the connection");
            DisconnectNamedPipe(pipe);
            CloseHandle(pipe);
            continue;
        }

        HANDLE thread = CreateThread(NULL, 0, PipeClientThread, (LPVOID)(intptr_t)slot, 0, NULL);
        if (!thread)
        {
            LogError("[pipe] cannot start the client thread (err=%lu)", GetLastError());
            EnterCriticalSection(&g_clientLock);
            g_clients[slot].active = 0;
            g_clients[slot].pipe = NULL;
            LeaveCriticalSection(&g_clientLock);
            DisconnectNamedPipe(pipe);
            CloseHandle(pipe);
            continue;
        }
        CloseHandle(thread);
    }
}

static void StartPipeServer(void)
{
    HANDLE thread = CreateThread(NULL, 0, PipeServerThread, NULL, 0, NULL);
    if (thread)
        CloseHandle(thread);
    else
        LogError("[pipe] cannot start the pipe thread (err=%lu)", GetLastError());
}

static void PublishHandshake(void)
{
    memset(&g_handshake, 0, sizeof(g_handshake));
    g_handshake.magic = HOOK_PROTOCOL_MAGIC;
    g_handshake.version = HOOK_PROTOCOL_VERSION;
    g_handshake.processId = (uint64_t)GetCurrentProcessId();
    g_handshake.imageBase = (uint64_t)(uintptr_t)g_imageBase;
    g_handshake.imageSize = (uint64_t)g_imageSize;
    g_handshake.dllBase = (uint64_t)(uintptr_t)g_selfBase;

    uint32_t count = 0;
    for (int i = 0; i < HOOK_COUNT && count < HOOK_MAX_ENTRIES; i++)
    {
        if (g_hookRuntime[i].status == HOOK_STATUS_MISSING)
            continue;
        struct HookEntry *entry = &g_handshake.entries[count++];
        entry->target = (uint64_t)(uintptr_t)g_hookRuntime[i].target;
        entry->detour = (uint64_t)(uintptr_t)g_hookSpecs[i].detour;
        entry->stolenBytes = g_hookSpecs[i].stolenBytes;
        entry->entryPatchBytes = HOOK_ENTRY_PATCH_BYTES;
        CopyText(entry->name, sizeof(entry->name), g_hookSpecs[i].name);
    }
    g_handshake.entryCount = count;

    InterlockedExchange(&g_handshakeReady, 1);
    LogInfo("[hook] handshake published, %u hooks", count);
}

static void InstallHooks(void)
{
    for (int i = 0; i < HOOK_COUNT; i++)
    {
        const struct HookSpec *spec = &g_hookSpecs[i];

        if (spec->stolenBytes < HOOK_ENTRY_PATCH_BYTES)
        {
            LogError("[hook] %s: needs at least %d relocated bytes", spec->name, HOOK_ENTRY_PATCH_BYTES);
            continue;
        }

        int matchCount = 0;
        uint8_t *target = FindUniquePattern(spec->signature, &matchCount);
        if (!target)
        {
            if (matchCount > 1)
                LogError("[hook] %s: the signature matches %d places, refusing to patch", spec->name, matchCount);
            else
                LogError("[hook] %s: signature not found", spec->name);
            continue;
        }

        void *trampoline = BuildTrampoline(spec, target);
        if (!trampoline)
            continue;

        g_hookRuntime[i].target = target;
        g_hookRuntime[i].trampoline = trampoline;
        g_hookRuntime[i].status = HOOK_STATUS_READY;
        spec->bindTrampoline(trampoline);

        LogInfo("[hook] %s: trampoline at %p for %p", spec->name, trampoline, target);
    }

    PublishHandshake();
}

static DWORD WINAPI PatchWatcherThread(LPVOID unused)
{
    (void)unused;
    for (int attempt = 0; attempt < 600; attempt++)
    {
        int patched = 0;
        for (int i = 0; i < HOOK_COUNT; i++)
        {
            if (g_hookRuntime[i].status != HOOK_STATUS_READY || !g_hookRuntime[i].target)
                continue;
            const uint8_t *code = g_hookRuntime[i].target;
            if (code[0] == 0xFF && code[1] == 0x25)
            {
                uint64_t destination = 0;
                memcpy(&destination, code + 6, sizeof(destination));
                if (destination == (uint64_t)(uintptr_t)g_hookSpecs[i].detour)
                {
                    g_hookRuntime[i].status = HOOK_STATUS_PATCHED;
                    patched = 1;
                }
            }
        }
        if (patched)
        {
            LogInfo("[hook] the entry points are patched, the hook is live");
            if (g_trampolineLogPrintf)
                g_trampolineLogPrintf("%s", "[gtools] hook injected successfully");
            return 0;
        }
        Sleep(50);
    }
    LogInfo("[hook] the entry points were not patched in time");
    return 0;
}

static void TrimInPlace(char *text)
{
    if (!text)
        return;
    size_t length = strlen(text);
    while (length > 0 && (text[length - 1] == ' ' || text[length - 1] == '\t' || text[length - 1] == '\r' ||
                          text[length - 1] == '\n'))
    {
        text[--length] = 0;
    }
    size_t start = 0;
    while (text[start] == ' ' || text[start] == '\t' || text[start] == '\r' || text[start] == '\n')
        start++;
    if (start > 0)
    {
        size_t index = 0;
        while (text[start])
            text[index++] = text[start++];
        text[index] = 0;
    }
}

static void ApplyConfigEntry(const char *key, const char *value)
{
    const struct SettingDescriptor *descriptor = FindSetting(key);
    if (!descriptor)
    {
        LogInfo("[config] ignoring the unknown key '%s'", key);
        return;
    }
    if (!descriptor->writable)
    {
        LogInfo("[config] ignoring the read only key '%s'", key);
        return;
    }

    char error[128];
    LockState();
    int applied = ApplySetting(descriptor, value, error, sizeof(error));
    if (applied && strcmp(descriptor->name, "log_level") == 0)
        ApplyLogLevelSetting();
    UnlockState();
    if (!applied)
        LogError("[config] %s: %s", key, error);
}

static void SetDefaultState(void)
{
    CopyText(g_state.proxyHost, sizeof(g_state.proxyHost), "127.0.0.1");
    g_state.proxyPort = 16999;
    g_state.startDelayMs = 2500;
    g_state.logLevel = LOG_LEVEL_INFO;
    g_state.allowAnyModule = 0;
    g_state.streamGameLogs = 0;
}

static void LoadConfig(void)
{
    SetDefaultState();

    char directory[MAX_PATH];
    memset(directory, 0, sizeof(directory));
    GetModuleFileNameA(g_selfModule, directory, MAX_PATH);
    char *separator = strrchr(directory, '\\');
    if (separator)
        *separator = 0;

    char configPath[MAX_PATH];
    snprintf(configPath, sizeof(configPath), "%s\\gtdump_hook.cfg", directory);

    FILE *file = fopen(configPath, "r");
    if (file)
    {
        char line[MAX_CONFIG_LINE];
        while (fgets(line, sizeof(line), file))
        {
            TrimInPlace(line);
            if (line[0] == 0 || line[0] == '#' || line[0] == ';')
                continue;
            char *separator = strchr(line, '=');
            if (!separator)
                continue;
            *separator = 0;
            char *key = line;
            char *value = separator + 1;
            TrimInPlace(key);
            TrimInPlace(value);
            ApplyConfigEntry(key, value);
        }
        fclose(file);
    }

    char environment[MAX_PATH];
    if (GetEnvironmentVariableA("GTD_IP", environment, sizeof(environment)) && environment[0])
        CopyText(g_state.proxyHost, sizeof(g_state.proxyHost), environment);
    if (GetEnvironmentVariableA("GTD_PORT", environment, sizeof(environment)) && environment[0])
        g_state.proxyPort = atoi(environment);
    if (GetEnvironmentVariableA("GTD_VERBOSE", environment, sizeof(environment)) && environment[0])
        g_state.logLevel = atoi(environment);

    ApplyLogLevelSetting();
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

static LONG NTAPI FirstChanceLogger(PEXCEPTION_POINTERS exceptionPointers)
{
    if (!exceptionPointers || !exceptionPointers->ExceptionRecord || !exceptionPointers->ContextRecord)
        return EXCEPTION_CONTINUE_SEARCH;
    DWORD code = (DWORD)exceptionPointers->ExceptionRecord->ExceptionCode;
    if (code != 0xC0000005 && code != 0xC000001D && code != 0xC0000096 && code != 0xC00000FD)
        return EXCEPTION_CONTINUE_SEARCH;

    if (!g_imageBase)
        return EXCEPTION_CONTINUE_SEARCH;
    uintptr_t rip = (uintptr_t)exceptionPointers->ContextRecord->Rip;
    uintptr_t image = (uintptr_t)g_imageBase;
    int inGame = (rip >= image && rip < image + g_imageSize);
    int inSelf = g_selfBase && rip >= (uintptr_t)g_selfBase && rip < (uintptr_t)g_selfBase + g_selfSize;
    if (!inGame && !inSelf)
        return EXCEPTION_CONTINUE_SEARCH;

    static uintptr_t seen[256];
    static int seenCount = 0;
    static LONG lock = 0;
    while (InterlockedExchange(&lock, 1))
        Sleep(0);
    int duplicate = 0;
    for (int i = 0; i < seenCount; i++)
    {
        if (seen[i] == rip)
        {
            duplicate = 1;
            break;
        }
    }
    if (!duplicate && seenCount < 256)
        seen[seenCount++] = rip;
    InterlockedExchange(&lock, 0);
    if (duplicate)
        return EXCEPTION_CONTINUE_SEARCH;

    uintptr_t fault = 0;
    if (code == 0xC0000005 && exceptionPointers->ExceptionRecord->NumberParameters >= 2)
        fault = (uintptr_t)exceptionPointers->ExceptionRecord->ExceptionInformation[1];

    LogInfo("[veh] code=0x%08lX rip=0x%llX fault=0x%llX tid=%lu", code, (unsigned long long)rip,
            (unsigned long long)fault, (unsigned long)GetCurrentThreadId());

    return EXCEPTION_CONTINUE_SEARCH;
}

static LONG WINAPI CrashFilter(EXCEPTION_POINTERS *exceptionPointers)
{
    if (!exceptionPointers || !exceptionPointers->ExceptionRecord || !exceptionPointers->ContextRecord || !g_imageBase)
        return EXCEPTION_EXECUTE_HANDLER;

    EXCEPTION_RECORD *record = exceptionPointers->ExceptionRecord;
    CONTEXT *context = exceptionPointers->ContextRecord;
    uintptr_t rip = (uintptr_t)context->Rip;
    uintptr_t image = (uintptr_t)g_imageBase;

    LogError("[crash] code=0x%08lX address=%p rip=0x%llX (module rva 0x%llX) tid=%lu",
             (unsigned long)record->ExceptionCode, (void *)record->ExceptionAddress, (unsigned long long)rip,
             (unsigned long long)(rip - image), (unsigned long)GetCurrentThreadId());

#if defined(_MSC_VER) && !defined(__clang__)
    __try
    {
        const uint8_t *code = (const uint8_t *)rip;
        LogError("[crash] code at rip: %02X %02X %02X %02X %02X %02X %02X %02X", code[0], code[1], code[2], code[3],
                 code[4], code[5], code[6], code[7]);
    }
    __except (EXCEPTION_EXECUTE_HANDLER)
    {
        LogError("[crash] the code at rip is unreadable");
    }
#endif

    return EXCEPTION_EXECUTE_HANDLER;
}

static DWORD WINAPI Worker(LPVOID unused)
{
    (void)unused;

    InitializeHookSpecs();

    InitializeCriticalSection(&g_stateLock);
    g_stateLockReady = 1;
    InitializeCriticalSection(&g_clientLock);
    g_clientLockReady = 1;
    InitializeCriticalSection(&g_logLock);
    g_logLockReady = 1;

    LoadConfig();

    HMODULE self = NULL;
    if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           (LPCWSTR)&Worker, &self))
    {
        g_selfBase = (uint8_t *)self;
        g_selfSize = ImageSizeOf(g_selfBase);
    }

    g_startTick = GetTickCount64();

    AddVectoredExceptionHandler(0, FirstChanceLogger);
    SetUnhandledExceptionFilter(CrashFilter);

    g_imageBase = (uint8_t *)GetModuleHandleA("Growtopia.exe");
    if (!g_imageBase && g_state.allowAnyModule)
        g_imageBase = (uint8_t *)GetModuleHandleA(NULL);
    g_imageSize = ImageSizeOf(g_imageBase);

    LogInfo("[hook] loaded in pid %lu, image %p (size 0x%X), waiting %d ms", (unsigned long)GetCurrentProcessId(),
            g_imageBase, (unsigned)g_imageSize, g_state.startDelayMs);

    StartPipeServer();

    if (g_state.startDelayMs > 0)
        Sleep((DWORD)g_state.startDelayMs);

    InstallHooks();

    HANDLE watcher = CreateThread(NULL, 0, PatchWatcherThread, NULL, 0, NULL);
    if (watcher)
        CloseHandle(watcher);
    return 0;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH)
    {
        g_selfModule = hModule;
        DisableThreadLibraryCalls(hModule);
        CreateThread(NULL, 0, Worker, NULL, 0, NULL);
    }
    else if (reason == DLL_PROCESS_DETACH)
    {
        OutputDebugStringA("[hook] the dll is being unloaded\n");
    }
    return TRUE;
}
