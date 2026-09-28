#!/usr/bin/env python3
"""
KaraokeZero - Module 2: Orchestrator Daemon
Idle Graphical Details Screen Generator

Renders high-resolution (1080p), beautiful graphical idle details screens
displaying the scannable mobile QR code, Wi-Fi instructions, IP address,
portal URL, and appliance branding for direct hardware rendering via MPV on DRM/KMS.
"""

import logging
import os
from typing import Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

logger = logging.getLogger("Orchestrator.ScreenGenerator")


class ScreenGenerator:
    """
    Renders clean, high-contrast graphical screens for DRM/KMS framebuffer output.
    """

    # Color Palette (Tailored dark mode with vibrant accents)
    BG_TOP = (11, 15, 25)
    BG_BOTTOM = (18, 24, 40)
    ACCENT_CYAN = (0, 220, 255)
    ACCENT_PURPLE = (168, 85, 247)
    ACCENT_YELLOW = (250, 204, 21)
    TEXT_WHITE = (255, 255, 255)
    TEXT_MUTED = (160, 175, 200)
    CARD_BG = (22, 29, 48)
    CARD_BORDER = (45, 58, 92)

    def __init__(
        self,
        output_path: str = "/tmp/karaoke_idle_screen.png",
        width: int = 1920,
        height: int = 1080
    ):
        self.output_path = output_path
        self.width = width
        self.height = height

    def _resolve_font(self, size: int, bold: bool = False):
        """Resolves TrueType fonts with system fallbacks."""
        if not PIL_AVAILABLE:
            return None

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

    def generate(
        self,
        output_path: Optional[str] = None,
        qr_path: Optional[str] = None,
        ip_address: Optional[str] = None,
        port: int = 5555,
        portal_port: int = 8888,
        wifi_ssid: Optional[str] = None,
        status_text: str = "SYSTEM READY  |  0 ACTIVE SONGS IN QUEUE  |  STANDBY"
    ) -> bool:
        """
        Renders the complete graphical idle details screen.
        """
        target_path = output_path or self.output_path

        if not PIL_AVAILABLE:
            logger.error("PIL/Pillow library not available. Cannot render graphical idle screen.")
            return False

        try:
            img = Image.new("RGB", (self.width, self.height), self.BG_TOP)
            draw = ImageDraw.Draw(img)

            # 1. Background gradient
            for y in range(self.height):
                factor = y / self.height
                r = int(self.BG_TOP[0] + factor * (self.BG_BOTTOM[0] - self.BG_TOP[0]))
                g = int(self.BG_TOP[1] + factor * (self.BG_BOTTOM[1] - self.BG_TOP[1]))
                b = int(self.BG_TOP[2] + factor * (self.BG_BOTTOM[2] - self.BG_TOP[2]))
                draw.line([(0, y), (self.width, y)], fill=(r, g, b))

            # Resolve typography
            font_brand = self._resolve_font(52, bold=True)
            font_sub = self._resolve_font(20, bold=False)
            font_section = self._resolve_font(26, bold=True)
            font_step_title = self._resolve_font(20, bold=True)
            font_body = self._resolve_font(22, bold=False)
            font_url = self._resolve_font(34, bold=True)
            font_caption = self._resolve_font(18, bold=True)
            font_small = self._resolve_font(15, bold=False)
            font_footer = self._resolve_font(18, bold=False)

            # 2. Header banner
            draw.rectangle([0, 0, self.width, 6], fill=self.ACCENT_CYAN)
            draw.text((self.width // 2, 60), "K A R A O K E - Z E R O", fill=self.TEXT_WHITE, font=font_brand, anchor="mm")
            draw.text((self.width // 2, 105), "STANDALONE OFFLINE KARAOKE APPLIANCE", fill=self.ACCENT_CYAN, font=font_sub, anchor="mm")

            header_line_w = 400
            draw.line([(self.width // 2 - header_line_w // 2, 125), (self.width // 2 + header_line_w // 2, 125)], fill=self.CARD_BORDER, width=2)

            # 3. Main layout containers
            content_top = 160
            content_h = 760

            # --- LEFT CARD: Scannable QR Code ---
            left_x1 = 120
            left_x2 = 720
            left_y1 = content_top
            left_y2 = content_top + content_h

            draw.rounded_rectangle([left_x1, left_y1, left_x2, left_y2], radius=24, fill=(255, 255, 255), outline=self.ACCENT_CYAN, width=3)
            draw.text(((left_x1 + left_x2) // 2, left_y1 + 50), "SCAN TO SING", fill=(15, 23, 42), font=font_section, anchor="mm")
            draw.text(((left_x1 + left_x2) // 2, left_y1 + 85), "ESCANEIE PARA CANTAR", fill=(100, 116, 139), font=font_caption, anchor="mm")

            qr_box_size = 440
            qr_x = (left_x1 + left_x2 - qr_box_size) // 2
            qr_y = left_y1 + 120

            qr_pasted = False
            if qr_path and os.path.isfile(qr_path):
                try:
                    qr_img = Image.open(qr_path).convert("RGB")
                    qr_img = qr_img.resize((qr_box_size, qr_box_size), Image.Resampling.NEAREST)
                    img.paste(qr_img, (qr_x, qr_y))
                    qr_pasted = True
                except Exception as e:
                    logger.debug("Failed to paste QR code image: %s", e)

            if not qr_pasted:
                draw.rectangle([qr_x, qr_y, qr_x + qr_box_size, qr_y + qr_box_size], fill=(240, 240, 245), outline=(200, 200, 200), width=2)
                draw.text(((left_x1 + left_x2) // 2, qr_y + qr_box_size // 2), "[ QR CODE READY ]", fill=(100, 100, 100), font=font_section, anchor="mm")

            draw.text(((left_x1 + left_x2) // 2, left_y2 - 60), "Use your smartphone camera", fill=(15, 23, 42), font=font_caption, anchor="mm")
            draw.text(((left_x1 + left_x2) // 2, left_y2 - 32), "Abra a camera do seu celular", fill=(100, 116, 139), font=font_small, anchor="mm")

            # --- RIGHT CARD: Connection Details & Instructions ---
            right_x1 = 780
            right_x2 = 1800
            right_y1 = content_top
            right_y2 = content_top + content_h

            draw.rounded_rectangle([right_x1, right_y1, right_x2, right_y2], radius=24, fill=self.CARD_BG, outline=self.CARD_BORDER, width=2)

            pad_x = right_x1 + 60
            curr_y = right_y1 + 55

            draw.text((pad_x, curr_y), "HOW TO CONNECT / COMO CONECTAR", fill=self.ACCENT_CYAN, font=font_section)
            curr_y += 65

            # Step 1: Wi-Fi
            draw.text((pad_x, curr_y), "STEP 1: Connect to Wi-Fi Network", fill=self.TEXT_WHITE, font=font_step_title)
            curr_y += 35
            badge_w = 900
            badge_h = 55
            ssid_label = wifi_ssid if wifi_ssid else "Venue Wi-Fi or Hotspot 'KaraokeZero-Setup'"
            draw.rounded_rectangle([pad_x, curr_y, pad_x + badge_w, curr_y + badge_h], radius=12, fill=(35, 45, 75), outline=(60, 80, 130), width=1)
            draw.text((pad_x + 20, curr_y + badge_h // 2), f"Wi-Fi: {ssid_label}", fill=self.ACCENT_YELLOW, font=font_body, anchor="lm")
            curr_y += 85

            # Step 2: Web App URL
            draw.text((pad_x, curr_y), "STEP 2: Open Web Browser or Scan QR Code", fill=self.TEXT_WHITE, font=font_step_title)
            curr_y += 35
            web_url = f"http://{ip_address}:{port}" if ip_address else f"http://127.0.0.1:{port}"
            url_badge_h = 75
            draw.rounded_rectangle([pad_x, curr_y, pad_x + badge_w, curr_y + url_badge_h], radius=14, fill=(15, 35, 55), outline=self.ACCENT_CYAN, width=2)
            draw.text((pad_x + 25, curr_y + url_badge_h // 2), web_url, fill=self.ACCENT_CYAN, font=font_url, anchor="lm")
            curr_y += 105

            # Step 3: Wi-Fi Setup Portal
            draw.text((pad_x, curr_y), "STEP 3: Wi-Fi Setup Portal (Venue Configuration)", fill=self.TEXT_WHITE, font=font_step_title)
            curr_y += 35
            portal_url = f"http://{ip_address}:{portal_port}" if ip_address else f"http://192.168.4.1:{portal_port}"
            portal_badge_h = 55
            draw.rounded_rectangle([pad_x, curr_y, pad_x + badge_w, curr_y + portal_badge_h], radius=12, fill=(35, 45, 75), outline=(60, 80, 130), width=1)
            draw.text((pad_x + 20, curr_y + portal_badge_h // 2), f"Setup Portal: {portal_url}", fill=self.TEXT_MUTED, font=font_body, anchor="lm")
            curr_y += 95

            # Hints & Tips
            draw.line([(pad_x, curr_y), (pad_x + badge_w, curr_y)], fill=self.CARD_BORDER, width=1)
            curr_y += 25
            draw.text((pad_x, curr_y), "• Add your favorite songs to the queue directly from your phone.", fill=self.TEXT_MUTED, font=font_body)
            curr_y += 35
            draw.text((pad_x, curr_y), "• Adicione suas musicas favoritas na fila direto pelo smartphone.", fill=self.TEXT_MUTED, font=font_body)

            # 4. Footer status bar
            footer_y = self.height - 70
            draw.rectangle([0, footer_y, self.width, self.height], fill=(9, 12, 20))
            draw.line([(0, footer_y), (self.width, footer_y)], fill=self.CARD_BORDER, width=1)

            dot_x = 120
            dot_y = footer_y + 35
            draw.ellipse([dot_x - 7, dot_y - 7, dot_x + 7, dot_y + 7], fill=(34, 197, 94))
            draw.text((dot_x + 20, dot_y), status_text, fill=(34, 197, 94), font=font_footer, anchor="lm")
            draw.text((self.width - 120, dot_y), "DRM/KMS Hardware Video  •  ALSA HDMI Audio", fill=self.TEXT_MUTED, font=font_footer, anchor="rm")

            # Save image directly
            img.save(target_path, "PNG")
            logger.info("Generated graphical idle details screen -> %s", target_path)
            return True
        except Exception as e:
            logger.exception("Failed to render graphical idle details screen: %s", e)
            return False

    def generate_boot_screen(
        self,
        output_path: Optional[str] = None,
        status_text: str = "Starting PiKaraoke appliance services..."
    ) -> bool:
        """
        Renders a clean, high-resolution appliance startup splash screen during boot.
        """
        target_path = output_path or self.output_path

        if not PIL_AVAILABLE:
            return False

        try:
            img = Image.new("RGB", (self.width, self.height), self.BG_TOP)
            draw = ImageDraw.Draw(img)

            # Gradient background
            for y in range(self.height):
                factor = y / self.height
                r = int(self.BG_TOP[0] + factor * (self.BG_BOTTOM[0] - self.BG_TOP[0]))
                g = int(self.BG_TOP[1] + factor * (self.BG_BOTTOM[1] - self.BG_TOP[1]))
                b = int(self.BG_TOP[2] + factor * (self.BG_BOTTOM[2] - self.BG_TOP[2]))
                draw.line([(0, y), (self.width, y)], fill=(r, g, b))

            font_brand = self._resolve_font(64, bold=True)
            font_sub = self._resolve_font(24, bold=False)
            font_status = self._resolve_font(24, bold=True)
            font_info = self._resolve_font(18, bold=False)

            draw.rectangle([0, 0, self.width, 6], fill=self.ACCENT_CYAN)

            center_y = self.height // 2 - 40
            draw.text((self.width // 2, center_y - 60), "K A R A O K E - Z E R O", fill=self.TEXT_WHITE, font=font_brand, anchor="mm")
            draw.text((self.width // 2, center_y), "STANDALONE OFFLINE KARAOKE APPLIANCE", fill=self.ACCENT_CYAN, font=font_sub, anchor="mm")

            # Status pill
            pill_w = 600
            pill_h = 60
            pill_x1 = (self.width - pill_w) // 2
            pill_y1 = center_y + 80
            draw.rounded_rectangle([pill_x1, pill_y1, pill_x1 + pill_w, pill_y1 + pill_h], radius=16, fill=self.CARD_BG, outline=self.CARD_BORDER, width=2)
            draw.text((self.width // 2, pill_y1 + pill_h // 2), status_text, fill=self.ACCENT_YELLOW, font=font_status, anchor="mm")

            # Hardware specs at bottom
            footer_y = self.height - 80
            draw.text(
                (self.width // 2, footer_y),
                "Raspberry Pi Zero W  •  VideoCore IV GPU DRM/KMS  •  Zero GUI Overhead",
                fill=self.TEXT_MUTED,
                font=font_info,
                anchor="mm"
            )

            img.save(target_path, "PNG")
            logger.info("Generated graphical boot splash screen -> %s", target_path)
            return True
        except Exception as e:
            logger.exception("Failed to render graphical boot splash screen: %s", e)
            return False
