#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdarg.h>
#include <errno.h>

#if defined(_MSC_VER)
#pragma comment(lib, "advapi32.lib")
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif

#define PATCH_LEN 14
#define HS_WAIT_TRIES 60
#define HS_WAIT_MS 500

static char g_last_err[1024] = {0};
static void set_err(const char* fmt, ...) {
    va_list ap; va_start(ap, fmt);
    vsnprintf(g_last_err, sizeof(g_last_err), fmt, ap);
    va_end(ap);
}

static DWORD find_pid(const char* exe) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return 0;
    DWORD pid = 0;
    PROCESSENTRY32 pe; memset(&pe, 0, sizeof(pe)); pe.dwSize = sizeof(pe);
    if (Process32First(snap, &pe)) {
        do {
            if (_stricmp(pe.szExeFile, exe) == 0) { pid = pe.th32ProcessID; break; }
        } while (Process32Next(snap, &pe));
    }
    CloseHandle(snap);
    return pid;
}

static HMODULE find_remote_module(DWORD pid, const char* base_name) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid);
    if (snap == INVALID_HANDLE_VALUE) return NULL;
    HMODULE mod = NULL;
    MODULEENTRY32 me; memset(&me, 0, sizeof(me)); me.dwSize = sizeof(me);
    if (Module32First(snap, &me)) {
        do {
            if (_stricmp(me.szModule, base_name) == 0) { mod = me.hModule; break; }
        } while (Module32Next(snap, &me));
    }
    CloseHandle(snap);
    return mod;
}

static const char* base_name_of(const char* path) {
    const char* p = strrchr(path, '\\');
    if (!p) p = strrchr(path, '/');
    return p ? p + 1 : path;
}

static DWORD g_pid = 0;
static HANDLE g_proc = NULL;
static LPVOID g_remote_mem = NULL;
static HMODULE g_remote_mod = NULL;
static char g_hs_path[MAX_PATH] = {0};
static uintptr_t g_targets[5] = {0};
static uintptr_t g_hooks[5] = {0};
static unsigned char g_originals[5][PATCH_LEN];
static int g_patched[5] = {0};
static int g_injected = 0;

static int read_handshake(const char* path) {
    FILE* f = fopen(path, "r");
    if (!f) return 0;
    char line[512];

    const char* keys[5] = {"target_logprintf","target_lograw","target_connect","target_onresponse","target_httppost"};
    uintptr_t* dests[5] = {&g_targets[1],&g_targets[2],&g_targets[0],&g_targets[3],&g_targets[4]};

    const char* hkeys[5] = {"hook_logprintf","hook_lograw","hook_connect","hook_onresponse","hook_httppost"};
    uintptr_t* hdests[5] = {&g_hooks[1],&g_hooks[2],&g_hooks[0],&g_hooks[3],&g_hooks[4]};
    while (fgets(line, sizeof(line), f)) {
        if (line[0] == '#') continue;
        char* eq = strchr(line, '=');
        if (!eq) continue;
        *eq = 0;
        char* k = line; char* v = eq + 1;

        while (*k == ' ' || *k == '\t') k++;
        char* e = k + strlen(k);
        while (e > k && (e[-1]==' '||e[-1]=='\t'||e[-1]=='\r'||e[-1]=='\n')) *--e=0;
        while (*v == ' ' || *v == '\t') v++;
        e = v + strlen(v);
        while (e > v && (e[-1]==' '||e[-1]=='\t'||e[-1]=='\r'||e[-1]=='\n')) *--e=0;
        unsigned long long val = strtoull(v, NULL, 0);
        for (int i = 0; i < 5; i++) {
            if (strcmp(k, keys[i]) == 0) *dests[i] = (uintptr_t)val;
            if (strcmp(k, hkeys[i]) == 0) *hdests[i] = (uintptr_t)val;
        }
    }
    fclose(f);
    return (g_targets[0] && g_hooks[0]);
}

static void put_abs_jump(unsigned char* p, unsigned long long dest) {
    p[0]=0xFF; p[1]=0x25; p[2]=p[3]=p[4]=p[5]=0;
    memcpy(p+6, &dest, 8);
}

