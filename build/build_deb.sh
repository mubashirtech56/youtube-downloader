#!/usr/bin/env bash
# ============================================================================
# Build a Debian/Ubuntu .deb for the YouTube Downloader desktop app.
#
#   ./build/build_deb.sh
#
# Produces:  dist/youtube-downloader_<version>_amd64.deb
#
# The package bundles a PyInstaller build of main.py plus the native C++
# splash launcher (splash/launcher) so startup shows instantly while the
# PySide6 (Qt) GUI boots underneath.
# ============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APP_NAME="youtube-downloader"
APP_ID="youtube.downloader"
VERSION="${VERSION:-2.0.0}"
ARCH="${ARCH:-amd64}"
PYTHON="${PYTHON:-$ROOT/venv/bin/python}"

if [ ! -x "$PYTHON" ]; then
    PYTHON="${PYTHON:-python3}"
fi

echo "[deb] using python: $PYTHON"
echo "[deb] version:      $VERSION"
echo "[deb] architecture: $ARCH"

# --- 1. Generate icons ------------------------------------------------------
"$PYTHON" build/make_icons.py
mkdir -p dist

# --- 2. Build the native C++ splash launcher --------------------------------
echo "[deb] building native splash launcher (C++)"
g++ -O3 -std=c++17 -s -o dist/launcher splash/launcher.cpp

# --- 3. Bundle the app with PyInstaller --------------------------------------
echo "[deb] ensuring pyinstaller..."
"$PYTHON" -m pip install --quiet --upgrade pyinstaller

echo "[deb] building app bundle (this can take a minute)..."
"$PYTHON" -m PyInstaller \
    --noconfirm \
    --clean \
    --name "$APP_NAME" \
    --onedir \
    --windowed \
    --icon "build/icons/youtube-downloader.ico" \
    --add-data "youtube-dl.png:." \
    --add-data "build/icons:icons" \
    --hidden-import "secretstorage" \
    --hidden-import "jeepney" \
    --hidden-import "cffi" \
    main.py

# --- 4. Assemble the package tree -------------------------------------------
PKG_ROOT="$ROOT/build/deb-root"
rm -rf "$PKG_ROOT"
mkdir -p "$PKG_ROOT/DEBIAN"
mkdir -p "$PKG_ROOT/usr/bin"
mkdir -p "$PKG_ROOT/usr/lib/$APP_NAME"
mkdir -p "$PKG_ROOT/usr/share/applications"
mkdir -p "$PKG_ROOT/usr/share/icons/hicolor/512x512/apps"

# DEBIAN/control
cat > "$PKG_ROOT/DEBIAN/control" <<EOF
Package: $APP_NAME
Version: $VERSION
Section: video
Priority: optional
Architecture: $ARCH
Maintainer: YouTube Downloader <support@example.com>
Installed-Size: $(du -sk dist/$APP_NAME | awk '{print $1}')
Depends: ffmpeg, libgl1, libxcb-cursor0, libxkbcommon-x11-0
Description: YouTube Downloader Pro
 A fast Qt-based desktop YouTube downloader with playlist support, batch
 downloads, audio extraction and a native C++ splash launcher.
EOF

cat > "$PKG_ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
chmod +x /usr/lib/youtube-downloader/launcher
chmod +x /usr/lib/youtube-downloader/app/youtube-downloader
update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
gtk-update-icon-cache /usr/share/icons/hicolor >/dev/null 2>&1 || true
update-mime-database /usr/share/mime >/dev/null 2>&1 || true
exit 0
EOF
chmod +x "$PKG_ROOT/DEBIAN/postinst"

# App bundle + launcher under /usr/lib
mkdir -p "$PKG_ROOT/usr/lib/$APP_NAME/app"
cp -a "dist/$APP_NAME/." "$PKG_ROOT/usr/lib/$APP_NAME/app/"
cp dist/launcher "$PKG_ROOT/usr/lib/$APP_NAME/launcher"
chmod +x "$PKG_ROOT/usr/lib/$APP_NAME/launcher"

# Launcher that hands control to the C++ splash + bundled binary.
cat > "$PKG_ROOT/usr/bin/$APP_NAME" <<EOF
#!/bin/sh
# C++ splash spawns the bundled app; YDL_SPLASH_READY tells it when the real
# window is up. Falls back to running the app directly if the launcher breaks.
if [ -x /usr/lib/$APP_NAME/launcher ]; then
    exec /usr/lib/$APP_NAME/launcher /usr/lib/$APP_NAME/app/$APP_NAME run
fi
exec /usr/lib/$APP_NAME/app/$APP_NAME
EOF
chmod +x "$PKG_ROOT/usr/bin/$APP_NAME"

# Desktop entry
cat > "$PKG_ROOT/usr/share/applications/$APP_NAME.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=YouTube Downloader
GenericName=Video Downloader
Comment=Download videos from YouTube
Exec=$APP_NAME
Icon=youtube-downloader
Terminal=false
Categories=AudioVideo;Video;Network;
StartupNotify=true
Keywords=youtube;video;download;
EOF

# High-resolution icon (hicolor theme picks this up)
cp build/icons/youtube-downloader-512.png \
   "$PKG_ROOT/usr/share/icons/hicolor/512x512/apps/youtube-downloader.png"

# --- 5. Build the .deb -------------------------------------------------------
echo "[deb] building package..."
mkdir -p dist
dpkg-deb --build --root-owner-group "$PKG_ROOT" "dist/${APP_NAME}_${VERSION}_${ARCH}.deb"

echo
echo "[deb] DONE -> dist/${APP_NAME}_${VERSION}_${ARCH}.deb"
echo "[deb] install with:  sudo apt install ./dist/${APP_NAME}_${VERSION}_${ARCH}.deb"