# KaraokeZero Project Guidelines

## 1. Language Standard
- **English (US)** is mandatory across all repository artifacts, including:
  - Source code, variable names, functions, and classes
  - Inline comments and docstrings
  - Commit messages and pull request descriptions
  - User interfaces (HTML/CSS/JS, captive portal banners, buttons, placeholders)
  - API schemas and JSON error/status payloads
  - Documentation and guides (README files, design docs, manifests)

## 2. Target Platform & Hardware Constraints
- **Primary Hardware:** Raspberry Pi Zero W (ARMv6, single-core 1.0 GHz, 512MB RAM).
- **Secondary Targets:** Raspberry Pi 3 / 4 / 5.
- **Operating System:** Raspberry Pi OS Lite (32-bit Bullseye, headless).
- **Zero GUI Overhead:** No X11, Wayland, or desktop managers. No local Chromium or web browser running on the device.
- **Memory Footprint:** Keep custom daemons and services under 25MB RAM whenever possible.
- **SD Card Protection:** Write-heavy storage (SQLite database, video buffers, downloads) must be routed to the external drive mounted at `/mnt/external_hd/karaoke`.

## 3. Network Architecture & Hotspot Strategy
- **Priority 100:** Admin Mobile Hotspot (fallback / provisioning connection).
- **Priority 50:** Venue Wi-Fi (target network configured via captive portal).
- **Captive UI:** 100% self-contained without external CDN dependencies (fonts, styles, scripts, or icons). Must be fully functional when disconnected from the internet.
