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

#define SHIM_WAIT_GRACE_MS   30000
#define SECTION_WAIT_STEP_MS 100

#define SCAN_CHUNK (1u << 20)
#define PATTERN_MAX 512

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
    INJECT_ERR_SECTION_MISSING = -14,
    INJECT_ERR_SECTION_INVALID = -15,
    INJECT_ERR_LOCK_TIMEOUT = -16,
};

static char g_lastError[1024] = {0};

static void CopyText(char *destination, size_t destinationSize, const char *source);

static void set_error(const char *format, ...)
{
    va_list args;
    va_start(args, format);
    vsnprintf(g_lastError, sizeof(g_lastError), format, args);
    va_end(args);
}

/* ---------- process and module discovery ---------- */

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

/* byte signatures live here, the identity table in hook_protocol.h carries
   the names, keys and stolen byte counts */
static const char *g_signatures[HOOK_INDEX_COUNT] = {
    "48 89 4C 24 08 48 89 54 24 10 4C 89 44 24 18 4C 89 4C 24 20 53 57 B8 88 10 00 00 E8 ?? ?? ?? ?? 48 2B E0 48 8B "
    "05 ?? ?? ?? ?? 48 33 C4 48 89 84 24 70 10 00 00 48 8B D9 33 D2 48 8D 4C 24 70 41",
    "48 89 4C 24 08 48 89 54 24 10 4C 89 44 24 18 4C 89 4C 24 20 53 57 B8 68 28 00 00 E8 ?? ?? ?? ?? 48 2B E0 48 8B "
    "05 ?? ?? ?? ?? 48 33 C4 48 89 84 24 50 28 00 00 48 8B D9 33 D2 48 8D 4C 24 40 41",
    "40 55 56 48 83 EC 28 81 BA ?? ?? ?? ?? C8 00 00 00 48 8B EA 48 8B 41 08 48 8B F1 75 1D C7 80 ?? ?? ?? ?? 00 "
    "00 00 00",
    "40 55 53 56 57 41 54 41 55 41 56 41 57 48 8D AC 24 48 FD FF FF 48 81 EC B8 03 00 00 48 8B 05 ?? ?? ?? ?? 48 "
    "33 C4 48 89 85 A0 02 00 00 4C 89 4C 24 40 45 8B E0 4C 8B FA 4C 8B E9",
};

/* ---------- shared section ---------- */

static HANDLE g_sectionMapping = NULL;
static struct HookShared *g_section = NULL;

static void CloseSection(void)
{
    if (g_section)
    {
        UnmapViewOfFile(g_section);
        g_section = NULL;
    }
    if (g_sectionMapping)
    {
        CloseHandle(g_sectionMapping);
        g_sectionMapping = NULL;
    }
}

static int OpenSection(void)
{
    if (g_section)
        return 1;

    HANDLE mapping = OpenFileMappingA(FILE_MAP_ALL_ACCESS, FALSE, HOOK_SECTION_NAME);
    if (!mapping)
        return 0;

    void *view = MapViewOfFile(mapping, FILE_MAP_ALL_ACCESS, 0, 0, 0);
    if (!view)
    {
        CloseHandle(mapping);
        return 0;
    }

    g_sectionMapping = mapping;
    g_section = (struct HookShared *)view;
    return 1;
}

/* wait for the agent to create the section and the shim to publish everything;
   the shim honors start_delay_ms before it publishes, so the wait scales */
static int WaitShimPublished(void)
{
    ULONGLONG deadline = GetTickCount64() + SHIM_WAIT_GRACE_MS;
    for (;;)
    {
        if (!g_section)
        {
            if (!OpenSection())
            {
                if (GetTickCount64() >= deadline)
                    return 0;
                Sleep(SECTION_WAIT_STEP_MS);
                continue;
            }
            if (g_section->magic != HOOK_PROTOCOL_MAGIC || g_section->version != HOOK_PROTOCOL_VERSION)
            {
                set_error("the shared section has a foreign version");
                CloseSection();
                return 0;
            }
            int delayMs = g_section->settings.startDelayMs;
            if (delayMs > 0)
                deadline += (ULONGLONG)delayMs;
        }
        if (InterlockedCompareExchange(&g_section->ready, 0, 0) == 1)
            return 1;
        if (GetTickCount64() >= deadline)
            return 0;
        Sleep(SECTION_WAIT_STEP_MS);
    }
}

/* ---------- cross process serialization ---------- */

