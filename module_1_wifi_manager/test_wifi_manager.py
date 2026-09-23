#!/usr/bin/env python3
"""
Unit tests for KaraokeZero Module 1 (WiFi Manager)
"""

import unittest
from unittest.mock import patch, MagicMock
import subprocess

from app import parse_terse_line, scan_wifi_networks, get_current_wifi_status, app


class TestWiFiManager(unittest.TestCase):

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

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


if __name__ == "__main__":
    unittest.main()
