/*
 * injector.c - remote patcher for the v4 hook payload.
 *
 * The payload (descriptors + programs, authored in Python) is written into the
 * shim's exported g_self block, which releases the shim worker; once the shim
 * has resolved and published its entries this patches the 14-byte absolute
 * jumps from outside the target and marks the entries PATCHED.
 *
 * Exports: inject(target, dll_path), cleanup(), last_error().
 *
 * BUILD_FLAGS[gcc(mingw)]: -O2 -shared -fPIC
 * BUILD_FLAGS[gcc, clang]: -O2 -shared -fPIC
 */

#ifndef _WIN32
/* injector.dll is Windows-only; keep compile_cmod.py's Linux job green */
int g_injector_windows_only;
#else

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
#include "hook_prologue.h"

#if defined(_MSC_VER)
#  pragma comment(lib, "advapi32.lib")
#  define EXPORT __declspec(dllexport)
#else
#  define EXPORT __attribute__((visibility("default")))
#endif

#define SHIM_WAIT_GRACE_MS   30000
#define SHIM_WAIT_STEP_MS    100
#define PAYLOAD_FILE         "hook_payload.bin"

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
    INJECT_ERR_HANDSHAKE_INVALID = -12,
    INJECT_ERR_EXPORT_MISSING = -14,
    INJECT_ERR_PAYLOAD_MISSING = -15,
    INJECT_ERR_PAYLOAD_INVALID = -16,
    INJECT_ERR_LOCK_TIMEOUT = -17,
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

/* ------------------------------------------------------------------ */

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

static int PayloadHasPattern(const struct HookDescriptor *desc)
{
    return desc->source == HOOK_SRC_PATTERN && desc->patternCount > 0;
}

static int TargetMatchesPattern(HANDLE process, uint8_t *target, const struct HookDescriptor *desc)
{
    for (uint32_t v = 0; v < desc->patternCount && v < HOOK_PATTERN_MAX; v++)
    {
        uint32_t length = desc->patterns[v].length;
        if (length == 0 || length > HOOK_PATTERN_BYTES)
            continue;
        uint8_t remote[HOOK_PATTERN_BYTES];
        SIZE_T got = 0;
        if (!ReadProcessMemory(process, target, remote, length, &got) || got != length)
            return 0;
        int ok = 1;
        for (uint32_t i = 0; i < length; i++)
        {
            if (desc->patterns[v].mask[i] && remote[i] != desc->patterns[v].bytes[i])
            {
                ok = 0;
                break;
            }
        }
        if (ok)
            return 1;
    }
    return 0;
}

/* ------------------------------------------------------------------ */

static HANDLE g_process = NULL;
static DWORD g_processId = 0;
static HMODULE g_remoteModule = NULL;
static uint64_t g_selfRemote = 0;
static unsigned char g_originalBytes[HOOK_MAX][HOOK_ENTRY_PATCH_BYTES];
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
    g_selfRemote = 0;
    memset(g_originalBytes, 0, sizeof(g_originalBytes));
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

static int ReadPayload(const char *dllPath, struct HookPayload *out)
{
    char directory[MAX_PATH];
    CopyText(directory, sizeof(directory), dllPath);
    char *separator = strrchr(directory, '\\');
    if (separator)
        *separator = 0;
    else
        CopyText(directory, sizeof(directory), ".");

    char path[MAX_PATH];
    snprintf(path, sizeof(path), "%s\\%s", directory, PAYLOAD_FILE);

    FILE *file = fopen(path, "rb");
    if (!file)
    {
        set_error("the payload %s is missing (write it before injecting)", path);
        return 0;
    }
    size_t read = fread(out, 1, sizeof(*out), file);
    fclose(file);
    if (read != sizeof(*out))
    {
        set_error("%s is %zu bytes, expected %zu", path, read, sizeof(*out));
        return 0;
    }
    if (out->magic != HOOK_PAYLOAD_MAGIC || out->version != HOOK_PROTOCOL_VERSION ||
        out->payloadBytes != sizeof(*out) || out->descriptorCount > HOOK_MAX)
    {
        set_error("%s has an incompatible header (version %u)", path, out->version);
        return 0;
    }
    return 1;
}

