// BUILD_FLAGS[gcc, clang]: -O2 -shared -fPIC -mwindows
// BUILD_FLAGS[msvc]: /O2 /LD /TC /Gy
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

#pragma comment(lib, "advapi32.lib")

#define MAX_LOG_MESSAGE       1024
#define MAX_EVENT_TEXT        512
#define MAX_PIPE_LINE         4096
#define PIPE_POLL_INTERVAL_MS 20
#define MAX_PIPE_CLIENTS      4
#define CLIENT_EVENT_CAPACITY 64

#define LOG_BACKLOG_CAPACITY 128
#define LOG_BACKLOG_LINE     512

#define TARGET_HUNT_INTERVAL_MS 1000
#define TARGET_FAIL_LOG_MS      30000
#define PID_MUTEX_WAIT_TRIES    200
#define PID_MUTEX_WAIT_STEP_MS  100

#ifndef AGENT_IDLE_GRACE_MS
#  define AGENT_IDLE_GRACE_MS 5000
#endif
#ifndef AGENT_BOOTSTRAP_EXIT_MS
#  define AGENT_BOOTSTRAP_EXIT_MS 180000
#endif

#define RING_DRAIN_PASSES 5

#if defined(_MSC_VER)
#  define EXPORT __declspec(dllexport)
#else
#  define EXPORT __attribute__((visibility("default")))
#endif

typedef int (*FnRemoteInject)(const char *target, const char *dll_path);
typedef const char *(*FnRemoteLastError)(void);
typedef int (*FnRemoteConfigure)(const void *settings, uint32_t size);
typedef int (*FnRemoteApplySettings)(const char *target, const char *dll_path, const void *settings, uint32_t size);

static FnRemoteInject g_inject = NULL;
static FnRemoteLastError g_lastErrorFn = NULL;
static FnRemoteConfigure g_configureFn = NULL;
static FnRemoteApplySettings g_applySettingsFn = NULL;
static char g_payloadPath[MAX_PATH] = {0};

static const char *const HOOK_AGENT_TARGET = "Growtopia.exe";
static const char *const HOOK_MODULE_NAME = "hook.dll";

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

static void ReplaceSpacesImpl(char *text)
{
    for (char *cursor = text; *cursor; cursor++)
    {
        if (*cursor == ' ')
            *cursor = '_';
    }
}

static struct HookSettings g_settings;
static struct HookCapture g_capture;
static CRITICAL_SECTION g_stateLock;
static volatile LONG g_stateLockReady = 0;

static void SetDefaultSettings(void)
{
    CopyText(g_settings.proxyHost, sizeof(g_settings.proxyHost), "127.0.0.1");
    g_settings.proxyPort = 16999;
    g_settings.startDelayMs = 2500;
    g_settings.logLevel = HOOK_LOG_INFO;
    g_settings.allowAnyModule = 0;
    g_settings.streamGameLogs = 0;
    ZeroMemory(&g_capture, sizeof(g_capture));
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

static void BufferFree(struct TextBuffer *buffer)
{
    free(buffer->data);
    buffer->data = NULL;
    buffer->length = 0;
    buffer->capacity = 0;
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

static char g_logBacklog[LOG_BACKLOG_CAPACITY][LOG_BACKLOG_LINE];
static size_t g_logBacklogHead = 0;
static size_t g_logBacklogCount = 0;
static CRITICAL_SECTION g_logLock;
static volatile LONG g_logLockReady = 0;

static void AgentEmit(const char *message, int keep)
{
    if (!message)
        return;

    if (keep && g_logLockReady)
    {
        EnterCriticalSection(&g_logLock);
        CopyText(g_logBacklog[g_logBacklogHead], LOG_BACKLOG_LINE, message);
        g_logBacklogHead = (g_logBacklogHead + 1) % LOG_BACKLOG_CAPACITY;
        if (g_logBacklogCount < LOG_BACKLOG_CAPACITY)
            g_logBacklogCount++;
        LeaveCriticalSection(&g_logLock);
    }

    QueueEvent("log", message);
}

static void AgentLog(const char *format, ...)
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

    OutputDebugStringA(message);
    AgentEmit(message, 1);
}

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
        OutputDebugStringA("[pipe] the write failed, the client is gone\n");
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

static DWORD g_gamePid = 0;
static HANDLE g_memoryProcess = NULL;
static uint64_t g_selfRemote = 0;
static uint32_t g_selfRva = 0;
static int g_selfRvaValid = 0;
static volatile LONG g_everHadClient = 0;
static ULONGLONG g_agentStartedAt = 0;

static struct ShimShared g_shimHead;
static int g_shimValid = 0;
static LONG g_consumedTicket = 0;
static struct HookSettings g_syncedSettings;
static int g_patchedAnnounced = 0;

static void InvalidateShimCaches(void)
{
    if (g_stateLockReady)
        EnterCriticalSection(&g_stateLock);
    g_selfRemote = 0;
    g_shimValid = 0;
    g_consumedTicket = 0;
    g_patchedAnnounced = 0;
    ZeroMemory(&g_syncedSettings, sizeof(g_syncedSettings));
    if (g_stateLockReady)
        LeaveCriticalSection(&g_stateLock);
}

static HMODULE find_remote_module(DWORD pid, const char *module_name)
{
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid);
    if (snapshot == INVALID_HANDLE_VALUE)
        return NULL;

    HMODULE module = NULL;
    MODULEENTRY32 entry;
    memset(&entry, 0, sizeof(entry));
    entry.dwSize = sizeof(entry);
    if (Module32First(snapshot, &entry))
    {
        do
        {
            if (_stricmp(entry.szModule, module_name) == 0)
            {
                module = entry.hModule;
                break;
            }
        } while (Module32Next(snapshot, &entry));
    }
    CloseHandle(snapshot);

    return module;
}

