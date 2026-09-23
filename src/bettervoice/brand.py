"""The BetterVoice brand in one place: name, words, colors and the mark.

The mark is built like its sibling, the BetterC0de icon (see BRAND.md): a
near-black tile with a 22 % corner radius and four bars of the same weight in
warm white at 38 / 72 / 100 / 40 % opacity. BetterC0de lays its bars down as
lines of code; BetterVoice stands them up as a voice level.
"""

import os

from PIL import Image, ImageDraw

from bettervoice import __version__

NAME = "BetterVoice"
TAGLINE = "Your voice, typed anywhere."
DESCRIPTION = (
    "BetterVoice is a Windows dictation app: press Win+O, speak, and your words "
    "appear wherever your cursor is."
)
AUTHOR = "kerim0x1"
REPO_URL = "https://github.com/kerim0x1/bettervoice"
USER_AGENT = f"{NAME}/{__version__} (+{REPO_URL})"
# Windows groups taskbar buttons by this ID; without it a source run would
# show Python's icon instead of ours
APP_USER_MODEL_ID = "kerim0x1.BetterVoice"

# ---------------------------------------------------------------- colors ---

NEAR_BLACK = "#0A0A0A"
WARM_WHITE = "#F7F5F2"
LIGHT_GRAY = "#B5B5B5"  # warm white at 72 % on near black
MID_GRAY = "#666666"  # warm white at 38 % on near black

# ------------------------------------------------------------------ mark ---

# in a 100 x 100 box, like BetterC0de's favicon.svg
TILE_RADIUS = 22
BAR_RADIUS = 3
BAR_WIDTH = 13
BAR_PITCH = 22
BARS = (  # (height, warm-white opacity), left to right, centered vertically
    (40, 0.38),
    (66, 0.72),
    (54, 1.00),
    (30, 0.40),
)
_FIRST_BAR_X = (100 - BAR_WIDTH * len(BARS) - (BAR_PITCH - BAR_WIDTH) * (len(BARS) - 1)) / 2

ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)  # 100-200 % small and large icons


def _hex_rgb(color):
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _on_tile(opacity):
    """Warm white at `opacity` over the tile, as an opaque color: a see-through
    bar would take on the color behind the icon instead of the tile's."""
    tile, ink = _hex_rgb(NEAR_BLACK), _hex_rgb(WARM_WHITE)
    return tuple(round(t + (i - t) * opacity) for t, i in zip(tile, ink, strict=True)) + (255,)


def draw_mark(size):
    """The mark as a size x size RGBA image.

    Up to 64 px the bars are snapped to whole pixels, so small icons (tray,
    title bar) stay crisp instead of blurring into gray stripes.
    """
    ss = 4  # supersampling for smooth corners
    canvas = size * ss
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, canvas - 1, canvas - 1], radius=TILE_RADIUS * canvas / 100,
                           fill=_hex_rgb(NEAR_BLACK) + (255,))
    k = size / 100
    snap = size <= 64
    if snap:
        width = max(1, round(BAR_WIDTH * k))
        pitch = max(width + 1, round(BAR_PITCH * k))
        left = (size - width * len(BARS) - (pitch - width) * (len(BARS) - 1)) // 2
    for i, (height, opacity) in enumerate(BARS):
        if snap:
            h = max(2, round(height * k))
            h += (size - h) % 2  # same parity as the tile: centered on the grid
            x0, y0 = left + i * pitch, (size - h) // 2
            box = [x0 * ss, y0 * ss, (x0 + width) * ss - 1, (y0 + h) * ss - 1]
        else:
            x = _FIRST_BAR_X + i * BAR_PITCH
            box = [x * k * ss, (50 - height / 2) * k * ss,
                   (x + BAR_WIDTH) * k * ss, (50 + height / 2) * k * ss]
        draw.rounded_rectangle(box, radius=max(0.5, BAR_RADIUS * k) * ss, fill=_on_tile(opacity))
    return img.resize((size, size), Image.BOX if snap else Image.LANCZOS)


def mark_svg():
    """The mark as an SVG document (the vector master for docs and web)."""
    bars = "\n".join(
        f'  <rect x="{_FIRST_BAR_X + i * BAR_PITCH:g}" y="{50 - height / 2:g}" '
        f'width="{BAR_WIDTH}" height="{height}" rx="{BAR_RADIUS}" fill="{WARM_WHITE.lower()}"'
        + (f' opacity="{opacity:g}"' if opacity < 1 else "") + "/>"
        for i, (height, opacity) in enumerate(BARS)
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 100 100" '
        f'fill="none">\n  <rect width="100" height="100" rx="{TILE_RADIUS}" '
        f'fill="{NEAR_BLACK.lower()}"/>\n{bars}\n</svg>\n'
    )
