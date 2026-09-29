#!/usr/bin/env bash
# ==============================================================================
# Unit & Integration Tests for KaraokeZero Module 3 (Installer & Provisioning)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INSTALLER="${PROJECT_ROOT}/install.sh"
CONFIG_EXAMPLE="${PROJECT_ROOT}/config.env.example"
CONFIG_BASE="${PROJECT_ROOT}/config.env"

FAILED=0

run_test() {
    local test_name="$1"
    shift
    echo -n "Running: ${test_name}... "
    if "$@"; then
        echo "PASSED"
    else
        echo "FAILED"
        FAILED=$((FAILED + 1))
    fi
}

# Test 1: Bash Syntax Validation
test_syntax() {
    bash -n "${INSTALLER}"
}

# Test 2: Help Flag Output
test_help() {
    bash "${INSTALLER}" --help >/dev/null 2>&1
}

# Test 3: Fully Populated Unattended Dry Run
test_unattended_dry_run() {
    local out
    out=$(bash "${INSTALLER}" --dry-run --config "${CONFIG_EXAMPLE}")
    echo "${out}" | grep -q "Storage target: External Drive" && \
    echo "${out}" | grep -q "Provisioning Complete"
}

# Test 4: Incomplete Config with Non-Interactive Flag Must Fail
test_non_interactive_failure() {
    # config.env has empty STORAGE_TYPE, so --non-interactive must exit with non-zero
    if bash "${INSTALLER}" --dry-run --non-interactive --config "${CONFIG_BASE}" >/dev/null 2>&1; then
        return 1
    else
        return 0
    fi
}

# Test 5: Interactive External HD Choice Simulation
test_interactive_external_hd() {
    local out
    out=$(printf "1\n/dev/sdb1\nTestSSID\nTestPassword\n" | bash "${INSTALLER}" --dry-run --config "${CONFIG_BASE}")
    echo "${out}" | grep -q "STORAGE NOTICE" && \
    echo "${out}" | grep -q "Storage target: External Drive (/dev/sdb1)" && \
    echo "${out}" | grep -q "Provisioning Complete"
}

# Test 6: Interactive Internal SD Card Choice Simulation
test_interactive_sd_card() {
    local out
    out=$(printf "2\n/custom/sd/path\nTestSSID\nTestPassword\n" | bash "${INSTALLER}" --dry-run --config "${CONFIG_BASE}")
    echo "${out}" | grep -q "Storage target: Internal MicroSD Card at /custom/sd/path" && \
    echo "${out}" | grep -q "Provisioning Complete"
}

# Test 7: Clean Log File Generation (Single log file, overwritten on each run)
test_log_generation_and_freshness() {
    local log_file="${PROJECT_ROOT}/install.log"
    rm -f "${log_file}"

    # Verify --help does not generate log
    bash "${INSTALLER}" --help >/dev/null 2>&1
    if [[ -f "${log_file}" ]]; then
        echo "Help flag unexpectedly created log file"
        return 1
    fi

    # First dry run execution
    bash "${INSTALLER}" --dry-run --config "${CONFIG_EXAMPLE}" >/dev/null
    [[ -f "${log_file}" ]] || return 1
    grep -q "KaraokeZero Appliance - Automated Provisioning Engine" "${log_file}" || return 1
    grep -q "Provisioning Complete" "${log_file}" || return 1

    local first_run_lines
    first_run_lines=$(wc -l < "${log_file}")

    # Second execution: verify the log is freshly truncated/overwritten and not duplicated
    bash "${INSTALLER}" --dry-run --config "${CONFIG_EXAMPLE}" >/dev/null
    local second_run_lines
    second_run_lines=$(wc -l < "${log_file}")

    [[ "${first_run_lines}" -eq "${second_run_lines}" ]] || return 1
    local banners
    banners=$(grep -c "KaraokeZero Appliance - Automated Provisioning Engine" "${log_file}")
    [[ "${banners}" -eq 1 ]] || return 1

    # Cleanup log created during tests
    rm -f "${log_file}"
}

