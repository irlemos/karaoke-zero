#!/usr/bin/env python3
"""
KaraokeZero - Boot Splash Video Generator
Generates a lightweight, hardware-accelerated 1080p H.264 MP4 video
displaying a dynamic progress bar, glowing shimmer wave, and status stages
for early boot DRM/KMS playback via MPV on Raspberry Pi VideoCore IV GPU.
"""

import math
import os
import subprocess
import sys
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


def generate_splash_video(
    output_mp4: str = "assets/boot_splash.mp4",
    width: int = 1920,
    height: int = 1080,
    fps: int = 25,
    duration: float = 50.0
):
    """
    Renders frames and pipes them directly to ffmpeg to encode H.264 video.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_mp4)), exist_ok=True)

    BG_TOP = (11, 15, 25)
    BG_BOTTOM = (18, 24, 40)
    ACCENT_CYAN = (0, 220, 255)
    ACCENT_YELLOW = (250, 204, 21)
    TEXT_WHITE = (255, 255, 255)
    TEXT_MUTED = (160, 175, 200)
    CARD_BG = (22, 29, 48)
    CARD_BORDER = (45, 58, 92)

    font_brand = resolve_font(64, bold=True)
    font_sub = resolve_font(24, bold=False)
    font_status = resolve_font(24, bold=True)
    font_small = resolve_font(16, bold=False)
    font_info = resolve_font(18, bold=False)

    # 1. Pre-render static background base
    base_img = Image.new("RGB", (width, height), BG_TOP)
    base_draw = ImageDraw.Draw(base_img)

    for y in range(height):
        factor = y / height
        r = int(BG_TOP[0] + factor * (BG_BOTTOM[0] - BG_TOP[0]))
        g = int(BG_TOP[1] + factor * (BG_BOTTOM[1] - BG_TOP[1]))
        b = int(BG_TOP[2] + factor * (BG_BOTTOM[2] - BG_TOP[2]))
        base_draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Top accent line
    base_draw.rectangle([0, 0, width, 6], fill=ACCENT_CYAN)

    center_y = height // 2 - 40
    base_draw.text((width // 2, center_y - 60), "K A R A O K E - Z E R O", fill=TEXT_WHITE, font=font_brand, anchor="mm")
    base_draw.text((width // 2, center_y), "STANDALONE OFFLINE KARAOKE APPLIANCE", fill=ACCENT_CYAN, font=font_sub, anchor="mm")

    # Status pill outline
    pill_w = 640
    pill_h = 60
    pill_x1 = (width - pill_w) // 2
    pill_y1 = center_y + 80
    base_draw.rounded_rectangle([pill_x1, pill_y1, pill_x1 + pill_w, pill_y1 + pill_h], radius=16, fill=CARD_BG, outline=CARD_BORDER, width=2)

    # Progress bar dimensions
    bar_w = 540
    bar_h = 14
    bar_x1 = (width - bar_w) // 2
    bar_y1 = pill_y1 + pill_h + 24
    bar_x2 = bar_x1 + bar_w
    bar_y2 = bar_y1 + bar_h

    # Progress bar track
    base_draw.rounded_rectangle([bar_x1, bar_y1, bar_x2, bar_y2], radius=7, fill=(18, 24, 38), outline=CARD_BORDER, width=1)

    # Specs footer
    footer_y = height - 80
    base_draw.text(
        (width // 2, footer_y),
        "Raspberry Pi Zero W  •  VideoCore IV GPU DRM/KMS  •  Zero GUI Overhead",
        fill=TEXT_MUTED,
        font=font_info,
        anchor="mm"
    )

    # Stages configuration (time_end, stage_text, start_progress, end_progress)
    stages = [
        (5.0,  "INITIALIZING HARDWARE SUBSYSTEMS",      0.10, 0.25),
        (12.0, "LOADING LINUX SYSTEM DAEMONS",         0.25, 0.50),
        (22.0, "MOUNTING STORAGE & MEDIA LIBRARY",     0.50, 0.75),
        (35.0, "STARTING PIKARAOKE APPLIANCE",         0.75, 0.92),
        (50.0, "AWAITING SERVICE READINESS",           0.92, 0.96),
    ]

    total_frames = int(duration * fps)

    # Start FFmpeg process piping raw RGB24 frames to libx264
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{width}x{height}",
        "-pix_fmt", "rgb24",
        "-r", str(fps),
        "-i", "-",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "faster",
        "-crf", "22",
        "-movflags", "+faststart",
        output_mp4
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    print(f"Generating {total_frames} frames ({duration}s @ {fps}fps) to {output_mp4}...")

    for frame_idx in range(total_frames):
        t = frame_idx / fps

        # Determine stage and progress
        curr_text = stages[-1][1]
        p = 0.95
        prev_end = 0.0

        for stage_end, text, p_start, p_end in stages:
            if t <= stage_end:
                curr_text = text
                stage_duration = stage_end - prev_end
                t_in_stage = t - prev_end
                ratio = max(0.0, min(1.0, t_in_stage / stage_duration if stage_duration > 0 else 1.0))
                # Smooth ease-in-out curve
                ratio_smooth = 0.5 - 0.5 * math.cos(ratio * math.pi)
                p = p_start + (p_end - p_start) * ratio_smooth
                break
            prev_end = stage_end

        frame = base_img.copy()
        draw = ImageDraw.Draw(frame)

        # Status text in pill
        draw.text((width // 2, pill_y1 + pill_h // 2), curr_text, fill=ACCENT_YELLOW, font=font_status, anchor="mm")

        # Progress bar fill
        fill_w = max(10, int(bar_w * p))
        draw.rounded_rectangle([bar_x1, bar_y1, bar_x1 + fill_w, bar_y2], radius=7, fill=ACCENT_CYAN)

        # Animated glowing shimmer pulse sweeping across the filled bar
        shimmer_period = 1.4
        shimmer_phase = (t % shimmer_period) / shimmer_period
        # Shimmer position moves across filled width with lead-in and lead-out
        shimmer_center = bar_x1 + int(shimmer_phase * (fill_w + 60)) - 30
        shimmer_width = 36

        s_x1 = max(bar_x1, shimmer_center - shimmer_width // 2)
        s_x2 = min(bar_x1 + fill_w, shimmer_center + shimmer_width // 2)

        if s_x2 > s_x1:
            # Bright highlight band
            draw.rounded_rectangle([s_x1, bar_y1 + 1, s_x2, bar_y2 - 1], radius=4, fill=(200, 245, 255))

        # Progress caption below bar
        pct_label = f"SYSTEM INITIALIZING  •  {int(p * 100)}%"
        draw.text((width // 2, bar_y2 + 20), pct_label, fill=TEXT_MUTED, font=font_small, anchor="mm")

        # Pipe raw bytes
        proc.stdin.write(frame.tobytes())

    proc.stdin.close()
    proc.wait()

    if proc.returncode != 0:
        stderr = proc.stderr.read().decode() if proc.stderr else ""
        print("FFmpeg error:", stderr, file=sys.stderr)
        return False

    size_kb = os.path.getsize(output_mp4) / 1024
    print(f"Successfully generated {output_mp4} ({size_kb:.1f} KB)")
    return True


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "assets/boot_splash.mp4"
    generate_splash_video(output_mp4=out)
