"""Regenerate every BetterVoice mark asset from bettervoice/brand.py.

    python scripts/generate_brand_assets.py

Writes:
    assets/bettervoice-mark.svg          vector master (docs, web)
    assets/bettervoice-mark.png          512 px (README, social)
    src/bettervoice/assets/icon.ico      Windows: app, window, tray and exe icon
    src/bettervoice/assets/icon.png      macOS and Linux: window icon, 256 px

Each ICO size is rendered on its own (small ones pixel-snapped) instead of
being scaled down from one large image, so 16-40 px icons stay crisp.
"""

import io
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from bettervoice import brand  # noqa: E402


def encode_ico(images):
    """A PNG-compressed .ico with one entry per image (Windows Vista+)."""
    pngs = []
    for image in images:
        buf = io.BytesIO()
        image.save(buf, format="PNG", optimize=True)
        pngs.append(buf.getvalue())
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = b""
    for image, png in zip(images, pngs, strict=True):
        size = image.width
        entries += struct.pack("<BBBBHHII", 0 if size >= 256 else size, 0 if size >= 256 else size,
                               0, 0, 1, 32, len(png), offset)
        offset += len(png)
    return header + entries + b"".join(pngs)


def main():
    docs = os.path.join(ROOT, "assets")
    os.makedirs(docs, exist_ok=True)
    with open(os.path.join(docs, "bettervoice-mark.svg"), "w", encoding="utf-8", newline="\n") as f:
        f.write(brand.mark_svg())
    brand.draw_mark(512).save(os.path.join(docs, "bettervoice-mark.png"), optimize=True)
    os.makedirs(os.path.dirname(brand.ICON_PATH), exist_ok=True)
    with open(brand.ICON_PATH, "wb") as f:
        f.write(encode_ico([brand.draw_mark(size) for size in brand.ICON_SIZES]))
    brand.draw_mark(256).save(brand.ICON_PNG_PATH, optimize=True)
    for path in ("assets/bettervoice-mark.svg", "assets/bettervoice-mark.png",
                 os.path.relpath(brand.ICON_PATH, ROOT),
                 os.path.relpath(brand.ICON_PNG_PATH, ROOT)):
        print(f"wrote {path} ({os.path.getsize(os.path.join(ROOT, path)):,} bytes)")


if __name__ == "__main__":
    main()
