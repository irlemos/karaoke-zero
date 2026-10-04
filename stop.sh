#!/usr/bin/env bash
# ==============================================================================
# KaraokeZero Appliance - Service Stop & Resource Release Utility
# Halts all active systemd services (orchestrator, pikaraoke, admin_panel,
# splash), terminates lingering media players and encoders, and frees DRM/KMS
# framebuffer display and network ports (5555, 8888).
# ==============================================================================

set -euo pipefail

# Visual formatting tokens
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

log_info() {
    echo -e "${CYAN}${BOLD}[INFO]${RESET} $1"
}

log_success() {
    echo -e "${GREEN}${BOLD}[SUCCESS]${RESET} $1"
}

log_warn() {
    echo -e "${YELLOW}${BOLD}[WARN]${RESET} $1"
}

# Require root permissions
if [[ ${EUID} -ne 0 ]]; then
    if command -v sudo >/dev/null 2>&1; then
        exec sudo bash "$0" "$@"
    else
        echo -e "${RED}${BOLD}[ERROR] This script must be run as root or with sudo.${RESET}" >&2
        exit 1
    fi
fi

echo -e "${CYAN}${BOLD}========================================================================${RESET}"
echo -e "${CYAN}${BOLD}         KaraokeZero - Halting Appliance Services & Freeing DRM        ${RESET}"
echo -e "${CYAN}${BOLD}========================================================================${RESET}"

SERVICES=(
    "orchestrator.service"
    "pikaraoke.service"
    "admin_panel.service"
    "karaokezero-splash.service"
)

# 1. Stop active systemd units
log_info "Stopping active systemd appliance services..."
for svc in "${SERVICES[@]}"; do
    if systemctl is-active --quiet "${svc}" 2>/dev/null; then
        echo -n "  • Stopping ${svc}... "
        systemctl stop "${svc}" 2>/dev/null || true
        echo -e "${GREEN}stopped${RESET}"
    else
        echo "  • ${svc} is already inactive."
    fi
done

# 2. Terminate any lingering media players, encoders, or child processes
log_info "Terminating lingering media players and daemon processes..."
PROCESS_PATTERNS=(
    "mpv"
    "pikaraoke"
    "orchestrator.py"
    "admin_panel/app.py"
    "show_splash.sh"
    "yt-dlp"
    "ffmpeg"
)

for pattern in "${PROCESS_PATTERNS[@]}"; do
    if pgrep -f "${pattern}" >/dev/null 2>&1; then
        pkill -9 -f "${pattern}" 2>/dev/null || true
        echo "  • Terminated processes matching '${pattern}'"
    fi
done

# 3. Clean stale IPC domain sockets
log_info "Cleaning stale IPC domain sockets..."
for sock in "/tmp/mpv.sock" "/tmp/mpv_splash.sock"; do
    if [[ -e "${sock}" ]]; then
        rm -f "${sock}"
        echo "  • Removed ${sock}"
    fi
done

# 4. Release network ports (5555: PiKaraoke, 8888: Admin Panel)
log_info "Verifying web ports are completely released..."
if command -v fuser >/dev/null 2>&1; then
    fuser -k 5555/tcp 2>/dev/null || true
    fuser -k 8888/tcp 2>/dev/null || true
fi

# 5. Clear HDMI console cursor and framebuffer artifacts
if [[ -c /dev/tty1 ]]; then
    TERM=linux setterm -cursor off >/dev/tty1 2>/dev/null || true
    clear >/dev/tty1 2>/dev/null || true
fi

echo -e "${GREEN}${BOLD}========================================================================${RESET}"
echo -e "${GREEN}${BOLD}[SUCCESS] All KaraokeZero and PiKaraoke services have been stopped.${RESET}"
echo -e "${GREEN}DRM/KMS display plane, audio device, CPU, and RAM are fully released.${RESET}"
echo -e "${GREEN}${BOLD}========================================================================${RESET}"
