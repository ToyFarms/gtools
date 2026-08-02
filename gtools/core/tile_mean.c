// BUILD_FLAGS[gcc, clang]: -O3 -march=native -ffast-math -funroll-loops -shared -fPIC -lm
// BUILD_FLAGS[gcc]: -fopenmp -fomit-frame-pointer -falign-functions=32 -falign-loops=32
// BUILD_FLAGS[clang(linux)]: -fopenmp=libomp
// BUILD_FLAGS[clang(macos)]: -Xpreprocessor -fopenmp -I$(brew --prefix libomp)/include -L$(brew --prefix libomp)/lib -lomp
// BUILD_FLAGS[msvc]: /O2 /arch:AVX2 /fp:fast /openmp /GL /Gy

#ifdef _MSC_VER
#  define ALIGN32 __declspec(align(32))
#  define EXPORT  __declspec(dllexport)
#else
#  pragma GCC optimize("O3,unroll-loops")
#  pragma GCC target("avx2,fma")
#  define ALIGN32 __attribute__((aligned(32)))
#  define EXPORT
#endif

#define RESTRICT __restrict

#include <immintrin.h>
#include <stdint.h>

#ifdef _OPENMP
#  include <omp.h>
#endif

#define GRID_K   8
#define TILE_W   32
#define TILE_H   32
#define CELL_W   (TILE_W / GRID_K)
#define CELL_H   (TILE_H / GRID_K)
#define N_LEAVES (GRID_K * GRID_K)
#define N_TILE   (TILE_W * TILE_H)
#define GRID_KH  (GRID_K / 2)

#define LAB_EPS 0.008856451679035631f
#define LAB_A   7.787037037037037f
#define LAB_B   0.13793103448275862f

#define M00 (0.4124564f / 0.95047f)
#define M01 (0.3575761f / 0.95047f)
#define M02 (0.1804375f / 0.95047f)
#define M10 0.2126729f
#define M11 0.7151522f
#define M12 0.0721750f
#define M20 (0.0193339f / 1.08883f)
#define M21 (0.1191920f / 1.08883f)
#define M22 (0.9503041f / 1.08883f)

#define INV16            (1.0f / 16.0f)
#define CLAMP(v, lo, hi) ((v) < (lo) ? (lo) : (v) > (hi) ? (hi) : (v))

static inline __m256 avx_lab_f(__m256 x)
{
    const __m256 v_one = _mm256_set1_ps(1.0f);
    const __m256 v_labA = _mm256_set1_ps(LAB_A);
    const __m256 v_labB = _mm256_set1_ps(LAB_B);
    const __m256 v_lab_eps = _mm256_set1_ps(LAB_EPS);
    const __m256 v_inv3 = _mm256_set1_ps(0.333333333333333333333f);

    // degree-6 fit for cbrt(1+t), t in [0,1)
    const __m256 c0 = _mm256_set1_ps(1.00000052f);
    const __m256 c1 = _mm256_set1_ps(0.33330263f);
    const __m256 c2 = _mm256_set1_ps(-0.11066586f);
    const __m256 c3 = _mm256_set1_ps(0.05898392f);
    const __m256 c4 = _mm256_set1_ps(-0.03227499f);
    const __m256 c5 = _mm256_set1_ps(0.01330320f);
    const __m256 c6 = _mm256_set1_ps(-0.00272876f);

    const __m256 cbrt2 = _mm256_set1_ps(1.2599210498948732f);
    const __m256 cbrt4 = _mm256_set1_ps(1.5874010519681994f);

    const __m256i exp127 = _mm256_set1_epi32(127);
    const __m256i mant_mask = _mm256_set1_epi32(0x007fffff);
    const __m256i one_bits = _mm256_set1_epi32(0x3f800000);
    const __m256i three = _mm256_set1_epi32(3);
    const __m256i two = _mm256_set1_epi32(2);
    const __m256i zero = _mm256_setzero_si256();
    const __m256i one_i = _mm256_set1_epi32(1);
    const __m256i two_i = _mm256_set1_epi32(2);

    // linear fallback for tiny x
    __m256 linear = _mm256_fmadd_ps(v_labA, x, v_labB);

    // x = m * 2^E, with m in [1,2) for normal floats
    __m256i xi = _mm256_castps_si256(x);
    __m256i exp = _mm256_srli_epi32(xi, 23);
    __m256i E = _mm256_sub_epi32(exp, exp127);

    // floor(E/3) for signed E, done with a tiny bias then trunc
    __m256i neg = _mm256_cmpgt_epi32(zero, E);
    __m256i adj = _mm256_sub_epi32(E, _mm256_and_si256(neg, two));
    __m256 qf = _mm256_mul_ps(_mm256_cvtepi32_ps(adj), v_inv3);
    __m256i q = _mm256_cvttps_epi32(qf);
    __m256i r = _mm256_sub_epi32(E, _mm256_mullo_epi32(q, three));

    __m256i mant = _mm256_or_si256(_mm256_and_si256(xi, mant_mask), one_bits);
    __m256 m = _mm256_castsi256_ps(mant);
    __m256 t = _mm256_sub_ps(m, v_one);

    // polynomial approximation of cbrt(1+t)
    __m256 p = c6;
    p = _mm256_fmadd_ps(p, t, c5);
    p = _mm256_fmadd_ps(p, t, c4);
    p = _mm256_fmadd_ps(p, t, c3);
    p = _mm256_fmadd_ps(p, t, c2);
    p = _mm256_fmadd_ps(p, t, c1);
    p = _mm256_fmadd_ps(p, t, c0);

    // 2^(q) via exponent bits
    __m256i expq = _mm256_add_epi32(q, exp127);
    expq = _mm256_slli_epi32(expq, 23);
    __m256 pow2q = _mm256_castsi256_ps(expq);

    // 2^(r/3) lookup
    __m256 tbl = _mm256_set1_ps(1.0f);
    tbl = _mm256_blendv_ps(tbl, cbrt2, _mm256_castsi256_ps(_mm256_cmpeq_epi32(r, one_i)));
    tbl = _mm256_blendv_ps(tbl, cbrt4, _mm256_castsi256_ps(_mm256_cmpeq_epi32(r, two_i)));

    __m256 y = _mm256_mul_ps(_mm256_mul_ps(p, tbl), pow2q);

    return _mm256_blendv_ps(linear, y, _mm256_cmp_ps(x, v_lab_eps, _CMP_GT_OQ));
}

