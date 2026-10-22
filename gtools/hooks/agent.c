// BUILD_FLAGS[gcc, clang]: -O2 -shared -fPIC -mwindows
// BUILD_FLAGS[msvc]: /O2 /LD /TC /Gy
// BUILD_FLAGS[gcc(mingw)]: -O2 -shared -fPIC -mwindows
//
// The host process (launch with: rundll32 agent.dll,AgentMain). It owns every
// part of the hook that does not have to live inside the game: the shared
// section, the named pipe, the settings, signature scanning happens in the
// injector (this process just hands over), trampoline building, patch
// verification, the game watch dog and crash reporting.

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

#define PATTERN_MAX 512

#define TARGET_HUNT_INTERVAL_MS 1000
#define TARGET_FAIL_LOG_MS      30000
#define PID_MUTEX_WAIT_TRIES    200
#define PID_MUTEX_WAIT_STEP_MS  100

typedef int (*FnRemoteInject)(const char *target, const char *dll_path);
typedef const char *(*FnRemoteLastError)(void);

__declspec(dllexport) void CALLBACK AgentMain(HWND window, HINSTANCE instance, LPSTR commandLine, int showCommand);

static struct HookShared *g_shm = NULL;
static HANDLE g_shmMapping = NULL;
static int g_sectionOwner = 0;

static FnRemoteInject g_inject = NULL;
static FnRemoteLastError g_lastErrorFn = NULL;
static char g_payloadPath[MAX_PATH] = {0};

static const char *const HOOK_AGENT_TARGET = "Growtopia.exe";

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

static void ReplaceSpaces(char *text)
{
    for (char *cursor = text; *cursor; cursor++)
    {
        if (*cursor == ' ')
            *cursor = '_';
    }
}

/* ---------- shared section ---------- */

static void SetDefaultSettings(struct HookSettings *settings)
{
    ZeroMemory(settings, sizeof(*settings));
    CopyText(settings->proxyHost, sizeof(settings->proxyHost), "127.0.0.1");
    settings->proxyPort = 16999;
    settings->startDelayMs = 2500;
    settings->logLevel = HOOK_LOG_INFO;
    settings->allowAnyModule = 0;
    settings->streamGameLogs = 0;
}

static int CreateSection(void)
{
    SECURITY_ATTRIBUTES attributes;
    PSECURITY_DESCRIPTOR descriptor = NULL;
    if (ConvertStringSecurityDescriptorToSecurityDescriptorA("D:(A;;GA;;;WD)", SDDL_REVISION_1, &descriptor, NULL))
    {
        attributes.nLength = sizeof(attributes);
        attributes.lpSecurityDescriptor = descriptor;
        attributes.bInheritHandle = FALSE;
    }
    else
    {
        ZeroMemory(&attributes, sizeof(attributes));
    }

    HANDLE mapping = CreateFileMappingA(INVALID_HANDLE_VALUE, descriptor ? &attributes : NULL, PAGE_READWRITE, 0,
                                        (DWORD)sizeof(struct HookShared), HOOK_SECTION_NAME);
    if (descriptor)
        LocalFree(descriptor);
    if (!mapping)
        return 0;

    int owner = (GetLastError() != ERROR_ALREADY_EXISTS);
    void *view = MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, 0);
    if (!view)
    {
        CloseHandle(mapping);
        return 0;
    }

    g_shmMapping = mapping;
    g_shm = (struct HookShared *)view;
    g_sectionOwner = owner;

    if (owner)
    {
        ZeroMemory(g_shm, sizeof(*g_shm));
        g_shm->magic = HOOK_PROTOCOL_MAGIC;
        g_shm->version = HOOK_PROTOCOL_VERSION;
        SetDefaultSettings(&g_shm->settings);
    }
    return 1;
}

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

/* ---------- settings ---------- */

struct SettingDescriptor
{
    const char *name;
    int kind;
    size_t offset;
    size_t capacity;
    long minimum;
    long maximum;
    int writable;
};

#define SETTING_TEXT 0
#define SETTING_NUMBER 1

