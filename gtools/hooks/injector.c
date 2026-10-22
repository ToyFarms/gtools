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
#define SHIM_WAIT_STEP_MS    100

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
    INJECT_ERR_EXPORT_MISSING = -14,
    INJECT_ERR_SETTINGS_SYNC = -15,
    INJECT_ERR_LOCK_TIMEOUT = -16,
};

static char g_lastError[1024] = {0};

static void set_error(const char *format, ...)
{
    va_list args;
    va_start(args, format);
    vsnprintf(g_lastError, sizeof(g_lastError), format, args);
    va_end(args);
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

static uint32_t RvaToFileOffset(const uint8_t *image, size_t imageSize, uint32_t rva)
{
    const IMAGE_DOS_HEADER *dos = (const IMAGE_DOS_HEADER *)image;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE)
        return 0;
    const IMAGE_NT_HEADERS64 *nt = (const IMAGE_NT_HEADERS64 *)(image + dos->e_lfanew);
    if ((uint8_t *)nt + sizeof(*nt) > image + imageSize || nt->Signature != IMAGE_NT_SIGNATURE)
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

static bool ExportRvaFromFile(const char *path, const char *name, uint32_t *outRva)
{
    if (!outRva)
        return false;
    *outRva = 0;

    FILE *file = fopen(path, "rb");
    if (!file)
        return false;

    uint8_t *image = NULL;
    size_t imageSize = 0;
    bool found = false;

    fseek(file, 0, SEEK_END);
    long size = ftell(file);
    fseek(file, 0, SEEK_SET);
    if (size > 0 && size < 16 * 1024 * 1024 &&
        (image = (uint8_t *)malloc((size_t)size)))
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
                const IMAGE_DATA_DIRECTORY *imported = (optional->NumberOfRvaAndSizes > IMAGE_DIRECTORY_ENTRY_EXPORT)
                                                           ? &optional->DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT]
                                                           : NULL;
                if (imported && imported->VirtualAddress)
                {
                    uint32_t offset = RvaToFileOffset(image, imageSize, imported->VirtualAddress);
                    if (offset && offset + sizeof(IMAGE_EXPORT_DIRECTORY) <= imageSize)
                    {
                        const IMAGE_EXPORT_DIRECTORY *exports = (const IMAGE_EXPORT_DIRECTORY *)(image + offset);
                        uint32_t namesRva = exports->AddressOfNames;
                        uint32_t ordinalsRva = exports->AddressOfNameOrdinals;
                        uint32_t functionsRva = exports->AddressOfFunctions;

                        uint32_t namesOffset = RvaToFileOffset(image, imageSize, namesRva);
                        uint32_t ordinalsOffset = RvaToFileOffset(image, imageSize, ordinalsRva);
                        uint32_t functionsOffset = RvaToFileOffset(image, imageSize, functionsRva);
                        if (namesOffset && ordinalsOffset && functionsOffset &&
                            exports->NumberOfNames > 0 && exports->NumberOfNames < 4096)
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
                                const char *candidate = (const char *)(image + nameOffset);
                                if (strcmp(candidate, name) == 0)
                                {
                                    uint16_t ordinal = ordinals[i];
                                    if (ordinal < exports->NumberOfFunctions)
                                    {
                                        *outRva = functions[ordinal];
                                        found = true;
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

static uint32_t g_selfRva = 0;
static int g_selfRvaValid = 0;
static char g_payloadPath[MAX_PATH] = {0};

static void RememberPayload(const char *dll_path)
{
    CopyText(g_payloadPath, sizeof(g_payloadPath), dll_path);
    g_selfRvaValid = ExportRvaFromFile(dll_path, HOOK_EXPORT_NAME, &g_selfRva) && g_selfRva != 0;
    if (!g_selfRvaValid)
        set_error("the payload has no %s export", HOOK_EXPORT_NAME);
}

static uint64_t ResolveSelfRemote(uint64_t moduleBase)
{
    if (!g_selfRvaValid)
        return 0;
    return moduleBase + g_selfRva;
}

static int WriteShimSettings(HANDLE process, uint64_t selfRemote, const struct HookSettings *settings)
{
    if (!selfRemote)
        return 0;

    void *revisionAddress = (void *)(uintptr_t)(selfRemote + offsetof(struct ShimShared, settingsRevision));
    void *settingsAddress = (void *)(uintptr_t)(selfRemote + offsetof(struct ShimShared, settings));

    LONG zero = 0;
    LONG revision = (LONG)(GetTickCount64() % 0x7FFFFFFF) + 1;
    if (!revision)
        revision = 1;

    if (!WriteProcessMemory(process, revisionAddress, (void *)&zero, sizeof(zero), NULL) ||
        !WriteProcessMemory(process, settingsAddress, (void *)settings, sizeof(*settings), NULL) ||
        !WriteProcessMemory(process, revisionAddress, (void *)&revision, sizeof(revision), NULL))
    {
        set_error("cannot mirror the settings (%lu)", GetLastError());
        return 0;
    }

    return 1;
}

static int ReadShimEntries(HANDLE process, uint64_t selfRemote, struct HookEntry *entries)
{
    SIZE_T readBytes = 0;
    void *address = (void *)(uintptr_t)(selfRemote + offsetof(struct ShimShared, entries));
    if (!ReadProcessMemory(process, address, entries, sizeof(struct HookEntry) * HOOK_MAX_ENTRIES, &readBytes) ||
        readBytes != sizeof(struct HookEntry) * HOOK_MAX_ENTRIES)
        return 0;
    return 1;
}

static int WriteShimEntryStatus(HANDLE process, uint64_t selfRemote, int index, LONG status)
{
    void *address =
        (void *)(uintptr_t)(selfRemote + offsetof(struct ShimShared, entries) + sizeof(struct HookEntry) * index +
                            offsetof(struct HookEntry, status));
    return WriteProcessMemory(process, address, &status, sizeof(status), NULL) ? 1 : 0;
}

static int WaitShimReady(HANDLE process, uint64_t selfRemote, int configuredDelayMs)
{
    ULONGLONG deadline = GetTickCount64() + SHIM_WAIT_GRACE_MS;
    if (configuredDelayMs > 0)
        deadline += (ULONGLONG)configuredDelayMs;

    for (;;)
    {
        volatile LONG readyValue = 0;
        SIZE_T readBytes = 0;
        if (ReadProcessMemory(process, (void *)(uintptr_t)(selfRemote + offsetof(struct ShimShared, ready)),
                              (void *)&readyValue, sizeof(readyValue), &readBytes) &&
            readBytes == sizeof(readyValue) && readyValue == 1)
            return 1;

        if (GetTickCount64() >= deadline)
            return 0;
        Sleep(SHIM_WAIT_STEP_MS);
    }
}

static HANDLE g_process = NULL;
static DWORD g_processId = 0;
static HMODULE g_remoteModule = NULL;
static uint64_t g_selfRemote = 0;
static unsigned char g_originalBytes[HOOK_MAX_ENTRIES][HOOK_ENTRY_PATCH_BYTES];
static uint64_t g_trampolineList[HOOK_MAX_ENTRIES];
static int g_patchedCount = 0;
static bool g_injected = false;

static struct HookSettings g_pendingSettings;
static int g_pendingValid = 0;

static void ResetState(void)
{
    if (g_process)
    {
        CloseHandle(g_process);
        g_process = NULL;
    }
    g_processId = 0;
    g_remoteModule = NULL;
    g_selfRemote = 0;
    memset(g_originalBytes, 0, sizeof(g_originalBytes));
    memset(g_trampolineList, 0, sizeof(g_trampolineList));
    g_patchedCount = 0;
    g_injected = false;
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

static int PatchEntry(HANDLE process, const struct HookEntry *entry, int index)
{
    uint8_t *target = (uint8_t *)(uintptr_t)entry->target;

    unsigned char original[HOOK_ENTRY_PATCH_BYTES];
    SIZE_T readBytes = 0;
    if (!ReadProcessMemory(process, target, original, HOOK_ENTRY_PATCH_BYTES, &readBytes) ||
        readBytes != HOOK_ENTRY_PATCH_BYTES)
    {
        set_error("cannot read the original bytes of %s", entry->name);
        return 0;
    }
    memcpy(g_originalBytes[index], original, HOOK_ENTRY_PATCH_BYTES);

    unsigned char patch[HOOK_ENTRY_PATCH_BYTES];
    write_abs_jump(patch, entry->detour);

    DWORD oldProtection = 0;
    if (!VirtualProtectEx(process, target, HOOK_ENTRY_PATCH_BYTES, PAGE_EXECUTE_READWRITE, &oldProtection))
    {
        set_error("VirtualProtectEx failed for %s (%lu)", entry->name, GetLastError());
        return 0;
    }

    SIZE_T written = 0;
    bool patched = WriteProcessMemory(process, target, patch, HOOK_ENTRY_PATCH_BYTES, &written) &&
                   written == HOOK_ENTRY_PATCH_BYTES;
    DWORD ignored = 0;
    VirtualProtectEx(process, target, HOOK_ENTRY_PATCH_BYTES, oldProtection, &ignored);
    if (!patched)
    {
        set_error("cannot patch %s", entry->name);
        return 0;
    }

    unsigned char verify[HOOK_ENTRY_PATCH_BYTES];
    readBytes = 0;
    if (!ReadProcessMemory(process, target, verify, HOOK_ENTRY_PATCH_BYTES, &readBytes) ||
        readBytes != HOOK_ENTRY_PATCH_BYTES || verify[0] != 0xFF || verify[1] != 0x25 ||
        memcmp(verify + 6, &entry->detour, sizeof(entry->detour)) != 0)
    {
        set_error("%s: the patch did not verify", entry->name);
        return 0;
    }

    return 1;
}

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

EXPORT int configure(const void *settings, uint32_t size)
{
    if (size != sizeof(struct HookSettings))
    {
        set_error("configure expects %zu bytes, got %u", sizeof(struct HookSettings), size);
        return -1;
    }
    memcpy(&g_pendingSettings, settings, sizeof(g_pendingSettings));
    g_pendingValid = 1;
    set_error("ok");
    return 0;
}

EXPORT int inject(const char *target, const char *dll_path)
{
    if (g_injected)
    {
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

    RememberPayload(fullPath);
    if (!g_selfRvaValid)
    {
        ReleaseHookLock(lock);
        return INJECT_ERR_EXPORT_MISSING;
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

    uint64_t selfRemote = ResolveSelfRemote((uint64_t)(uintptr_t)remoteModule);
    if (!selfRemote)
    {
        CloseHandle(process);
        ReleaseHookLock(lock);
        set_error("the shim module has no export table entry");
        return INJECT_ERR_EXPORT_MISSING;
    }

    struct HookSettings settings;
    if (g_pendingValid)
    {
        memcpy(&settings, &g_pendingSettings, sizeof(settings));
    }
    else
    {
        CopyText(settings.proxyHost, sizeof(settings.proxyHost), "127.0.0.1");
        settings.proxyPort = 16999;
        settings.startDelayMs = 2500;
        settings.logLevel = HOOK_LOG_INFO;
        settings.allowAnyModule = 0;
        settings.streamGameLogs = 0;
    }
    if (!WriteShimSettings(process, selfRemote, &settings))
    {
        CloseHandle(process);
        ReleaseHookLock(lock);
        return INJECT_ERR_SETTINGS_SYNC;
    }

    if (!WaitShimReady(process, selfRemote, settings.startDelayMs))
    {
        CloseHandle(process);
        ReleaseHookLock(lock);
        set_error("the shim never published its handshake");
        return INJECT_ERR_HANDSHAKE_MISSING;
    }

    struct HookEntry entries[HOOK_MAX_ENTRIES];
    if (!ReadShimEntries(process, selfRemote, entries))
    {
        CloseHandle(process);
        ReleaseHookLock(lock);
        set_error("cannot read the shim entries");
        return INJECT_ERR_HANDSHAKE_INVALID;
    }

    g_patchedCount = 0;
    for (int i = 0; i < HOOK_MAX_ENTRIES; i++)
    {
        const struct HookEntry *entry = &entries[i];
        if (entry->status != HOOK_STATUS_READY || !entry->target || !entry->detour || !entry->trampoline)
            continue;
        if (entry->entryPatchBytes != HOOK_ENTRY_PATCH_BYTES || entry->stolenBytes < HOOK_ENTRY_PATCH_BYTES)
        {
            set_error("%s expects at least %d stolen bytes", entry->name, HOOK_ENTRY_PATCH_BYTES);
            continue;
        }

        if (!PatchEntry(process, entry, i))
            continue;

        WriteShimEntryStatus(process, selfRemote, i, HOOK_STATUS_PATCHED);
        g_trampolineList[g_patchedCount] = entry->trampoline;
        g_patchedCount++;
    }

    g_process = process;
    g_processId = pid;
    g_remoteModule = remoteModule;
    g_selfRemote = selfRemote;
    g_injected = true;

    ReleaseHookLock(lock);

    if (g_patchedCount == 0)
    {
        ResetState();
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

EXPORT int apply_settings(const char *target, const char *dll_path, const void *settings, uint32_t size)
{
    if (!target || !dll_path || !settings)
    {
        set_error("bad args");
        return INJECT_ERR_BAD_ARGS;
    }
    if (size != sizeof(struct HookSettings))
    {
        set_error("apply_settings expects %zu bytes, got %u", sizeof(struct HookSettings), size);
        return INJECT_ERR_BAD_ARGS;
    }

    RememberPayload(dll_path);
    if (!g_selfRvaValid)
    {
        return INJECT_ERR_EXPORT_MISSING;
    }

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

    HMODULE module = find_remote_module(pid, file_base_name(dll_path));
    if (!module)
    {
        set_error("the shim is not loaded in the target");
        return INJECT_ERR_MODULE_NOT_FOUND;
    }

    uint64_t selfRemote = ResolveSelfRemote((uint64_t)(uintptr_t)module);
    if (!selfRemote)
    {
        set_error("the shim module has no export table entry");
        return INJECT_ERR_EXPORT_MISSING;
    }

    HANDLE process = OpenProcess(PROCESS_VM_OPERATION | PROCESS_VM_WRITE, FALSE, pid);
    if (!process)
    {
        set_error("OpenProcess failed %lu", GetLastError());
        return INJECT_ERR_OPEN_PROCESS;
    }
    int ok = WriteShimSettings(process, selfRemote, (const struct HookSettings *)settings);
    CloseHandle(process);

    set_error("ok");
    return ok ? INJECT_OK : INJECT_ERR_SETTINGS_SYNC;
}

EXPORT int cleanup(void)
{
    if (!g_injected)
    {
        set_error("not injected");
        return INJECT_ERR_ALREADY_INJECTED;
    }
    if (!g_process || !g_selfRemote)
    {
        set_error("the process handle is gone");
        ResetState();
        return INJECT_ERR_ALREADY_INJECTED;
    }

    struct HookEntry entries[HOOK_MAX_ENTRIES];
    if (!ReadShimEntries(g_process, g_selfRemote, entries))
    {
        set_error("cannot read the shim entries");
        ResetState();
        return INJECT_ERR_HANDSHAKE_INVALID;
    }

    for (int i = 0; i < HOOK_MAX_ENTRIES; i++)
    {
        const struct HookEntry *entry = &entries[i];
        if (entry->status != HOOK_STATUS_PATCHED)
            continue;

        uint8_t *target = (uint8_t *)(uintptr_t)entry->target;
        uint8_t *trampoline = (uint8_t *)(uintptr_t)entry->trampoline;

        DWORD oldProtection = 0;
        if (VirtualProtectEx(g_process, target, HOOK_ENTRY_PATCH_BYTES, PAGE_EXECUTE_READWRITE, &oldProtection))
        {
            SIZE_T written = 0;
            WriteProcessMemory(g_process, target, g_originalBytes[i], HOOK_ENTRY_PATCH_BYTES, &written);
            DWORD ignored = 0;
            VirtualProtectEx(g_process, target, HOOK_ENTRY_PATCH_BYTES, oldProtection, &ignored);
        }
        if (trampoline)
            VirtualFreeEx(g_process, trampoline, 0, MEM_RELEASE);

        WriteShimEntryStatus(g_process, g_selfRemote, i, HOOK_STATUS_MISSING);
    }

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
