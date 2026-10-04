#!/usr/bin/env bash
# ==============================================================================
# KaraokeZero - Fast Lightweight Project Updater
# ==============================================================================
# Performs a direct, streamlined update of KaraokeZero application modules
# (admin panel, display orchestrator, systemd units, yt-dlp) without the
# overhead of a full reinstall or system package reconfiguration.
#
# Prerequisite: KaraokeZero MUST be already installed on the appliance.
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

# Default paths and options
KARAOKEZERO_INSTALL_DIR="/opt/karaokezero"
PIKARAOKE_INSTALL_DIR="/opt/pikaraoke"
LOG_FILE="${SCRIPT_DIR}/update.log"
DRY_RUN="false"
SKIP_PIKARAOKE="false"
SKIP_YTDLP="false"

usage() {
    cat << EOF
KaraokeZero Fast Lightweight Updater

Usage:
    sudo bash $(basename "$0") [OPTIONS]

Options:
    --target-dir <path>       Target KaraokeZero installation path (default: ${KARAOKEZERO_INSTALL_DIR})
    --pikaraoke-dir <path>    PiKaraoke upstream installation path (default: ${PIKARAOKE_INSTALL_DIR})
    --log <path>              Log file location (default: ${LOG_FILE})
    --skip-pikaraoke          Skip pulling latest commits from upstream PiKaraoke
    --skip-ytdlp              Skip updating yt-dlp binary
    --dry-run                 Simulate update workflow without modifying the system
    -h, --help                Show this help message

Notes:
    This script performs a fast, safe update of KaraokeZero application files,
    preserving all existing user configurations and Wi-Fi credentials.
    If KaraokeZero is not installed yet, use 'sudo bash install.sh' instead.
EOF
    exit 0
}

# Parse command line flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target-dir)
            KARAOKEZERO_INSTALL_DIR="$2"
            shift 2
            ;;
        --pikaraoke-dir)
            PIKARAOKE_INSTALL_DIR="$2"
            shift 2
            ;;
        --log)
            LOG_FILE="$2"
            shift 2
            ;;
        --skip-pikaraoke)
            SKIP_PIKARAOKE="true"
            shift
            ;;
        --skip-ytdlp)
            SKIP_YTDLP="true"
            shift
            ;;
        --dry-run)
            DRY_RUN="true"
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

# Resolve active appliance runtime user
APP_USER="${SUDO_USER:-$(id -un)}"
if [[ "${APP_USER}" == "root" && -d "/home/karaoke" ]]; then
    APP_USER="karaoke"
elif [[ "${APP_USER}" == "root" && -d "/home/pi" ]]; then
    APP_USER="pi"
fi

# ------------------------------------------------------------------------------
# 1. Permission and Root Check
# ------------------------------------------------------------------------------
if [[ "${DRY_RUN}" != "true" && "${EUID}" -ne 0 ]]; then
    log_error "This update script must be run as root (or via sudo)."
    log_error "Please execute: sudo bash $(basename "$0")"
    exit 1
fi

# ------------------------------------------------------------------------------
# 2. Strict Pre-requisite Validation: Existing Installation Required
# ------------------------------------------------------------------------------
echo ""
echo -e "${CYAN}${BOLD}===================================================================${RESET}"
echo -e "${CYAN}${BOLD}KaraokeZero Lightweight Application Updater${RESET}"
echo -e "${CYAN}${BOLD}===================================================================${RESET}"
log_info "Verifying existing installation at: ${KARAOKEZERO_INSTALL_DIR}..."

# Must exist as a directory
if [[ ! -d "${KARAOKEZERO_INSTALL_DIR}" ]]; then
    echo ""
    log_error "KaraokeZero installation not found at '${KARAOKEZERO_INSTALL_DIR}'."
    log_error "Cannot perform an update on a system that does not have KaraokeZero installed."
    echo ""
    echo -e "${YELLOW}${BOLD}To perform a full initial installation, please execute:${RESET}"
    echo -e "    ${BOLD}sudo bash ${SCRIPT_DIR}/install.sh${RESET}"
    echo ""
    exit 1
