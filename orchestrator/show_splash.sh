#!/usr/bin/env bash
# ==============================================================================
# KaraokeZero Early Boot Splash Launcher
# Displays instantaneous hardware-accelerated boot splash on /dev/fb0 via the
# compiled C splash engine. Zero CPU overhead, zero external dependencies.
# ==============================================================================

set -euo pipefail

# Clean stale sockets
rm -f /tmp/mpv_splash.sock

# Locate compiled C framebuffer splash binary
SPLASH_BIN="/opt/karaokezero/tools/splash/splash"
if [[ ! -x "${SPLASH_BIN}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SPLASH_BIN="${SCRIPT_DIR}/../tools/splash/splash"
fi

# If compiled splash binary exists, execute directly on /dev/fb0
if [[ -x "${SPLASH_BIN}" ]]; then
    exec "${SPLASH_BIN}"
fi

# Fallback if binary is not yet compiled
FALLBACK_IMG="/opt/karaokezero/assets/boot_splash.png"
if [[ ! -f "${FALLBACK_IMG}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    FALLBACK_IMG="${SCRIPT_DIR}/../assets/boot_splash.png"
fi

if [[ -f "${FALLBACK_IMG}" && (-e /dev/dri/card0 || -e /dev/dri/card1) ]]; then
    exec /usr/bin/mpv \
        --no-config \
        --vo=gpu \
        --gpu-context=drm \
        --profile=fast \
        --no-terminal \
        --quiet \
        --no-audio \
        --image-display-duration=inf \
        "${FALLBACK_IMG}"
fi

exit 0
