#!/usr/bin/env python3
"""Generate application icons (PNG sizes + Windows .ico) from youtube-dl.png.

Run:  python3 build/make_icons.py
Outputs to: build/icons/
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "youtube-dl.png"
OUT = ROOT / "build" / "icons"

PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def main() -> int:
    try:
        import PIL.Image
    except ImportError:
        print("Pillow is required: pip install Pillow", file=sys.stderr)
        return 1

    if not SRC.is_file():
        print(f"icon source not found: {SRC}", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    img = PIL.Image.open(SRC).convert("RGBA")

    # Square-crop to the shortest edge so all icons come out proportional.
    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2,
                    (w - side) // 2 + side, (h - side) // 2 + side))

    for size in PNG_SIZES:
        resized = img.resize((size, size), PIL.Image.Resampling.LANCZOS)
        out = OUT / f"youtube-downloader-{size}.png"
        resized.save(out, "PNG")
        print(f"wrote {out}")

    img = img.resize((256, 256), PIL.Image.Resampling.LANCZOS)
    ico = OUT / "youtube-downloader.ico"
    img.save(ico, "ICO", sizes=[(s, s) for s in sorted(set(ICO_SIZES))])
    print(f"wrote {ico}")

    # Copy the canonical large PNG used by .deb hicolor icon theme.
    large = OUT / "youtube-downloader-512.png"
    if large.is_file():
        img.resize((512, 512), PIL.Image.Resampling.LANCZOS).save(
            large, "PNG")
    print("icons ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())