static int ProcessIsHooked(DWORD pid)
{
    char name[64];
    snprintf(name, sizeof(name), "%s%lu", HOOK_PID_MUTEX_PREFIX, (unsigned long)pid);
    HANDLE existing = OpenMutexA(SYNCHRONIZE, FALSE, name);
    if (!existing)
        return 0;
    CloseHandle(existing);
    return 1;
}

static HANDLE AcquireHookLock(DWORD pid)
{
    char name[64];
    snprintf(name, sizeof(name), "%s%lu", HOOK_LOCK_MUTEX_PREFIX, (unsigned long)pid);

    HANDLE mutex = CreateMutexA(NULL, TRUE, name);
    if (!mutex)
        return NULL;

    DWORD wait = WaitForSingleObject(mutex, 15000);
    if (wait != WAIT_OBJECT_0 && wait != WAIT_ABANDONED)
    {
        CloseHandle(mutex);
        return NULL;
    }
    return mutex;
}

static void ReleaseHookLock(HANDLE mutex)
{
    if (!mutex)
        return;
    ReleaseMutex(mutex);
    CloseHandle(mutex);
}

/* ---------- signature scanning (remote) ---------- */

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

/* scan the target image through ReadProcessMemory, chunk by chunk; every
   start position is examined exactly once and cross chunk boundaries are
   handled by re reading a small overlap */
static uint8_t *ScanSignature(HANDLE process, uint8_t *base, size_t size, const struct PatternBytes *pattern,
                              int *matchCount)
{
    if (matchCount)
        *matchCount = 0;
    if (!base || !size || pattern->length == 0 || pattern->length > SCAN_CHUNK)
        return NULL;

    uint8_t *buffer = (uint8_t *)malloc(SCAN_CHUNK + pattern->length);
    if (!buffer)
        return NULL;

    uint8_t *found = NULL;
    int matches = 0;
    size_t offset = 0;

    while (offset + pattern->length <= size)
    {
        size_t chunkSize = SCAN_CHUNK;
        if (offset + chunkSize > size)
            chunkSize = size - offset;

        SIZE_T readBytes = 0;
        if (!ReadProcessMemory(process, base + offset, buffer, chunkSize, &readBytes) || readBytes == 0)
            break;
        size_t have = readBytes;
        if (have < pattern->length)
            break;

        for (size_t i = 0; i + pattern->length <= have; i++)
        {
            if (!PatternMatches(buffer + i, pattern))
                continue;
            matches++;
            if (!found)
                found = base + offset + i;
            if (matches > 1)
                break;
        }
        if (matchCount)
            *matchCount = matches;
        if (matches > 1)
            break;

        if (offset + have >= size)
            break;
        /* keep a tail overlap so patterns starting at the chunk edge are seen */
        offset += have - (pattern->length - 1);
    }

    free(buffer);
    if (matchCount)
        *matchCount = matches;

    return matches == 1 ? found : NULL;
}

/* ---------- patching (remote) ---------- */

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

