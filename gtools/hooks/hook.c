// BUILD_FLAGS[gcc, clang]: -O3 -march=native -ffast-math -funroll-loops -shared -fPIC
// BUILD_FLAGS[gcc]: -fopenmp -fomit-frame-pointer -falign-functions=32 -falign-loops=32
// BUILD_FLAGS[clang(linux)]: -fopenmp=libomp
// BUILD_FLAGS[clang(macos)]: -Xpreprocessor -fopenmp -I$(brew --prefix libomp)/include -L$(brew --prefix libomp)/lib -lomp
// BUILD_FLAGS[msvc]: /O2 /arch:AVX2 /fp:fast /openmp /GL /Gy /TC
// BUILD_FLAGS[gcc(mingw)]: -O2 -shared -fPIC -mwindows

#define WIN32_LEAN_AND_MEAN
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>
#include <tlhelp32.h>

#pragma comment(lib, "user32.lib")
#pragma comment(lib, "advapi32.lib")

#ifndef NTSTATUS
typedef LONG NTSTATUS;
#endif
#ifndef STATUS_SUCCESS
#  define STATUS_SUCCESS ((NTSTATUS)0x00000000L)
#endif

#if defined(_MSC_VER)
#  define GT_FASTCALL __fastcall
#else
#  define GT_FASTCALL
#endif

#define GT_SNPRINTF snprintf

static const uintptr_t RVA_CONNECT = 0x107DF40;
static const uintptr_t RVA_LOG_PRINTF = 0x0D3CBA0;
static const uintptr_t RVA_LOG_RAW = 0x11A6480;
static const uintptr_t RVA_ON_RESPONSE = 0x1080BD0;
static const uintptr_t RVA_HTTP_POST = 0x1254030;

#define RESP_STATUS_OFFSET 0xE0
#define RESP_BODY_OFFSET   0x60
#define HS_OFFSET          0x3F0
#define PORT_OFFSET        0x410
#define TYPE_OFFSET        0x414

#define STOLEN_LOG        27
#define STOLEN_CONNECT    14
#define STOLEN_ONRESPONSE 17
#define STOLEN_HTTPPOST   21

#define MAX_SUSPENDED   4096
#define MAX_LINE        1024
#define MAX_BODY        2048
#define MAX_NOTIFY_URL  512
#define MAX_NOTIFY_BODY 512

struct GtString
{
    char *buf;
    uint64_t pad;
    uint64_t size;
    uint64_t cap;
};

static const char *GtStringData(const struct GtString *s)
{
    if (!s)
        return NULL;
    return (s->cap > 0xF) ? s->buf : (const char *)s;
}

struct Detour
{
    uint8_t *target;
    void *trampoline;
    uint8_t stolen[32];
    size_t len;
    int installed;
    int ok;
};

typedef uintptr_t(GT_FASTCALL *FnConnect)(void *self, void *a2, int a3, void *a4, void *stackArg5, void *stackArg6);
typedef uintptr_t(GT_FASTCALL *FnHttpPost)(void *client, void *urlStr, int isTls, void *dict, void *callback);
typedef long long(GT_FASTCALL *FnLog)(const char *fmt, ...);
typedef void(GT_FASTCALL *FnOnResponse)(void *closure, void *resp);

static FnConnect g_origConnect = NULL;
static FnLog g_origLogPrintf = NULL;
static FnLog g_origLogRaw = NULL;
static FnOnResponse g_onResponse = NULL;
static FnHttpPost g_origHttpPost = NULL;

static struct Detour dConn, dLogP, dLogR, dResp, dPost;

static uint8_t *g_base = NULL;
static uint8_t **g_cbVtable = NULL;
static HMODULE g_hSelf = NULL;
static size_t g_imageSize = 0;
static int g_isTarget = 0;
static uint8_t *g_selfBase = NULL;
static size_t g_selfSize = 0;

static char g_ip[128] = "127.0.0.1";
static int g_port = 16999;
static int g_type = 1;
static char g_loginUrl[256] = "login.growtopiagame.com";
static char g_logPath[MAX_PATH] = "";
static DWORD g_delayMs = 2500;
static int g_verbose = 1;
static int g_nopRequest = 0;
static int g_allowAnyMod = 0;
static int g_outOfProcess = 1;
static char g_handshake[MAX_PATH] = "";

static char g_notifyUrl[MAX_NOTIFY_URL] = "";
static char g_notifyFormat[MAX_NOTIFY_BODY] =
    "version=%version%&protocol=%protocol%&platform=%platform%&server=%server%&port=%port%";
static int g_notifyTimeout = 3000;
static char g_reqVersion[64] = "";
static char g_reqProtocol[64] = "";
static char g_reqPlatform[64] = "";
static char g_realServer[64] = "";
static int g_realPort = 0;
static volatile long g_notified = 0;

static HANDLE g_logFile = INVALID_HANDLE_VALUE;
static CRITICAL_SECTION g_logLock;
static int g_logLockReady = 0;

static HANDLE g_suspended[MAX_SUSPENDED];
static size_t g_suspended_count = 0;

static void DirNameOfModule(HMODULE h, char *out, size_t outsz)
{
    char buf[MAX_PATH];
    memset(buf, 0, sizeof(buf));
    GetModuleFileNameA(h, buf, MAX_PATH);
    char *p = strrchr(buf, '\\');
    if (p)
        *p = 0;
    GT_SNPRINTF(out, outsz, "%s", buf);
}

static void TrimInPlace(char *s)
{
    if (!s)
        return;
    size_t len = strlen(s);
    while (len > 0 && (s[len - 1] == ' ' || s[len - 1] == '\t' || s[len - 1] == '\r' || s[len - 1] == '\n'))
    {
        s[--len] = 0;
    }
    size_t b = 0;
    while (s[b] == ' ' || s[b] == '\t' || s[b] == '\r' || s[b] == '\n')
        b++;
    if (b > 0)
    {
        size_t i = 0;
        while (s[b])
            s[i++] = s[b++];
        s[i] = 0;
    }
    if (s[0] == 0)
        return;
}

static void Emit(const char *line);

static void Emit(const char *line)
{
    char buf[4200];
    SYSTEMTIME st;
    GetLocalTime(&st);
    int n = GT_SNPRINTF(buf, sizeof(buf), "[%02u:%02u:%02u.%03u][tid %5lu] %s\n", st.wHour, st.wMinute, st.wSecond,
                        st.wMilliseconds, (unsigned long)GetCurrentThreadId(), line ? line : "");

    OutputDebugStringA(buf);

    if (g_logLockReady)
        EnterCriticalSection(&g_logLock);
    if (g_logFile != INVALID_HANDLE_VALUE && n > 0)
    {
        DWORD w = 0;
        WriteFile(g_logFile, buf, (DWORD)n, &w, NULL);
    }
    if (g_logLockReady)
        LeaveCriticalSection(&g_logLock);
}

static void ExtractRealServerPort(const struct GtString *body);
static void TrySendNotify(void);

static void ModifyResponseBody(struct GtString *body)
{
    if (!body || body->size == 0)
        return;

    const char *src = GtStringData(body);
    if (!src)
        return;
    size_t srcSize = body->size;
    size_t srcCap = body->cap;

    char newBody[MAX_BODY];
    size_t newPos = 0;

    size_t i = 0;
    while (i < srcSize)
    {
        size_t lineStart = i;
        while (i < srcSize && src[i] != '\n')
            i++;
        size_t lineLen = (i - lineStart) + (i < srcSize ? 1 : 0);
        i++;

        char line[512];
        size_t copyLen = lineLen > sizeof(line) - 1 ? sizeof(line) - 1 : lineLen;
        memcpy(line, src + lineStart, copyLen);
        line[copyLen] = 0;

        if (strncmp(line, "server|", 7) == 0)
        {
            int written = GT_SNPRINTF(newBody + newPos, sizeof(newBody) - newPos, "server|%s\n", g_ip);
            if (written > 0)
                newPos += (size_t)written;
        }
        else if (strncmp(line, "port|", 5) == 0)
        {
            int written = GT_SNPRINTF(newBody + newPos, sizeof(newBody) - newPos, "port|%d\n", g_port);
            if (written > 0)
                newPos += (size_t)written;
        }
        else
        {
            if (newPos + lineLen < sizeof(newBody))
            {
                memcpy(newBody + newPos, src + lineStart, lineLen);
                newPos += lineLen;
            }
        }
    }

    newBody[newPos] = 0;

    char *dst = (body->cap > 0xF) ? body->buf : (char *)body;
    if (newPos <= srcCap)
    {
        memcpy(dst, newBody, newPos + 1);
        body->size = newPos;
    }
    else
    {
        char *newBuf = (char *)malloc(newPos + 0x40);
        if (newBuf)
        {
            memcpy(newBuf, newBody, newPos + 1);
            if (srcCap > 0xF)
                free(body->buf);
            body->buf = newBuf;
            body->size = newPos;
            body->cap = newPos + 0x40;
        }
    }

    char m[256];
    GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] response body rewritten: server|%s port|%d  (new size %zu)", g_ip, g_port,
                newPos);
    Emit(m);
}

