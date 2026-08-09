// splash/launcher.cpp
// ---------------------------------------------------------------------------
// Dependency-free native splash launcher for the YouTube Downloader app.
//
// Why: the app's startup is dominated by the PySide6 (Qt) toolkit import, not
// by Python code. This C++ binary erects a tiny native X11 window in ~10-30ms
// by speaking the raw X wire protocol over the local socket (no gtk/Xlib
// dev headers needed), so the user gets instant feedback while the Python
// GUI finishes loading underneath.
//
// Flow:
//   launcher <python-exe> <script> [args...]
//   1. Connect to the X server and parse the connection setup.
//   2. Create a tiny window, spawn the python child with the ready-file path
//      exported as YDL_SPLASH_READY.
//   3. Animate a loading bar until the child writes that file (real window
//      shown), the child exits, or a timeout elapses.
//   4. Then wait on the child and exit with its exit code.
//
// Never required: if there is no display or the binary is missing, main.py
// simply runs Python directly.
//
// Build:  g++ -O2 -std=c++17 -o launcher launcher.cpp
// ---------------------------------------------------------------------------

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <unistd.h>
#include <errno.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <sys/select.h>
#include <thread>
static bool dbg = getenv("YDL_SPLASH_DEBUG") != nullptr;
#define D(fmt, ...) do { if (dbg) fprintf(stderr, "[splash-debug] " fmt "\n", ##__VA_ARGS__); } while (0)


// ---------------------------------------------------------------------------
// Endian helpers. Requests are always emitted little-endian with the 'l'
// marker (x86/ARM64 targets). The server's overflow byte order is read back.
// ---------------------------------------------------------------------------
static bool g_le = true;

