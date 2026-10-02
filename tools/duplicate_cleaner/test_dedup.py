#!/usr/bin/env python3
"""
Unit tests for KaraokeZero Video Deduplication & Duplicate Cleaner Tool.
Covers binary hashing, YouTube ID matching, audio stream fingerprinting,
quality scoring, duplicate grouping, and safe deletion.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from dedup_engine import (
    DuplicateGroup,
    MatchStrategy,
    MediaFile,
    VideoDeduplicator,
    calculate_file_hash,
    calculate_partial_hash,
    extract_youtube_id,
    normalize_title,
    score_media_file
)


class TestHelpers(unittest.TestCase):
    def test_extract_youtube_id(self):
        self.assertEqual(
            extract_youtube_id("Queen - Bohemian Rhapsody [dQw4w9WgXcQ].mp4"),
            "dQw4w9WgXcQ"
        )
        self.assertEqual(
            extract_youtube_id("Song Title [1234567890A].webm"),
            "1234567890A"
        )
        self.assertIsNone(extract_youtube_id("Just a song title without id.mp4"))
        self.assertIsNone(extract_youtube_id("Song [short].mp4"))

    def test_normalize_title(self):
        s1 = "Queen - Bohemian Rhapsody [dQw4w9WgXcQ].mp4"
        s2 = "Bohemian Rhapsody (Official Video) [dQw4w9WgXcQ].mp4"
        self.assertEqual(normalize_title(s1), "queen bohemian rhapsody")
        self.assertEqual(normalize_title(s2), "bohemian rhapsody")

    def test_score_media_file(self):
        f_good = MediaFile(
            path="/tmp/Queen - Song [dQw4w9WgXcQ].mp4",
            filename="Queen - Song [dQw4w9WgXcQ].mp4",
            size=50000000,
            mtime=1000.0,
            video_id="dQw4w9WgXcQ",
            height=720,
            vcodec="h264",
            acodec="aac"
        )
        f_poor = MediaFile(
            path="/tmp/VID_12345.mp4",
            filename="VID_12345.mp4",
            size=15000000,
            mtime=1000.0,
            height=360,
            vcodec="vp9",
            acodec="opus"
        )
        score_good = score_media_file(f_good)
        score_poor = score_media_file(f_poor)
        self.assertGreater(score_good, score_poor)


class TestDeduplicator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="kz_dedup_unit_")
        self.dedup = VideoDeduplicator()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_dummy_file(self, filename: str, content: bytes) -> str:
        fp = os.path.join(self.temp_dir, filename)
        with open(fp, "wb") as f:
            f.write(content)
        return fp

    def test_exact_hash_duplicates_different_names(self):
        # Create 2 files with totally different names but identical content
        content = b"KaraokeZero Media Content Test Bytes 1234567890" * 500
        p1 = self._create_dummy_file("Queen - Bohemian Rhapsody.mp4", content)
        p2 = self._create_dummy_file("Random File 999.mp4", content)
        # Create a unique 3rd file
        p3 = self._create_dummy_file("Beatles - Yesterday.mp4", b"Different Content" * 500)

        groups = self.dedup.scan_directory(self.temp_dir, strategy=MatchStrategy.EXACT_HASH, deep_audio=False)
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertIn("Exact Binary", g.matched_by)
        self.assertEqual(len(g.duplicates), 1)
        # Verify keeper is the better-named file
        self.assertEqual(g.keeper.filename, "Queen - Bohemian Rhapsody.mp4")
        self.assertEqual(g.duplicates[0].filename, "Random File 999.mp4")

    def test_youtube_id_duplicates(self):
        # Create 2 files with different sizes/content but same YouTube ID
        p1 = self._create_dummy_file("Queen - Radio Ga Ga [dQw4w9WgXcQ].mp4", b"Track A" * 100)
        p2 = self._create_dummy_file("Radio Ga Ga Karaoke [dQw4w9WgXcQ].mp4", b"Track B Different" * 200)

        groups = self.dedup.scan_directory(self.temp_dir, strategy=MatchStrategy.YOUTUBE_ID, deep_audio=False)
        self.assertEqual(len(groups), 1)
        g = groups[0]
        self.assertIn("YouTube Video ID", g.matched_by)
        self.assertIn("dQw4w9WgXcQ", g.matched_by)
        self.assertEqual(len(g.duplicates), 1)

    def test_delete_file_permanent(self):
        fp = self._create_dummy_file("delete_me.mp4", b"content")
        self.assertTrue(os.path.isfile(fp))
        res = self.dedup.delete_file(fp, move_to_trash=False)
        self.assertTrue(res)
        self.assertFalse(os.path.isfile(fp))

    def test_delete_file_move_to_trash(self):
        fp = self._create_dummy_file("trash_me.mp4", b"content")
        self.assertTrue(os.path.isfile(fp))
        res = self.dedup.delete_file(fp, move_to_trash=True)
        self.assertTrue(res)
        self.assertFalse(os.path.isfile(fp))
        trash_file = os.path.join(self.temp_dir, ".trash", "trash_me.mp4")
        self.assertTrue(os.path.isfile(trash_file))

    def test_fuzzy_duration_and_title_duplicates(self):
        # Create files with mock media info
        p1 = self._create_dummy_file("Queen - Bohemian Rhapsody.mp4", b"A" * 100)
        p2 = self._create_dummy_file("Queen - Bohemian Rhapsody [Karaoke].mp4", b"B" * 150)

        # Mock probe_media_info to return identical duration
        with patch("dedup_engine.probe_media_info") as mock_probe:
            mock_probe.side_effect = lambda fp, **kw: {
                "format": {"duration": "354.2"},
                "streams": [{"codec_type": "video", "height": 720, "codec_name": "h264"}]
            }
            groups = self.dedup.scan_directory(
                self.temp_dir,
                strategy=MatchStrategy.DURATION_TITLE,
                deep_audio=False
            )
            self.assertEqual(len(groups), 1)
            self.assertIn("Duration", groups[0].matched_by)


if __name__ == "__main__":
    unittest.main()
