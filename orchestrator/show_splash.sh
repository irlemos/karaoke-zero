#!/usr/bin/env bash
# ==============================================================================
# KaraokeZero Early Boot Splash Launcher with Dynamic Progress Animation
# Displays hardware-accelerated boot splash screen via MPV DRM/KMS during
# the earliest stages of systemd initialization and dynamically advances progress.
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

# Locate splash assets directory
SPLASH_DIR="/opt/karaokezero/assets/splash"
if [[ ! -d "${SPLASH_DIR}" ]]; then
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    SPLASH_DIR="${SCRIPT_DIR}/../assets/splash"
fi

INITIAL_IMG="${SPLASH_DIR}/splash_10.png"
if [[ ! -f "${INITIAL_IMG}" ]]; then
    INITIAL_IMG="/opt/karaokezero/assets/boot_splash.png"
fi

if [[ ! -f "${INITIAL_IMG}" ]]; then
    exit 0
fi

# Function to update MPV displayed image via IPC Unix domain socket
update_splash_frame() {
    local target_img="$1"
    if [[ ! -f "${target_img}" || ! -S /tmp/mpv_splash.sock ]]; then
        return 0
    fi
    python3 -c "
import socket, json, sys
try:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        s.connect('/tmp/mpv_splash.sock')
        cmd = json.dumps({'command': ['loadfile', sys.argv[1], 'replace']}) + '\n'
        s.sendall(cmd.encode('utf-8'))
except Exception:
    pass
" "${target_img}" 2>/dev/null || true
}

# Background worker: smoothly advances progress frames during systemd initialization
animate_early_boot() {
    # Wait for MPV IPC socket to become ready
    for i in {1..30}; do
        if [[ -S /tmp/mpv_splash.sock ]]; then
            break
        fi
        sleep 0.2
    done

    local stages=(
        "splash_20.png:3.0"
        "splash_30.png:3.5"
        "splash_40.png:3.5"
        "splash_50.png:4.0"
        "splash_60.png:4.0"
        "splash_70.png:4.0"
        "splash_80.png:4.0"
    )

    for stage in "${stages[@]}"; do
        IFS=":" read -r img delay <<< "${stage}"
        sleep "${delay}"
        if [[ ! -S /tmp/mpv_splash.sock ]]; then
            break
        fi
        update_splash_frame "${SPLASH_DIR}/${img}"
    done
}

# Start background progress animation
animate_early_boot &
ANIM_PID=$!

cleanup() {
    kill "${ANIM_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Launch MPV directly on VideoCore IV GPU via DRM/KMS
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
    "${INITIAL_IMG}"