static void GT_FASTCALL Hook_OnServerDataResponse(void *closure, void *resp)
{
    uint32_t status = *(uint32_t *)((uint8_t *)resp + RESP_STATUS_OFFSET);
    char m[256];
    GT_SNPRINTF(m, sizeof(m), "[hook] OnServerDataResponse: status=%u closure=%p resp=%p trampoline=%p", status,
                closure, resp, (void *)g_onResponse);
    Emit(m);

    if (status == 200)
    {
        struct GtString *body = (struct GtString *)((uint8_t *)resp + RESP_BODY_OFFSET);
        GT_SNPRINTF(m, sizeof(m),
                    "[hook] OnServerDataResponse: body at resp+0x60, size=%zu cap=%zu, first 64 bytes: %.64s",
                    body->size, body->cap, body->size ? GtStringData(body) : "(empty)");
        Emit(m);

        ExtractRealServerPort(body);
        char mm[256];
        if (g_realServer[0] || g_realPort)
        {
            GT_SNPRINTF(mm, sizeof(mm), "[fwd] real server response: server=%s port=%d", g_realServer, g_realPort);
            Emit(mm);
        }

        ModifyResponseBody(body);
    }
    else
    {
        Emit("[hook] OnServerDataResponse: status != 200, body untouched");
    }

    if (g_onResponse)
    {
        g_onResponse(closure, resp);
        Emit("[hook] OnServerDataResponse: real function returned (server/port parsed)");
    }
    else if (status == 200)
    {
        Emit("[hook] OnServerDataResponse: FATAL - g_onResponse==NULL, the real parser never ran!");
    }

    TrySendNotify();
}

static uintptr_t GT_FASTCALL Hook_ConnectToGameServer(void *self, void *a2, int a3, void *a4, void *stackArg5,
                                                      void *stackArg6)
{
    struct GtString *hs = (struct GtString *)((uint8_t *)self + HS_OFFSET);
    int port = *(int32_t *)((uint8_t *)self + PORT_OFFSET);
    int type = *(int32_t *)((uint8_t *)self + TYPE_OFFSET);

    char m[1024];
    GT_SNPRINTF(m, sizeof(m), "[hook] ConnectToGameServer called: self=%p, g_origConnect=%p", self,
                (void *)g_origConnect);
    Emit(m);

    if (hs)
    {
        const char *server = GtStringData(hs);
        int n = (int)(hs->size < 128 ? hs->size : 128);
        GT_SNPRINTF(
            m, sizeof(m),
            "[hook] ConnectToGameServer: server@0x3F0=\"%.*s\" port@0x410=%d type@0x414=%d  (size=%zu cap=%zu%s)", n,
            server, port, type, hs->size, hs->cap, hs->cap > 0xF ? "" : ", SSO");
        Emit(m);
    }
    else
    {
        Emit("[hook] ConnectToGameServer: self+0x3F0 invalid!");
    }

    GT_SNPRINTF(m, sizeof(m), "[hook] ConnectToGameServer: args a2=%p a3=%d a4=%p stackArg5=%p stackArg6=%p", a2, a3,
                a4, stackArg5, stackArg6);
    Emit(m);

    if (g_origConnect)
    {
        Emit("[hook] ConnectToGameServer: calling real ConnectToGameServer via trampoline");
        return g_origConnect(self, a2, a3, a4, stackArg5, stackArg6);
    }
    Emit("[hook] ConnectToGameServer: g_origConnect is NULL!");
    return 0;
}

static void CopyGtValue(char *dst, size_t dstN, const struct GtString *s)
{
    if (!s || !s->size || !dst || dstN == 0)
        return;
    const char *d = GtStringData(s);
    if (!d)
        return;
    size_t n = s->size < dstN - 1 ? s->size : dstN - 1;
    memcpy(dst, d, n);
    dst[n] = 0;
}

static void CaptureRequestParams(void *dict)
{
    if (!dict)
        return;
    uint8_t *sentinel = *(uint8_t **)((uint8_t *)dict + 8);
    if (!sentinel)
        return;

    char dump[1024];
    size_t dpos = 0;
    dump[0] = 0;

    uint8_t *node = *(uint8_t **)sentinel;
    while (node && node != sentinel)
    {
        struct GtString *key = (struct GtString *)(node + 0x10);
        struct GtString *val = (struct GtString *)(node + 0x30);
        if (key->size && GtStringData(key))
        {
            const char *k = GtStringData(key);
            size_t kN = key->size;
            if (kN == 7 && !memcmp(k, "version", 7))
                CopyGtValue(g_reqVersion, sizeof(g_reqVersion), val);
            else if (kN == 8 && !memcmp(k, "protocol", 8))
                CopyGtValue(g_reqProtocol, sizeof(g_reqProtocol), val);
            else if (kN == 8 && !memcmp(k, "platform", 8))
                CopyGtValue(g_reqPlatform, sizeof(g_reqPlatform), val);

            if (dpos + 2 + key->size + 1 + (val ? val->size : 0) + 1 < sizeof(dump))
            {
                if (dpos)
                    dump[dpos++] = ' ';
                memcpy(dump + dpos, k, key->size);
                dpos += key->size;
                dump[dpos++] = '=';
                if (val && val->size && GtStringData(val))
                {
                    size_t n = val->size;
                    memcpy(dump + dpos, GtStringData(val), n);
                    dpos += n;
                }
                dump[dpos] = 0;
            }
        }
        node = *(uint8_t **)node;
    }
    char m[1100];
    GT_SNPRINTF(m, sizeof(m), "[fwd] request params: %s", dump[0] ? dump : "(none)");
    Emit(m);
}

static void ExtractRealServerPort(const struct GtString *body)
{
    if (!body || !body->size)
        return;
    const char *src = GtStringData(body);
    if (!src)
        return;
    size_t srcSize = body->size, i = 0;
    while (i < srcSize)
    {
        size_t ls = i;
        while (i < srcSize && src[i] != '\n')
            i++;
        size_t len = i - ls;
        if (len >= 7 && strncmp(src + ls, "server|", 7) == 0)
        {
            size_t take = (len - 7) < 63 ? (len - 7) : 63;
            if (take && src[ls + 7 + take - 1] == '\r')
                take--;
            memcpy(g_realServer, src + ls + 7, take);
            g_realServer[take] = 0;
        }
        else if (len >= 5 && strncmp(src + ls, "port|", 5) == 0)
        {
            g_realPort = atoi(src + ls + 5);
        }
        i++;
    }
}

struct NotifyJob
{
    char url[MAX_NOTIFY_URL];
    char body[MAX_NOTIFY_BODY];
};

static void AppendNumberToken(char *out, size_t outsz, size_t *pos, int v)
{
    char b[16];
    GT_SNPRINTF(b, sizeof(b), "%d", v);
    size_t n = strlen(b);
    if (*pos + n < outsz)
    {
        memcpy(out + *pos, b, n);
        *pos += n;
        out[*pos] = 0;
    }
}

static void BuildNotifyBody(char *out, size_t outsz)
{
    out[0] = 0;
    size_t pos = 0;
    const char *fmt = g_notifyFormat;
    for (const char *p = fmt; *p && pos + 1 < outsz;)
    {
        if (*p == '%')
        {
            const char *e = strchr(p + 1, '%');
            if (e && (size_t)(e - p) < 24)
            {
                char token[32];
                size_t tn = (size_t)(e - p - 1);
                memcpy(token, p + 1, tn);
                token[tn] = 0;
                const char *val = NULL;
                if (strcmp(token, "version") == 0)
                    val = g_reqVersion;
                else if (strcmp(token, "protocol") == 0)
                    val = g_reqProtocol;
                else if (strcmp(token, "platform") == 0)
                    val = g_reqPlatform;
                else if (strcmp(token, "server") == 0)
                    val = g_realServer;

                if (val)
                {
                    size_t vl = strlen(val);
                    if (pos + vl < outsz)
                    {
                        memcpy(out + pos, val, vl);
                        pos += vl;
                        out[pos] = 0;
                    }
                }
                else if (strcmp(token, "port") == 0)
                {
                    AppendNumberToken(out, outsz, &pos, g_realPort);
                }
                else
                {
                    size_t vl = (size_t)(e - p + 1);
                    if (pos + vl < outsz)
                    {
                        memcpy(out + pos, p, vl);
                        pos += vl;
                        out[pos] = 0;
                    }
                }
                p = e + 1;
                continue;
            }
        }
        out[pos++] = *p++;
        out[pos] = 0;
    }
}