static uint32_t RvaToFileOffset(const uint8_t *image, size_t imageSize, uint32_t rva)
{
    const IMAGE_DOS_HEADER *dos = (const IMAGE_DOS_HEADER *)image;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE)
        return 0;
    const IMAGE_NT_HEADERS64 *nt = (const IMAGE_NT_HEADERS64 *)(image + dos->e_lfanew);
    if ((const uint8_t *)nt + sizeof(*nt) > image + imageSize || nt->Signature != IMAGE_NT_SIGNATURE)
        return 0;

    const IMAGE_SECTION_HEADER *section =
        (const IMAGE_SECTION_HEADER *)((const uint8_t *)nt + offsetof(IMAGE_NT_HEADERS64, OptionalHeader) +
                                       nt->FileHeader.SizeOfOptionalHeader);
    uint16_t count = nt->FileHeader.NumberOfSections;
    for (uint16_t i = 0; i < count; i++)
    {
        uint32_t start = section[i].VirtualAddress;
        uint32_t end = start + section[i].Misc.VirtualSize;
        if (rva >= start && rva < end)
        {
            uint32_t delta = rva - start;
            if (delta >= section[i].SizeOfRawData)
                return 0;
            return section[i].PointerToRawData + delta;
        }
    }

    return 0;
}

