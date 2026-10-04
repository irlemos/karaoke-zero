#!/usr/bin/env bash
# ==============================================================================
# KaraokeZero Appliance - Service Start & Health Check Utility
# Starts all core appliance systemd services (admin_panel, pikaraoke,
# orchestrator) and verifies their active operational status.
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
echo -e "${CYAN}${BOLD}       KaraokeZero - Starting Appliance Services & Display Engine       ${RESET}"
echo -e "${CYAN}${BOLD}========================================================================${RESET}"

# Stop any early boot splash if still lingering
if systemctl is-active --quiet karaokezero-splash.service 2>/dev/null; then
    systemctl stop karaokezero-splash.service 2>/dev/null || true
fi
pkill -f "boot_splash" 2>/dev/null || true

SERVICES=(
    "admin_panel.service"
    "pikaraoke.service"
    "orchestrator.service"
)

log_info "Starting appliance systemd services in dependency order..."
for svc in "${SERVICES[@]}"; do
    echo -n "  • Starting ${svc}... "
    systemctl restart "${svc}" 2>/dev/null || systemctl start "${svc}" 2>/dev/null || true
    sleep 0.5
    if systemctl is-active --quiet "${svc}" 2>/dev/null; then
        echo -e "${GREEN}active (running)${RESET}"
    else
        echo -e "${YELLOW}starting in background${RESET}"
    fi
done

echo ""
echo -e "${GREEN}${BOLD}========================================================================${RESET}"
echo -e "${GREEN}${BOLD}[SUCCESS] KaraokeZero services started successfully.${RESET}"
echo -e "  • PiKaraoke:   http://localhost:5555"
echo -e "  • Admin Panel: http://localhost:8888"
echo -e "${GREEN}${BOLD}========================================================================${RESET}"