static DWORD WINAPI NotifySendThread(LPVOID pRaw)
{
    struct NotifyJob *job = (struct NotifyJob *)pRaw;
    if (!job)
        return 0;

    if (_strnicmp(job->url, "http://", 7) != 0)
    {
        Emit("[fwd] notify_url must start with http:// (TLS not supported here)");
        free(job);
        return 0;
    }

    const char *auth = job->url + 7;
    const char *path = strchr(auth, '/');
    if (!path)
    {
        Emit("[fwd] notify_url has no path portion");
        free(job);
        return 0;
    }

    char hostPort[256];
    size_t hpLen = (size_t)(path - auth);
    if (hpLen >= sizeof(hostPort))
        hpLen = sizeof(hostPort) - 1;
    memcpy(hostPort, auth, hpLen);
    hostPort[hpLen] = 0;

    char reqPath[2048];
    GT_SNPRINTF(reqPath, sizeof(reqPath), "%s", path);
    if (reqPath[0] == 0)
        GT_SNPRINTF(reqPath, sizeof(reqPath), "/");

    char host[256];
    GT_SNPRINTF(host, sizeof(host), "%s", hostPort);
    int port = 80;
    char *colon = strchr(host, ':');
    if (colon)
    {
        port = atoi(colon + 1);
        *colon = 0;
    }

    char m[768];
    GT_SNPRINTF(m, sizeof(m), "[fwd] POST http://%s:%d%.200s body=%.400s", host, port, reqPath, job->body);
    Emit(m);

    HMODULE wh = GetModuleHandleW(L"winhttp.dll");
    if (!wh)
        wh = LoadLibraryW(L"winhttp.dll");
    if (!wh)
    {
        Emit("[fwd] winhttp.dll not loadable");
        free(job);
        return 0;
    }

    typedef void *(__stdcall * TWinHttpOpen)(const wchar_t *, unsigned long, const wchar_t *, const wchar_t *,
                                             unsigned long);
    typedef int(__stdcall * TWinHttpSetTimeouts)(void *, int, int, int, int);
    typedef void *(__stdcall * TWinHttpConnect)(void *, const wchar_t *, unsigned short, unsigned long);
    typedef void *(__stdcall * TWinHttpOpenRequest)(void *, const wchar_t *, const wchar_t *, const wchar_t *, void *,
                                                    const void **, unsigned long);
    typedef int(__stdcall * TWinHttpAddRequestHeaders)(void *, const wchar_t *, unsigned long, unsigned long);
    typedef int(__stdcall * TWinHttpSendRequest)(void *, void *, unsigned long, void *, unsigned long, unsigned long,
                                                 unsigned long long);
    typedef int(__stdcall * TWinHttpReceiveResponse)(void *, void *);
    typedef int(__stdcall * TWinHttpQueryHeaders)(void *, unsigned long, unsigned long, void *, unsigned long *,
                                                  unsigned long *);
    typedef int(__stdcall * TWinHttpCloseHandle)(void *);

#define GT_PROC(type, v, n) type v = (type)GetProcAddress(wh, n)
    GT_PROC(TWinHttpOpen, pOpen, "WinHttpOpen");
    GT_PROC(TWinHttpSetTimeouts, pTO, "WinHttpSetTimeouts");
    GT_PROC(TWinHttpConnect, pConn, "WinHttpConnect");
    GT_PROC(TWinHttpOpenRequest, pOpenReq, "WinHttpOpenRequest");
    GT_PROC(TWinHttpAddRequestHeaders, pHdrs, "WinHttpAddRequestHeaders");
    GT_PROC(TWinHttpSendRequest, pSendReq, "WinHttpSendRequest");
    GT_PROC(TWinHttpReceiveResponse, pRecv, "WinHttpReceiveResponse");
    GT_PROC(TWinHttpQueryHeaders, pQuery, "WinHttpQueryHeaders");
    GT_PROC(TWinHttpCloseHandle, pClose, "WinHttpCloseHandle");
#undef GT_PROC
    if (!pOpen || !pConn || !pOpenReq || !pHdrs || !pSendReq || !pRecv || !pClose)
    {
        Emit("[fwd] WinHTTP exports missing");
        free(job);
        return 0;
    }

    wchar_t hostW[256];
    MultiByteToWideChar(CP_UTF8, 0, host, -1, hostW, 256);

    size_t rplen = strlen(reqPath);
    wchar_t *pathW = (wchar_t *)malloc((rplen + 1) * sizeof(wchar_t));
    if (!pathW)
    {
        free(job);
        return 0;
    }
    int wlen = MultiByteToWideChar(CP_UTF8, 0, reqPath, (int)rplen, pathW, (int)(rplen + 1));
    if (wlen > 0)
        pathW[wlen] = 0;
    else
        pathW[0] = 0;

    void *ses = pOpen(L"gtdump_hook-fwd", 1, NULL, NULL, 0);
    if (!ses)
    {
        GT_SNPRINTF(m, sizeof(m), "[fwd] WinHttpOpen failed err=%lu", GetLastError());
        Emit(m);
        free(pathW);
        free(job);
        return 0;
    }

    void *con = pConn(ses, hostW, (unsigned short)(port > 0 && port <= 65535 ? port : 80), 0);
    if (!con)
    {
        GT_SNPRINTF(m, sizeof(m), "[fwd] WinHttpConnect(%s:%d) failed err=%lu", host, port, GetLastError());
        Emit(m);
        pClose(ses);
        free(pathW);
        free(job);
        return 0;
    }

    void *req = pOpenReq(con, L"POST", pathW, L"HTTP/1.1", NULL, NULL, 0);
    if (!req)
    {
        GT_SNPRINTF(m, sizeof(m), "[fwd] WinHttpOpenRequest failed err=%lu", GetLastError());
        Emit(m);
        pClose(con);
        pClose(ses);
        free(pathW);
        free(job);
        return 0;
    }

    if (pTO)
        pTO(req, g_notifyTimeout, g_notifyTimeout, g_notifyTimeout, g_notifyTimeout);
    pHdrs(req, L"Content-Type: application/x-www-form-urlencoded\r\n", (unsigned long)-1, 4);

    unsigned long bodyLen = (unsigned long)strlen(job->body);
    BOOL sent = pSendReq(req, NULL, 0, (void *)job->body, bodyLen, bodyLen, 0);
    if (sent && pRecv)
        sent = pRecv(req, NULL);

    unsigned long status = 0;
    if (sent && pQuery)
    {
        wchar_t stc[16] = {0};
        unsigned long sz = sizeof(stc);
        if (pQuery(req, 19, 0, stc, &sz, 0))
            status = (unsigned long)wcstoul(stc, NULL, 10);
    }
    pClose(req);
    pClose(con);
    pClose(ses);
    free(pathW);

    GT_SNPRINTF(m, sizeof(m), "[fwd] POST http://%s:%d%.200s sent=%d status=%lu err=%lu", host, port, reqPath, sent,
                status, sent ? 0 : GetLastError());
    Emit(m);
    free(job);
    return 0;
}

static void TrySendNotify(void)
{
    if (!g_notifyUrl[0])
        return;
    if (!g_reqVersion[0] || !g_reqProtocol[0] || !g_reqPlatform[0] || !g_realServer[0] || !g_realPort)
        return;
    if (InterlockedExchange(&g_notified, 1))
        return;

    char body[MAX_NOTIFY_BODY];
    BuildNotifyBody(body, sizeof(body));

    struct NotifyJob *job = (struct NotifyJob *)malloc(sizeof(struct NotifyJob));
    if (!job)
    {
        InterlockedExchange(&g_notified, 0);
        return;
    }
    memset(job, 0, sizeof(*job));
    GT_SNPRINTF(job->url, sizeof(job->url), "%s", g_notifyUrl);
    GT_SNPRINTF(job->body, sizeof(job->body), "%.*s", (int)(strlen(body) > 500 ? 500 : strlen(body)), body);

    HANDLE t = CreateThread(NULL, 0, NotifySendThread, job, 0, NULL);
    if (t)
    {
        CloseHandle(t);
        char m[640];
        GT_SNPRINTF(m, sizeof(m), "[fwd] forward dispatched (worker thread): url=%s", g_notifyUrl);
        Emit(m);
    }
    else
    {
        free(job);
        InterlockedExchange(&g_notified, 0);
        char m[128];
        GT_SNPRINTF(m, sizeof(m), "[fwd] CreateThread failed err=%lu", GetLastError());
        Emit(m);
    }
}

static uintptr_t GT_FASTCALL Hook_HttpPost(void *client, void *urlStr, int isTls, void *dict, void *callback)
{
    if (g_origHttpPost)
    {
        uintptr_t rc = g_origHttpPost(client, urlStr, isTls, dict, callback);

        struct GtString *u = (struct GtString *)urlStr;
        const char *url = (u && u->size) ? GtStringData(u) : NULL;
        if (url && strstr(url, "server_data.php"))
        {
            Emit("[hook] HttpClient_PostWithCallback: server_data.php request (capturing params)");
            CaptureRequestParams(dict);
            TrySendNotify();
        }
        return rc;
    }
    Emit("[hook] HttpClient_PostWithCallback: g_origHttpPost is NULL!");
    return 0;
}

static long long GT_FASTCALL Hook_GameLogPrintf(const char *fmt, ...)
{
    char line[8192];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    Emit(line);

    if (g_origLogPrintf)
        return g_origLogPrintf("%s", line);
    return 0;
}

