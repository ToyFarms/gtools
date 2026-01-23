#include <stdint.h>

#if defined(_MSC_VER)
#include <intrin.h>
__declspec(dllexport) int16_t cpuid_checksum(void) {
  int regs[4];
  __cpuid(regs, 0);

  uint32_t eax = regs[0];
  uint32_t ebx = regs[1];
  uint32_t ecx = regs[2];
  uint32_t edx = regs[3];

  return (int16_t)(((edx >> 16) & 0xFFFF) + ((ecx >> 16) & 0xFFFF) +
                   ((ebx >> 16) & 0xFFFF) + ((eax >> 16) & 0xFFFF) + edx + ecx +
                   ebx + eax);
}
#else
__attribute__((visibility("default"))) int16_t cpuid_checksum(void) {
  uint32_t eax, ebx, ecx, edx;
  eax = 0;

  __asm__ volatile("cpuid"
                   : "=a"(eax), "=b"(ebx), "=c"(ecx), "=d"(edx)
                   : "a"(eax));

  return (int16_t)(((edx >> 16) & 0xFFFF) + ((ecx >> 16) & 0xFFFF) +
                   ((ebx >> 16) & 0xFFFF) + ((eax >> 16) & 0xFFFF) + edx + ecx +
                   ebx + eax);
}
#endif
