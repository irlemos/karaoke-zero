#!/usr/bin/env bash
# ==============================================================================
# KaraokeZero - Module 3: Master Installer & Provisioning Engine
# ==============================================================================
# Transforms a clean Raspberry Pi OS Lite (32-bit Bookworm or newer) into an
# ultra-low resource, zero-GUI headless KaraokeZero appliance.
# ==============================================================================

set -euo pipefail

# Visual formatting helpers
BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
CYAN="\033[0;36m"
RED="\033[0;31m"
RESET="\033[0m"

log_info()    { echo -e "${CYAN}[INFO]${RESET} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${RESET} $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${RESET} $*"; }
log_error()   { echo -e "${RED}[ERROR]${RESET} $*"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}"

# Default CLI options
CONFIG_FILE="${SCRIPT_DIR}/config.env"
LOG_FILE="${SCRIPT_DIR}/install.log"
DRY_RUN="false"
NON_INTERACTIVE="false"

usage() {
    cat << EOF
KaraokeZero Installer & Provisioning Engine

Usage:
    sudo bash $(basename "$0") [OPTIONS]

Options:
    --config <path>       Specify custom config file (default: ${CONFIG_FILE})
    --log <path>          Specify custom log file (default: ${LOG_FILE})
    --dry-run             Simulate execution without modifying the host system
    --non-interactive     Fail if required configurations are missing instead of prompting
    -h, --help            Show this help message
EOF
    exit 0
}

# Parse command line flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --log)
            LOG_FILE="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN="true"
            shift
            ;;
        --non-interactive)
            NON_INTERACTIVE="true"
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            log_error "Unknown argument: $1"
            usage
            ;;
    esac
done

# ------------------------------------------------------------------------------
# Logging Initialization (captures terminal output to a single clean log file)
# ------------------------------------------------------------------------------
# Always start fresh with an empty log file for each run in the script directory
: > "${LOG_FILE}"
chmod 644 "${LOG_FILE}" 2>/dev/null || true
if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    chown "${SUDO_USER}:" "${LOG_FILE}" 2>/dev/null || true
fi

# Duplicate stdout and stderr to both console and log file in real-time
exec 3>&1 4>&2
cleanup_logging() {
    local exit_code=$?
    if [[ ${exit_code} -ne 0 ]]; then
        echo -e "${RED}${BOLD}[ERROR] Installation aborted or failed with exit code ${exit_code}.${RESET}" >&2
        echo -e "${RED}${BOLD}[ERROR] Full installation log available at: ${LOG_FILE}${RESET}" >&2
    fi
    exec 1>&3 2>&4 3>&- 4>&- 2>/dev/null || true
}
trap cleanup_logging EXIT INT TERM
exec > >(tee "${LOG_FILE}") 2>&1

echo -e "${BOLD}===================================================================${RESET}"
echo -e "${BOLD}KaraokeZero Appliance - Automated Provisioning Engine${RESET}"
echo -e "${BOLD}===================================================================${RESET}"
log_info "Logging session output to: ${LOG_FILE}"

# ------------------------------------------------------------------------------
# 1. Pre-flight Checks
# ------------------------------------------------------------------------------
if [[ "${DRY_RUN}" != "true" && "${EUID}" -ne 0 ]]; then
    log_error "This script must be run as root. Please run: sudo bash $0"
    exit 1
fi

log_info "Running pre-flight system checks..."
ARCH=$(uname -m)
log_info "Detected architecture: ${ARCH}"

# Detect standard non-root runtime user (who executed sudo or primary login user)
if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    APP_USER="${SUDO_USER}"
else
    APP_USER=$(id -un 1000 2>/dev/null || echo "karaoke")
fi
APP_HOME=$(getent passwd "${APP_USER}" 2>/dev/null | cut -d: -f6)
APP_HOME="${APP_HOME:-/home/${APP_USER}}"
log_info "Target non-root runtime user: ${APP_USER} (${APP_HOME})"

# ------------------------------------------------------------------------------
# 2. Configuration Loading
# ------------------------------------------------------------------------------
if [[ -f "${CONFIG_FILE}" ]]; then
    log_info "Loading configuration from: ${CONFIG_FILE}"
    # shellcheck source=/dev/null
    source "${CONFIG_FILE}"