static int ExportRvaFromFile(const char *path, const char *name, uint32_t *outRva)
{
    if (!outRva)
        return 0;
    *outRva = 0;

    FILE *file = fopen(path, "rb");
    if (!file)
        return 0;

    uint8_t *image = NULL;
    size_t imageSize = 0;
    int found = 0;

    fseek(file, 0, SEEK_END);
    long size = ftell(file);
    fseek(file, 0, SEEK_SET);
    if (size > 0 && size < 16 * 1024 * 1024 && (image = (uint8_t *)malloc((size_t)size)))
    {
        imageSize = fread(image, 1, (size_t)size, file);
        const IMAGE_DOS_HEADER *dos = (const IMAGE_DOS_HEADER *)image;
        if (imageSize > sizeof(IMAGE_DOS_HEADER) && dos->e_magic == IMAGE_DOS_SIGNATURE)
        {
            const IMAGE_NT_HEADERS64 *nt = (const IMAGE_NT_HEADERS64 *)(image + dos->e_lfanew);
            if ((const uint8_t *)nt + sizeof(*nt) <= image + imageSize && nt->Signature == IMAGE_NT_SIGNATURE &&
                nt->FileHeader.SizeOfOptionalHeader >= sizeof(IMAGE_OPTIONAL_HEADER64))
            {
                const IMAGE_OPTIONAL_HEADER64 *optional = &nt->OptionalHeader;
                const IMAGE_DATA_DIRECTORY *exported = (optional->NumberOfRvaAndSizes > IMAGE_DIRECTORY_ENTRY_EXPORT)
                                                           ? &optional->DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT]
                                                           : NULL;
                if (exported && exported->VirtualAddress)
                {
                    uint32_t offset = RvaToFileOffset(image, imageSize, exported->VirtualAddress);
                    if (offset && offset + sizeof(IMAGE_EXPORT_DIRECTORY) <= imageSize)
                    {
                        const IMAGE_EXPORT_DIRECTORY *exports = (const IMAGE_EXPORT_DIRECTORY *)(image + offset);
                        uint32_t namesOffset = RvaToFileOffset(image, imageSize, exports->AddressOfNames);
                        uint32_t ordinalsOffset = RvaToFileOffset(image, imageSize, exports->AddressOfNameOrdinals);
                        uint32_t functionsOffset = RvaToFileOffset(image, imageSize, exports->AddressOfFunctions);
                        if (namesOffset && ordinalsOffset && functionsOffset && exports->NumberOfNames > 0 &&
                            exports->NumberOfNames < 4096)
                        {
                            const uint32_t *names = (const uint32_t *)(image + namesOffset);
                            const uint16_t *ordinals = (const uint16_t *)(image + ordinalsOffset);
                            const uint32_t *functions = (const uint32_t *)(image + functionsOffset);
                            for (uint32_t i = 0; i < exports->NumberOfNames; i++)
                            {
                                if (!names[i])
                                    continue;
                                uint32_t nameOffset = RvaToFileOffset(image, imageSize, names[i]);
                                if (!nameOffset)
                                    continue;
                                if (strcmp((const char *)(image + nameOffset), name) == 0)
                                {
                                    uint16_t ordinal = ordinals[i];
                                    if (ordinal < exports->NumberOfFunctions)
                                    {
                                        *outRva = functions[ordinal];
                                        found = 1;
                                    }
                                    break;
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    free(image);
    fclose(file);
    return found;
}

static HANDLE EnsureMemoryProcess(DWORD pid)
{
    if (g_memoryProcess && g_gamePid == pid)
        return g_memoryProcess;
    if (g_memoryProcess)
    {
        CloseHandle(g_memoryProcess);
        g_memoryProcess = NULL;
    }
    if (!pid)
        return NULL;
    g_memoryProcess = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, FALSE, pid);
    return g_memoryProcess;
}

static void ForgetTarget(void)
{
    g_gamePid = 0;
    if (g_memoryProcess)
    {
        CloseHandle(g_memoryProcess);
        g_memoryProcess = NULL;
    }
    InvalidateShimCaches();
}

static void RefreshSnapshot(void)
{
    if (!g_selfRvaValid)
    {
        if (g_payloadPath[0])
            g_selfRvaValid = ExportRvaFromFile(g_payloadPath, HOOK_EXPORT_NAME, &g_selfRva) && g_selfRva;
        if (!g_selfRvaValid)
            return;
    }
    if (!g_gamePid || !g_memoryProcess)
        return;

    if (!g_selfRemote)
    {
        HMODULE base = find_remote_module(g_gamePid, HOOK_MODULE_NAME);
        if (!base)
            return;
        g_selfRemote = (uint64_t)(uintptr_t)base + g_selfRva;
    }

    struct ShimShared head;
    SIZE_T readBytes = 0;
    void *address = (void *)(uintptr_t)g_selfRemote;
    if (!ReadProcessMemory(g_memoryProcess, address, &head, offsetof(struct ShimShared, log), &readBytes) ||
        readBytes != offsetof(struct ShimShared, log))
        return;

    if (head.magic != HOOK_PROTOCOL_MAGIC || head.version != HOOK_PROTOCOL_VERSION)
        return;

    EnterCriticalSection(&g_stateLock);
    g_shimHead = head;
    g_shimValid = 1;
    LeaveCriticalSection(&g_stateLock);
}

struct SettingDescriptor
{
    const char *name;
    int kind;
    int base;
    size_t offset;
    size_t capacity;
    long minimum;
    long maximum;
    int writable;
};

#define SETTING_TEXT   0
#define SETTING_NUMBER 1
#define BASE_SETTINGS  0
#define BASE_CAPTURE   1

static const struct SettingDescriptor g_descriptors[] = {
    {"proxy_host",       SETTING_TEXT,   BASE_SETTINGS, offsetof(struct HookSettings, proxyHost),
     sizeof(((struct HookSettings *)0)->proxyHost),                                                       0, 0,      1},
    {"proxy_port",       SETTING_NUMBER, BASE_SETTINGS, offsetof(struct HookSettings, proxyPort),      0, 1, 65535,  1},
    {"start_delay_ms",   SETTING_NUMBER, BASE_SETTINGS, offsetof(struct HookSettings, startDelayMs),   0, 0, 600000, 1},
    {"log_level",        SETTING_NUMBER, BASE_SETTINGS, offsetof(struct HookSettings, logLevel),       0, 0, 2,      1},
    {"allow_any_module", SETTING_NUMBER, BASE_SETTINGS, offsetof(struct HookSettings, allowAnyModule), 0, 0, 1,      1},
    {"stream_game_logs", SETTING_NUMBER, BASE_SETTINGS, offsetof(struct HookSettings, streamGameLogs), 0, 0, 1,      1},

    {"client_version",   SETTING_TEXT,   BASE_CAPTURE,  offsetof(struct HookCapture,  clientVersion),
     sizeof(((struct HookCapture *)0)->clientVersion),                                                    0, 0,      0},
    {"client_protocol",  SETTING_TEXT,   BASE_CAPTURE,  offsetof(struct HookCapture,  clientProtocol),
     sizeof(((struct HookCapture *)0)->clientProtocol),                                                   0, 0,      0},
    {"client_platform",  SETTING_TEXT,   BASE_CAPTURE,  offsetof(struct HookCapture,  clientPlatform),
     sizeof(((struct HookCapture *)0)->clientPlatform),                                                   0, 0,      0},
    {"real_server",      SETTING_TEXT,   BASE_CAPTURE,  offsetof(struct HookCapture,  realServer),
     sizeof(((struct HookCapture *)0)->realServer),                                                       0, 0,      0},
    {"real_port",        SETTING_NUMBER, BASE_CAPTURE,  offsetof(struct HookCapture,  realPort),       0, 0, 65535,  0},
};

#define SETTING_COUNT ((int)(sizeof(g_descriptors) / sizeof(g_descriptors[0])))

static const struct SettingDescriptor *FindSetting(const char *name)
{
    if (!name)
        return NULL;

    for (int i = 0; i < SETTING_COUNT; i++)
    {
        if (_stricmp(g_descriptors[i].name, name) == 0)
            return &g_descriptors[i];
    }

    return NULL;
}

static void *SettingPointer(const struct SettingDescriptor *descriptor)
{
    char *base = descriptor->base == BASE_CAPTURE ? (char *)&g_capture : (char *)&g_settings;
    return base + descriptor->offset;
}

static void FormatSetting(const struct SettingDescriptor *descriptor, char *out, size_t outSize)
{
    if (!descriptor || !out || outSize == 0)
        return;
    const void *pointer = SettingPointer(descriptor);
    if (descriptor->kind == SETTING_NUMBER)
        snprintf(out, outSize, "%d", *(const int *)pointer);
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

static void SyncShimSettings(void)
{
    if (!g_applySettingsFn || !g_gamePid || !g_shimValid)
        return;
    if (memcmp(&g_settings, &g_syncedSettings, sizeof(g_settings)) == 0)
        return;

    char pidText[16];
    snprintf(pidText, sizeof(pidText), "%lu", (unsigned long)g_gamePid);

    struct HookSettings outbound;
    EnterCriticalSection(&g_stateLock);
    outbound = g_settings;
    LeaveCriticalSection(&g_stateLock);

    int rc = g_applySettingsFn(pidText, g_payloadPath, &outbound, (uint32_t)sizeof(outbound));
    if (rc == 0)
        g_syncedSettings = outbound;
    else
        AgentLog("[hook] agent: the settings sync failed (rc=%d: %s)", rc, g_lastErrorFn ? g_lastErrorFn() : "unknown");
}

static void BuildStatusLine(struct TextBuffer *buffer)
{
    BufferAppendText(buffer, "DATA");

    struct HookSettings settingsLocal;
    struct HookCapture captureLocal;
    struct ShimShared shimLocal;
    int shimValidLocal;
    ULONGLONG now = GetTickCount64();

    EnterCriticalSection(&g_stateLock);
    settingsLocal = g_settings;
    captureLocal = g_capture;
    shimValidLocal = g_shimValid;
    if (g_shimValid)
        shimLocal = g_shimHead;
    LeaveCriticalSection(&g_stateLock);

    for (int i = 0; i < SETTING_COUNT; i++)
    {
        char value[MAX_LOG_MESSAGE];
        if (g_descriptors[i].base == BASE_CAPTURE)
        {
            const void *pointer = (const char *)&captureLocal + g_descriptors[i].offset;
            if (g_descriptors[i].kind == SETTING_NUMBER)
                snprintf(value, sizeof(value), "%d", *(const int *)pointer);
            else
                CopyText(value, sizeof(value), (const char *)pointer);
        }
        else
        {
            const void *pointer = (const char *)&settingsLocal + g_descriptors[i].offset;
            if (g_descriptors[i].kind == SETTING_NUMBER)
                snprintf(value, sizeof(value), "%d", *(const int *)pointer);
            else
                CopyText(value, sizeof(value), (const char *)pointer);
        }
        BufferAppendText(buffer, " ");
        BufferAppendText(buffer, g_descriptors[i].name);
        BufferAppendText(buffer, "=");
        AppendSanitized(buffer, value);
    }

    uint64_t processId = shimValidLocal ? shimLocal.processId : 0;
    char scratch[160];
    snprintf(scratch, sizeof(scratch), " pid=%lu", (unsigned long)(uintptr_t)processId);
    BufferAppendText(buffer, scratch);

    snprintf(scratch, sizeof(scratch), " image_base=0x%llX",
             (unsigned long long)(shimValidLocal ? shimLocal.imageBase : 0));
    BufferAppendText(buffer, scratch);

    snprintf(scratch, sizeof(scratch), " image_size=0x%llX",
             (unsigned long long)(shimValidLocal ? shimLocal.imageSize : 0));
    BufferAppendText(buffer, scratch);

    snprintf(scratch, sizeof(scratch), " dll_base=0x%llX",
             (unsigned long long)(shimValidLocal ? shimLocal.dllBase : 0));
    BufferAppendText(buffer, scratch);

    uint64_t uptime = 0;
    if (shimValidLocal && shimLocal.bootTick && now >= shimLocal.bootTick)
        uptime = now - shimLocal.bootTick;
    snprintf(scratch, sizeof(scratch), " uptime_ms=%llu", (unsigned long long)uptime);
    BufferAppendText(buffer, scratch);

    for (int i = 0; i < HOOK_INDEX_COUNT && i < HOOK_MAX_ENTRIES; i++)
    {
        LONG value =
            (shimValidLocal && i < (int)shimLocal.entryCount) ? shimLocal.entries[i].status : (LONG)HOOK_STATUS_MISSING;
        const char *status = "missing";
        if (value == HOOK_STATUS_PATCHED)
            status = "patched";
        else if (value == HOOK_STATUS_READY)
            status = "ready";

        snprintf(scratch, sizeof(scratch), " hook_%s=%s", HOOK_IDENTITIES[i].key, status);
        BufferAppendText(buffer, scratch);

        snprintf(
            scratch, sizeof(scratch), " target_%s=0x%llX", HOOK_IDENTITIES[i].key,
            (unsigned long long)((shimValidLocal && i < (int)shimLocal.entryCount) ? shimLocal.entries[i].target : 0));
        BufferAppendText(buffer, scratch);
    }
}

static void PublishStateEvent(void)
{
    char version[HOOK_FIELD_MAX];
    char protocol[HOOK_FIELD_MAX];
    char platform[HOOK_FIELD_MAX];
    char server[HOOK_FIELD_MAX];
    int port = 0;

    EnterCriticalSection(&g_stateLock);
    CopyText(version, sizeof(version), g_capture.clientVersion);
    CopyText(protocol, sizeof(protocol), g_capture.clientProtocol);
    CopyText(platform, sizeof(platform), g_capture.clientPlatform);
    CopyText(server, sizeof(server), g_capture.realServer);
    port = g_capture.realPort;
    LeaveCriticalSection(&g_stateLock);

    ReplaceSpacesImpl(version);
    ReplaceSpacesImpl(protocol);
    ReplaceSpacesImpl(platform);
    ReplaceSpacesImpl(server);

    char text[MAX_EVENT_TEXT];
    snprintf(text, sizeof(text), "client_version=%s client_protocol=%s client_platform=%s real_server=%s real_port=%d",
             version, protocol, platform, server, port);
    QueueEvent("state", text);
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

static void BuildHandshake(struct HookHandshake *out)
{
    memset(out, 0, sizeof(*out));

    struct ShimShared shimLocal;
    int shimValidLocal;
    EnterCriticalSection(&g_stateLock);
    shimValidLocal = g_shimValid;
    if (g_shimValid)
        shimLocal = g_shimHead;
    LeaveCriticalSection(&g_stateLock);
    if (!shimValidLocal)
        return;

    out->magic = HOOK_PROTOCOL_MAGIC;
    out->version = HOOK_PROTOCOL_VERSION;
    out->processId = shimLocal.processId;
    out->imageBase = shimLocal.imageBase;
    out->imageSize = shimLocal.imageSize;
    out->dllBase = shimLocal.dllBase;

    uint32_t count = 0;
    for (int i = 0; i < HOOK_INDEX_COUNT && i < HOOK_MAX_ENTRIES; i++)
    {
        if (shimLocal.entries[i].status == HOOK_STATUS_MISSING)
            continue;
        out->entries[count++] = shimLocal.entries[i];
    }
    out->entryCount = count;
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
        int shimValidLocal;
        EnterCriticalSection(&g_stateLock);
        shimValidLocal = g_shimValid;
        LeaveCriticalSection(&g_stateLock);
        if (!shimValidLocal)
        {
            WritePipeLine(pipe, "ERR the hooks are not installed yet");
            return 0;
        }
        struct HookHandshake handshake;
        BuildHandshake(&handshake);
        char hex[MAX_PIPE_LINE];
        HexEncode((const uint8_t *)&handshake, sizeof(handshake), hex, sizeof(hex));
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
        EnterCriticalSection(&g_stateLock);
        FormatSetting(descriptor, value, sizeof(value));
        LeaveCriticalSection(&g_stateLock);
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
        int applied;
        EnterCriticalSection(&g_stateLock);
        applied = ApplySetting(descriptor, value, error, sizeof(error));
        LeaveCriticalSection(&g_stateLock);
        if (!applied)
        {
            WritePipeLine(pipe, error[0] ? error : "ERR invalid value");
            return 0;
        }
        WritePipeLine(pipe, "OK");
        SyncShimSettings();
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
    if (slot >= 0)
        InterlockedExchange(&g_everHadClient, 1);
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
        AgentLog("[pipe] cannot create the security descriptor, using the process default");
    }

    AgentLog("[pipe] listening on %s", HOOK_PIPE_NAME);

    for (;;)
    {
        HANDLE pipe = CreateNamedPipeA(HOOK_PIPE_NAME, PIPE_ACCESS_DUPLEX,
                                       PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                                       PIPE_UNLIMITED_INSTANCES, 8192, 8192, 0, descriptor ? &attributes : NULL);
        if (pipe == INVALID_HANDLE_VALUE)
        {
            AgentLog("[pipe] cannot create the pipe (err=%lu)", GetLastError());
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
            AgentLog("[pipe] too many clients, refusing the connection");
            DisconnectNamedPipe(pipe);
            CloseHandle(pipe);
            continue;
        }

        HANDLE thread = CreateThread(NULL, 0, PipeClientThread, (LPVOID)(intptr_t)slot, 0, NULL);
        if (!thread)
        {
            AgentLog("[pipe] cannot start the client thread (err=%lu)", GetLastError());
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

static int g_streamGate = 0;
static int g_levelGate = HOOK_LOG_INFO;

static void DrainLogRing(void)
{
    if (!g_memoryProcess || !g_selfRemote || !g_shimValid)
        return;

    EnterCriticalSection(&g_stateLock);
    g_streamGate = g_settings.streamGameLogs;
    g_levelGate = g_settings.logLevel;
    LeaveCriticalSection(&g_stateLock);

    LONG ticket = g_shimHead.logTicket;
    LONG oldest = ticket - HOOK_LOG_SLOTS;
    if (g_consumedTicket < oldest)
        g_consumedTicket = oldest;
    if (g_consumedTicket >= ticket)
        return;

    struct HookSlot slots[HOOK_LOG_SLOTS];
    SIZE_T readBytes = 0;
    void *address = (void *)(uintptr_t)(g_selfRemote + offsetof(struct ShimShared, log));
    if (!ReadProcessMemory(g_memoryProcess, address, slots, sizeof(slots), &readBytes) || readBytes != sizeof(slots))
        return;

    for (LONG sequence = g_consumedTicket; sequence < ticket; sequence++)
    {
        const struct HookSlot *slot = &slots[(size_t)((ULONG)sequence % HOOK_LOG_SLOTS)];
        if (slot->sequence != sequence)
            continue;
        if (slot->state != HOOK_SLOT_READY)
            continue;

        if (slot->level == HOOK_LOG_GAME)
        {
            if (g_streamGate)
                QueueEvent("log", slot->text);
        }
        else if (slot->level <= g_levelGate)
        {
            QueueEvent("log", slot->text);
        }
    }

    g_consumedTicket = ticket;
}

static int g_lastStateValid = 0;
static struct HookCapture g_lastCapture;

static void DiffState(void)
{
    struct HookCapture captureLocal;
    EnterCriticalSection(&g_stateLock);
    captureLocal = g_capture;
    LeaveCriticalSection(&g_stateLock);

    if (!g_lastStateValid)
    {
        g_lastCapture = captureLocal;
        g_lastStateValid = 1;
        return;
    }

    if (strcmp(g_lastCapture.clientVersion, captureLocal.clientVersion) != 0 ||
        strcmp(g_lastCapture.clientProtocol, captureLocal.clientProtocol) != 0 ||
        strcmp(g_lastCapture.clientPlatform, captureLocal.clientPlatform) != 0 ||
        strcmp(g_lastCapture.realServer, captureLocal.realServer) != 0 ||
        g_lastCapture.realPort != captureLocal.realPort)
    {
        g_lastCapture = captureLocal;
        PublishStateEvent();
    }
}

static void WatchStatuses(void)
{
    if (!g_shimValid || g_patchedAnnounced)
        return;

    for (int i = 0; i < HOOK_INDEX_COUNT && i < HOOK_MAX_ENTRIES; i++)
    {
        if (g_shimHead.entries[i].status == HOOK_STATUS_PATCHED)
        {
            g_patchedAnnounced = 1;
            AgentLog("[hook] the entry points are patched, the hook is live");
            AgentLog("[gtools] hook injected successfully");
            return;
        }
    }
}

static HANDLE g_targetProcess = NULL;
static ULONGLONG g_lastFailLog = 0;

static DWORD FindTargetPid(const char *target)
{
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE)
        return 0;

    DWORD pid = 0;
    PROCESSENTRY32 entry;
    memset(&entry, 0, sizeof(entry));
    entry.dwSize = sizeof(entry);
    if (Process32First(snapshot, &entry))
    {
        do
        {
            if (_stricmp(entry.szExeFile, target) == 0)
            {
                pid = entry.th32ProcessID;
                break;
            }
        } while (Process32Next(snapshot, &entry));
    }
    CloseHandle(snapshot);

    return pid;
}

static int PidIsHooked(DWORD pid)
{
    char name[64];
    snprintf(name, sizeof(name), "%s%lu", HOOK_PID_MUTEX_PREFIX, (unsigned long)pid);
    HANDLE existing = OpenMutexA(SYNCHRONIZE, FALSE, name);
    if (!existing)
        return 0;
    CloseHandle(existing);
    return 1;
}

static void AdoptPid(DWORD pid)
{
    g_gamePid = pid;
    InvalidateShimCaches();
    EnsureMemoryProcess(pid);
}

static void MonitorTarget(void)
{
    if (g_targetProcess)
    {
        if (WaitForSingleObject(g_targetProcess, 0) == WAIT_OBJECT_0)
        {
            DWORD code = 0;
            GetExitCodeProcess(g_targetProcess, &code);
            CloseHandle(g_targetProcess);
            g_targetProcess = NULL;
            ForgetTarget();
            if (code & 0x80000000)
                AgentLog("[hook] %s exited with status 0x%08lX", HOOK_AGENT_TARGET, (unsigned long)code);
        }
        return;
    }

    if (g_gamePid)
    {
        if (PidIsHooked(g_gamePid))
            return;
        ForgetTarget();
    }

    static ULONGLONG lastHunt = 0;
    ULONGLONG now = GetTickCount64();
    if (lastHunt && now - lastHunt < TARGET_HUNT_INTERVAL_MS)
        return;
    lastHunt = now;

    DWORD pid = FindTargetPid(HOOK_AGENT_TARGET);
    if (!pid)
        return;

    if (PidIsHooked(pid))
    {
        AdoptPid(pid);
        g_targetProcess = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
        return;
    }

    if (!g_inject)
    {
        if (now - g_lastFailLog > TARGET_FAIL_LOG_MS || !g_lastFailLog)
        {
            g_lastFailLog = now;
            AgentLog("[hook] the injector is unavailable, cannot hook %s", HOOK_AGENT_TARGET);
        }
        return;
    }

    struct HookSettings outbound;
    EnterCriticalSection(&g_stateLock);
    outbound = g_settings;
    LeaveCriticalSection(&g_stateLock);
    if (g_configureFn)
        g_configureFn(&outbound, (uint32_t)sizeof(outbound));

    int rc = g_inject(HOOK_AGENT_TARGET, g_payloadPath);
    if (rc == 0 || rc == -1)
    {
        for (int i = 0; i < PID_MUTEX_WAIT_TRIES && !PidIsHooked(pid); i++)
            Sleep(PID_MUTEX_WAIT_STEP_MS);
        AdoptPid(pid);
        g_targetProcess = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
        AgentLog("[hook] %s is hooked (pid %lu)", HOOK_AGENT_TARGET, (unsigned long)pid);
    }
    else
    {
        if (now - g_lastFailLog > TARGET_FAIL_LOG_MS || !g_lastFailLog)
        {
            g_lastFailLog = now;
            const char *failure = g_lastErrorFn ? g_lastErrorFn() : NULL;
            AgentLog("[hook] agent: %s (rc=%d: %s)", HOOK_AGENT_TARGET, rc, failure ? failure : "unknown");
        }
    }
}

static void MaybeShutdown(void)
{
    int clients = 0;
    EnterCriticalSection(&g_clientLock);
    for (int i = 0; i < MAX_PIPE_CLIENTS; i++)
    {
        if (g_clients[i].active)
            clients++;
    }
    LeaveCriticalSection(&g_clientLock);

    static ULONGLONG idleSince = 0;
    ULONGLONG now = GetTickCount64();
    if (clients > 0)
    {
        idleSince = 0;
        return;
    }
    if (!idleSince)
    {
        idleSince = now;
        return;
    }
    if (now - idleSince < AGENT_IDLE_GRACE_MS)
        return;

    static ULONGLONG lastGameCheck = 0;
    if (lastGameCheck && now - lastGameCheck < 1000)
        return;
    lastGameCheck = now;

    if (g_gamePid)
        return;
    if (FindTargetPid(HOOK_AGENT_TARGET))
        return;

    if (!InterlockedCompareExchange(&g_everHadClient, 0, 0) && now - g_agentStartedAt < AGENT_BOOTSTRAP_EXIT_MS)
        return;

    AgentLog("[agent] the proxy and %s are both gone, terminating", HOOK_AGENT_TARGET);
    ExitProcess(0);
}

static HANDLE AgentAcquireSingleton(void)
{
    HANDLE mutex = CreateMutexA(NULL, TRUE, HOOK_AGENT_MUTEX_NAME);
    if (!mutex)
        return NULL;
    if (GetLastError() == ERROR_ALREADY_EXISTS)
    {
        CloseHandle(mutex);
        return NULL;
    }
    return mutex;
}

static void RunAgent(void);
EXPORT void CALLBACK AgentMain(HWND window, HINSTANCE instance, LPSTR commandLine, int showCommand);

static void LoadInjector(void)
{
    char agentPath[MAX_PATH];
    HMODULE self = NULL;
    if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            (LPCWSTR)&AgentMain, &self) ||
        !GetModuleFileNameA(self, agentPath, (DWORD)sizeof(agentPath)))
    {
        AgentLog("[hook] agent: cannot resolve the agent module");
        return;
    }

    char agentDirectory[MAX_PATH];
    CopyText(agentDirectory, sizeof(agentDirectory), agentPath);
    char *separator = strrchr(agentDirectory, '\\');
    if (separator)
        *separator = 0;
    else
        CopyText(agentDirectory, sizeof(agentDirectory), ".");

    char injectorPath[MAX_PATH];
    snprintf(injectorPath, sizeof(injectorPath), "%s\\injector.dll", agentDirectory);
    snprintf(g_payloadPath, sizeof(g_payloadPath), "%s\\hook.dll", agentDirectory);

    HMODULE injector = LoadLibraryA(injectorPath);
    if (!injector)
    {
        AgentLog("[hook] agent: missing %s (err=%lu)", injectorPath, GetLastError());
        return;
    }

    g_inject = (FnRemoteInject)(void *)GetProcAddress(injector, "inject");
    g_lastErrorFn = (FnRemoteLastError)(void *)GetProcAddress(injector, "last_error");
    g_configureFn = (FnRemoteConfigure)(void *)GetProcAddress(injector, "configure");
    g_applySettingsFn = (FnRemoteApplySettings)(void *)GetProcAddress(injector, "apply_settings");
    if (!g_inject || !g_lastErrorFn)
    {
        AgentLog("[hook] agent: injector exports are missing");
        g_inject = NULL;
        FreeLibrary(injector);
        return;
    }

    AgentLog("[hook] agent: watching %s", HOOK_AGENT_TARGET);
}

static void RunAgent(void)
{
    HANDLE singleton = AgentAcquireSingleton();
    if (!singleton)
        return;

    g_agentStartedAt = GetTickCount64();

    InitializeCriticalSection(&g_clientLock);
    g_clientLockReady = 1;
    InitializeCriticalSection(&g_logLock);
    g_logLockReady = 1;
    InitializeCriticalSection(&g_stateLock);
    g_stateLockReady = 1;

    SetDefaultSettings();

    LoadInjector();

    HANDLE pipeThread = CreateThread(NULL, 0, PipeServerThread, NULL, 0, NULL);
    if (!pipeThread)
        AgentLog("[hook] agent: cannot start the pipe thread (err=%lu)", GetLastError());
    else
        CloseHandle(pipeThread);

    int pass = 0;
    for (;;)
    {
        MonitorTarget();
        RefreshSnapshot();

        EnterCriticalSection(&g_stateLock);
        if (g_shimValid)
        {
            g_capture = g_shimHead.capture;
        }
        LeaveCriticalSection(&g_stateLock);

        SyncShimSettings();
        DiffState();
        WatchStatuses();
        MaybeShutdown();
        if (pass % RING_DRAIN_PASSES == 0)
            DrainLogRing();
        pass++;
        Sleep(PIPE_POLL_INTERVAL_MS);
    }
}

EXPORT void CALLBACK AgentMain(HWND window, HINSTANCE instance, LPSTR commandLine, int showCommand)
{
    (void)window;
    (void)instance;
    (void)commandLine;
    (void)showCommand;

    RunAgent();
}

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID reserved)
{
    (void)module;
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH)
        DisableThreadLibraryCalls(module);

    return TRUE;
}
