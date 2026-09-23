# KaraokeZero Project Guidelines

## Language Standard
- **English (US)** is the mandatory standard for all project artifacts, code, inline comments, docstrings, commit messages, API payloads, user interfaces (UI), and documentation (README, guides, manifests).
- Even when communicating with Portuguese-speaking users, maintain all generated code, identifiers, templates, documentation, and user-facing UI text in English (US).

## Architecture & Resource Constraints
- Target platform: Raspberry Pi Zero W / RPi 3 running Raspberry Pi OS Lite (32-bit Bullseye, headless).
- Ultra-low memory and CPU footprint (no X11/Wayland desktop, zero web browser instances running locally on the Pi).
- Minimal dependencies (standard library preferred; lightweight frameworks like Flask when required).
- Zero external CDN dependencies in web interfaces (captive portals and dashboards must function completely offline).
