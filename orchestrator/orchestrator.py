#!/usr/bin/env python3
"""
KaraokeZero - Module 2: Orchestrator Daemon
Main Service Coordinator & Display FSM Engine

Coordinates PiKaraoke status, hardware-accelerated VLC framebuffer rendering,
and dynamic QR code generation on Raspberry Pi Zero W without X11/Chromium.
"""

import argparse
import logging
import os
import signal
import sys
import time
from typing import Optional

from display_manager import DisplayManager
from network_watcher import NetworkWatcher
from pikaraoke_client import PiKaraokeClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Orchestrator] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("Orchestrator")


class OrchestratorDaemon:
    """
    Main finite state machine daemon orchestrating headless display and PiKaraoke playback.
    """

    STATE_BOOT = "BOOT"
    STATE_IDLE = "IDLE"
    STATE_PLAYING = "PLAYING"
    STATE_SHUTDOWN = "SHUTDOWN"

    def __init__(
        self,
        pikaraoke_url: str = "http://127.0.0.1:5555",
        interface: str = "wlan0",
        port: int = 5555,
        bg_video_path: Optional[str] = None,
        vout: str = "gpu",
        aout: str = "alsa",
        alsa_device: str = "alsa/plughw:CARD=vc4hdmi,DEV=0",
        qr_output: str = "/tmp/qrcode.png",
        poll_interval: float = 1.0,
        enable_rc: bool = True
    ):
        self.pikaraoke_url = pikaraoke_url
        self.poll_interval = poll_interval
        self.running = False
        self.state = self.STATE_BOOT

        # Subsystems
        self.network = NetworkWatcher(
            interface=interface,
            port=port,
            qr_output_path=qr_output
        )
        self.display = DisplayManager(
            vout=vout,
            aout=aout,
            alsa_device=alsa_device,
            enable_rc=enable_rc
        )
        self.client = PiKaraokeClient(base_url=pikaraoke_url)

        # Background video resolution
        self.bg_video = self._resolve_background_video(bg_video_path)

        # Track state
        self.active_song_id: Optional[str] = None
        self.last_pause_state: bool = False

    def _resolve_background_video(self, custom_path: Optional[str]) -> str:
        """
        Locates the idle background video directly from the installed PiKaraoke directory
        or falls back to the local PiKaraoke HTTP stream.
        """
        if custom_path and os.path.isfile(custom_path):
            logger.info("Using custom background video: %s", custom_path)
            return custom_path

        # 1. Check external HDD custom media directory
        hdd_candidates = [
            "/mnt/external_hd/karaoke/media/idle_loop.mp4",
            "/mnt/external_hd/karaoke/media/night_sea.mp4",
            "/mnt/external_hd/karaoke/idle_loop.mp4",
            "/mnt/external_hd/karaoke/night_sea.mp4"
        ]
        for path in hdd_candidates:
            if os.path.isfile(path):
                logger.info("Using external HDD background video: %s", path)
                return path

        # 2. Try resolving via installed python pikaraoke package
        try:
            import pikaraoke
            pkg_video = os.path.join(os.path.dirname(pikaraoke.__file__), "static", "video", "night_sea.mp4")
            if os.path.isfile(pkg_video):
                logger.info("Using installed PiKaraoke package video: %s", pkg_video)
                return pkg_video
        except ImportError:
            pass

        # 3. Known PiKaraoke clone and system directories
        known_locations = [
            "/opt/pikaraoke/pikaraoke/static/video/night_sea.mp4",
            "/usr/local/share/pikaraoke/static/video/night_sea.mp4",
            "/usr/share/pikaraoke/static/video/night_sea.mp4",
            os.path.expanduser("~/pikaraoke/pikaraoke/static/video/night_sea.mp4")
        ]
        for path in known_locations:
            if os.path.isfile(path):
                logger.info("Using installed PiKaraoke video: %s", path)
                return path

        # 4. Fallback to PiKaraoke stream endpoint
        stream_url = f"{self.pikaraoke_url}/stream/bg_video"
        logger.info("No local background video found; falling back to PiKaraoke stream: %s", stream_url)
        return stream_url

    def setup_signals(self) -> None:
        """Configures clean POSIX termination signal handlers."""
        def handle_signal(sig, frame):
            logger.info("Received termination signal (%d). Shutting down Orchestrator...", sig)
            self.running = False

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

    def on_skip_event(self) -> None:
        """Callback triggered when a skip event is received via WebSocket."""
        logger.info("Skip triggered. Stopping active playback...")
        if self.state == self.STATE_PLAYING:
            self.display.stop(timeout=1.0)

    def _find_local_song_file(self, song_title: str) -> Optional[str]:
        """
        Attempts to locate the actual downloaded media file in local storage.
        Playing direct from disk eliminates HTTP streaming and transcode latency.
        """
        candidate_dirs = [
            "/mnt/external_hd/karaoke/songs",
            os.path.expanduser("~/songs")
        ]
        clean_title = song_title.strip().lower()
        for base_dir in candidate_dirs:
            if not os.path.isdir(base_dir):
                continue
            try:
                for root, _, files in os.walk(base_dir):
                    for fname in files:
                        fname_lower = fname.lower()
                        name_without_ext = os.path.splitext(fname_lower)[0]
                        if clean_title in name_without_ext or name_without_ext in clean_title:
                            full_path = os.path.join(root, fname)
                            if os.path.isfile(full_path):
                                logger.info("Found local media file for '%s': %s", song_title, full_path)
                                return full_path
            except Exception as e:
                logger.debug("Error scanning %s for song: %s", base_dir, e)
        return None

    def render_idle_screen(self, tty_device: str = "/dev/tty1") -> None:
        """
        Renders the static, zero-CPU idle screen to the HDMI console (/dev/tty1).
        Displays appliance branding, network connection info, and a scannable QR code.
        """
        ip = self.network.get_ip_address()
        web_url = f"http://{ip}:{self.network.port}" if ip else f"http://127.0.0.1:{self.network.port}"
        portal_url = f"http://{ip}:8888" if ip else "http://192.168.4.1:8888"

        qr_text = self.network.get_terminal_qr(web_url)
        qr_lines = []
        if qr_text:
            for line in qr_text.splitlines():
                qr_lines.append(f"          {line}")
            qr_block = "\n".join(qr_lines)
        else:
            qr_block = f"          [ QR Code Available at {web_url} ]"

        screen = [
            "",
            "  ============================================================================",
            "                            K A R A O K E - Z E R O                           ",
            "                     Standalone Offline Karaoke Appliance                     ",
            "  ============================================================================",
            "",
            "                 >>> SCAN WITH YOUR PHONE TO CHOOSE SONGS <<<                 ",
            "                 >>>  ESCANEIE COM O CELULAR PARA CANTAR  <<<                 ",
            "",
            qr_block,
            "",
            "   • Wi-Fi Network:      Connect to Venue Wi-Fi or Hotspot 'KaraokeZero-Setup'",
            f"   • PiKaraoke Web App:  {web_url}",
            f"   • Wi-Fi Setup Portal: {portal_url}",
            "",
            "  ----------------------------------------------------------------------------",
            "   Status: IDLE (Waiting for singers) | 0 Active Songs | CPU: 0% Standby      ",
            "  ============================================================================",
            ""
        ]

        try:
            with open(tty_device, "w", encoding="utf-8") as f:
                f.write("\033[2J\033[H\033[?25l" + "\n".join(screen) + "\n")
                f.flush()
        except PermissionError:
            logger.debug("Insufficient permissions to write idle screen to %s", tty_device)
        except Exception as e:
            logger.debug("Failed to write idle screen to console %s: %s", tty_device, e)

    def transition_to_idle(self) -> None:
        """Transitions state machine to IDLE state and renders the static console screen."""
        logger.info("Transitioning to IDLE state (Zero-CPU Mode).")
        self.state = self.STATE_IDLE
        self.active_song_id = None
        self.last_pause_state = False

        # Ensure any video playback is stopped (Zero CPU)
        self.display.stop(timeout=1.0)

        # Update network and render static promo + QR screen
        self.network.update()
        self.render_idle_screen()

    def transition_to_playing(self, song_title: str, stream_url: str) -> None:
        """Transitions state machine to PLAYING state for the requested song."""
        logger.info("Transitioning to PLAYING state: '%s'", song_title)
        self.state = self.STATE_PLAYING
        self.active_song_id = stream_url
        self.playback_start_time = time.time()

        # Display loading notification on console
        self.write_console_status(f"Starting track: {song_title}...")

        # 1. Check local storage first, fallback to HTTP stream
        local_path = self._find_local_song_file(song_title)
        target = local_path if local_path else self.client.resolve_media_url(stream_url)
        logger.info("Selected playback target for '%s': %s", song_title, target)

        # 2. Start hardware video playback
        started = self.display.start_playback(media_target=target)
        if not started and local_path:
            logger.warning("Local playback failed for %s. Retrying via HTTP stream URL...", target)
            stream_target = self.client.resolve_media_url(stream_url)
            started = self.display.start_playback(media_target=stream_target)

        # 3. Notify PiKaraoke so backend sets is_playing = True
        self.client.notify_start_song(stream_url=stream_url)

        if not started:
            logger.error("Failed to start playback for: %s", song_title)
            # Revert to idle without calling notify_end_song so queue is not silently dropped
            self.transition_to_idle()

    def step(self) -> None:
        """Single tick of the orchestrator state machine."""
        # 1. Check network IP and update console if migrated
        ip_changed, current_url = self.network.update()
        if ip_changed and self.state == self.STATE_IDLE:
            logger.info("IP address changed (%s). Refreshing idle console screen...", current_url)
            self.render_idle_screen()

        # 2. Query PiKaraoke now_playing status
        now_playing_data = self.client.get_now_playing()

        # Handle states
        if self.state == self.STATE_BOOT:
            self.transition_to_idle()

        elif self.state == self.STATE_IDLE:
            if now_playing_data and now_playing_data.get("now_playing") and now_playing_data.get("now_playing_url"):
                song_title = now_playing_data.get("now_playing")
                stream_url = now_playing_data.get("now_playing_url")
                self.transition_to_playing(song_title, stream_url)

        elif self.state == self.STATE_PLAYING:
            # Check if MPV process is still running
            if not self.display.is_running():
                duration = time.time() - getattr(self, "playback_start_time", 0)
                logger.info("Playback process exited after %.1fs.", duration)
                if duration >= 3.0:
                    logger.info("Track completed normally. Notifying PiKaraoke.")
                    self.client.notify_end_song(reason="complete")
                else:
                    logger.warning("Playback exited prematurely (%.1fs). Avoiding accidental track drop.", duration)
                self.transition_to_idle()
                return

            # Check if PiKaraoke cleared the song (e.g. user clicked Skip in web UI)
            if now_playing_data:
                current_song = now_playing_data.get("now_playing")
                current_url = now_playing_data.get("now_playing_url")

                if not current_song or not current_url:
                    logger.info("PiKaraoke reports no active track. Halting playback...")
                    self.display.stop(timeout=1.0)
                    self.transition_to_idle()
                    return

                # Check pause state synchronization
                is_paused = bool(now_playing_data.get("is_paused"))
                if is_paused != self.last_pause_state:
                    logger.info("Syncing pause state: is_paused=%s", is_paused)
                    self.display.pause_toggle()
                    self.last_pause_state = is_paused

    def write_console_status(self, message: str, tty_device: str = "/dev/tty1") -> None:
        """
        Renders a clean appliance startup status banner to the local framebuffer / tty1 console.
        This provides clear visual feedback on the HDMI output during boot before the display
        engine takes over.
        """
        ip = self.network.get_ip_address()
        web_url = f"http://{ip}:{self.network.port}" if ip else f"http://127.0.0.1:{self.network.port}"
        portal_url = f"http://{ip}:8888" if ip else "http://192.168.4.1:8888"

        banner = [
            "",
            "  ================================================================",
            "                   KARAOKE-ZERO APPLIANCE BOOT                    ",
            "  ================================================================",
            "   Hardware:   Raspberry Pi Zero W (ARMv6, VideoCore IV GPU)      ",
            "   Display:    MPV direct DRM/KMS (No X11 / Wayland)              ",
            "   Audio:      HDMI / 3.5mm P2 Audio (vc4-hdmi via ALSA)          ",
            f"   Network IP: {ip or 'Connecting to Wi-Fi...'}",
            f"   PiKaraoke:  {web_url}",
            f"   Portal:     {portal_url}",
            "  ----------------------------------------------------------------",
            f"   Status:     {message}",
            "  ================================================================",
            ""
        ]

        try:
            with open(tty_device, "w", encoding="utf-8") as f:
                f.write("\033[2J\033[H\033[?25l" + "\n".join(banner) + "\n")
                f.flush()
        except PermissionError:
            logger.debug("Insufficient permissions to write to %s", tty_device)
        except Exception as e:
            logger.debug("Failed to write status to console %s: %s", tty_device, e)

    def wait_for_backend(self, max_wait_seconds: float = 120.0) -> bool:
        """
        Waits for PiKaraoke web service to become operational while outputting status
        to the local HDMI console (/dev/tty1).
        """
        logger.info("Awaiting PiKaraoke service readiness at %s...", self.pikaraoke_url)
        start_time = time.time()
        while self.running and (time.time() - start_time < max_wait_seconds):
            if self.client.is_healthy():
                self.write_console_status("PiKaraoke is ready! Starting display engine...")
                time.sleep(1.0)
                return True

            elapsed = int(time.time() - start_time)
            self.write_console_status(f"Waiting for PiKaraoke to start (elapsed {elapsed}s)...")
            time.sleep(2.0)

        logger.warning("Timed out waiting for PiKaraoke. Proceeding with startup anyway...")
        return False

    def run(self) -> None:
        """Runs the main orchestrator daemon loop."""
        self.setup_signals()
        self.running = True
        logger.info("Starting KaraokeZero Orchestrator Daemon (Target: %s)", self.pikaraoke_url)

        # Wait for backend and display boot progress on /dev/tty1
        self.wait_for_backend()

        # Setup Socket.IO callbacks and initiate connection
        self.client.on_skip_callback = self.on_skip_event
        self.client.connect_socketio()

        # Initial transition to IDLE
        self.transition_to_idle()

        try:
            while self.running:
                self.step()
                time.sleep(self.poll_interval)
        except Exception as e:
            logger.exception("Unexpected error in orchestrator loop: %s", e)
        finally:
            self.cleanup()

    def cleanup(self) -> None:
        """Performs graceful resource cleanup on shutdown."""
        logger.info("Cleaning up Orchestrator resources...")
        self.state = self.STATE_SHUTDOWN
        self.client.disconnect()
        self.display.stop(timeout=2.0)
        logger.info("Orchestrator stopped cleanly.")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="KaraokeZero Module 2 - Display & Queue Orchestrator Daemon"
    )
    parser.add_argument(
        "--pikaraoke-url",
        default=os.environ.get("PIKARAOKE_URL", "http://127.0.0.1:5555"),
        help="Base URL for local PiKaraoke service (default: http://127.0.0.1:5555)"
    )
    parser.add_argument(
        "--interface",
        default=os.environ.get("NET_INTERFACE", "wlan0"),
        help="Network interface to monitor for IP detection (default: wlan0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PORT", "5555")),
        help="PiKaraoke web port for QR code generation (default: 5555)"
    )
    parser.add_argument(
        "--bg-video",
        default=os.environ.get("BG_VIDEO"),
        help="Path to custom idle background video"
    )
    parser.add_argument(
        "--vout",
        default=os.environ.get("MPV_VOUT", "gpu"),
        help="MPV video output module (default: gpu for RPi VideoCore IV DRM/KMS)"
    )
    parser.add_argument(
        "--aout",
        default=os.environ.get("MPV_AOUT", "alsa"),
        help="MPV audio output module (default: alsa)"
    )
    parser.add_argument(
        "--alsa-device",
        default=os.environ.get("ALSA_DEVICE", "alsa/plughw:CARD=vc4hdmi,DEV=0"),
        help="ALSA audio device (default: alsa/plughw:CARD=vc4hdmi,DEV=0)"
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=float(os.environ.get("POLL_INTERVAL", "1.0")),
        help="Polling interval in seconds (default: 1.0)"
    )
    parser.add_argument(
        "--no-rc",
        action="store_true",
        help="Disable MPV IPC Unix domain socket interface"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    daemon = OrchestratorDaemon(
        pikaraoke_url=args.pikaraoke_url,
        interface=args.interface,
        port=args.port,
        bg_video_path=args.bg_video,
        vout=args.vout,
        aout=args.aout,
        alsa_device=args.alsa_device,
        poll_interval=args.poll_interval,
        enable_rc=not args.no_rc
    )
    daemon.run()
