#!/usr/bin/env python
"""Download the Deno JavaScript runtime needed by yt-dlp.

YouTube now requires yt-dlp to solve an "n" signature challenge in
JavaScript. Without a JS runtime (Deno/Node/Bun) yt-dlp cannot compute the
fileName signatures, so every fetch returns only storyboard stubs and the app
reports "DRM protected / no streams". The finished app bundles this runtime so
users never have to install anything.

Downloads into a `deno/` folder next to this script's project root:
    deno/deno.exe   (Windows)   -> spec datas ("deno", "deno")
    deno/deno       (Linux/macOS)
"""
import os
import platform
import sys
import zipfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEST_DIR = os.path.join(ROOT, "deno")

SYSTEM = sys.platform

if SYSTEM == "win32":
    ARCHIVE = "deno-x86_64-pc-windows-msvc.zip"
    DEST = os.path.join(DEST_DIR, "deno.exe")
elif SYSTEM in ("linux", "linux2"):
    arch = platform.machine()
    triples = {
        "x86_64": "deno-x86_64-unknown-linux-gnu.zip",
        "aarch64": "deno-aarch64-unknown-linux-gnu.zip",
    }
    if arch not in triples:
        sys.exit(f"Unsupported Linux architecture: {arch}")
    ARCHIVE = triples[arch]
    DEST = os.path.join(DEST_DIR, "deno")
elif SYSTEM == "darwin":
    ARCHIVE = "deno-x86_64-apple-darwin.zip"
    DEST = os.path.join(DEST_DIR, "deno")
else:
    sys.exit(f"Unsupported platform: {SYSTEM}")

URL = f"https://github.com/denoland/deno/releases/latest/download/{ARCHIVE}"


def main() -> None:
    if os.path.isfile(DEST):
        print(f"[deno] already present: {DEST}")
        return
    os.makedirs(DEST_DIR, exist_ok=True)
    tmp = os.path.join(DEST_DIR, ARCHIVE)
    print(f"[deno] downloading {URL}")
    urllib.request.urlretrieve(URL, tmp)
    size_mb = os.path.getsize(tmp) / (1024 * 1024)
    print(f"[deno] downloaded {size_mb:.1f} MB")
    with zipfile.ZipFile(tmp) as zf:
        zf.extractall(DEST_DIR)
    os.remove(tmp)
    if not os.path.isfile(DEST):
        sys.exit(f"[deno] FAILED: expected binary {DEST} not found")
    os.chmod(DEST, 0o755)
    print(f"[deno] ready: {DEST}")


if __name__ == "__main__":
    main()