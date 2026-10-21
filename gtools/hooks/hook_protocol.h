#ifndef __HOOK_PROTOCOL_H
#define __HOOK_PROTOCOL_H

#include <stdint.h>

#define HOOK_PROTOCOL_VERSION 1u
#define HOOK_PROTOCOL_MAGIC   0x4B485447u /* "GTHK" */
#define HOOK_PIPE_NAME        "\\\\.\\pipe\\gtools_hook"

#define HOOK_MAX_ENTRIES    8
#define HOOK_ENTRY_NAME_MAX 32

#define HOOK_ENTRY_PATCH_BYTES 14

#pragma pack(push, 1)

struct HookEntry
{
    uint64_t target;
    uint64_t detour;
    uint32_t stolenBytes;
    uint32_t entryPatchBytes;
    char name[HOOK_ENTRY_NAME_MAX];
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

#pragma pack(pop)

#endif /* __HOOK_PROTOCOL_H */