else
    log_warn "Configuration file not found at ${CONFIG_FILE}. Applying defaults..."
    STORAGE_TYPE="${STORAGE_TYPE:-}"
    STORAGE_DEVICE="${STORAGE_DEVICE:-}"
    MOUNT_POINT="${MOUNT_POINT:-/mnt/external_hd/karaoke}"
    SD_CARD_STORAGE_PATH="${SD_CARD_STORAGE_PATH:-}"
    ADMIN_WIFI_SSID="${ADMIN_WIFI_SSID:-}"
    ADMIN_WIFI_PASSWORD="${ADMIN_WIFI_PASSWORD:-}"
    PIKARAOKE_PORT="${PIKARAOKE_PORT:-5555}"
    WIFI_MANAGER_PORT="${WIFI_MANAGER_PORT:-8888}"
    PIKARAOKE_REPO_URL="${PIKARAOKE_REPO_URL:-https://github.com/vicwomg/pikaraoke.git}"
    PIKARAOKE_BRANCH="${PIKARAOKE_BRANCH:-master}"
    PIKARAOKE_INSTALL_DIR="${PIKARAOKE_INSTALL_DIR:-/opt/pikaraoke}"
    KARAOKEZERO_INSTALL_DIR="${KARAOKEZERO_INSTALL_DIR:-/opt/karaokezero}"
    CONFIGURE_BOOT_CONFIG="${CONFIGURE_BOOT_CONFIG:-true}"
    SUPPRESS_FB_CURSOR="${SUPPRESS_FB_CURSOR:-true}"
    ENABLE_SERVICES_NOW="${ENABLE_SERVICES_NOW:-true}"
fi

# Ensure all default variables exist
STORAGE_TYPE="${STORAGE_TYPE:-}"
STORAGE_DEVICE="${STORAGE_DEVICE:-}"
MOUNT_POINT="${MOUNT_POINT:-/mnt/external_hd/karaoke}"
SD_CARD_STORAGE_PATH="${SD_CARD_STORAGE_PATH:-}"
ADMIN_WIFI_SSID="${ADMIN_WIFI_SSID:-}"
ADMIN_WIFI_PASSWORD="${ADMIN_WIFI_PASSWORD:-}"
PIKARAOKE_PORT="${PIKARAOKE_PORT:-5555}"
WIFI_MANAGER_PORT="${WIFI_MANAGER_PORT:-8888}"
PIKARAOKE_REPO_URL="${PIKARAOKE_REPO_URL:-https://github.com/vicwomg/pikaraoke.git}"
PIKARAOKE_BRANCH="${PIKARAOKE_BRANCH:-master}"
PIKARAOKE_INSTALL_DIR="${PIKARAOKE_INSTALL_DIR:-/opt/pikaraoke}"
KARAOKEZERO_INSTALL_DIR="${KARAOKEZERO_INSTALL_DIR:-/opt/karaokezero}"
CONFIGURE_BOOT_CONFIG="${CONFIGURE_BOOT_CONFIG:-true}"
SUPPRESS_FB_CURSOR="${SUPPRESS_FB_CURSOR:-true}"
ENABLE_SERVICES_NOW="${ENABLE_SERVICES_NOW:-true}"

# ------------------------------------------------------------------------------
# 3. Interactive Prompts for Incomplete Configuration
# ------------------------------------------------------------------------------