static long long GT_FASTCALL Hook_GameLogRaw(const char *fmt, ...)
{
    char line[12288];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof(line), fmt, ap);
    va_end(ap);
    Emit(line);

    if (g_origLogRaw)
        return g_origLogRaw("%s", line);
    return 0;
}

static size_t ImageSizeOf(uint8_t *base)
{
    if (!base)
        return 0;
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE)
        return 0;
    IMAGE_NT_HEADERS64 *nt = (IMAGE_NT_HEADERS64 *)(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE)
        return 0;
    return nt->OptionalHeader.SizeOfImage;
}

struct PatBytes
{
    uint8_t bytes[512];
    uint8_t mask[512];
    size_t len;
};

static int HexNibble(char c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}

static int ParsePattern(const char *pat, struct PatBytes *out)
{
    out->len = 0;
    const char *p = pat;
    while (*p)
    {
        while (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')
            p++;
        if (!*p)
            break;
        if (out->len >= sizeof(out->bytes))
            return 0;
        if (p[0] == '?' && p[1] == '?')
        {
            out->mask[out->len] = 0;
            out->bytes[out->len] = 0;
            p += 2;
        }
        else
        {
            int hi = HexNibble(p[0]);
            int lo = (hi >= 0) ? HexNibble(p[1]) : -1;
            if (hi < 0 || lo < 0)
                return 0;
            out->mask[out->len] = 0xFF;
            out->bytes[out->len] = (uint8_t)((hi << 4) | lo);
            p += 2;
        }
        out->len++;
    }
    return out->len > 0;
}

static int MatchAt(const uint8_t *mem, const struct PatBytes *p)
{
    for (size_t i = 0; i < p->len; i++)
    {
        if (p->mask[i] && mem[i] != p->bytes[i])
            return 0;
    }
    return 1;
}

static uint8_t *FindPattern(const char *pat)
{
    if (!g_base || !g_isTarget)
        return NULL;
    struct PatBytes p;
    if (!ParsePattern(pat, &p))
        return NULL;
    uint8_t *end = g_base + g_imageSize;
    for (uint8_t *q = g_base; q + p.len <= end; ++q)
    {
        if (MatchAt(q, &p))
            return q;
    }
    return NULL;
}

static int CountPattern(const char *pat, uint8_t **firstHit, uint8_t **secondHit)
{
    if (!g_base || !g_isTarget)
        return 0;
    struct PatBytes p;
    if (!ParsePattern(pat, &p))
        return 0;
    int n = 0;
    uint8_t *end = g_base + g_imageSize;
    for (uint8_t *q = g_base; q + p.len <= end; ++q)
    {
        if (MatchAt(q, &p))
        {
            if (n == 0 && firstHit)
                *firstHit = q;
            if (n == 1 && secondHit)
                *secondHit = q;
            n++;
            if (n > 2)
                break;
        }
    }
    return n;
}

static int IsCodeAddr(const void *p)
{
    uintptr_t v = (uintptr_t)p;
    return v > 0x10000 && v < 0x7FFFFFFFFFFFull;
}

static void *FindInvokeVtable(void *doCall)
{
    if (!g_base || !g_isTarget || !doCall)
        return NULL;
    uint8_t *end = g_base + g_imageSize;
    for (uint8_t *q = g_base; q + sizeof(void *) <= end; q += sizeof(void *))
    {
        if (*(void **)q != doCall)
            continue;
        uint8_t *vt = q - 0x10;
        if (vt < g_base)
            continue;
        void **v = (void **)vt;
        if (!IsCodeAddr(v[0]) || !IsCodeAddr(v[1]) || !IsCodeAddr(v[3]) || !IsCodeAddr(v[4]) || !IsCodeAddr(v[5]))
            continue;
        return (void *)vt;
    }
    return NULL;
}

static void CrossCheck(char *out, size_t n, const void *found, uintptr_t refRva)
{
    if (!found || !g_base)
    {
        GT_SNPRINTF(out, n, "not found");
        return;
    }
    long long d = (long long)((uintptr_t)found - (uintptr_t)g_base) - (long long)refRva;
    if (d == 0)
        GT_SNPRINTF(out, n, "same as ref build");
    else
        GT_SNPRINTF(out, n, "MOVED %+lld bytes (new build)", d);
}

static const char *SIG_CONN = "40 53 55 56 57 41 56 48 83 ec 60 45 8b f0 48 8b ea 48 8b f9 48 8b b4 24 ?? "
                              "?? ?? ?? 48 8d 0d ?? ?? ?? ?? e8 ?? ?? ?? ?? c7 87 5c 04 00 00 03 00 00 00 e8 ?? "
                              "?? ?? ?? 48 8b 88 d0 0a 00 00 c7 81 f0 00 00 00 00 00 00 00 e8 ?? ?? ?? ?? 8b "
                              "8f 14 04 00 00 89 88 ?? ?? ?? ?? e8 ?? ?? ?? ?? 48 8d 9f f0 03 00 00 80 b8 ?? "
                              "?? ?? ?? 00 74 1a 44 8b 87 10 04 00 00 48 83 7b 18 0f 76 03 48 8b 1b 48 8d 0d "
                              "?? ?? ?? ?? eb 63";

static const char *SIG_LOG_PRINTF = "48 89 4C 24 08 48 89 54 24 10 4C 89 44 24 18 4C 89 4C 24 20 "
                                    "53 57 B8 88 10 00 00 E8 ?? ?? ?? ?? 48 2B E0 48 8B 05 ?? ?? ?? ?? 48 33 C4 "
                                    "48 89 84 24 70 10 00 00 48 8B D9 33 D2 48 8D 4C 24 70 41";

static const char *SIG_LOG_RAW = "48 89 4C 24 08 48 89 54 24 10 4C 89 44 24 18 4C 89 4C 24 20 "
                                 "53 57 B8 68 28 00 00 E8 ?? ?? ?? ?? 48 2B E0 48 8B 05 ?? ?? ?? ?? 48 33 C4 "
                                 "48 89 84 24 50 28 00 00 48 8B D9 33 D2 48 8D 4C 24 40 41";

static const char *SIG_RESP = "40 55 56 48 83 EC 28 81 BA ?? ?? ?? ?? C8 00 00 00 "
                              "48 8B EA 48 8B 41 08 48 8B F1 75 1D C7 80 ?? ?? ?? ?? 00 00 00 00";

static const char *SIG_HTTP_POST = "40 55 53 56 57 41 54 41 55 41 56 41 57 48 8D AC 24 48 FD FF FF "
                                   "48 81 EC B8 03 00 00 48 8B 05 ?? ?? ?? ?? 48 33 C4 48 89 85 A0 02 00 00 "
                                   "4C 89 4C 24 40 45 8B E0 4C 8B FA 4C 8B E9";

static void ReportMitigations(void)
{
    struct
    {
        int id;
        const char *name;
    } q[] = {
        {2, "dynamic-code (ACG)"},
        {3, "signature policy"  },
        {1, "extension point"   },
        {5, "image load"        },
    };
    size_t nq = sizeof(q) / sizeof(q[0]);
    for (size_t i = 0; i < nq; i++)
    {
        DWORD v = 0;
        if (GetProcessMitigationPolicy(GetCurrentProcess(), (PROCESS_MITIGATION_POLICY)q[i].id, (PVOID)&v, sizeof(v)))
        {
            char m[160];
            GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] mitigation %-20s: 0x%lX%s", q[i].name, v,
                        (q[i].id == 2 && v) ? "   <-- executable pages restricted" : "");
            Emit(m);
        }
    }
}

typedef NTSTATUS(NTAPI *PFN_NtProtect)(HANDLE, PVOID *, PULONG, ULONG, PULONG);
typedef NTSTATUS(NTAPI *PFN_NtWrite)(HANDLE, PVOID, PVOID, SIZE_T, PSIZE_T);
typedef NTSTATUS(NTAPI *PFN_NtFlush)(HANDLE, PVOID, ULONG, ULONG);

static PFN_NtProtect g_ntProtect = NULL;
static PFN_NtWrite g_ntWrite = NULL;
static PFN_NtFlush g_ntFlush = NULL;
static int g_sysInit = 0;

static int ReadSyscallNumber(const char *name, uint32_t *out)
{
    HMODULE ntdll = GetModuleHandleA("ntdll.dll");
    if (!ntdll)
        return 0;
    const uint8_t *p = (const uint8_t *)GetProcAddress(ntdll, name);
    if (!p)
        return 0;
    if (p[0] == 0x4C && p[1] == 0x8B && p[2] == 0xD1 && p[3] == 0xB8)
    {
        memcpy(out, p + 4, sizeof(uint32_t));
        return 1;
    }
    return 0;
}

