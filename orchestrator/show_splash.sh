#!/usr/bin/env bash
# ==============================================================================
# KaraokeZero Early Boot Splash Launcher with Dynamic Hardware Video Animation
# Displays hardware-accelerated boot splash via MPV DRM/KMS during the earliest
# stages of systemd initialization (sysinit.target). Plays a lightweight H.264
# dynamic progress video on VideoCore IV GPU with zero CPU overhead.
# ==============================================================================

set -euo pipefail

# Wait up to 3 seconds for DRM/KMS device node (/dev/dri/card0 or /dev/dri/card1) to appear
for i in {1..30}; do
    if [[ -e /dev/dri/card0 || -e /dev/dri/card1 ]]; then
        break
    fi
    sleep 0.1
done

# Clean stale IPC socket
rm -f /tmp/mpv_splash.sock

# Locate splash assets directory
SPLASH_VIDEO="/opt/karaokezero/assets/boot_splash.mp4"
if [[ ! -f "${SPLASH_VIDEO}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SPLASH_VIDEO="${SCRIPT_DIR}/../assets/boot_splash.mp4"
fi

# Fallback image if MP4 is not yet generated
FALLBACK_IMG="/opt/karaokezero/assets/splash/splash_10.png"
if [[ ! -f "${FALLBACK_IMG}" ]]; then
    FALLBACK_IMG="/opt/karaokezero/assets/boot_splash.png"
fi

# If dynamic MP4 splash video exists, play with hardware decoding on VideoCore IV GPU
if [[ -f "${SPLASH_VIDEO}" ]]; then
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
        --input-ipc-server=/tmp/mpv_splash.sock \
        "${SPLASH_VIDEO}"
elif [[ -f "${FALLBACK_IMG}" ]]; then
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
        "${FALLBACK_IMG}"
fi

exit 0
