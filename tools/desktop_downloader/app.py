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

from youtube_search import search_youtube, search_playlists, extract_playlist_info
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


DEFAULT_PORT = 7777
MAX_PORT_ATTEMPTS = 20


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """Checks if a TCP port is available to bind on the specified host."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def find_available_port(
    start_port: int = DEFAULT_PORT,
    max_attempts: int = MAX_PORT_ATTEMPTS,
    host: str = "127.0.0.1"
) -> Optional[int]:
    """
    Finds the first unused TCP port starting from start_port up to max_attempts.
    Returns the port number if found, or None if all attempts are occupied.
    """
    for offset in range(max_attempts):
        port = start_port + offset
        if is_port_available(port, host=host):
            return port
    return None


def resolve_server_port(
    requested_port: Optional[int] = None,
    default_port: int = DEFAULT_PORT,
    max_attempts: int = MAX_PORT_ATTEMPTS,
    host: str = "127.0.0.1"
) -> int:
    """
    Validates and resolves the TCP port for the local server:
    1. If requested_port is provided: verifies if that port is available.
       If occupied, displays an error requesting an available port and exits.
    2. If requested_port is None: checks default_port (7777). If in use,
       scans up to max_attempts consecutive ports. If an open port is found,
       notifies the user and returns it. If all max_attempts ports are in use,
       displays an error asking the user to specify a free port via --port and exits.
    """
    launcher_cmd = "karaoke-downloader-win.bat" if sys.platform == "win32" else "./karaoke-downloader"

    if requested_port is not None:
        if not is_port_available(requested_port, host=host):
            print("\n" + "=" * 65, file=sys.stderr)
            print(f"[ERROR] Port {requested_port} is already in use by another application.", file=sys.stderr)
            print("=" * 65, file=sys.stderr)
            print("Please specify a different, available port using the --port parameter:", file=sys.stderr)
            print(f"\n    {launcher_cmd} --port <PORT_NUMBER>\n", file=sys.stderr)
            print("=" * 65 + "\n", file=sys.stderr)
            sys.exit(1)
        return requested_port

    actual_port = find_available_port(start_port=default_port, max_attempts=max_attempts, host=host)
    if actual_port is None:
        end_port = default_port + max_attempts - 1
        print("\n" + "=" * 65, file=sys.stderr)
        print(f"[ERROR] Port conflict: All {max_attempts} automatic ports ({default_port} - {end_port}) are occupied!", file=sys.stderr)
        print("=" * 65, file=sys.stderr)
        print("No available port could be found automatically.", file=sys.stderr)
        print("Please free up one of these ports or specify an available port using the --port parameter:", file=sys.stderr)
        print(f"\n    {launcher_cmd} --port <PORT_NUMBER>\n", file=sys.stderr)
        print("Example:", file=sys.stderr)
        print(f"    {launcher_cmd} --port 8888", file=sys.stderr)
        print("=" * 65 + "\n", file=sys.stderr)
        sys.exit(1)

    if actual_port != default_port:
        print(f"\n[NOTICE] Default port {default_port} is in use.")
        print(f"[NOTICE] Automatically switched to available port: {actual_port}\n")

    return actual_port


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

        # 1. API: Search YouTube (Videos or Playlists)
        if path == "/api/search":
            q = query_params.get("q", [""])[0].strip()
            search_type = query_params.get("type", ["videos"])[0].lower()
            max_r = int(query_params.get("limit", [15])[0])

            if search_type == "playlists":
                results = search_playlists(q, max_results=max_r)
                self._send_json(200, {
                    "success": True,
                    "status": "ok",
                    "type": "playlists",
                    "results": results,
                    "count": len(results)
                })
            else:
                ytdlp_cmd = resolve_ytdlp_command()
                results = search_youtube(q, max_results=max_r, ytdlp_cmd=ytdlp_cmd)
                self._send_json(200, {
                    "success": True,
                    "status": "ok",
                    "type": "videos",
                    "results": results,
                    "count": len(results)
                })
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
                "completed": status.get("completed_count", 0),
                "errors": len(status.get("errors", [])),
                "total": len(status.get("active", [])) + len(status.get("queued", []))
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
            repo_root = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
            ffmpeg_exists = (
                shutil.which("ffmpeg") is not None
                or (sys.platform == "win32" and shutil.which("ffmpeg.exe") is not None)
                or os.path.isfile(os.path.join(repo_root, "bin", "ffmpeg.exe"))
                or os.path.isfile(os.path.join(repo_root, "bin", "ffmpeg"))
                or os.path.isfile(os.path.join(SCRIPT_DIR, "bin", "ffmpeg.exe"))
                or os.path.isfile(os.path.join(SCRIPT_DIR, "bin", "ffmpeg"))
            )

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

        # 5. API: Anti-Ban Security & Resilience Status
        if path == "/api/system/security":
            now = time.time()
            self._send_json(200, {
                "success": True,
                "status": "ok",
                "mitigations": {
                    "random_pauses": True,
                    "pacing_min_seconds": download_mgr.settings.get("pacing_min_seconds", 5),
                    "pacing_max_seconds": download_mgr.settings.get("pacing_max_seconds", 15),
                    "streaming_rate_cap": download_mgr.settings.get("rate_limit_streaming", "5M"),
                    "client_emulation": "android,web",
                    "autonomous_daily_updates": True,
                    "cooldown_on_429_minutes": 30
                },
                "rate_limit": {
                    "active": download_mgr.rate_limit_active,
                    "cooldown_until": download_mgr.rate_limit_cooldown_until,
                    "remaining_seconds": max(0, int(download_mgr.rate_limit_cooldown_until - now)) if download_mgr.rate_limit_active else 0,
                    "reason": download_mgr.rate_limit_reason
                },
                "pacing": {
                    "active": bool(download_mgr.pacing_status.get("active") and download_mgr.pacing_status.get("until", 0) > now),
                    "seconds": download_mgr.pacing_status.get("seconds", 0.0),
                    "remaining_seconds": max(0, round(download_mgr.pacing_status.get("until", 0) - now, 1)) if download_mgr.pacing_status.get("active") else 0.0
                },
                "last_ytdlp_update_check": download_mgr.settings.get("last_ytdlp_update_check", 0)
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

        # 3. API: Enqueue complete playlist by URL
        if path == "/api/download/playlist":
            url = body.get("url")
            quality = body.get("quality") or body.get("default_quality")
            if not url:
                self._send_json(400, {"success": False, "status": "error", "error": "Missing 'url' field."})
                return

            ytdlp_cmd = resolve_ytdlp_command()
            info = extract_playlist_info(url, ytdlp_cmd=ytdlp_cmd)
            if not info.get("success") or not info.get("items"):
                self._send_json(400, {
                    "success": False,
                    "status": "error",
                    "error": info.get("error") or "No songs found in playlist."
                })
                return

            items = info["items"]
            enqueued = download_mgr.enqueue_batch(items, quality=quality)
            self._send_json(200, {
                "success": True,
                "status": "ok",
                "playlist_title": info.get("title"),
                "playlist_id": info.get("id"),
                "enqueued_count": len(enqueued),
                "tasks": enqueued
            })
            return

        # 4. API: Cancel / Remove task from queue
        if path in ("/api/queue/cancel", "/api/queue/remove"):
            task_id = body.get("task_id") or body.get("id")
            if not task_id:
                self._send_json(400, {"success": False, "status": "error", "error": "Missing 'task_id'."})
                return
            ok = download_mgr.cancel_task(task_id)
            self._send_json(200, {"success": True, "status": "ok", "cancelled": ok})
            return

        # 5. API: Retry specific failed task
        if path == "/api/queue/retry":
            task_id = body.get("task_id") or body.get("id")
            if not task_id:
                self._send_json(400, {"success": False, "status": "error", "error": "Missing 'task_id'."})
                return
            ok = download_mgr.retry_task(task_id)
            self._send_json(200, {"success": True, "status": "ok", "retried": ok, "task_id": task_id})
            return

        # 6. API: Retry all failed tasks
        if path == "/api/queue/retry-all":
            count = download_mgr.retry_all_failed()
            self._send_json(200, {"success": True, "status": "ok", "retried_count": count})
            return

        # 7. API: Clear completed/cancelled
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
            if "browser_cookies" in body:
                new_cfg["browser_cookies"] = str(body["browser_cookies"])

            updated = download_mgr.save_settings(new_cfg)
            self._send_json(200, {
                "success": True,
                "status": "ok",
                "output_dir": updated.get("output_dir"),
                "quality": updated.get("default_quality"),
                "settings": updated
            })
            return

        # 7. API: Dismiss Rate Limit Cooldown & Resume Queue
        if path in ("/api/queue/cooldown/dismiss", "/api/queue/dismiss-cooldown"):
            download_mgr.dismiss_rate_limit()
            self._send_json(200, {
                "success": True,
                "status": "ok",
                "message": "Rate limit cooldown dismissed manually. Queue resumed."
            })
            return

        # 8. API: Trigger Autonomous yt-dlp Update Check
        if path == "/api/system/update-ytdlp":
            res = download_mgr.check_and_update_ytdlp(force=True)
            self._send_json(200, res)
            return

        self._send_json(404, {"success": False, "status": "error", "error": f"POST endpoint not found: {path}"})


def launch_server(port: Optional[int] = None, open_browser: bool = True, output_dir: Optional[str] = None):
    """Starts the HTTP server and opens user's browser."""
    if output_dir:
        download_mgr.save_settings({"output_dir": os.path.abspath(os.path.expanduser(output_dir))})

    actual_port = resolve_server_port(requested_port=port)
    server_address = ("127.0.0.1", actual_port)
    ThreadingHTTPServer.allow_reuse_address = True
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
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Local HTTP port (default: 7777, auto-scans up to 20 ports if busy)"
    )
    parser.add_argument("--no-browser", action="store_true", help="Do not open web browser automatically")
    parser.add_argument("--dir", type=str, default=None, help="Output directory for downloaded songs")
    args = parser.parse_args()

    launch_server(port=args.port, open_browser=not args.no_browser, output_dir=args.dir)