# 3.1. Storage Device Selection
if [[ -z "${STORAGE_TYPE}" ]]; then
    if [[ "${NON_INTERACTIVE}" == "true" ]]; then
        log_error "STORAGE_TYPE is required in non-interactive mode."
        exit 1
    fi

    echo ""
    echo -e "${RED}${BOLD}========================================================================${RESET}"
    echo -e "${YELLOW}${BOLD}STORAGE NOTICE & FLASH MEMORY WEAR WARNING${RESET}"
    echo -e "${RED}${BOLD}========================================================================${RESET}"
    echo -e "KaraokeZero routes the persistent SQLite database, YouTube download"
    echo -e "buffers (yt-dlp), and the media library to your chosen storage."
    echo ""
    echo -e "${RED}USING THE INTERNAL MICRO-SD CARD IS STRONGLY DISCOURAGED:${RESET}"
    echo -e "  1. ${BOLD}I/O Speed Bottlenecks:${RESET} Single-bus SD access causes audio/video"
    echo -e "     playback stutter when songs are being downloaded in the background."
    echo -e "  2. ${BOLD}Hardware Degradation:${RESET} Frequent write cycles rapidly wear down"
    echo -e "     flash blocks, resulting in MicroSD card corruption and boot failure."
    echo ""
    echo -e "${GREEN}${BOLD}RECOMMENDED:${RESET} Use an external USB Hard Drive / SSD mounted at"
    echo -e "${MOUNT_POINT}."
    echo -e "${RED}${BOLD}========================================================================${RESET}"
    echo ""

    echo -e "${BOLD}Select storage destination:${RESET}"
    echo "  1) External USB Drive / SSD (Recommended)"
    echo "  2) Internal MicroSD Card Directory (Not recommended)"
    read -rp "Enter choice [1 or 2] (Default: 1): " STORAGE_CHOICE
    STORAGE_CHOICE="${STORAGE_CHOICE:-1}"

    if [[ "${STORAGE_CHOICE}" == "1" ]]; then
        STORAGE_TYPE="external_hd"
    else
        STORAGE_TYPE="sd_card"
    fi
fi

if [[ "${STORAGE_TYPE}" == "external_hd" && -z "${STORAGE_DEVICE}" ]]; then
    if [[ "${NON_INTERACTIVE}" == "true" ]]; then
        log_error "STORAGE_DEVICE is required when STORAGE_TYPE='external_hd' in non-interactive mode."
        exit 1
    fi

    echo ""
    log_info "Detected storage partitions on this system:"
    if command -v lsblk >/dev/null 2>&1; then
        lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL || true
    else
        fdisk -l || true
    fi
    echo ""
    read -rp "Enter partition device path or UUID (e.g. /dev/sda1 or UUID=xxxx) [Default: /dev/sda1]: " INPUT_DEVICE
    STORAGE_DEVICE="${INPUT_DEVICE:-/dev/sda1}"
elif [[ "${STORAGE_TYPE}" == "sd_card" && -z "${SD_CARD_STORAGE_PATH}" ]]; then
    if [[ "${NON_INTERACTIVE}" == "true" ]]; then
        log_error "SD_CARD_STORAGE_PATH is required when STORAGE_TYPE='sd_card' in non-interactive mode."
        exit 1
    fi
    echo ""
    read -rp "Enter SD card storage directory path [Default: /var/lib/karaokezero]: " INPUT_SD_PATH
    SD_CARD_STORAGE_PATH="${INPUT_SD_PATH:-/var/lib/karaokezero}"
fi

# 3.2. Initial Wi-Fi / Admin Hotspot Setup
if [[ -z "${ADMIN_WIFI_SSID}" ]]; then
    if [[ "${NON_INTERACTIVE}" != "true" ]]; then
        echo ""
        echo -e "${BOLD}Configure Primary Fallback Wi-Fi (Admin Mobile Hotspot):${RESET}"
        echo -e "This network will be saved with Priority 100 in NetworkManager as a fallback connection."
        read -rp "Enter Admin Hotspot SSID (or press Enter to skip): " INPUT_SSID
        if [[ -n "${INPUT_SSID}" ]]; then
            ADMIN_WIFI_SSID="${INPUT_SSID}"
            read -rsp "Enter Password for '${ADMIN_WIFI_SSID}': " INPUT_PASS
            echo ""
            ADMIN_WIFI_PASSWORD="${INPUT_PASS}"
        fi
    fi
fi

# ------------------------------------------------------------------------------
# 4. Storage Provisioning
# ------------------------------------------------------------------------------
log_info "Configuring media and data storage paths..."