static const struct SettingDescriptor g_settings[] = {
    {"proxy_host",       SETTING_TEXT,   offsetof(struct HookSettings, proxyHost),
     sizeof(((struct HookSettings *)0)->proxyHost), 0, 0, 1},
    {"proxy_port",       SETTING_NUMBER, offsetof(struct HookSettings, proxyPort),       0, 1, 65535,  1},
    {"start_delay_ms",   SETTING_NUMBER, offsetof(struct HookSettings, startDelayMs),    0, 0, 600000, 1},
    {"log_level",        SETTING_NUMBER, offsetof(struct HookSettings, logLevel),        0, 0, 2,      1},
    {"allow_any_module", SETTING_NUMBER, offsetof(struct HookSettings, allowAnyModule),  0, 0, 1,      1},
    {"stream_game_logs", SETTING_NUMBER, offsetof(struct HookSettings, streamGameLogs),  0, 0, 1,      1},

    {"client_version",   SETTING_TEXT,   offsetof(struct HookSettings, clientVersion),
     sizeof(((struct HookSettings *)0)->clientVersion), 0, 0, 0},
    {"client_protocol",  SETTING_TEXT,   offsetof(struct HookSettings, clientProtocol),
     sizeof(((struct HookSettings *)0)->clientProtocol), 0, 0, 0},
    {"client_platform",  SETTING_TEXT,   offsetof(struct HookSettings, clientPlatform),
     sizeof(((struct HookSettings *)0)->clientPlatform), 0, 0, 0},
    {"real_server",      SETTING_TEXT,   offsetof(struct HookSettings, realServer),
     sizeof(((struct HookSettings *)0)->realServer), 0, 0, 0},
    {"real_port",        SETTING_NUMBER, offsetof(struct HookSettings, realPort),        0, 0, 65535,  0},
};

#define SETTING_COUNT ((int)(sizeof(g_settings) / sizeof(g_settings[0])))

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

/* the caller holds the settings lock */
static void FormatSetting(const struct SettingDescriptor *descriptor, char *out, size_t outSize)
{
    if (!descriptor || !out || outSize == 0)
        return;
    const char *pointer = (const char *)&g_shm->settings + descriptor->offset;
    if (descriptor->kind == SETTING_NUMBER)
        snprintf(out, outSize, "%d", *(const int *)pointer);
    else
        CopyText(out, outSize, pointer);
}

/* the caller holds the settings lock */
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

    char *pointer = (char *)&g_shm->settings + descriptor->offset;
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

/* ---------- text buffers and pipe plumbing (same as the old in game code) ---------- */

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

/* ---------- status, state and handshake ---------- */

static void BuildStatusLine(struct TextBuffer *buffer)
{
    BufferAppendText(buffer, "DATA");

    if (AcquireSettings())
    {
        for (int i = 0; i < SETTING_COUNT; i++)
        {
            char value[MAX_LOG_MESSAGE];
            FormatSetting(&g_settings[i], value, sizeof(value));
            BufferAppendText(buffer, " ");
            BufferAppendText(buffer, g_settings[i].name);
            BufferAppendText(buffer, "=");
            AppendSanitized(buffer, value);
        }
        ReleaseSettings();
    }

    char scratch[128];
    snprintf(scratch, sizeof(scratch), " pid=%lu", (unsigned long)(uintptr_t)(g_shm ? g_shm->processId : 0));
    BufferAppendText(buffer, scratch);

    snprintf(scratch, sizeof(scratch), " image_base=0x%llX", (unsigned long long)(g_shm ? g_shm->imageBase : 0));
    BufferAppendText(buffer, scratch);

    snprintf(scratch, sizeof(scratch), " image_size=0x%llX", (unsigned long long)(g_shm ? g_shm->imageSize : 0));
    BufferAppendText(buffer, scratch);

    snprintf(scratch, sizeof(scratch), " dll_base=0x%llX", (unsigned long long)(g_shm ? g_shm->dllBase : 0));
    BufferAppendText(buffer, scratch);

    uint64_t uptime = 0;
    if (g_shm && g_shm->bootTick && GetTickCount64() >= g_shm->bootTick)
        uptime = GetTickCount64() - g_shm->bootTick;
    snprintf(scratch, sizeof(scratch), " uptime_ms=%llu", (unsigned long long)uptime);
    BufferAppendText(buffer, scratch);

    for (int i = 0; i < HOOK_INDEX_COUNT && i < HOOK_MAX_ENTRIES; i++)
    {
        const char *status = "missing";
        LONG value = g_shm ? InterlockedCompareExchange(&g_shm->entries[i].status, 0, 0) : HOOK_STATUS_MISSING;
        if (value == HOOK_STATUS_PATCHED)
            status = "patched";
        else if (value == HOOK_STATUS_READY)
            status = "ready";

        snprintf(scratch, sizeof(scratch), " hook_%s=%s", HOOK_IDENTITIES[i].key, status);
        BufferAppendText(buffer, scratch);

        snprintf(scratch, sizeof(scratch), " target_%s=0x%llX", HOOK_IDENTITIES[i].key,
                 (unsigned long long)(g_shm ? g_shm->entries[i].target : 0));
        BufferAppendText(buffer, scratch);
    }
}