# Test 8: Reinstallation & Legacy Services Cleanup Logic
test_reinstall_cleanup_logic() {
    # Verify installer script contains teardown for obsolete wifi_manager service
    grep -q "systemctl stop wifi_manager.service" "${INSTALLER}" || return 1
    grep -q "systemctl disable wifi_manager.service" "${INSTALLER}" || return 1
    grep -q "rm -f /etc/systemd/system/wifi_manager.service" "${INSTALLER}" || return 1

    # Verify installer purges previous files while preserving configs
    grep -q "Purging previous installation files" "${INSTALLER}" || return 1
    grep -q "rm -rf \"\${KARAOKEZERO_INSTALL_DIR}\"" "${INSTALLER}" || return 1
    grep -q "CFG_BACKUP_DIR" "${INSTALLER}" || return 1

    # Verify immediate service startup check
    grep -q "systemctl restart admin_panel.service" "${INSTALLER}" || return 1
}

# Test 9: Early Service & Player Halting for 100% CPU Reclaim
test_early_service_halt() {
    # Verify installer stops services and kills processes before package installation
    grep -q "Halting all active and legacy KaraokeZero & PiKaraoke services to free CPU/RAM" "${INSTALLER}" || return 1
    grep -q 'pkill -9 -f "mpv"' "${INSTALLER}" || return 1
    grep -q 'pkill -9 -f "pikaraoke"' "${INSTALLER}" || return 1
    grep -q 'pkill -9 -f "orchestrator.py"' "${INSTALLER}" || return 1
}

# Test 10: Updater Bash Syntax & Help Flag
test_updater_basics() {
    local updater="${PROJECT_ROOT}/update.sh"
    [[ -x "${updater}" ]] || return 1
    bash -n "${updater}" || return 1
    bash "${updater}" --help | grep -q "KaraokeZero Fast Lightweight Updater" || return 1
}

# Test 11: Updater Pre-requisite Validation (Fails if not installed)
test_updater_validation_missing_install() {
    local updater="${PROJECT_ROOT}/update.sh"
    local out
    # 1. Non-existent directory must fail with exit code 1
    if out=$(bash "${updater}" --dry-run --target-dir "/tmp/nonexistent_kz_test_$$" 2>&1); then
        return 1
    fi
    echo "${out}" | grep -q "KaraokeZero installation not found" || return 1
    echo "${out}" | grep -q "install.sh" || return 1

    # 2. Empty directory must fail with exit code 1
    local empty_dir
    empty_dir=$(mktemp -d /tmp/kz_empty_test.XXXXXX)
    local empty_res=0
    if out=$(bash "${updater}" --dry-run --target-dir "${empty_dir}" 2>&1); then
        empty_res=1
    fi
    rm -rf "${empty_dir}"
    [[ ${empty_res} -eq 0 ]] || return 1
    echo "${out}" | grep -q "contains no valid KaraokeZero installation" || return 1
}

# Test 12: Updater Dry-Run Success on Existing Installation
test_updater_dry_run_success() {
    local updater="${PROJECT_ROOT}/update.sh"
    local test_dir
    test_dir=$(mktemp -d /tmp/kz_installed_test.XXXXXX)
    mkdir -p "${test_dir}/admin_panel" "${test_dir}/orchestrator"

    local out
    local res=0
    if ! out=$(bash "${updater}" --dry-run --target-dir "${test_dir}" 2>&1); then
        res=1
    fi
    rm -rf "${test_dir}"
    [[ ${res} -eq 0 ]] || return 1
    echo "${out}" | grep -q "Existing installation verified successfully" || return 1
    echo "${out}" | grep -q "KaraokeZero Update Complete" || return 1
}

echo "==================================================================="
echo "Running KaraokeZero Installer & Updater Test Suite"
echo "==================================================================="

run_test "Bash syntax check" test_syntax
run_test "CLI --help flag" test_help
run_test "Unattended dry run (config.env.example)" test_unattended_dry_run
run_test "Non-interactive incomplete config check" test_non_interactive_failure
run_test "Interactive external HD input simulation" test_interactive_external_hd
run_test "Interactive internal SD card input simulation" test_interactive_sd_card
run_test "Clean single log file generation" test_log_generation_and_freshness
run_test "Reinstallation & legacy cleanup validation" test_reinstall_cleanup_logic
run_test "Early service and player halt validation" test_early_service_halt
run_test "Updater syntax & CLI options" test_updater_basics
run_test "Updater prior-installation requirement check" test_updater_validation_missing_install
run_test "Updater dry-run execution on installed system" test_updater_dry_run_success

echo "==================================================================="
if [[ "${FAILED}" -eq 0 ]]; then
    echo "All tests passed successfully!"
    exit 0
else
    echo "${FAILED} test(s) failed."
    exit 1
fi