if [[ "${STORAGE_TYPE}" == "external_hd" ]]; then
    SONGS_DIR="${MOUNT_POINT}/songs"
    DATA_DIR="${MOUNT_POINT}/data"
    MEDIA_DIR="${MOUNT_POINT}/media"

    log_info "Storage target: External Drive (${STORAGE_DEVICE}) -> ${MOUNT_POINT}"

    if [[ "${DRY_RUN}" != "true" ]]; then
        mkdir -p "${MOUNT_POINT}"

        # Resolve UUID if STORAGE_DEVICE is a block device (e.g. /dev/sda1)
        FSTAB_TARGET="${STORAGE_DEVICE}"
        if [[ "${STORAGE_DEVICE}" =~ ^/dev/ ]]; then
            DEVICE_UUID=$(blkid -s UUID -o value "${STORAGE_DEVICE}" 2>/dev/null || true)
            if [[ -n "${DEVICE_UUID}" ]]; then
                log_info "Resolved ${STORAGE_DEVICE} to UUID=${DEVICE_UUID}"
                FSTAB_TARGET="UUID=${DEVICE_UUID}"
            fi
        fi

        # Add fstab entry with automount, nofail, and generous timeout
        FSTAB_ENTRY="${FSTAB_TARGET} ${MOUNT_POINT} auto defaults,noatime,nofail,x-systemd.automount,x-systemd.device-timeout=30 0 2"
        if ! grep -qs "${MOUNT_POINT}" /etc/fstab; then
            log_info "Adding ${MOUNT_POINT} (${FSTAB_TARGET}) to /etc/fstab with x-systemd.automount..."
            echo "${FSTAB_ENTRY}" >> /etc/fstab
        else
            log_info "Updating existing ${MOUNT_POINT} entry in /etc/fstab..."
            sed -i "s|.*[[:space:]]${MOUNT_POINT}[[:space:]].*|${FSTAB_ENTRY}|" /etc/fstab
        fi

        if command -v systemctl >/dev/null 2>&1; then
            systemctl daemon-reload 2>/dev/null || true
        fi

        # Mount target if device exists and not currently mounted
        if ! mountpoint -q "${MOUNT_POINT}"; then
            mount "${MOUNT_POINT}" || log_warn "Could not mount ${STORAGE_DEVICE} to ${MOUNT_POINT}. Will mount on next reboot or when drive is plugged in."
        fi

        mkdir -p "${SONGS_DIR}" "${DATA_DIR}" "${MEDIA_DIR}"
        chown -R "${APP_USER}:${APP_USER}" "${MOUNT_POINT}" 2>/dev/null || true
        chmod -R 777 "${MOUNT_POINT}" || true
    fi
else
    SONGS_DIR="${SD_CARD_STORAGE_PATH}/songs"
    DATA_DIR="${SD_CARD_STORAGE_PATH}/data"
    MEDIA_DIR="${SD_CARD_STORAGE_PATH}/media"

    log_warn "Storage target: Internal MicroSD Card at ${SD_CARD_STORAGE_PATH}"
    if [[ "${DRY_RUN}" != "true" ]]; then
        mkdir -p "${SONGS_DIR}" "${DATA_DIR}" "${MEDIA_DIR}"
        chmod -R 777 "${SD_CARD_STORAGE_PATH}" || true
    fi
fi

# ------------------------------------------------------------------------------
# 5. System Package Installation
# ------------------------------------------------------------------------------
log_info "Installing core system packages..."

PKGS=(
    network-manager
    vlc
    qrencode
    ffmpeg
    alsa-utils
    python3
    python3-pip
    python3-venv
    python3-flask
    python3-brotli
    python3-gevent
    python3-greenlet
    python3-psutil
    python3-mutagen
    python3-pycryptodome
    python3-websockets
    python3-qrcode
    python3-requests
    python3-urllib3
    python3-babel
    python3-jinja2
    python3-werkzeug
    python3-markupsafe
    python3-click
    python3-blinker
    python3-itsdangerous
    python3-simple-websocket
    python3-wsproto
    git
    curl
)