static void *BuildThunk(uint32_t ssn, const char *name)
{
    uint8_t code[16];
    size_t i = 0;
    code[i++] = 0xF3;
    code[i++] = 0x0F;
    code[i++] = 0x1E;
    code[i++] = 0xFA;
    code[i++] = 0x49;
    code[i++] = 0x89;
    code[i++] = 0xD1;
    code[i++] = 0xB8;
    code[i++] = (uint8_t)(ssn & 0xFF);
    code[i++] = (uint8_t)((ssn >> 8) & 0xFF);
    code[i++] = (uint8_t)((ssn >> 16) & 0xFF);
    code[i++] = (uint8_t)((ssn >> 24) & 0xFF);
    code[i++] = 0x0F;
    code[i++] = 0x05;
    code[i++] = 0xC3;

    void *mem = VirtualAlloc(NULL, i, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!mem)
    {
        char m[160];
        GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] thunk %s alloc failed err=%lu", name, GetLastError());
        Emit(m);
        return NULL;
    }
    memcpy(mem, code, i);
    FlushInstructionCache(GetCurrentProcess(), mem, i);

    char m[160];
    GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] syscall thunk %-22s ssn=0x%02X at %p", name, ssn, mem);
    Emit(m);
    return mem;
}

static int EnablePrivilege(const char *name)
{
    char m[224];
    HANDLE tok = NULL;
    if (!OpenProcessToken(GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, &tok))
    {
        GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] privilege %s : OpenProcessToken failed err=%lu", name, GetLastError());
        Emit(m);
        return 0;
    }
    {
        DWORD sz = 0, elev = 0;
        if (GetTokenInformation(tok, TokenElevation, &elev, sizeof(elev), &sz) && elev)
            Emit("[gtdump_hook] process token : ELEVATED (administrator)");
        else
            Emit("[gtdump_hook] process token : NOT elevated - run the game as administrator");
    }
    LUID luid;
    if (!LookupPrivilegeValueA(NULL, name, &luid))
    {
        GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] privilege %s : LookupPrivilegeValue failed err=%lu", name,
                    GetLastError());
        Emit(m);
        CloseHandle(tok);
        return 0;
    }
    TOKEN_PRIVILEGES tp;
    tp.PrivilegeCount = 1;
    tp.Privileges[0].Luid = luid;
    tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED;
    SetLastError(0);
    BOOL adj = AdjustTokenPrivileges(tok, FALSE, &tp, sizeof(tp), NULL, NULL);
    DWORD err = GetLastError();
    CloseHandle(tok);
    if (adj && err == ERROR_SUCCESS)
    {
        GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] privilege %s : enabled", name);
        Emit(m);
        return 1;
    }
    GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] privilege %s : FAILED (err=%lu%s) - %s", name, err,
                err == ERROR_NOT_ALL_ASSIGNED ? " ERROR_NOT_ALL_ASSIGNED: not in this token" : "",
                "launch Growtopia.exe as administrator, then inject again");
    Emit(m);
    return 0;
}

static void InitSyscalls(void)
{
    if (g_sysInit)
        return;
    g_sysInit = 1;
    EnablePrivilege(SE_DEBUG_NAME);

    uint32_t nProtect = 0x50, nWrite = 0x3A, nFlush = 0x36, v = 0;
    if (ReadSyscallNumber("NtProtectVirtualMemory", &v))
    {
        nProtect = v;
        Emit("[gtdump_hook] ssn NtProtectVirtualMemory read from ntdll (stub intact)");
    }
    else
    {
        char m[128];
        GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] ssn NtProtectVirtualMemory stub hooked - using default 0x%02X",
                    nProtect);
        Emit(m);
    }
    if (ReadSyscallNumber("NtWriteVirtualMemory", &v))
        nWrite = v;
    if (ReadSyscallNumber("NtFlushInstructionCache", &v))
        nFlush = v;

    g_ntProtect = (PFN_NtProtect)BuildThunk(nProtect, "NtProtectVirtualMemory");
    g_ntWrite = (PFN_NtWrite)BuildThunk(nWrite, "NtWriteVirtualMemory");
    g_ntFlush = (PFN_NtFlush)BuildThunk(nFlush, "NtFlushInstructionCache");
}

static int NtProtectExec(void *addr, size_t sz, ULONG prot, DWORD *oldProt)
{
    static PFN_NtProtect f = NULL;
    if (!f)
        f = (PFN_NtProtect)GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "NtProtectVirtualMemory");
    if (!f)
        return 0;
    PVOID p = addr;
    ULONG s = (ULONG)sz;
    ULONG op = 0;
    LONG st = f(GetCurrentProcess(), &p, &s, prot, &op);
    if (st == 0 && oldProt)
        *oldProt = (DWORD)op;
    return st == 0;
}

static int DirectPatch(void *addr, const uint8_t *bytes, size_t len, const char *name)
{
    if (!g_ntProtect || !g_ntWrite || !g_ntFlush)
        return 0;

    const DWORD prot[2] = {PAGE_EXECUTE_READWRITE, PAGE_EXECUTE_WRITECOPY};
    static const char *pname[2] = {"RWX", "WRITECOPY"};
    NTSTATUS lastSt = (NTSTATUS)0xFFFFFFFF;

    for (int i = 0; i < 2; i++)
    {
        PVOID base = addr;
        ULONG sz = (ULONG)len;
        ULONG oldProt = 0;
        NTSTATUS st = g_ntProtect(GetCurrentProcess(), &base, &sz, prot[i], &oldProt);
        if (st < 0)
        {
            lastSt = st;
            char m[224];
            GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] %-20s : syscall NtProtect(%s) -> 0x%08lX", name, pname[i],
                        (unsigned long)st);
            Emit(m);
            continue;
        }
        SIZE_T written = 0;
        st = g_ntWrite(GetCurrentProcess(), addr, (PVOID)bytes, len, &written);
        if (st < 0 || written != len)
        {
            lastSt = st;
            char m[224];
            GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] %-20s : syscall NtWrite -> 0x%08lX (%zu/%zu)", name,
                        (unsigned long)st, (size_t)written, len);
            Emit(m);
            continue;
        }
        g_ntFlush(GetCurrentProcess(), addr, (ULONG)len, 0);
        PVOID rb = addr;
        ULONG rs = (ULONG)len;
        ULONG dummy = 0;
        g_ntProtect(GetCurrentProcess(), &rb, &rs, oldProt, &dummy);
        char m[160];
        GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] %-20s : PATCHED at %p via syscall (%s)", name, addr, pname[i]);
        Emit(m);
        return 1;
    }
    char m[224];
    GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] %-20s : syscall NtProtect failed both protections, last=0x%08lX", name,
                (unsigned long)lastSt);
    Emit(m);
    return 0;
}

static void SuspendOthers(void)
{
    g_suspended_count = 0;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0);
    if (snap == INVALID_HANDLE_VALUE)
        return;
    DWORD pid = GetCurrentProcessId();
    DWORD self = GetCurrentThreadId();
    THREADENTRY32 te;
    memset(&te, 0, sizeof(te));
    te.dwSize = sizeof(te);
    if (Thread32First(snap, &te))
    {
        do
        {
            if (te.th32OwnerProcessID == pid && te.th32ThreadID != self)
            {
                HANDLE h = OpenThread(THREAD_SUSPEND_RESUME, FALSE, te.th32ThreadID);
                if (h)
                {
                    if (SuspendThread(h) != (DWORD)-1)
                    {
                        if (g_suspended_count < MAX_SUSPENDED)
                            g_suspended[g_suspended_count++] = h;
                        else
                            CloseHandle(h);
                    }
                    else
                    {
                        CloseHandle(h);
                    }
                }
            }
        } while (Thread32Next(snap, &te));
    }
    CloseHandle(snap);
}

static void ResumeOthers(void)
{
    for (size_t i = 0; i < g_suspended_count; i++)
    {
        ResumeThread(g_suspended[i]);
        CloseHandle(g_suspended[i]);
    }
    g_suspended_count = 0;
}

static int BuildTrampoline(struct Detour *d, const char *name, void *target, size_t len)
{
    if (!d || !target || len < 5 || len > sizeof(d->stolen))
    {
        char m[192];
        GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] %-20s : cannot build trampoline (target=%p len=%zu)", name, target,
                    len);
        Emit(m);
        return 0;
    }
    d->target = (uint8_t *)target;
    d->len = len;
    memcpy(d->stolen, target, len);

    size_t tsize = len + 16;
    uint8_t *t = (uint8_t *)VirtualAlloc(NULL, tsize, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!t)
    {
        DWORD e1 = GetLastError();
        t = (uint8_t *)VirtualAlloc(NULL, tsize, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
        if (t)
        {
            DWORD wp = 0;
            if (!VirtualProtect(t, tsize, PAGE_EXECUTE_READ, &wp))
            {
                char m[224];
                GT_SNPRINTF(m, sizeof(m),
                            "[gtdump_hook] %-20s : trampoline RWX denied (%lu), RW ok but promote failed (%lu)", name,
                            e1, GetLastError());
                Emit(m);
                VirtualFree(t, 0, MEM_RELEASE);
                return 0;
            }
            char m[224];
            GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] %-20s : RWX alloc denied (%lu), using RW+promote", name, e1);
            Emit(m);
        }
    }
    if (!t)
    {
        char m[224];
        GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] %-20s : trampoline VirtualAlloc failed err=%lu at %p", name,
                    GetLastError(), target);
        Emit(m);
        return 0;
    }

    memcpy(t, d->stolen, len);
    t[len + 0] = 0xFF;
    t[len + 1] = 0x25;
    t[len + 2] = t[len + 3] = t[len + 4] = t[len + 5] = 0;
    *(void **)(t + len + 6) = (void *)((uint8_t *)target + len);
    FlushInstructionCache(GetCurrentProcess(), t, tsize);
    d->trampoline = t;

    char m[192];
    GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] %-20s : trampoline ready at %p (%zu stolen bytes from %p)", name,
                (void *)t, len, target);
    Emit(m);
    return 1;
}