EXPORT int inject(const char* target, const char* dll_path, const char* handshake_path) {
    if (g_injected) { set_err("already injected"); return -1; }
    if (!target || !dll_path) { set_err("bad args"); return -2; }
    const char* hs = handshake_path ? handshake_path : "gtdump_hook.handshake";

    DWORD pid = 0;
    char* end = NULL; errno = 0;
    long v = strtol(target, &end, 10);
    if (end && *end == '\0' && v > 0 && errno == 0) pid = (DWORD)v;
    else pid = find_pid(target);
    if (!pid) { set_err("process not found: %s", target); return -3; }

    char full[MAX_PATH]; memset(full,0,sizeof(full));
    DWORD n = GetFullPathNameA(dll_path, MAX_PATH, full, NULL);
    if (n == 0 || n >= MAX_PATH) { set_err("bad dll path"); return -4; }

    DeleteFileA(hs);

    HANDLE proc = OpenProcess(PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION |
                              PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ,
                              FALSE, pid);
    if (!proc) { set_err("OpenProcess failed %lu", GetLastError()); return -5; }

    // inject DLL
    size_t len = strlen(full) + 1;
    LPVOID remote = VirtualAllocEx(proc, NULL, len, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!remote) { set_err("VirtualAllocEx failed"); CloseHandle(proc); return -6; }
    if (!WriteProcessMemory(proc, remote, full, len, NULL)) { set_err("WPM path failed"); VirtualFreeEx(proc,remote,0,MEM_RELEASE); CloseHandle(proc); return -7; }
    FARPROC loadLib = GetProcAddress(GetModuleHandleA("kernel32.dll"), "LoadLibraryA");
    HANDLE th = CreateRemoteThread(proc, NULL, 0, (LPTHREAD_START_ROUTINE)loadLib, remote, 0, NULL);
    if (!th) { set_err("CreateRemoteThread failed"); VirtualFreeEx(proc,remote,0,MEM_RELEASE); CloseHandle(proc); return -8; }
    WaitForSingleObject(th, 10000);
    DWORD rc = 0; GetExitCodeThread(th, &rc);
    CloseHandle(th);
    VirtualFreeEx(proc, remote, 0, MEM_RELEASE);

    // find module base in target
    HMODULE mod = find_remote_module(pid, base_name_of(full));
    if (!mod) { set_err("module not found in target"); CloseHandle(proc); return -9; }

    // wait handshake
    int got = 0;
    for (int i = 0; i < HS_WAIT_TRIES && !got; i++) {
        Sleep(HS_WAIT_MS);
        got = read_handshake(hs);
    }
    if (!got) { set_err("handshake never appeared"); CloseHandle(proc); return -10; }

    // patch
    HANDLE pproc = OpenProcess(PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, FALSE, pid);
    if (!pproc) { set_err("OpenProcess patch failed"); CloseHandle(proc); return -11; }

    for (int i = 0; i < 5; i++) {
        g_patched[i] = 0;
        if (!g_targets[i] || !g_hooks[i]) continue;
        // read original
        SIZE_T gotb = 0;
        ReadProcessMemory(pproc, (void*)g_targets[i], g_originals[i], PATCH_LEN, &gotb);
        // patch
        unsigned char patch[PATCH_LEN];
        put_abs_jump(patch, (unsigned long long)g_hooks[i]);
        DWORD oldp = 0;
        if (VirtualProtectEx(pproc, (void*)g_targets[i], PATCH_LEN, PAGE_EXECUTE_READWRITE, &oldp)) {
            SIZE_T w = 0;
            if (WriteProcessMemory(pproc, (void*)g_targets[i], patch, PATCH_LEN, &w) && w == PATCH_LEN) {
                DWORD d = 0;
                VirtualProtectEx(pproc, (void*)g_targets[i], PATCH_LEN, oldp, &d);
                g_patched[i] = 1;
            }
        }
    }

    g_pid = pid;
    g_proc = pproc;
    g_remote_mem = NULL;
    g_remote_mod = mod;
    snprintf(g_hs_path, sizeof(g_hs_path), "%s", hs);
    g_injected = 1;

    CloseHandle(proc);
    set_err("ok");
    return 0;
}

EXPORT int cleanup(void) {
    if (!g_injected) { set_err("not injected"); return -1; }
    // restore originals
    if (g_proc) {
        for (int i = 0; i < 5; i++) {
            if (!g_patched[i] || !g_targets[i]) continue;
            DWORD oldp = 0;
            if (VirtualProtectEx(g_proc, (void*)g_targets[i], PATCH_LEN, PAGE_EXECUTE_READWRITE, &oldp)) {
                SIZE_T w = 0;
                WriteProcessMemory(g_proc, (void*)g_targets[i], g_originals[i], PATCH_LEN, &w);
                DWORD d = 0;
                VirtualProtectEx(g_proc, (void*)g_targets[i], PATCH_LEN, PAGE_EXECUTE_READ, &d);
            }
            g_patched[i] = 0;
        }
        // unload module remotely
        if (g_remote_mod) {
            FARPROC freeLib = GetProcAddress(GetModuleHandleA("kernel32.dll"), "FreeLibrary");
            HANDLE th = CreateRemoteThread(g_proc, NULL, 0, (LPTHREAD_START_ROUTINE)freeLib, (LPVOID)g_remote_mod, 0, NULL);
            if (th) { WaitForSingleObject(th, 5000); CloseHandle(th); }
        }
        CloseHandle(g_proc);
        g_proc = NULL;
    }
    if (g_remote_mem) { /* none tracked */ }
    if (g_hs_path[0]) { DeleteFileA(g_hs_path); g_hs_path[0] = 0; }
    g_injected = 0;
    g_pid = 0;
    g_remote_mod = NULL;
    set_err("ok");
    return 0;
}

EXPORT const char* last_error(void) {
    return g_last_err;
}
