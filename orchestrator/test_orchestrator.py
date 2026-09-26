#!/usr/bin/env python3
"""
Unit tests for KaraokeZero Module 2 (Display & Queue Orchestrator Daemon)
"""

import json
import os
import signal
import subprocess
import unittest
from unittest.mock import MagicMock, patch

from display_manager import DisplayManager
from network_watcher import NetworkWatcher
from pikaraoke_client import PiKaraokeClient
from orchestrator import OrchestratorDaemon


class TestNetworkWatcher(unittest.TestCase):

    @patch("socket.socket")
    def test_get_ip_address_socket_probe(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_sock.getsockname.return_value = ("192.168.1.50", 12345)
        mock_socket_cls.return_value = mock_sock

        watcher = NetworkWatcher(interface="wlan0", port=5555)
        ip = watcher.get_ip_address()
        self.assertEqual(ip, "192.168.1.50")
        self.assertEqual(watcher.get_access_url(), "http://192.168.1.50:5555")

    @patch("shutil.which", return_value="/usr/bin/qrencode")
    @patch("subprocess.run")
    @patch("os.path.exists", return_value=True)
    def test_generate_qr_code_success(self, mock_exists, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        watcher = NetworkWatcher(qr_output_path="/tmp/test_qr.png")
        success = watcher.generate_qr_code("http://192.168.1.50:5555")
        self.assertTrue(success)

        # Verify qrencode arguments
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "qrencode")
        self.assertIn("-s", cmd)
        self.assertIn("http://192.168.1.50:5555", cmd)

    @patch.object(NetworkWatcher, "get_ip_address", return_value="192.168.43.100")
    @patch.object(NetworkWatcher, "generate_qr_code", return_value=True)
    @patch("os.path.exists", return_value=True)
    def test_update_ip_change_detection(self, mock_exists, mock_gen, mock_ip):
        watcher = NetworkWatcher()
        changed, url = watcher.update()
        self.assertTrue(changed)
        self.assertEqual(url, "http://192.168.43.100:5555")
        mock_gen.assert_called_once_with("http://192.168.43.100:5555")

        # Second update without IP change -> no generation
        mock_gen.reset_mock()
        changed2, url2 = watcher.update()
        self.assertFalse(changed2)
        mock_gen.assert_not_called()


class TestDisplayManager(unittest.TestCase):

    def setUp(self):
        self.display = DisplayManager(
            vout="gpu",
            aout="alsa",
            alsa_device="alsa/plughw:CARD=vc4hdmi,DEV=0",
            enable_rc=False
        )

    @patch("os.path.exists", return_value=True)
    @patch("subprocess.Popen")
    def test_start_idle_with_qr_overlay(self, mock_popen, mock_exists):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        success = self.display.start_idle(
            video_path="/opt/assets/idle.mp4",
            qr_code_path="/tmp/qrcode.png"
        )
        self.assertTrue(success)
        self.assertEqual(self.display.current_mode, "idle")

        cmd = mock_popen.call_args[0][0]
        self.assertEqual(cmd[0], "mpv")
        self.assertIn("--vo=gpu", cmd)
        self.assertIn("--gpu-context=drm", cmd)
        self.assertIn("--hwdec=v4l2m2m-copy", cmd)
        self.assertIn("--profile=fast", cmd)
        self.assertIn("--no-audio", cmd)
        self.assertIn("--loop-file=inf", cmd)
        self.assertEqual(cmd[-1], "/opt/assets/idle.mp4")

    @patch("subprocess.Popen")
    def test_start_playback(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        success = self.display.start_playback("http://127.0.0.1:5555/stream/song.mp4")
        self.assertTrue(success)
        self.assertEqual(self.display.current_mode, "playing")

        cmd = mock_popen.call_args[0][0]
        self.assertEqual(cmd[0], "mpv")
        self.assertIn("--vo=gpu", cmd)
        self.assertIn("--ao=alsa", cmd)
        self.assertIn("--audio-device=alsa/plughw:CARD=vc4hdmi,DEV=0", cmd)
        self.assertIn("--audio-samplerate=48000", cmd)
        self.assertEqual(cmd[-1], "http://127.0.0.1:5555/stream/song.mp4")

    def test_stop_graceful_and_escalate(self):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        # First wait times out (IPC quit), second wait times out (SIGTERM), third succeeds after SIGKILL
        mock_proc.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="mpv", timeout=1.0),
            subprocess.TimeoutExpired(cmd="mpv", timeout=1.0),
            None
        ]
        self.display.process = mock_proc

        self.display.stop(timeout=1.0)
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()
        self.assertEqual(self.display.current_mode, "stopped")
        self.assertIsNone(self.display.process)


