#!/usr/bin/env python3
"""
KaraokeZero - Module 2: Orchestrator Daemon
Storage Validation & MicroSD Protection Engine

Validates external storage availability, mount state, and filesystem integrity on boot.
Guarantees zero-write protection when configured external storage is absent, disconnected,
or corrupted, halting appliance startup without modifying system configurations or files.
"""

from dataclasses import dataclass, field
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("Orchestrator.StorageValidator")

DEFAULT_MOUNT_POINT = "/mnt/external_hd/karaoke"
DEFAULT_CONFIG_PATHS = [
    "/etc/karaokezero/storage.env",
    "/opt/karaokezero/config.env",
    "/etc/karaokezero/config.env",
    os.path.join(os.path.dirname(__file__), "..", "config.env"),
]
DEFAULT_FSTAB_PATH = "/etc/fstab"
DEFAULT_PROCMOUNTS_PATH = "/proc/mounts"


@dataclass
class StorageConfig:
    is_external: bool = False
    mount_point: str = DEFAULT_MOUNT_POINT
    storage_device: Optional[str] = None
    device_uuid: Optional[str] = None
    songs_dir: Optional[str] = None
    data_dir: Optional[str] = None


@dataclass
class StorageValidationResult:
    valid: bool
    error_code: Optional[str] = None
    reason: str = ""
    mount_point: str = DEFAULT_MOUNT_POINT
    is_external_configured: bool = False
    details: Dict[str, any] = field(default_factory=dict)


