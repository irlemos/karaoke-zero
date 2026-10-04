#!/usr/bin/env bash
# ==============================================================================
# KaraokeZero Early Boot Splash Launcher
# Displays hardware-accelerated boot splash screen via MPV DRM/KMS during
# the earliest stages of systemd initialization (sysinit.target/basic.target).
# ==============================================================================

set -euo pipefail

# Wait up to 5 seconds for DRM/KMS device node (/dev/dri/card0 or /dev/dri/card1) to appear
for i in {1..25}; do
    if [[ -e /dev/dri/card0 || -e /dev/dri/card1 ]]; then
        break
    fi
    sleep 0.2
done

# Clean stale IPC socket
rm -f /tmp/mpv_splash.sock

# Locate splash image asset
SPLASH_IMG="/opt/karaokezero/assets/boot_splash.png"
if [[ ! -f "${SPLASH_IMG}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SPLASH_IMG="${SCRIPT_DIR}/../assets/boot_splash.png"
fi

# Exit gracefully if asset is missing
if [[ ! -f "${SPLASH_IMG}" ]]; then
    exit 0
fi

# Launch MPV directly on VideoCore IV GPU via DRM/KMS with zero window-system overhead
exec /usr/bin/mpv \
    --no-config \
    --vo=gpu \
    --gpu-context=drm \
    --hwdec=v4l2m2m-copy \
    --profile=fast \
    --no-terminal \
    --quiet \
    --no-audio \
    --loop-file=inf \
    --image-display-duration=inf \
    --input-ipc-server=/tmp/mpv_splash.sock \
    "${SPLASH_IMG}"