static int Detour_Install(struct Detour *d, const char *name, void *target, void *detour, size_t len)
{
    InitSyscalls();
    if (!target || !detour || len < 5 || len > sizeof(d->stolen))
    {
        char m[160];
        GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] %-20s : bad args (target=%p detour=%p len=%zu)", name, target, detour,
                    len);
        Emit(m);
        return 0;
    }
    if (!BuildTrampoline(d, name, target, len))
        return 0;

    SuspendOthers();
    DWORD old = 0;
    int patched = 0;
    DWORD err = 0;
    const DWORD tries[2] = {PAGE_EXECUTE_READWRITE, PAGE_EXECUTE_WRITECOPY};
    for (int i = 0; i < 2 && !patched; i++)
    {
        if (VirtualProtect(target, len, tries[i], &old))
        {
            uint8_t patch[32];
            patch[0] = 0xE9;
            int32_t rel = (int32_t)((intptr_t)detour - ((intptr_t)target + 5));
            memcpy(patch + 1, &rel, 4);
            for (size_t k = 5; k < len; k++)
                patch[k] = 0x90;
            memcpy(target, patch, len);
            FlushInstructionCache(GetCurrentProcess(), target, len);
            DWORD tmp;
            if (i == 0)
                VirtualProtect(target, len, old, &tmp);
            patched = 1;
        }
        else
        {
            err = GetLastError();
        }
    }
    for (int i = 0; i < 2 && !patched; i++)
    {
        if (NtProtectExec(target, len, tries[i], &old))
        {
            uint8_t patch[32];
            patch[0] = 0xE9;
            int32_t rel = (int32_t)((intptr_t)detour - ((intptr_t)target + 5));
            memcpy(patch + 1, &rel, 4);
            for (size_t k = 5; k < len; k++)
                patch[k] = 0x90;
            memcpy(target, patch, len);
            FlushInstructionCache(GetCurrentProcess(), target, len);
            DWORD tmp;
            if (i == 0)
                VirtualProtect(target, len, old, &tmp);
            patched = 1;
        }
    }
    if (!patched)
    {
        uint8_t patch[32];
        patch[0] = 0xE9;
        int32_t rel = (int32_t)((intptr_t)detour - ((intptr_t)target + 5));
        memcpy(patch + 1, &rel, 4);
        for (size_t k = 5; k < len; k++)
            patch[k] = 0x90;
        patched = DirectPatch(target, patch, len, name);
    }
    ResumeOthers();

    if (!patched)
    {
        char m[224];
        GT_SNPRINTF(
            m, sizeof(m),
            "[gtdump_hook] %-20s : could not patch %p (VirtualProtect/NtProtect/direct-syscall all failed, err=%lu)",
            name, target, err);
        Emit(m);
    }

    d->installed = patched;
    d->ok = patched;
    return patched;
}

static void WriteHandshake(void *pConn, void *pLP, void *pLR, void *pResp, void *pPost);

static void InstallHooks(void)
{
    uint8_t *pConn = FindPattern(SIG_CONN);
    uint8_t *pLP = FindPattern(SIG_LOG_PRINTF);
    uint8_t *pLR = FindPattern(SIG_LOG_RAW);
    uint8_t *pResp = FindPattern(SIG_RESP);
    uint8_t *pPost = FindPattern(SIG_HTTP_POST);

    uint8_t *h1 = NULL;
    uint8_t *h2 = NULL;
    int nConn = CountPattern(SIG_CONN, &h1, &h2);
    int nLP = CountPattern(SIG_LOG_PRINTF, &h1, &h2);
    int nLR = CountPattern(SIG_LOG_RAW, &h1, &h2);
    int nResp = CountPattern(SIG_RESP, &h1, &h2);
    int nPost = CountPattern(SIG_HTTP_POST, &h1, &h2);

    g_onResponse = NULL;
    if (pResp)
        g_cbVtable = (uint8_t **)FindInvokeVtable(pResp);
    if (pResp && !g_cbVtable)
        Emit("[gtdump_hook] WARNING: found OnServerDataResponse but not its _Func_impl vftable");

    ReportMitigations();

    if (g_outOfProcess)
    {
        int tLP = pLP && BuildTrampoline(&dLogP, "GameLog_Printf", pLP, STOLEN_LOG);
        int tLR = pLR && BuildTrampoline(&dLogR, "GameLog_Raw", pLR, STOLEN_LOG);
        int tConn = pConn && BuildTrampoline(&dConn, "ConnectToGameServer", pConn, STOLEN_CONNECT);
        int tResp = pResp && BuildTrampoline(&dResp, "OnServerDataResponse", pResp, STOLEN_ONRESPONSE);
        int tPost = pPost && BuildTrampoline(&dPost, "HttpClient_Post", pPost, STOLEN_HTTPPOST);

        if (tLP)
            g_origLogPrintf = (FnLog)dLogP.trampoline;
        if (tLR)
            g_origLogRaw = (FnLog)dLogR.trampoline;
        if (tConn)
            g_origConnect = (FnConnect)dConn.trampoline;
        if (tResp)
            g_onResponse = (FnOnResponse)dResp.trampoline;
        if (tPost)
            g_origHttpPost = (FnHttpPost)dPost.trampoline;

        char m[256];
        GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] out_of_process=1 trampolines: logp=%s logr=%s conn=%s resp=%s post=%s",
                    tLP ? "ready" : "MISSING", tLR ? "ready" : "MISSING", tConn ? "ready" : "MISSING",
                    tResp ? "ready" : "MISSING", tPost ? "ready" : "MISSING");
        Emit(m);

        WriteHandshake(pConn, pLP, pLR, pResp, pPost);
        GT_SNPRINTF(m, sizeof(m),
                    "[gtdump_hook] out_of_process=1 : handshake published. Run injector_patch.exe "
                    "(elevated) - it only writes 14-byte entry jumps; trampolines and "
                    "g_orig*/g_onResponse are already live here.");
        Emit(m);
        return;
    }

    int okLP = 0, okLR = 0, okConn = 0, okResp = 0, okPost = 0;
    if (pLP)
        okLP = Detour_Install(&dLogP, "GameLog_Printf", pLP, (void *)Hook_GameLogPrintf, STOLEN_LOG);
    if (pLR)
        okLR = Detour_Install(&dLogR, "GameLog_Raw", pLR, (void *)Hook_GameLogRaw, STOLEN_LOG);
    if (pConn)
        okConn = Detour_Install(&dConn, "ConnectToGameServer", pConn, (void *)Hook_ConnectToGameServer, STOLEN_CONNECT);
    if (pResp)
        okResp =
            Detour_Install(&dResp, "OnServerDataResponse", pResp, (void *)Hook_OnServerDataResponse, STOLEN_ONRESPONSE);
    if (pPost)
        okPost = Detour_Install(&dPost, "HttpClient_Post", pPost, (void *)Hook_HttpPost, STOLEN_HTTPPOST);
    if (okLP)
        g_origLogPrintf = (FnLog)dLogP.trampoline;
    if (okLR)
        g_origLogRaw = (FnLog)dLogR.trampoline;
    if (okConn)
        g_origConnect = (FnConnect)dConn.trampoline;
    if (okResp)
        g_onResponse = (FnOnResponse)dResp.trampoline;
    if (okPost)
        g_origHttpPost = (FnHttpPost)dPost.trampoline;

    char ccConn[64], ccLP[64], ccLR[64], ccResp[64], ccPost[64];
    CrossCheck(ccConn, sizeof(ccConn), pConn, RVA_CONNECT);
    CrossCheck(ccLP, sizeof(ccLP), pLP, RVA_LOG_PRINTF);
    CrossCheck(ccLR, sizeof(ccLR), pLR, RVA_LOG_RAW);
    CrossCheck(ccResp, sizeof(ccResp), pResp, RVA_ON_RESPONSE);
    CrossCheck(ccPost, sizeof(ccPost), pPost, RVA_HTTP_POST);

    char st[4600];
    GT_SNPRINTF(st, sizeof(st),
                "\n[gtdump_hook] ===== HOOK STATUS (pattern matched, no hardcoded RVAs) =====\n"
                "[gtdump_hook] module base         : %p (SizeOfImage 0x%X, target module %s)\n"
                "[gtdump_hook] GameLog_Printf      : %-6s at %p   [%s]\n"
                "[gtdump_hook] GameLog_Raw         : %-6s at %p   [%s]\n"
                "[gtdump_hook] ConnectToGameServer : %-6s at %p   [%s]\n"
                "[gtdump_hook] OnServerDataResponse: %-6s at %p   [%s]\n"
                "[gtdump_hook] HttpClient_Post     : %-6s at %p   [%s]\n"
                "[gtdump_hook] callback vtable     : %p\n"
                "[gtdump_hook] signature hits      : Conn=%d LP=%d LR=%d Resp=%d Post=%d (want 1)\n"
                "[gtdump_hook] request suppressed  : %s\n"
                "[gtdump_hook] target server       : %s : %d  (type %d, loginurl %s)\n"
                "[gtdump_hook] forward POST        : %s -> %s (timeout %d ms, sent once)\n"
                "[gtdump_hook] log file            : %s\n"
                "[gtdump_hook] ====================================================\n",
                (void *)g_base, (unsigned)g_imageSize, g_isTarget ? "yes" : "NO - nothing will be patched",
                okLP ? "OK" : "FAIL", (void *)pLP, ccLP, okLR ? "OK" : "FAIL", (void *)pLR, ccLR,
                okConn ? "OK" : "FAIL", (void *)pConn, ccConn, okResp ? "OK" : "FAIL", (void *)pResp, ccResp,
                okPost ? "OK" : "FAIL", (void *)pPost, ccPost, (void *)g_cbVtable, nConn, nLP, nLR, nResp, nPost,
                g_nopRequest ? "YES" : "no (passthrough)", g_ip, g_port, g_type, g_loginUrl,
                g_notifyUrl[0] ? "on" : "off", g_notifyUrl, g_notifyTimeout, g_logPath);

    Emit(st);
    if (g_origLogPrintf)
        g_origLogPrintf("%s", st);
    if (g_origLogRaw)
        g_origLogRaw("%s", st);

    if (!okResp)
        Emit("[gtdump_hook] WARNING: OnServerDataResponse hook failed - the real response will be parsed unmodified.");
}

