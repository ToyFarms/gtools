#define _CRT_SECURE_NO_WARNINGS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <errno.h>
#include <stdarg.h>
#include <stdbool.h>
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

#define HANDSHAKE_WAIT_TRIES 120
#define HANDSHAKE_WAIT_MS    250
#define PIPE_CONNECT_TIMEOUT 250

#define PIPE_LINE_MAX 4096

enum InjectResult
{
    INJECT_OK = 0,
    INJECT_ERR_ALREADY_INJECTED = -1,
    INJECT_ERR_BAD_ARGS = -2,
    INJECT_ERR_TARGET_NOT_FOUND = -3,
    INJECT_ERR_BAD_DLL_PATH = -4,
    INJECT_ERR_OPEN_PROCESS = -5,
    INJECT_ERR_ALLOCATE_REMOTE = -6,
    INJECT_ERR_WRITE_REMOTE = -7,
    INJECT_ERR_CREATE_REMOTE_THREAD = -8,
    INJECT_ERR_MODULE_NOT_FOUND = -9,
    INJECT_ERR_HANDSHAKE_MISSING = -10,
    INJECT_ERR_OPEN_PROCESS_PATCH = -11,
    INJECT_ERR_HANDSHAKE_INVALID = -12,
    INJECT_ERR_NO_HOOKS = -13,
};

static char g_lastError[1024] = {0};

static void set_error(const char *format, ...)
{
    va_list args;
    va_start(args, format);
    vsnprintf(g_lastError, sizeof(g_lastError), format, args);
    va_end(args);
}

static DWORD find_process_id(const char *executable)
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
            if (_stricmp(entry.szExeFile, executable) == 0)
            {
                pid = entry.th32ProcessID;
                break;
            }
        } while (Process32Next(snapshot, &entry));
    }
    CloseHandle(snapshot);

    return pid;
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

static const char *file_base_name(const char *path)
{
    const char *separator = strrchr(path, '\\');
    if (!separator)
        separator = strrchr(path, '/');

    return separator ? separator + 1 : path;
}

static HANDLE pipe_connect(DWORD timeoutMs)
{
    ULONGLONG deadline = GetTickCount64() + timeoutMs;
    for (;;)
    {
        HANDLE pipe = CreateFileA(HOOK_PIPE_NAME, GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING, 0, NULL);
        if (pipe != INVALID_HANDLE_VALUE)
            return pipe;

        DWORD error = GetLastError();
        if (error != ERROR_FILE_NOT_FOUND && error != ERROR_PIPE_BUSY)
            return INVALID_HANDLE_VALUE;
        if (GetTickCount64() >= deadline)
            return INVALID_HANDLE_VALUE;

        Sleep(50);
    }
}

struct PipeReader
{
    char buffer[PIPE_LINE_MAX * 2];
    size_t length;
    size_t position;
};

static bool pipe_read_line(HANDLE pipe, struct PipeReader *reader, char *out, size_t outSize)
{
    size_t position = 0;
    for (;;)
    {
        while (reader->position < reader->length)
        {
            char c = reader->buffer[reader->position++];
            if (c == '\n')
            {
                out[position] = 0;
                return true;
            }
            if (c == '\r' || c == '\0')
                continue;
            if (position + 1 < outSize)
                out[position++] = c;
        }
        reader->position = 0;
        reader->length = 0;

        DWORD readBytes = 0;
        if (!ReadFile(pipe, reader->buffer, (DWORD)sizeof(reader->buffer), &readBytes, NULL) || readBytes == 0)
            return false;

        reader->length += readBytes;
    }
}

static bool pipe_write_line(HANDLE pipe, const char *text)
{
    size_t length = strlen(text);
    char *line = (char *)malloc(length + 2);
    if (!line)
        return false;

    memcpy(line, text, length);
    line[length] = '\n';
    line[length + 1] = 0;

    DWORD writtenBytes = 0;
    bool ok = WriteFile(pipe, line, (DWORD)(length + 1), &writtenBytes, NULL) != FALSE;
    free(line);

    return ok;
}

static bool pipe_command(HANDLE pipe, const char *command, char *out, size_t outSize)
{
    struct PipeReader reader;
    memset(&reader, 0, sizeof(reader));

    if (!pipe_write_line(pipe, command))
        return false;

    char line[PIPE_LINE_MAX];
    for (;;)
    {
        if (!pipe_read_line(pipe, &reader, line, sizeof(line)))
            return false;

        if (strncmp(line, "EVENT ", 6) == 0)
            continue;

        if (outSize)
        {
            size_t length = strlen(line);
            if (length >= outSize)
                length = outSize - 1;
            memcpy(out, line, length);
            out[length] = 0;
        }

        return true;
    }
}

static int hex_value(char c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;

    return -1;
}