fi

# Must contain at least one installed core component or previous setup
HAS_EXISTING_COMPONENTS="false"
if [[ -d "${KARAOKEZERO_INSTALL_DIR}/admin_panel" || \
      -d "${KARAOKEZERO_INSTALL_DIR}/orchestrator" || \
      -d "${KARAOKEZERO_INSTALL_DIR}/wifi_manager" || \
      -f "${KARAOKEZERO_INSTALL_DIR}/config.env" || \
      -f "/etc/systemd/system/orchestrator.service" || \
      -f "/etc/systemd/system/admin_panel.service" ]]; then
    HAS_EXISTING_COMPONENTS="true"
fi

if [[ "${HAS_EXISTING_COMPONENTS}" != "true" ]]; then
    echo ""
    log_error "Directory '${KARAOKEZERO_INSTALL_DIR}' exists but contains no valid KaraokeZero installation."
    log_error "Cannot perform update. Please run 'sudo bash install.sh' to install the appliance first."
    echo ""
    exit 1
fi

log_success "Existing installation verified successfully."

# ------------------------------------------------------------------------------
# 3. Logging Initialization
# ------------------------------------------------------------------------------
: > "${LOG_FILE}"
chmod 644 "${LOG_FILE}" 2>/dev/null || true
if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    chown "${SUDO_USER}:" "${LOG_FILE}" 2>/dev/null || true
fi

exec 3>&1 4>&2
cleanup_logging() {
    local exit_code=$?
    if [[ ${exit_code} -ne 0 ]]; then
        echo -e "${RED}${BOLD}[ERROR] Update aborted or failed with exit code ${exit_code}.${RESET}" >&2
        echo -e "${RED}${BOLD}[ERROR] Full log available at: ${LOG_FILE}${RESET}" >&2
    fi
    exec 1>&3 2>&4 3>&- 4>&- 2>/dev/null || true
}
trap cleanup_logging EXIT INT TERM
exec > >(tee "${LOG_FILE}") 2>&1

# ------------------------------------------------------------------------------
# 4. Stop Active Services (Release CPU, Audio & DRM Plane)
# ------------------------------------------------------------------------------
log_info "Stopping active KaraokeZero services for clean code replacement..."

if [[ "${DRY_RUN}" != "true" ]]; then
    if command -v systemctl >/dev/null 2>&1; then
        systemctl stop orchestrator.service admin_panel.service pikaraoke.service wifi_manager.service 2>/dev/null || true
    fi
    pkill -f "opt/karaokezero" 2>/dev/null || true
    pkill -f "mpv" 2>/dev/null || true
    log_success "Active services stopped."
else
    log_info "[DRY-RUN] Would stop orchestrator, admin_panel, and pikaraoke services."
fi

# ------------------------------------------------------------------------------
# 5. Backup & Preserve Runtime Configurations
# ------------------------------------------------------------------------------
log_info "Preserving runtime configuration files (settings.json, config.ini, .env)..."
CFG_BACKUP_DIR=$(mktemp -d /tmp/kz_update_backup.XXXXXX)

if [[ -d "${KARAOKEZERO_INSTALL_DIR}" ]]; then
    find "${KARAOKEZERO_INSTALL_DIR}" -maxdepth 3 -type f \( -name "*.json" -o -name "*.env" -o -name "*.ini" -o -name "*.conf" \) -not -path "*/__pycache__/*" -exec cp --parents -t "${CFG_BACKUP_DIR}" {} + 2>/dev/null || true
fi

# ------------------------------------------------------------------------------
# 6. Update KaraokeZero Core Modules (admin_panel & orchestrator)
# ------------------------------------------------------------------------------
log_info "Updating application modules in ${KARAOKEZERO_INSTALL_DIR}..."