static void WriteHandshake(void *pConn, void *pLP, void *pLR, void *pResp, void *pPost)
{
    if (!g_handshake[0])
        return;

    char txt[3200];
    int n = GT_SNPRINTF(
        txt, sizeof(txt),
        "# gtdump_hook out-of-process handshake v4\n"
        "version              = 4\n"
        "pid                  = %lu\n"
        "dllbase              = 0x%llX\n"
        "imagebase            = 0x%llX\n"
        "target_connect       = 0x%llX\n"
        "target_logprintf     = 0x%llX\n"
        "target_lograw        = 0x%llX\n"
        "target_onresponse    = 0x%llX\n"
        "target_httppost      = 0x%llX\n"
        "hook_connect         = 0x%llX\n"
        "hook_logprintf      = 0x%llX\n"
        "hook_lograw          = 0x%llX\n"
        "hook_onresponse      = 0x%llX\n"
        "hook_httppost        = 0x%llX\n"
        "tramp_connect        = 0x%llX\n"
        "tramp_logprintf      = 0x%llX\n"
        "tramp_lograw          = 0x%llX\n"
        "tramp_onresponse     = 0x%llX\n"
        "tramp_httppost       = 0x%llX\n"
        "stolen_connect       = %zu\n"
        "stolen_logprintf     = %zu\n"
        "stolen_lograw        = %zu\n"
        "stolen_onresponse    = %zu\n"
        "stolen_httppost      = %zu\n"
        "on_response          = 0x%llX\n"
        "resp_vtable          = 0x%llX\n",
        (unsigned long)GetCurrentProcessId(), (unsigned long long)(uintptr_t)(g_hSelf),
        (unsigned long long)(uintptr_t)g_base, (unsigned long long)(uintptr_t)pConn, (unsigned long long)(uintptr_t)pLP,
        (unsigned long long)(uintptr_t)pLR, (unsigned long long)(uintptr_t)pResp, (unsigned long long)(uintptr_t)pPost,
        (unsigned long long)(uintptr_t)(void *)Hook_ConnectToGameServer,
        (unsigned long long)(uintptr_t)(void *)Hook_GameLogPrintf,
        (unsigned long long)(uintptr_t)(void *)Hook_GameLogRaw,
        (unsigned long long)(uintptr_t)(void *)Hook_OnServerDataResponse,
        (unsigned long long)(uintptr_t)(void *)Hook_HttpPost, (unsigned long long)(uintptr_t)dConn.trampoline,
        (unsigned long long)(uintptr_t)dLogP.trampoline, (unsigned long long)(uintptr_t)dLogR.trampoline,
        (unsigned long long)(uintptr_t)dResp.trampoline, (unsigned long long)(uintptr_t)dPost.trampoline, dConn.len,
        dLogP.len, dLogR.len, dResp.len, dPost.len, (unsigned long long)(uintptr_t)(void *)g_onResponse,
        (unsigned long long)(uintptr_t)(g_cbVtable ? *g_cbVtable : NULL));

    HANDLE h =
        CreateFileA(g_handshake, GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
    {
        char m[256];
        GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] handshake write FAILED err=%lu (%s)", GetLastError(), g_handshake);
        Emit(m);
        return;
    }
    DWORD w = 0;
    WriteFile(h, txt, (DWORD)n, &w, NULL);
    CloseHandle(h);

    char m[160];
    GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] handshake written (%d bytes) -> %s", n, g_handshake);
    Emit(m);
}

static void LoadConfig(void)
{
    char dir[MAX_PATH];
    memset(dir, 0, sizeof(dir));
    DirNameOfModule(g_hSelf, dir, sizeof(dir));
    GT_SNPRINTF(g_logPath, MAX_PATH, "%s\\gtdump_hook.log", dir);

    char tmp[512];
    if (GetEnvironmentVariableA("GTD_LOG", tmp, sizeof(tmp)) && tmp[0])
    {
        GT_SNPRINTF(g_logPath, MAX_PATH, "%s", tmp);
    }

    char cfgPath[MAX_PATH];
    GT_SNPRINTF(cfgPath, MAX_PATH, "%s\\gtdump_hook.cfg", dir);
    FILE *f = NULL;
    f = fopen(cfgPath, "r");
    if (f)
    {
        char line[MAX_LINE];
        while (fgets(line, sizeof(line), f))
        {
            TrimInPlace(line);
            if (line[0] == 0 || line[0] == '#' || line[0] == ';')
                continue;
            char *eq = strchr(line, '=');
            if (!eq)
                continue;
            *eq = 0;
            char *k = line;
            char *v = eq + 1;
            TrimInPlace(k);
            TrimInPlace(v);
            if (strcmp(k, "server_ip") == 0)
                GT_SNPRINTF(g_ip, sizeof(g_ip), "%s", v);
            else if (strcmp(k, "server_port") == 0)
                g_port = atoi(v);
            else if (strcmp(k, "server_type") == 0)
                g_type = atoi(v);
            else if (strcmp(k, "loginurl") == 0)
                GT_SNPRINTF(g_loginUrl, sizeof(g_loginUrl), "%s", v);
            else if (strcmp(k, "logfile") == 0)
            {
                if (strchr(v, '\\') || strchr(v, '/') || strchr(v, ':'))
                    GT_SNPRINTF(g_logPath, MAX_PATH, "%s", v);
                else
                    GT_SNPRINTF(g_logPath, MAX_PATH, "%s\\%s", dir, v);
            }
            else if (strcmp(k, "delay_ms") == 0)
                g_delayMs = (DWORD)atoi(v);
            else if (strcmp(k, "verbose") == 0)
                g_verbose = atoi(v);
            else if (strcmp(k, "nop_request") == 0)
                g_nopRequest = atoi(v);
            else if (strcmp(k, "notify_url") == 0)
                GT_SNPRINTF(g_notifyUrl, sizeof(g_notifyUrl), "%s", v);
            else if (strcmp(k, "notify_format") == 0)
                GT_SNPRINTF(g_notifyFormat, sizeof(g_notifyFormat), "%s", v);
            else if (strcmp(k, "notify_timeout_ms") == 0)
                g_notifyTimeout = atoi(v);
            else if (strcmp(k, "allow_any_module") == 0)
                g_allowAnyMod = atoi(v);
            else if (strcmp(k, "out_of_process") == 0)
                g_outOfProcess = atoi(v);
            else if (strcmp(k, "handshake") == 0)
            {
                if (strchr(v, '\\') || strchr(v, '/') || strchr(v, ':'))
                    GT_SNPRINTF(g_handshake, MAX_PATH, "%s", v);
                else
                    GT_SNPRINTF(g_handshake, MAX_PATH, "%s\\%s", dir, v);
            }
        }
        fclose(f);
    }

    if (GetEnvironmentVariableA("GTD_IP", tmp, sizeof(tmp)) && tmp[0])
        GT_SNPRINTF(g_ip, sizeof(g_ip), "%s", tmp);
    if (GetEnvironmentVariableA("GTD_PORT", tmp, sizeof(tmp)) && tmp[0])
        g_port = atoi(tmp);
    if (GetEnvironmentVariableA("GTD_NOP", tmp, sizeof(tmp)) && tmp[0])
        g_nopRequest = atoi(tmp);
    if (GetEnvironmentVariableA("GTD_VERBOSE", tmp, sizeof(tmp)) && tmp[0])
        g_verbose = atoi(tmp);
}