static void PublishStateEvent(void)
{
    if (!g_shm)
        return;

    char version[HOOK_FIELD_MAX];
    char protocol[HOOK_FIELD_MAX];
    char platform[HOOK_FIELD_MAX];
    char server[HOOK_FIELD_MAX];
    int port = 0;

    if (AcquireSettings())
    {
        CopyText(version, sizeof(version), g_shm->settings.clientVersion);
        CopyText(protocol, sizeof(protocol), g_shm->settings.clientProtocol);
        CopyText(platform, sizeof(platform), g_shm->settings.clientPlatform);
        CopyText(server, sizeof(server), g_shm->settings.realServer);
        port = g_shm->settings.realPort;
        ReleaseSettings();
    }

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
    if (!g_shm)
        return;

    out->magic = HOOK_PROTOCOL_MAGIC;
    out->version = HOOK_PROTOCOL_VERSION;
    out->processId = g_shm->processId;
    out->imageBase = g_shm->imageBase;
    out->imageSize = g_shm->imageSize;
    out->dllBase = g_shm->dllBase;

    uint32_t count = 0;
    for (int i = 0; i < HOOK_INDEX_COUNT && i < HOOK_MAX_ENTRIES; i++)
    {
        if (InterlockedCompareExchange(&g_shm->entries[i].status, 0, 0) == HOOK_STATUS_MISSING)
            continue;
        out->entries[count++] = g_shm->entries[i];
    }
    out->entryCount = count;
}

/* ---------- pipe commands ---------- */

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
        if (!g_shm || !InterlockedCompareExchange(&g_shm->ready, 0, 0))
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
        if (AcquireSettings())
        {
            FormatSetting(descriptor, value, sizeof(value));
            ReleaseSettings();
        }
        else
            CopyText(value, sizeof(value), "");
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
        int applied = 0;
        if (AcquireSettings())
        {
            applied = ApplySetting(descriptor, value, error, sizeof(error));
            ReleaseSettings();
        }
        else
            snprintf(error, sizeof(error), "the shared section is missing");
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

/* ---------- log ring drain ---------- */

struct ReadySlot
{
    LONG sequence;
    int index;
};

static int ReadySlotOrder(const void *left, const void *right)
{
    const struct ReadySlot *a = (const struct ReadySlot *)left;
    const struct ReadySlot *b = (const struct ReadySlot *)right;
    if (a->sequence < b->sequence)
        return -1;
    if (a->sequence > b->sequence)
        return 1;
    return 0;
}

static void DrainSlots(void)
{
    if (!g_shm)
        return;

    /* take CLAIMED ownership of every ready slot, sort by ticket, forward */
    struct ReadySlot ready[HOOK_LOG_SLOTS];
    int count = 0;
    for (int i = 0; i < HOOK_LOG_SLOTS; i++)
    {
        struct HookSlot *slot = &g_shm->log[i];
        if (InterlockedCompareExchange(&slot->state, HOOK_SLOT_CLAIMED, HOOK_SLOT_READY) != HOOK_SLOT_READY)
            continue;
        ready[count].sequence = slot->sequence;
        ready[count].index = i;
        count++;
    }
    if (count == 0)
        return;

    qsort(ready, (size_t)count, sizeof(ready[0]), ReadySlotOrder);

    int gate = g_shm->settings.logLevel;
    for (int i = 0; i < count; i++)
    {
        struct HookSlot *slot = &g_shm->log[ready[i].index];
        if (slot->level == HOOK_LOG_GAME || slot->level <= gate)
            QueueEvent("log", slot->text);
        InterlockedExchange(&slot->state, HOOK_SLOT_EMPTY);
    }
}

/* ---------- state diff ---------- */

static struct HookSettings g_lastState;
static int g_lastStateValid = 0;

