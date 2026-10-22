// BUILD_FLAGS[gcc, clang]: -O2 -shared -fPIC
// BUILD_FLAGS[msvc]: /O2 /LD /TC /Gy
// BUILD_FLAGS[gcc(mingw)]: -O2 -shared -fPIC -mwindows
//
// Thin in-process shim. It runs no threads beyond its one boot worker, no
// pipe server, no scanner and no exception hooks: it publishes runtime facts
// (image base, detour addresses) into a shared section, forwards game log
// lines into the same section and performs the minimal in-place rewrite of
// the server_data response. Everything else (the pipe server, settings,
// signature scanning, trampoline building, patching, patch watching) happens
// in external processes (agent.c, injector.c).

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

#pragma comment(lib, "user32.lib")

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

#define GAME_STRING_INLINE_CAPACITY 16

#define REWRITE_SCRATCH_MAX  4096
#define SECTION_OPEN_RETRIES 100 /* 10 s, 100 ms steps */

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

/* ---------- read only game types ---------- */

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

/* ---------- shared section ---------- */

static struct HookShared *g_shm = NULL;
static HANDLE g_shmMapping = NULL;

static int AcquireSettings(void)
{
    if (!g_shm)
        return 0;
    while (InterlockedCompareExchange(&g_shm->settingsLock, 1, 0) != 0)
        Sleep(0);
    return 1;
}

static void ReleaseSettings(void)
{
    if (g_shm)
        InterlockedExchange(&g_shm->settingsLock, 0);
}

/* hand one log line to the agent through the shared section */
static void PublishLine(int level, const char *format, ...)
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

    if (!g_shm)
    {
        OutputDebugStringA(text);
        return;
    }

    LONG ticket = InterlockedIncrement(&g_shm->logTicket) - 1;
    struct HookSlot *slot = &g_shm->log[(size_t)ticket % HOOK_LOG_SLOTS];
    if (InterlockedCompareExchange(&slot->state, HOOK_SLOT_CLAIMED, HOOK_SLOT_EMPTY) != HOOK_SLOT_EMPTY)
        return; /* the ring is contended, drop this line */

    size_t length = strlen(text);
    if (length >= HOOK_LOG_LINE)
        length = HOOK_LOG_LINE - 1;
    memcpy(slot->text, text, length);
    slot->text[length] = 0;
    slot->sequence = ticket;
    slot->threadId = GetCurrentThreadId();
    slot->level = level;

    InterlockedExchange(&slot->state, HOOK_SLOT_READY);
}

static struct HookShared *MapSharedSection(int retries)
{
    for (int attempt = 0; attempt < retries; attempt++)
    {
        HANDLE mapping = OpenFileMappingA(FILE_MAP_ALL_ACCESS, FALSE, HOOK_SECTION_NAME);
        if (!mapping)
        {
            Sleep(100);
            continue;
        }

        void *view = MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, 0);
        if (!view)
        {
            CloseHandle(mapping);
            Sleep(100);
            continue;
        }

        struct HookShared *memory = (struct HookShared *)view;
        if (memory->magic != HOOK_PROTOCOL_MAGIC || memory->version != HOOK_PROTOCOL_VERSION)
        {
            UnmapViewOfFile(view);
            CloseHandle(mapping);
            OutputDebugStringA("[hook] the shared section has a foreign version\n");
            return NULL;
        }

        /* keep the mapping handle open: it keeps the section alive even if
           the agent process dies before the exit of the game */
        g_shmMapping = mapping;
        return memory;
    }

    return NULL;
}

/* ---------- process bookkeeping ---------- */

static HANDLE g_processMutex = NULL;

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

/* ---------- detours ---------- */

typedef long long(FASTCALL *FnGameLog)(const char *format, ...);
typedef void(FASTCALL *FnServerDataResponse)(void *closure, void *response);
typedef uintptr_t(FASTCALL *FnHttpClientPost)(void *client, void *url, int isTls, void *dictionary, void *callback);

static void *EntryTrampoline(int index)
{
    if (!g_shm)
        return NULL;
    return (void *)(uintptr_t)g_shm->entries[index].trampoline;
}

static void EmitGameLog(const char *line)
{
    if (!g_shm)
    {
        OutputDebugStringA(line);
        return;
    }
    if (g_shm->settings.streamGameLogs)
        PublishLine(HOOK_LOG_GAME, "%s", line);
    else if (g_shm->settings.logLevel >= HOOK_LOG_TRACE)
        OutputDebugStringA(line);
}

static long long GameLogForward(int index, char *line)
{
    FnGameLog trampoline = (FnGameLog)EntryTrampoline(index);
    if (!trampoline)
        return 0;
    return trampoline("%s", line);
}

static long long FASTCALL Hook_GameLogPrintf(const char *format, ...)
{
    char line[HOOK_LOG_LINE];
    va_list args;
    va_start(args, format);
    int written = vsnprintf(line, sizeof(line), format, args);
    va_end(args);
    if (written < 0)
        return 0;
    if ((size_t)written >= sizeof(line))
        line[sizeof(line) - 1] = 0;

    EmitGameLog(line);

    return GameLogForward(HOOK_INDEX_GAME_LOG_PRINTF, line);
}

