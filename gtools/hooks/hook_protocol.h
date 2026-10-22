#ifndef __HOOK_PROTOCOL_H
#define __HOOK_PROTOCOL_H

#include <stdint.h>
#include <windows.h>

#define HOOK_PROTOCOL_VERSION 2u
#define HOOK_PROTOCOL_MAGIC   0x4B485447u /* "GTHK" */
#define HOOK_PIPE_NAME        "\\\\.\\pipe\\gtools_hook"
#ifndef HOOK_SECTION_NAME
#define HOOK_SECTION_NAME     "Global\\gtools_hook_section"
#endif
#ifndef HOOK_AGENT_MUTEX_NAME
#define HOOK_AGENT_MUTEX_NAME "Global\\gtools_hook_agent"
#endif
#define HOOK_PID_MUTEX_PREFIX "Global\\gtools_hook_pid_"
#define HOOK_LOCK_MUTEX_PREFIX "Global\\gtools_hook_lock_"

#define HOOK_MAX_ENTRIES    8
#define HOOK_ENTRY_NAME_MAX 32
#define HOOK_ENTRY_KEY_MAX  32

#define HOOK_ENTRY_PATCH_BYTES 14

/* fixed hook identity: the shim only fills detour, the injector fills the rest */
#define HOOK_INDEX_GAME_LOG_PRINTF 0
#define HOOK_INDEX_GAME_LOG_RAW    1
#define HOOK_INDEX_RESPONSE        2
#define HOOK_INDEX_HTTP_POST       3
#define HOOK_INDEX_COUNT           4

enum HookEntryStatus
{
    HOOK_STATUS_MISSING = 0,
    HOOK_STATUS_READY   = 1,
    HOOK_STATUS_PATCHED = 2,
};

/* log slot lifetime */
#define HOOK_SLOT_EMPTY   0
#define HOOK_SLOT_CLAIMED 1
#define HOOK_SLOT_READY   2

/* verbosity levels, higher is chattier; HOOK_LOG_GAME is a game log line the
   agent always forwards when streaming is on, regardless of the gate */
#define HOOK_LOG_ERROR 0
#define HOOK_LOG_INFO  1
#define HOOK_LOG_TRACE 2
#define HOOK_LOG_GAME  3

#define HOOK_LOG_SLOTS 128
#define HOOK_LOG_LINE  512

#define HOOK_TEXT_FIELD_MAX 128
#define HOOK_FIELD_MAX      64

/* handshake only travels hex encoded on the pipe and nobody parses the
   fields from python, so it needs no packing either */
struct HookEntry
{
    uint64_t target;     /* inside the game, written by the injector */
    uint64_t detour;     /* inside the shim, written by the shim */
    uint64_t trampoline; /* inside the game, written by the injector */
    uint32_t stolenBytes;
    uint32_t entryPatchBytes;
    LONG     status;     /* enum HookEntryStatus */
    char     name[HOOK_ENTRY_NAME_MAX];
    char     key[HOOK_ENTRY_KEY_MAX];
};

struct HookSettings
{
    char proxyHost[HOOK_TEXT_FIELD_MAX];
    int  proxyPort;
    int  startDelayMs;
    int  logLevel;
    int  allowAnyModule;
    int  streamGameLogs;

    /* captured from the client, read only */
    char clientVersion[HOOK_FIELD_MAX];
    char clientProtocol[HOOK_FIELD_MAX];
    char clientPlatform[HOOK_FIELD_MAX];
    char realServer[HOOK_FIELD_MAX];
    int  realPort;
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

/* one log line handed from the shim to the agent */
struct HookSlot
{
    volatile LONG state; /* HOOK_SLOT_* */
    LONG sequence;       /* ticket drawn from logTicket, unique per line */
    DWORD threadId;
    int level;           /* HOOK_LOG_* */
    char text[HOOK_LOG_LINE];
};

/* the shared memory: created by the agent, published into by the shim,
   read and completed by the injector. the shim keeps its mapping handle
   open so the section survives the agent process dying. */
struct HookShared
{
    volatile LONG magic;   /* HOOK_PROTOCOL_MAGIC */
    uint32_t      version; /* HOOK_PROTOCOL_VERSION */
    volatile LONG ready;   /* 1 once the shim published everything */
    int32_t       reserved;

    uint64_t      processId;
    uint64_t      imageBase;
    uint64_t      imageSize;
    uint64_t      dllBase;
    uint64_t      bootTick;

    struct HookEntry entries[HOOK_MAX_ENTRIES];
    volatile LONG    entryCount;

    /* guards struct HookSettings: 0 = free, 1 = held */
    volatile LONG settingsLock;
    struct HookSettings settings;

    volatile LONG   logTicket; /* incremented per published line */
    struct HookSlot log[HOOK_LOG_SLOTS];
};

struct HookIdentity
{
    const char *name;
    const char *key;
    uint32_t stolenBytes;
};

/* static per translation unit on purpose, it is tiny */
static const struct HookIdentity HOOK_IDENTITIES[HOOK_INDEX_COUNT] = {
    {"GameLog_Printf",       "game_log_printf",      27},
    {"GameLog_Raw",          "game_log_raw",         27},
    {"OnServerDataResponse", "server_data_response", 17},
    {"HttpClient_Post",      "http_client_post",     21},
};

#endif /* __HOOK_PROTOCOL_H */
