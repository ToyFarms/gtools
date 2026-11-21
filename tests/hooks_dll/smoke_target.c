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

#include <windows.h>

volatile LONG g_ticks = 0;

/* the prologue of this function must decode to >= 14 relocatable bytes; the
 * -O0 frame prologue qualifies */
__declspec(dllexport) int SmokeTick(int value)
{
    int local = value * 2;
    InterlockedIncrement((volatile LONG *)&g_ticks);
    return local + 1;
}

int main(void)
{
    for (;;)
    {
        SmokeTick(1);
        Sleep(10);
    }
    return 0;
}
