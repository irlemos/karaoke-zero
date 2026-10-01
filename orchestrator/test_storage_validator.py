#!/usr/bin/env python3
"""
Unit tests for KaraokeZero Storage Validation & MicroSD Protection Engine
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, os.path.dirname(__file__))
from storage_validator import StorageValidator, StorageConfig, StorageValidationResult


class TestStorageValidator(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.mount_point = os.path.join(self.temp_dir.name, "mnt_external_hd")
        os.makedirs(self.mount_point, exist_ok=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_env_file(self):
        env_file = os.path.join(self.temp_dir.name, "test.env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("# Comment line\n")
            f.write("STORAGE_TYPE=\"external_hd\"\n")
            f.write("STORAGE_DEVICE='/dev/sdb1'\n")
            f.write("MOUNT_POINT=/mnt/external_hd/karaoke\n")

        validator = StorageValidator()
        parsed = validator._parse_env_file(env_file)
        self.assertEqual(parsed.get("STORAGE_TYPE"), "external_hd")
        self.assertEqual(parsed.get("STORAGE_DEVICE"), "/dev/sdb1")
        self.assertEqual(parsed.get("MOUNT_POINT"), "/mnt/external_hd/karaoke")

    def test_detect_external_storage_from_config_file(self):
        env_file = os.path.join(self.temp_dir.name, "storage.env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("STORAGE_TYPE=external_hd\n")
            f.write("STORAGE_DEVICE=/dev/sda1\n")
            f.write(f"MOUNT_POINT={self.mount_point}\n")

        validator = StorageValidator(config_paths=[env_file], fstab_path="/nonexistent/fstab")
        config = validator.detect_storage_configuration()
        self.assertTrue(config.is_external)
        self.assertEqual(config.mount_point, self.mount_point)
        self.assertEqual(config.storage_device, "/dev/sda1")

    def test_detect_sd_card_storage_from_config_file(self):
        env_file = os.path.join(self.temp_dir.name, "storage.env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("STORAGE_TYPE=sd_card\n")

        validator = StorageValidator(config_paths=[env_file], fstab_path="/nonexistent/fstab")
        config = validator.detect_storage_configuration()
        self.assertFalse(config.is_external)

    def test_detect_external_storage_from_fstab_fallback(self):
        fstab_file = os.path.join(self.temp_dir.name, "fstab")
        with open(fstab_file, "w", encoding="utf-8") as f:
            f.write("/dev/sda1 /mnt/external_hd/karaoke auto defaults,nofail 0 2\n")

        validator = StorageValidator(config_paths=["/nonexistent/env"], fstab_path=fstab_file)
        config = validator.detect_storage_configuration()
        self.assertTrue(config.is_external)
        self.assertEqual(config.mount_point, "/mnt/external_hd/karaoke")
        self.assertEqual(config.storage_device, "/dev/sda1")

    def test_is_mount_active_real_filesystem(self):
        proc_mounts = os.path.join(self.temp_dir.name, "proc_mounts")
        with open(proc_mounts, "w", encoding="utf-8") as f:
            f.write(f"/dev/sda1 {self.mount_point} ext4 rw,relatime 0 0\n")

        validator = StorageValidator(proc_mounts_path=proc_mounts)
        is_mounted, fstype, is_ro, dev = validator.is_mount_active(self.mount_point)
        self.assertTrue(is_mounted)
        self.assertEqual(fstype, "ext4")
        self.assertFalse(is_ro)
        self.assertEqual(dev, "/dev/sda1")

    def test_is_mount_active_autofs_not_real_mount(self):
        proc_mounts = os.path.join(self.temp_dir.name, "proc_mounts")
        with open(proc_mounts, "w", encoding="utf-8") as f:
            f.write(f"systemd-1 {self.mount_point} autofs rw,relatime,fd=28,pgrp=1 0 0\n")

        validator = StorageValidator(proc_mounts_path=proc_mounts)
        is_mounted, fstype, is_ro, dev = validator.is_mount_active(self.mount_point)
        self.assertFalse(is_mounted)

    def test_is_mount_active_read_only(self):
        proc_mounts = os.path.join(self.temp_dir.name, "proc_mounts")
        with open(proc_mounts, "w", encoding="utf-8") as f:
            f.write(f"/dev/sda1 {self.mount_point} ext4 ro,relatime 0 0\n")

        validator = StorageValidator(proc_mounts_path=proc_mounts)
        is_mounted, fstype, is_ro, dev = validator.is_mount_active(self.mount_point)
        self.assertTrue(is_mounted)
        self.assertTrue(is_ro)

    def test_validate_storage_success(self):
        # Setup data and songs folders inside mount point
        os.makedirs(os.path.join(self.mount_point, "data"), exist_ok=True)
        os.makedirs(os.path.join(self.mount_point, "songs"), exist_ok=True)

        env_file = os.path.join(self.temp_dir.name, "storage.env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("STORAGE_TYPE=external_hd\n")
            f.write(f"MOUNT_POINT={self.mount_point}\n")

        proc_mounts = os.path.join(self.temp_dir.name, "proc_mounts")
        with open(proc_mounts, "w", encoding="utf-8") as f:
            f.write(f"/dev/sda1 {self.mount_point} ext4 rw,relatime 0 0\n")

        validator = StorageValidator(config_paths=[env_file], proc_mounts_path=proc_mounts)
        result = validator.validate_storage()
        self.assertTrue(result.valid)
        self.assertIsNone(result.error_code)
        self.assertEqual(result.mount_point, self.mount_point)

    def test_validate_storage_not_mounted(self):
        env_file = os.path.join(self.temp_dir.name, "storage.env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("STORAGE_TYPE=external_hd\n")
            f.write(f"MOUNT_POINT={self.mount_point}\n")

        proc_mounts = os.path.join(self.temp_dir.name, "proc_mounts")
        with open(proc_mounts, "w", encoding="utf-8") as f:
            f.write("/dev/mmcblk0p2 / ext4 rw,relatime 0 0\n")

        validator = StorageValidator(config_paths=[env_file], proc_mounts_path=proc_mounts)
        with patch.object(validator, "attempt_mount_trigger"):
            result = validator.validate_storage()
            self.assertFalse(result.valid)
            self.assertEqual(result.error_code, "DEVICE_NOT_FOUND")
            self.assertIn("not connected or failed to mount", result.reason)

    def test_validate_storage_read_only_error(self):
        env_file = os.path.join(self.temp_dir.name, "storage.env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("STORAGE_TYPE=external_hd\n")
            f.write(f"MOUNT_POINT={self.mount_point}\n")

        proc_mounts = os.path.join(self.temp_dir.name, "proc_mounts")
        with open(proc_mounts, "w", encoding="utf-8") as f:
            f.write(f"/dev/sda1 {self.mount_point} ext4 ro,relatime 0 0\n")

        validator = StorageValidator(config_paths=[env_file], proc_mounts_path=proc_mounts)
        with patch.object(validator, "attempt_mount_trigger"):
            result = validator.validate_storage()
            self.assertFalse(result.valid)
            self.assertEqual(result.error_code, "READ_ONLY")
            self.assertIn("read-only mode", result.reason)

    def test_validate_storage_data_lost(self):
        # Mount is rw, but neither data/ nor songs/ directory exists (empty/wiped drive)
        env_file = os.path.join(self.temp_dir.name, "storage.env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("STORAGE_TYPE=external_hd\n")
            f.write(f"MOUNT_POINT={self.mount_point}\n")

        proc_mounts = os.path.join(self.temp_dir.name, "proc_mounts")
        with open(proc_mounts, "w", encoding="utf-8") as f:
            f.write(f"/dev/sda1 {self.mount_point} ext4 rw,relatime 0 0\n")

        validator = StorageValidator(config_paths=[env_file], proc_mounts_path=proc_mounts)
        with patch.object(validator, "attempt_mount_trigger"):
            result = validator.validate_storage()
            self.assertFalse(result.valid)
            self.assertEqual(result.error_code, "DATA_LOST")
            self.assertIn("data was not found", result.reason)
            self.assertIn("new installation of KaraokeZero must be performed", result.reason)

    def test_validate_storage_internal_sd_always_valid(self):
        env_file = os.path.join(self.temp_dir.name, "storage.env")
        with open(env_file, "w", encoding="utf-8") as f:
            f.write("STORAGE_TYPE=sd_card\n")

        validator = StorageValidator(config_paths=[env_file])
        result = validator.validate_storage()
        self.assertTrue(result.valid)
        self.assertFalse(result.is_external_configured)


if __name__ == "__main__":
    unittest.main()