class TestPiKaraokeClient(unittest.TestCase):

    def setUp(self):
        self.client = PiKaraokeClient(base_url="http://127.0.0.1:5555")

    @patch("urllib.request.urlopen")
    def test_get_now_playing_parsing(self, mock_urlopen):
        payload = {
            "now_playing": "Queen - Radio Ga Ga",
            "now_playing_url": "/stream/radio_gaga.mp4",
            "is_paused": False
        }
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        data = self.client.get_now_playing()
        self.assertIsNotNone(data)
        self.assertEqual(data["now_playing"], "Queen - Radio Ga Ga")
        self.assertEqual(data["now_playing_url"], "/stream/radio_gaga.mp4")

    def test_resolve_media_url(self):
        url = self.client.resolve_media_url("/stream/test.mp4")
        self.assertEqual(url, "http://127.0.0.1:5555/stream/test.mp4")

        abs_url = self.client.resolve_media_url("http://example.com/audio.mp3")
        self.assertEqual(abs_url, "http://example.com/audio.mp3")

    @patch("urllib.request.urlopen")
    def test_is_healthy_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        self.assertTrue(self.client.is_healthy())

    @patch("urllib.request.urlopen", side_effect=Exception("Connection refused"))
    def test_is_healthy_failure(self, mock_urlopen):
        self.assertFalse(self.client.is_healthy())


class TestOrchestratorDaemonFSM(unittest.TestCase):

    def setUp(self):
        self.daemon = OrchestratorDaemon(
            pikaraoke_url="http://127.0.0.1:5555",
            poll_interval=0.1,
            enable_rc=False
        )

    @patch.object(NetworkWatcher, "get_ip_address", return_value="192.168.1.100")
    @patch.object(PiKaraokeClient, "is_healthy", side_effect=[False, True])
    @patch("builtins.open")
    def test_wait_for_backend(self, mock_open, mock_healthy, mock_ip):
        self.daemon.running = True
        ready = self.daemon.wait_for_backend(max_wait_seconds=5.0)
        self.assertTrue(ready)
        self.assertEqual(mock_healthy.call_count, 2)

    @patch.object(NetworkWatcher, "update", return_value=(False, "http://192.168.1.100:5555"))
    @patch.object(DisplayManager, "start_idle", return_value=True)
    @patch.object(PiKaraokeClient, "get_now_playing", return_value=None)
    def test_boot_to_idle_transition(self, mock_np, mock_idle, mock_net):
        self.assertEqual(self.daemon.state, OrchestratorDaemon.STATE_BOOT)
        self.daemon.step()
        self.assertEqual(self.daemon.state, OrchestratorDaemon.STATE_IDLE)
        mock_idle.assert_called_once()

    @patch.object(NetworkWatcher, "update", return_value=(False, "http://192.168.1.100:5555"))
    @patch.object(DisplayManager, "start_playback", return_value=True)
    @patch.object(PiKaraokeClient, "notify_start_song", return_value=True)
    def test_idle_to_playing_transition(self, mock_start, mock_play, mock_net):
        self.daemon.state = OrchestratorDaemon.STATE_IDLE

        with patch.object(self.daemon.client, "get_now_playing") as mock_np:
            mock_np.return_value = {
                "now_playing": "Nirvana - Smells Like Teen Spirit",
                "now_playing_url": "/stream/nirvana.mp4",
                "is_paused": False
            }
            self.daemon.step()

        self.assertEqual(self.daemon.state, OrchestratorDaemon.STATE_PLAYING)
        mock_play.assert_called_once_with(media_target="http://127.0.0.1:5555/stream/nirvana.mp4")
        mock_start.assert_called_once()

    @patch.object(NetworkWatcher, "update", return_value=(False, "http://192.168.1.100:5555"))
    @patch.object(DisplayManager, "is_running", return_value=False)
    @patch.object(DisplayManager, "start_idle", return_value=True)
    @patch.object(PiKaraokeClient, "notify_end_song", return_value=True)
    @patch.object(PiKaraokeClient, "get_now_playing", return_value=None)
    def test_song_completion_to_idle_transition(self, mock_np, mock_notify_end, mock_idle, mock_running, mock_net):
        self.daemon.state = OrchestratorDaemon.STATE_PLAYING
        self.daemon.active_song_id = "/stream/nirvana.mp4"

        self.daemon.step()

        self.assertEqual(self.daemon.state, OrchestratorDaemon.STATE_IDLE)
        mock_notify_end.assert_called_once_with(reason="complete")
        mock_idle.assert_called_once()


if __name__ == "__main__":
    unittest.main()
