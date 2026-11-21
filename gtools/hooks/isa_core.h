/*
 * isa_core.h - the portable hook ISA: instruction format, verifier, interpreter.
 *
 * No Windows (or any OS) includes: hook.c includes this and supplies the host
 * callbacks; tests include this and supply a fake flat-memory host. The Python
 * side (gtools/hooks/isa.py) must mirror every constant and the 16-byte
 * instruction encoding byte for byte; tests/test_hook_isa.py asserts that.
 *
 * Program contract:
 *   - fixed-arity hook entry only (variadic AL count is not preserved by the
 *     stub; printf-style hooks use a compiled varargs detour instead)
 *   - registers r0..r11 are the program's; r12..r15 are preloaded by the host:
 *       r12 = scratch size in bytes
 *       r13 = &scratch[0]
 *       r14 = &HookRuntime (state/data, agent-writable)
 *       r15 = &HookCtx (saved game registers; ctx layout is shim knowledge)
 *   - the program ends with RET (action = pass) or ACTION(skip), which stops
 *     the interpreter and overrides the return value with r0
 *   - every memory access goes through the host's validated read/write, so a
 *     bad pointer faults the hook, not the game
 */
#ifndef __HOOK_ISA_CORE_H
#define __HOOK_ISA_CORE_H

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>

#define ISA_VERSION        1u
#define ISA_INSN_SIZE      16u
#define ISA_MAX_INSNS      512u
#define ISA_MAX_STEPS      100000u
#define ISA_REGS           16u
#define ISA_MEMCMP_MAX     256u
#define ISA_MEMCPY_MAX     4096u
#define ISA_EMIT_MAX       4096u
#define ISA_SLEEP_US_MAX   100000u
#define ISA_REG_FREE_MIN   0u  /* r0..r11 are the program's */
#define ISA_REG_FREE_MAX   11u
#define ISA_REG_RESERVED   12u /* r12..r15 preloaded by the host */

/* opcodes (keep in sync with gtools/hooks/isa.py) */
enum
{
    ISA_OP_NOP = 0,
    ISA_OP_MOVI,   /* r[dst] = imm                                     */
    ISA_OP_MOV,    /* r[dst] = r[src]                                  */
    ISA_OP_ADD,    /* r[dst] += r[src]                                 */
    ISA_OP_SUB,
    ISA_OP_AND,
    ISA_OP_OR,
    ISA_OP_XOR,
    ISA_OP_SHL,    /* r[dst] <<= r[src] & 63                           */
    ISA_OP_SHR,    /* logical                                          */
    ISA_OP_CMP,    /* flags from r[dst] - r[src]                       */
    ISA_OP_JMP,    /* imm = absolute instruction index                 */
    ISA_OP_JEQ,
    ISA_OP_JNE,
    ISA_OP_JLT,    /* signed                                           */
    ISA_OP_JLE,
    ISA_OP_JGT,
    ISA_OP_JGE,
    ISA_OP_JLTU,   /* unsigned                                         */
    ISA_OP_JGTU,
    ISA_OP_LDR8,   /* r[dst] = zext( [r[src] + (int32)aux] )           */
    ISA_OP_LDR16,
    ISA_OP_LDR32,
    ISA_OP_LDR64,
    ISA_OP_LDRS8,  /* sign-extended                                    */
    ISA_OP_LDRS16,
    ISA_OP_LDRS32,
    ISA_OP_STR8,   /* (uint8)[r[dst] + (int32)aux] = r[src]            */
    ISA_OP_STR16,
    ISA_OP_STR32,
    ISA_OP_STR64,
    ISA_OP_CALLH,  /* helper id in aux; args r1..r4; result r0         */
    ISA_OP_ACTION, /* imm: 0 = pass, 1 = skip with return value r[0]   */
    ISA_OP_RET,    /* end of program, action = pass                    */
    ISA_OP_HLT,    /* alias of RET for readability                     */
    ISA_OP_COUNT
};

