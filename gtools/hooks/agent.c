/*
 * agent.c - the out-of-process watcher (rundll32 AgentMain).
 *
 * Feature-blind v4: watches for the target process, injects hook.dll with the
 * install payload (authored by Python), serves the control pipe with generic
 * commands (STATUS/HOOKS/ENABLE/STATE/DATA), drains the shim's event ring and
 * forwards everything to connected clients.
 *
 * BUILD_FLAGS[gcc, clang]: -O2 -shared -fPIC -mwindows
 * BUILD_FLAGS[msvc]: /O2 /LD /TC /Gy
 * BUILD_FLAGS[gcc(mingw)]: -O2 -shared -fPIC -mwindows
 */

#ifndef _WIN32
/* agent.dll is Windows-only; keep compile_cmod.py's Linux job green */
int g_agent_windows_only;
#else

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

#if defined(_MSC_VER)
#  pragma comment(lib, "advapi32.lib")
#  define EXPORT __declspec(dllexport)
#else
#  define EXPORT __attribute__((visibility("default")))
#endif

#define MAX_LOG_MESSAGE       1024
#define MAX_EVENT_TEXT        2048
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
#define RING_DRAIN_PASSES       5

#ifndef AGENT_IDLE_GRACE_MS
#  define AGENT_IDLE_GRACE_MS 5000
#endif
#ifndef AGENT_BOOTSTRAP_EXIT_MS
#  define AGENT_BOOTSTRAP_EXIT_MS 180000
#endif

#define HOOK_AGENT_DLL "agent.dll"
#define HOOK_MODULE_NAME "hook.dll"
#define PAYLOAD_FILE "hook_payload.bin"

typedef int (*FnRemoteInject)(const char *target, const char *dll_path);
typedef const char *(*FnRemoteLastError)(void);

static FnRemoteInject g_inject = NULL;
static FnRemoteLastError g_lastErrorFn = NULL;
static char g_payloadPath[MAX_PATH] = {0};
static char g_targetProcess[HOOK_KEY_MAX] = "Growtopia.exe";

/* ------------------------------------------------------------------ */
/* text + queue plumbing (generic)                                     */

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
    char scratch[256];
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

static void AgentDebugFile(const char *message)
{
    static char path[MAX_PATH];
    static int pathReady = 0;
    if (!pathReady)
    {
        char self[MAX_PATH];
        HMODULE module = NULL;
        if (GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                               (LPCWSTR)&AgentDebugFile, &module) &&
            GetModuleFileNameA(module, self, (DWORD)sizeof(self)))
        {
            char *separator = strrchr(self, '\\');
            if (separator)
                *separator = 0;
            snprintf(path, sizeof(path), "%s\\agent_debug.log", separator ? self : ".");
        }
        else
        {
            snprintf(path, sizeof(path), "agent_debug.log");
        }
        pathReady = 1;
    }
    HANDLE file = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_ALWAYS,
                              FILE_ATTRIBUTE_NORMAL, NULL);
    if (file != INVALID_HANDLE_VALUE)
    {
        char line[MAX_LOG_MESSAGE + 32];
        ULONGLONG tick = GetTickCount64();
        int n = snprintf(line, sizeof(line), "[%10llu.%03llu] %s\r\n", tick / 1000, tick % 1000, message);
        if (n > 0)
        {
            DWORD written = 0;
            WriteFile(file, line, (DWORD)n, &written, NULL);
        }
        CloseHandle(file);
    }
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
    AgentDebugFile(message);
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

/* ------------------------------------------------------------------ */
/* remote state                                                        */

static DWORD g_gamePid = 0;
static HANDLE g_memoryProcess = NULL;
static uint64_t g_selfRemote = 0;
static uint32_t g_selfRva = 0;
static int g_selfRvaValid = 0;
static volatile LONG g_everHadClient = 0;
static ULONGLONG g_agentStartedAt = 0;

static struct HookRuntime g_runtime[HOOK_MAX];
static int g_runtimeValid = 0;
static CRITICAL_SECTION g_stateLock;
static volatile LONG g_stateLockReady = 0;
static uint32_t g_logLevel = HOOK_LOG_INFO;

