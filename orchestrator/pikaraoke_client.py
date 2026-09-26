#!/usr/bin/env python3
"""
KaraokeZero - Module 2: Orchestrator Daemon
PiKaraoke Client & Event Coordinator

Interfaces with the upstream PiKaraoke service via REST endpoints and real-time
Socket.IO events to monitor queue status, playback triggers, and track progression.
"""

import json
import logging
import time
from typing import Any, Callable, Dict, Optional
import urllib.request
import urllib.error

logger = logging.getLogger("Orchestrator.PiKaraokeClient")

# Graceful optional dependency for python-socketio
try:
    import socketio
    HAS_SOCKETIO = True
except ImportError:
    HAS_SOCKETIO = False


class PiKaraokeClient:
    """
    Client for interacting with local PiKaraoke server.
    Supports hybrid operation: Socket.IO event listener with REST polling fallback.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:5555",
        timeout: float = 2.0
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.sio: Optional[Any] = None
        self.connected_socket: bool = False

        # Callbacks
        self.on_skip_callback: Optional[Callable[[], None]] = None
        self.on_state_change_callback: Optional[Callable[[Dict[str, Any]], None]] = None

    def get_now_playing(self) -> Optional[Dict[str, Any]]:
        """
        Polls the public GET /now_playing endpoint.
        Returns parsed JSON dictionary or None if unreachable.
        """
        url = f"{self.base_url}/now_playing"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "KaraokeZero-Orchestrator/1.0"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    raw = resp.read().decode("utf-8").strip()
                    if raw:
                        return json.loads(raw)
        except urllib.error.URLError as e:
            logger.debug("PiKaraoke not yet available at %s: %s", url, e)
        except Exception as e:
            logger.debug("Error reading /now_playing: %s", e)

        return None

    def is_healthy(self) -> bool:
        """Returns True if the PiKaraoke server is reachable and responding."""
        url = f"{self.base_url}/"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "KaraokeZero-Orchestrator/1.0"}
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def resolve_media_url(self, relative_or_absolute_url: str) -> str:
        """Converts relative stream endpoints (e.g. /stream/abc.mp4) to full HTTP URLs."""
        if relative_or_absolute_url.startswith("http://") or relative_or_absolute_url.startswith("https://"):
            return relative_or_absolute_url
        if not relative_or_absolute_url.startswith("/"):
            relative_or_absolute_url = f"/{relative_or_absolute_url}"
        return f"{self.base_url}{relative_or_absolute_url}"

    def notify_start_song(self) -> bool:
        """
        Emits start_song to PiKaraoke via Socket.IO if connected.
        """
        if self.connected_socket and self.sio:
            try:
                self.sio.emit("start_song")
                logger.debug("Emitted 'start_song' via Socket.IO")
                return True
            except Exception as e:
                logger.warning("Failed to emit start_song: %s", e)
        return False

    def notify_end_song(self, reason: str = "complete") -> bool:
        """
        Notifies PiKaraoke that the track has finished so the queue can advance.
        Emits 'end_song' event via Socket.IO.
        """
        if self.connected_socket and self.sio:
            try:
                self.sio.emit("end_song", reason)
                logger.info("Emitted 'end_song' (%s) via Socket.IO", reason)
                return True
            except Exception as e:
                logger.warning("Failed to emit end_song: %s", e)

        # Fallback: POST /skip if Socket.IO is unavailable and track needs advancement
        try:
            req = urllib.request.Request(
                f"{self.base_url}/skip",
                data=b"",
                headers={"User-Agent": "KaraokeZero-Orchestrator/1.0"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                logger.info("Advanced song via REST fallback /skip (status: %d)", resp.status)
                return resp.status in (200, 302)
        except Exception as e:
            logger.debug("REST skip fallback error: %s", e)

        return False

    def connect_socketio(self) -> bool:
        """
        Initializes background Socket.IO connection for real-time push events.
        """
        if not HAS_SOCKETIO:
            logger.info("python-socketio not installed. Using high-efficiency REST polling.")
            return False

        try:
            self.sio = socketio.Client(reconnection=True, reconnection_delay=2)

            @self.sio.event
            def connect():
                self.connected_socket = True
                logger.info("Connected to PiKaraoke Socket.IO at %s", self.base_url)

            @self.sio.event
            def disconnect():
                self.connected_socket = False
                logger.info("Disconnected from PiKaraoke Socket.IO")

            @self.sio.on("skip")
            def on_skip(data=None):
                logger.info("Received 'skip' event from PiKaraoke")
                if self.on_skip_callback:
                    self.on_skip_callback()

            @self.sio.on("now_playing_update")
            def on_update(data=None):
                logger.debug("Received 'now_playing_update' event: %s", data)
                if self.on_state_change_callback and isinstance(data, dict):
                    self.on_state_change_callback(data)

            self.sio.connect(
                self.base_url,
                socketio_path="/socket.io",
                transports=["websocket", "polling"],
                wait_timeout=3
            )
            return True
        except Exception as e:
            logger.debug("Could not establish initial Socket.IO connection (%s). Will retry in background.", e)
            self.connected_socket = False
            return False

    def disconnect(self) -> None:
        """Disconnects Socket.IO client if active."""
        if self.sio and self.connected_socket:
            try:
                self.sio.disconnect()
            except Exception:
                pass
        self.connected_socket = False
