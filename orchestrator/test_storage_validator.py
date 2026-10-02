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

    def test_sanitize_storage(self):
        songs_dir = os.path.join(self.mount_point, "songs")
        os.makedirs(songs_dir, exist_ok=True)

        # Incomplete download artifacts
        part_file = os.path.join(songs_dir, "song.mp4.part")
        ytdl_file = os.path.join(songs_dir, "video.ytdl")
        temp_file = os.path.join(songs_dir, "buffer.temp")

        # 0-byte corrupt media files
        zero_mp4 = os.path.join(songs_dir, "broken.mp4")
        zero_mp3 = os.path.join(songs_dir, "empty.mp3")

        # Valid finished song file
        valid_mp4 = os.path.join(songs_dir, "valid.mp4")

        for p in [part_file, ytdl_file, temp_file, zero_mp4, zero_mp3]:
            with open(p, "wb") as f:
                pass  # 0 bytes

        with open(valid_mp4, "wb") as f:
            f.write(b"RIFF....WAVE" + b"x" * 1024)

        validator = StorageValidator()
        res = validator.sanitize_storage(self.mount_point)

        self.assertEqual(res["cleaned_temp"], 3)
        self.assertEqual(res["cleaned_zero_byte"], 2)

        self.assertFalse(os.path.exists(part_file))
        self.assertFalse(os.path.exists(ytdl_file))
        self.assertFalse(os.path.exists(temp_file))
        self.assertFalse(os.path.exists(zero_mp4))
        self.assertFalse(os.path.exists(zero_mp3))
        self.assertTrue(os.path.exists(valid_mp4))

    def test_verify_and_repair_sqlite_healthy(self):
        data_dir = os.path.join(self.mount_point, "data")
        os.makedirs(data_dir, exist_ok=True)
        db_path = os.path.join(data_dir, "pikaraoke.db")

        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE songs (id INTEGER PRIMARY KEY, title TEXT);")
        conn.execute("INSERT INTO songs (title) VALUES ('Bohemian Rhapsody');")
        conn.commit()
        conn.close()

        validator = StorageValidator()
        res = validator.verify_and_repair_sqlite(self.mount_point)

        self.assertEqual(res["checked"], 1)
        self.assertEqual(res["corrupted"], 0)

        # Verify WAL mode was applied
        conn = sqlite3.connect(db_path)
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        conn.close()
        self.assertEqual(mode.lower(), "wal")

    def test_verify_and_repair_sqlite_corrupt(self):
        data_dir = os.path.join(self.mount_point, "data")
        os.makedirs(data_dir, exist_ok=True)
        db_path = os.path.join(data_dir, "corrupt.db")

        # Write invalid SQLite binary headers
        with open(db_path, "wb") as f:
            f.write(b"NOT A VALID SQLITE HEADER GARBAGE CONTENT")

        validator = StorageValidator()
        res = validator.verify_and_repair_sqlite(self.mount_point)

        self.assertEqual(res["checked"], 1)
        self.assertEqual(res["corrupted"], 1)

        # Check backup created
        backup_files = [f for f in os.listdir(data_dir) if "corrupt.db.corrupt" in f]
        self.assertTrue(len(backup_files) >= 1)

    def test_sync_wifi_profiles_from_storage(self):
        wifi_dir = os.path.join(self.mount_point, "data", "wifi")
        os.makedirs(wifi_dir, exist_ok=True)

        profile_file = os.path.join(wifi_dir, "Venue-Network.nmconnection")
        with open(profile_file, "w", encoding="utf-8") as f:
            f.write("[connection]\nid=Venue-Network\ntype=wifi\n")

        run_nm_dir = os.path.join(self.temp_dir.name, "run_nm")

        validator = StorageValidator()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            res = validator.sync_wifi_profiles_from_storage(self.mount_point, run_nm_dir=run_nm_dir)

            self.assertEqual(res["synced"], 1)
            self.assertIn("Venue-Network.nmconnection", res["profiles"])

            synced_file = os.path.join(run_nm_dir, "Venue-Network.nmconnection")
            self.assertTrue(os.path.exists(synced_file))
            # Verify permissions are 0600
            mode = oct(os.stat(synced_file).st_mode & 0o777)
            self.assertEqual(mode, oct(0o600))
            mock_run.assert_called_once()

    def test_repair_filesystem_if_needed(self):
        validator = StorageValidator()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            self.assertTrue(validator.repair_filesystem_if_needed("/dev/sda1"))
            mock_run.assert_called_once()

            # Non /dev/ device should immediately return False
            self.assertFalse(validator.repair_filesystem_if_needed("invalid_dev"))


if __name__ == "__main__":
    unittest.main()