static uint16_t rd16(const uint8_t* p) {
    return g_le ? (uint16_t)(p[0] | ((uint16_t)p[1] << 8))
                : (uint16_t)(((uint16_t)p[0] << 8) | (uint16_t)p[1]);
}
static uint32_t rd32(const uint8_t* p) {
    return g_le ? (uint32_t)(p[0] | ((uint32_t)p[1] << 8) |
                             ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24))
                : (uint32_t)(((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
                             ((uint32_t)p[2] << 8) | (uint32_t)p[3]);
}

struct Buf {
    std::vector<uint8_t> v;
    void u8(uint8_t x) { v.push_back(x); }
    void u16(uint16_t x) { v.push_back(x & 0xff); v.push_back((x >> 8) & 0xff); }
    void u32(uint32_t x) {
        v.push_back(x & 0xff); v.push_back((x >> 8) & 0xff);
        v.push_back((x >> 16) & 0xff); v.push_back((x >> 24) & 0xff);
    }
};

static int read_full(int fd, uint8_t* out, size_t n) {
    size_t got = 0;
    while (got < n) {
        ssize_t r = ::read(fd, out + got, n - got);
        if (r <= 0) return -1;
        got += (size_t)r;
    }
    return 0;
}
static int write_all(int fd, const uint8_t* data, size_t n) {
    size_t off = 0;
    while (off < n) {
        ssize_t w = ::write(fd, data + off, n - off);
        if (w <= 0) return -1;
        off += (size_t)w;
    }
    return 0;
}

// ---------------------------------------------------------------------------
// Read the MIT-MAGIC-COOKIE-1 entry for our display from XAUTHORITY.
// ---------------------------------------------------------------------------
static std::string read_cookie(int display) {
    const char* xauth = getenv("XAUTHORITY");
    std::string path;
    if (xauth && *xauth) path = xauth;
    else {
        const char* home = getenv("HOME");
        if (home) path = std::string(home) + "/.Xauthority";
    }
    if (path.empty()) return "";
    FILE* f = fopen(path.c_str(), "rb");
    if (!f) return "";
    std::vector<uint8_t> b;
    uint8_t chunk[4096];
    for (;;) {
        size_t r = fread(chunk, 1, sizeof(chunk), f);
        if (r == 0) break;
        b.insert(b.end(), chunk, chunk + r);
        if (b.size() > (1u << 20)) break;
    }
    fclose(f);
    if (b.size() < 6) return "";

    std::string want = (display == 0) ? std::string() : std::to_string(display);
    size_t off = 0;
    while (off + 6 <= b.size()) {
        uint16_t family = (uint16_t)b[off] | ((uint16_t)b[off + 1] << 8);
        uint16_t addr_len = (uint16_t)b[off + 2] | ((uint16_t)b[off + 3] << 8);
        off += 4;
        if (off + addr_len + 6 > b.size()) break;
        off += addr_len;
        uint16_t num_len = (uint16_t)b[off] | ((uint16_t)b[off + 1] << 8);
        uint16_t name_len = (uint16_t)b[off + 2] | ((uint16_t)b[off + 3] << 8);
        uint16_t data_len = (uint16_t)b[off + 4] | ((uint16_t)b[off + 5] << 8);
        off += 6;
        if (off + num_len + name_len + data_len > b.size()) break;
        std::string number((const char*)&b[off], num_len); off += num_len;
        std::string name((const char*)&b[off], name_len); off += name_len;
        std::string data((const char*)&b[off], data_len); off += data_len;

        bool ok = (family == 0 || family == 256) &&
                  (num_len == 0 || number == want) &&
                  name == "MIT-MAGIC-COOKIE-1" && !data.empty();
        if (ok) return data;
    }
    return "";
}

// ---------------------------------------------------------------------------
// X connection + connection-setup handshake
// ---------------------------------------------------------------------------
struct XSetup {
    int fd = -1;
    bool little = true;
    uint32_t rid_base = 0;
    uint32_t root = 0, white = 0, black = 0;
    uint16_t sw = 0, sh = 0;
    std::vector<uint8_t> body;
};

static bool connect_x(XSetup& s, int display, const std::string& path) {
    D("socket");
    int fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) { perror("[splash] socket"); return false; }
    struct sockaddr_un addr;
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    if (path.size() >= sizeof(addr.sun_path)) { close(fd); return false; }
    strcpy(addr.sun_path, path.c_str());
    D("connecting %s", addr.sun_path);
    if (::connect(fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        fprintf(stderr, "[splash] connect %s: %s\n", path.c_str(), strerror(errno));
        close(fd);
        return false;
    }
    s.fd = fd;

    // Perform the handshake.  First try without a cookie; if the server
    // refuses, reload the cookie from XAUTHORITY and retry.
    auto try_handshake = [&](const std::string& cookie) -> bool {
        Buf req;
        req.u8(0x6c);                 // little-endian byte-order marker
        req.u8(0);                    // unused
        req.u16(11);                  // protocol major version
        req.u16(0);                   // protocol minor version
        const char* nm = "MIT-MAGIC-COOKIE-1";
        req.u16(cookie.empty() ? 0 : 18);
        req.u16((uint16_t)cookie.size());
        if (!cookie.empty()) {
            for (int i = 0; i < 18; i++) req.u8((uint8_t)nm[i]);
            for (size_t i = 0; i < cookie.size(); i++) req.u8((uint8_t)cookie[i]);
        }
        D("hs bytes=%zu", req.v.size());
        if (write_all(fd, req.v.data(), req.v.size()) != 0) return false;
        // bounded read to avoid hanging on a server expecting a different size
        fd_set rf; FD_ZERO(&rf); FD_SET(fd, &rf);
        struct timeval tv = {4, 0};
        int sel = select(fd + 1, &rf, nullptr, nullptr, &tv);
        if (sel <= 0) { D("handshake no reply (sel=%d)", sel); return false; }
        uint8_t head[8];
        ssize_t got = 0;
        while ((size_t)got < 8) {
            ssize_t r = ::read(fd, head + got, 8 - (size_t)got);
            if (r <= 0) { D("handshake read r=%zd errno%d", r, errno); return false; }
            got += r;
        }
        D("reply byte0=%02x", head[0]);
        if (head[0] != 0x6c && head[0] != 0x42) return false;
        s.little = (head[0] == 0x6c);
        g_le = s.little;
        uint16_t len = rd16(head + 6);  // bytes of setup that follow in 4-byte units
        s.body.resize((size_t)len * 4);
        if (!s.body.empty() && read_full(fd, s.body.data(), s.body.size()) != 0)
            return false;
        if (s.body.size() < 7) return false;
        // Tail of the setup: CARD32 unused, CARD8 status, CARD16 reason_len.
        uint8_t status = s.body[s.body.size() - 4];
        return status == 1;
    };

    D("no-cookie handshake");
    if (try_handshake(std::string())) return true;
    D("cookie handshake");
    std::string cookie = read_cookie(display);
    return !cookie.empty() && try_handshake(cookie);
}

// Parse the fields we need out of the connection-setup body.
static bool parse_setup(XSetup& s) {
    const std::vector<uint8_t>& b = s.body;
    if (b.size() < 40) return false;
    s.rid_base = rd32(&b[4]);
    uint16_t vendor_len = rd16(&b[16]);
    uint8_t roots = b[20];
    if (roots < 1) return false;
    uint8_t nformats = b[21];
    size_t off = 32u + ((vendor_len + 3u) & ~3u);   // vendor, padded to 4
    off += (size_t)nformats * 8;                  // 8-byte pixmap formats
    if (off + 8 + 12 >= b.size()) return false;
    s.root = rd32(&b[off]);                       // screen: root window
    s.white = rd32(&b[off + 8]);
    s.black = rd32(&b[off + 12]);
    s.sw = rd16(&b[off + 16]);
    s.sh = rd16(&b[off + 18]);
    return true;
}

// ---------------------------------------------------------------------------
// X requests (opcodes: CreateWindow=1, MapWindow=8, CreateGC=55,
// PolyFillRectangle=68, DestroyWindow=4, FreeGC=60)
// ---------------------------------------------------------------------------
static void x_request(int fd, const Buf& r) { write_all(fd, r.v.data(), r.v.size()); }

static void x_create_window(int fd, uint32_t win, uint32_t parent,
                            int16_t x, int16_t y, uint16_t w, uint16_t h,
                            uint32_t bg, uint32_t border) {
    // bits: background pixel(2), border pixel(8),
    //       override redirect(512), event mask(2048)
    uint32_t mask = (1u << 1) | (1u << 3) | (1u << 9) | (1u << 11);
    uint32_t event_mask = (1u << 15);  // ExposureMask
    // 4 generic + win(4) + parent(4) + 8x2 fields + visual(4) + mask(4)
    // = 32 bytes fixed; + 4 value words -> 12 words total
    uint16_t len = (uint16_t)((32 + 4 * 4) / 4);
    Buf r;
    r.u8(1); r.u8(0);
    r.u16(len);
    r.u32(win); r.u32(parent);
    r.u16((uint16_t)x); r.u16((uint16_t)y);
    r.u16(w); r.u16(h);
    r.u16(0); r.u16(1);  // border width 0, class = InputOutput
    r.u32(0);            // visual = CopyFromParent
    r.u32(mask);
    // values in mask-bit order: background pixel, border pixel,
    // override redirect, event mask
    r.u32(bg); r.u32(border); r.u32(1); r.u32(event_mask);
    x_request(fd, r);
}

static void x_map_window(int fd, uint32_t win) {
    Buf r; r.u8(8); r.u8(0); r.u16(2); r.u32(win);
    x_request(fd, r);
}

static void x_create_gc(int fd, uint32_t gc, uint32_t drawable,
                        uint32_t fg, uint32_t bg) {
    uint32_t mask = (1u << 2) | (1u << 3);  // foreground, background
    uint16_t len = (uint16_t)((4 + 4 + 4 + 4 + 8) / 4);  // 6 words
    Buf r;
    r.u8(55); r.u8(0);
    r.u16(len);
    r.u32(gc); r.u32(drawable); r.u32(mask);
    r.u32(fg); r.u32(bg);
    x_request(fd, r);
}

static void x_poly_fill_rectangle(int fd, uint32_t drawable, uint32_t gc,
                                  int16_t x, int16_t y, uint16_t w, uint16_t h) {
    uint16_t len = (uint16_t)((4 + 8 + 8) / 4);  // fixed parts + one rect(8B)
    Buf r;
    r.u8(68); r.u8(0); r.u16(len);
    r.u32(drawable); r.u32(gc);
    r.u16((uint16_t)x); r.u16((uint16_t)y); r.u16(w); r.u16(h);
    x_request(fd, r);
}

static void x_destroy_window(int fd, uint32_t win) {
    Buf r; r.u8(4); r.u8(0); r.u16(2); r.u32(win);
    x_request(fd, r);
}

// ---------------------------------------------------------------------------
// main
// ---------------------------------------------------------------------------
int main(int argc, char** argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: %s <python-exe> <script> [args...]\n", argv[0]);
        return 2;
    }

    // --- Determine the X socket path ---------------------------------------
    const char* dispenv = getenv("DISPLAY");
    bool have_display = dispenv && *dispenv;
    int display = 0;
    std::string xpath;
    if (have_display) {
        std::string d(dispenv);
        // strip a hostname ("host:0" -> "0"), later ".", and the screen ".0"
        size_t colon = d.find(':');
        if (colon != std::string::npos) {
            std::string num = d.substr(colon + 1);
            size_t dot = num.find('.');
            if (dot != std::string::npos) num = num.substr(0, dot);
            if (!num.empty() && num.find_first_not_of("0123456789") == std::string::npos)
                display = atoi(num.c_str());
            else
                display = -1;
        }
        if (display >= 0) {
            xpath = "/tmp/.X11-unix/X" + std::to_string(display);
        }
    }

    // Ready-file the python child will touch once its window is shown.
    char ready_path[128];
    int parent_pid = (int)getpid();
    snprintf(ready_path, sizeof(ready_path), "/tmp/ydl_splash_%d.ready", parent_pid);

    // Spawn the child app.
    pid_t child = fork();
    if (child < 0) { fprintf(stderr, "[splash] fork: %s\n", strerror(errno)); return 1; }
    if (child == 0) {
        setenv("YDL_SPLASH_READY", ready_path, 1);
        const char* target[argc];
        for (int i = 1; i < argc; i++) target[i - 1] = argv[i];
        target[argc - 1] = nullptr;
        execv(argv[1], (char* const*)target);
        fprintf(stderr, "[splash] exec %s: %s\n", argv[1], strerror(errno));
        _exit(127);
    }

    XSetup s;
    bool show_splash = false;
    if (display >= 0) {
        if (connect_x(s, display, xpath)) {
            if (parse_setup(s)) show_splash = true;
            else close(s.fd);
        }
        D("show_splash=true rid=%x root=%x\n", s.rid_base, s.root);
        if (show_splash) {
            // -----------------------------------------------------------------
            // Small override-redirect (borderless) window, centered.
            // -----------------------------------------------------------------
            const int W = 480, H = 200;
            int wx, wy;
            if (s.sw >= W + 40 && s.sh >= H + 40) {
                wx = ((int)s.sw - W) / 2;
                wy = ((int)s.sh - H) / 2;
            } else { wx = 40; wy = 40; }
            uint32_t win = s.rid_base;          // some id in our range
            uint32_t gc = s.rid_base | 1;
            if ((gc & s.white) == s.rid_base) gc = s.rid_base | 2;  // avoid clash

            x_create_window(s.fd, win, s.root, (int16_t)wx, (int16_t)wy, W, H,
                            s.black, 0x3a3a3a);
            x_map_window(s.fd, win);
            uint32_t fg = s.white;
            uint32_t bg = s.black;
            x_create_gc(s.fd, gc, win, fg, bg);

            // ---- wait loop -------------------------------------------------
            auto start = std::chrono::steady_clock::now();
            bool done = false;
            bool ready = false;
            int bar_progress = 0;
            D("loop start");
            while (!done) {
                auto now = std::chrono::steady_clock::now();
                if (now - start > std::chrono::seconds(12)) break;
                // draw a growing loading bar
                int bx = 24, by = H - 40, bw = W - 48;
                int grow = bar_progress % (bw + 1);
                if (grow > 0)
                    x_poly_fill_rectangle(s.fd, win, gc, bx, by, (int16_t)grow, 14);
                bar_progress += (bw) / 20; // ~20 frames of growth. If grow runs past.
                // check ready file
                if (::access(ready_path, F_OK) == 0) { ready = true; done = true; }
                // check child
                int status = 0;
                pid_t r = waitpid(child, &status, WNOHANG);
                if (r == child) { done = true; }
                if (r < 0 && errno != EINTR) done = true;

                // service incoming X events (Expose etc.) non-blocking
                struct timeval tv { 0, 20 * 1000 };
                fd_set rf; FD_ZERO(&rf); FD_SET(s.fd, &rf);
                if (select(s.fd + 1, &rf, nullptr, nullptr, &tv) > 0) {
                    uint8_t ev[32];
                    ssize_t n = ::read(s.fd, ev, sizeof(ev));
                    (void)n;  // ignore content; repaint on next frame anyway
                } else {
                    std::this_thread::sleep_for(std::chrono::milliseconds(20));
                }
            }

            x_destroy_window(s.fd, win);
            close(s.fd);
            (void)ready;
        }
    }

    unlink(ready_path);
    // Wait for the app to finish; propagate its exit status.
    int status = 0;
    if (child > 0) {
        while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
    }
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return 0;
}