/* helper table (id in CALLH aux; append-only across protocol versions) */
enum
{
    ISA_H_MEMCMP = 0, /* r1=addrA r2=addrB r3=len      -> r0: 0 eq / 1 a>b / 2 a<b / 0xFFFFFFFF fault */
    ISA_H_EMIT = 1,   /* r1=kind r2=addr r3=len        -> r0: 1 ok / 0 dropped                        */
    ISA_H_NOW_MS = 2, /*                               -> r0: ms                                      */
    ISA_H_SLEEP_US = 3, /* r1=us (capped)              -> r0: 1                                       */
    ISA_H_CALL = 4,   /* r1=fn r2=a r3=b r4=c          -> r0: rax                                     */
    ISA_H_DATA_PTR = 5, /*                             -> r0: &runtime->data                          */
    ISA_H_MEMCPY = 6, /* r1=dst r2=src r3=len (capped) -> r0: len / 0 fault                           */
    ISA_HELPER_COUNT
};

/* runtime states */
enum IsaRunResult
{
    ISA_RUN_PASS = 0,       /* continue to the trampoline */
    ISA_RUN_SKIP = 1,       /* return r0 instead of calling the trampoline */
    ISA_RUN_FAULT = 2,      /* bad access / bad helper use; host should fail open */
    ISA_RUN_STEPLIMIT = 3,  /* ran too long; fail open */
    ISA_RUN_BADPROGRAM = 4  /* rejected by the verifier; never runs */
};

struct IsaInsn
{
    uint16_t op;
    uint8_t dst;
    uint8_t src;
    int32_t aux;   /* memory offset (signed), helper id, unused */
    uint64_t imm;  /* immediate / absolute jump target */
};

struct IsaHost
{
    void *ctx;
    /* all return 1 on success, 0 on fault */
    int (*mem_read)(void *ctx, uint64_t addr, uint32_t len, void *out);
    int (*mem_write)(void *ctx, uint64_t addr, uint32_t len, const void *in);
    int (*emit)(void *ctx, uint32_t kind, uint64_t addr, uint32_t len);
    uint64_t (*now_ms)(void *ctx);
    void (*sleep_us)(void *ctx, uint64_t us);
    uint64_t (*call)(void *ctx, uint64_t fn, uint64_t a, uint64_t b, uint64_t c);
    uint64_t (*data_ptr)(void *ctx);
};

static uint16_t IsaLoad16(const uint8_t *p)
{
    return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t IsaLoad32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint64_t IsaLoad64(const uint8_t *p)
{
    return (uint64_t)IsaLoad32(p) | ((uint64_t)IsaLoad32(p + 4) << 32);
}

static void IsaStore16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v & 0xFF);
    p[1] = (uint8_t)(v >> 8);
}

static void IsaStore32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v & 0xFF);
    p[1] = (uint8_t)((v >> 8) & 0xFF);
    p[2] = (uint8_t)((v >> 16) & 0xFF);
    p[3] = (uint8_t)((v >> 24) & 0xFF);
}

static void IsaStore64(uint8_t *p, uint64_t v)
{
    IsaStore32(p, (uint32_t)(v & 0xFFFFFFFFu));
    IsaStore32(p + 4, (uint32_t)(v >> 32));
}

static void IsaEncode(uint8_t *out, uint16_t op, uint8_t dst, uint8_t src, int32_t aux, uint64_t imm)
{
    IsaStore16(out, op);
    out[2] = dst;
    out[3] = src;
    IsaStore32(out + 4, (uint32_t)aux);
    IsaStore64(out + 8, imm);
}

static void IsaDecode(const uint8_t *code, uint32_t index, struct IsaInsn *out)
{
    const uint8_t *p = code + (size_t)index * ISA_INSN_SIZE;
    out->op = IsaLoad16(p);
    out->dst = p[2];
    out->src = p[3];
    out->aux = (int32_t)IsaLoad32(p + 4);
    out->imm = IsaLoad64(p + 8);
}

/*
 * Verify a program without running it. Returns 1 when valid; on failure returns
 * 0 and writes a short reason into err (always NUL terminated).
 */
