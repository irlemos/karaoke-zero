#!/usr/bin/env python3
"""
KaraokeZero - Module 2: Orchestrator Daemon
Display & Hardware-Accelerated Video Rendering Manager

Controls cvlc subprocess instances for framebuffer playback with MMAL hardware decoding,
logo overlay for QR codes, and zero-GUI overhead.
"""

import logging
import os
import signal
import socket
import subprocess
import time
from typing import List, Optional

logger = logging.getLogger("Orchestrator.DisplayManager")


class DisplayManager:
    """
    Subprocess manager for cvlc hardware-accelerated playback directly on the framebuffer.
    """

    def __init__(
        self,
        vout: str = "mmal_vout",
        aout: str = "alsa",
        alsa_device: str = "default",
        rc_socket_path: str = "/tmp/vlc_rc.sock",
        enable_rc: bool = True
    ):
        self.vout = vout
        self.aout = aout
        self.alsa_device = alsa_device
        self.rc_socket_path = rc_socket_path
        self.enable_rc = enable_rc
        self.process: Optional[subprocess.Popen] = None
        self.current_mode: str = "stopped"  # "stopped", "idle", "playing"
        self.current_media: Optional[str] = None

    def _build_base_args(self) -> List[str]:
        """Constructs core low-overhead VLC CLI flags."""
        args = [
            "cvlc",
            "-I", "dummy",
            "--fullscreen",
            "--no-osd",
            "--no-video-title-show",
            "--quiet"
        ]

        if self.vout:
            args.extend(["--vout", self.vout])

        if self.enable_rc:
            # Clean up stale socket file if present
            if os.path.exists(self.rc_socket_path):
                try:
                    os.unlink(self.rc_socket_path)
                except OSError:
                    pass
            args.extend(["--extraintf", "rc", "--rc-unix", self.rc_socket_path])

        return args

    def is_running(self) -> bool:
        """Returns True if the VLC subprocess is actively running."""
        if self.process is None:
            return False
        return self.process.poll() is None

    def stop(self, timeout: float = 2.0) -> None:
        """
        Gracefully terminates the active VLC process.
        Escalates from SIGTERM to SIGKILL if the process fails to exit.
        """
        if not self.is_running():
            self.process = None
            self.current_mode = "stopped"
            self.current_media = None
            return

        proc = self.process
        logger.debug("Stopping VLC process (PID %d)...", proc.pid)

        try:
            proc.terminate()
            try:
                proc.wait(timeout=timeout)
                logger.debug("VLC process (PID %d) terminated gracefully.", proc.pid)
            except subprocess.TimeoutExpired:
                logger.warning("VLC process did not terminate within %0.1fs. Sending SIGKILL...", timeout)
                proc.kill()
                proc.wait(timeout=1.0)
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.error("Error stopping VLC process: %s", e)
        finally:
            self.process = None
            self.current_mode = "stopped"
            self.current_media = None
            if os.path.exists(self.rc_socket_path):
                try:
                    os.unlink(self.rc_socket_path)
                except OSError:
                    pass

    def start_idle(self, video_path: str, qr_code_path: Optional[str] = None) -> bool:
        """
        Launches VLC in continuous loop mode playing the idle background video.
        Optionally overlays the QR code logo on the bottom-right corner.
        """
        self.stop(timeout=1.0)

        is_url = video_path.startswith("http://") or video_path.startswith("https://")
        if not is_url and not os.path.exists(video_path):
            logger.error("Background video file not found: %s", video_path)
            return False

        args = self._build_base_args()
        args.append("--loop")

        # Configure VLC logo sub-source filter for QR code overlay
        # Position 9 = bottom-right in VLC logo position matrix
        if qr_code_path and os.path.exists(qr_code_path):
            args.extend([
                "--sub-source", "logo",
                "--logo-file", qr_code_path,
                "--logo-position", "9",
                "--logo-opacity", "240"
            ])
            logger.info("Applying QR code overlay from: %s", qr_code_path)

        args.append(video_path)

        logger.info("Starting IDLE screen via cvlc (vout=%s)...", self.vout)
        logger.debug("Command: %s", " ".join(args))

        try:
            self.process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None
            )
            self.current_mode = "idle"
            self.current_media = video_path
            return True
        except Exception as e:
            logger.exception("Failed to spawn idle VLC process: %s", e)
            self.process = None
            self.current_mode = "stopped"
            return False

    def start_playback(self, media_target: str) -> bool:
        """
        Launches hardware-accelerated playback for the active song.
        Plays once and exits immediately (--play-and-exit).
        """
        self.stop(timeout=1.0)

        args = self._build_base_args()
        args.append("--play-and-exit")

        if self.aout:
            args.extend(["--aout", self.aout])
        if self.alsa_device:
            args.extend(["--alsa-audio-device", self.alsa_device])

        args.append(media_target)

        logger.info("Starting song playback for: %s", media_target)
        logger.debug("Command: %s", " ".join(args))

        try:
            self.process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None
            )
            self.current_mode = "playing"
            self.current_media = media_target
            return True
        except Exception as e:
            logger.exception("Failed to start song playback: %s", e)
            self.process = None
            self.current_mode = "stopped"
            return False

    def send_rc_command(self, command: str) -> bool:
        """
        Sends an interactive control command (e.g. 'pause', 'volume 256')
        to the running VLC instance via Unix domain socket.
        """
        if not self.is_running() or not self.enable_rc:
            return False

        if not os.path.exists(self.rc_socket_path):
            return False

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1.0)
                client.connect(self.rc_socket_path)
                client.sendall(f"{command.strip()}\n".encode("utf-8"))
                return True
        except Exception as e:
            logger.debug("Failed to send RC command '%s': %s", command, e)
            return False

    def pause_toggle(self) -> bool:
        """Toggles playback pause state."""
        return self.send_rc_command("pause")