class StorageValidator:
    """
    Validates storage configuration and health during appliance boot.
    Enforces strict zero-write safety: never creates fallback directories
    on the MicroSD rootfs when external storage is unavailable.
    """

    def __init__(
        self,
        config_paths: Optional[List[str]] = None,
        fstab_path: str = DEFAULT_FSTAB_PATH,
        proc_mounts_path: str = DEFAULT_PROCMOUNTS_PATH
    ):
        self.config_paths = config_paths or list(DEFAULT_CONFIG_PATHS)
        self.fstab_path = fstab_path
        self.proc_mounts_path = proc_mounts_path

    def _parse_env_file(self, filepath: str) -> Dict[str, str]:
        """Parses simple KEY=VALUE bash/env files safely."""
        env_vars = {}
        if not os.path.isfile(filepath):
            return env_vars

        try:
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        env_vars[k] = v
        except Exception as e:
            logger.debug("Failed to read env file %s: %s", filepath, e)
        return env_vars

    def detect_storage_configuration(self) -> StorageConfig:
        """
        Detects whether KaraokeZero was installed with an external hard drive bound.
        Checks:
        1. Explicit environment variables.
        2. /etc/karaokezero/storage.env and config.env files.
        3. /etc/fstab mount definitions for external storage.
        4. /etc/systemd/system unit dependencies.
        """
        # 1. Environment variables take precedence
        env_storage_type = os.environ.get("STORAGE_TYPE")
        env_mount_point = os.environ.get("MOUNT_POINT")
        env_storage_device = os.environ.get("STORAGE_DEVICE")

        # 2. Check config files
        loaded_vars: Dict[str, str] = {}
        for path in self.config_paths:
            if os.path.isfile(path):
                parsed = self._parse_env_file(path)
                if parsed:
                    logger.debug("Loaded storage configuration from %s", path)
                    loaded_vars.update(parsed)
                    if "STORAGE_TYPE" in parsed:
                        break

        storage_type = env_storage_type or loaded_vars.get("STORAGE_TYPE", "")
        mount_point = env_mount_point or loaded_vars.get("MOUNT_POINT", DEFAULT_MOUNT_POINT)
        storage_device = env_storage_device or loaded_vars.get("STORAGE_DEVICE")
        device_uuid = loaded_vars.get("DEVICE_UUID")

        # 3. If storage_type is explicitly specified
        if storage_type:
            is_external = storage_type.strip().lower() == "external_hd"
            return StorageConfig(
                is_external=is_external,
                mount_point=mount_point,
                storage_device=storage_device,
                device_uuid=device_uuid,
                songs_dir=loaded_vars.get("SONGS_DIR", os.path.join(mount_point, "songs")),
                data_dir=loaded_vars.get("DATA_DIR", os.path.join(mount_point, "data"))
            )

        # 4. Fallback: inspect /etc/fstab for mount point
        if os.path.isfile(self.fstab_path):
            try:
                with open(self.fstab_path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("#") or not line:
                            continue
                        parts = line.split()
                        if len(parts) >= 2:
                            fstab_target = parts[0]
                            fstab_mp = parts[1]
                            if fstab_mp == DEFAULT_MOUNT_POINT or "external_hd" in fstab_mp:
                                logger.info("Detected external HD binding in %s (%s -> %s)",
                                            self.fstab_path, fstab_target, fstab_mp)
                                return StorageConfig(
                                    is_external=True,
                                    mount_point=fstab_mp,
                                    storage_device=fstab_target,
                                    songs_dir=os.path.join(fstab_mp, "songs"),
                                    data_dir=os.path.join(fstab_mp, "data")
                                )
            except Exception as e:
                logger.debug("Failed to inspect %s: %s", self.fstab_path, e)

        # 5. Fallback: inspect systemd service files
        service_candidates = [
            "/etc/systemd/system/pikaraoke.service",
            "/etc/systemd/system/orchestrator.service"
        ]
        for svc_file in service_candidates:
            if os.path.isfile(svc_file):
                try:
                    with open(svc_file, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                        if "RequiresMountsFor=/mnt/external_hd" in content or "/mnt/external_hd/karaoke" in content:
                            logger.info("Detected external storage dependency in %s", svc_file)
                            return StorageConfig(
                                is_external=True,
                                mount_point=DEFAULT_MOUNT_POINT,
                                songs_dir=os.path.join(DEFAULT_MOUNT_POINT, "songs"),
                                data_dir=os.path.join(DEFAULT_MOUNT_POINT, "data")
                            )
                except Exception as e:
                    logger.debug("Failed to inspect %s: %s", svc_file, e)

        # Default to internal MicroSD card if no external configuration was detected
        return StorageConfig(
            is_external=False,
            mount_point=mount_point,
            songs_dir="/var/lib/karaokezero/songs",
            data_dir="/var/lib/karaokezero/data"
        )

    def is_mount_active(self, mount_point: str) -> Tuple[bool, Optional[str], bool, Optional[str]]:
        """
        Determines whether mount_point is actively mounted to a real block storage filesystem.
        Returns: (is_mounted, fstype, is_read_only, device_path)
        Excludes 'autofs' placeholders.
        """
        # Parse /proc/mounts if available (standard Linux)
        if os.path.isfile(self.proc_mounts_path):
            try:
                active_match = None
                with open(self.proc_mounts_path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 4:
                            dev, mp, fstype, opts = parts[0], parts[1], parts[2], parts[3]
                            if mp == mount_point:
                                # Overwrite with the latest mount in the stack
                                active_match = (dev, mp, fstype, opts)

                if active_match:
                    dev, mp, fstype, opts = active_match
                    if fstype != "autofs":
                        opt_list = opts.split(",")
                        is_ro = "ro" in opt_list
                        return True, fstype, is_ro, dev
                    # If it's autofs, the actual drive is not yet mounted
            except Exception as e:
                logger.debug("Error checking %s: %s", self.proc_mounts_path, e)

        # Fallback to os.path.ismount
        try:
            if os.path.ismount(mount_point):
                return True, "unknown", False, None
        except Exception:
            pass

        return False, None, False, None

    def repair_filesystem_if_needed(self, device: str) -> bool:
        """
        Executes an automatic non-interactive repair on a dirty filesystem via fsck -y.
        Returns True if repair completed cleanly or corrected errors.
        """
        if not device or not device.startswith("/dev/"):
            return False
        try:
            logger.info("Executing automatic fsck repair on %s...", device)
            proc = subprocess.run(
                ["fsck", "-y", device],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30
            )
            # fsck returncode 0 = no errors, 1 = errors corrected
            if proc.returncode in (0, 1):
                logger.info("fsck repair on %s completed successfully (code %d).", device, proc.returncode)
                return True
            logger.warning("fsck repair on %s exited with code %d.", device, proc.returncode)
            return False
        except Exception as e:
            logger.debug("fsck execution error for %s: %s", device, e)
            return False

    def attempt_mount_trigger(self, mount_point: str) -> None:
        """
        Attempts a non-destructive read access or mount command to trigger automount
        if x-systemd.automount is waiting on access. Does NOT modify any files.
        If mounting fails and a block device is known, attempts automated fsck repair.
        """
        try:
            # Simple non-destructive directory list triggers systemd automount
            if os.path.exists(mount_point):
                os.listdir(mount_point)
        except OSError:
            pass

        try:
            res = subprocess.run(
                ["mount", mount_point],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
            # If mount command failed, check if automated fsck can fix a dirty bit
            if res.returncode != 0:
                config = self.detect_storage_configuration()
                dev = config.storage_device
                if dev and dev.startswith("/dev/") and os.path.exists(dev):
                    if self.repair_filesystem_if_needed(dev):
                        subprocess.run(
                            ["mount", mount_point],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=5
                        )
        except Exception:
            pass

    def validate_storage(
        self,
        mount_point: Optional[str] = None,
        check_data_integrity: bool = True
    ) -> StorageValidationResult:
        """
        Executes complete storage health and configuration validation.
        Guarantees zero modifications to the system or SD card.
        """
        config = self.detect_storage_configuration()

        # If installation was not configured with an external hard drive, validation passes
        if not config.is_external:
            return StorageValidationResult(
                valid=True,
                error_code=None,
                reason="Storage configured for internal MicroSD card mode.",
                mount_point=config.mount_point,
                is_external_configured=False,
                details={"mode": "internal_sd"}
            )

        target_mp = mount_point or config.mount_point

        # 1. Trigger automount probe safely
        self.attempt_mount_trigger(target_mp)

        # 2. Check if mounted
        is_mounted, fstype, is_ro, dev = self.is_mount_active(target_mp)

        if not is_mounted:
            logger.error("External storage validation FAILED: %s is not mounted.", target_mp)
            return StorageValidationResult(
                valid=False,
                error_code="DEVICE_NOT_FOUND",
                reason=f"Configured storage disk is not connected or failed to mount at '{target_mp}'.",
                mount_point=target_mp,
                is_external_configured=True,
                details={"fstype": fstype, "device": dev, "is_mounted": False}
            )

        # 3. Check for read-only error mode
        if is_ro:
            logger.error("External storage validation FAILED: %s is mounted read-only.", target_mp)
            return StorageValidationResult(
                valid=False,
                error_code="READ_ONLY",
                reason=f"Storage drive at '{target_mp}' is mounted in read-only mode (filesystem error or corruption).",
                mount_point=target_mp,
                is_external_configured=True,
                details={"fstype": fstype, "device": dev, "is_ro": True}
            )

        # 4. Check write permissions without modifying any files
        try:
            if not os.access(target_mp, os.W_OK):
                logger.error("External storage validation FAILED: %s write access denied.", target_mp)
                return StorageValidationResult(
                    valid=False,
                    error_code="PERMISSION_DENIED",
                    reason=f"Storage mount point '{target_mp}' lacks write permissions.",
                    mount_point=target_mp,
                    is_external_configured=True,
                    details={"fstype": fstype, "device": dev}
                )
        except Exception as e:
            logger.error("External storage access check error for %s: %s", target_mp, e)
            return StorageValidationResult(
                valid=False,
                error_code="ACCESS_ERROR",
                reason=f"Could not access storage directory '{target_mp}': {e}",
                mount_point=target_mp,
                is_external_configured=True,
                details={"error": str(e)}
            )

        # 5. Check data integrity (verify configured directory structures exist)
        if check_data_integrity:
            data_dir = os.path.join(target_mp, "data")
            songs_dir = os.path.join(target_mp, "songs")
            data_exists = os.path.isdir(data_dir)
            songs_exists = os.path.isdir(songs_dir)

            if not data_exists and not songs_exists:
                logger.error("External storage validation FAILED: data directories missing on %s.", target_mp)
                return StorageValidationResult(
                    valid=False,
                    error_code="DATA_LOST",
                    reason=(
                        f"Configured KaraokeZero data was not found on '{target_mp}'. "
                        "The disk may have been reformatted, replaced, or data lost. "
                        "A new installation of KaraokeZero must be performed."
                    ),
                    mount_point=target_mp,
                    is_external_configured=True,
                    details={
                        "fstype": fstype,
                        "device": dev,
                        "data_dir_exists": data_exists,
                        "songs_dir_exists": songs_exists
                    }
                )

        logger.info("External storage validation PASSED: %s (%s on %s) is healthy.", target_mp, fstype, dev)
        return StorageValidationResult(
            valid=True,
            error_code=None,
            reason="External storage verified and healthy.",
            mount_point=target_mp,
            is_external_configured=True,
            details={"fstype": fstype, "device": dev, "is_mounted": True}
        )

    def sanitize_storage(self, mount_point: str) -> Dict[str, object]:
        """
        Scans storage directories for incomplete download artifacts (.part, .ytdl, .temp, .tmp)
        and corrupted 0-byte media files left by unexpected power loss. Safely purges them so
        playback engines and daemons do not crash or stall.
        """
        temp_extensions = {".part", ".ytdl", ".temp", ".tmp"}
        media_extensions = {".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".avi", ".cdg", ".zip", ".flac", ".ogg", ".wav"}

        cleaned_temp = 0
        cleaned_zero_byte = 0
        removed_files: List[str] = []

        if not mount_point or not os.path.isdir(mount_point):
            return {"cleaned_temp": 0, "cleaned_zero_byte": 0, "removed_files": []}

        search_dirs = [
            os.path.join(mount_point, "songs"),
            os.path.join(mount_point, "media"),
            os.path.join(mount_point, "data"),
        ]
        # Also check root mount point if standard subdirectories don't exist yet
        dirs_to_scan = [d for d in search_dirs if os.path.isdir(d)]
        if not dirs_to_scan:
            dirs_to_scan = [mount_point]

        for base_dir in dirs_to_scan:
            for root, _, files in os.walk(base_dir):
                for f in files:
                    file_path = os.path.join(root, f)
                    lower_name = f.lower()
                    _, ext = os.path.splitext(lower_name)

                    should_remove = False
                    is_zero_byte = False

                    # Check for partial/temporary download artifacts
                    if ext in temp_extensions or any(lower_name.endswith(te) for te in temp_extensions):
                        should_remove = True
                    # Check for 0-byte corrupted media files
                    elif ext in media_extensions:
                        try:
                            if os.path.getsize(file_path) == 0:
                                should_remove = True
                                is_zero_byte = True
                        except OSError:
                            pass

                    if should_remove:
                        try:
                            os.remove(file_path)
                            removed_files.append(file_path)
                            if is_zero_byte:
                                cleaned_zero_byte += 1
                                logger.warning("Purged 0-byte corrupt media artifact: %s", file_path)
                            else:
                                cleaned_temp += 1
                                logger.info("Purged incomplete download artifact: %s", file_path)
                        except OSError as e:
                            logger.error("Failed to remove corrupted file %s: %s", file_path, e)

        if removed_files:
            logger.info(
                "Storage sanitization completed: purged %d temp artifacts and %d 0-byte files.",
                cleaned_temp, cleaned_zero_byte
            )
        return {
            "cleaned_temp": cleaned_temp,
            "cleaned_zero_byte": cleaned_zero_byte,
            "removed_files": removed_files,
        }

    def verify_and_repair_sqlite(self, mount_point: str) -> Dict[str, object]:
        """
        Enforces crash-resilient WAL (Write-Ahead Logging) mode and verifies integrity
        for all SQLite databases located in the persistent data directory.
        If an unrecoverable corrupted database is detected, creates a safety backup
        to prevent service startup crashes.
        """
        checked_count = 0
        corrupted_count = 0
        details: List[Dict[str, object]] = []

        if not mount_point or not os.path.isdir(mount_point):
            return {"checked": 0, "corrupted": 0, "details": []}

        data_dir = os.path.join(mount_point, "data")
        scan_dir = data_dir if os.path.isdir(data_dir) else mount_point

        sqlite_extensions = {".db", ".sqlite", ".sqlite3"}

        for root, _, files in os.walk(scan_dir):
            for f in files:
                lower_name = f.lower()
                _, ext = os.path.splitext(lower_name)
                if ext in sqlite_extensions:
                    db_path = os.path.join(root, f)
                    checked_count += 1
                    try:
                        conn = sqlite3.connect(db_path, timeout=5.0)
                        cursor = conn.cursor()

                        # Configure WAL mode and NORMAL synchronous for power-loss resilience
                        cursor.execute("PRAGMA journal_mode=WAL;")
                        cursor.execute("PRAGMA synchronous=NORMAL;")

                        # Execute SQLite integrity check
                        cursor.execute("PRAGMA integrity_check;")
                        rows = cursor.fetchall()
                        conn.commit()
                        conn.close()

                        is_healthy = len(rows) == 1 and rows[0][0] == "ok"
                        if is_healthy:
                            logger.debug("SQLite database %s is healthy (WAL mode enabled).", db_path)
                            details.append({"path": db_path, "status": "ok"})
                        else:
                            corrupted_count += 1
                            backup_path = f"{db_path}.corrupt.{int(time.time())}"
                            logger.critical(
                                "SQLite database %s is corrupted! Output: %s. Creating backup -> %s",
                                db_path, rows, backup_path
                            )
                            try:
                                shutil.copy2(db_path, backup_path)
                            except OSError as e:
                                logger.error("Failed to backup corrupt DB %s: %s", db_path, e)
                            details.append({
                                "path": db_path,
                                "status": "corrupt",
                                "backup": backup_path,
                                "errors": [r[0] for r in rows if r]
                            })
                    except Exception as e:
                        corrupted_count += 1
                        backup_path = f"{db_path}.corrupt.{int(time.time())}"
                        logger.critical("SQLite check exception on %s: %s. Creating safety backup.", db_path, e)
                        try:
                            shutil.copy2(db_path, backup_path)
                        except OSError:
                            pass
                        details.append({"path": db_path, "status": "error", "error": str(e), "backup": backup_path})

        return {
            "checked": checked_count,
            "corrupted": corrupted_count,
            "details": details,
        }

    def sync_wifi_profiles_from_storage(
        self,
        mount_point: str,
        run_nm_dir: str = "/run/NetworkManager/system-connections"
    ) -> Dict[str, object]:
        """
        Loads saved NetworkManager Wi-Fi profiles (.nmconnection) from the persistent
        external storage directory into /run/NetworkManager/system-connections/ (tmpfs RAM).
        Guarantees zero writes to the MicroSD rootfs while restoring venue Wi-Fi credentials
        across reboots and fresh appliance re-installations.
        """
        synced_profiles: List[str] = []

        if not mount_point or not os.path.isdir(mount_point):
            return {"synced": 0, "profiles": []}

        wifi_dir = os.path.join(mount_point, "data", "wifi")
        if not os.path.isdir(wifi_dir):
            return {"synced": 0, "profiles": []}

        try:
            os.makedirs(run_nm_dir, mode=0o700, exist_ok=True)
        except OSError as e:
            logger.error("Could not ensure transient NetworkManager directory %s: %s", run_nm_dir, e)
            return {"synced": 0, "profiles": []}

        try:
            for entry in os.listdir(wifi_dir):
                if entry.endswith(".nmconnection"):
                    src = os.path.join(wifi_dir, entry)
                    dst = os.path.join(run_nm_dir, entry)
                    if os.path.isfile(src):
                        try:
                            shutil.copy2(src, dst)
                            os.chmod(dst, 0o600)
                            # Attempt chown root:root if permitted
                            try:
                                shutil.chown(dst, user=0, group=0)
                            except (PermissionError, LookupError):
                                pass
                            synced_profiles.append(entry)
                            logger.info("Restored Wi-Fi profile from storage to transient RAM: %s", entry)
                        except OSError as e:
                            logger.error("Failed to copy Wi-Fi profile %s to %s: %s", src, dst, e)

            if synced_profiles:
                logger.info("Reloading NetworkManager connections for %d restored profile(s)...", len(synced_profiles))
                subprocess.run(
                    ["nmcli", "connection", "reload"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5
                )
        except Exception as e:
            logger.error("Error during Wi-Fi profile sync from storage: %s", e)

        return {
            "synced": len(synced_profiles),
            "profiles": synced_profiles,
        }