static int isa_verify(const uint8_t *code, uint32_t codeLen, char *err, uint32_t errCap)
{
#define ISA_FAIL(...)                                                     \
    do                                                                    \
    {                                                                     \
        if (err && errCap)                                                \
        {                                                                 \
            int _n = snprintf(err, errCap, __VA_ARGS__);                  \
            (void)_n;                                                     \
            err[errCap - 1] = 0;                                          \
        }                                                                 \
        return 0;                                                         \
    } while (0)

    uint32_t count;
    uint32_t i;

    if (err && errCap)
        err[0] = 0;
    if (codeLen % ISA_INSN_SIZE != 0)
        ISA_FAIL("program length %u is not a multiple of %u", codeLen, ISA_INSN_SIZE);
    count = codeLen / ISA_INSN_SIZE;
    if (count == 0)
        ISA_FAIL("empty program");
    if (count > ISA_MAX_INSNS)
        ISA_FAIL("program has %u instructions, max is %u", count, ISA_MAX_INSNS);

    for (i = 0; i < count; i++)
    {
        struct IsaInsn insn;
        IsaDecode(code, i, &insn);
        if (insn.op >= ISA_OP_COUNT)
            ISA_FAIL("instruction %u: unknown opcode %u", i, (unsigned)insn.op);
        if (insn.dst >= ISA_REGS)
            ISA_FAIL("instruction %u: dst register %u out of range", i, (unsigned)insn.dst);
        if (insn.src >= ISA_REGS)
            ISA_FAIL("instruction %u: src register %u out of range", i, (unsigned)insn.src);

        switch (insn.op)
        {
        case ISA_OP_JMP:
        case ISA_OP_JEQ:
        case ISA_OP_JNE:
        case ISA_OP_JLT:
        case ISA_OP_JLE:
        case ISA_OP_JGT:
        case ISA_OP_JGE:
        case ISA_OP_JLTU:
        case ISA_OP_JGTU:
            if (insn.imm >= count)
                ISA_FAIL("instruction %u: jump target %llu out of range", i, (unsigned long long)insn.imm);
            break;
        case ISA_OP_CALLH:
            if (insn.aux < 0 || (uint32_t)insn.aux >= ISA_HELPER_COUNT)
                ISA_FAIL("instruction %u: unknown helper %d", i, insn.aux);
            break;
        case ISA_OP_MOVI:
        case ISA_OP_MOV:
        case ISA_OP_ADD:
        case ISA_OP_SUB:
        case ISA_OP_AND:
        case ISA_OP_OR:
        case ISA_OP_XOR:
        case ISA_OP_SHL:
        case ISA_OP_SHR:
        case ISA_OP_CMP:
        case ISA_OP_LDR8:
        case ISA_OP_LDR16:
        case ISA_OP_LDR32:
        case ISA_OP_LDR64:
        case ISA_OP_LDRS8:
        case ISA_OP_LDRS16:
        case ISA_OP_LDRS32:
        case ISA_OP_STR8:
        case ISA_OP_STR16:
        case ISA_OP_STR32:
        case ISA_OP_STR64:
        case ISA_OP_ACTION:
        case ISA_OP_RET:
        case ISA_OP_HLT:
        case ISA_OP_NOP:
            break;
        default:
            ISA_FAIL("instruction %u: unhandled opcode %u", i, (unsigned)insn.op);
        }
    }

    /* must terminate: last instruction is a terminator or an ACTION */
    {
        struct IsaInsn last;
        IsaDecode(code, count - 1, &last);
        if (last.op != ISA_OP_RET && last.op != ISA_OP_HLT && last.op != ISA_OP_ACTION)
            ISA_FAIL("program does not end with RET/ACTION");
    }

#undef ISA_FAIL
    return 1;
}

static int IsaMemoryWidth(uint16_t op)
{
    switch (op)
    {
    case ISA_OP_LDR8:
    case ISA_OP_LDRS8:
    case ISA_OP_STR8:
        return 1;
    case ISA_OP_LDR16:
    case ISA_OP_LDRS16:
    case ISA_OP_STR16:
        return 2;
    case ISA_OP_LDR32:
    case ISA_OP_LDRS32:
    case ISA_OP_STR32:
        return 4;
    case ISA_OP_LDR64:
    case ISA_OP_STR64:
        return 8;
    default:
        return 0;
    }
}

