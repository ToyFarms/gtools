// BUILD_FLAGS[gcc, clang]: -O2 -shared -fPIC
// BUILD_FLAGS[msvc]: /O2 /LD /TC /Gy
// BUILD_FLAGS[gcc(mingw)]: -O2 -shared -fPIC -mwindows

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

#define REWRITE_SCRATCH_MAX 4096

#define STOLEN_LOG_BYTES       27
#define STOLEN_RESPONSE_BYTES  17
#define STOLEN_HTTP_POST_BYTES 21

#define PATTERN_MAX 512

#if defined(_MSC_VER)
#  define EXPORT __declspec(dllexport)
#else
#  define EXPORT __attribute__((visibility("default")))
#endif

EXPORT struct ShimShared g_self;

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

static void CopyShimDefaultSettings(struct HookSettings *settings)
{
    ZeroMemory(settings, sizeof(*settings));
    CopyText(settings->proxyHost, sizeof(settings->proxyHost), "127.0.0.1");
    settings->proxyPort = 16999;
    settings->startDelayMs = 2500;
    settings->logLevel = HOOK_LOG_INFO;
    settings->allowAnyModule = 0;
    settings->streamGameLogs = 0;
}

static int SelfSettingsSnapshot(struct HookSettings *out)
{
    for (int attempt = 0; attempt < 16; attempt++)
    {
        LONG revision = g_self.settingsRevision;
        if (revision == 0)
        {
            Sleep(0);
            continue;
        }
        *out = g_self.settings;
        if (g_self.settingsRevision == revision)
            return 1;
        Sleep(0);
    }
    return 0;
}

static struct HookSettings g_settingsCache;
static int g_settingsCacheValid = 0;

static struct HookSettings *SettingsSnapshot(void)
{
    if (SelfSettingsSnapshot(&g_settingsCache))
        g_settingsCacheValid = 1;

    if (!g_settingsCacheValid)
        CopyShimDefaultSettings(&g_settingsCache);

    return &g_settingsCache;
}

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

    LONG ticket = (LONG)(InterlockedIncrement(&g_self.logTicket) - 1);
    struct HookSlot *slot = &g_self.log[(size_t)ticket % HOOK_LOG_SLOTS];
    if (InterlockedCompareExchange(&slot->state, HOOK_SLOT_CLAIMED, HOOK_SLOT_EMPTY) != HOOK_SLOT_EMPTY)
        return;

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

struct HookSpec
{
    const char *name;
    const char *key;
    const char *signature;
    uint32_t stolenBytes;
};

static const struct HookSpec g_hookSpecs[HOOK_INDEX_COUNT] = {
    {"GameLog_Printf",       "game_log_printf",
     "48 89 4C 24 08 48 89 54 24 10 4C 89 44 24 18 4C 89 4C 24 20 53 57 B8 88 10 00 00 E8 ?? ?? ?? ?? 48 2B E0 48 8B "
     "05 ?? ?? ?? ?? 48 33 C4 48 89 84 24 70 10 00 00 48 8B D9 33 D2 48 8D 4C 24 70 41", STOLEN_LOG_BYTES      },
    {"GameLog_Raw",          "game_log_raw",
     "48 89 4C 24 08 48 89 54 24 10 4C 89 44 24 18 4C 89 4C 24 20 53 57 B8 68 28 00 00 E8 ?? ?? ?? ?? 48 2B E0 48 8B "
     "05 ?? ?? ?? ?? 48 33 C4 48 89 84 24 50 28 00 00 48 8B D9 33 D2 48 8D 4C 24 40 41", STOLEN_LOG_BYTES      },
    {"OnServerDataResponse", "server_data_response",
     "40 55 56 48 83 EC 28 81 BA ?? ?? ?? ?? C8 00 00 00 48 8B EA 48 8B 41 08 48 8B F1 75 1D C7 80 ?? ?? ?? ?? 00 "
     "00 00 00",                                                                         STOLEN_RESPONSE_BYTES },
    {"HttpClient_Post",      "http_client_post",
     "40 55 53 56 57 41 54 41 55 41 56 41 57 48 8D AC 24 48 FD FF FF 48 81 EC B8 03 00 00 48 8B 05 ?? ?? ?? ?? 48 "
     "33 C4 48 89 85 A0 02 00 00 4C 89 4C 24 40 45 8B E0 4C 8B FA 4C 8B E9",             STOLEN_HTTP_POST_BYTES},
};