static inline void process_8_inline(const float *RESTRICT fR, const float *RESTRICT fG, const float *RESTRICT fB,
                                    const float *RESTRICT fA, const float *RESTRICT bR, const float *RESTRICT bG,
                                    const float *RESTRICT bB, const float *RESTRICT bA, int i, __m256 *RESTRICT outL,
                                    __m256 *RESTRICT outa, __m256 *RESTRICT outb)
{
    __m256 fR8 = _mm256_load_ps(fR + i), fG8 = _mm256_load_ps(fG + i);
    __m256 fB8 = _mm256_load_ps(fB + i), fA8 = _mm256_load_ps(fA + i);
    __m256 bR8 = _mm256_load_ps(bR + i), bG8 = _mm256_load_ps(bG + i);
    __m256 bB8 = _mm256_load_ps(bB + i), bA8 = _mm256_load_ps(bA + i);

    // out_a = fg_a + bg_a * (1-fg_a)
    __m256 v1 = _mm256_set1_ps(1.0f);
    __m256 omfa = _mm256_sub_ps(v1, fA8);
    __m256 oa = _mm256_fmadd_ps(bA8, omfa, fA8);
    __m256 inva = _mm256_div_ps(v1, _mm256_max_ps(oa, _mm256_set1_ps(1e-6f)));
    __m256 baom = _mm256_mul_ps(bA8, omfa);

    __m256 cR = _mm256_mul_ps(inva, _mm256_fmadd_ps(bR8, baom, _mm256_mul_ps(fR8, fA8)));
    __m256 cG = _mm256_mul_ps(inva, _mm256_fmadd_ps(bG8, baom, _mm256_mul_ps(fG8, fA8)));
    __m256 cB = _mm256_mul_ps(inva, _mm256_fmadd_ps(bB8, baom, _mm256_mul_ps(fB8, fA8)));

    // Linear sRGB to XYZ (D65 white-point normalized)
    __m256 X = _mm256_fmadd_ps(_mm256_set1_ps(M00), cR,
                               _mm256_fmadd_ps(_mm256_set1_ps(M01), cG, _mm256_mul_ps(_mm256_set1_ps(M02), cB)));
    __m256 Y = _mm256_fmadd_ps(_mm256_set1_ps(M10), cR,
                               _mm256_fmadd_ps(_mm256_set1_ps(M11), cG, _mm256_mul_ps(_mm256_set1_ps(M12), cB)));
    __m256 Z = _mm256_fmadd_ps(_mm256_set1_ps(M20), cR,
                               _mm256_fmadd_ps(_mm256_set1_ps(M21), cG, _mm256_mul_ps(_mm256_set1_ps(M22), cB)));

    __m256 fX = avx_lab_f(X);
    __m256 fY = avx_lab_f(Y);
    __m256 fZ = avx_lab_f(Z);

    *outL = _mm256_fmsub_ps(_mm256_set1_ps(116.f), fY, _mm256_set1_ps(16.f));
    *outa = _mm256_mul_ps(_mm256_set1_ps(500.f), _mm256_sub_ps(fX, fY));
    *outb = _mm256_mul_ps(_mm256_set1_ps(200.f), _mm256_sub_ps(fY, fZ));
}

