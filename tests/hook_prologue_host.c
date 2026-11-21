/* Exposes the prologue decoder to the Python tests. */
#include <stdio.h>
#include <stddef.h>

#include "hook_prologue.h"

unsigned long long host_insn_length(const unsigned char *code, unsigned long long avail)
{
    return (unsigned long long)hook_insn_length(code, (size_t)avail);
}

unsigned long long host_prologue_length(const unsigned char *code, unsigned long long avail,
                                        unsigned long long minBytes)
{
    return (unsigned long long)hook_prologue_length(code, (size_t)avail, (size_t)minBytes);
}