if [[ "${DRY_RUN}" != "true" ]]; then
    # Copy updated admin_panel and orchestrator modules
    mkdir -p "${KARAOKEZERO_INSTALL_DIR}"
    rm -rf "${KARAOKEZERO_INSTALL_DIR}/admin_panel" "${KARAOKEZERO_INSTALL_DIR}/orchestrator"
    cp -r "${PROJECT_ROOT}/admin_panel" "${KARAOKEZERO_INSTALL_DIR}/"
    cp -r "${PROJECT_ROOT}/orchestrator" "${KARAOKEZERO_INSTALL_DIR}/"

    # Restore preserved configurations (settings.json, custom credentials, etc.)
    if [[ -d "${CFG_BACKUP_DIR}${KARAOKEZERO_INSTALL_DIR}" ]]; then
        cp -rn "${CFG_BACKUP_DIR}${KARAOKEZERO_INSTALL_DIR}/"* "${KARAOKEZERO_INSTALL_DIR}/" 2>/dev/null || true
    fi

    # Set executable permissions
    chmod +x "${KARAOKEZERO_INSTALL_DIR}/admin_panel/app.py" 2>/dev/null || true
    chmod +x "${KARAOKEZERO_INSTALL_DIR}/orchestrator/orchestrator.py" 2>/dev/null || true

    # Fix ownership
    if id "${APP_USER}" >/dev/null 2>&1; then
        chown -R "${APP_USER}:${APP_USER}" "${KARAOKEZERO_INSTALL_DIR}" 2>/dev/null || true
    fi
    log_success "Application modules updated successfully."
else
    log_info "[DRY-RUN] Would update admin_panel and orchestrator directories and restore configurations."
fi
rm -rf "${CFG_BACKUP_DIR}"

# ------------------------------------------------------------------------------
# 7. Update Systemd Services
# ------------------------------------------------------------------------------
log_info "Updating systemd service definitions..."

