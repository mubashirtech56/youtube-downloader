# ============================================================================
# YouTube Downloader - build targets
#
#   make run               run the app with the local venv
#   make test              run the unit tests
#   make icons             regenerate icons from youtube-dl.png
#   make deb               build dist/youtube-downloader_*.deb (Linux)
#                             - PyInstaller bundle + native C++ splash
#   make launcher          rebuild native C++ splash (Linux)
#   make clean             remove build artifacts
#
# Windows .exe must be built on Windows: run build\build_windows.bat
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

deb: icons launcher
	./build/build_deb.sh

windows:
	@echo "Run build\build_windows.bat on a Windows machine (PyInstaller cannot cross-compile)."

clean:
	rm -rf build/deb-root build/youtube-downloader build/icons build/pyi-* \
	       dist/youtube-downloader dist/launcher __pycache__ tests/__pycache__
	rm -f *.spec

all: test deb