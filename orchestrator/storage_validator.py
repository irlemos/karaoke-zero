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
import subprocess
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

    def attempt_mount_trigger(self, mount_point: str) -> None:
        """
        Attempts a non-destructive read access or mount command to trigger automount
        if x-systemd.automount is waiting on access. Does NOT modify any files.
        """
        try:
            # Simple non-destructive directory list triggers systemd automount
            if os.path.exists(mount_point):
                os.listdir(mount_point)
        except OSError:
            pass

        try:
            subprocess.run(
                ["mount", mount_point],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3
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