if [[ "${DRY_RUN}" != "true" ]]; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    apt-get install -y "${PKGS[@]}"

    # Ensure application runtime user has hardware access permissions (DRM, framebuffer, audio, input)
    if id "${APP_USER}" >/dev/null 2>&1; then
        log_info "Configuring hardware access groups for user '${APP_USER}'..."
        usermod -a -G video,audio,render,input "${APP_USER}" 2>/dev/null || true
    fi

    # Modern yt-dlp binary installation from official GitHub release
    log_info "Installing / updating official yt-dlp binary..."
    curl -sL https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp
    chmod a+rx /usr/local/bin/yt-dlp

    # Enable NetworkManager and disable dhcpcd for the next boot without disrupting current live connection
    log_info "Configuring network stack for next boot (preserving active connection)..."
    if command -v systemctl >/dev/null 2>&1; then
        systemctl unmask NetworkManager.service 2>/dev/null || true
        systemctl enable NetworkManager.service 2>/dev/null || true
        systemctl disable dhcpcd 2>/dev/null || true
    fi
fi

# ------------------------------------------------------------------------------
# 6. Upstream PiKaraoke Deployment (Always Latest Master)
# ------------------------------------------------------------------------------
log_info "Deploying official upstream PiKaraoke (latest master branch)..."

if [[ "${DRY_RUN}" != "true" ]]; then
    mkdir -p "$(dirname "${PIKARAOKE_INSTALL_DIR}")"
    if [[ -d "${PIKARAOKE_INSTALL_DIR}/.git" ]]; then
        log_info "Updating existing PiKaraoke clone to latest master..."
        git -C "${PIKARAOKE_INSTALL_DIR}" remote set-url origin "${PIKARAOKE_REPO_URL}" 2>/dev/null || true
        git -C "${PIKARAOKE_INSTALL_DIR}" fetch origin master
        git -C "${PIKARAOKE_INSTALL_DIR}" checkout master
        git -C "${PIKARAOKE_INSTALL_DIR}" pull --ff-only origin master || true
    else
        log_info "Cloning latest PiKaraoke (master branch) to ${PIKARAOKE_INSTALL_DIR}..."
        git clone --depth 1 -b master "${PIKARAOKE_REPO_URL}" "${PIKARAOKE_INSTALL_DIR}"
    fi

    # Create isolated Python virtualenv with access to system packages (PEP 668 compliant, native APT packages)
    if [[ ! -d "${PIKARAOKE_INSTALL_DIR}/venv" ]]; then
        log_info "Creating Python virtual environment in ${PIKARAOKE_INSTALL_DIR}/venv (with system site packages)..."
        python3 -m venv --system-site-packages "${PIKARAOKE_INSTALL_DIR}/venv"
    else
        log_info "Ensuring system site packages are enabled in ${PIKARAOKE_INSTALL_DIR}/venv..."
        python3 -m venv --system-site-packages --upgrade "${PIKARAOKE_INSTALL_DIR}/venv" 2>/dev/null || true
        if [[ -f "${PIKARAOKE_INSTALL_DIR}/venv/pyvenv.cfg" ]]; then
            sed -i 's/include-system-site-packages = false/include-system-site-packages = true/' "${PIKARAOKE_INSTALL_DIR}/venv/pyvenv.cfg"
        fi
    fi

    log_info "Installing PiKaraoke and dependencies into virtual environment..."
    "${PIKARAOKE_INSTALL_DIR}/venv/bin/pip" install --upgrade pip setuptools wheel
    if [[ -f "${PIKARAOKE_INSTALL_DIR}/pyproject.toml" ]]; then
        "${PIKARAOKE_INSTALL_DIR}/venv/bin/pip" install --extra-index-url https://www.piwheels.org/simple "${PIKARAOKE_INSTALL_DIR}" || \
        "${PIKARAOKE_INSTALL_DIR}/venv/bin/pip" install "${PIKARAOKE_INSTALL_DIR}"
    elif [[ -f "${PIKARAOKE_INSTALL_DIR}/requirements.txt" ]]; then
        "${PIKARAOKE_INSTALL_DIR}/venv/bin/pip" install --extra-index-url https://www.piwheels.org/simple -r "${PIKARAOKE_INSTALL_DIR}/requirements.txt" || \
        "${PIKARAOKE_INSTALL_DIR}/venv/bin/pip" install -r "${PIKARAOKE_INSTALL_DIR}/requirements.txt"
    fi
