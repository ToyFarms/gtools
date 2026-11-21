/*
 * hook_prologue.h - x86-64 instruction length decoder for prologue validation.
 *
 * Pure byte math, no OS includes: the shim uses it to prove that the bytes a
 * hook steals (the patch is a 14-byte absolute jump) end on an instruction
 * boundary and contain nothing that breaks when relocated into the trampoline.
 * Anything not understood is rejected (fail closed); tests/test_hook_prologue.py
 * exercises the decoder on Linux against encodings produced by the system
 * assembler.
 *
 * Rejected:
 *   - unknown/invalid encodings
 *   - relative branches (E8/E9/EB/E0-E3, 70-7F, 0F 8x) and indirect call/jmp
 *   - RIP-relative memory operands (mod=00, rm=101)
 *   - VEX/EVEX and three-byte opcodes
 */
#ifndef __HOOK_PROLOGUE_H
#define __HOOK_PROLOGUE_H

#include <stdint.h>
#include <stddef.h>

/* advance past the ModRM/SIB/disp of an instruction whose opcode byte is at
   index i; returns the new index, or 0 to reject (rip-relative or truncated) */
static size_t hook_modrm_length(const uint8_t *code, size_t i, size_t avail, int rex)
{
    uint8_t modrm, mod, rm;
    (void)rex;
    if (i >= avail)
        return 0;
    modrm = code[i++];
    mod = (uint8_t)(modrm >> 6);
    rm = (uint8_t)(modrm & 7);
    if (mod == 3)
        return i;
    if (rm == 4)
    { /* SIB byte follows */
        uint8_t sib, base;
        if (i >= avail)
            return 0;
        sib = code[i++];
        base = (uint8_t)(sib & 7);
        if (mod == 0 && base == 5)
        { /* disp32 with no base (absolute, relocatable) */
            if (i + 4 > avail)
                return 0;
            i += 4;
        }
    }
    else if (mod == 0 && rm == 5)
    {
        return 0; /* rip-relative: relocation would change its meaning */
    }
    if (mod == 1)
    {
        if (i + 1 > avail)
            return 0;
        i += 1;
    }
    else if (mod == 2)
    {
        if (i + 4 > avail)
            return 0;
        i += 4;
    }
    return i;
}

