#!/usr/bin/env python3
"""
Unit tests for KaraokeZero Module 2 (Display & Queue Orchestrator Daemon)
"""

import json
import os
import signal
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from display_manager import DisplayManager
from network_watcher import NetworkWatcher
from pikaraoke_client import PiKaraokeClient
from screen_generator import ScreenGenerator
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

    @patch("shutil.which", return_value="/usr/bin/qrencode")
    @patch("subprocess.run")
    def test_get_terminal_qr(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="████\n████", stderr="")
        watcher = NetworkWatcher(port=5555)
        qr = watcher.get_terminal_qr("http://192.168.1.50:5555")
        self.assertEqual(qr, "████\n████")
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "qrencode")
        self.assertIn("-t", cmd)
        self.assertIn("UTF8", cmd)

    @patch("subprocess.run")
    def test_get_ssid(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="MyHomeNetwork\n", stderr="")
        watcher = NetworkWatcher(port=5555)
        ssid = watcher.get_ssid()
        self.assertEqual(ssid, "MyHomeNetwork")


class TestScreenGenerator(unittest.TestCase):

    def test_generate_idle_screen(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            temp_path = tf.name
        try:
            sg = ScreenGenerator(output_path=temp_path)
            res = sg.generate(
                output_path=temp_path,
                ip_address="192.168.1.150",
                port=5555,
                portal_port=8888,
                wifi_ssid="KaraokeSetup"
            )
            self.assertTrue(res)
            self.assertTrue(os.path.isfile(temp_path))
            self.assertGreater(os.path.getsize(temp_path), 5000)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_generate_boot_screen(self):
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            temp_path = tf.name
        try:
            sg = ScreenGenerator(output_path=temp_path)
            res = sg.generate_boot_screen(
                output_path=temp_path,
                status_text="Starting PiKaraoke appliance services..."
            )
            self.assertTrue(res)
            self.assertTrue(os.path.isfile(temp_path))
            self.assertGreater(os.path.getsize(temp_path), 5000)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


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
    def test_start_idle_with_video(self, mock_popen, mock_exists):
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

    @patch("os.path.exists", return_value=True)
    @patch("subprocess.Popen")
    def test_start_idle_with_image(self, mock_popen, mock_exists):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        success = self.display.start_idle(
            media_path="/tmp/karaoke_idle_screen.png"
        )
        self.assertTrue(success)
        self.assertEqual(self.display.current_mode, "idle")

        cmd = mock_popen.call_args[0][0]
        self.assertEqual(cmd[0], "mpv")
        self.assertIn("--image-display-duration=inf", cmd)
        self.assertIn("--loop-file=inf", cmd)
        self.assertEqual(cmd[-1], "/tmp/karaoke_idle_screen.png")

    @patch.object(DisplayManager, "is_running", return_value=True)
    @patch.object(DisplayManager, "stop")
    @patch("subprocess.Popen")
    @patch("os.path.exists", return_value=True)
    def test_start_idle_restarts_mpv_for_drm_refresh(self, mock_exists, mock_popen, mock_stop, mock_running):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        self.display.current_mode = "idle"
        success = self.display.start_idle(media_path="/tmp/karaoke_idle_screen.png")
        self.assertTrue(success)
        mock_stop.assert_called_once_with(timeout=1.0)
        self.assertEqual(self.display.current_mode, "idle")

    @patch.object(DisplayManager, "start_idle", return_value=True)
    def test_start_boot_screen(self, mock_idle):
        success = self.display.start_boot_screen("/tmp/boot.png")
        self.assertTrue(success)
        mock_idle.assert_called_once_with(media_path="/tmp/boot.png")
        self.assertEqual(self.display.current_mode, "boot")

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

    @patch.object(DisplayManager, "send_ipc_command", return_value=True)
    def test_set_pause(self, mock_ipc):
        self.display.set_pause(True)
        mock_ipc.assert_called_once_with(["set_property", "pause", True])

    @patch.object(DisplayManager, "is_running", return_value=True)
    @patch.object(DisplayManager, "send_ipc_command", return_value=True)
    def test_restart_playback_via_ipc(self, mock_ipc, mock_running):
        res = self.display.restart_playback()
        self.assertTrue(res)
        mock_ipc.assert_any_call(["seek", 0, "absolute"])
        mock_ipc.assert_any_call(["set_property", "pause", False])


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
    @patch.object(ScreenGenerator, "generate_boot_screen", return_value=True)
    @patch.object(DisplayManager, "start_boot_screen", return_value=True)
    @patch.object(DisplayManager, "stop")
    @patch("builtins.open")
    def test_wait_for_backend(self, mock_open, mock_stop, mock_start_boot, mock_boot, mock_healthy, mock_ip):
        self.daemon.running = True
        ready = self.daemon.wait_for_backend(max_wait_seconds=5.0)
        self.assertTrue(ready)
        self.assertEqual(mock_healthy.call_count, 2)
        mock_boot.assert_called_once()
        mock_start_boot.assert_called_once()
        mock_stop.assert_called_once_with(timeout=1.0)

    @patch.object(NetworkWatcher, "get_ip_address", return_value="192.168.1.100")
    @patch.object(PiKaraokeClient, "is_healthy", return_value=False)
    @patch.object(ScreenGenerator, "generate_boot_screen", return_value=True)
    @patch.object(DisplayManager, "start_boot_screen", return_value=True)
    @patch.object(DisplayManager, "stop")
    @patch("builtins.open")
    def test_wait_for_backend_timeout(self, mock_open, mock_stop, mock_start_boot, mock_boot, mock_healthy, mock_ip):
        self.daemon.running = True
        ready = self.daemon.wait_for_backend(max_wait_seconds=0.1)
        self.assertFalse(ready)
        mock_stop.assert_called_once_with(timeout=1.0)

    @patch.object(NetworkWatcher, "update", return_value=(False, "http://192.168.1.100:5555"))
    @patch.object(OrchestratorDaemon, "render_idle_screen")
    @patch.object(DisplayManager, "start_idle", return_value=True)
    @patch.object(PiKaraokeClient, "get_now_playing", return_value=None)
    def test_boot_to_idle_transition(self, mock_np, mock_start_idle, mock_render, mock_net):
        self.assertEqual(self.daemon.state, OrchestratorDaemon.STATE_BOOT)
        self.daemon.step()
        self.assertEqual(self.daemon.state, OrchestratorDaemon.STATE_IDLE)
        mock_render.assert_called_once()
        mock_start_idle.assert_called_once()

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
        mock_start.assert_called_once_with(stream_url="/stream/nirvana.mp4")

    @patch.object(NetworkWatcher, "update", return_value=(False, "http://192.168.1.100:5555"))
    @patch.object(DisplayManager, "is_running", return_value=False)
    @patch.object(DisplayManager, "start_idle", return_value=True)
    @patch.object(OrchestratorDaemon, "render_idle_screen")
    @patch.object(PiKaraokeClient, "notify_end_song", return_value=True)
    @patch.object(PiKaraokeClient, "get_now_playing", return_value=None)
    def test_song_completion_to_idle_transition(self, mock_np, mock_notify_end, mock_render, mock_start_idle, mock_running, mock_net):
        self.daemon.state = OrchestratorDaemon.STATE_PLAYING
        self.daemon.active_song_id = "/stream/nirvana.mp4"
        self.daemon.playback_start_time = 0

        self.daemon.step()

        self.assertEqual(self.daemon.state, OrchestratorDaemon.STATE_IDLE)
        mock_notify_end.assert_called_once_with(reason="complete")
        mock_render.assert_called_once()
        mock_start_idle.assert_called_once()

    @patch.object(DisplayManager, "stop")
    @patch.object(OrchestratorDaemon, "transition_to_idle")
    def test_on_skip_event(self, mock_idle, mock_stop):
        self.daemon.state = OrchestratorDaemon.STATE_PLAYING
        self.daemon.on_skip_event()
        mock_stop.assert_called_once_with(timeout=1.0)
        mock_idle.assert_called_once()

    @patch.object(DisplayManager, "restart_playback")
    def test_on_restart_event(self, mock_restart):
        self.daemon.state = OrchestratorDaemon.STATE_PLAYING
        self.daemon.last_pause_state = True
        self.daemon.on_restart_event()
        mock_restart.assert_called_once()
        self.assertFalse(self.daemon.last_pause_state)

    @patch.object(DisplayManager, "set_pause")
    def test_on_pause_event(self, mock_pause):
        self.daemon.state = OrchestratorDaemon.STATE_PLAYING
        self.daemon.last_pause_state = False
        self.daemon.on_pause_event()
        mock_pause.assert_called_once_with(True)
        self.assertTrue(self.daemon.last_pause_state)

    @patch.object(DisplayManager, "set_pause")
    def test_on_play_event(self, mock_pause):
        self.daemon.state = OrchestratorDaemon.STATE_PLAYING
        self.daemon.last_pause_state = True
        self.daemon.on_play_event()
        mock_pause.assert_called_once_with(False)
        self.assertFalse(self.daemon.last_pause_state)

    def test_idle_media_defaults_to_graphical_screen(self):
        self.assertIsNone(self.daemon.bg_video)
        with patch.object(self.daemon, "_update_idle_screen", return_value="/tmp/karaoke_idle_screen.png") as mock_update:
            target = self.daemon._resolve_idle_media()
            self.assertEqual(target, "/tmp/karaoke_idle_screen.png")
            mock_update.assert_called_once()

    @patch("os.path.isfile")
    def test_resolve_background_video_no_autodiscovery(self, mock_isfile):
        # Even if bundled video files exist in the environment, auto-discovery is disabled
        mock_isfile.return_value = True
        video = self.daemon._resolve_background_video(None)
        self.assertIsNone(video)

        # Only returns path when explicitly passed and existing
        custom_video = self.daemon._resolve_background_video("/opt/custom.mp4")
        self.assertEqual(custom_video, "/opt/custom.mp4")


if __name__ == "__main__":
    unittest.main()