if [[ "${DRY_RUN}" != "true" ]]; then
    if [[ -d "/etc/systemd/system" ]]; then
        if [[ -f "${PROJECT_ROOT}/systemd/admin_panel.service" ]]; then
            cp "${PROJECT_ROOT}/systemd/admin_panel.service" /etc/systemd/system/
        fi
        if [[ -f "${PROJECT_ROOT}/systemd/orchestrator.service" ]]; then
            cp "${PROJECT_ROOT}/systemd/orchestrator.service" /etc/systemd/system/
        fi

        # Remove obsolete wifi_manager.service if still present on system
        if [[ -f /etc/systemd/system/wifi_manager.service ]]; then
            systemctl disable wifi_manager.service 2>/dev/null || true
            rm -f /etc/systemd/system/wifi_manager.service
            rm -f /etc/systemd/system/multi-user.target.wants/wifi_manager.service
            systemctl reset-failed wifi_manager.service 2>/dev/null || true
        fi

        # Mask getty login prompt on tty1 so HDMI output stays pitch black between graphical scenes
        systemctl disable --now getty@tty1.service 2>/dev/null || true
        systemctl mask getty@tty1.service 2>/dev/null || true

        # Ensure boot configs suppress terminal text and cursor if boot files exist
        BOOT_CONFIG="/boot/firmware/config.txt"
        [[ ! -f "${BOOT_CONFIG}" && -f "/boot/config.txt" ]] && BOOT_CONFIG="/boot/config.txt"
        if [[ -f "${BOOT_CONFIG}" ]]; then
            if ! grep -q "^disable_splash=1" "${BOOT_CONFIG}"; then
                echo "disable_splash=1" >> "${BOOT_CONFIG}"
            fi
        fi

        BOOT_CMDLINE="/boot/firmware/cmdline.txt"
        [[ ! -f "${BOOT_CMDLINE}" && -f "/boot/cmdline.txt" ]] && BOOT_CMDLINE="/boot/cmdline.txt"
        if [[ -f "${BOOT_CMDLINE}" ]]; then
            sed -i 's/console=tty1/console=tty3/g' "${BOOT_CMDLINE}"
            sed -i 's/loglevel=[0-9]/loglevel=0/g' "${BOOT_CMDLINE}"
            for opt in "consoleblank=0" "vt.global_cursor_default=0" "quiet" "loglevel=0" "systemd.show_status=0" "logo.nologo" "console=tty3" "fsck.repair=yes" "fsck.mode=auto"; do
                if ! grep -q "${opt}" "${BOOT_CMDLINE}"; then
                    sed -i "$ s/$/ ${opt}/" "${BOOT_CMDLINE}"
                fi
            done
        fi

        # Configure volatile journald logging to protect MicroSD from wear (Zero-Write Rootfs)
        if [[ -f /etc/systemd/journald.conf ]]; then
            if ! grep -q "^Storage=volatile" /etc/systemd/journald.conf; then
                sed -i 's/^#\?Storage=.*/Storage=volatile/' /etc/systemd/journald.conf
            fi
            if ! grep -q "^RuntimeMaxUse=" /etc/systemd/journald.conf; then
                echo "RuntimeMaxUse=16M" >> /etc/systemd/journald.conf
            else
                sed -i 's/^#\?RuntimeMaxUse=.*/RuntimeMaxUse=16M/' /etc/systemd/journald.conf
            fi
            systemctl restart systemd-journald 2>/dev/null || true
        fi

        # Disable disk-based logging daemons (rsyslog, logrotate) and mount /var/log as tmpfs
        systemctl disable --now rsyslog.service logrotate.timer logrotate.service 2>/dev/null || true
        systemctl mask rsyslog.service logrotate.timer logrotate.service 2>/dev/null || true
        rm -rf /var/log/journal 2>/dev/null || true

        if [[ -f /etc/fstab ]] && ! grep -qs "^tmpfs[[:space:]]\+/var/log" /etc/fstab; then
            echo "tmpfs /var/log tmpfs defaults,noatime,nosuid,nodev,mode=0755,size=16M 0 0" >> /etc/fstab
        fi

        # Disable automatic background updates and indexing services
        systemctl disable --now apt-daily.timer apt-daily.service apt-daily-upgrade.timer apt-daily-upgrade.service unattended-upgrades.service packagekit.service man-db.timer man-db.service e2scrub_all.timer 2>/dev/null || true
        systemctl mask apt-daily.timer apt-daily.service apt-daily-upgrade.timer apt-daily-upgrade.service unattended-upgrades.service packagekit.service man-db.timer man-db.service e2scrub_all.timer 2>/dev/null || true

        # Disable cloud-init if installed (prevents 2+ minute boot stalls, socket interaction messages, and console spam)
        if command -v cloud-init >/dev/null 2>&1 || [[ -d /etc/cloud ]]; then
            log_info "Disabling cloud-init to eliminate boot stalls and console spam..."
            mkdir -p /etc/cloud
            touch /etc/cloud/cloud-init.disabled
            systemctl disable --now cloud-init.service cloud-init-local.service cloud-config.service cloud-final.service 2>/dev/null || true
            systemctl mask cloud-init.service cloud-init-local.service cloud-config.service cloud-final.service 2>/dev/null || true
        fi

        if [[ -d /etc/apt/apt.conf.d ]]; then
            cat << EOF > /etc/apt/apt.conf.d/20auto-upgrades
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Download-Upgradeable-Packages "0";
APT::Periodic::AutocleanInterval "0";
APT::Periodic::Unattended-Upgrade "0";
EOF
        fi

        # Disable swap paging on flash storage
        if command -v dphys-swapfile >/dev/null 2>&1; then
            dphys-swapfile swapoff 2>/dev/null || true
            systemctl disable dphys-swapfile 2>/dev/null || true
        fi

        # Tune rootfs in /etc/fstab for flash protection
        if [[ -f /etc/fstab ]] && grep -qE '[[:space:]]/[[:space:]]' /etc/fstab; then
            awk '{
                if ($2 == "/" && $3 ~ /^(ext4|ext3|f2fs)$/) {
                    if ($4 !~ /commit=60/) { $4 = $4 ",commit=60" }
                    if ($4 !~ /noatime/) { $4 = $4 ",noatime" }
                    if ($4 !~ /errors=remount-ro/) { $4 = $4 ",errors=remount-ro" }
                }
                print $0
            }' /etc/fstab > /tmp/fstab.tmp 2>/dev/null && mv /tmp/fstab.tmp /etc/fstab || true
        fi

        systemctl daemon-reload
        systemctl enable admin_panel.service orchestrator.service pikaraoke.service 2>/dev/null || true
        log_success "Systemd services and display settings updated and reloaded."
    fi