static int WriteShimPayload(HANDLE process, uint64_t selfRemote, const struct HookPayload *payload)
{
    void *payloadAddress = (void *)(uintptr_t)(selfRemote + offsetof(struct ShimShared, payload));
    void *crcAddress = (void *)(uintptr_t)(selfRemote + offsetof(struct ShimShared, payloadCrc));
    void *countAddress = (void *)(uintptr_t)(selfRemote + offsetof(struct ShimShared, descriptorCount));
    void *revisionAddress = (void *)(uintptr_t)(selfRemote + offsetof(struct ShimShared, payloadRevision));

    LONG zero = 0;
    LONG revision = (LONG)(GetTickCount64() % 0x7FFFFFFF) + 1;
    if (!revision)
        revision = 1;

    uint32_t crc = crc32_of((const uint8_t *)payload, sizeof(*payload));
    uint32_t count = payload->descriptorCount;

    if (!WriteProcessMemory(process, payloadAddress, (LPCVOID)payload, sizeof(*payload), NULL) ||
        !WriteProcessMemory(process, crcAddress, &crc, sizeof(crc), NULL) ||
        !WriteProcessMemory(process, countAddress, &count, sizeof(count), NULL) ||
        !WriteProcessMemory(process, revisionAddress, &zero, sizeof(zero), NULL) ||
        !WriteProcessMemory(process, revisionAddress, &revision, sizeof(revision), NULL))
    {
        set_error("cannot mirror the payload (%lu)", GetLastError());
        return 0;
    }
    return 1;
}

static int WaitShimReady(HANDLE process, uint64_t selfRemote, uint32_t startDelayMs)
{
    ULONGLONG deadline = GetTickCount64() + SHIM_WAIT_GRACE_MS;
    if (startDelayMs > 0)
        deadline += startDelayMs;

    for (;;)
    {
        int32_t ready = 0;
        SIZE_T got = 0;
        if (ReadProcessMemory(process, (LPCVOID)(uintptr_t)(selfRemote + offsetof(struct ShimShared, ready)),
                              &ready, sizeof(ready), &got) &&
            got == sizeof(ready) && ready == 1)
            return 1;
        if (GetTickCount64() >= deadline)
            return 0;
        Sleep(SHIM_WAIT_STEP_MS);
    }
}

static int ReadShimEntries(HANDLE process, uint64_t selfRemote, struct HookRuntime *runtime)
{
    SIZE_T got = 0;
    void *address = (void *)(uintptr_t)(selfRemote + offsetof(struct ShimShared, runtime));
    if (!ReadProcessMemory(process, address, runtime, sizeof(struct HookRuntime) * HOOK_MAX, &got) ||
        got != sizeof(struct HookRuntime) * HOOK_MAX)
        return 0;
    return 1;
}

static int WriteShimEntryStatus(HANDLE process, uint64_t selfRemote, int index, LONG status)
{
    void *address = (void *)(uintptr_t)(selfRemote + offsetof(struct ShimShared, runtime) +
                                        sizeof(struct HookRuntime) * (size_t)index +
                                        offsetof(struct HookRuntime, status));
    return WriteProcessMemory(process, address, &status, sizeof(status), NULL) ? 1 : 0;
}

static int PatchEntry(HANDLE process, const struct HookRuntime *entry, int index, const struct HookDescriptor *desc)
{
    uint8_t *target = (uint8_t *)(uintptr_t)entry->target;

    if (PayloadHasPattern(desc) && !TargetMatchesPattern(process, target, desc))
    {
        set_error("%s: the bytes at %p no longer match the payload signature", entry->key,
                  (void *)(uintptr_t)target);
        return 0;
    }

    /* verify the whole stolen prefix (the shim's decoded length), not just the patch */
    unsigned stolen = (unsigned)(entry->stolenBytes > 0 ? entry->stolenBytes : HOOK_ENTRY_PATCH_BYTES);
    if (stolen < HOOK_ENTRY_PATCH_BYTES || stolen > 256)
    {
        set_error("%s: implausible stolen length %u", entry->key, stolen);
        return 0;
    }
    unsigned char original[256];
    SIZE_T got = 0;
    if (!ReadProcessMemory(process, target, original, stolen, &got) || got != stolen)
    {
        set_error("cannot read the original bytes of %s", entry->key);
        return 0;
    }
    if (hook_prologue_length(original, stolen, stolen) == 0)
    {
        set_error("%s: the %u bytes at %p are not a safe patch site", entry->key, stolen, (void *)(uintptr_t)target);
        return 0;
    }
    memcpy(g_originalBytes[index], original, HOOK_ENTRY_PATCH_BYTES);

    unsigned char patch[HOOK_ENTRY_PATCH_BYTES];
    write_abs_jump(patch, entry->detour);

    DWORD oldProtection = 0;
    if (!VirtualProtectEx(process, target, HOOK_ENTRY_PATCH_BYTES, PAGE_EXECUTE_READWRITE, &oldProtection))
    {
        set_error("VirtualProtectEx failed for %s (%lu)", entry->key, GetLastError());
        return 0;
    }

    SIZE_T written = 0;
    bool patched = WriteProcessMemory(process, target, patch, HOOK_ENTRY_PATCH_BYTES, &written) &&
                   written == HOOK_ENTRY_PATCH_BYTES;
    DWORD ignored = 0;
    VirtualProtectEx(process, target, HOOK_ENTRY_PATCH_BYTES, oldProtection, &ignored);
    if (!patched)
    {
        set_error("cannot patch %s", entry->key);
        return 0;
    }

    unsigned char verify[HOOK_ENTRY_PATCH_BYTES];
    got = 0;
    if (!ReadProcessMemory(process, target, verify, HOOK_ENTRY_PATCH_BYTES, &got) ||
        got != HOOK_ENTRY_PATCH_BYTES || verify[0] != 0xFF || verify[1] != 0x25 ||
        memcmp(verify + 6, &entry->detour, sizeof(entry->detour)) != 0)
    {
        set_error("%s: the patch did not verify", entry->key);
        return 0;
    }
    return 1;
}