static long long FASTCALL Hook_GameLogRaw(const char *format, ...)
{
    char line[HOOK_LOG_LINE];
    va_list args;
    va_start(args, format);
    int written = vsnprintf(line, sizeof(line), format, args);
    va_end(args);
    if (written < 0)
        return 0;
    if ((size_t)written >= sizeof(line))
        line[sizeof(line) - 1] = 0;

    EmitGameLog(line);

    return GameLogForward(HOOK_INDEX_GAME_LOG_RAW, line);
}

/* ---------- server data rewrite (in place, never allocates) ---------- */

struct Rewrite
{
    char *data;
    size_t length;
    size_t capacity;
};

static void AppendRewrite(struct Rewrite *buffer, const char *text, size_t length)
{
    if (!text || length == 0)
        return;
    if (buffer->length + length > buffer->capacity)
        return;
    memcpy(buffer->data + buffer->length, text, length);
    buffer->length += length;
}

static void AppendRewriteText(struct Rewrite *buffer, const char *text)
{
    if (text)
        AppendRewrite(buffer, text, strlen(text));
}

static void AppendRewriteFormat(struct Rewrite *buffer, const char *format, ...)
{
    char scratch[256];
    va_list args;
    va_start(args, format);
    int written = vsnprintf(scratch, sizeof(scratch), format, args);
    va_end(args);
    if (written < 0)
        return;
    if ((size_t)written >= sizeof(scratch))
        written = (int)sizeof(scratch) - 1;
    AppendRewrite(buffer, scratch, (size_t)written);
}

static void SnapshotProxy(char *host, size_t hostSize, int *port)
{
    host[0] = 0;
    *port = 0;
    if (!AcquireSettings())
        return;
    CopyText(host, hostSize, g_shm->settings.proxyHost);
    *port = g_shm->settings.proxyPort;
    ReleaseSettings();
}

/* the rewrite only writes inside the existing buffer, if the new body does
   not fit the old capacity the rewrite is refused and the game keeps the
   original response */
static int ApplyRewrite(struct SSO *target, const char *data, size_t length)
{
    if (!target || !data)
        return 0;

    if (target->capacity > 0xF)
    {
        if (length + 1 > target->capacity)
            return 0;
        memcpy(target->buffer, data, length + 1);
    }
    else
    {
        if (length + 1 > GAME_STRING_INLINE_CAPACITY)
            return 0;
        memcpy((char *)target, data, length + 1);
    }
    target->size = length;
    return 1;
}

static void FASTCALL Hook_ServerDataResponse(void *closure, void *response)
{
    void *trampoline = EntryTrampoline(HOOK_INDEX_RESPONSE);

    if (!response)
    {
        PublishLine(HOOK_LOG_INFO, "[hook] server_data response is null");
    }
    else
    {
        uint32_t status = *(uint32_t *)((uint8_t *)response + RESPONSE_STATUS_OFFSET);
        if (status != 200)
        {
            PublishLine(HOOK_LOG_INFO, "[hook] server_data response status=%u, nothing to rewrite", status);
        }
        else
        {
            struct SSO *body = (struct SSO *)((uint8_t *)response + RESPONSE_BODY_OFFSET);
            const char *source = SSOData(body);
            if (!source || body->size == 0)
            {
                PublishLine(HOOK_LOG_TRACE, "[hook] server_data response status=%u", status);
            }
            else if (body->size > REWRITE_SCRATCH_MAX)
            {
                PublishLine(HOOK_LOG_ERROR, "[hook] server_data body is too large to rewrite (%zu bytes)",
                            (size_t)body->size);
            }
            else
            {
                char proxyHost[HOOK_TEXT_FIELD_MAX];
                int proxyPort = 0;
                SnapshotProxy(proxyHost, sizeof(proxyHost), &proxyPort);

                char realServer[HOOK_FIELD_MAX];
                int realPort = 0;
                int captured = 0;

                char scratch[REWRITE_SCRATCH_MAX];
                struct Rewrite output;
                output.data = scratch;
                output.length = 0;
                output.capacity = sizeof(scratch);

                size_t offset = 0;
                size_t size = (size_t)body->size;
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
                        AppendRewriteFormat(&output, "server|%s\n", proxyHost);
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
                        AppendRewriteFormat(&output, "port|%d\n", proxyPort);
                    }
                    else
                    {
                        AppendRewrite(&output, source + start, lineLength);
                        if (hasNewline)
                            AppendRewriteText(&output, "\n");
                    }
                }

                if (captured && AcquireSettings())
                {
                    CopyText(g_shm->settings.realServer, sizeof(g_shm->settings.realServer), realServer);
                    g_shm->settings.realPort = realPort;
                    ReleaseSettings();
                }

                if (output.length)
                {
                    if (ApplyRewrite(body, output.data, output.length))
                        PublishLine(HOOK_LOG_TRACE,
                                    "[hook] server_data rewritten: server|%s port|%d (%zu bytes)", proxyHost,
                                    proxyPort, output.length);
                    else
                        PublishLine(HOOK_LOG_ERROR,
                                    "[hook] the server_data rewrite failed, the game will connect to the real server");
                }
            }
        }
    }

    if (trampoline)
        ((FnServerDataResponse)trampoline)(closure, response);
}

