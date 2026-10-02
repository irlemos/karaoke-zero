#!/usr/bin/env python3
"""
Unit tests for KaraokeZero Desktop Downloader.
Covers download queue management, hardware format string generators,
storage detection, YouTube search parsing, and REST HTTP API.
"""

import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock, patch

# Ensure tools directory and repo root are in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.dirname(SCRIPT_DIR)
REPO_ROOT = os.path.dirname(TOOLS_DIR)
for p in (SCRIPT_DIR, TOOLS_DIR, REPO_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

from desktop_downloader.download_manager import (
    DownloadManager,
    detect_storage_devices,
    resolve_ytdlp_command,
    sanitize_filename,
    sanitize_file_path,
)
from desktop_downloader.youtube_search import (
    parse_duration_seconds,
    search_youtube,
    search_playlists,
    extract_playlist_info,
)
from desktop_downloader.app import (
    DownloaderRequestHandler,
    download_mgr,
    is_port_available,
    find_available_port,
    resolve_server_port,
    DEFAULT_PORT,
    MAX_PORT_ATTEMPTS,
)


class TestDurationParsing(unittest.TestCase):
    def test_parse_duration_seconds(self):
        self.assertEqual(parse_duration_seconds("3:45"), 225)
        self.assertEqual(parse_duration_seconds("0:30"), 30)
        self.assertEqual(parse_duration_seconds("1:02:15"), 3735)
        self.assertEqual(parse_duration_seconds("invalid"), 0)
        self.assertEqual(parse_duration_seconds(""), 0)


class TestFilenameSanitization(unittest.TestCase):
    def test_sanitize_emojis_and_icons(self):
        s = "🎤 Queen - Bohemian Rhapsody (Official Karaoke Video) ᴴᴰ 🔥 [4K]"
        clean = sanitize_filename(s)
        self.assertEqual(clean, "Queen - Bohemian Rhapsody (Official Karaoke Video) HD [4K]")
        self.assertNotIn("🎤", clean)
        self.assertNotIn("🔥", clean)

    def test_sanitize_accents_preserved(self):
        s = "🎵 Evidências - Chitãozinho & Xororó (Karaokê) ⭐ [HD]!?"
        clean = sanitize_filename(s)
        self.assertEqual(clean, "Evidências - Chitãozinho & Xororó (Karaokê) [HD]")
        self.assertIn("Evidências", clean)
        self.assertIn("Chitãozinho", clean)
        self.assertNotIn("🎵", clean)
        self.assertNotIn("⭐", clean)
        self.assertNotIn("!?", clean)

    def test_sanitize_quotes_and_brackets(self):
        s = "✨【KARAOKE】“Song Title” / ‘Artist’ ft. Someone `Special` 🎉"
        clean = sanitize_filename(s)
        self.assertEqual(clean, "[KARAOKE] Song Title - Artist ft. Someone Special")

    def test_sanitize_forbidden_and_unreadable(self):
        s = "Song with *bad* :chars: | pipes | \\slashes/ and \u200b\u200e\ufeff zero-width chars"
        clean = sanitize_filename(s)
        self.assertNotIn("*", clean)
        self.assertNotIn(":", clean)
        self.assertNotIn("|", clean)
        self.assertNotIn("/", clean)
        self.assertNotIn("\\", clean)
        self.assertNotIn("\u200b", clean)
        self.assertNotIn("\ufeff", clean)

    def test_sanitize_file_path(self):
        p = "/mnt/hd/songs/🎤 Queen - Bohemian ᴴᴰ 🔥 [dQw4w9WgXcQ].mp4"
        clean_p = sanitize_file_path(p)
        self.assertEqual(clean_p, "/mnt/hd/songs/Queen - Bohemian HD [dQw4w9WgXcQ].mp4")


class TestDownloadManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="kz_dl_test_")
        self.config_path = os.path.join(self.temp_dir, "test_config.json")
        self.dm = DownloadManager(config_path=self.config_path, auto_start=False)
        self.dm.save_settings({"output_dir": self.temp_dir, "default_quality": "480"})

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_initial_state(self):
        status = self.dm.get_queue_status()
        self.assertEqual(status["total_count"], 0)
        self.assertEqual(len(status["active"]), 0)
        self.assertEqual(len(status["queued"]), 0)
        self.assertEqual(len(status["completed"]), 0)

    def test_enqueue_single_task(self):
        task = self.dm.enqueue_download(
            url_or_id="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            title="Rick Astley - Never Gonna Give You Up",
            thumbnail="https://example.com/thumb.jpg",
            quality="720",
        )
        self.assertIsNotNone(task)
        self.assertEqual(task["title"], "Rick Astley - Never Gonna Give You Up")
        self.assertEqual(task["quality"], "720")
        self.assertEqual(task["status"], "queued")

        status = self.dm.get_queue_status()
        self.assertEqual(status["total_count"], 1)
        self.assertEqual(status["tasks"][0]["id"], task["id"])

    def test_enqueue_batch(self):
        items = [
            {"url": "https://www.youtube.com/watch?v=item1", "title": "Song 1"},
            {"url": "https://www.youtube.com/watch?v=item2", "title": "Song 2"},
            {"url": "https://www.youtube.com/watch?v=item3", "title": "Song 3"},
        ]
        tasks = self.dm.enqueue_batch(items, quality="480")
        self.assertEqual(len(tasks), 3)
        status = self.dm.get_queue_status()
        self.assertEqual(status["total_count"], 3)

    def test_pause_and_resume(self):
        paused = self.dm.set_paused(True)
        self.assertTrue(paused)
        self.assertTrue(self.dm.is_paused)

        resumed = self.dm.set_paused(False)
        self.assertFalse(resumed)
        self.assertFalse(self.dm.is_paused)

    def test_cancel_task(self):
        task = self.dm.enqueue_download(
            url_or_id="https://youtube.com/watch?v=cancel_me", title="Cancel Test"
        )
        self.assertIn(task["id"], self.dm.tasks)
        success = self.dm.cancel_task(task["id"])
        self.assertTrue(success)
        self.assertNotIn(task["id"], self.dm.tasks)
        status = self.dm.get_queue_status()
        self.assertEqual(len(status["tasks"]), 0)

        # Non-existent task returns False
        self.assertFalse(self.dm.cancel_task("non-existent-id"))

    def test_completed_tasks_auto_leave_queue(self):
        t1 = self.dm.enqueue_download(
            url_or_id="https://youtube.com/watch?v=comp1", title="Comp 1"
        )
        t1["status"] = "completed"
        t1["completed_at"] = time.time() - 2.5
        self.dm.completed_count = 1

        status = self.dm.get_queue_status()
        self.assertEqual(len(status["tasks"]), 0)
        self.assertEqual(status["completed_count"], 1)

    def test_sanitize_downloaded_file_on_disk(self):
        test_file = os.path.join(self.temp_dir, "🎤 Queen - Test Song 🔥 [dQw4w9WgXcQ].mp4")
        with open(test_file, "w") as f:
            f.write("dummy media")

        task = {
            "id": "test_t",
            "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "title": "Old Title"
        }
        renamed = self.dm._sanitize_downloaded_file(self.temp_dir, task, test_file)
        self.assertIsNotNone(renamed)
        expected_name = "Queen - Test Song [dQw4w9WgXcQ].mp4"
        self.assertEqual(os.path.basename(renamed), expected_name)
        self.assertTrue(os.path.isfile(renamed))
        self.assertFalse(os.path.isfile(test_file))

    def test_clear_completed(self):
        t1 = self.dm.enqueue_download(
            url_or_id="https://youtube.com/watch?v=1", title="Task 1"
        )
        t2 = self.dm.enqueue_download(
            url_or_id="https://youtube.com/watch?v=2", title="Task 2"
        )
        t1["status"] = "completed"

        cleared = self.dm.clear_completed()
        self.assertEqual(cleared, 1)
        status = self.dm.get_queue_status()
        self.assertEqual(status["total_count"], 1)
        self.assertEqual(status["tasks"][0]["id"], t2["id"])

    def test_detect_storage_devices(self):
        devices = detect_storage_devices()
        self.assertIsInstance(devices, list)
        self.assertGreater(len(devices), 0)
        labels = [d["label"] for d in devices]
        self.assertTrue(any("Home" in l or "Music" in l or "Desktop" in l or "Karaoke" in l for l in labels))

    def test_resolve_ytdlp_command(self):
        cmd = resolve_ytdlp_command()
        self.assertIsInstance(cmd, list)
        self.assertGreater(len(cmd), 0)


