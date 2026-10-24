#ifndef __HOOK_PROTOCOL_H
#define __HOOK_PROTOCOL_H

#include <stdint.h>
#include <windows.h>

#define HOOK_PROTOCOL_VERSION 3u
#define HOOK_PROTOCOL_MAGIC   0x4B485447u /* "GTHK" */
#define HOOK_PIPE_NAME        "\\\\.\\pipe\\gtools_hook"
#ifndef HOOK_AGENT_MUTEX_NAME
#  define HOOK_AGENT_MUTEX_NAME "Global\\gtools_hook_agent"
#endif
#define HOOK_PID_MUTEX_PREFIX  "Global\\gtools_hook_pid_"
#define HOOK_LOCK_MUTEX_PREFIX "Global\\gtools_hook_lock_"

#define HOOK_EXPORT_NAME "g_self"

#define HOOK_MAX_ENTRIES    8
#define HOOK_ENTRY_NAME_MAX 32
#define HOOK_ENTRY_KEY_MAX  32

#define HOOK_ENTRY_PATCH_BYTES 14

#define HOOK_INDEX_GAME_LOG_PRINTF 0
#define HOOK_INDEX_GAME_LOG_RAW    1
#define HOOK_INDEX_RESPONSE        2
#define HOOK_INDEX_HTTP_POST       3
#define HOOK_INDEX_RENDER_FRAME    4
#define HOOK_INDEX_RENDER_SUBMIT   5
#define HOOK_INDEX_COUNT           6

enum HookEntryStatus
{
    HOOK_STATUS_MISSING = 0,
    HOOK_STATUS_READY = 1,
    HOOK_STATUS_PATCHED = 2,
};

#define HOOK_SLOT_EMPTY   0
#define HOOK_SLOT_CLAIMED 1
#define HOOK_SLOT_READY   2

#define HOOK_LOG_ERROR 0
#define HOOK_LOG_INFO  1
#define HOOK_LOG_TRACE 2
#define HOOK_LOG_GAME  3

#define HOOK_LOG_SLOTS 128
#define HOOK_LOG_LINE  512

#define HOOK_TEXT_FIELD_MAX 128
#define HOOK_FIELD_MAX      64

#define HOOK_BOOT_SETTINGS_SPIN_MS 30000

struct HookEntry
{
    uint64_t target;
    uint64_t detour;
    uint64_t trampoline;
    uint32_t stolenBytes;
    uint32_t entryPatchBytes;
    LONG status;
    char name[HOOK_ENTRY_NAME_MAX];
    char key[HOOK_ENTRY_KEY_MAX];
};

struct HookSettings
{
    char proxyHost[HOOK_TEXT_FIELD_MAX];
    int proxyPort;
    int startDelayMs;
    int logLevel;
    int allowAnyModule;
    int streamGameLogs;
    int lowPower;
    int lowPowerFps;
    int lowPowerSkipDraws;
};

struct HookCapture
{
    char clientVersion[HOOK_FIELD_MAX];
    char clientProtocol[HOOK_FIELD_MAX];
    char clientPlatform[HOOK_FIELD_MAX];
    char realServer[HOOK_FIELD_MAX];
    int realPort;
};

struct HookHandshake
{
    uint32_t magic;
    uint32_t version;
    uint32_t entryCount;
    uint32_t reserved;
    uint64_t processId;
    uint64_t imageBase;
    uint64_t imageSize;
    uint64_t dllBase;
    struct HookEntry entries[HOOK_MAX_ENTRIES];
};

struct HookSlot
{
    volatile LONG state;
    LONG sequence;
    DWORD threadId;
    int level;
    char text[HOOK_LOG_LINE];
};

struct ShimShared
{
    volatile LONG magic;
    uint32_t version;
    volatile LONG ready;
    volatile LONG settingsRevision;

    uint64_t processId;
    uint64_t imageBase;
    uint64_t imageSize;
    uint64_t dllBase;
    uint64_t bootTick;

    struct HookEntry entries[HOOK_MAX_ENTRIES];
    volatile LONG entryCount;

    struct HookSettings settings;
    struct HookCapture capture;

    volatile LONG logTicket;
    struct HookSlot log[HOOK_LOG_SLOTS];
};

struct HookIdentity
{
    const char *name;
    const char *key;
};

static const struct HookIdentity HOOK_IDENTITIES[HOOK_INDEX_COUNT] = {
    {"GameLog_Printf",       "game_log_printf"     },
    {"GameLog_Raw",          "game_log_raw"        },
    {"OnServerDataResponse", "server_data_response"},
    {"HttpClient_Post",      "http_client_post"    },
    {"Render_Frame",         "render_frame"        },
    {"Render_Submit",        "render_submit"       },
};

#endif /* __HOOK_PROTOCOL_H */
