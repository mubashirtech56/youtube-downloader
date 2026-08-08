// splash/launcher_win.cpp
// ---------------------------------------------------------------------------
// Dependency-free native splash launcher for Windows.
//
// While the Python/CustomTkinter app boots (which is dominated by the toolkit,
// not by app code), this small binary shows a borderless Win32 window with a
// growing progress bar so the user gets instant feedback.
//
// Flow:
//   launcher.exe <python.exe> <main.py> [args...]
//   1. Spawn the python child with the ready-file path in YDL_SPLASH_READY.
//   2. Animate a loading bar until the child writes that file (real window
//      shown), the child exits, or a timeout elapses.
//   3. Then wait on the child and exit with its exit code.
//
// Never required: if the binary is missing, main.py simply runs Python
// directly.
//
// Build (pick your toolchain):
//   g++ -O3 -std=c++17 -static -municode -mwindows -o launcher.exe launcher_win.cpp -lgdi32
//   cl /O2 /EHsc launcher_win.cpp /Fe:launcher.exe user32.lib gdi32.lib shell32.lib
// ---------------------------------------------------------------------------

#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0600
#endif

#include <windows.h>
#include <wchar.h>
#include <stdio.h>
#include <stdlib.h>
#include <string>
#include <vector>

static HWND g_hwnd = NULL;
static int  g_prog = 0;
static const int WIN_W = 480;
static const int WIN_H = 180;