static void EmitNow(const char *line)
{
    char buf[4400];
    SYSTEMTIME st;
    GetLocalTime(&st);
    int n = GT_SNPRINTF(buf, sizeof(buf), "[%02u:%02u:%02u.%03u][tid %5lu] %s\n", st.wHour, st.wMinute, st.wSecond,
                        st.wMilliseconds, (unsigned long)GetCurrentThreadId(), line ? line : "");
    if (g_logFile == INVALID_HANDLE_VALUE || n <= 0)
        return;

    BOOL held = g_logLockReady ? TryEnterCriticalSection(&g_logLock) : TRUE;
    DWORD w = 0;
    WriteFile(g_logFile, buf, (DWORD)n, &w, NULL);
    if (g_logLockReady && held)
        LeaveCriticalSection(&g_logLock);
}

static LONG NTAPI FirstChanceLogger(PEXCEPTION_POINTERS ep)
{
    if (!ep || !ep->ExceptionRecord || !ep->ContextRecord)
        return EXCEPTION_CONTINUE_SEARCH;
    DWORD code = (DWORD)ep->ExceptionRecord->ExceptionCode;
    if (code != 0xC0000005 && code != 0xC000001D && code != 0xC0000096 && code != 0xC00000FD)
        return EXCEPTION_CONTINUE_SEARCH;

    if (!g_base)
        return EXCEPTION_CONTINUE_SEARCH;
    uintptr_t rip = (uintptr_t)ep->ContextRecord->Rip;
    uintptr_t b = (uintptr_t)g_base;
    int inGame = (rip >= b && rip < b + g_imageSize);
    int inSelf = g_selfBase && rip >= (uintptr_t)g_selfBase && rip < (uintptr_t)g_selfBase + g_selfSize;
    if (!inGame && !inSelf)
        return EXCEPTION_CONTINUE_SEARCH;

    static uintptr_t seen[256];
    static int seenN = 0;
    static LONG lock = 0;
    while (InterlockedExchange(&lock, 1))
        Sleep(0);
    int dup = 0;
    for (int i = 0; i < seenN; i++)
        if (seen[i] == rip)
        {
            dup = 1;
            break;
        }
    if (dup)
    {
        InterlockedExchange(&lock, 0);
        return EXCEPTION_CONTINUE_SEARCH;
    }
    if (seenN < 256)
        seen[seenN++] = rip;
    InterlockedExchange(&lock, 0);

    uintptr_t fault = 0;
    if (code == 0xC0000005 && ep->ExceptionRecord->NumberParameters >= 2)
        fault = (uintptr_t)ep->ExceptionRecord->ExceptionInformation[1];
    char f[64];
    if (fault >= b && fault < b + g_imageSize)
        GT_SNPRINTF(f, sizeof(f), "0x%llX (rva 0x%llX)", (unsigned long long)fault, (unsigned long long)(fault - b));
    else
        GT_SNPRINTF(f, sizeof(f), "0x%llX", (unsigned long long)fault);

    char m[512];
    GT_SNPRINTF(m, sizeof(m), "[veh-1st] code=0x%08lX %s-rva=0x%llX fault=%s tid=%lu", code,
                inSelf && !inGame ? "HOOKDLL" : "rip",
                (unsigned long long)(inGame ? rip - b : rip - (uintptr_t)g_selfBase), f, GetCurrentThreadId());
    EmitNow(m);
    return EXCEPTION_CONTINUE_SEARCH;
}

static LONG WINAPI CrashFilter(EXCEPTION_POINTERS *ep)
{
    if (!ep || !ep->ExceptionRecord || !ep->ContextRecord || !g_base)
        return EXCEPTION_EXECUTE_HANDLER;

    EXCEPTION_RECORD *r = ep->ExceptionRecord;
    CONTEXT *c = ep->ContextRecord;
    uintptr_t rip = (uintptr_t)c->Rip;
    uintptr_t b = (uintptr_t)g_base;
    int inImage = rip >= b && rip < b + g_imageSize;

    char m[1024];
    GT_SNPRINTF(m, sizeof(m),
                "\n[gtdump_hook] ============ FATAL EXCEPTION ============\n"
                "[gtdump_hook] code=0x%08lX faultAddr=%p tid=%lu\n"
                "[gtdump_hook] rip=0x%llX  (module rva 0x%llX, in-image=%s)\n"
                "[gtdump_hook] rax=0x%llX rbx=0x%llX rcx=0x%llX rdx=0x%llX rsi=0x%llX rdi=0x%llX\n"
                "[gtdump_hook] rbp=0x%llX rsp=0x%llX r8=0x%llX r9=0x%llX r10=0x%llX r11=0x%llX\n",
                (unsigned long)r->ExceptionCode, (void *)r->ExceptionAddress, (unsigned long)GetCurrentThreadId(),
                (unsigned long long)rip, (unsigned long long)(rip - b), inImage ? "yes" : "no",
                (unsigned long long)c->Rax, (unsigned long long)c->Rbx, (unsigned long long)c->Rcx,
                (unsigned long long)c->Rdx, (unsigned long long)c->Rsi, (unsigned long long)c->Rdi,
                (unsigned long long)c->Rbp, (unsigned long long)c->Rsp, (unsigned long long)c->R8,
                (unsigned long long)c->R9, (unsigned long long)c->R10, (unsigned long long)c->R11);
    Emit(m);

#if defined(_MSC_VER) && !defined(__clang__)
    __try
    {
        const uint8_t *p = (const uint8_t *)rip;
        GT_SNPRINTF(
            m, sizeof(m),
            "[gtdump_hook] code@rip: %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X %02X",
            p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], p[8], p[9], p[10], p[11], p[12], p[13], p[14], p[15]);
        Emit(m);
    }
    __except (EXCEPTION_EXECUTE_HANDLER)
    {
        Emit("[gtdump_hook] code@rip: <unreadable>");
    }

    __try
    {
        uint64_t *sp = (uint64_t *)c->Rsp;
        GT_SNPRINTF(m, sizeof(m), "[gtdump_hook] stack returns (in-image):");
        for (int i = 0; i < 256; i++)
        {
            uintptr_t v = (uintptr_t)sp[i];
            if (v >= b && v < b + g_imageSize)
            {
                size_t cur = strlen(m);
                GT_SNPRINTF(m + cur, sizeof(m) - cur, " rva=0x%llX", (unsigned long long)(v - b));
            }
        }
        Emit(m);
    }
    __except (EXCEPTION_EXECUTE_HANDLER)
    {
        Emit("[gtdump_hook] stack scan aborted (bad rsp)");
    }
#else
    Emit("[gtdump_hook] code@rip/stack scan skipped (no SEH on this compiler)");
#endif

    Emit("[gtdump_hook] =========================================");
    FlushFileBuffers(g_logFile);
    return EXCEPTION_EXECUTE_HANDLER;
}

static DWORD WINAPI Worker(LPVOID unused)
{
    (void)unused;
    LoadConfig();
    {
        HMODULE self = NULL;
        GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                           (LPCWSTR)&Worker, &self);
        g_selfBase = (uint8_t *)self;
        g_selfSize = ImageSizeOf(g_selfBase);
    }
    AddVectoredExceptionHandler(0, FirstChanceLogger);
    SetUnhandledExceptionFilter(CrashFilter);

    g_base = (uint8_t *)GetModuleHandleA("Growtopia.exe");
    g_isTarget = (g_base != NULL);
    if (!g_base && g_allowAnyMod)
    {
        g_base = (uint8_t *)GetModuleHandleA(NULL);
        g_isTarget = 1;
    }
    if (!g_base)
        g_base = (uint8_t *)GetModuleHandleA(NULL);
    g_imageSize = ImageSizeOf(g_base);

    g_logFile = CreateFileA(g_logPath, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_ALWAYS,
                            FILE_ATTRIBUTE_NORMAL, NULL);
    InitializeCriticalSection(&g_logLock);
    g_logLockReady = 1;

    char b[512];
    GT_SNPRINTF(b, sizeof(b), "[gtdump_hook] loaded, pid %lu, waiting %lu ms before patching",
                (unsigned long)GetCurrentProcessId(), (unsigned long)g_delayMs);
    Emit(b);

    if (g_delayMs)
        Sleep(g_delayMs);

    InstallHooks();
    return 0;
}

BOOL APIENTRY DllMain(HMODULE hModule, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH)
    {
        g_hSelf = hModule;
        DisableThreadLibraryCalls(hModule);
        CreateThread(NULL, 0, Worker, NULL, 0, NULL);
    }
    else if (reason == DLL_PROCESS_DETACH)
    {
        Emit("[gtdump_hook] DLL_PROCESS_DETACH - GRACEFUL process teardown (exit path taken)");
    }
    return TRUE;
}