/* length of one instruction starting at code, or 0 to reject */
static size_t hook_insn_length(const uint8_t *code, size_t avail)
{
    size_t i = 0;
    int rex = 0;
    size_t osz = 4; /* immediate size for the 66-sensitive forms */

    if (avail == 0)
        return 0;

    for (;;)
    {
        uint8_t b;
        if (i >= avail)
            return 0;
        b = code[i];
        if (b == 0x66)
        {
            osz = 2;
            i++;
            continue;
        }
        if (b == 0x67 || b == 0x2E || b == 0x3E || b == 0x26 || b == 0x36 || b == 0x64 || b == 0x65 || b == 0xF0 ||
            b == 0xF2 || b == 0xF3)
        {
            i++;
            continue;
        }
        if ((b & 0xF0) == 0x40)
        {
            rex = b;
            i++;
            continue;
        }
        break;
    }

    if (i >= avail)
        return 0;
    {
        uint8_t op = code[i++];
        switch (op)
        {
        case 0x0F: /* two-byte opcodes */
        {
            uint8_t op2;
            if (i >= avail)
                return 0;
            op2 = code[i++];
            if (op2 == 0x0B || op2 == 0x38 || op2 == 0x3A || op2 == 0x0A || op2 == 0xA6 || op2 == 0xA7)
                return 0;
            if (op2 >= 0x80 && op2 <= 0x8F) /* jcc rel32 */
                return 0;
            if (op2 == 0x71 || op2 == 0x72 || op2 == 0x73 || op2 == 0xBA || op2 == 0xA4 || op2 == 0xAC)
            { /* modrm + imm8 */
                size_t m = hook_modrm_length(code, i, avail, rex);
                return (m && m < avail) ? m + 1 : 0;
            }
            if ((op2 >= 0x30 && op2 <= 0x37) || (op2 >= 0xC8 && op2 <= 0xCF) || op2 == 0x06 || op2 == 0x07 ||
                op2 == 0x08 || op2 == 0x09 || op2 == 0xA0 || op2 == 0xA1 || op2 == 0xA8 || op2 == 0xA9 || op2 == 0xAA)
                return i; /* no modrm */
            return hook_modrm_length(code, i, avail, rex);
        }
        case 0x04: case 0x0C: case 0x14: case 0x1C: case 0x24: case 0x2C: case 0x34: case 0x3C:
        case 0xA8: /* AL, imm8 */
            return i + 1;
        case 0x05: case 0x0D: case 0x15: case 0x1D: case 0x25: case 0x2D: case 0x35: case 0x3D:
        case 0xA9: /* eAX, imm */
            return i + osz;
        case 0x6A: /* push imm8 */
            return i + 1;
        case 0x68: /* push imm */
            return i + osz;
        case 0x69: /* imul r, r/m, imm */
        {
            size_t m = hook_modrm_length(code, i, avail, rex);
            return (m && m + osz <= avail) ? m + osz : 0;
        }
        case 0x6B: /* imul r, r/m, imm8 */
        {
            size_t m = hook_modrm_length(code, i, avail, rex);
            return (m && m < avail) ? m + 1 : 0;
        }
        /* branches and invalid encodings: reject outright */
        case 0x70: case 0x71: case 0x72: case 0x73: case 0x74: case 0x75: case 0x76: case 0x77:
        case 0x78: case 0x79: case 0x7A: case 0x7B: case 0x7C: case 0x7D: case 0x7E: case 0x7F:
        case 0x9A: case 0xCE: case 0xCF: case 0xF1: case 0xF4:
        case 0xE0: case 0xE1: case 0xE2: case 0xE3: case 0xE8: case 0xE9: case 0xEA: case 0xEB:
        case 0x60: case 0x61: case 0x62: case 0xC4: case 0xC5:
        case 0x27: case 0x2F: case 0x37: case 0x3F: case 0xD4: case 0xD5: case 0xD6: case 0xD7:
            return 0;
        case 0x80: /* group 1, imm8 */
        {
            size_t m = hook_modrm_length(code, i, avail, rex);
            return (m && m < avail) ? m + 1 : 0;
        }
        case 0x81: /* group 1, imm */
        {
            size_t m = hook_modrm_length(code, i, avail, rex);
            return (m && m + osz <= avail) ? m + osz : 0;
        }
        case 0x82: /* invalid in long mode */
            return 0;
        case 0x83: /* group 1, imm8 sign extended */
        {
            size_t m = hook_modrm_length(code, i, avail, rex);
            return (m && m < avail) ? m + 1 : 0;
        }
        case 0xA0: case 0xA1: case 0xA2: case 0xA3: /* moffs64 */
            return i + 8;
        case 0xB0: case 0xB1: case 0xB2: case 0xB3: case 0xB4: case 0xB5: case 0xB6: case 0xB7:
            return i + 1;
        case 0xB8: case 0xB9: case 0xBA: case 0xBB: case 0xBC: case 0xBD: case 0xBE: case 0xBF:
            return i + ((rex & 8) ? 8 : osz);
        case 0xC0: case 0xC1: /* shift group, imm8 */
        {
            size_t m = hook_modrm_length(code, i, avail, rex);
            return (m && m < avail) ? m + 1 : 0;
        }
        case 0xC2: /* ret imm16 */
            return i + 2;
        case 0xC6: /* mov r/m8, imm8 */
        {
            size_t m = hook_modrm_length(code, i, avail, rex);
            return (m && m < avail) ? m + 1 : 0;
        }
        case 0xC7: /* mov r/m, imm */
        {
            size_t m = hook_modrm_length(code, i, avail, rex);
            return (m && m + osz <= avail) ? m + osz : 0;
        }
        case 0xC8: /* enter imm16, imm8 */
            return i + 3;
        case 0xD0: case 0xD1: case 0xD2: case 0xD3: /* shift group */
        case 0xD8: case 0xD9: case 0xDA: case 0xDB: case 0xDC: case 0xDD: case 0xDE: case 0xDF:
            return hook_modrm_length(code, i, avail, rex);
        case 0xE4: case 0xE5: case 0xE6: case 0xE7: /* in/out imm8 */
            return i + 1;
        case 0xEC: case 0xED: case 0xEE: case 0xEF: /* in/out */
            return i;
        case 0xF6: /* group 3, imm8 for test forms */
        {
            uint8_t modrm;
            size_t m;
            if (i >= avail)
                return 0;
            modrm = code[i];
            m = hook_modrm_length(code, i, avail, rex);
            if (!m)
                return 0;
            return (((modrm >> 3) & 7) <= 1) ? ((m < avail) ? m + 1 : 0) : m;
        }
        case 0xF7: /* group 3, imm for test forms */
        {
            uint8_t modrm;
            size_t m;
            if (i >= avail)
                return 0;
            modrm = code[i];
            m = hook_modrm_length(code, i, avail, rex);
            if (!m)
                return 0;
            return (((modrm >> 3) & 7) <= 1) ? ((m + osz <= avail) ? m + osz : 0) : m;
        }
        case 0xFE: /* inc/dec r/m8 only */
        {
            uint8_t modrm;
            if (i >= avail)
                return 0;
            modrm = code[i];
            if (((modrm >> 3) & 7) >= 6)
                return 0;
            return hook_modrm_length(code, i, avail, rex);
        }
        case 0xFF: /* no call/jmp via this stub */
        {
            uint8_t modrm;
            if (i >= avail)
                return 0;
            modrm = code[i];
            switch ((modrm >> 3) & 7)
            {
            case 2: case 3: case 4: case 5: case 7:
                return 0;
            default:
                return hook_modrm_length(code, i, avail, rex);
            }
        }
        default:
            /* no-modrm single byte ops */
            if ((op >= 0x50 && op <= 0x5F) || op == 0x90 || op == 0x98 || op == 0x99 || op == 0x9B ||
                (op >= 0x9C && op <= 0x9F) || (op >= 0xA4 && op <= 0xA7) || (op >= 0xAA && op <= 0xAF) ||
                op == 0xC3 || op == 0xC9 || op == 0xCC || op == 0xF5 || op == 0xF8 || op == 0xF9 ||
                op == 0xFA || op == 0xFB || op == 0xFC || op == 0xFD)
                return i;
            /* modrm forms: 00-3F with (op & 7) <= 3, 63, 84-8F */
            if ((op < 0x40 && (op & 7) <= 3) || op == 0x63 || (op >= 0x84 && op <= 0x8F))
                return hook_modrm_length(code, i, avail, rex);
            return 0; /* unknown -> reject */
        }
    }
}

/* walks instructions from code until at least minBytes sit on an instruction
   boundary; returns the covered length, or 0 when a rejection occurs first */
static size_t hook_prologue_length(const uint8_t *code, size_t avail, size_t minBytes)
{
    size_t total = 0;
    while (total < minBytes)
    {
        size_t len;
        if (total >= avail)
            return 0;
        len = hook_insn_length(code + total, avail - total);
        if (len == 0 || total + len > avail)
            return 0;
        total += len;
    }
    return total;
}

#endif /* __HOOK_PROLOGUE_H */
