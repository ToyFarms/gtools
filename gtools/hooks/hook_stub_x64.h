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
 * HookCtx, calls HookDispatch(ctx), then either tail-jumps to the trampoline
 * (all entry registers restored) or returns the override value.
 *
 * Calling contract for HookDispatch:
 *   rcx = &HookCtx
 *   return rax = trampoline address to jump to, or 0 to skip the call
 *   when skipping: rdx = the return value for the caller
 *
 * Conventions (asserted in hook.c):
 *   - HOOK_CTX_FRAME_SIZE is a multiple of 16 (stack alignment around `call`)
 *   - the template's `mov rax, imm64` placeholder (HOOK_STUB_CALL_MARKER) is
 *     patched once with &HookDispatch after the copy
 *   - gpr[10]/gpr[11] (r10/r11) are consumed by the stub itself; the context
 *     records the entry rsp for r10 and 0 for r11
 *   - variadic hooks (AL vector count) must use HOOK_KIND_VARARGS, not this stub
 */
#ifndef __HOOK_STUB_X64_H
#define __HOOK_STUB_X64_H

/* requires hook_protocol.h (HOOK_CTX_FRAME_SIZE) to be included first */
#ifndef HOOK_CTX_FRAME_SIZE
#error "include hook_protocol.h before hook_stub_x64.h"
#endif

#define HOOK_STR_(x) #x
#define HOOK_STR(x) HOOK_STR_(x)

#define HOOK_STUB_CALL_MARKER 0x1122334455667788ull

#ifndef __ASSEMBLER__

__asm__(
    ".pushsection .text\n"
    ".balign 16\n"
    ".globl hook_stub_template\n"
    "hook_stub_template:\n"
    "  .intel_syntax noprefix\n"
    /* r11 = &HookRuntime (from the thunk); every other register is live */
    "  mov r10, rsp\n"
    "  push rax\n"
    "  sub rsp, " HOOK_STR(HOOK_CTX_FRAME_SIZE) "\n"
    "  mov rax, [r10]\n"                      /* return address = entry rip */
    "  mov [rsp + 224], rax\n"
    "  mov rax, [rsp + " HOOK_STR(HOOK_CTX_FRAME_SIZE) "]\n" /* original rax */
    "  mov [rsp + 0], rax\n"
    "  mov [rsp + 8], rcx\n"
    "  mov [rsp + 16], rdx\n"
    "  mov [rsp + 24], rbx\n"
    "  lea rax, [rsp + " HOOK_STR(HOOK_CTX_FRAME_SIZE + 8) "]\n" /* entry rsp */
    "  mov [rsp + 32], rax\n"                 /* gpr[4] = rsp */
    "  mov [rsp + 232], rax\n"                /* ctx.entryRsp */
    "  mov [rsp + 40], rbp\n"
    "  mov [rsp + 48], rsi\n"
    "  mov [rsp + 56], rdi\n"
    "  mov [rsp + 64], r8\n"
    "  mov [rsp + 72], r9\n"
    "  mov [rsp + 80], r10\n"
    "  mov qword ptr [rsp + 88], 0\n"         /* r11 clobbered by the thunk */
    "  mov [rsp + 96], r12\n"
    "  mov [rsp + 104], r13\n"
    "  mov [rsp + 112], r14\n"
    "  mov [rsp + 120], r15\n"
    "  movaps [rsp + 128], xmm0\n"
    "  movaps [rsp + 144], xmm1\n"
    "  movaps [rsp + 160], xmm2\n"
    "  movaps [rsp + 176], xmm3\n"
    "  movaps [rsp + 192], xmm4\n"
    "  movaps [rsp + 208], xmm5\n"
    "  mov [rsp + 240], r11\n"                /* ctx.runtimePtr */
    "  mov dword ptr [rsp + 248], 0\n"        /* ctx.hookIndex, set by dispatch */
    "  lea rcx, [rsp]\n"
    "  movabs rax, " HOOK_STR(HOOK_STUB_CALL_MARKER) "\n"
    "  call rax\n"                            /* -> HookDispatch, patched once */
    "  add rsp, " HOOK_STR(HOOK_CTX_FRAME_SIZE) "\n"
    "  mov r10, rax\n"                        /* trampoline, or 0 = skip */
    "  pop rax\n"
    "  test r10, r10\n"
    "  jz .Lhook_stub_skip\n"
    "  jmp r10\n"
    ".Lhook_stub_skip:\n"
    "  mov rax, rdx\n"
    "  ret\n"
    ".globl hook_stub_template_end\n"
    "hook_stub_template_end:\n"
    "  .att_syntax prefix\n"
    ".popsection\n"
);

extern const unsigned char hook_stub_template[];
extern const unsigned char hook_stub_template_end[];

#endif /* !__ASSEMBLER__ */

#endif /* __HOOK_STUB_X64_H */
