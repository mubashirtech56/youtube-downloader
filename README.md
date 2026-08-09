<div align="center">

# 🎬 YouTube Downloader Pro

**A fast, modern desktop application for Linux and Windows to download YouTube videos, playlists and audio — with a native C++ splash screen that makes startup instant.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![UI](https://img.shields.io/badge/UI-PySide6%20(Qt%206)-41CD52?logo=qt)](https://doc.qt.io/qtforpython-6/)
[![Engine](https://img.shields.io/badge/Engine-yt--dlp-red)](https://github.com/yt-dlp/yt-dlp)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-lightgrey)](#platform-support)
[![Version](https://img.shields.io/badge/Version-v3.0.0-blue)](#version)

![YouTube Downloader logo](youtube-dl.png)

</div>

---

## ✨ Features

- **⚡ Instant startup** — a native C++17 splash draws while the Qt UI boots.
- **🎥 Single-video downloads** — pick from every stream YouTube exposes, up to the video's native resolution (4K/2160p when available).
- **📃 Playlist support** — fetch playlists with thumbnails and batch-download the whole list.
- **⬇ Concurrent batch queue** — an event-driven scheduler runs multiple downloads in parallel (concurrency configurable in Settings).
- **🎧 Audio extraction** — download audio-only streams and extract to **MP3** at 64–320 kbps via ffmpeg.
- **🖼 Rich metadata** — title, thumbnail, channel, views, likes, duration and estimated file size before you download.
- **🕒 Download history** — every completed download is stored locally and is searchable/filterable.
- **🔑 Cookie support** — import a Netscape `cookies.txt` or use cookies from an installed browser for restricted videos.
- **🌗 Light & dark themes** — one-click toggle from the sidebar or Settings page.
- **⚙ Settings** — download folder, maximum simultaneous downloads, and the default MP3 audio bitrate.

## 🖥 Platform Support

| Platform | Status |
| :--- | :--- |
| Linux (Debian/Ubuntu) | ✅ `.deb` installer (built on Linux) |
| Windows | ✅ `.exe` installer (built on Windows) |
| macOS | ⚠ Not yet packaged |

---

## Requirements

- **Python 3.11+**
- **ffmpeg** (required by yt-dlp for merging video+audio and for MP3 extraction). Install it yourself:

```bash
# Debian / Ubuntu
sudo apt install ffmpeg

# Windows (chocolatey) — then add ffmpeg.exe to PATH
choco install ffmpeg
```

> The **JavaScript (Deno) runtime** that yt-dlp needs for YouTube ("n" signature challenge) is **bundled inside the shipped installers**, so users never install anything extra.

## 🚀 Installation

### Linux — from a `.deb`

Download the installer for the current release (`v2.0.0`):

- <https://github.com/mubashirtech56/youtube-downloader/releases/download/v2.0.0/youtube-downloader_1.0.0_amd64.deb>

```bash
sudo apt install ./youtube-downloader_1.0.0_amd64.deb
youtube-downloader
```

### Windows — from the `.exe`

Download the installer for the current release (`v2.0.0`):

- <https://github.com/mubashirtech56/youtube-downloader/releases/download/v2.0.0/youtube-downloader.exe>

Run `youtube-downloader.exe` — no installation step is required. (Add ffmpeg to your PATH if it isn't installed.)

### Run from source

```bash
git clone https://github.com/mubashirtech56/youtube-downloader.git
cd youtube-downloader

python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

python main.py
```

On GNU/Linux you can also use `make run` inside the repository.

---

## 🎮 Usage

1. **Paste a URL** (video or playlist) and press **Fetch**.
2. **Review the metadata** — title, thumbnail, channel, likes/views, duration.
3. **Pick a format** — a resolution for video or a bitrate for audio, then **Start Download** (or **Add to Batch**).
4. Watch it run on the **Downloading** page with live progress, speed and ETA.
5. Finished items land in **History** (searchable/filterable).

For age-restricted content, open **Account** → import a Netscape `cookies.txt` or select an installed browser, then re-fetch. If cookies are stale, the app automatically retries the fetch/download without them.

## ⚙ Configuration

Settings are stored in `~/.youtube_downloader/settings.json`:

| Key | Meaning | Default |
| :--- | :--- | :--- |
| `download_folder` | where completed files go | `~/Downloads/YouTube` |
| `max_concurrent_downloads` | parallel downloads | `3` |
| `default_audio_quality` | MP3 bitrate (kbps) | `192` |
| `theme` | `dark` or `light` | `dark` |
| `cookie_file` / `cookie_browser` | cookie source for restricted videos | none |

Logs and history are also written under `~/.youtube_downloader/`.

---

## 🏗 Architecture

Cleanly layered so the UI, business logic and download engine can evolve independently:

```
  PySide6 (Qt 6)        →  UI layer          (app/ui)
        ↓
  MainController         →  ViewModel         (app/controllers)
        ↓
  DownloadManager        →  queue / workers   (app/download)
        ↓
  yt-dlp / FFmpeg        →  engine            (app/services + core)
```

| Layer | Location | Responsibility |
| :--- | :--- | :--- |
| UI | `app/ui/` | Qt widgets, pages, theming. No threads, no network. |
| Controller | `app/controllers/main_controller.py` | Routes UI actions to services; reports back via Qt signals. |
| Download manager | `app/download/manager.py` | Queue, concurrency, retries, cancellation. |
| Services | `app/services/` | YouTube metadata extraction (`yt-dlp`), thumbnail caching, error mapping. |
| Core | `app/core/` | Settings, history, models, utilities. No Qt / yt-dlp dependency. |

```
youtube-downloader/
├── main.py                  # Qt entry point
├── requirements.txt         # Python dependencies
├── Makefile                 # Build / run / test targets
├── youtube-dl.png           # App logo / icon source
├── youtube-downloader.spec  # PyInstaller spec (Windows .exe)
├── index.html               # GitHub Pages landing page
├── app/                     # Layered application package
│   ├── core/                #   settings, history, models, utils
│   ├── services/            #   YouTubeService, thumbnails, errors
│   ├── download/            #   DownloadManager
│   ├── controllers/         #   MainController (ViewModel)
│   └── ui/                  #   main window, pages, theme
├── build/                   # Packaging scripts + generated icons
│   ├── build_deb.sh         #   .deb builder
│   ├── build_windows.bat    #   Windows .exe builder
│   ├── fetch_deno.py        #   Downloads the bundled Deno runtime
│   ├── make_icons.py        #   Icon generation
│   └── linux.spec           #   PyInstaller spec (Linux, onedir)
├── splash/                  # Native C++ splash launcher sources
│   ├── launcher.cpp         #   Linux
│   └── launcher_win.cpp     #   Windows
└── tests/
    └── test_services.py     # Unit tests (no network required)
```

---

## 🛠 Building from source

PyInstaller cannot cross-compile, so each artifact must be built on its own OS.

### Linux — `.deb`

```bash
make deb                 # or: ./build/build_deb.sh
```

This fetches the Deno runtime into `deno/` (if absent), builds the app with the Linux spec, and packages `dist/youtube-downloader_<version>_amd64.deb` (default version `3.0.0`, override with `VERSION=... ./build/build_deb.sh`).

### Windows — `.exe`

```bat
build\build_windows.bat
```

This installs dependencies, generates icons, fetches Deno, and produces `dist\youtube-downloader.exe` (one-file, windowed).

Both build scripts auto-download **Deno** (`build/fetch_deno.py`) so the shipped binary can solve YouTube's JavaScript challenge without any user setup.

## 🧪 Testing

```
make test
# or
python -m unittest discover -s tests -v
```

The suite covers URL validation, filename sanitization, size/duration formatting, format deduping, caching, queue dedupe, progress throttling and history — with mocks, no network needed.

---

## 📄 Version

- **Codebase version:** `v3.0.0`
- **Current published release (installers):** `v2.0.0` — the `.deb` is attached as `youtube-downloader_1.0.0_amd64.deb` and the Windows binary as `youtube-downloader.exe`.

## 🔗 Releases

Compiled binaries (`.deb`, `.exe`) are **never committed to this repository**. They are built locally (output in `dist/`, which is git-ignored) and uploaded to [GitHub Releases](https://github.com/mubashirtech56/youtube-downloader/releases) for the download links above to serve. Keep the uploaded asset **filenames** identical to the release links (`youtube-downloader.exe`, `youtube-downloader_1.0.0_amd64.deb`) so the URLs above keep working.

## 🤝 Contributing

Found a bug or want a feature? Open an issue first, then submit a pull request. Keep changes focused, add/adjust unit tests in `tests/`, and run `make test` (or the equivalent on Windows) before submitting.

## 📝 License

Distributed under the **MIT License** (see the LICENSE file in the repository).

<!-- MIT is the license stated by this project; ensure a LICENSE file lands in the repo before first public release -->

## ⚠️ Disclaimer

This project is an **independent client for YouTube** built on top of `yt-dlp`/ffmpeg. It is not affiliated with, endorsed by, or sponsored by YouTube or Google. Downloading videos may violate YouTube's Terms of Service. You are solely responsible for how you use this software and for respecting applicable copyright laws in your jurisdiction. Download only content you have permission to download.

---

<div align="center">
  Made with ❤️ by <a href="https://github.com/mubashirtech56">mubashirtech56</a>
</div>