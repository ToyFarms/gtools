/*
 * Fake ISA host for the Linux tests: a flat 1 MiB memory, recorded emits,
 * calls and sleeps. Built as a shared library by tests/test_hook_isa.py and
 * driven over ctypes.
 */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "isa_core.h"

#define HOST_MEM_BASE 0x100000ull
#define HOST_MEM_SIZE (1024u * 1024u)
#define HOST_DATA_BASE 0x200000ull
#define HOST_DATA_SIZE 4096u
#define HOST_MAX_EVENTS 256

struct HostEvent
{
    uint32_t kind;
    uint32_t size;
    uint8_t data[512];
};

struct Host
{
    uint8_t mem[HOST_MEM_SIZE];
    uint8_t data[HOST_DATA_SIZE];
    struct HostEvent events[HOST_MAX_EVENTS];
    uint32_t eventCount;
    uint32_t callCount;
    uint32_t sleepCount;
    uint64_t lastCallFn;
    uint64_t callResult;
    uint64_t nowValue;
    uint32_t protectedBase;
    uint32_t protectedSize;
    uint32_t writeFaults;
};

static int HostRead(void *ctx, uint64_t addr, uint32_t len, void *out)
{
    struct Host *host = (struct Host *)ctx;
    if (len > 8)
        return 0;
    if (addr < HOST_MEM_BASE || addr + len > HOST_MEM_BASE + HOST_MEM_SIZE)
        return 0;
    memcpy(out, host->mem + (addr - HOST_MEM_BASE), len);
    return 1;
}

static int HostWrite(void *ctx, uint64_t addr, uint32_t len, const void *in)
{
    struct Host *host = (struct Host *)ctx;
    if (len > 8)
        return 0;
    if (addr < HOST_MEM_BASE || addr + len > HOST_MEM_BASE + HOST_MEM_SIZE)
        return 0;
    if (host->protectedSize && addr >= host->protectedBase && addr + len <= host->protectedBase + host->protectedSize)
    {
        host->writeFaults++;
        return 0;
    }
    memcpy(host->mem + (addr - HOST_MEM_BASE), in, len);
    return 1;
}

static int HostEmit(void *ctx, uint32_t kind, uint64_t addr, uint32_t len)
{
    struct Host *host = (struct Host *)ctx;
    uint8_t scratch[ISA_EMIT_MAX];
    if (host->eventCount >= HOST_MAX_EVENTS)
        return 0;
    if (len > ISA_EMIT_MAX)
        return 0;
    if (len && !HostRead(ctx, addr, len, scratch))
        return 0;
    host->events[host->eventCount].kind = kind;
    host->events[host->eventCount].size = len;
    if (len)
        memcpy(host->events[host->eventCount].data, scratch, len);
    host->eventCount++;
    return 1;
}

static uint64_t HostNow(void *ctx)
{
    struct Host *host = (struct Host *)ctx;
    return ++host->nowValue;
}

static void HostSleep(void *ctx, uint64_t us)
{
    (void)us;
    ((struct Host *)ctx)->sleepCount++;
}

static uint64_t HostCall(void *ctx, uint64_t fn, uint64_t a, uint64_t b, uint64_t c)
{
    struct Host *host = (struct Host *)ctx;
    (void)a;
    (void)b;
    (void)c;
    host->callCount++;
    host->lastCallFn = fn;
    return host->callResult;
}

static uint64_t HostDataPtr(void *ctx)
{
    return HOST_DATA_BASE;
}

static const struct IsaHost HOST_VTABLE = {
    NULL, HostRead, HostWrite, HostEmit, HostNow, HostSleep, HostCall, HostDataPtr,
};

void *host_create(void)
{
    struct Host *host = (struct Host *)calloc(1, sizeof(*host));
    return host;
}

void host_destroy(void *raw)
{
    free(raw);
}

int host_poke(void *raw, uint64_t addr, const uint8_t *data, uint32_t len)
{
    struct Host *host = (struct Host *)raw;
    if (addr < HOST_MEM_BASE || addr + len > HOST_MEM_BASE + HOST_MEM_SIZE)
        return 0;
    memcpy(host->mem + (addr - HOST_MEM_BASE), data, len);
    return 1;
}

int host_peek(void *raw, uint64_t addr, uint8_t *out, uint32_t len)
{
    struct Host *host = (struct Host *)raw;
    if (addr < HOST_MEM_BASE || addr + len > HOST_MEM_BASE + HOST_MEM_SIZE)
        return 0;
    memcpy(out, host->mem + (addr - HOST_MEM_BASE), len);
    return 1;
}

void host_protect(void *raw, uint64_t base, uint64_t size)
{
    struct Host *host = (struct Host *)raw;
    host->protectedBase = (uint32_t)base;
    host->protectedSize = (uint32_t)size;
}

uint32_t host_write_faults(void *raw)
{
    return ((struct Host *)raw)->writeFaults;
}

/* regs must point at ISA_REGS uint64 values */
int host_run(void *raw, const uint8_t *code, uint32_t codeLen, uint64_t *regs, uint32_t maxSteps)
{
    struct Host *host = (struct Host *)raw;
    struct IsaHost vtable = HOST_VTABLE;
    vtable.ctx = host;
    return (int)isa_run(&vtable, code, codeLen, regs, maxSteps);
}

int host_verify(const uint8_t *code, uint32_t codeLen, char *err, uint32_t errCap)
{
    return isa_verify(code, codeLen, err, errCap);
}

uint32_t host_emit_count(void *raw)
{
    return ((struct Host *)raw)->eventCount;
}

int host_emit_at(void *raw, uint32_t index, uint32_t *kind, uint8_t *buf, uint32_t cap)
{
    struct Host *host = (struct Host *)raw;
    if (index >= host->eventCount)
        return 0;
    *kind = host->events[index].kind;
    if (host->events[index].size > cap)
        return 0;
    memcpy(buf, host->events[index].data, host->events[index].size);
    return (int)host->events[index].size;
}

void host_set_call_result(void *raw, uint64_t value)
{
    ((struct Host *)raw)->callResult = value;
}

uint32_t host_call_count(void *raw)
{
    return ((struct Host *)raw)->callCount;
}

uint64_t host_last_call_fn(void *raw)
{
    return ((struct Host *)raw)->lastCallFn;
}

uint32_t host_sleep_count(void *raw)
{
    return ((struct Host *)raw)->sleepCount;
}

uint64_t host_now_value(void *raw)
{
    return ((struct Host *)raw)->nowValue;
}

uint64_t host_data_base(void)
{
    return HOST_DATA_BASE;
}

uint64_t host_mem_base(void)
{
    return HOST_MEM_BASE;
}
