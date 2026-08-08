<div align="center">

# 🎬 YouTube Downloader Pro

**A fast, modern desktop application to download YouTube videos, playlists and audio — with a native C++ splash that makes startup instant.**

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![UI](https://img.shields.io/badge/UI-CustomTkinter-3B7EBF)](https://github.com/TomSchimansky/CustomTkinter)
[![Downloader](https://img.shields.io/badge/Engine-yt--dlp-red)](https://github.com/yt-dlp/yt-dlp)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20Windows-lightgrey)](#platform-support)
[![License](https://img.shields.io/badge/License-MIT-blue)](https://opensource.org/licenses/MIT)

![YouTube Downloader screenshot](youtube-dl.png)

</div>

---

## ✨ Features

- **⚡ Instant startup** — a native C++17 splash screen (SDL-Free, pure X11/Win32) draws while the UI boots, so the window appears immediately.
- **🎥 Single video downloads** — pick from every available resolution, from `144p` up to `4K/2160p`.
- **📃 Playlist support** — fetch entire playlists with thumbnails, and batch-download them all at once.
- **⬇ Concurrent batch queue** — an event-driven scheduler runs up to *N* simultaneous downloads (configurable) with live progress bars.
- **🎧 Audio extraction** — rip audio as `MP3`, `M4A`, `OPUS`, `FLAC` and more, at bitrates from `64–320 kbps`.
- **🎨 Format selection** — choose your output container (`MP4`, `MKV`, `WebM`, `AVI`, `MOV`), or let the app pick the best available stream.
- **🖼 Rich video metadata** — thumbnail, channel, duration, upload date, views, likes, description and estimated file size.
- **🕒 Download history** — every download is persisted locally and searchable/filterable.
- **🔑 Cookie support** — load a Netscape `cookies.txt` or your browser cookies to download age-restricted or private videos.
- **🌗 Light & Dark themes** — sleek Modern-Dark aesthetic with an easy one-click theme toggle.
- **⚙ Customizable defaults** — default quality, audio bitrate, container, output folder and download concurrency live in a settings page.

## 🖥 Platform Support

| Platform | Status |
| :--- | :--- |
| **Linux (Debian/Ubuntu)** | ✅ `.deb` installer (`make deb`) + `ffmpeg` |
| **Windows** | ✅ `.exe` (Windows toolchain, `build\build_windows.bat`) |
| macOS | ⚠ Not yet packaged |

---

## 🚀 Getting Started

### Prerequisites

- **Python 3.11+** (developed on 3.13)
- **ffmpeg** (required for merging video+audio and media conversion)

```bash
# Debian / Ubuntu
sudo apt install ffmpeg

# macOS
brew install ffmpeg

# Windows
choco install ffmpeg   # then add ffmpeg.exe to your PATH
```

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/mubashirtech56/youtube-downloader.git
cd youtube-downloader

# 2. Create a virtual environment and install dependencies
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Run the app
python main.py
```

> 💡 On GNU/Linux you can also use `make run` and `make test`.

---

## 🛠 Building & Packaging

The repo ships a `Makefile` that drives every build target:

| Command | What it does |
| :--- | :--- |
| `make run` | Launch the app from the local venv |
| `make test` | Run the unit test suite |
| `make icons` | Regenerate icon set from `youtube-dl.png` |
| `make launcher` | Rebuild the native C++ splash launcher (Linux) |
| `make deb` | Build `dist/youtube-downloader_1.0.0_amd64.deb` |
| `make windows` | Instructions for building the Windows `.exe` (Win machine) |
| `make clean` | Remove all build artifacts |

```bash
# Build & install the Debian package
make deb
sudo apt install ./dist/youtube-downloader_*.deb
youtube-downloader
```

Windows executables are produced with **PyInstaller** from a Windows machine:

```bat
build\build_windows.bat
```

The generated bundle glues together a PyInstaller `onedir` build of `main.py`, the bundled icon set, and the native launcher (C++17, `splash/launcher.cpp`) using an env-variable handshake (`YDL_SPLASH_READY`) so the splash hides the moment the real window is mapped.

---

## 🎮 How to Use

1. **Paste a URL** — single video `https://youtu.be/...` or a playlist link — and hit **Fetch**.
2. **Review the metadata** — title, thumbnail, channel, likes/views, duration.
3. **Pick a format** — a resolution for video or a bitrate for audio; the container dropdown sets the output type.
4. **Download** — the item enters the queue, runs in parallel, and gets written to your chosen output folder.
5. **Track progress** — the *Downloading* page shows real-time progress; finished items land in *History*.

Want age-restricted videos? Go to **Account** → import a `cookies.txt` in Netscape format (or select cookies from your browser) and re-fetch.

---

## 🧪 Testing

```
make test
# or
python -m unittest discover -s tests -v
```

The suite covers the core services with mocks — URL validation, filename sanitization, size/duration formatting, format deduplication, caching, queue deduplication, and progress throttling — with no network required.

---

## 📁 Project Layout

```
youtube-downloader/
├── main.py                  # Application entry point & GUI
├── requirements.txt         # Python dependencies
├── Makefile                 # Build/run/test targets
├── youtube-dl.png           # App logo
├── build/                   # Packaging & assets
│   ├── build_deb.sh         #   .deb builder
│   ├── build_windows.bat    #   Windows .exe builder
│   ├── make_icons.py        #   Icon generation
│   └── youtube-downloader.spec  #   PyInstaller spec
├── splash/                  # Native C++ splash launcher
│   ├── launcher.cpp         #   Linux implementation
│   └── launcher_win.cpp     #   Windows implementation
└── tests/
    └── test_services.py     # Unit tests
```

---

## 🧰 Tech Stack

| Layer | Technology |
| :--- | :--- |
| **GUI** | [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) 6.0.0 |
| **Download engine** | [yt-dlp](https://github.com/yt-dlp/yt-dlp) 2026.7.4 |
| **Media tagging** | mutagen |
| **Network / images** | requests • Pillow |
| **Startup splash** | C++17 (`g++`), X11 / Win32 GDI |
| **Packaging** | PyInstaller + `dpkg-deb` |

### Dependencies

```
customtkinter==6.0.0
yt-dlp==2026.7.4
yt-dlp-ejs==0.8.0
secretstorage==3.5.0
Pillow==10.3.0
requests==2.31.0
mutagen==1.47.0
```

---

## 📝 License

Distributed under the **MIT License**. See `LICENSE` for details.

---

<div align="center">
  Made with ❤️ by <a href="https://github.com/mubashirtech56">mubashirtech56</a>
</div>