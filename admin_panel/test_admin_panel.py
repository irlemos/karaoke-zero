#!/usr/bin/env python3
"""
Unit tests for KaraokeZero Module 1 (System Admin Panel)
"""

import configparser
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import subprocess

from app import (
    parse_terse_line,
    scan_wifi_networks,
    get_current_wifi_status,
    app,
    SystemSettingsManager,
    get_ytdlp_command,
    search_youtube_videos
)


class TestAdminPanel(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_system_settings_sync_to_pikaraoke(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = os.path.join(tmpdir, "settings.json")
            config_path = os.path.join(tmpdir, "config.ini")

            with patch("app.get_settings_file_path", return_value=settings_path), \
                 patch("app.get_pikaraoke_config_path", return_value=config_path):
                mgr = SystemSettingsManager()

                # 1. Test offline mode True
                mgr.save({"offline_mode": True, "default_video_quality": "720"})
                self.assertTrue(mgr.settings["offline_mode"])
                self.assertEqual(mgr.settings["default_video_quality"], "720")

                # Verify written config.ini
                cp = configparser.ConfigParser()
                cp.read(config_path)
                self.assertEqual(cp.get("SECRETS", "admin_password"), "karaokezero_locked")
                self.assertEqual(cp.get("USERPREFERENCES", "high_quality"), "True")

                # 2. Test offline mode False and standard quality
                mgr.save({"offline_mode": False, "default_video_quality": "480"})
                self.assertFalse(mgr.settings["offline_mode"])
                self.assertEqual(mgr.settings["default_video_quality"], "480")

                cp = configparser.ConfigParser()
                cp.read(config_path)
                self.assertEqual(cp.get("SECRETS", "admin_password"), "")
                self.assertEqual(cp.get("USERPREFERENCES", "high_quality"), "False")


    def test_parse_terse_line_simple(self):
        line = "*:MyHomeWifi:85:WPA2"
        expected = ["*", "MyHomeWifi", "85", "WPA2"]
        self.assertEqual(parse_terse_line(line), expected)

    def test_parse_terse_line_escaped_colons(self):
        # nmcli escapes literal colons with \:
        line = " :Bar\\:Karaoke\\:5G:70:WPA2 802.1X"
        expected = [" ", "Bar:Karaoke:5G", "70", "WPA2 802.1X"]
        self.assertEqual(parse_terse_line(line), expected)

    def test_parse_terse_line_open_network(self):
        line = " :FreeWiFi:50:"
        expected = [" ", "FreeWiFi", "50", ""]
        self.assertEqual(parse_terse_line(line), expected)

    @patch("app.run_nmcli_command")
    def test_scan_wifi_networks_deduplication_and_sorting(self, mock_run):
        # Multiple BSSIDs for "Venue_Mesh", one hidden SSID "--", and one active "AdminHotspot"
        mock_stdout = (
            " :Venue_Mesh:45:WPA2\n"
            "*:AdminHotspot:90:WPA2\n"
            " :Venue_Mesh:78:WPA2\n"
            " :--:60:WPA2\n"
            " :OpenNet:30:\n"
        )
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = mock_stdout
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        networks = scan_wifi_networks(rescan=False)

        # Total unique valid networks: AdminHotspot, Venue_Mesh, OpenNet (hidden "--" omitted)
        self.assertEqual(len(networks), 3)

        # First must be active network: AdminHotspot
        self.assertEqual(networks[0]["ssid"], "AdminHotspot")
        self.assertTrue(networks[0]["is_active"])
        self.assertEqual(networks[0]["signal"], 90)

        # Second must be Venue_Mesh with higher signal (78, not 45)
        self.assertEqual(networks[1]["ssid"], "Venue_Mesh")
        self.assertEqual(networks[1]["signal"], 78)

        # Third must be OpenNet (unsecured)
        self.assertEqual(networks[2]["ssid"], "OpenNet")
        self.assertFalse(networks[2]["is_secured"])

    @patch("app.run_nmcli_command")
    def test_get_current_wifi_status(self, mock_run):
        def side_effect(args, timeout=5):
            proc = MagicMock()
            proc.returncode = 0
            if "status" in args:
                proc.stdout = "wlan0:wifi:connected:AdminHotspot\neth0:ethernet:unavailable:\n"
            elif "IP4.ADDRESS" in args:
                proc.stdout = "192.168.43.100/24\n"
            elif "wifi" in args and "list" in args:
                proc.stdout = "*:AdminHotspot:95:WPA2\n"
            else:
                proc.stdout = ""
            return proc

        mock_run.side_effect = side_effect

        status = get_current_wifi_status()
        self.assertTrue(status["connected"])
        self.assertEqual(status["ssid"], "AdminHotspot")
        self.assertEqual(status["device"], "wlan0")
        self.assertEqual(status["ip_address"], "192.168.43.100")
        self.assertEqual(status["signal"], 95)

    def test_index_route(self):
        with patch("app.get_current_wifi_status") as mock_status:
            mock_status.return_value = {
                "connected": True,
                "ssid": "AdminHotspot",
                "device": "wlan0",
                "ip_address": "192.168.43.100",
                "signal": 95
            }
            response = self.client.get("/")
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn("KaraokeZero", html)
            self.assertIn("AdminHotspot", html)
            self.assertIn("192.168.43.100", html)

    def test_api_connect_validation(self):
        # Missing SSID
        res1 = self.client.post("/api/connect", json={})
        self.assertEqual(res1.status_code, 400)
        data1 = res1.get_json()
        self.assertFalse(data1["success"])

        # Empty SSID
        res2 = self.client.post("/api/connect", json={"ssid": "   "})
        self.assertEqual(res2.status_code, 400)

        # Valid SSID
        with patch("app._async_connect_worker"):
            res3 = self.client.post("/api/connect", json={"ssid": "Venue_WiFi", "password": "secretpassword"})
            self.assertEqual(res3.status_code, 200)
            data3 = res3.get_json()
            self.assertTrue(data3["success"])
            self.assertIn("Venue_WiFi", data3["message"])

    def test_api_status(self):
        with patch("app.get_current_wifi_status") as mock_wifi, \
             patch("app.get_system_diagnostics") as mock_diag:
            mock_wifi.return_value = {"connected": True, "ssid": "TestHotspot"}
            mock_diag.return_value = {"cpu_temp": 45.0, "ram_percent": 30.0}

            res = self.client.get("/api/status")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["success"])
            self.assertIn("wifi", data)
            self.assertIn("diagnostics", data)
            self.assertIn("settings", data)
            self.assertEqual(data["diagnostics"]["cpu_temp"], 45.0)

    def test_api_get_and_update_settings(self):
        with patch("app.settings_mgr.save") as mock_save:
            mock_save.return_value = {
                "default_video_quality": "720",
                "offline_mode": True,
                "audio_quality": "best"
            }

            # Update settings
            res = self.client.post("/api/settings", json={
                "default_video_quality": "720",
                "offline_mode": True
            })
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(data["settings"]["default_video_quality"], "720")
            self.assertTrue(data["settings"]["offline_mode"])

            # Read settings
            res_get = self.client.get("/api/settings")
            self.assertEqual(res_get.status_code, 200)
            data_get = res_get.get_json()
            self.assertTrue(data_get["success"])
            self.assertIn("settings", data_get)

    def test_api_songs_search(self):
        # Empty query
        res_empty = self.client.get("/api/songs/search?q=")
        self.assertEqual(res_empty.status_code, 200)
        self.assertEqual(res_empty.get_json()["results"], [])

        # Mocked search query
        with patch("app.search_youtube_videos") as mock_search:
            mock_search.return_value = [
                {
                    "id": "abc12345",
                    "title": "Queen - Bohemian Rhapsody Karaoke",
                    "uploader": "KaraokeChannel",
                    "duration": "5:55",
                    "thumbnail": "https://example.com/thumb.jpg",
                    "url": "https://www.youtube.com/watch?v=abc12345"
                }
            ]
            res = self.client.get("/api/songs/search?q=bohemian")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(data["count"], 1)
            self.assertEqual(data["results"][0]["title"], "Queen - Bohemian Rhapsody Karaoke")

    def test_api_songs_download_and_list(self):
        # Missing URL
        res_err = self.client.post("/api/songs/download", json={})
        self.assertEqual(res_err.status_code, 400)

        # Enqueue download
        with patch("app.download_mgr.add_download") as mock_add:
            mock_add.return_value = {
                "id": "dl_test_123",
                "url": "https://www.youtube.com/watch?v=abc12345",
                "title": "Test Song",
                "quality": "480",
                "status": "queued"
            }
            res = self.client.post("/api/songs/download", json={
                "url": "https://www.youtube.com/watch?v=abc12345",
                "title": "Test Song"
            })
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data["success"])
            self.assertEqual(data["task"]["id"], "dl_test_123")

        # List downloads
        res_list = self.client.get("/api/songs/downloads")
        self.assertEqual(res_list.status_code, 200)
        data_list = res_list.get_json()
        self.assertTrue(data_list["success"])
        self.assertIn("tasks", data_list)

    def test_api_pikaraoke_rescan(self):
        with patch("app.restart_pikaraoke_service") as mock_restart:
            mock_restart.return_value = True
            res = self.client.post("/api/pikaraoke/rescan")
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.get_json()["success"])

            mock_restart.return_value = False
            res_fail = self.client.post("/api/pikaraoke/rescan")
            self.assertEqual(res_fail.status_code, 500)
            self.assertFalse(res_fail.get_json()["success"])

    def test_api_system_power(self):
        with patch("app.delayed_power_action"):
            # Reboot
            res_reboot = self.client.post("/api/system/reboot")
            self.assertEqual(res_reboot.status_code, 200)
            self.assertTrue(res_reboot.get_json()["success"])

            # Shutdown
            res_shutdown = self.client.post("/api/system/shutdown")
            self.assertEqual(res_shutdown.status_code, 200)
            self.assertTrue(res_shutdown.get_json()["success"])

    def test_get_ytdlp_command(self):
        with patch("shutil.which", return_value="/usr/local/bin/yt-dlp"), \
             patch("os.path.isfile", return_value=True), \
             patch("os.access", return_value=True):
            cmd = get_ytdlp_command()
            self.assertEqual(cmd, ["/usr/local/bin/yt-dlp"])

        with patch("shutil.which", return_value=None), \
             patch("os.path.isfile", side_effect=lambda p: p == "/opt/pikaraoke/venv/bin/yt-dlp"), \
             patch("os.access", return_value=True):
            cmd = get_ytdlp_command()
            self.assertEqual(cmd, ["/opt/pikaraoke/venv/bin/yt-dlp"])

    @patch("urllib.request.urlopen")
    def test_search_youtube_videos_direct_url(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"title": "Direct Song", "author_name": "Artist", "thumbnail_url": "https://example.com/thumb.jpg"}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        results = search_youtube_videos("https://www.youtube.com/watch?v=20JSZ4u6Gy4")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "20JSZ4u6Gy4")
        self.assertEqual(results[0]["title"], "Direct Song")
        self.assertEqual(results[0]["uploader"], "Artist")

    @patch("urllib.request.urlopen")
    def test_search_youtube_videos_innertube(self, mock_urlopen):
        payload = {
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
                                                    "videoId": "test1234567",
                                                    "title": {"runs": [{"text": "Innertube Hit Karaoke"}]},
                                                    "ownerText": {"runs": [{"text": "Singer Pro"}]},
                                                    "lengthText": {"simpleText": "3:45"},
                                                    "thumbnail": {"thumbnails": [{"url": "https://example.com/pic.jpg"}]}
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
        import json
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        results = search_youtube_videos("queen")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "test1234567")
        self.assertEqual(results[0]["title"], "Innertube Hit Karaoke")
        self.assertEqual(results[0]["uploader"], "Singer Pro")
        self.assertEqual(results[0]["duration"], "3:45")


if __name__ == "__main__":
    unittest.main()