fi

# ------------------------------------------------------------------------------
# 7. KaraokeZero Services Deployment
# ------------------------------------------------------------------------------
log_info "Installing KaraokeZero appliance services into ${KARAOKEZERO_INSTALL_DIR}..."

if [[ "${DRY_RUN}" != "true" ]]; then
    mkdir -p "${KARAOKEZERO_INSTALL_DIR}"
    cp -r "${PROJECT_ROOT}/wifi_manager" "${KARAOKEZERO_INSTALL_DIR}/"
    cp -r "${PROJECT_ROOT}/orchestrator" "${KARAOKEZERO_INSTALL_DIR}/"
    chmod +x "${KARAOKEZERO_INSTALL_DIR}/wifi_manager/app.py"
    chmod +x "${KARAOKEZERO_INSTALL_DIR}/orchestrator/orchestrator.py"
    chown -R "${APP_USER}:${APP_USER}" "${KARAOKEZERO_INSTALL_DIR}" "${PIKARAOKE_INSTALL_DIR}" 2>/dev/null || true
fi

# ------------------------------------------------------------------------------
# 8. Firmware & Hardware Tuning (/boot/firmware/config.txt & /boot/firmware/cmdline.txt)
# ------------------------------------------------------------------------------
if [[ "${CONFIGURE_BOOT_CONFIG}" == "true" && "${DRY_RUN}" != "true" ]]; then
    # Bookworm standardizes on /boot/firmware, with legacy fallback to /boot
    BOOT_CONFIG="/boot/firmware/config.txt"
    [[ ! -f "${BOOT_CONFIG}" && -f "/boot/config.txt" ]] && BOOT_CONFIG="/boot/config.txt"

    if [[ -f "${BOOT_CONFIG}" ]]; then
        log_info "Applying hardware tuning in ${BOOT_CONFIG}..."

        # KMS/DRM GPU memory allocation (128MB for smooth hardware decoding)
        if ! grep -q "^gpu_mem=" "${BOOT_CONFIG}"; then
            echo "gpu_mem=128" >> "${BOOT_CONFIG}"
        else
            sed -i 's/^gpu_mem=.*/gpu_mem=128/' "${BOOT_CONFIG}"
        fi

        # Force HDMI audio drive (mode 2) for Mini-HDMI adapter 3.5mm P2 audio out
        if ! grep -q "^hdmi_drive=2" "${BOOT_CONFIG}"; then
            echo "hdmi_drive=2" >> "${BOOT_CONFIG}"
        fi
    fi
fi

if [[ "${SUPPRESS_FB_CURSOR}" == "true" && "${DRY_RUN}" != "true" ]]; then
    BOOT_CMDLINE="/boot/firmware/cmdline.txt"
    [[ ! -f "${BOOT_CMDLINE}" && -f "/boot/cmdline.txt" ]] && BOOT_CMDLINE="/boot/cmdline.txt"

    if [[ -f "${BOOT_CMDLINE}" ]]; then
        if ! grep -q "vt.global_cursor_default=0" "${BOOT_CMDLINE}"; then
            log_info "Disabling blinking console cursor on framebuffer..."
            sed -i '$ s/$/ consoleblank=0 vt.global_cursor_default=0/' "${BOOT_CMDLINE}"
        fi
    fi
fi

# ------------------------------------------------------------------------------
# 9. Fallback & Active Network Provisioning (NetworkManager Keyfiles)
# ------------------------------------------------------------------------------
if [[ "${DRY_RUN}" != "true" ]]; then
    NM_DIR="/etc/NetworkManager/system-connections"
    mkdir -p "${NM_DIR}"

    # 9.1 Provision Fallback Admin Hotspot (Priority 100)
    if [[ -n "${ADMIN_WIFI_SSID}" ]]; then
        log_info "Provisioning fallback Wi-Fi network '${ADMIN_WIFI_SSID}' (Priority 100)..."
        NM_FILE="${NM_DIR}/${ADMIN_WIFI_SSID}.nmconnection"
        UUID_VAL=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "c3d1f456-789a-4bc1-9def-0123456789ab")

        cat << EOF > "${NM_FILE}"