static void InvalidateShimCaches(void)
{
    if (g_stateLockReady)
        EnterCriticalSection(&g_stateLock);
    g_selfRemote = 0;
    g_runtimeValid = 0;
    memset(g_runtime, 0, sizeof(g_runtime));
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
    const IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(image + dos->e_lfanew);
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
    if (size > 0 && size < 64 * 1024 * 1024 && (image = (uint8_t *)malloc((size_t)size)))
    {
        imageSize = fread(image, 1, (size_t)size, file);
        const IMAGE_DOS_HEADER *dos = (const IMAGE_DOS_HEADER *)image;
        if (imageSize > sizeof(IMAGE_DOS_HEADER) && dos->e_magic == IMAGE_DOS_SIGNATURE)
        {
            const IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(image + dos->e_lfanew);
            if ((const uint8_t *)nt + sizeof(*nt) <= image + imageSize && nt->Signature == IMAGE_NT_SIGNATURE &&
                nt->FileHeader.SizeOfOptionalHeader >= sizeof(IMAGE_OPTIONAL_HEADER64))
            {
                const IMAGE_OPTIONAL_HEADER64 *optional = &nt->OptionalHeader;
                const IMAGE_DATA_DIRECTORY *exported =
                    (optional->NumberOfRvaAndSizes > IMAGE_DIRECTORY_ENTRY_EXPORT)
                        ? &optional->DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT]
                        : NULL;
                if (exported && exported->VirtualAddress)
                {
                    uint32_t offset = RvaToFileOffset(image, imageSize, exported->VirtualAddress);
                    if (offset && offset + sizeof(IMAGE_EXPORT_DIRECTORY) <= imageSize)
                    {
                        const IMAGE_EXPORT_DIRECTORY *exports = (IMAGE_EXPORT_DIRECTORY *)(image + offset);
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

static int RefreshRuntime(void)
{
    if (!g_selfRvaValid)
    {
        if (g_payloadPath[0])
            g_selfRvaValid = ExportRvaFromFile(g_payloadPath, HOOK_EXPORT_NAME, &g_selfRva) && g_selfRva;
        if (!g_selfRvaValid)
            return 0;
    }
    if (!g_gamePid || !g_memoryProcess)
        return 0;

    if (!g_selfRemote)
    {
        HMODULE base = find_remote_module(g_gamePid, HOOK_MODULE_NAME);
        if (!base)
            return 0;
        g_selfRemote = (uint64_t)(uintptr_t)base + g_selfRva;
    }

    struct HookRuntime remote[HOOK_MAX];
    SIZE_T readBytes = 0;
    void *address = (void *)(uintptr_t)(g_selfRemote + offsetof(struct ShimShared, runtime));
    if (!ReadProcessMemory(g_memoryProcess, address, remote, sizeof(remote), &readBytes) ||
        readBytes != sizeof(remote))
        return 0;

    int32_t magic = 0;
    ReadProcessMemory(g_memoryProcess, (LPCVOID)(uintptr_t)(g_selfRemote + offsetof(struct ShimShared, magic)),
                      &magic, sizeof(magic), &readBytes);
    if (magic != (int32_t)HOOK_PROTOCOL_MAGIC)
        return 0;

    EnterCriticalSection(&g_stateLock);
    memcpy(g_runtime, remote, sizeof(remote));
    g_runtimeValid = 1;
    LeaveCriticalSection(&g_stateLock);
    return 1;
}

static int RemoteWrite(HANDLE process, uint64_t address, const void *data, size_t size)
{
    SIZE_T written = 0;
    return WriteProcessMemory(process, (LPVOID)(uintptr_t)address, data, size, &written) && written == size;
}

static int AgentWriteRuntimeField(int index, size_t fieldOffset, const void *data, size_t size)
{
    HANDLE process = OpenProcess(PROCESS_VM_OPERATION | PROCESS_VM_WRITE, FALSE, g_gamePid);
    if (!process)
    {
        AgentLog("[hook] cannot open %lu for a runtime write (err=%lu) -- is the game elevated above the agent?",
                 (unsigned long)g_gamePid, GetLastError());
        return 0;
    }
    uint64_t address = g_selfRemote + offsetof(struct ShimShared, runtime) +
                       sizeof(struct HookRuntime) * (size_t)index + fieldOffset;
    int ok = RemoteWrite(process, address, data, size);
    if (!ok)
        AgentLog("[hook] the runtime write at %llX failed (err=%lu)", (unsigned long long)address, GetLastError());
    CloseHandle(process);
    return ok;
}

static int FindRuntimeIndex(const char *key)
{
    for (int i = 0; i < (int)HOOK_MAX; i++)
    {
        if (g_runtime[i].key[0] && _stricmp(g_runtime[i].key, key) == 0)
            return i;
    }
    return -1;
}

/* ------------------------------------------------------------------ */
/* status + handshake                                                  */

static const char *StatusText(int32_t status)
{
    switch (status)
    {
    case HOOK_STATUS_PATCHED:
        return "patched";
    case HOOK_STATUS_READY:
        return "ready";
    default:
        return "missing";
    }
}

static void BuildStatusLine(struct TextBuffer *buffer)
{
    BufferAppendText(buffer, "DATA");

    uint64_t processId = 0;
    uint64_t imageBase = 0;
    uint64_t imageSize = 0;
    uint64_t dllBase = 0;
    uint64_t bootTick = 0;

    EnterCriticalSection(&g_stateLock);
    int valid = g_runtimeValid;
    struct HookRuntime local[HOOK_MAX];
    if (valid)
        memcpy(local, g_runtime, sizeof(local));
    LeaveCriticalSection(&g_stateLock);

    if (valid && g_memoryProcess)
    {
        uint8_t head[64];
        SIZE_T got = 0;
        if (ReadProcessMemory(g_memoryProcess, (LPCVOID)(uintptr_t)g_selfRemote, head, sizeof(head), &got) &&
            got == sizeof(head))
        {
            memcpy(&processId, head + offsetof(struct ShimShared, processId), 8);
            memcpy(&imageBase, head + offsetof(struct ShimShared, imageBase), 8);
            memcpy(&imageSize, head + offsetof(struct ShimShared, imageSize), 8);
            memcpy(&dllBase, head + offsetof(struct ShimShared, dllBase), 8);
            memcpy(&bootTick, head + offsetof(struct ShimShared, bootTick), 8);
        }
    }

    BufferAppendFormat(buffer, " pid=%lu", (unsigned long)processId);
    BufferAppendFormat(buffer, " image_base=0x%llX", (unsigned long long)imageBase);
    BufferAppendFormat(buffer, " image_size=0x%llX", (unsigned long long)imageSize);
    BufferAppendFormat(buffer, " dll_base=0x%llX", (unsigned long long)dllBase);
    ULONGLONG now = GetTickCount64();
    uint64_t uptime = (valid && bootTick && now >= bootTick) ? (uint64_t)(now - bootTick) : 0;
    BufferAppendFormat(buffer, " uptime_ms=%llu", (unsigned long long)uptime);
    BufferAppendFormat(buffer, " level=%u", (unsigned)g_logLevel);
    BufferAppendFormat(buffer, " target=%s", g_targetProcess);

    if (!valid)
        return;

    for (int i = 0; i < (int)HOOK_MAX; i++)
    {
        if (!local[i].key[0])
            continue;
        char flat[HOOK_KEY_MAX];
        CopyText(flat, sizeof(flat), local[i].key);
        ReplaceSpaces(flat);
        for (char *cursor = flat; *cursor; cursor++)
        {
            if (*cursor == '/')
                *cursor = '_';
        }
        BufferAppendFormat(buffer, " hook_%s=%s", flat, StatusText(local[i].status));
        BufferAppendFormat(buffer, " target_%s=0x%llX", flat, (unsigned long long)local[i].target);
        BufferAppendFormat(buffer, " hits_%s=%llu", flat, (unsigned long long)local[i].hits);
        BufferAppendFormat(buffer, " faults_%s=%llu", flat, (unsigned long long)local[i].faults);
        BufferAppendFormat(buffer, " enabled_%s=%d", flat, (int)local[i].enabled);
        BufferAppendFormat(buffer, " state_%s_0=%llu", flat, (unsigned long long)local[i].state[0]);
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

static int HexValue(char c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}

static int HexDecode(const char *text, uint8_t *out, size_t outSize)
{
    size_t count = 0;
    while (text[0] && text[1])
    {
        int high = HexValue(text[0]);
        int low = HexValue(text[1]);
        if (high < 0 || low < 0)
            return -1;
        if (count >= outSize)
            return -1;
        out[count++] = (uint8_t)((high << 4) | low);
        text += 2;
    }
    if (text[0])
        return -1;
    return (int)count;
}

static void BuildHandshake(struct HookHandshake *out)
{
    memset(out, 0, sizeof(*out));
    int valid;
    struct HookRuntime local[HOOK_MAX];
    EnterCriticalSection(&g_stateLock);
    valid = g_runtimeValid;
    if (valid)
        memcpy(local, g_runtime, sizeof(local));
    LeaveCriticalSection(&g_stateLock);
    if (!valid)
        return;

    SIZE_T got = 0;
    uint8_t head[64];
    if (g_memoryProcess && ReadProcessMemory(g_memoryProcess, (LPCVOID)(uintptr_t)g_selfRemote, head, sizeof(head), &got) &&
        got == sizeof(head))
    {
        memcpy(&out->processId, head + offsetof(struct ShimShared, processId), 8);
        memcpy(&out->imageBase, head + offsetof(struct ShimShared, imageBase), 8);
        memcpy(&out->imageSize, head + offsetof(struct ShimShared, imageSize), 8);
        memcpy(&out->dllBase, head + offsetof(struct ShimShared, dllBase), 8);
    }
    out->magic = HOOK_PROTOCOL_MAGIC;
    out->version = HOOK_PROTOCOL_VERSION;

    uint32_t count = 0;
    for (int i = 0; i < (int)HOOK_MAX; i++)
    {
        if (!local[i].key[0] || local[i].status == HOOK_STATUS_MISSING)
            continue;
        struct HookHandshakeEntry *entry = &out->entries[count++];
        CopyText(entry->key, sizeof(entry->key), local[i].key);
        entry->status = local[i].status;
        entry->index = (uint32_t)i;
        entry->target = local[i].target;
        entry->trampoline = local[i].trampoline;
    }
    out->descriptorCount = count;
}

/* ------------------------------------------------------------------ */
/* pipe commands                                                       */

static void HandlePing(HANDLE pipe)
{
    WritePipeLine(pipe, "OK pong");
}

static void HandleStatus(HANDLE pipe)
{
    struct TextBuffer status;
    memset(&status, 0, sizeof(status));
    BuildStatusLine(&status);
    WritePipeLine(pipe, status.data ? status.data : "DATA");
    BufferFree(&status);
}

static void HandleHooks(HANDLE pipe)
{
    struct TextBuffer text;
    memset(&text, 0, sizeof(text));
    BufferAppendText(&text, "DATA");

    EnterCriticalSection(&g_stateLock);
    int valid = g_runtimeValid;
    struct HookRuntime local[HOOK_MAX];
    if (valid)
        memcpy(local, g_runtime, sizeof(local));
    LeaveCriticalSection(&g_stateLock);

    if (valid)
    {
        for (int i = 0; i < (int)HOOK_MAX; i++)
        {
            if (!local[i].key[0])
                continue;
            BufferAppendFormat(&text, " %s:%d:%d:%d:%llu", local[i].key, (int)local[i].status, (int)local[i].enabled,
                               (int)local[i].hits, (unsigned long long)local[i].state[0]);
        }
    }
    WritePipeLine(pipe, text.data ? text.data : "DATA");
    BufferFree(&text);
}

static void HandleHandshake(HANDLE pipe)
{
    int valid;
    EnterCriticalSection(&g_stateLock);
    valid = g_runtimeValid;
    LeaveCriticalSection(&g_stateLock);
    if (!valid)
    {
        WritePipeLine(pipe, "ERR the hooks are not installed yet");
        return;
    }
    struct HookHandshake handshake;
    BuildHandshake(&handshake);
    char hex[sizeof(handshake) * 2 + 2];
    HexEncode((const uint8_t *)&handshake, sizeof(handshake), hex, sizeof(hex));
    struct TextBuffer reply;
    memset(&reply, 0, sizeof(reply));
    BufferAppendText(&reply, "HANDSHAKE ");
    BufferAppendText(&reply, hex);
    WritePipeLine(pipe, reply.data ? reply.data : "HANDSHAKE");
    BufferFree(&reply);
}

static void HandleEnable(HANDLE pipe, const char *argument)
{
    char key[HOOK_KEY_MAX];
    int value = -1;
    if (sscanf(argument, "%31s %d", key, &value) != 2 || (value != 0 && value != 1))
    {
        WritePipeLine(pipe, "ERR usage: ENABLE <key> <0|1>");
        return;
    }
    EnterCriticalSection(&g_stateLock);
    int index = g_runtimeValid ? FindRuntimeIndex(key) : -1;
    LeaveCriticalSection(&g_stateLock);
    if (index < 0)
    {
        WritePipeLine(pipe, "ERR unknown key");
        return;
    }
    int32_t enabled = (int32_t)value;
    if (!AgentWriteRuntimeField(index, offsetof(struct HookRuntime, enabled), &enabled, sizeof(enabled)))
    {
        WritePipeLine(pipe, "ERR write failed");
        return;
    }
    WritePipeLine(pipe, "OK");
}

static void HandleState(HANDLE pipe, const char *argument)
{
    char key[HOOK_KEY_MAX];
    int slot = -1;
    unsigned long long value = 0;
    if (sscanf(argument, "%31s %d %llu", key, &slot, &value) != 3 || slot < 0 || slot >= (int)HOOK_STATE_SLOTS)
    {
        WritePipeLine(pipe, "ERR usage: STATE <key> <slot 0..7> <u64>");
        return;
    }
    EnterCriticalSection(&g_stateLock);
    int index = g_runtimeValid ? FindRuntimeIndex(key) : -1;
    LeaveCriticalSection(&g_stateLock);
    if (index < 0)
    {
        WritePipeLine(pipe, "ERR unknown key");
        return;
    }
    uint64_t number = (uint64_t)value;
    if (!AgentWriteRuntimeField(index, offsetof(struct HookRuntime, state) + sizeof(uint64_t) * (size_t)slot,
                                &number, sizeof(number)))
    {
        WritePipeLine(pipe, "ERR write failed");
        return;
    }
    WritePipeLine(pipe, "OK");
}

static void HandleData(HANDLE pipe, const char *argument)
{
    char key[HOOK_KEY_MAX];
    long offset = -1;
    char hexText[MAX_PIPE_LINE];
    if (sscanf(argument, "%31s %ld %4095s", key, &offset, hexText) != 3 || offset < 0 || offset >= (int)HOOK_DATA_MAX)
    {
        WritePipeLine(pipe, "ERR usage: DATA <key> <offset> <hex>");
        return;
    }
    uint8_t bytes[HOOK_DATA_MAX];
    int length = HexDecode(hexText, bytes, HOOK_DATA_MAX);
    if (length < 0 || offset + length > (int)HOOK_DATA_MAX)
    {
        WritePipeLine(pipe, "ERR bad hex or out of range");
        return;
    }
    EnterCriticalSection(&g_stateLock);
    int index = g_runtimeValid ? FindRuntimeIndex(key) : -1;
    LeaveCriticalSection(&g_stateLock);
    if (index < 0)
    {
        WritePipeLine(pipe, "ERR unknown key");
        return;
    }
    if (!AgentWriteRuntimeField(index, offsetof(struct HookRuntime, data) + (size_t)offset, bytes, (size_t)length))
    {
        WritePipeLine(pipe, "ERR write failed");
        return;
    }
    WritePipeLine(pipe, "OK");
}

static void HandleLogLevel(HANDLE pipe, const char *argument)
{
    int level = atoi(argument);
    if (level < 0 || level > 2)
    {
        WritePipeLine(pipe, "ERR usage: LOGLEVEL <0|1|2>");
        return;
    }
    g_logLevel = (uint32_t)level;
    WritePipeLine(pipe, "OK");
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
        HandlePing(pipe);
        return 0;
    }
    if (_stricmp(command, "QUIT") == 0)
    {
        WritePipeLine(pipe, "OK bye");
        return -1;
    }
    if (_stricmp(command, "STATUS") == 0)
    {
        HandleStatus(pipe);
        return 0;
    }
    if (_stricmp(command, "HOOKS") == 0)
    {
        HandleHooks(pipe);
        return 0;
    }
    if (_stricmp(command, "HANDSHAKE") == 0)
    {
        HandleHandshake(pipe);
        return 0;
    }
    if (_stricmp(command, "ENABLE") == 0)
    {
        HandleEnable(pipe, argument);
        return 0;
    }
    if (_stricmp(command, "STATE") == 0)
    {
        HandleState(pipe, argument);
        return 0;
    }
    if (_stricmp(command, "DATA") == 0)
    {
        HandleData(pipe, argument);
        return 0;
    }
    if (_stricmp(command, "LOGLEVEL") == 0)
    {
        HandleLogLevel(pipe, argument);
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

/* ------------------------------------------------------------------ */
/* event ring drain                                                    */

static LONG g_consumedTicket = 0;

static void PublishHookEvent(const struct HookEventSlot *slot)
{
    if (slot->hookIndex == HOOK_HOOK_INDEX_SYSTEM)
    {
        char text[HOOK_EVENT_MAX + 8];
        CopyText(text, sizeof(text), (const char *)slot->data);
        text[HOOK_EVENT_MAX] = 0;
        /* system diagnostics: honor the log level (slot->kind carries it) */
        if (slot->kind <= g_logLevel)
            QueueEvent("log", text);
        return;
    }

    const char *key = "?";
    char keyBuffer[HOOK_KEY_MAX];
    EnterCriticalSection(&g_stateLock);
    if (slot->hookIndex < HOOK_MAX && g_runtime[slot->hookIndex].key[0])
        CopyText(keyBuffer, sizeof(keyBuffer), g_runtime[slot->hookIndex].key);
    else
        CopyText(keyBuffer, sizeof(keyBuffer), "?");
    LeaveCriticalSection(&g_stateLock);
    key = keyBuffer;

    char hex[HOOK_EVENT_MAX * 2 + 4];
    HexEncode(slot->data, slot->size, hex, sizeof(hex));

    char text[MAX_EVENT_TEXT];
    int written = snprintf(text, sizeof(text), "hook %s %u %s", key, slot->kind, hex);
    if (written <= 0)
        return;
    QueueEvent("hook", text);
}

static void DrainEventRing(void)
{
    if (!g_memoryProcess || !g_selfRemote || !g_runtimeValid)
        return;

    uint64_t ticket = 0;
    SIZE_T got = 0;
    if (!ReadProcessMemory(g_memoryProcess, (LPCVOID)(uintptr_t)(g_selfRemote + offsetof(struct ShimShared, eventTicket)),
                           &ticket, sizeof(ticket), &got) || got != sizeof(ticket))
        return;
    LONG remoteTicket = (LONG)ticket;
    LONG oldest = remoteTicket - HOOK_EVENT_SLOTS;
    if (g_consumedTicket < oldest)
        g_consumedTicket = oldest;
    if (g_consumedTicket >= remoteTicket)
        return;

    struct HookEventSlot slots[HOOK_EVENT_SLOTS];
    if (!ReadProcessMemory(g_memoryProcess, (LPCVOID)(uintptr_t)(g_selfRemote + offsetof(struct ShimShared, events)),
                           slots, sizeof(slots), &got) || got != sizeof(slots))
        return;

    for (LONG sequence = g_consumedTicket; sequence < remoteTicket; sequence++)
    {
        const struct HookEventSlot *slot = &slots[(size_t)((ULONG)sequence % HOOK_EVENT_SLOTS)];
        if (slot->state != HOOK_SLOT_READY)
            continue;
        if (slot->sequence != sequence)
            continue;
        PublishHookEvent(slot);
    }

    g_consumedTicket = remoteTicket;
}

/* ------------------------------------------------------------------ */
/* target monitor + lifecycle                                          */

static HANDLE g_targetHandle = NULL;
static ULONGLONG g_lastFailLog = 0;
static int g_patchedAnnounced = 0;

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

/*
 * First matching process the injector can actually work on: an elevated copy
 * of the game (or any pid we cannot open) must not block a hookable instance.
 */
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
            if (_stricmp(entry.szExeFile, target) != 0)
                continue;
            if (PidIsHooked(entry.th32ProcessID))
            {
                pid = entry.th32ProcessID; /* already hooked: adopt this one */
                break;
            }
            HANDLE probe = OpenProcess(PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION |
                                           PROCESS_VM_WRITE | PROCESS_VM_READ,
                                       FALSE, entry.th32ProcessID);
            if (!probe)
                continue; /* cannot inject this instance (elevated?), try the next */
            CloseHandle(probe);
            pid = entry.th32ProcessID;
            break;
        } while (Process32Next(snapshot, &entry));
    }
    CloseHandle(snapshot);

    return pid;
}

static void AdoptPid(DWORD pid)
{
    g_gamePid = pid;
    InvalidateShimCaches();
    EnsureMemoryProcess(pid);
}

static void WatchStatuses(void)
{
    if (!g_runtimeValid || g_patchedAnnounced)
        return;

    for (int i = 0; i < (int)HOOK_MAX; i++)
    {
        if (g_runtime[i].status == HOOK_STATUS_PATCHED)
        {
            g_patchedAnnounced = 1;
            AgentLog("[hook] the entry points are patched, the hook is live");
            return;
        }
    }
}

static void MonitorTarget(void)
{
    if (g_targetHandle)
    {
        if (WaitForSingleObject(g_targetHandle, 0) == WAIT_OBJECT_0)
        {
            DWORD code = 0;
            GetExitCodeProcess(g_targetHandle, &code);
            CloseHandle(g_targetHandle);
            g_targetHandle = NULL;
            ForgetTarget();
            g_patchedAnnounced = 0;
            if (code & 0x80000000)
                AgentLog("[hook] %s exited with status 0x%08lX", g_targetProcess, (unsigned long)code);
        }
        return;
    }

    if (g_gamePid)
    {
        if (PidIsHooked(g_gamePid))
            return;
        ForgetTarget();
        g_patchedAnnounced = 0;
    }

    static ULONGLONG lastHunt = 0;
    ULONGLONG now = GetTickCount64();
    if (lastHunt && now - lastHunt < TARGET_HUNT_INTERVAL_MS)
        return;
    lastHunt = now;

    DWORD pid = FindTargetPid(g_targetProcess);
    if (!pid)
        return;

    if (PidIsHooked(pid))
    {
        AdoptPid(pid);
        g_targetHandle = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
        return;
    }

    if (!g_inject)
    {
        if (now - g_lastFailLog > TARGET_FAIL_LOG_MS || !g_lastFailLog)
        {
            g_lastFailLog = now;
            AgentLog("[hook] the injector is unavailable, cannot hook %s", g_targetProcess);
        }
        return;
    }

    int rc = g_inject(g_targetProcess, g_payloadPath);
    if (rc == 0 || rc == -1)
    {
        for (int i = 0; i < PID_MUTEX_WAIT_TRIES && !PidIsHooked(pid); i++)
            Sleep(PID_MUTEX_WAIT_STEP_MS);
        AdoptPid(pid);
        g_targetHandle = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
        AgentLog("[hook] %s is hooked (pid %lu)", g_targetProcess, (unsigned long)pid);
    }
    else
    {
        if (now - g_lastFailLog > TARGET_FAIL_LOG_MS || !g_lastFailLog)
        {
            g_lastFailLog = now;
            const char *failure = g_lastErrorFn ? g_lastErrorFn() : NULL;
            AgentLog("[hook] agent: %s (rc=%d: %s)", g_targetProcess, rc, failure ? failure : "unknown");
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
    if (FindTargetPid(g_targetProcess))
        return;

    if (!InterlockedCompareExchange(&g_everHadClient, 0, 0) && now - g_agentStartedAt < AGENT_BOOTSTRAP_EXIT_MS)
        return;

    AgentLog("[agent] the client and %s are both gone, terminating", g_targetProcess);
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

    /* the payload names the target process; without it there is nothing to do */
    char payloadFile[MAX_PATH];
    snprintf(payloadFile, sizeof(payloadFile), "%s\\%s", agentDirectory, PAYLOAD_FILE);
    FILE *file = fopen(payloadFile, "rb");
    if (file)
    {
        uint8_t head[64];
        size_t got = fread(head, 1, sizeof(head), file);
        fclose(file);
        if (got >= 64)
        {
            uint32_t magic, version, count, reserved0, allowAny, reserved1, payloadBytes;
            char target[HOOK_KEY_MAX];
            memcpy(&magic, head + 0, 4);
            memcpy(&version, head + 4, 4);
            memcpy(&count, head + 8, 4);
            memcpy(&reserved0, head + 12, 4);
            memcpy(&allowAny, head + 16, 4);
            memcpy(&reserved1, head + 20, 4);
            memcpy(&payloadBytes, head + 24, 4);
            memcpy(target, head + 32, HOOK_KEY_MAX);
            (void)reserved0;
            (void)reserved1;
            (void)allowAny;
            if (magic == HOOK_PAYLOAD_MAGIC && version == HOOK_PROTOCOL_VERSION && payloadBytes >= 64)
            {
                target[HOOK_KEY_MAX - 1] = 0;
                if (target[0])
                    CopyText(g_targetProcess, sizeof(g_targetProcess), target);
            }
        }
    }

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

    AgentLog("[hook] agent: watching %s", g_targetProcess);
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
        RefreshRuntime();
        WatchStatuses();
        DrainEventRing();
        MaybeShutdown();
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

#endif /* _WIN32 */