/* runs one helper; returns 1 when r0 was produced, 0 on fault */
static int IsaRunHelper(const struct IsaHost *host, uint32_t id, uint64_t *regs)
{
    uint64_t arg1 = regs[1];
    uint64_t arg2 = regs[2];
    uint64_t arg3 = regs[3];
    uint64_t arg4 = regs[4];

    switch (id)
    {
    case ISA_H_MEMCMP:
    {
        uint8_t left[ISA_MEMCMP_MAX];
        uint8_t right[ISA_MEMCMP_MAX];
        uint32_t len = (uint32_t)(arg3 > ISA_MEMCMP_MAX ? ISA_MEMCMP_MAX : arg3);
        uint32_t i;
        if (!len)
        {
            regs[0] = 0;
            return 1;
        }
        if (len > ISA_MEMCMP_MAX || !host->mem_read || !host->mem_read(host->ctx, arg1, len, left) ||
            !host->mem_read(host->ctx, arg2, len, right))
            return 0;
        for (i = 0; i < len; i++)
        {
            if (left[i] != right[i])
            {
                regs[0] = (left[i] > right[i]) ? 1 : 2;
                return 1;
            }
        }
        regs[0] = 0;
        return 1;
    }
    case ISA_H_EMIT:
    {
        uint32_t len = (uint32_t)(arg3 > ISA_EMIT_MAX ? ISA_EMIT_MAX : arg3);
        regs[0] = (host->emit && host->emit(host->ctx, (uint32_t)arg1, arg2, len)) ? 1 : 0;
        return 1;
    }
    case ISA_H_NOW_MS:
        regs[0] = host->now_ms ? host->now_ms(host->ctx) : 0;
        return 1;
    case ISA_H_SLEEP_US:
        if (host->sleep_us)
            host->sleep_us(host->ctx, arg1 > ISA_SLEEP_US_MAX ? ISA_SLEEP_US_MAX : arg1);
        regs[0] = 1;
        return 1;
    case ISA_H_CALL:
        regs[0] = host->call ? host->call(host->ctx, arg1, arg2, arg3, arg4) : 0;
        return 1;
    case ISA_H_DATA_PTR:
        regs[0] = host->data_ptr ? host->data_ptr(host->ctx) : 0;
        return 1;
    case ISA_H_MEMCPY:
    {
        static uint8_t IsaCopyScratch[ISA_MEMCPY_MAX];
        uint32_t len = (uint32_t)(arg3 > ISA_MEMCPY_MAX ? ISA_MEMCPY_MAX : arg3);
        if (!len)
        {
            regs[0] = 0;
            return 1;
        }
        if (len > ISA_MEMCPY_MAX || !host->mem_read || !host->mem_write ||
            !host->mem_read(host->ctx, arg2, len, IsaCopyScratch) ||
            !host->mem_write(host->ctx, arg1, len, IsaCopyScratch))
            return 0;
        regs[0] = len;
        return 1;
    }
    default:
        return 0;
    }
}

/*
 * Interpret a program. regs must be preloaded by the caller (r12..r15);
 * they are updated in place. Returns the run result; regs[0] carries the
 * skip return value when the result is ISA_RUN_SKIP.
 */