static inline void hsum_pair(__m256 v, float *RESTRICT out0, float *RESTRICT out1)
{
    __m128 lo = _mm256_castps256_ps128(v);
    __m128 hi = _mm256_extractf128_ps(v, 1);

    __m128 slo = _mm_movehdup_ps(lo);
    slo = _mm_add_ps(lo, slo);
    *out0 = _mm_cvtss_f32(_mm_add_ss(slo, _mm_movehl_ps(slo, slo)));

    __m128 shi = _mm_movehdup_ps(hi);
    shi = _mm_add_ps(hi, shi);
    *out1 = _mm_cvtss_f32(_mm_add_ss(shi, _mm_movehl_ps(shi, shi)));
}

EXPORT void compute_tile_means(const float *RESTRICT fg_soa, /* [n_fg][4][N_TILE] float32, 32-byte aligned */
                               const float *RESTRICT bg_soa, /* [n_bg][4][N_TILE] float32, 32-byte aligned */
                               uint32_t *RESTRICT out,       /* [n_bg][n_fg][N_LEAVES] uint32              */
                               int n_fg, int n_bg)
{

    int bg_idx;
#ifdef _OPENMP
#  pragma omp parallel for schedule(static)
#endif
    for (bg_idx = 0; bg_idx < n_bg; bg_idx++)
    {
        const float *bch = bg_soa + (size_t)bg_idx * 4 * N_TILE;
        const float *bR = bch, *bG = bch + N_TILE;
        const float *bB = bch + 2 * N_TILE, *bA = bch + 3 * N_TILE;

        uint32_t *out_bg = out + (size_t)bg_idx * n_fg * N_LEAVES;

        for (int fg_idx = 0; fg_idx < n_fg; fg_idx++)
        {
            const float *fch = fg_soa + (size_t)fg_idx * 4 * N_TILE;
            const float *fR = fch, *fG = fch + N_TILE;
            const float *fB = fch + 2 * N_TILE, *fA = fch + 3 * N_TILE;

            uint32_t *out_pair = out_bg + fg_idx * N_LEAVES;

            for (int gy = 0; gy < GRID_K; gy++)
            {
                __m256 accL[GRID_KH], acca[GRID_KH], accb[GRID_KH];
                for (int j = 0; j < GRID_KH; j++)
                {
                    accL[j] = _mm256_setzero_ps();
                    acca[j] = _mm256_setzero_ps();
                    accb[j] = _mm256_setzero_ps();
                }

                int row_base = gy * CELL_H;
                for (int row = row_base; row < row_base + CELL_H; row++)
                {
                    int base = row * TILE_W;
                    __m256 L8, a8, b8;

                    for (int j = 0; j < GRID_KH; j++)
                    {
                        process_8_inline(fR, fG, fB, fA, bR, bG, bB, bA, base + j * 8, &L8, &a8, &b8);
                        accL[j] = _mm256_add_ps(accL[j], L8);
                        acca[j] = _mm256_add_ps(acca[j], a8);
                        accb[j] = _mm256_add_ps(accb[j], b8);
                    }
                }

                for (int gxp = 0; gxp < GRID_KH; gxp++)
                {
                    float mL0, mL1, ma0, ma1, mb0, mb1;
                    hsum_pair(accL[gxp], &mL0, &mL1);
                    hsum_pair(acca[gxp], &ma0, &ma1);
                    hsum_pair(accb[gxp], &mb0, &mb1);

                    mL0 *= INV16;
                    mL1 *= INV16;
                    ma0 *= INV16;
                    ma1 *= INV16;
                    mb0 *= INV16;
                    mb1 *= INV16;

                    int Lq = CLAMP((int)(mL0 * (1023.f / 100.f)), 0, 1023);
                    int aq = CLAMP((int)((ma0 + 128.f) * (2047.f / 256.f)), 0, 2047);
                    int bq = CLAMP((int)((mb0 + 128.f) * (2047.f / 256.f)), 0, 2047);
                    out_pair[gy * GRID_K + gxp * 2] = (uint32_t)(Lq | (aq << 10) | (bq << 21));

                    Lq = CLAMP((int)(mL1 * (1023.f / 100.f)), 0, 1023);
                    aq = CLAMP((int)((ma1 + 128.f) * (2047.f / 256.f)), 0, 2047);
                    bq = CLAMP((int)((mb1 + 128.f) * (2047.f / 256.f)), 0, 2047);
                    out_pair[gy * GRID_K + gxp * 2 + 1] = (uint32_t)(Lq | (aq << 10) | (bq << 21));
                }
            }
        }
    }
}