static void DiffState(void)
{
    struct HookSettings snapshot;
    if (!AcquireSettings())
        return;
    snapshot = g_shm->settings;
    ReleaseSettings();

    if (!g_lastStateValid)
    {
        g_lastState = snapshot;
        g_lastStateValid = 1;
        return;
    }

    if (strcmp(g_lastState.clientVersion, snapshot.clientVersion) != 0 ||
        strcmp(g_lastState.clientProtocol, snapshot.clientProtocol) != 0 ||
        strcmp(g_lastState.clientPlatform, snapshot.clientPlatform) != 0 ||
        strcmp(g_lastState.realServer, snapshot.realServer) != 0 || g_lastState.realPort != snapshot.realPort)
    {
        g_lastState = snapshot;
        PublishStateEvent();
    }
}

/* ---------- hook status watch ---------- */

static int g_patchedAnnounced = 0;

static void WatchStatuses(void)
{
    if (!g_shm || g_patchedAnnounced)
        return;

    for (int i = 0; i < HOOK_INDEX_COUNT && i < HOOK_MAX_ENTRIES; i++)
    {
        if (InterlockedCompareExchange(&g_shm->entries[i].status, 0, 0) == HOOK_STATUS_PATCHED)
        {
            g_patchedAnnounced = 1;
            AgentLog("[hook] the entry points are patched, the hook is live");
            AgentLog("[gtools] hook injected successfully");
            return;
        }
    }
}

/* ---------- game watch dog ---------- */

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

static DWORD g_targetPid = 0;
static HANDLE g_targetProcess = NULL;
static ULONGLONG g_lastFailLog = 0;

/* stale statuses would look like live hooks to the clients */
static void ResetHookStatuses(void)
{
    if (!g_shm)
        return;
    for (int i = 0; i < HOOK_INDEX_COUNT && i < HOOK_MAX_ENTRIES; i++)
        InterlockedExchange(&g_shm->entries[i].status, HOOK_STATUS_MISSING);
    g_patchedAnnounced = 0;
}

static void MonitorTarget(void)
{
    /* crash and exit reporting for the process we injected */
    if (g_targetProcess)
    {
        if (WaitForSingleObject(g_targetProcess, 0) == WAIT_OBJECT_0)
        {
            DWORD code = 0;
            GetExitCodeProcess(g_targetProcess, &code);
            CloseHandle(g_targetProcess);
            g_targetProcess = NULL;
            g_targetPid = 0;
            ResetHookStatuses();
            if (code & 0x80000000)
                AgentLog("[hook] %s exited with status 0x%08lX", HOOK_AGENT_TARGET, (unsigned long)code);
        }
        return;
    }

    if (g_targetPid)
    {
        if (PidIsHooked(g_targetPid))
            return;
        g_targetPid = 0;
        ResetHookStatuses();
    }

    /* only hunt for the game once per interval */
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
        /* injected by another path (python), start the exit monitor anyway */
        g_targetPid = pid;
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

    int rc = g_inject(HOOK_AGENT_TARGET, g_payloadPath);
    if (rc == 0 || rc == -1)
    {
        for (int i = 0; i < PID_MUTEX_WAIT_TRIES && !PidIsHooked(pid); i++)
            Sleep(PID_MUTEX_WAIT_STEP_MS);
        g_targetPid = pid;
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

/* ---------- agent entry ---------- */

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

    if (!CreateSection())
    {
        OutputDebugStringA("[hook] agent: cannot create the shared section\n");
        return;
    }

    InitializeCriticalSection(&g_clientLock);
    g_clientLockReady = 1;
    InitializeCriticalSection(&g_logLock);
    g_logLockReady = 1;

    LoadInjector();

    HANDLE pipeThread = CreateThread(NULL, 0, PipeServerThread, NULL, 0, NULL);
    if (!pipeThread)
        AgentLog("[hook] agent: cannot start the pipe thread (err=%lu)", GetLastError());
    else
        CloseHandle(pipeThread);

    for (;;)
    {
        DrainSlots();
        DiffState();
        WatchStatuses();
        MonitorTarget();
        Sleep(PIPE_POLL_INTERVAL_MS);
    }
}

__declspec(dllexport) void CALLBACK AgentMain(HWND window, HINSTANCE instance, LPSTR commandLine, int showCommand)
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