[connection]
id=${ADMIN_WIFI_SSID}
uuid=${UUID_VAL}
type=wifi
interface-name=wlan0
autoconnect=true
autoconnect-priority=100

[wifi]
mode=infrastructure
ssid=${ADMIN_WIFI_SSID}

EOF
        if [[ -n "${ADMIN_WIFI_PASSWORD}" ]]; then
            cat << EOF >> "${NM_FILE}"
[wifi-security]
key-mgmt=wpa-psk
psk=${ADMIN_WIFI_PASSWORD}

EOF
        fi

        cat << EOF >> "${NM_FILE}"
[ipv4]
method=auto

[ipv6]
method=auto
EOF
        chmod 600 "${NM_FILE}"
        chown root:root "${NM_FILE}" 2>/dev/null || true
        log_success "Saved NetworkManager profile for '${ADMIN_WIFI_SSID}' (Priority 100)."
    fi

    # 9.2 Migrate existing active Wi-Fi from wpa_supplicant as Venue/Home network (Priority 50)
    WPA_CONF="/etc/wpa_supplicant/wpa_supplicant.conf"
    if [[ -f "${WPA_CONF}" ]]; then
        EXISTING_SSID=$(grep -E '^\s*ssid=' "${WPA_CONF}" 2>/dev/null | head -n 1 | cut -d'"' -f2 || true)
        EXISTING_PSK=$(grep -E '^\s*psk=' "${WPA_CONF}" 2>/dev/null | head -n 1 | cut -d'"' -f2 || true)

        if [[ -n "${EXISTING_SSID}" && "${EXISTING_SSID}" != "${ADMIN_WIFI_SSID:-}" ]]; then
            log_info "Migrating current active Wi-Fi '${EXISTING_SSID}' to NetworkManager (Priority 50)..."
            EXISTING_FILE="${NM_DIR}/${EXISTING_SSID}.nmconnection"
            EXISTING_UUID=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "e4f5a678-90ab-4cde-8123-456789abcdef")

            cat << EOF > "${EXISTING_FILE}"
[connection]
id=${EXISTING_SSID}
uuid=${EXISTING_UUID}
type=wifi
interface-name=wlan0
autoconnect=true
autoconnect-priority=50

[wifi]
mode=infrastructure
ssid=${EXISTING_SSID}

EOF
            if [[ -n "${EXISTING_PSK}" ]]; then
                cat << EOF >> "${EXISTING_FILE}"
[wifi-security]
key-mgmt=wpa-psk
psk=${EXISTING_PSK}

EOF
            fi

            cat << EOF >> "${EXISTING_FILE}"
[ipv4]
method=auto

[ipv6]
method=auto
EOF
            chmod 600 "${EXISTING_FILE}"
            chown root:root "${EXISTING_FILE}" 2>/dev/null || true
            log_success "Saved NetworkManager profile for current network '${EXISTING_SSID}' (Priority 50)."
        fi
    fi
fi

# ------------------------------------------------------------------------------
# 10. Systemd Services Setup
# ------------------------------------------------------------------------------
log_info "Registering systemd services..."

