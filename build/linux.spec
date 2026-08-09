# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir build specification for Linux (.deb packaging).

Run on a Linux machine:  python -m PyInstaller --noconfirm build/linux.spec
Produces: dist/youtube-downloader/  (onedir app, consumed by build_deb.sh)
"""

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("youtube-dl.png", "."),
        ("build/icons", "icons"),
        ("deno", "deno"),
    ],
    hiddenimports=[
        "yt_dlp",
        "requests",
        "PIL.Image",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="youtube-downloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="build/icons/youtube-downloader-256.png",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="youtube-downloader",
)