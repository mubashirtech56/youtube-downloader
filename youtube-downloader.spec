# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification for YouTube Downloader Pro (Windows .exe).

The service layer loads yt_dlp / requests / PIL.Image lazily through
__import__() (see app/services/imports.py), which static analysis cannot
follow, so they are declared in `hiddenimports`. PySide6 is discovered from
main.py and handled by PyInstaller's Qt hooks.
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
    a.binaries,
    a.datas,
    [],
    name="youtube-downloader",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="build/icons/youtube-downloader.ico",
)