class TestSearchYouTube(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_search_youtube_mocked_results(self, mock_urlopen):
        # Mock Innertube API JSON payload
        mock_data = {
            "contents": {
                "twoColumnSearchResultsRenderer": {
                    "primaryContents": {
                        "sectionListRenderer": {
                            "contents": [
                                {
                                    "itemSectionRenderer": {
                                        "contents": [
                                            {
                                                "videoRenderer": {
                                                    "videoId": "abc123xyz",
                                                    "title": {
                                                        "runs": [
                                                            {
                                                                "text": "Queen - Bohemian Rhapsody Karaoke"
                                                            }
                                                        ]
                                                    },
                                                    "ownerText": {
                                                        "runs": [
                                                            {"text": "Sing King"}
                                                        ]
                                                    },
                                                    "lengthText": {
                                                        "simpleText": "5:55"
                                                    },
                                                    "thumbnail": {
                                                        "thumbnails": [
                                                            {
                                                                "url": "https://i.ytimg.com/vi/abc123xyz/hqdefault.jpg"
                                                            }
                                                        ]
                                                    },
                                                }
                                            }
                                        ]
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        }
        mock_json = json.dumps(mock_data).encode("utf-8")
        mock_response = MagicMock()
        mock_response.read.return_value = mock_json
        mock_urlopen.return_value.__enter__.return_value = mock_response

        results = search_youtube("Queen Karaoke", max_results=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "abc123xyz")
        self.assertIn("Bohemian Rhapsody", results[0]["title"])
        self.assertEqual(results[0]["channel"], "Sing King")
        self.assertEqual(results[0]["duration"], "5:55")
        self.assertEqual(results[0]["duration_sec"], 355)

    @patch("urllib.request.urlopen")
    def test_search_playlists_mocked(self, mock_urlopen):
        mock_data = {
            "contents": {
                "twoColumnSearchResultsRenderer": {
                    "primaryContents": {
                        "sectionListRenderer": {
                            "contents": [
                                {
                                    "itemSectionRenderer": {
                                        "contents": [
                                            {
                                                "lockupViewModel": {
                                                    "contentId": "PLtest123",
                                                    "contentType": "LOCKUP_CONTENT_TYPE_PLAYLIST",
                                                    "metadata": {
                                                        "lockupMetadataViewModel": {
                                                            "title": {"content": "Greatest Karaoke Hits Playlist"},
                                                            "metadata": {
                                                                "contentMetadataViewModel": {
                                                                    "metadataRows": [
                                                                        {
                                                                            "metadataParts": [
                                                                                {"text": {"content": "Karaoke Master"}}
                                                                            ]
                                                                        }
                                                                    ]
                                                                }
                                                            }
                                                        }
                                                    },
                                                    "contentImage": {
                                                        "collectionThumbnailViewModel": {
                                                            "primaryThumbnail": {
                                                                "thumbnailViewModel": {
                                                                    "overlays": [
                                                                        {
                                                                            "thumbnailOverlayBadgeViewModel": {
                                                                                "thumbnailBadges": [
                                                                                    {
                                                                                        "thumbnailBadgeViewModel": {
                                                                                            "text": "45 videos"
                                                                                        }
                                                                                    }
                                                                                ]
                                                                            }
                                                                        }
                                                                    ],
                                                                    "image": {
                                                                        "sources": [
                                                                            {"url": "https://example.com/playlist_thumb.jpg"}
                                                                        ]
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        ]
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        }
        mock_html = f"var ytInitialData = {json.dumps(mock_data)};</script>".encode("utf-8")
        mock_response = MagicMock()
        mock_response.read.return_value = mock_html
        mock_urlopen.return_value.__enter__.return_value = mock_response

        playlists = search_playlists("rock karaoke", max_results=5)
        self.assertEqual(len(playlists), 1)
        self.assertEqual(playlists[0]["id"], "PLtest123")
        self.assertEqual(playlists[0]["title"], "Greatest Karaoke Hits Playlist")
        self.assertEqual(playlists[0]["channel"], "Karaoke Master")
        self.assertEqual(playlists[0]["video_count"], "45 videos")
        self.assertIn("PLtest123", playlists[0]["url"])


class TestDownloaderHTTPAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.mkdtemp(prefix="kz_api_test_")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("", 0))
        cls.port = sock.getsockname()[1]
        sock.close()

        download_mgr.save_settings({"output_dir": cls.temp_dir, "default_quality": "480"})
        download_mgr.set_paused(True)

        cls.server = ThreadingHTTPServer(("127.0.0.1", cls.port), DownloaderRequestHandler)
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def _get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.headers.get_content_type(), resp.read()

    def _post(self, path, payload):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.headers.get_content_type(), resp.read()

    def test_serve_static_index(self):
        status, ctype, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "text/html")
        self.assertIn(b"KaraokeZero", body)

    def test_serve_static_css(self):
        status, ctype, body = self._get("/style.css")
        self.assertEqual(status, 200)
        self.assertEqual(ctype, "text/css")
        self.assertIn(b"--bg-primary", body)

    def test_serve_static_js(self):
        status, ctype, body = self._get("/app.js")
        self.assertEqual(status, 200)
        self.assertTrue(ctype in ("text/javascript", "application/javascript"))
        self.assertIn(b"DOMContentLoaded", body)

    def test_get_settings(self):
        status, ctype, body = self._get("/api/settings")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertIn("output_dir", data)
        self.assertIn("quality", data)
        self.assertIn("available_drives", data)

    def test_post_settings(self):
        new_dir = os.path.join(self.temp_dir, "custom_songs")
        status, ctype, body = self._post(
            "/api/settings", {"output_dir": new_dir, "quality": "720"}
        )
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["output_dir"], new_dir)
        self.assertEqual(data["quality"], "720")

    def test_queue_lifecycle_api(self):
        # 1. Enqueue single item
        status, ctype, body = self._post(
            "/api/download",
            {"url": "https://www.youtube.com/watch?v=api_test", "title": "API Test Song"},
        )
        self.assertEqual(status, 200)
        res = json.loads(body.decode("utf-8"))
        self.assertEqual(res["status"], "ok")
        task_id = res["task"]["id"]

        # 2. Query queue
        status, ctype, body = self._get("/api/queue")
        self.assertEqual(status, 200)
        queue_data = json.loads(body.decode("utf-8"))
        self.assertGreaterEqual(len(queue_data["queue"]), 1)

        # 3. Pause queue (toggle)
        status, ctype, body = self._post("/api/queue/pause", {})
        self.assertEqual(status, 200)
        pause_data = json.loads(body.decode("utf-8"))
        self.assertIn("is_paused", pause_data)

        # 4. Cancel item
        status, ctype, body = self._post("/api/queue/cancel", {"task_id": task_id})
        self.assertEqual(status, 200)

        # 5. Clear completed
        status, ctype, body = self._post("/api/queue/clear", {})
        self.assertEqual(status, 200)

    @patch("desktop_downloader.app.search_playlists")
    def test_search_api_with_playlists_type(self, mock_search_pl):
        mock_search_pl.return_value = [
            {
                "id": "PLsertanejo123",
                "title": "Sertanejo Karaoke Best",
                "channel": "Sertanejo Hits",
                "video_count": "50 videos",
                "thumbnail": "https://example.com/thumb.jpg",
                "url": "https://www.youtube.com/playlist?list=PLsertanejo123"
            }
        ]
        status, ctype, body = self._get("/api/search?type=playlists&q=sertanejo")
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["type"], "playlists")
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["id"], "PLsertanejo123")

    @patch("desktop_downloader.app.extract_playlist_info")
    def test_download_playlist_api(self, mock_extract):
        mock_extract.return_value = {
            "success": True,
            "id": "PLrock99",
            "title": "Rock Karaoke Collection",
            "count": 2,
            "items": [
                {"id": "v1", "title": "Rock 1", "thumbnail": "", "url": "https://youtube.com/watch?v=v1"},
                {"id": "v2", "title": "Rock 2", "thumbnail": "", "url": "https://youtube.com/watch?v=v2"}
            ]
        }

        status, ctype, body = self._post(
            "/api/download/playlist",
            {"url": "https://www.youtube.com/playlist?list=PLrock99", "quality": "480"}
        )
        self.assertEqual(status, 200)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["enqueued_count"], 2)
        self.assertEqual(data["playlist_title"], "Rock Karaoke Collection")



class TestPortResolution(unittest.TestCase):
    def test_is_port_available_free(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
        s.close()
        self.assertTrue(is_port_available(free_port))

    def test_is_port_available_busy(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        busy_port = s.getsockname()[1]
        try:
            self.assertFalse(is_port_available(busy_port))
        finally:
            s.close()

    def test_find_available_port_immediate(self):
        with patch("desktop_downloader.app.is_port_available", return_value=True):
            port = find_available_port(start_port=7777, max_attempts=20)
            self.assertEqual(port, 7777)

    def test_find_available_port_fallback(self):
        def side_effect(p, host="127.0.0.1"):
            return p >= 7779

        with patch("desktop_downloader.app.is_port_available", side_effect=side_effect):
            port = find_available_port(start_port=7777, max_attempts=20)
            self.assertEqual(port, 7779)

    def test_find_available_port_all_busy_returns_none(self):
        with patch("desktop_downloader.app.is_port_available", return_value=False):
            port = find_available_port(start_port=7777, max_attempts=20)
            self.assertIsNone(port)

    def test_resolve_server_port_default_free(self):
        with patch("desktop_downloader.app.find_available_port", return_value=7777):
            actual = resolve_server_port(requested_port=None)
            self.assertEqual(actual, 7777)

    def test_resolve_server_port_auto_switch_prints_notice(self):
        with patch("desktop_downloader.app.find_available_port", return_value=7779), \
             patch("builtins.print") as mock_print:
            actual = resolve_server_port(requested_port=None)
            self.assertEqual(actual, 7779)
            printed_texts = [str(call[0][0]) for call in mock_print.call_args_list if call[0]]
            self.assertTrue(any("switched to available port: 7779" in t for t in printed_texts))

    def test_resolve_server_port_all_20_busy_exits_with_error(self):
        with patch("desktop_downloader.app.find_available_port", return_value=None), \
             self.assertRaises(SystemExit) as cm:
            resolve_server_port(requested_port=None)
        self.assertEqual(cm.exception.code, 1)

    def test_resolve_server_port_custom_port_available(self):
        with patch("desktop_downloader.app.is_port_available", return_value=True):
            actual = resolve_server_port(requested_port=8080)
            self.assertEqual(actual, 8080)

    def test_resolve_server_port_custom_port_busy_exits_with_error(self):
        with patch("desktop_downloader.app.is_port_available", return_value=False), \
             self.assertRaises(SystemExit) as cm:
            resolve_server_port(requested_port=8080)
        self.assertEqual(cm.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
