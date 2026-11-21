/*
 * smoke_target.c - a tiny hook target for the smoke test (no game needed).
 *
 * Exports SmokeTick; the payload hooks it via the module+export source and an
 * ISA program that counts hits into runtime->state[0] and emits one event per
 * call. main() calls it in a loop so the smoke script can watch the counter
 * rise and fall with the hook's enabled flag.
 *
 * BUILD_FLAGS[gcc(mingw)]: -O0 -municode? no: plain console app
 * build: x86_64-w64-mingw32-gcc -O0 -o smoke.exe tests/hooks_dll/smoke_target.c
 */

#include <stdarg.h>
#include <stdio.h>
#include <windows.h>

volatile LONG g_ticks = 0;
volatile LONG g_badArgs = 0;

static LONG WINAPI SmokeCrashFilter(EXCEPTION_POINTERS *info)
{
    /* print the crash site before dying: the smoke test reads stdout */
    char line[256];
    int n = snprintf(line, sizeof(line),
                     "CRASH code=0x%08lX rip=%p rsp=%p type=%llu addr=%llu r11=%p\n",
                     (unsigned long)info->ExceptionRecord->ExceptionCode,
                     (void *)info->ExceptionRecord->ExceptionAddress,
                     (void *)info->ContextRecord->Rsp,
                     (unsigned long long)info->ExceptionRecord->ExceptionInformation[0],
                     (unsigned long long)info->ExceptionRecord->ExceptionInformation[1],
                     (void *)info->ContextRecord->R11);
    OutputDebugStringA(line);
    HANDLE stderr_handle = GetStdHandle(STD_ERROR_HANDLE);
    DWORD written = 0;
    WriteFile(stderr_handle, line, (DWORD)n, &written, NULL);
    {
        unsigned char code[16];
        memcpy(code, (const void *)info->ExceptionRecord->ExceptionAddress, sizeof(code));
        for (int i = 0; i < 16; i++)
        {
            n = snprintf(line, sizeof(line), "RIPBYTE %d %02x\n", i, code[i]);
            WriteFile(stderr_handle, line, (DWORD)n, &written, NULL);
        }
    }
    /* stack: return addresses let the smoke script reconstruct the path */
    unsigned long long *stack = (unsigned long long *)info->ContextRecord->Rsp;
    for (int i = 0; i < 8; i++)
    {
        n = snprintf(line, sizeof(line), "STACK %d %p\n", i, (void *)stack[i]);
        WriteFile(stderr_handle, line, (DWORD)n, &written, NULL);
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

/* the prologue of this function must decode to >= 14 relocatable bytes; the
 * -O0 frame prologue qualifies */
__declspec(dllexport) int SmokeTick(int value)
{
    int local = value * 2;
    if (value != 1)
        InterlockedIncrement((volatile LONG *)&g_badArgs); /* the stub must not clobber rcx */
    InterlockedIncrement((volatile LONG *)&g_ticks);
    return local + 1;
}

volatile LONG g_logs = 0;

/* printf-style export: exercises the compiled varargs detour */
__declspec(dllexport) void SmokeLog(const char *format, ...)
{
    char text[256];
    va_list args;
    va_start(args, format);
    vsnprintf(text, sizeof(text), format, args);
    va_end(args);
    InterlockedIncrement((volatile LONG *)&g_logs);
    OutputDebugStringA(text);
}

int main(void)
{
    SetUnhandledExceptionFilter(SmokeCrashFilter);
    for (;;)
    {
        static int logged = 0;
        SmokeTick(1);
        SmokeLog("tick %d g_ticks=%ld", logged++, g_ticks);  // the varargs hook is toggled at runtime
        Sleep(200);
    }
    return 0;
}
