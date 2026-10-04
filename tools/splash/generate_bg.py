#!/usr/bin/env python3
"""
KaraokeZero - Boot Splash Background Asset Generator
Renders a 1080p high-contrast background image with typography and branding,
then compresses the raw BGRA pixel buffer with zlib into assets/splash_bg.bin (~25KB)
for instantaneous (< 5ms) memory-mapped loading by tools/splash/splash.
"""

import os
import sys
import zlib
from PIL import Image, ImageDraw, ImageFont


def resolve_font(size: int, bold: bool = False):
    """Resolves TrueType fonts with system fallbacks."""
    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf" if bold else "/usr/share/fonts/truetype/freefont/FreeSans.ttf"
    ]
    for path in font_candidates:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def generate_splash_background(output_bin: str = "assets/splash_bg.bin", width: int = 1920, height: int = 1080):
    BG_TOP = (11, 15, 25)
    BG_BOTTOM = (18, 24, 40)
    ACCENT_CYAN = (0, 220, 255)
    TEXT_WHITE = (255, 255, 255)
    TEXT_MUTED = (160, 175, 200)

    font_brand = resolve_font(64, bold=True)
    font_sub = resolve_font(24, bold=False)
    font_info = resolve_font(18, bold=False)

    img = Image.new("RGBA", (width, height), (*BG_TOP, 255))
    draw = ImageDraw.Draw(img)

    # Vertical gradient
    for y in range(height):
        factor = y / height
        r = int(BG_TOP[0] + factor * (BG_BOTTOM[0] - BG_TOP[0]))
        g = int(BG_TOP[1] + factor * (BG_BOTTOM[1] - BG_TOP[1]))
        b = int(BG_TOP[2] + factor * (BG_BOTTOM[2] - BG_TOP[2]))
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    # Top accent line
    draw.rectangle([0, 0, width, 5], fill=(*ACCENT_CYAN, 255))

    center_y = height // 2 - 40
    draw.text((width // 2, center_y - 60), "K A R A O K E - Z E R O", fill=(*TEXT_WHITE, 255), font=font_brand, anchor="mm")
    draw.text((width // 2, center_y), "STANDALONE OFFLINE KARAOKE APPLIANCE", fill=(*ACCENT_CYAN, 255), font=font_sub, anchor="mm")

    # Specs footer
    footer_y = height - 70
    draw.text(
        (width // 2, footer_y),
        "Raspberry Pi Zero W  •  VideoCore IV GPU  •  Zero GUI Overhead",
        fill=(*TEXT_MUTED, 255),
        font=font_info,
        anchor="mm"
    )

    # Raw 32-bit ARGB/BGRA bytes
    raw_bytes = img.tobytes("raw", "BGRA")
    compressed = zlib.compress(raw_bytes, level=6)

    os.makedirs(os.path.dirname(os.path.abspath(output_bin)), exist_ok=True)
    with open(output_bin, "wb") as f:
        f.write(compressed)

    # Also save PNG for offline viewing/fallbacks
    png_path = os.path.splitext(output_bin)[0] + ".png"
    img.save(png_path, "PNG")

    print(f"Generated {output_bin} ({len(compressed) / 1024:.1f} KB, raw {len(raw_bytes) / 1024:.1f} KB)")


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "assets/splash_bg.bin"
    generate_splash_background(out)