struct PatternBytes
{
    uint8_t bytes[PATTERN_MAX];
    uint8_t mask[PATTERN_MAX];
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

static uint8_t *FindUniquePattern(const char *pattern, uint8_t *imageBase, size_t imageSize, int *matchCount)
{
    if (matchCount)
        *matchCount = 0;
    if (!imageBase || !imageSize)
        return NULL;

    struct PatternBytes parsed;
    if (!ParsePattern(pattern, &parsed))
        return NULL;

    uint8_t *end = imageBase + imageSize;
    uint8_t *found = NULL;
    int count = 0;
    for (uint8_t *cursor = imageBase; cursor + parsed.length <= end; ++cursor)
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

static void *BuildTrampoline(const struct HookSpec *spec, uint8_t *target)
{
    size_t length = spec->stolenBytes;
    size_t size = length + HOOK_ENTRY_PATCH_BYTES;

    void *trampoline = VirtualAlloc(NULL, size, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!trampoline)
    {
        DWORD error = GetLastError();
        trampoline = VirtualAlloc(NULL, size, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!trampoline)
        {
            PublishLine(HOOK_LOG_ERROR, "[hook] %s: cannot allocate a trampoline (err=%lu)", spec->name, error);
            return NULL;
        }
        DWORD oldProtection = 0;
        if (!VirtualProtect(trampoline, size, PAGE_EXECUTE_READ, &oldProtection))
        {
            PublishLine(HOOK_LOG_ERROR, "[hook] %s: cannot make the trampoline executable (err=%lu)", spec->name,
                        GetLastError());
            VirtualFree(trampoline, 0, MEM_RELEASE);
            return NULL;
        }
        PublishLine(HOOK_LOG_INFO, "[hook] %s: rwx allocation denied (%lu), using rw plus promote", spec->name, error);
    }

    memcpy(trampoline, target, length);

    uint64_t returnAddress = (uint64_t)(uintptr_t)(target + length);
    write_abs_jump((unsigned char *)trampoline + length, returnAddress);

    FlushInstructionCache(GetCurrentProcess(), trampoline, size);
    return trampoline;
}

typedef long long(FASTCALL *FnGameLog)(const char *format, ...);
typedef void(FASTCALL *FnServerDataResponse)(void *closure, void *response);
typedef uintptr_t(FASTCALL *FnHttpClientPost)(void *client, void *url, int isTls, void *dictionary, void *callback);

static void *EntryTrampoline(int index)
{
    return (void *)(uintptr_t)g_self.entries[index].trampoline;
}

static void EmitGameLog(const char *line)
{
    PublishLine(HOOK_LOG_GAME, "%s", line);
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
    struct HookSettings *settings = SettingsSnapshot();
    CopyText(host, hostSize, settings->proxyHost);
    *port = settings->proxyPort;
}

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

                if (captured)
                {
                    CopyText(g_self.capture.realServer, sizeof(g_self.capture.realServer), realServer);
                    g_self.capture.realPort = realPort;
                }

                if (output.length)
                {
                    if (ApplyRewrite(body, output.data, output.length))
                        PublishLine(HOOK_LOG_TRACE, "[hook] server_data rewritten: server|%s port|%d (%zu bytes)",
                                    proxyHost, proxyPort, output.length);
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

    CopyText(g_self.capture.clientVersion, sizeof(g_self.capture.clientVersion), version);
    CopyText(g_self.capture.clientProtocol, sizeof(g_self.capture.clientProtocol), protocol);
    CopyText(g_self.capture.clientPlatform, sizeof(g_self.capture.clientPlatform), platform);

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

static const void *const g_detours[HOOK_INDEX_COUNT] = {
    (const void *)&Hook_GameLogPrintf,
    (const void *)&Hook_GameLogRaw,
    (const void *)&Hook_ServerDataResponse,
    (const void *)&Hook_HttpClientPost,
};

static void PublishEntries(uint64_t processId, uint64_t imageBase, uint64_t dllBase, size_t imageSize)
{
    for (int i = 0; i < HOOK_INDEX_COUNT; i++)
    {
        const struct HookSpec *spec = &g_hookSpecs[i];
        struct HookEntry *entry = &g_self.entries[i];

        CopyText(entry->name, sizeof(entry->name), spec->name);
        CopyText(entry->key, sizeof(entry->key), HOOK_IDENTITIES[i].key);
        entry->stolenBytes = spec->stolenBytes;
        entry->entryPatchBytes = HOOK_ENTRY_PATCH_BYTES;
        entry->detour = (uint64_t)(uintptr_t)g_detours[i];
        entry->target = 0;
        entry->trampoline = 0;
        entry->status = HOOK_STATUS_MISSING;
    }

    g_self.processId = processId;
    g_self.imageBase = imageBase;
    g_self.imageSize = imageSize;
    g_self.dllBase = dllBase;
    g_self.bootTick = (uint64_t)GetTickCount64();

    for (int i = 0; i < HOOK_INDEX_COUNT; i++)
    {
        const struct HookSpec *spec = &g_hookSpecs[i];
        struct HookEntry *entry = &g_self.entries[i];

        int matchCount = 0;
        uint8_t *target = FindUniquePattern(spec->signature, (uint8_t *)imageBase, imageSize, &matchCount);
        if (!target)
        {
            if (matchCount > 1)
                PublishLine(HOOK_LOG_ERROR, "[hook] %s: the signature matches %d places, refusing to patch", spec->name,
                            matchCount);
            else
                PublishLine(HOOK_LOG_ERROR, "[hook] %s: signature not found", spec->name);
            continue;
        }

        void *trampoline = BuildTrampoline(spec, target);
        if (!trampoline)
            continue;

        entry->target = (uint64_t)(uintptr_t)target;
        entry->trampoline = (uint64_t)(uintptr_t)trampoline;
        entry->status = HOOK_STATUS_READY;

        PublishLine(HOOK_LOG_INFO, "[hook] %s: trampoline at %p for %p", spec->name, trampoline,
                    (void *)(uintptr_t)target);
    }

    InterlockedExchange(&g_self.entryCount, HOOK_INDEX_COUNT);
}

static DWORD WINAPI ShimWorker(LPVOID unused)
{
    (void)unused;

    InterlockedExchange(&g_self.magic, (LONG)HOOK_PROTOCOL_MAGIC);
    g_self.version = HOOK_PROTOCOL_VERSION;

    AcquireProcessHookMutex();

    for (int attempt = 0; attempt < HOOK_BOOT_SETTINGS_SPIN_MS / 100 && g_self.settingsRevision == 0; attempt++)
        Sleep(100);

    struct HookSettings settings;
    if (!SelfSettingsSnapshot(&settings))
        CopyShimDefaultSettings(&settings);

    if (settings.startDelayMs > 0)
        Sleep((DWORD)settings.startDelayMs);

    HMODULE self = NULL;
    GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                       (LPCWSTR)&ShimWorker, &self);

    uint8_t *image = (uint8_t *)GetModuleHandleA("Growtopia.exe");
    if (!image && settings.allowAnyModule)
        image = (uint8_t *)GetModuleHandleA(NULL);
    size_t imageSize = ImageSizeOf(image);

    if (!image)
    {
        PublishLine(HOOK_LOG_ERROR, "[hook] the game image could not be resolved, the shim stays idle");
        return 0;
    }

    PublishEntries((uint64_t)GetCurrentProcessId(), (uint64_t)(uintptr_t)image, (uint64_t)(uintptr_t)self, imageSize);

    InterlockedExchange(&g_self.ready, 1);

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
    }
    return TRUE;
}
