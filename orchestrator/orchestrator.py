#!/usr/bin/env python3
"""
KaraokeZero - Module 2: Orchestrator Daemon
Main Service Coordinator & Display FSM Engine

Coordinates PiKaraoke status, hardware-accelerated MPV framebuffer rendering,
and dynamic QR code generation on Raspberry Pi Zero W without X11/Chromium.
"""

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from typing import Optional

from display_manager import DisplayManager
from network_watcher import NetworkWatcher
from pikaraoke_client import PiKaraokeClient
from screen_generator import ScreenGenerator
from storage_validator import StorageValidator, StorageValidationResult


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
    STATE_STORAGE_ERROR = "STORAGE_ERROR"
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

        # Graphical idle details screen generator and output path
        self.idle_screen_path = os.environ.get("IDLE_SCREEN_PATH", "/tmp/karaoke_idle_screen.png")
        self.storage_error_screen_path = os.environ.get("STORAGE_ERROR_SCREEN_PATH", "/tmp/karaoke_storage_error.png")
        self.screen_generator = ScreenGenerator(output_path=self.idle_screen_path)

        # Storage validator subsystem
        self.storage_validator = StorageValidator()

        # Background video resolution
        self.bg_video = self._resolve_background_video(bg_video_path)

        # Track state
        self.active_song_id: Optional[str] = None
        self.last_pause_state: bool = False

    def _resolve_background_video(self, custom_path: Optional[str]) -> Optional[str]:
        """
        Validates custom background video path if explicitly provided via CLI/env.
        Automatic fallback searching for bundled videos (e.g. night_sea.mp4) is
        disabled to prevent unnecessary CPU/GPU load on Pi Zero W and guarantee
        the high-contrast graphical details screen with QR code is always displayed during idle.
        """
        if custom_path and os.path.isfile(custom_path):
            logger.info("Using explicitly configured background video: %s", custom_path)
            return custom_path

        logger.info("No custom background video configured; using static graphical details screen (Zero CPU).")
        return None

    def _update_idle_screen(self) -> str:
        """
        Generates or refreshes the graphical details screen image.
        Returns the path to the rendered idle image.
        """
        ip = self.network.get_ip_address()
        qr_path = self.network.qr_output_path if os.path.exists(self.network.qr_output_path) else None
        ssid = self.network.get_ssid()
        self.screen_generator.generate(
            output_path=self.idle_screen_path,
            qr_path=qr_path,
            ip_address=ip,
            port=self.network.port,
            wifi_ssid=ssid,
            status_text="SYSTEM READY  |  0 ACTIVE SONGS IN QUEUE  |  STANDBY"
        )
        return self.idle_screen_path

    def _resolve_idle_media(self) -> str:
        """
        Determines active idle media target:
        Uses custom background video if explicitly configured and existing on disk,
        otherwise uses the dynamically generated graphical details screen.
        """
        if self.bg_video and os.path.isfile(self.bg_video):
            return self.bg_video
        return self._update_idle_screen()


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
            self.clear_console()
            self.display.stop(timeout=1.0)
            self.transition_to_idle()

    def on_restart_event(self) -> None:
        """Callback triggered when a restart event is received via WebSocket."""
        logger.info("Restart triggered. Resetting current track playback to beginning (0:00)...")
        if self.state == self.STATE_PLAYING:
            self.playback_start_time = time.time()
            self.last_pause_state = False
            self.display.restart_playback()

    def on_pause_event(self) -> None:
        """Callback triggered when a pause event is received via WebSocket."""
        logger.info("Pause triggered via WebSocket.")
        if self.state == self.STATE_PLAYING:
            self.display.set_pause(True)
            self.last_pause_state = True

    def on_play_event(self) -> None:
        """Callback triggered when a play event is received via WebSocket."""
        logger.info("Play (resume) triggered via WebSocket.")
        if self.state == self.STATE_PLAYING:
            self.display.set_pause(False)
            self.last_pause_state = False


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

    def clear_console(self, tty_device: str = "/dev/tty1") -> None:
        """
        Clears the Linux virtual terminal and scrollback buffer to pitch black,
        disabling the visible cursor and setting black-on-black attributes.
        Ensures zero text flicker during MPV DRM/KMS transitions.
        """
        try:
            with open(tty_device, "w", encoding="utf-8") as f:
                # \033[2J: Clear entire visible screen
                # \033[3J: Clear terminal scrollback buffer completely
                # \033[H: Move cursor to home position (1,1)
                # \033[?25l: Hide console cursor (suppresses blinking underscore/block)
                # \033[30;40m: Set black foreground on black background
                f.write("\033[2J\033[3J\033[H\033[?25l\033[30;40m")
                f.flush()
        except PermissionError:
            logger.debug("Insufficient permissions to clear console %s", tty_device)
        except Exception as e:
            logger.debug("Failed to clear console %s: %s", tty_device, e)

    def render_idle_screen(self, tty_device: str = "/dev/tty1") -> None:
        """
        Ensures the local HDMI console (/dev/tty1) remains clean and pitch black
        beneath the graphical MPV DRM/KMS idle display, preventing text flickers.
        """
        self.clear_console(tty_device)

    def transition_to_idle(self) -> None:
        """Transitions state machine to IDLE state and activates the graphical details screen."""
        logger.info("Transitioning to IDLE state (Activating Graphical Details Screen).")
        self.state = self.STATE_IDLE
        self.active_song_id = None
        self.last_pause_state = False

        # Ensure HDMI console is clean and pitch black
        self.clear_console()

        # Ensure network IP and QR code are refreshed
        self.network.update()

        # Resolve and activate idle media via MPV DRM/KMS
        target_media = self._resolve_idle_media()
        self.display.start_idle(media_path=target_media)

        # Also ensure tty1 console remains dark beneath the graphical display
        self.render_idle_screen()

    def transition_to_playing(self, song_title: str, stream_url: str) -> None:
        """Transitions state machine to PLAYING state for the requested song."""
        logger.info("Transitioning to PLAYING state: '%s'", song_title)
        self.state = self.STATE_PLAYING
        self.active_song_id = stream_url
        self.playback_start_time = time.time()

        # Clear HDMI console to solid black before stopping idle and starting video
        self.clear_console()

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
        # 0. Storage Error state: keep emergency warning screen active and halt processing
        if self.state == self.STATE_STORAGE_ERROR:
            if not self.display.is_running():
                self.display.start_idle(media_path=self.storage_error_screen_path)
            return

        # 1. Check network IP and update display if migrated
        ip_changed, current_url = self.network.update()
        if ip_changed and self.state == self.STATE_IDLE:
            logger.info("IP address changed (%s). Refreshing idle display...", current_url)
            target_media = self._resolve_idle_media()
            self.display.start_idle(media_path=target_media)
            self.render_idle_screen()

        # 2. Watchdog: ensure idle screen remains actively displayed while in IDLE state
        if self.state == self.STATE_IDLE and not self.display.is_running():
            logger.warning("Idle display process is not running. Restarting idle screen...")
            target_media = self._resolve_idle_media()
            self.display.start_idle(media_path=target_media)

        # 3. Query PiKaraoke now_playing status
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
                # Immediately ensure console is clean and pitch black
                self.clear_console()
                duration = time.time() - getattr(self, "playback_start_time", 0)
                logger.info("Playback process exited after %.1fs.", duration)
                if duration >= 3.0:
                    logger.info("Track completed normally. Notifying PiKaraoke.")
                    self.client.notify_end_song(reason="complete")

                    # Check if another track is already queued in PiKaraoke to avoid
                    # flashing the idle screen between consecutive songs.
                    time.sleep(0.3)
                    next_track = self.client.get_now_playing()
                    if next_track and next_track.get("now_playing") and next_track.get("now_playing_url"):
                        next_title = next_track.get("now_playing")
                        next_url = next_track.get("now_playing_url")
                        if next_url != self.active_song_id:
                            logger.info("Advancing directly to next queued song: '%s'", next_title)
                            self.transition_to_playing(next_title, next_url)
                            return
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
                    self.clear_console()
                    self.display.stop(timeout=1.0)
                    self.transition_to_idle()
                    return

                # Check pause state synchronization
                is_paused = bool(now_playing_data.get("is_paused"))
                if is_paused != self.last_pause_state:
                    logger.info("Syncing pause state: is_paused=%s", is_paused)
                    self.display.set_pause(is_paused)
                    self.last_pause_state = is_paused

    def write_console_status(self, message: str, tty_device: str = "/dev/tty1") -> None:
        """
        Logs appliance status and guarantees local console (/dev/tty1) remains pitch black.
        Avoids printing ASCII banners that cause visible text mode flickers between video scenes.
        """
        logger.info("Status: %s", message)
        self.clear_console(tty_device)

    def wait_for_backend(self, max_wait_seconds: float = 120.0, min_display_seconds: float = 2.5) -> bool:
        """
        Waits for PiKaraoke web service to become operational while outputting status
        both graphically via MPV DRM/KMS and keeping the local HDMI console (/dev/tty1) clean.
        Enforces min_display_seconds so the boot splash and progress bar are always seen.
        """
        logger.info("Awaiting PiKaraoke service readiness at %s...", self.pikaraoke_url)
        start_time = time.time()

        # Ensure HDMI console is clean and pitch black before any initial screen
        self.clear_console()

        # Render initial boot/startup screen so HDMI output is graphical from the earliest stage
        boot_screen = "/tmp/karaoke_boot_screen.png"
        try:
            if self.screen_generator.generate_boot_screen(
                output_path=boot_screen,
                status_text="Starting PiKaraoke appliance services...",
                progress=0.25
            ):
                if not self.display.is_running() or self.display.current_mode != "boot":
                    self.display.start_boot_screen(boot_screen)
                else:
                    self.display.update_boot_screen(boot_screen)
        except Exception as e:
            logger.debug("Initial graphical boot screen note: %s", e)

        while self.running and (time.time() - start_time < max_wait_seconds):
            elapsed = time.time() - start_time
            if self.client.is_healthy():
                # Ensure the loading screen and progress bar are clearly visible to user
                if elapsed < min_display_seconds:
                    time.sleep(min_display_seconds - elapsed)

                self.write_console_status("PiKaraoke is ready! Starting display engine...")
                try:
                    if self.screen_generator.generate_boot_screen(
                        output_path=boot_screen,
                        status_text="Starting PiKaraoke appliance services...",
                        progress=1.0
                    ):
                        self.display.update_boot_screen(boot_screen)
                except Exception:
                    pass
                time.sleep(0.8)
                # Cleanly dismiss boot splash screen so idle screen spawns cleanly on DRM/KMS
                self.display.stop(timeout=1.0)
                self.clear_console()
                return True

            elapsed_int = int(elapsed)
            self.write_console_status(f"Waiting for PiKaraoke to start (elapsed {elapsed_int}s)...")

            # Progressively advance bar from 0.25 to 0.92 so user sees active progress
            pct = min(0.92, 0.25 + (elapsed / max_wait_seconds) * 0.67)
            try:
                if self.screen_generator.generate_boot_screen(
                    output_path=boot_screen,
                    status_text="Starting PiKaraoke appliance services...",
                    progress=pct
                ):
                    self.display.update_boot_screen(boot_screen)
            except Exception:
                pass

            time.sleep(2.0)

        logger.warning("Timed out waiting for PiKaraoke. Proceeding with startup anyway...")
        self.display.stop(timeout=1.0)
        self.clear_console()
        return False

    def validate_storage_on_boot(self, max_wait_seconds: float = 6.0) -> StorageValidationResult:
        """
        Validates external storage readiness during early boot.
        Displays graphical boot splash while waiting for USB block devices to enumerate.
        If storage fails, returns StorageValidationResult with valid=False.
        """
        config = self.storage_validator.detect_storage_configuration()
        if not config.is_external:
            logger.info("Internal MicroSD storage mode active. Bypassing external drive checks.")
            return StorageValidationResult(
                valid=True,
                reason="Internal storage mode active.",
                mount_point=config.mount_point,
                is_external_configured=False
            )

        logger.info("External storage configuration detected (%s -> %s). Verifying drive...",
                    config.storage_device or "USB", config.mount_point)

        # Display initial boot splash early
        boot_screen = "/tmp/karaoke_boot_screen.png"
        try:
            if self.screen_generator.generate_boot_screen(
                output_path=boot_screen,
                status_text="Starting PiKaraoke appliance services...",
                progress=0.10
            ):
                self.display.start_boot_screen(boot_screen)
        except Exception as e:
            logger.debug("Storage boot screen notification: %s", e)

        start_time = time.time()
        last_result = None

        while self.running and (time.time() - start_time < max_wait_seconds):
            last_result = self.storage_validator.validate_storage(mount_point=config.mount_point)
            if last_result.valid:
                logger.info("Storage validation passed: %s is mounted and healthy.", config.mount_point)
                return last_result
            time.sleep(1.0)

        if last_result is None:
            last_result = self.storage_validator.validate_storage(mount_point=config.mount_point)
        return last_result

    def _ensure_services_stopped_for_storage_error(self) -> None:
        """Stops PiKaraoke and Admin Panel to guarantee zero writes to rootfs."""
        try:
            subprocess.run(
                ["systemctl", "stop", "pikaraoke.service", "admin_panel.service"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
        except Exception:
            pass

    def _restart_services_after_storage_recovery(self) -> None:
        """Restarts PiKaraoke and Admin Panel once storage is reconnected and healthy."""
        try:
            subprocess.run(
                ["systemctl", "restart", "admin_panel.service", "pikaraoke.service"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10
            )
        except Exception:
            pass

    def halt_boot_for_storage(self, initial_result: StorageValidationResult) -> None:
        """
        Halts appliance boot when external storage validation fails.
        Renders and displays the warning screen on HDMI via MPV DRM/KMS.
        Enters a frozen loop without modifying any system files or SD card paths,
        allowing the user to resolve the issue (reconnecting drive or power cycling).
        If the drive is reconnected and healthy, unfreezes and resumes boot.
        """
        self.state = self.STATE_STORAGE_ERROR
        val_result = initial_result

        # Stop background services so they do not attempt disk access on rootfs
        self._ensure_services_stopped_for_storage_error()

        # Stop boot splash if running
        self.display.stop(timeout=1.0)
        self.clear_console()

        # Render and display graphical storage error warning screen
        self.screen_generator.generate_storage_error_screen(
            output_path=self.storage_error_screen_path,
            mount_point=val_result.mount_point,
            error_reason=val_result.reason,
            error_code=val_result.error_code or "STORAGE_FAILED"
        )
        self.display.start_idle(media_path=self.storage_error_screen_path)
        self.clear_console()

        logger.critical(
            "====================================================================\n"
            "APPLIANCE BOOT HALTED: STORAGE DISK NOT LOADED\n"
            "Target Mount: %s\n"
            "Error State:  %s\n"
            "Reason:       %s\n"
            "Safe Mode:    Zero files or system settings have been modified.\n"
            "Action:       Reconnect external HD or reinstall if data was lost.\n"
            "====================================================================",
            val_result.mount_point, val_result.error_code, val_result.reason
        )

        # Safe frozen loop: polls for drive reconnection every 3 seconds
        while self.running and self.state == self.STATE_STORAGE_ERROR:
            time.sleep(3.0)

            # Check if external storage has been reconnected and mounted
            recovery_result = self.storage_validator.validate_storage(mount_point=val_result.mount_point)
            if recovery_result.valid:
                logger.info(
                    "External storage [%s] restored and healthy! Unfreezing boot...",
                    recovery_result.mount_point
                )
                self.display.stop(timeout=1.0)
                self.clear_console()
                self.apply_storage_resilience(recovery_result)
                self._restart_services_after_storage_recovery()
                self.state = self.STATE_BOOT
                break

    def apply_storage_resilience(self, storage_result: StorageValidationResult) -> None:
        """
        Applies post-mount resilience procedures:
        1. Purges incomplete download remnants and 0-byte corrupt media files.
        2. Enforces SQLite WAL mode and verifies database integrity.
        3. Syncs saved Wi-Fi profiles from external storage to transient RAM (/run).
        """
        if not storage_result.valid or not storage_result.mount_point:
            return

        mp = storage_result.mount_point
        try:
            logger.info("Applying power-loss resilience and storage sanitization on %s...", mp)
            clean_res = self.storage_validator.sanitize_storage(mp)
            if clean_res.get("cleaned_temp", 0) > 0 or clean_res.get("cleaned_zero_byte", 0) > 0:
                logger.info(
                    "Cleaned %d partial files and %d corrupt 0-byte files.",
                    clean_res.get("cleaned_temp", 0), clean_res.get("cleaned_zero_byte", 0)
                )

            db_res = self.storage_validator.verify_and_repair_sqlite(mp)
            if db_res.get("corrupted", 0) > 0:
                logger.warning("Detected and quarantined %d corrupted database(s).", db_res.get("corrupted", 0))

            wifi_res = self.storage_validator.sync_wifi_profiles_from_storage(mp)
            if wifi_res.get("synced", 0) > 0:
                logger.info("Synchronized %d persistent Wi-Fi profile(s) to transient RAM.", wifi_res.get("synced", 0))
        except Exception as e:
            logger.error("Error during storage resilience execution: %s", e)

    def run(self) -> None:
        """Runs the main orchestrator daemon loop."""
        self.setup_signals()
        self.running = True
        logger.info("Starting KaraokeZero Orchestrator Daemon (Target: %s)", self.pikaraoke_url)

        # Clear local virtual console immediately to eliminate boot logs and cursor
        self.clear_console()

        # Display initial boot splash screen immediately on daemon start
        boot_screen = "/tmp/karaoke_boot_screen.png"
        try:
            if self.screen_generator.generate_boot_screen(
                output_path=boot_screen,
                status_text="Starting PiKaraoke appliance services...",
                progress=0.10
            ):
                self.display.start_boot_screen(boot_screen)
        except Exception as e:
            logger.debug("Initial early boot splash screen note: %s", e)

        # Storage validation and boot halt guard
        storage_result = self.validate_storage_on_boot(max_wait_seconds=6.0)
        if not storage_result.valid:
            logger.critical("External storage validation FAILED on boot. Reason: %s", storage_result.reason)
            self.halt_boot_for_storage(storage_result)
            if not self.running:
                self.cleanup()
                return

        # Execute power-loss resilience, cleanup incomplete downloads, and sync Wi-Fi
        self.apply_storage_resilience(storage_result)

        # Wait for backend and display boot progress on /dev/tty1
        self.wait_for_backend()

        # Setup Socket.IO callbacks and initiate connection
        self.client.on_skip_callback = self.on_skip_event
        self.client.on_restart_callback = self.on_restart_event
        self.client.on_pause_callback = self.on_pause_event
        self.client.on_play_callback = self.on_play_event
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
        self.clear_console()
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
