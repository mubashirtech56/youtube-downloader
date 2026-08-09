# ============================================================================
# YouTube Downloader - build targets
#
#   make run               run the app with the local venv
#   make test              run the unit tests
#   make icons             regenerate icons from youtube-dl.png
#   make deb               build dist/youtube-downloader_*.deb (Linux)
#                             - PyInstaller onedir bundle + optional C++ splash
#   make launcher          rebuild native C++ splash (Linux)
#   make windows           build dist\youtube-downloader.exe (Windows)
#   make clean             remove build artifacts
#
# PyInstaller cannot cross-compile: build the .deb on Linux and the .exe on
# Windows. Both outputs share the same source + build/ specs:
#   - Windows: build\build_windows.bat  (one-file youtube-downloader.exe)
#   - Linux:   make deb                (onedir bundle -> .deb package)
#
# Architecture: PySide6 UI  ->  MainController (ViewModel)  ->  DownloadManager
#                              ->  yt-dlp / FFmpeg
# ============================================================================

PYTHON := venv/bin/python

.PHONY: run test icons launcher deb windows clean all

all: test deb

run:
	$(PYTHON) main.py

test:
	$(PYTHON) -m unittest discover -s tests -v

icons:
	$(PYTHON) build/make_icons.py

launcher:
	g++ -O3 -std=c++17 -s -o splash/launcher splash/launcher.cpp

deb: icons
	./build/build_deb.sh

windows: icons
	@echo "Building the Windows .exe requires a Windows machine."
	@echo "Run:  build\build_windows.bat"
	@echo "Output:  dist\youtube-downloader.exe"

clean:
	rm -rf build/deb-root build/youtube-downloader build/icons build/pyi-linux \
	       build/pyi-build dist/youtube-downloader dist/launcher __pycache__ tests/__pycache__
	rm -f dist/youtube-downloader.exe dist/*.deb