// ---------------------------------------------------------------------------
// Window procedure
// ---------------------------------------------------------------------------
static void Paint(HWND hwnd) {
    PAINTSTRUCT ps;
    HDC hdc = ::BeginPaint(hwnd, &ps);
    RECT rc; ::GetClientRect(hwnd, &rc);
    int w = rc.right - rc.left;
    int h = rc.bottom - rc.top;

    HBRUSH bg = ::CreateSolidBrush(RGB(28, 28, 28));
    ::FillRect(hdc, &rc, bg);
    ::DeleteObject(bg);

    HBRUSH edge = ::CreateSolidBrush(RGB(80, 80, 80));
    ::FrameRect(hdc, &rc, edge);
    ::DeleteObject(edge);

    ::SetBkMode(hdc, TRANSPARENT);

    HFONT title = ::CreateFontW(32, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
                                DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
                                CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                                DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
    HFONT old = (HFONT)::SelectObject(hdc, title);
    ::SetTextColor(hdc, RGB(240, 240, 240));
    RECT tr = {0, 30, w, 72};
    ::DrawTextW(hdc, L"YouTube Downloader", -1, &tr,
                DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    ::SelectObject(hdc, old);
    ::DeleteObject(title);

    HFONT sub = ::CreateFontW(16, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                              DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
                              CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                              DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
    old = (HFONT)::SelectObject(hdc, sub);
    ::SetTextColor(hdc, RGB(160, 160, 160));
    RECT sr = {0, 78, w, 102};
    ::DrawTextW(hdc, L"Starting...", -1, &sr, DT_CENTER | DT_SINGLELINE);
    ::SelectObject(hdc, old);
    ::DeleteObject(sub);

    int bx = 24, by = 116, bw = w - 48, bh = 14;
    HBRUSH track = ::CreateSolidBrush(RGB(55, 55, 55));
    RECT track_rc = {bx, by, bx + bw, by + bh};
    ::FillRect(hdc, &track_rc, track);
    ::DeleteObject(track);

    int grow = (int)((__int64)g_prog * bw / 1000);
    if (grow > 0) {
        HBRUSH fill = ::CreateSolidBrush(RGB(0, 122, 255));
        RECT fill_rc = {bx, by, bx + grow, by + bh};
        ::FillRect(hdc, &fill_rc, fill);
        ::DeleteObject(fill);
    }

    ::EndPaint(hwnd, &ps);
}

static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
        case WM_PAINT:
            Paint(hwnd);
            return 0;
        case WM_ERASEBKGND:
            return 1;
        case WM_TIMER:
            if (g_prog < 1000) g_prog += 8;
            ::InvalidateRect(hwnd, nullptr, TRUE);
            return 0;
        case WM_CLOSE:
            ::DestroyWindow(hwnd);
            return 0;
        case WM_DESTROY:
            ::PostQuitMessage(0);
            return 0;
    }
    return ::DefWindowProcW(hwnd, msg, wp, lp);
}

static void CenterWindow(HWND hwnd) {
    RECT rc;
    ::GetWindowRect(hwnd, &rc);
    int sw = ::GetSystemMetrics(SM_CXSCREEN);
    int sh = ::GetSystemMetrics(SM_CYSCREEN);
    int x = (sw - (rc.right - rc.left)) / 2;
    int y = (sh - (rc.bottom - rc.top)) / 2;
    if (x < 0) x = 0;
    if (y < 0) y = 0;
    ::SetWindowPos(hwnd, nullptr, x, y, 0, 0, SWP_NOSIZE | SWP_NOZORDER);
}

// ---------------------------------------------------------------------------
// Main logic. `argv` is the UTF-16 command line (argc+1 including the exe).
// ---------------------------------------------------------------------------
static int RunLauncher(HINSTANCE hInstance, int argc, LPWSTR* argv) {
    if (argc < 3) {
        ::MessageBoxW(nullptr, L"launcher.exe <python.exe> <main.py> [args...]",
                      L"YouTube Downloader", MB_OK | MB_ICONINFORMATION);
        return 2;
    }

    std::wstring python = argv[1];
    std::wstring script = argv[2];
    std::wstring cmdline = L"\"" + python + L"\" \"" + script + L"\"";
    for (int i = 3; i < argc; i++) {
        cmdline += L" \"" + std::wstring(argv[i]) + L"\"";
    }
    // CreateProcessW may modify the command-line buffer in place; give it a
    // writable copy we own.
    std::vector<wchar_t> cmd_buf(cmdline.begin(), cmdline.end());
    cmd_buf.push_back(L'\0');

    // Ready-file the python child will touch once its window is shown.
    wchar_t tmpdir[MAX_PATH] = {0};
    ::GetTempPathW(MAX_PATH, tmpdir);
    wchar_t ready[MAX_PATH];
    ::swprintf_s(ready, L"%sydl_splash_%lu.ready", tmpdir, ::GetCurrentProcessId());

    // ---- Splash window ---------------------------------------------------
    WNDCLASSEXW wc = {0};
    wc.cbSize        = sizeof(wc);
    wc.style         = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc   = WndProc;
    wc.hInstance     = hInstance;
    wc.hCursor       = ::LoadCursor(nullptr, IDC_ARROW);
    wc.hbrBackground = nullptr;
    wc.lpszClassName = L"YdlSplashWin";
    ::RegisterClassExW(&wc);

    DWORD ex = WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE;
    g_hwnd = ::CreateWindowExW(ex, L"YdlSplashWin", L"YouTube Downloader",
                               WS_POPUP, CW_USEDEFAULT, CW_USEDEFAULT, WIN_W, WIN_H,
                               nullptr, nullptr, hInstance, nullptr);
    if (g_hwnd) {
        CenterWindow(g_hwnd);
        ::ShowWindow(g_hwnd, SW_SHOWNOACTIVATE);
        ::SetTimer(g_hwnd, 1, 30, nullptr);
    }

    // ---- Spawn the child app ---------------------------------------------
    ::SetEnvironmentVariableW(L"YDL_SPLASH_READY", ready_path);

    PROCESS_INFORMATION pi = {0};
    STARTUPINFOW si = {0};
    si.cb = sizeof(si);
    BOOL spawned = ::CreateProcessW(python.c_str(),
                                    cmd_buf.data(),
                                    nullptr, nullptr, FALSE,
                                    CREATE_UNICODE_ENVIRONMENT,
                                    nullptr, nullptr, &si, &pi);

    // ---- Wait loop -------------------------------------------------------
    ULONGLONG start = ::GetTickCount64();
    for (;;) {
        if (g_hwnd && ::GetFileAttributesW(ready_path) != INVALID_FILE_ATTRIBUTES)
            break;  // app window shown -> splash goes away

        if (spawned) {
            DWORD code = 0;
            if (::WaitForSingleObject(pi.hProcess, 0) == WAIT_OBJECT_0) {
                ::GetExitCodeProcess(pi.hProcess, &code);
                if (code != STILL_ACTIVE) {
                    ::KillTimer(g_hwnd, 1);
                    break;  // child died -> hand over
                }
            }
        }
        if (::GetTickCount64() - start > 12000) break;  // hard timeout

        MSG msg;
        while (::PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
            ::TranslateMessage(&msg);
            ::DispatchMessageW(&msg);
        }
        ::Sleep(10);
    }

    if (g_hwnd) { ::KillTimer(g_hwnd, 1); ::DestroyWindow(g_hwnd); g_hwnd = nullptr; }
    ::DeleteFileW(ready_path);

    // ---- Wait for the app to finish and propagate its exit status ------
    DWORD exitcode = 0;
    if (spawned) {
        ::WaitForSingleObject(pi.hProcess, INFINITE);
        ::GetExitCodeProcess(pi.hProcess, &exitcode);
        ::CloseHandle(pi.hProcess);
        ::CloseHandle(pi.hThread);
    }
    return (int)exitcode;
}

// ---------------------------------------------------------------------------
// Entry point.
// ---------------------------------------------------------------------------
#if defined(_MSC_VER)
// MSVC wide GUI entry point: wWinMain is the CRT entry for Unicode apps.
int APIENTRY wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, PWSTR pCmdLine, int nCmdShow)
#else
// MinGW: with -municode the CRT calls wmain(argc, argv, envp); we re-split the
// command line below so both toolchains run identical logic.
int wmain(int, wchar_t**)
#endif
{
    int argc = 0;
    int rc = 2;
    LPWSTR* argvw = ::CommandLineToArgvW(::GetCommandLineW(), &argc);
    if (argvw) {
        rc = RunLauncher(::GetModuleHandleW(nullptr), argc, argvw);
        ::LocalFree(argvw);
    }
    return rc;
}