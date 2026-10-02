#!/usr/bin/env python3
"""
KaraokeZero Desktop Downloader - Local Web Server
Runs a lightweight, zero-dependency local HTTP API and UI server
using pure Python standard library (http.server.ThreadingHTTPServer).
"""

import argparse
import json
import logging
import mimetypes
import os
import shutil
import socket
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

# Ensure local imports work cleanly
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from youtube_search import search_youtube, extract_playlist_info
from download_manager import (
    DownloadManager,
    detect_storage_devices,
    resolve_ytdlp_command
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [Downloader] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("DesktopDownloader.Server")

download_mgr = DownloadManager()
STATIC_DIR = os.path.join(SCRIPT_DIR, "static")


def find_available_port(start_port: int = 7777, max_attempts: int = 20) -> int:
    """Finds an unused TCP port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start_port


class DownloaderRequestHandler(BaseHTTPRequestHandler):
    """Handles REST API requests and serves static web assets."""

    def log_message(self, format: str, *args: Any):
        """Suppress noisy access log lines, logging errors only."""
        if args and str(args[1]) in ("400", "404", "500"):
            logger.warning("%s - %s", self.address_string(), format % args)

    def _send_json(self, status_code: int, data: Dict[str, Any]):
        """Helper to send JSON responses with proper headers."""
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)

    def _read_json_body(self) -> Dict[str, Any]:
        """Reads and parses incoming JSON payload from POST request."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                raw = self.rfile.read(content_length).decode("utf-8")
                return json.loads(raw)
        except Exception as e:
            logger.debug("Failed to parse JSON body: %s", e)
        return {}

    def do_OPTIONS(self):
        """Handle CORS pre-flight requests."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        """Route GET requests."""
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query_params = urllib.parse.parse_qs(parsed_url.query)

        # 1. API: Search YouTube
        if path == "/api/search":
            q = query_params.get("q", [""])[0].strip()
            max_r = int(query_params.get("limit", [15])[0])
            ytdlp_cmd = resolve_ytdlp_command()
            results = search_youtube(q, max_results=max_r, ytdlp_cmd=ytdlp_cmd)
            self._send_json(200, {"success": True, "results": results, "count": len(results)})
            return

        # 2. API: Extract Playlist
        if path == "/api/playlist":
            url = query_params.get("url", [""])[0].strip()
            ytdlp_cmd = resolve_ytdlp_command()
            info = extract_playlist_info(url, ytdlp_cmd=ytdlp_cmd)
            self._send_json(200, info)
            return

        # 3. API: Queue Status
        if path == "/api/queue":
            status = download_mgr.get_queue_status()
            stats = {
                "queued": len(status.get("queued", [])),
                "downloading": len(status.get("active", [])),
                "completed": len(status.get("completed", [])),
                "errors": len(status.get("errors", [])),
                "total": status.get("total_count", 0)
            }
            self._send_json(200, {
                "success": True,
                "status": "ok",
                "queue": status.get("tasks", []),
                "tasks": status.get("tasks", []),
                "stats": stats,
                **status
            })
            return

        # 4. API: Settings & Hardware Storage
        if path == "/api/settings":
            devices = detect_storage_devices()
            ytdlp_cmd = resolve_ytdlp_command()
            ytdlp_exists = shutil.which(ytdlp_cmd[0]) is not None or os.path.isfile(ytdlp_cmd[0])
            ffmpeg_exists = shutil.which("ffmpeg") is not None

            self._send_json(200, {
                "success": True,
                "status": "ok",
                "output_dir": download_mgr.settings.get("output_dir"),
                "quality": download_mgr.settings.get("default_quality", "480"),
                "default_quality": download_mgr.settings.get("default_quality", "480"),
                "available_drives": devices,
                "storage_devices": devices,
                "settings": download_mgr.settings,
                "system": {
                    "ytdlp_available": ytdlp_exists,
                    "ytdlp_path": ytdlp_cmd[0],
                    "ffmpeg_available": ffmpeg_exists
                }
            })
            return

        # 5. Serve Web Static Assets
        if path in ("/", "/index.html"):
            target_file = os.path.join(STATIC_DIR, "index.html")
        else:
            rel_path = path.lstrip("/")
            target_file = os.path.join(STATIC_DIR, rel_path)

        if os.path.isfile(target_file):
            content_type, _ = mimetypes.guess_type(target_file)
            content_type = content_type or "application/octet-stream"
            try:
                with open(target_file, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", f"{content_type}; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            except OSError as e:
                logger.error("Failed to read static asset %s: %s", target_file, e)

        # 404 Not Found
        self._send_json(404, {"success": False, "status": "error", "error": f"Path not found: {path}"})

    def do_POST(self):
        """Route POST requests."""
        path = urllib.parse.urlparse(self.path).path
        body = self._read_json_body()

        # 1. API: Enqueue single song download
        if path == "/api/download":
            url_or_id = body.get("url") or body.get("id")
            if not url_or_id:
                self._send_json(400, {"success": False, "status": "error", "error": "Missing 'url' or 'id' field."})
                return

            task = download_mgr.enqueue_download(
                url_or_id=url_or_id,
                title=body.get("title"),
                uploader=body.get("uploader"),
                duration=body.get("duration"),
                thumbnail=body.get("thumbnail"),
                quality=body.get("quality") or body.get("default_quality")
            )
            self._send_json(200, {"success": True, "status": "ok", "task": task})
            return

        # 2. API: Enqueue batch song downloads (e.g. from playlist or text file)
        if path == "/api/download/batch":
            items = body.get("items") or []
            quality = body.get("quality") or body.get("default_quality")
            if not items:
                self._send_json(400, {"success": False, "status": "error", "error": "No items provided in batch."})
                return

            enqueued = download_mgr.enqueue_batch(items, quality=quality)
            self._send_json(200, {
                "success": True,
                "status": "ok",
                "enqueued_count": len(enqueued),
                "tasks": enqueued
            })
            return

        # 3. API: Cancel task
        if path == "/api/queue/cancel":
            task_id = body.get("task_id")
            if not task_id:
                self._send_json(400, {"success": False, "status": "error", "error": "Missing 'task_id'."})
                return
            ok = download_mgr.cancel_task(task_id)
            self._send_json(200, {"success": ok, "status": "ok" if ok else "error"})
            return

        # 4. API: Clear completed/cancelled
        if path == "/api/queue/clear":
            count = download_mgr.clear_completed()
            self._send_json(200, {"success": True, "status": "ok", "cleared_count": count})
            return

        # 5. API: Pause / Resume queue
        if path == "/api/queue/pause":
            if "paused" in body:
                now_paused = download_mgr.set_paused(bool(body["paused"]))
            else:
                now_paused = download_mgr.set_paused(not download_mgr.is_paused)
            self._send_json(200, {"success": True, "status": "ok", "is_paused": now_paused})
            return

        # 6. API: Update Settings
        if path == "/api/settings":
            new_cfg = {}
            if "output_dir" in body and body["output_dir"]:
                new_cfg["output_dir"] = os.path.abspath(os.path.expanduser(body["output_dir"]))
            q_val = body.get("quality") or body.get("default_quality")
            if q_val:
                new_cfg["default_quality"] = str(q_val)

            updated = download_mgr.save_settings(new_cfg)
            self._send_json(200, {
                "success": True,
                "status": "ok",
                "output_dir": updated.get("output_dir"),
                "quality": updated.get("default_quality"),
                "settings": updated
            })
            return

        self._send_json(404, {"success": False, "status": "error", "error": f"POST endpoint not found: {path}"})


def launch_server(port: int = 7777, open_browser: bool = True, output_dir: Optional[str] = None):
    """Starts the HTTP server and opens user's browser."""
    if output_dir:
        download_mgr.save_settings({"output_dir": os.path.abspath(os.path.expanduser(output_dir))})

    actual_port = find_available_port(port)
    server_address = ("127.0.0.1", actual_port)
    httpd = ThreadingHTTPServer(server_address, DownloaderRequestHandler)

    url = f"http://127.0.0.1:{actual_port}"

    print("===================================================================")
    print("           KaraokeZero Desktop Song Downloader")
    print("===================================================================")
    print(f"  • Web UI:             {url}")
    print(f"  • Destination Folder: {download_mgr.settings.get('output_dir')}")
    print(f"  • Default Quality:    {download_mgr.settings.get('default_quality')}p (Pi Zero H.264 Optimized)")
    print("===================================================================")
    print("Press Ctrl+C to stop the downloader.")
    print("")

    if open_browser:
        def _open():
            time.sleep(0.6)
            try:
                webbrowser.open(url)
            except Exception as e:
                logger.debug("Could not auto-open browser: %s", e)

        t = threading.Thread(target=_open, daemon=True)
        t.start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping KaraokeZero Desktop Downloader...")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="KaraokeZero Desktop Downloader Server")
    parser.add_argument("--port", type=int, default=7777, help="Local HTTP port (default: 7777)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open web browser automatically")
    parser.add_argument("--dir", type=str, default=None, help="Output directory for downloaded songs")
    args = parser.parse_args()

    launch_server(port=args.port, open_browser=not args.no_browser, output_dir=args.dir)
