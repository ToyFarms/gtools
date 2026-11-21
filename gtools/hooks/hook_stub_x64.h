/*
 * hook_stub_x64.h - the register-preserving detour stub (GNU as, x64).
 *
 * Layout of the generated code block (VirtualAlloc'd RWX -> RX):
 *
 *   [ hook_stub_template copy ]          shared by every hook
 *   [ thunk 0 ] [ thunk 1 ] ...          32 bytes per hook, built in C
 *
 * The thunk carries the hook identity and the disabled fast path:
 *
 *   49 BB <imm64 &runtime[i]>        mov r11, &runtime[i]
 *   41 83 BB <enabled_off> 00        cmp dword [r11+enabled], 0
 *   75 07                            jne enabled            (to the rel32 jmp)
 *   41 FF A3 <tramp_off>             jmp qword [r11+trampoline]  (disabled)
 *   E9 <rel32>                       jmp hook_stub_template      (enabled)
 *
 * The common stub saves the entry register state into a stack-allocated
 * HookCtx (with 32 bytes of shadow space below it for the dispatch call),
 * calls HookDispatch(ctx), then either tail-jumps to the trampoline (all
 * entry registers restored) or returns the override value.
 *
 * Calling contract for HookDispatch (returns a u64 -- a 16-byte struct return
 * would take the hidden-pointer slot in rcx and break the ctx argument):
 *   rcx = &HookCtx
 *   return rax = 0 -> pass: tail-jump to runtime->trampoline
 *                 1 -> skip: return ctx->retValue to the caller
 *   the dispatch writes ctx->retValue before returning 1
 *
 * Conventions (asserted in hook.c):
 *   - HOOK_STUB_FRAME = sizeof(HookCtx) + 32 shadow bytes, multiple of 16
 *   - the template's `movabs rax, imm64` placeholder (HOOK_STUB_CALL_MARKER)
 *     is patched once with &HookDispatch after the copy
 *   - gpr[10]/gpr[11] (r10/r11) are consumed by the stub itself; the context
 *     records the entry rsp for r10 and 0 for r11
 *   - variadic hooks (AL vector count) must use HOOK_KIND_VARARGS, not this stub
 */
#ifndef __HOOK_STUB_X64_H
#define __HOOK_STUB_X64_H

/* requires hook_protocol.h to be included first */
#ifndef HOOK_CTX_FRAME_SIZE
#error "include hook_protocol.h before hook_stub_x64.h"
#endif

#define HOOK_STR_(x) #x
#define HOOK_STR(x) HOOK_STR_(x)

#define HOOK_STUB_SHADOW 32
#define HOOK_STUB_FRAME (HOOK_CTX_FRAME_SIZE + HOOK_STUB_SHADOW)
/* distance from the entry rsp back to the ctx base, parenthesized because the
 * expression is stringified into the assembler source */
#define HOOK_STUB_CTX_OFFSET ((HOOK_STUB_FRAME) + 8 - (HOOK_STUB_SHADOW))
#define HOOK_STUB_CALL_MARKER 0x1122334455667788ull

#ifndef __ASSEMBLER__

__asm__(
    ".text\n"
    ".balign 16\n"
    ".globl hook_stub_template\n"
    "hook_stub_template:\n"
    "  .intel_syntax noprefix\n"
    /* r11 = &HookRuntime (from the thunk); every other register is live */
    "  mov r10, rsp\n"
    "  push rax\n"
    "  sub rsp, " HOOK_STR(HOOK_STUB_FRAME) "\n"
    "  mov rax, [r10]\n"                      /* return address = entry rip */
    "  mov [rsp + 256], rax\n"
    "  mov rax, [rsp + " HOOK_STR(HOOK_STUB_FRAME) "]\n" /* original rax */
    "  mov [rsp + 32], rax\n"
    "  mov [rsp + 40], rcx\n"
    "  mov [rsp + 48], rdx\n"
    "  mov [rsp + 56], rbx\n"
    "  lea rax, [rsp + " HOOK_STR(HOOK_STUB_FRAME + 8) "]\n" /* entry rsp */
    "  mov [rsp + 64], rax\n"                 /* gpr[4] = rsp */
    "  mov [rsp + 264], rax\n"                /* ctx.entryRsp */
    "  mov [rsp + 72], rbp\n"
    "  mov [rsp + 80], rsi\n"
    "  mov [rsp + 88], rdi\n"
    "  mov [rsp + 96], r8\n"
    "  mov [rsp + 104], r9\n"
    "  mov [rsp + 112], r10\n"
    "  mov qword ptr [rsp + 120], 0\n"        /* r11 clobbered by the thunk */
    "  mov [rsp + 128], r12\n"
    "  mov [rsp + 136], r13\n"
    "  mov [rsp + 144], r14\n"
    "  mov [rsp + 152], r15\n"
    "  movaps [rsp + 160], xmm0\n"
    "  movaps [rsp + 176], xmm1\n"
    "  movaps [rsp + 192], xmm2\n"
    "  movaps [rsp + 208], xmm3\n"
    "  movaps [rsp + 224], xmm4\n"
    "  movaps [rsp + 240], xmm5\n"
    "  mov [rsp + 272], r11\n"                /* ctx.runtimePtr */
    "  mov dword ptr [rsp + 280], 0\n"        /* ctx.hookIndex, set by dispatch */
    "  lea rcx, [rsp + 32]\n"                 /* &ctx */
    "  movabs rax, " HOOK_STR(HOOK_STUB_CALL_MARKER) "\n"
    "  call rax\n"                            /* -> HookDispatch, patched once */
    "  add rsp, " HOOK_STR(HOOK_STUB_FRAME) "\n"
    "  mov r10d, eax\n"                       /* 0 = pass, 1 = skip */
    "  pop rax\n"
    "  lea r11, [rsp - " HOOK_STR(HOOK_STUB_CTX_OFFSET) "]\n" /* back to ctx */
    "  test r10d, r10d\n"
    "  jnz .Lhook_stub_skip\n"
    "  mov r11, [r11 + 240]\n"                /* ctx.runtimePtr (ctx-relative!) */
    "  jmp qword ptr [r11 + 72]\n"            /* runtime.trampoline */
    ".Lhook_stub_skip:\n"
    "  mov rax, [r11 + 256]\n"                /* ctx.retValue (ctx-relative!) */
    "  ret\n"
    ".globl hook_stub_template_end\n"
    "hook_stub_template_end:\n"
    "  .att_syntax prefix\n"
);

extern const unsigned char hook_stub_template[];
extern const unsigned char hook_stub_template_end[];

#endif /* !__ASSEMBLER__ */

#endif /* __HOOK_STUB_X64_H */