static uint8_t *BuildRemoteTrampoline(HANDLE process, uint8_t *target, uint32_t stolenBytes, int *promoted)
{
    size_t total = (size_t)stolenBytes + HOOK_ENTRY_PATCH_BYTES;
    *promoted = 0;

    LPVOID remote = VirtualAllocEx(process, NULL, total, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!remote)
    {
        DWORD error = GetLastError();
        remote = VirtualAllocEx(process, NULL, total, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (!remote)
        {
            set_error("VirtualAllocEx failed %lu", error);
            return NULL;
        }
        *promoted = 1;
    }

    unsigned char code[512];
    if (total > sizeof(code))
    {
        set_error("the trampoline is unexpectedly large");
        VirtualFreeEx(process, remote, 0, MEM_RELEASE);
        return NULL;
    }

    SIZE_T readBytes = 0;
    if (!ReadProcessMemory(process, target, code, stolenBytes, &readBytes) || readBytes != stolenBytes)
    {
        set_error("cannot read the %u stolen bytes of the trampoline", stolenBytes);
        VirtualFreeEx(process, remote, 0, MEM_RELEASE);
        return NULL;
    }
    write_abs_jump(code + stolenBytes, (uint64_t)(uintptr_t)target + stolenBytes);

    SIZE_T written = 0;
    if (!WriteProcessMemory(process, remote, code, total, &written) || written != total)
    {
        set_error("cannot write the trampoline (%lu)", GetLastError());
        VirtualFreeEx(process, remote, 0, MEM_RELEASE);
        return NULL;
    }

    if (*promoted)
    {
        DWORD old = 0;
        if (!VirtualProtectEx(process, remote, total, PAGE_EXECUTE_READ, &old))
        {
            set_error("cannot make the trampoline executable (%lu)", GetLastError());
            VirtualFreeEx(process, remote, 0, MEM_RELEASE);
            return NULL;
        }
    }

    FlushInstructionCache(process, remote, total);
    return (uint8_t *)remote;
}

static int PatchEntry(HANDLE process, struct HookEntry *entry, const struct HookIdentity *identity)
{
    uint8_t *target = (uint8_t *)(uintptr_t)entry->target;

    unsigned char original[HOOK_ENTRY_PATCH_BYTES];
    SIZE_T readBytes = 0;
    if (!ReadProcessMemory(process, target, original, HOOK_ENTRY_PATCH_BYTES, &readBytes) ||
        readBytes != HOOK_ENTRY_PATCH_BYTES)
    {
        set_error("cannot read the original bytes of %s", identity->name);
        return 0;
    }

    unsigned char patch[HOOK_ENTRY_PATCH_BYTES];
    write_abs_jump(patch, entry->detour);

    DWORD oldProtection = 0;
    if (!VirtualProtectEx(process, target, HOOK_ENTRY_PATCH_BYTES, PAGE_EXECUTE_READWRITE, &oldProtection))
    {
        set_error("VirtualProtectEx failed for %s (%lu)", identity->name, GetLastError());
        return 0;
    }

    SIZE_T written = 0;
    bool patched = WriteProcessMemory(process, target, patch, HOOK_ENTRY_PATCH_BYTES, &written) &&
                   written == HOOK_ENTRY_PATCH_BYTES;
    DWORD ignored = 0;
    VirtualProtectEx(process, target, HOOK_ENTRY_PATCH_BYTES, oldProtection, &ignored);
    if (!patched)
    {
        set_error("cannot patch %s", identity->name);
        return 0;
    }

    unsigned char verify[HOOK_ENTRY_PATCH_BYTES];
    readBytes = 0;
    if (!ReadProcessMemory(process, target, verify, HOOK_ENTRY_PATCH_BYTES, &readBytes) ||
        readBytes != HOOK_ENTRY_PATCH_BYTES || verify[0] != 0xFF || verify[1] != 0x25 ||
        memcmp(verify + 6, &entry->detour, sizeof(entry->detour)) != 0)
    {
        set_error("%s: the patch did not verify", identity->name);
        return 0;
    }

    return 1;
}

/* ---------- injector state ---------- */

static HANDLE g_process = NULL;
static DWORD g_processId = 0;
static HMODULE g_remoteModule = NULL;
static uint64_t g_trampolineSlots[HOOK_MAX_ENTRIES];
static int g_patchedCount = 0;
static bool g_injected = false;

static void ResetState(void)
{
    if (g_process)
    {
        CloseHandle(g_process);
        g_process = NULL;
    }
    g_processId = 0;
    g_remoteModule = NULL;
    memset(g_trampolineSlots, 0, sizeof(g_trampolineSlots));
    g_patchedCount = 0;
    g_injected = false;
}

/* ---------- dll loading into the target ---------- */

static int LoadRemoteLibrary(HANDLE process, const char *fullPath)
{
    size_t pathBytes = strlen(fullPath) + 1;
    LPVOID remote = VirtualAllocEx(process, NULL, pathBytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!remote)
    {
        set_error("VirtualAllocEx failed %lu", GetLastError());
        return 0;
    }
    if (!WriteProcessMemory(process, remote, fullPath, pathBytes, NULL))
    {
        set_error("WriteProcessMemory failed %lu", GetLastError());
        VirtualFreeEx(process, remote, 0, MEM_RELEASE);
        return 0;
    }

    FARPROC loadLibrary = GetProcAddress(GetModuleHandleA("kernel32.dll"), "LoadLibraryA");
    HANDLE thread = CreateRemoteThread(process, NULL, 0, (LPTHREAD_START_ROUTINE)loadLibrary, remote, 0, NULL);
    if (!thread)
    {
        set_error("CreateRemoteThread failed %lu", GetLastError());
        VirtualFreeEx(process, remote, 0, MEM_RELEASE);
        return 0;
    }
    WaitForSingleObject(thread, 10000);
    CloseHandle(thread);
    VirtualFreeEx(process, remote, 0, MEM_RELEASE);
    return 1;
}

/* ---------- exported api ---------- */

EXPORT int inject(const char *target, const char *dll_path)
{
    if (g_injected)
    {
        /* self heal when the tracked process is gone */
        if (g_process && WaitForSingleObject(g_process, 0) == WAIT_OBJECT_0)
            ResetState();
        else
        {
            set_error("already injected");
            return INJECT_ERR_ALREADY_INJECTED;
        }
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

    if (ProcessIsHooked(pid))
    {
        set_error("the target is already hooked");
        return INJECT_ERR_ALREADY_INJECTED;
    }

    HANDLE lock = AcquireHookLock(pid);
    if (!lock)
    {
        set_error("another injector is working on this process");
        return INJECT_ERR_LOCK_TIMEOUT;
    }
    if (ProcessIsHooked(pid))
    {
        ReleaseHookLock(lock);
        set_error("the target is already hooked");
        return INJECT_ERR_ALREADY_INJECTED;
    }

    char fullPath[MAX_PATH];
    memset(fullPath, 0, sizeof(fullPath));
    DWORD pathLength = GetFullPathNameA(dll_path, MAX_PATH, fullPath, NULL);
    if (pathLength == 0 || pathLength >= MAX_PATH)
    {
        ReleaseHookLock(lock);
        set_error("bad dll path");
        return INJECT_ERR_BAD_DLL_PATH;
    }

    HANDLE process = OpenProcess(PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION |
                                     PROCESS_VM_WRITE | PROCESS_VM_READ | SYNCHRONIZE,
                                 FALSE, pid);
    if (!process)
    {
        ReleaseHookLock(lock);
        set_error("OpenProcess failed %lu", GetLastError());
        return INJECT_ERR_OPEN_PROCESS;
    }

    if (!LoadRemoteLibrary(process, fullPath))
    {
        CloseHandle(process);
        ReleaseHookLock(lock);
        return INJECT_ERR_CREATE_REMOTE_THREAD;
    }

    HMODULE remoteModule = find_remote_module(pid, file_base_name(fullPath));
    if (!remoteModule)
    {
        CloseHandle(process);
        ReleaseHookLock(lock);
        set_error("the dll is not loaded in the target");
        return INJECT_ERR_MODULE_NOT_FOUND;
    }

    /* the shim publishes its detour addresses and the image bounds through
       the shared section, everything below runs without touching the shim */
    if (!OpenSection())
    {
        CloseHandle(process);
        ReleaseHookLock(lock);
        set_error("cannot open %s, is the agent running?", HOOK_SECTION_NAME);
        return INJECT_ERR_SECTION_MISSING;
    }
    if (!WaitShimPublished())
    {
        CloseHandle(process);
        ReleaseHookLock(lock);
        if (g_section)
            CloseSection();
        set_error("the shim never published its handshake");
        return INJECT_ERR_HANDSHAKE_MISSING;
    }

    uint8_t *imageBase = (uint8_t *)(uintptr_t)g_section->imageBase;
    size_t imageSize = (size_t)g_section->imageSize;
    if (!imageBase || !imageSize)
    {
        CloseHandle(process);
        ReleaseHookLock(lock);
        CloseSection();
        set_error("the shim did not publish the image bounds");
        return INJECT_ERR_HANDSHAKE_INVALID;
    }

    g_patchedCount = 0;
    for (int i = 0; i < HOOK_INDEX_COUNT && i < HOOK_MAX_ENTRIES; i++)
    {
        const struct HookIdentity *identity = &HOOK_IDENTITIES[i];
        struct HookEntry *entry = &g_section->entries[i];

        entry->stolenBytes = identity->stolenBytes;
        entry->entryPatchBytes = HOOK_ENTRY_PATCH_BYTES;
        CopyText(entry->name, sizeof(entry->name), identity->name);
        CopyText(entry->key, sizeof(entry->key), identity->key);

        struct PatternBytes pattern;
        if (!ParsePattern(g_signatures[i], &pattern))
        {
            set_error("%s: the signature is malformed", identity->name);
            InterlockedExchange(&entry->status, HOOK_STATUS_MISSING);
            continue;
        }

        int matchCount = 0;
        uint8_t *hookTarget = ScanSignature(process, imageBase, imageSize, &pattern, &matchCount);
        if (!hookTarget)
        {
            if (matchCount > 1)
                set_error("%s: the signature matches %d places, refusing to patch", identity->name, matchCount);
            else
                set_error("%s: signature not found", identity->name);
            entry->target = 0;
            entry->trampoline = 0;
            InterlockedExchange(&entry->status, HOOK_STATUS_MISSING);
            continue;
        }

        int promoted = 0;
        uint8_t *trampoline = BuildRemoteTrampoline(process, hookTarget, identity->stolenBytes, &promoted);
        if (!trampoline)
        {
            entry->target = 0;
            entry->trampoline = 0;
            InterlockedExchange(&entry->status, HOOK_STATUS_MISSING);
            continue;
        }

        entry->target = (uint64_t)(uintptr_t)hookTarget;
        entry->trampoline = (uint64_t)(uintptr_t)trampoline;
        MemoryBarrier();
        InterlockedExchange(&entry->status, HOOK_STATUS_READY);

        if (!PatchEntry(process, entry, identity))
        {
            VirtualFreeEx(process, trampoline, 0, MEM_RELEASE);
            entry->target = 0;
            entry->trampoline = 0;
            InterlockedExchange(&entry->status, HOOK_STATUS_MISSING);
            continue;
        }

        g_trampolineSlots[g_patchedCount] = (uint64_t)(uintptr_t)trampoline;
        g_patchedCount++;
        if (promoted)
            set_error("%s: rwx allocation denied, using rw plus promote", identity->name);
    }

    g_process = process;
    g_processId = pid;
    g_remoteModule = remoteModule;
    g_injected = true;

    CloseSection();

    ReleaseHookLock(lock);

    if (g_patchedCount == 0)
    {
        set_error("no hook could be patched");
        return INJECT_ERR_NO_HOOKS;
    }

    set_error("ok");
    return INJECT_OK;
}

EXPORT void reset(void)
{
    ResetState();
    set_error("ok");
}

EXPORT int cleanup(void)
{
    if (!g_injected)
    {
        set_error("not injected");
        return INJECT_ERR_ALREADY_INJECTED;
    }
    if (!g_process)
    {
        set_error("the process handle is gone");
        ResetState();
        return INJECT_ERR_ALREADY_INJECTED;
    }
    if (!OpenSection())
    {
        set_error("cannot open %s", HOOK_SECTION_NAME);
        return INJECT_ERR_SECTION_MISSING;
    }

    for (int i = 0; i < HOOK_MAX_ENTRIES; i++)
    {
        struct HookEntry *entry = &g_section->entries[i];
        if (InterlockedCompareExchange(&entry->status, 0, 0) != HOOK_STATUS_PATCHED)
            continue;

        uint8_t *target = (uint8_t *)(uintptr_t)entry->target;
        uint8_t *trampoline = (uint8_t *)(uintptr_t)entry->trampoline;
        uint32_t stolenBytes = entry->stolenBytes;

        unsigned char original[HOOK_ENTRY_PATCH_BYTES];
        SIZE_T readBytes = 0;
        if (target && trampoline && ReadProcessMemory(g_process, trampoline, original, stolenBytes, &readBytes) &&
            readBytes == stolenBytes)
        {
            DWORD oldProtection = 0;
            if (VirtualProtectEx(g_process, target, HOOK_ENTRY_PATCH_BYTES, PAGE_EXECUTE_READWRITE, &oldProtection))
            {
                SIZE_T written = 0;
                WriteProcessMemory(g_process, target, original, stolenBytes, &written);
                DWORD ignored = 0;
                VirtualProtectEx(g_process, target, HOOK_ENTRY_PATCH_BYTES, oldProtection, &ignored);
            }
        }

        if (trampoline)
            VirtualFreeEx(g_process, trampoline, 0, MEM_RELEASE);
        entry->target = 0;
        entry->trampoline = 0;
        InterlockedExchange(&entry->status, HOOK_STATUS_MISSING);
    }
    CloseSection();

    if (g_remoteModule)
    {
        FARPROC freeLibrary = GetProcAddress(GetModuleHandleA("kernel32.dll"), "FreeLibrary");
        HANDLE thread =
            CreateRemoteThread(g_process, NULL, 0, (LPTHREAD_START_ROUTINE)freeLibrary, (LPVOID)g_remoteModule, 0, NULL);
        if (thread)
        {
            WaitForSingleObject(thread, 5000);
            CloseHandle(thread);
        }
    }

    ResetState();
    set_error("ok");
    return INJECT_OK;
}

EXPORT const char *last_error(void)
{
    return g_lastError;
}
