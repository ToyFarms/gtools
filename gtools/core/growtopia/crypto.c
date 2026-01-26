// BUILD_FLAGS[gcc, clang, mingw]: -O3 -march=native -mtune=native -funroll-loops -fomit-frame-pointer -fno-exceptions -flto -pipe
// BUILD_FLAGS[msvc]: /O2 /Ob2 /Ot /Gy /GL /arch:AVX2 /DNDEBUG
#include <immintrin.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#if defined(_MSC_VER)
#define EXPORT __declspec(dllexport)
#else
#define EXPORT __attribute__((visibility("default")))
#endif

#if defined(__GNUC__) || defined(__clang__)
#define ALWAYS_INLINE inline __attribute__((always_inline))
#else
#define ALWAYS_INLINE inline
#endif

static ALWAYS_INLINE uint32_t rol32(uint32_t x, unsigned int r) {
  // r is within 0 < r < 32
  return (x << r) | (x >> (32 - r));
}

EXPORT int32_t proton_hash(const void *data_, size_t len) {
  const uint8_t *restrict data = (const uint8_t *restrict)data_;
#if defined(__GNUC__) || defined(__clang__)
  data = __builtin_assume_aligned(data, 16);
#endif

  int32_t h = 0x55555555u;

  const size_t PREFETCH_DISTANCE = 256;
  for (size_t p = 0; p + 64 < len; p += PREFETCH_DISTANCE) {
#if defined(__GNUC__) || defined(__clang__)
    __builtin_prefetch(data + p + PREFETCH_DISTANCE, 0, 3);
#else
    _mm_prefetch((const char *)(data + p + PREFETCH_DISTANCE), _MM_HINT_T0);
#endif
  }

  size_t i = 0;

  size_t n = len;
  while (n >= 16) {
    h = rol32(h, 5) + data[i + 0];
    h = rol32(h, 5) + data[i + 1];
    h = rol32(h, 5) + data[i + 2];
    h = rol32(h, 5) + data[i + 3];

    h = rol32(h, 5) + data[i + 4];
    h = rol32(h, 5) + data[i + 5];
    h = rol32(h, 5) + data[i + 6];
    h = rol32(h, 5) + data[i + 7];

    h = rol32(h, 5) + data[i + 8];
    h = rol32(h, 5) + data[i + 9];
    h = rol32(h, 5) + data[i + 10];
    h = rol32(h, 5) + data[i + 11];

    h = rol32(h, 5) + data[i + 12];
    h = rol32(h, 5) + data[i + 13];
    h = rol32(h, 5) + data[i + 14];
    h = rol32(h, 5) + data[i + 15];

    i += 16;
    n -= 16;
  }

  // handle remaining
  while (n >= 8) {
    h = rol32(h, 5) + data[i + 0];
    h = rol32(h, 5) + data[i + 1];
    h = rol32(h, 5) + data[i + 2];
    h = rol32(h, 5) + data[i + 3];
    h = rol32(h, 5) + data[i + 4];
    h = rol32(h, 5) + data[i + 5];
    h = rol32(h, 5) + data[i + 6];
    h = rol32(h, 5) + data[i + 7];
    i += 8;
    n -= 8;
  }

  // tail
  while (n--) {
    h = rol32(h, 5) + data[i++];
  }

  return h;
}
