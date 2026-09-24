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

echo "==================================================================="
echo "Running KaraokeZero Installer Test Suite"
echo "==================================================================="

run_test "Bash syntax check" test_syntax
run_test "CLI --help flag" test_help
run_test "Unattended dry run (config.env.example)" test_unattended_dry_run
run_test "Non-interactive incomplete config check" test_non_interactive_failure
run_test "Interactive external HD input simulation" test_interactive_external_hd
run_test "Interactive internal SD card input simulation" test_interactive_sd_card
run_test "Clean single log file generation" test_log_generation_and_freshness

echo "==================================================================="
if [[ "${FAILED}" -eq 0 ]]; then
    echo "All tests passed successfully!"
    exit 0
else
    echo "${FAILED} test(s) failed."
    exit 1
fi