else
    log_info "[DRY-RUN] Would update systemd service unit files, mask getty@tty1, tune console cmdline, and execute daemon-reload."
fi

# ------------------------------------------------------------------------------
# 8. Update yt-dlp Binary
# ------------------------------------------------------------------------------
if [[ "${SKIP_YTDLP}" != "true" ]]; then
    log_info "Checking for yt-dlp binary updates..."
    if [[ "${DRY_RUN}" != "true" ]]; then
        if curl -sL --max-time 15 https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp.tmp; then
            mv /usr/local/bin/yt-dlp.tmp /usr/local/bin/yt-dlp
            chmod a+rx /usr/local/bin/yt-dlp
            log_success "yt-dlp binary updated."
        else
            log_warn "Could not reach GitHub for yt-dlp update (offline or timeout). Keeping current binary."
            rm -f /usr/local/bin/yt-dlp.tmp
        fi
    else
        log_info "[DRY-RUN] Would download latest yt-dlp binary to /usr/local/bin/yt-dlp."
    fi
fi

# ------------------------------------------------------------------------------
# 9. Update Upstream PiKaraoke (if repository clone is present)
# ------------------------------------------------------------------------------
if [[ "${SKIP_PIKARAOKE}" != "true" ]]; then
    if [[ -d "${PIKARAOKE_INSTALL_DIR}/.git" ]]; then
        log_info "Pulling latest upstream PiKaraoke commits..."
        if [[ "${DRY_RUN}" != "true" ]]; then
            git -C "${PIKARAOKE_INSTALL_DIR}" fetch origin master 2>/dev/null || true
            git -C "${PIKARAOKE_INSTALL_DIR}" checkout master 2>/dev/null || true
            git -C "${PIKARAOKE_INSTALL_DIR}" pull --ff-only origin master 2>/dev/null || true
            log_success "PiKaraoke repository updated."
        else
            log_info "[DRY-RUN] Would pull latest commits from PiKaraoke master branch."
        fi
    fi
fi

# ------------------------------------------------------------------------------
# 10. Restart Services
# ------------------------------------------------------------------------------
log_info "Starting updated KaraokeZero appliance services..."

if [[ "${DRY_RUN}" != "true" ]]; then
    if command -v systemctl >/dev/null 2>&1; then
        systemctl restart admin_panel.service pikaraoke.service orchestrator.service 2>/dev/null || true
    fi
    log_success "Appliance services restarted."
else
    log_info "[DRY-RUN] Would restart admin_panel, pikaraoke, and orchestrator services."
fi

echo ""
echo -e "${GREEN}${BOLD}===================================================================${RESET}"
echo -e "${GREEN}${BOLD}KaraokeZero Update Complete!${RESET}"
echo -e "${GREEN}${BOLD}===================================================================${RESET}"
echo -e "  • ${BOLD}Installation Target:${RESET}  ${KARAOKEZERO_INSTALL_DIR}"
echo -e "  • ${BOLD}Admin Panel:${RESET}          Updated"
echo -e "  • ${BOLD}Orchestrator:${RESET}         Updated"
echo -e "  • ${BOLD}Update Log:${RESET}           ${LOG_FILE}"
echo -e "${GREEN}${BOLD}===================================================================${RESET}"
echo ""