static bool hex_decode(const char *hex, uint8_t *out, size_t outSize)
{
    size_t length = strlen(hex);
    if (length % 2 != 0 || length / 2 > outSize)
        return false;

    for (size_t i = 0; i < length / 2; i++)
    {
        int high = hex_value(hex[i * 2]);
        int low = hex_value(hex[i * 2 + 1]);
        if (high < 0 || low < 0)
            return false;

        out[i] = (uint8_t)((high << 4) | low);
    }

    return true;
}

static bool fetch_handshake(uint64_t expected_dll_base, struct HookHandshake *out)
{
    for (int attempt = 0; attempt < HANDSHAKE_WAIT_TRIES; attempt++)
    {
        HANDLE pipe = pipe_connect(PIPE_CONNECT_TIMEOUT);
        if (pipe != INVALID_HANDLE_VALUE)
        {
            char reply[PIPE_LINE_MAX];
            bool got = pipe_command(pipe, "HANDSHAKE", reply, sizeof(reply)) &&
                       strncmp(reply, "HANDSHAKE ", 10) == 0;
            if (got)
                got = hex_decode(reply + 10, (uint8_t *)out, sizeof(*out));
            CloseHandle(pipe);

            if (got && out->magic == HOOK_PROTOCOL_MAGIC && out->version == HOOK_PROTOCOL_VERSION &&
                out->entryCount <= HOOK_MAX_ENTRIES && (!expected_dll_base || out->dllBase == expected_dll_base))
                return true;
        }
        Sleep(HANDSHAKE_WAIT_MS);
    }

    return false;
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

static HANDLE g_process = NULL;
static DWORD g_processId = 0;
static HMODULE g_remoteModule = NULL;
static struct HookEntry g_patchedEntries[HOOK_MAX_ENTRIES];
static unsigned char g_originalBytes[HOOK_MAX_ENTRIES][HOOK_ENTRY_PATCH_BYTES];
static int g_patchedCount = 0;
static bool g_injected = false;

EXPORT int inject(const char *target, const char *dll_path)
{
    if (g_injected)
    {
        set_error("already injected");
        return INJECT_ERR_ALREADY_INJECTED;
    }
    if (!target || !dll_path)
    {
        set_error("bad args");
        return INJECT_ERR_BAD_ARGS;
    }

    /* the target is either a process id or an executable name */
    DWORD pid = 0;
    char *end = NULL;
    errno = 0;
    long parsed = strtol(target, &end, 10);
    if (end && *end == '\0' && parsed > 0 && errno == 0)
        pid = (DWORD)parsed;
    else
        pid = find_process_id(target);
    if (!pid)
    {
        set_error("process not found: %s", target);
        return INJECT_ERR_TARGET_NOT_FOUND;
    }

    char fullPath[MAX_PATH];
    memset(fullPath, 0, sizeof(fullPath));
    DWORD pathLength = GetFullPathNameA(dll_path, MAX_PATH, fullPath, NULL);
    if (pathLength == 0 || pathLength >= MAX_PATH)
    {
        set_error("bad dll path");
        return INJECT_ERR_BAD_DLL_PATH;
    }

    HANDLE process = OpenProcess(PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION |
                                     PROCESS_VM_WRITE | PROCESS_VM_READ,
                                 FALSE, pid);
    if (!process)
    {
        set_error("OpenProcess failed %lu", GetLastError());
        return INJECT_ERR_OPEN_PROCESS;
    }

    /* load the dll inside the target */
    size_t pathBytes = strlen(fullPath) + 1;
    LPVOID remote = VirtualAllocEx(process, NULL, pathBytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!remote)
    {
        set_error("VirtualAllocEx failed %lu", GetLastError());
        CloseHandle(process);
        return INJECT_ERR_ALLOCATE_REMOTE;
    }
    if (!WriteProcessMemory(process, remote, fullPath, pathBytes, NULL))
    {
        set_error("WriteProcessMemory failed %lu", GetLastError());
        VirtualFreeEx(process, remote, 0, MEM_RELEASE);
        CloseHandle(process);
        return INJECT_ERR_WRITE_REMOTE;
    }

    FARPROC loadLibrary = GetProcAddress(GetModuleHandleA("kernel32.dll"), "LoadLibraryA");
    HANDLE thread = CreateRemoteThread(process, NULL, 0, (LPTHREAD_START_ROUTINE)loadLibrary, remote, 0, NULL);
    if (!thread)
    {
        set_error("CreateRemoteThread failed %lu", GetLastError());
        VirtualFreeEx(process, remote, 0, MEM_RELEASE);
        CloseHandle(process);
        return INJECT_ERR_CREATE_REMOTE_THREAD;
    }
    WaitForSingleObject(thread, 10000);
    DWORD exitCode = 0;
    GetExitCodeThread(thread, &exitCode);
    CloseHandle(thread);
    VirtualFreeEx(process, remote, 0, MEM_RELEASE);

    HMODULE remoteModule = find_remote_module(pid, file_base_name(fullPath));
    if (!remoteModule)
    {
        set_error("the dll is not loaded in the target");
        CloseHandle(process);
        return INJECT_ERR_MODULE_NOT_FOUND;
    }

    /* the dll publishes the functions it wants patched over its pipe */
    struct HookHandshake handshake;
    memset(&handshake, 0, sizeof(handshake));
    if (!fetch_handshake((uint64_t)(uintptr_t)remoteModule, &handshake))
    {
        set_error("the dll never published its handshake");
        CloseHandle(process);
        return INJECT_ERR_HANDSHAKE_MISSING;
    }
    if (handshake.entryCount == 0)
    {
        set_error("the dll did not find any hook to install");
        CloseHandle(process);
        return INJECT_ERR_NO_HOOKS;
    }

    HANDLE patchProcess = OpenProcess(PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ |
                                          PROCESS_QUERY_INFORMATION,
                                      FALSE, pid);
    if (!patchProcess)
    {
        set_error("OpenProcess for patching failed %lu", GetLastError());
        CloseHandle(process);
        return INJECT_ERR_OPEN_PROCESS_PATCH;
    }

    g_patchedCount = 0;
    for (uint32_t i = 0; i < handshake.entryCount && i < HOOK_MAX_ENTRIES; i++)
    {
        const struct HookEntry *entry = &handshake.entries[i];
        if (!entry->target || !entry->detour)
            continue;
        if (entry->entryPatchBytes != HOOK_ENTRY_PATCH_BYTES)
        {
            set_error("%s expects a %u byte patch but only %d bytes are supported", entry->name,
                      entry->entryPatchBytes, HOOK_ENTRY_PATCH_BYTES);
            continue;
        }

        int slot = g_patchedCount;
        SIZE_T readBytes = 0;
        if (!ReadProcessMemory(patchProcess, (void *)entry->target, g_originalBytes[slot], HOOK_ENTRY_PATCH_BYTES,
                               &readBytes) ||
            readBytes != HOOK_ENTRY_PATCH_BYTES)
        {
            set_error("cannot read the original bytes of %s", entry->name);
            continue;
        }

        unsigned char patch[HOOK_ENTRY_PATCH_BYTES];
        write_abs_jump(patch, entry->detour);

        DWORD oldProtection = 0;
        if (!VirtualProtectEx(patchProcess, (void *)entry->target, HOOK_ENTRY_PATCH_BYTES, PAGE_EXECUTE_READWRITE,
                               &oldProtection))
        {
            set_error("VirtualProtectEx failed for %s (%lu)", entry->name, GetLastError());
            continue;
        }

        SIZE_T written = 0;
        bool patched = WriteProcessMemory(patchProcess, (void *)entry->target, patch, HOOK_ENTRY_PATCH_BYTES, &written) &&
                       written == HOOK_ENTRY_PATCH_BYTES;
        DWORD ignored = 0;
        VirtualProtectEx(patchProcess, (void *)entry->target, HOOK_ENTRY_PATCH_BYTES, oldProtection, &ignored);

        if (!patched)
        {
            set_error("cannot patch %s", entry->name);
            continue;
        }

        g_patchedEntries[g_patchedCount++] = *entry;
    }

    g_process = patchProcess;
    g_processId = pid;
    g_remoteModule = remoteModule;
    g_injected = true;

    CloseHandle(process);

    if (g_patchedCount == 0)
    {
        set_error("no hook could be patched");
        return INJECT_ERR_NO_HOOKS;
    }

    set_error("ok");
    return INJECT_OK;
}

EXPORT int cleanup(void)
{
    if (!g_injected)
    {
        set_error("not injected");
        return INJECT_ERR_ALREADY_INJECTED;
    }

    if (g_process)
    {
        for (int i = 0; i < g_patchedCount; i++)
        {
            const struct HookEntry *entry = &g_patchedEntries[i];
            DWORD oldProtection = 0;
            if (!VirtualProtectEx(g_process, (void *)entry->target, HOOK_ENTRY_PATCH_BYTES, PAGE_EXECUTE_READWRITE,
                                   &oldProtection))
                continue;
            SIZE_T written = 0;
            WriteProcessMemory(g_process, (void *)entry->target, g_originalBytes[i], HOOK_ENTRY_PATCH_BYTES, &written);
            DWORD ignored = 0;
            VirtualProtectEx(g_process, (void *)entry->target, HOOK_ENTRY_PATCH_BYTES, oldProtection, &ignored);
        }
        g_patchedCount = 0;

        if (g_remoteModule)
        {
            FARPROC freeLibrary = GetProcAddress(GetModuleHandleA("kernel32.dll"), "FreeLibrary");
            HANDLE thread =
                CreateRemoteThread(g_process, NULL, 0, (LPTHREAD_START_ROUTINE)freeLibrary, (LPVOID)g_remoteModule, 0,
                                   NULL);
            if (thread)
            {
                WaitForSingleObject(thread, 5000);
                CloseHandle(thread);
            }
        }
        CloseHandle(g_process);
        g_process = NULL;
    }

    g_injected = false;
    g_processId = 0;
    g_remoteModule = NULL;
    set_error("ok");
    return INJECT_OK;
}

EXPORT const char *last_error(void)
{
    return g_lastError;
}