if [[ "${DRY_RUN}" != "true" ]]; then
    # WiFi Manager Service (runs as root to manage NetworkManager keyfiles)
    cp "${PROJECT_ROOT}/systemd/wifi_manager.service" /etc/systemd/system/

    # Ensure persistent data directory and link ~/.pikaraoke to DATA_DIR for SQLite storage
    mkdir -p "${DATA_DIR}" "${SONGS_DIR}" "${MEDIA_DIR}"
    chown -R "${APP_USER}:${APP_USER}" "${DATA_DIR}" "${SONGS_DIR}" "${MEDIA_DIR}" 2>/dev/null || true

    for TARGET_HOME in "/root" "${APP_HOME}"; do
        if [[ -d "${TARGET_HOME}" ]]; then
            PIKARAOKE_HOME_DIR="${TARGET_HOME}/.pikaraoke"
            if [[ -L "${PIKARAOKE_HOME_DIR}" ]]; then
                rm -f "${PIKARAOKE_HOME_DIR}"
            elif [[ -d "${PIKARAOKE_HOME_DIR}" ]]; then
                cp -rn "${PIKARAOKE_HOME_DIR}/"* "${DATA_DIR}/" 2>/dev/null || true
                rm -rf "${PIKARAOKE_HOME_DIR}"
            fi
            ln -sf "${DATA_DIR}" "${PIKARAOKE_HOME_DIR}"
            chown -h "${APP_USER}:${APP_USER}" "${PIKARAOKE_HOME_DIR}" 2>/dev/null || true
        fi
    done

    # Orchestrator Service (Runs as APP_USER to enable direct DRM/KMS hardware playback via VLC)
    cat << EOF > /etc/systemd/system/orchestrator.service
[Unit]
Description=KaraokeZero Display & Queue Orchestrator Daemon
RequiresMountsFor=${MOUNT_POINT}
After=local-fs.target network.target NetworkManager.service pikaraoke.service
Wants=pikaraoke.service

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
SupplementaryGroups=video audio render input
WorkingDirectory=${KARAOKEZERO_INSTALL_DIR}/orchestrator
ExecStart=/usr/bin/python3 ${KARAOKEZERO_INSTALL_DIR}/orchestrator/orchestrator.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=PIKARAOKE_URL=http://127.0.0.1:${PIKARAOKE_PORT}
Environment=VLC_VOUT=drm
Environment=VLC_AOUT=alsa
Environment=ALSA_DEVICE=default
Environment=HOME=%h

[Install]
WantedBy=multi-user.target
EOF

    # PiKaraoke Core Service (Runs as APP_USER with strict mount dependency on the external drive)
    cat << EOF > /etc/systemd/system/pikaraoke.service
[Unit]
Description=PiKaraoke Core Headless Background Service
RequiresMountsFor=${MOUNT_POINT}
After=local-fs.target network.target NetworkManager.service
Wants=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_USER}
SupplementaryGroups=video audio render input
WorkingDirectory=${PIKARAOKE_INSTALL_DIR}
ExecStart=${PIKARAOKE_INSTALL_DIR}/venv/bin/python -m pikaraoke.app \\
    --headless \\
    --port ${PIKARAOKE_PORT} \\
    --download-path ${SONGS_DIR} \\
    --config-file-path ${DATA_DIR}/config.ini
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1
Environment=HOME=%h
KillMode=mixed
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    log_info "Enabling KaraokeZero services for auto-start on boot..."
    systemctl enable wifi_manager.service pikaraoke.service orchestrator.service
fi

echo ""
echo -e "${GREEN}${BOLD}===================================================================${RESET}"
echo -e "${GREEN}${BOLD}KaraokeZero Appliance Provisioning Complete!${RESET}"
echo -e "${GREEN}${BOLD}===================================================================${RESET}"
echo -e "  • ${BOLD}PiKaraoke Web App:${RESET}        http://<pi-ip>:${PIKARAOKE_PORT}"
echo -e "  • ${BOLD}Captive Wi-Fi Portal:${RESET}     http://<pi-ip>:${WIFI_MANAGER_PORT}"
echo -e "  • ${BOLD}Song Library Directory:${RESET}   ${SONGS_DIR}"
echo -e "  • ${BOLD}Persistent Data Storage:${RESET}  ${DATA_DIR}"
echo -e "  • ${BOLD}Display Engine:${RESET}           cvlc (Direct Rendering Manager / KMS via --vout drm)"
echo -e "  • ${BOLD}Installation Log:${RESET}         ${LOG_FILE}"
echo -e "${GREEN}${BOLD}===================================================================${RESET}"
echo ""
if [[ "${CONFIGURE_BOOT_CONFIG}" == "true" ]]; then
    echo -e "${YELLOW}Note: Firmware and GPU allocation adjustments require a system reboot.${RESET}"
    echo -e "To reboot now, execute: ${BOLD}sudo reboot${RESET}"
fi