/* ---------- http client post (read only capture) ---------- */

static void CaptureRequestParameters(void *dictionary)
{
    if (!dictionary)
        return;

    uint8_t *sentinel = *(uint8_t **)((uint8_t *)dictionary + DICT_SENTINEL_OFFSET);
    if (!sentinel)
        return;

    char version[HOOK_FIELD_MAX];
    char protocol[HOOK_FIELD_MAX];
    char platform[HOOK_FIELD_MAX];
    version[0] = 0;
    protocol[0] = 0;
    platform[0] = 0;

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
                if (key->size == 7 && memcmp(keyText, "version", 7) == 0)
                    CopyGameString(version, sizeof(version), value);
                else if (key->size == 8 && memcmp(keyText, "protocol", 8) == 0)
                    CopyGameString(protocol, sizeof(protocol), value);
                else if (key->size == 8 && memcmp(keyText, "platform", 8) == 0)
                    CopyGameString(platform, sizeof(platform), value);
            }
        }
        node = *(uint8_t **)node;
    }

    if (AcquireSettings())
    {
        CopyText(g_shm->settings.clientVersion, sizeof(g_shm->settings.clientVersion), version);
        CopyText(g_shm->settings.clientProtocol, sizeof(g_shm->settings.clientProtocol), protocol);
        CopyText(g_shm->settings.clientPlatform, sizeof(g_shm->settings.clientPlatform), platform);
        ReleaseSettings();
    }

    PublishLine(HOOK_LOG_INFO, "[hook] request parameters: version=%s protocol=%s platform=%s", version, protocol,
                platform);
}

static uintptr_t FASTCALL Hook_HttpClientPost(void *client, void *url, int isTls, void *dictionary, void *callback)
{
    struct SSO *urlString = (struct SSO *)url;
    const char *urlText = (urlString && urlString->size) ? SSOData(urlString) : NULL;
    if (urlText && strstr(urlText, "server_data.php"))
    {
        PublishLine(HOOK_LOG_TRACE, "[hook] server_data request captured");
        CaptureRequestParameters(dictionary);
    }

    FnHttpClientPost trampoline = (FnHttpClientPost)EntryTrampoline(HOOK_INDEX_HTTP_POST);
    if (!trampoline)
        return 0;
    return trampoline(client, url, isTls, dictionary, callback);
}

/* ---------- boot ---------- */

static const void *const g_detours[HOOK_INDEX_COUNT] = {
    (const void *)&Hook_GameLogPrintf,
    (const void *)&Hook_GameLogRaw,
    (const void *)&Hook_ServerDataResponse,
    (const void *)&Hook_HttpClientPost,
};

static DWORD WINAPI ShimWorker(LPVOID unused)
{
    (void)unused;

    AcquireProcessHookMutex();

    g_shm = MapSharedSection(SECTION_OPEN_RETRIES);
    if (!g_shm)
    {
        OutputDebugStringA("[hook] the shared section is missing, the shim stays idle\n");
        return 0;
    }

    /* honor the configured start delay, the agent serves the settings while
       the shim waits, matching the timing of the previous design */
    int delay = g_shm->settings.startDelayMs;
    if (delay < 0)
        delay = 0;
    if (delay > 0)
        Sleep((DWORD)delay);

    HMODULE self = NULL;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       (LPCWSTR)&ShimWorker, &self);

    uint8_t *image = (uint8_t *)GetModuleHandleA("Growtopia.exe");
    if (!image && g_shm->settings.allowAnyModule)
        image = (uint8_t *)GetModuleHandleA(NULL);
    size_t imageSize = ImageSizeOf(image);

    g_shm->processId = (uint64_t)GetCurrentProcessId();
    g_shm->dllBase = (uint64_t)(uintptr_t)self;
    g_shm->imageBase = (uint64_t)(uintptr_t)image;
    g_shm->imageSize = (uint64_t)imageSize;
    g_shm->bootTick = (uint64_t)GetTickCount64();

    for (int i = 0; i < HOOK_INDEX_COUNT; i++)
        g_shm->entries[i].detour = (uint64_t)(uintptr_t)g_detours[i];
    InterlockedExchange(&g_shm->entryCount, HOOK_INDEX_COUNT);
    InterlockedExchange(&g_shm->ready, 1);

    PublishLine(HOOK_LOG_INFO, "[hook] shim ready: pid %lu image %p (size 0x%zX) dll %p",
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
        if (g_shmMapping)
            CloseHandle(g_shmMapping);
    }
    return TRUE;
}