static enum IsaRunResult isa_run(const struct IsaHost *host, const uint8_t *code, uint32_t codeLen,
                                 uint64_t *regs, uint32_t maxSteps)
{
    uint32_t count = codeLen / ISA_INSN_SIZE;
    uint32_t pc = 0;
    uint32_t steps = 0;
    int eq = 0, lt = 0, gt = 0;

    if (codeLen % ISA_INSN_SIZE != 0 || count == 0 || count > ISA_MAX_INSNS)
        return ISA_RUN_BADPROGRAM;

    for (;;)
    {
        struct IsaInsn insn;
        int width;

        if (steps++ >= maxSteps)
            return ISA_RUN_STEPLIMIT;
        if (pc >= count)
            return ISA_RUN_FAULT;

        IsaDecode(code, pc, &insn);
        pc++;

        switch (insn.op)
        {
        case ISA_OP_NOP:
            break;
        case ISA_OP_MOVI:
            regs[insn.dst] = insn.imm;
            break;
        case ISA_OP_MOV:
            regs[insn.dst] = regs[insn.src];
            break;
        case ISA_OP_ADD:
            regs[insn.dst] += regs[insn.src];
            break;
        case ISA_OP_SUB:
            regs[insn.dst] -= regs[insn.src];
            break;
        case ISA_OP_AND:
            regs[insn.dst] &= regs[insn.src];
            break;
        case ISA_OP_OR:
            regs[insn.dst] |= regs[insn.src];
            break;
        case ISA_OP_XOR:
            regs[insn.dst] ^= regs[insn.src];
            break;
        case ISA_OP_SHL:
            regs[insn.dst] <<= (regs[insn.src] & 63);
            break;
        case ISA_OP_SHR:
            regs[insn.dst] >>= (regs[insn.src] & 63);
            break;
        case ISA_OP_CMP:
        {
            int64_t diff = (int64_t)(regs[insn.dst] - regs[insn.src]);
            eq = (regs[insn.dst] == regs[insn.src]);
            lt = (diff < 0);
            gt = (diff > 0);
            break;
        }
        case ISA_OP_JMP:
            pc = (uint32_t)insn.imm;
            break;
        case ISA_OP_JEQ:
            if (eq)
                pc = (uint32_t)insn.imm;
            break;
        case ISA_OP_JNE:
            if (!eq)
                pc = (uint32_t)insn.imm;
            break;
        case ISA_OP_JLT:
            if (lt)
                pc = (uint32_t)insn.imm;
            break;
        case ISA_OP_JLE:
            if (lt || eq)
                pc = (uint32_t)insn.imm;
            break;
        case ISA_OP_JGT:
            if (gt)
                pc = (uint32_t)insn.imm;
            break;
        case ISA_OP_JGE:
            if (gt || eq)
                pc = (uint32_t)insn.imm;
            break;
        case ISA_OP_JLTU:
            if (regs[insn.dst] < regs[insn.src])
                pc = (uint32_t)insn.imm;
            break;
        case ISA_OP_JGTU:
            if (regs[insn.dst] > regs[insn.src])
                pc = (uint32_t)insn.imm;
            break;
        case ISA_OP_LDR8:
        case ISA_OP_LDR16:
        case ISA_OP_LDR32:
        case ISA_OP_LDR64:
        case ISA_OP_LDRS8:
        case ISA_OP_LDRS16:
        case ISA_OP_LDRS32:
        {
            uint8_t raw[8];
            uint64_t addr = regs[insn.src] + (uint64_t)(int64_t)insn.aux;
            width = IsaMemoryWidth(insn.op);
            if (!host->mem_read || !host->mem_read(host->ctx, addr, (uint32_t)width, raw))
                return ISA_RUN_FAULT;
            switch (insn.op)
            {
            case ISA_OP_LDR8:
                regs[insn.dst] = raw[0];
                break;
            case ISA_OP_LDR16:
                regs[insn.dst] = IsaLoad16(raw);
                break;
            case ISA_OP_LDR32:
                regs[insn.dst] = IsaLoad32(raw);
                break;
            case ISA_OP_LDR64:
                regs[insn.dst] = IsaLoad64(raw);
                break;
            case ISA_OP_LDRS8:
                regs[insn.dst] = (uint64_t)(int64_t)(int8_t)raw[0];
                break;
            case ISA_OP_LDRS16:
                regs[insn.dst] = (uint64_t)(int64_t)(int16_t)IsaLoad16(raw);
                break;
            case ISA_OP_LDRS32:
                regs[insn.dst] = (uint64_t)(int64_t)(int32_t)IsaLoad32(raw);
                break;
            }
            break;
        }
        case ISA_OP_STR8:
        case ISA_OP_STR16:
        case ISA_OP_STR32:
        case ISA_OP_STR64:
        {
            uint8_t raw[8];
            uint64_t addr = regs[insn.dst] + (uint64_t)(int64_t)insn.aux;
            width = IsaMemoryWidth(insn.op);
            switch (width)
            {
            case 1:
                raw[0] = (uint8_t)regs[insn.src];
                break;
            case 2:
                IsaStore16(raw, (uint16_t)regs[insn.src]);
                break;
            case 4:
                IsaStore32(raw, (uint32_t)regs[insn.src]);
                break;
            case 8:
                IsaStore64(raw, regs[insn.src]);
                break;
            }
            if (!host->mem_write || !host->mem_write(host->ctx, addr, (uint32_t)width, raw))
                return ISA_RUN_FAULT;
            break;
        }
        case ISA_OP_CALLH:
            if (!IsaRunHelper(host, (uint32_t)insn.aux, regs))
                return ISA_RUN_FAULT;
            break;
        case ISA_OP_ACTION:
            if (insn.imm == 1)
                return ISA_RUN_SKIP;
            if (insn.imm != 0)
                return ISA_RUN_FAULT;
            return ISA_RUN_PASS;
        case ISA_OP_RET:
        case ISA_OP_HLT:
            return ISA_RUN_PASS;
        default:
            return ISA_RUN_FAULT;
        }
    }
}

#endif /* __HOOK_ISA_CORE_H */