EXPORT int inject(const char *target, const char *dll_path)
{
    /* 317 KB: static, never on the injector's stack */
    static struct HookPayload payload;

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

    if (!ReadPayload(fullPath, &payload))
    {
        ReleaseHookLock(lock);
        return INJECT_ERR_PAYLOAD_MISSING;
    }

    uint32_t selfRva = 0;
    if (!ExportRvaFromFile(fullPath, HOOK_EXPORT_NAME, &selfRva) || !selfRva)
    {
        ReleaseHookLock(lock);
        set_error("the shim module has no %s export", HOOK_EXPORT_NAME);
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

    HMODULE remoteModule = NULL;
    for (int attempt = 0; attempt < 20 && !remoteModule; attempt++)
    {
        remoteModule = find_remote_module(pid, file_base_name(fullPath));
        if (!remoteModule)
            Sleep(50); /* the loader may not have published the module yet */
    }
    if (!remoteModule)
    {
        CloseHandle(process);
        ReleaseHookLock(lock);
        set_error("the dll is not loaded in the target");
        return INJECT_ERR_MODULE_NOT_FOUND;
    }

    uint64_t selfRemote = (uint64_t)(uintptr_t)remoteModule + selfRva;

    if (!WriteShimPayload(process, selfRemote, &payload))
    {
        CloseHandle(process);
        ReleaseHookLock(lock);
        return INJECT_ERR_WRITE_REMOTE;
    }

    if (!WaitShimReady(process, selfRemote, payload.startDelayMs))
    {
        CloseHandle(process);
        ReleaseHookLock(lock);
        set_error("the shim never published its entries");
        return INJECT_ERR_HANDSHAKE_MISSING;
    }

    struct HookRuntime runtime[HOOK_MAX];
    if (!ReadShimEntries(process, selfRemote, runtime))
    {
        CloseHandle(process);
        ReleaseHookLock(lock);
        set_error("cannot read the shim entries");
        return INJECT_ERR_HANDSHAKE_INVALID;
    }

    g_patchedCount = 0;
    for (int i = 0; i < (int)HOOK_MAX && i < (int)payload.descriptorCount; i++)
    {
        const struct HookRuntime *entry = &runtime[i];
        if (entry->status != HOOK_STATUS_READY || !entry->target || !entry->detour || !entry->trampoline)
            continue;
        if (!PatchEntry(process, entry, i, &payload.descriptors[i]))
            continue; /* the detailed error is already in g_lastError */
        WriteShimEntryStatus(process, selfRemote, i, HOOK_STATUS_PATCHED);
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
        return INJECT_ERR_HANDSHAKE_INVALID;
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
    if (!g_process || !g_selfRemote)
    {
        set_error("the process handle is gone");
        ResetState();
        return INJECT_ERR_ALREADY_INJECTED;
    }

    struct HookRuntime runtime[HOOK_MAX];
    if (!ReadShimEntries(g_process, g_selfRemote, runtime))
    {
        set_error("cannot read the shim entries");
        ResetState();
        return INJECT_ERR_HANDSHAKE_INVALID;
    }

    for (int i = 0; i < (int)HOOK_MAX; i++)
    {
        const struct HookRuntime *entry = &runtime[i];
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

#endif /* _WIN32 */
