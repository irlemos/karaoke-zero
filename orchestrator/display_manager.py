#!/usr/bin/env python3
"""
KaraokeZero - Module 2: Orchestrator Daemon
Display & Hardware-Accelerated Video Rendering Manager

Controls mpv subprocess instances for direct DRM/KMS playback with VideoCore IV
hardware decoding (v4l2m2m-copy), ALSA hardware audio, and zero-GUI overhead.
"""

import json
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
    Subprocess manager for mpv hardware-accelerated playback directly on DRM/KMS.
    """

    def __init__(
        self,
        vout: str = "gpu",
        aout: str = "alsa",
        alsa_device: str = "alsa/plughw:CARD=vc4hdmi,DEV=0",
        rc_socket_path: str = "/tmp/mpv.sock",
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
        """Constructs core low-overhead MPV CLI flags for RPi VideoCore IV GPU."""
        args = [
            "mpv",
            f"--vo={self.vout}",
            "--gpu-context=drm",
            "--hwdec=v4l2m2m-copy",
            "--profile=fast",
            "--no-terminal",
            "--quiet"
        ]

        if self.enable_rc:
            if os.path.exists(self.rc_socket_path):
                try:
                    os.unlink(self.rc_socket_path)
                except OSError:
                    pass
            args.append(f"--input-ipc-server={self.rc_socket_path}")

        return args

    def is_running(self) -> bool:
        """Returns True if the mpv subprocess is actively running."""
        if self.process is None:
            return False
        return self.process.poll() is None

    def stop(self, timeout: float = 2.0) -> None:
        """
        Gracefully terminates the active mpv process.
        Escalates from IPC quit to SIGTERM to SIGKILL if the process fails to exit.
        """
        if not self.is_running():
            self.process = None
            self.current_mode = "stopped"
            self.current_media = None
            return

        proc = self.process
        logger.debug("Stopping mpv process (PID %d)...", proc.pid)

        # Try graceful IPC quit first
        self.send_ipc_command(["quit"])

        try:
            try:
                proc.wait(timeout=timeout)
                logger.debug("mpv process (PID %d) terminated gracefully.", proc.pid)
            except subprocess.TimeoutExpired:
                logger.warning("mpv process did not terminate within %0.1fs. Sending SIGTERM...", timeout)
                proc.terminate()
                try:
                    proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    logger.warning("mpv process did not terminate after SIGTERM. Sending SIGKILL...")
                    proc.kill()
                    proc.wait(timeout=1.0)
        except ProcessLookupError:
            pass
        except Exception as e:
            logger.error("Error stopping mpv process: %s", e)
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
        Launches mpv in continuous loop mode playing the idle background video.
        Uses --no-audio for zero audio-driver overhead during standby.
        """
        self.stop(timeout=1.0)

        is_url = video_path.startswith("http://") or video_path.startswith("https://")
        if not is_url and not os.path.exists(video_path):
            logger.error("Background video file not found: %s", video_path)
            return False

        args = self._build_base_args()
        args.extend([
            "--no-audio",
            "--loop-file=inf"
        ])

        args.append(video_path)

        logger.info("Starting IDLE screen via mpv (vo=%s, gpu-context=drm)...", self.vout)
        logger.debug("Command: %s", " ".join(args))

        try:
            with open("/tmp/mpv_stderr.log", "w", encoding="utf-8") as log_file:
                self.process = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=log_file,
                    stdin=subprocess.DEVNULL,
                    preexec_fn=os.setsid if hasattr(os, "setsid") else None
                )

            # Brief check if mpv exited on launch
            time.sleep(0.1)
            exit_code = self.process.poll()
            if exit_code is not None:
                err_snippet = self._read_last_log_snippet()
                logger.error("mpv idle process exited immediately with code %s. Detail: %s", exit_code, err_snippet)
                self.process = None
                self.current_mode = "stopped"
                return False

            self.current_mode = "idle"
            self.current_media = video_path
            return True
        except Exception as e:
            logger.exception("Failed to spawn idle mpv process: %s", e)
            self.process = None
            self.current_mode = "stopped"
            return False

    def start_playback(self, media_target: str) -> bool:
        """
        Launches hardware-accelerated playback for the active song.
        Routes audio directly to ALSA (HDMI / P2 adapter) and exits on completion.
        """
        self.stop(timeout=1.0)

        args = self._build_base_args()
        args.extend([
            f"--ao={self.aout}",
            f"--audio-device={self.alsa_device}",
            "--audio-samplerate=48000",
            media_target
        ])

        logger.info("Starting song playback via mpv for: %s", media_target)
        logger.debug("Command: %s", " ".join(args))

        try:
            with open("/tmp/mpv_stderr.log", "w", encoding="utf-8") as log_file:
                self.process = subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=log_file,
                    stdin=subprocess.DEVNULL,
                    preexec_fn=os.setsid if hasattr(os, "setsid") else None
                )

            time.sleep(0.1)
            exit_code = self.process.poll()
            if exit_code is not None:
                err_snippet = self._read_last_log_snippet()
                logger.error("mpv playback process exited immediately with code %s. Detail: %s", exit_code, err_snippet)
                self.process = None
                self.current_mode = "stopped"
                return False

            self.current_mode = "playing"
            self.current_media = media_target
            return True
        except Exception as e:
            logger.exception("Failed to start song playback: %s", e)
            self.process = None
            self.current_mode = "stopped"
            return False

    def _read_last_log_snippet(self, log_path: str = "/tmp/mpv_stderr.log", max_lines: int = 5) -> str:
        """Reads recent lines from the mpv log file for diagnostic reporting."""
        if not os.path.exists(log_path):
            return "No log file found"
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                return " ".join([l.strip() for l in lines[-max_lines:] if l.strip()])
        except Exception:
            return "Could not read log file"

    def send_ipc_command(self, command_args: List) -> bool:
        """
        Sends a JSON-RPC command list to the mpv IPC Unix domain socket.
        Example: ['cycle', 'pause'] or ['set_property', 'volume', 80].
        """
        if not self.is_running() or not self.enable_rc:
            return False

        if not os.path.exists(self.rc_socket_path):
            return False

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1.0)
                client.connect(self.rc_socket_path)
                payload = json.dumps({"command": command_args}) + "\n"
                client.sendall(payload.encode("utf-8"))
                return True
        except Exception as e:
            logger.debug("Failed to send MPV IPC command %s: %s", command_args, e)
            return False

    def send_rc_command(self, command: str) -> bool:
        """
        Backward-compatible control command dispatcher.
        """
        cmd_str = command.strip().lower()
        if cmd_str == "pause":
            return self.pause_toggle()
        return self.send_ipc_command([command.strip()])

    def pause_toggle(self) -> bool:
        """Toggles playback pause state."""
        return self.send_ipc_command(["cycle", "pause"])

