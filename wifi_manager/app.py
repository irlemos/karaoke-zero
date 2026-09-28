#!/usr/bin/env python3
"""
KaraokeZero - Module 1: System Admin & Configuration Panel
Mobile-first management portal for Wi-Fi provisioning, song search & downloads,
PiKaraoke settings, and device power controls on Raspberry Pi Zero W.

Author: KaraokeZero Open-Source Project
License: MIT
"""

import configparser
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request

# Try importing psutil for memory statistics
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [AdminPanel] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("AdminPanel")

app = Flask(__name__)

# ==============================================================================
# 1. System Settings & Persistence Management
# ==============================================================================

DEFAULT_SETTINGS: Dict[str, Any] = {
    "default_video_quality": "480",  # Options: "360", "480", "720", "1080"
    "offline_mode": False,           # True: Restricts PiKaraoke to local songs
    "audio_quality": "best"          # Always maximum available bitrate
}


def get_settings_file_path() -> str:
    """Resolves persistent storage location for system settings."""
    primary_data_dir = "/mnt/external_hd/karaoke/data"
    if os.path.isdir(primary_data_dir):
        return os.path.join(primary_data_dir, "system_settings.json")
    backup_etc_dir = "/etc/karaokezero"
    if os.path.isdir(backup_etc_dir):
        return os.path.join(backup_etc_dir, "system_settings.json")
    return "/tmp/system_settings.json"


def get_pikaraoke_config_path() -> str:
    """Resolves path to PiKaraoke config.ini."""
    candidates = [
        "/mnt/external_hd/karaoke/data/config.ini",
        "/mnt/external_hd/karaoke/config.ini",
        "/var/lib/karaokezero/data/config.ini",
        os.path.expanduser("~/.pikaraoke/config.ini")
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    if os.path.isdir("/mnt/external_hd/karaoke/data"):
        return "/mnt/external_hd/karaoke/data/config.ini"
    return "/tmp/pikaraoke_config.ini"


def get_songs_storage_dir() -> str:
    """Resolves directory path for downloaded karaoke media."""
    candidates = [
        "/mnt/external_hd/karaoke/songs",
        "/var/lib/karaokezero/songs",
        os.path.expanduser("~/songs")
    ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    primary = "/mnt/external_hd/karaoke/songs"
    try:
        os.makedirs(primary, exist_ok=True)
        return primary
    except Exception:
        fallback = os.path.expanduser("~/songs")
        os.makedirs(fallback, exist_ok=True)
        return fallback


class SystemSettingsManager:
    """Manages persistent system configuration and synchronizes with PiKaraoke."""

    def __init__(self):
        self.lock = threading.Lock()
        self.settings = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> Dict[str, Any]:
        with self.lock:
            file_path = get_settings_file_path()
            if os.path.isfile(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        saved = json.load(f)
                        self.settings.update(saved)
                except Exception as e:
                    logger.warning("Could not read settings from %s: %s", file_path, e)
            return dict(self.settings)

    def save(self, new_values: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            for k in DEFAULT_SETTINGS:
                if k in new_values:
                    self.settings[k] = new_values[k]

            file_path = get_settings_file_path()
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(self.settings, f, indent=2)
                logger.info("Saved persistent settings to %s", file_path)
            except Exception as e:
                logger.error("Failed to write settings to %s: %s", file_path, e)

            # Sync side-effects to PiKaraoke config.ini
            self.sync_to_pikaraoke()
            return dict(self.settings)

    def sync_to_pikaraoke(self) -> bool:
        """
        Updates PiKaraoke config.ini based on current settings:
        - When offline_mode=True, sets admin_password lock in PiKaraoke so guests cannot
          use the Add New / YouTube search on port 5555.
        - When offline_mode=False, clears admin_password so guests can search YouTube.
        - Updates high_quality flag based on default video quality.
        """
        config_path = get_pikaraoke_config_path()
        try:
            config = configparser.ConfigParser()
            if os.path.isfile(config_path):
                config.read(config_path)

            if not config.has_section("USERPREFERENCES"):
                config.add_section("USERPREFERENCES")
            if not config.has_section("SECRETS"):
                config.add_section("SECRETS")

            # High quality setting in PiKaraoke
            is_hq = self.settings.get("default_video_quality") in ["720", "1080"]
            config.set("USERPREFERENCES", "high_quality", str(is_hq))

            # Offline mode lock: set admin password to lock guest online searches
            if self.settings.get("offline_mode"):
                config.set("SECRETS", "admin_password", "karaokezero_locked")
                logger.info("PiKaraoke offline mode applied: Guest YouTube search locked.")
            else:
                config.set("SECRETS", "admin_password", "")
                logger.info("PiKaraoke online mode applied: Guest YouTube search enabled.")

            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                config.write(f)
            return True
        except Exception as e:
            logger.warning("Failed to sync settings to PiKaraoke config (%s): %s", config_path, e)
            return False


settings_mgr = SystemSettingsManager()

# ==============================================================================
# 2. Song Search & Download Engine (yt-dlp)
# ==============================================================================

class SongDownloadManager:
    """Manages asynchronous, non-blocking video downloads via yt-dlp."""

    def __init__(self):
        self.lock = threading.Lock()
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.queue: queue.Queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def add_download(self, url: str, title: Optional[str] = None, quality: Optional[str] = None) -> Dict[str, Any]:
        task_id = f"dl_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        chosen_quality = quality or settings_mgr.settings.get("default_video_quality", "480")

        task = {
            "id": task_id,
            "url": url,
            "title": title or "Unknown Song",
            "quality": str(chosen_quality),
            "status": "queued",  # queued, downloading, completed, error
            "progress": 0.0,
            "speed": "",
            "eta": "",
            "size": "",
            "error": None,
            "timestamp": time.time()
        }

        with self.lock:
            self.tasks[task_id] = task

        self.queue.put(task_id)
        logger.info("Enqueued download task %s for '%s' (%sp, audio=best)", task_id, task["title"], chosen_quality)
        return task

    def get_tasks(self) -> List[Dict[str, Any]]:
        with self.lock:
            # Sort newest first
            return sorted(self.tasks.values(), key=lambda t: t["timestamp"], reverse=True)

    def _worker_loop(self):
        while True:
            try:
                task_id = self.queue.get()
                with self.lock:
                    task = self.tasks.get(task_id)
                if not task:
                    continue

                self._execute_download(task)
            except Exception as e:
                logger.exception("Unexpected error in download worker: %s", e)
            finally:
                time.sleep(0.5)

    def _execute_download(self, task: Dict[str, Any]):
        task_id = task["id"]
        url = task["url"]
        quality = task.get("quality", "480")
        songs_dir = get_songs_storage_dir()

        with self.lock:
            task["status"] = "downloading"
            task["progress"] = 5.0

        ytdlp_bin = shutil.which("yt-dlp") or "/usr/local/bin/yt-dlp" or "/usr/bin/yt-dlp"
        if not shutil.which(ytdlp_bin) and not os.path.isfile(ytdlp_bin):
            with self.lock:
                task["status"] = "error"
                task["error"] = "yt-dlp binary not found on system."
            logger.error("yt-dlp binary not found.")
            return

        # Format selector: strictly limit video height to requested quality, ALWAYS request highest quality audio
        format_spec = f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best"
        output_template = os.path.join(songs_dir, "%(title)s [%(id)s].%(ext)s")

        cmd = [
            ytdlp_bin,
            "--no-playlist",
            "-f", format_spec,
            "--merge-output-format", "mp4",
            "--no-mtime",
            "--newline",
            "-o", output_template,
            url
        ]

        logger.info("Executing yt-dlp: %s", " ".join(cmd))

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            progress_re = re.compile(
                r"\[download\]\s+([0-9.]+)%\s+of\s+~?\s*([0-9.]+[A-Za-z]+)\s+at\s+([0-9.]+[A-Za-z/]+)\s+ETA\s+([0-9:]+)"
            )
            simple_re = re.compile(r"\[download\]\s+([0-9.]+)%")

            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    if not line:
                        break
                    line_str = line.strip()

                    # Progress parsing
                    m = progress_re.search(line_str)
                    if m:
                        with self.lock:
                            task["progress"] = float(m.group(1))
                            task["size"] = m.group(2)
                            task["speed"] = m.group(3)
                            task["eta"] = m.group(4)
                        continue

                    sm = simple_re.search(line_str)
                    if sm:
                        with self.lock:
                            task["progress"] = float(sm.group(1))

            proc.wait()

            with self.lock:
                if proc.returncode == 0:
                    task["status"] = "completed"
                    task["progress"] = 100.0
                    task["speed"] = ""
                    task["eta"] = ""
                    logger.info("Download completed successfully for task %s (%s)", task_id, task["title"])
                else:
                    task["status"] = "error"
                    task["error"] = f"yt-dlp exited with code {proc.returncode}"
                    logger.error("Download failed for task %s (code %d)", task_id, proc.returncode)

        except Exception as e:
            logger.exception("Error during download execution for task %s: %s", task_id, e)
            with self.lock:
                task["status"] = "error"
                task["error"] = str(e)


download_mgr = SongDownloadManager()


def search_youtube_videos(query: str, max_results: int = 8) -> List[Dict[str, Any]]:
    """Performs lightweight YouTube video search using yt-dlp flat-playlist metadata."""
    if not query.strip():
        return []

    ytdlp_bin = shutil.which("yt-dlp") or "/usr/local/bin/yt-dlp" or "/usr/bin/yt-dlp"
    clean_query = query.strip()
    cmd = [
        ytdlp_bin,
        f"ytsearch{max_results}:{clean_query}",
        "--dump-json",
        "--flat-playlist",
        "--skip-download",
        "--no-warnings"
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
        results = []
        for line in res.stdout.strip().splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line.strip())
                vid = data.get("id")
                if not vid:
                    continue

                thumbnails = data.get("thumbnails", [])
                thumb_url = thumbnails[-1].get("url") if thumbnails else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

                results.append({
                    "id": vid,
                    "title": data.get("title") or "Unknown Title",
                    "uploader": data.get("uploader") or data.get("channel") or "Unknown Artist",
                    "duration": data.get("duration_string") or str(data.get("duration") or ""),
                    "thumbnail": thumb_url,
                    "url": f"https://www.youtube.com/watch?v={vid}"
                })
            except Exception:
                continue

        return results
    except subprocess.TimeoutExpired:
        logger.warning("YouTube search timed out for query: %s", clean_query)
        return []
    except Exception as e:
        logger.error("Error executing YouTube search: %s", e)
        return []


# ==============================================================================
# 3. System Actions & Hardware Diagnostics
# ==============================================================================

def get_system_diagnostics() -> Dict[str, Any]:
    """Reads system stats: CPU temperature, RAM, disk space, and uptime."""
    stats = {
        "cpu_temp": None,
        "ram_total_mb": 0,
        "ram_used_mb": 0,
        "ram_percent": 0.0,
        "disk_total_gb": 0.0,
        "disk_free_gb": 0.0,
        "disk_percent": 0.0,
        "uptime_str": "Unknown",
        "songs_count": 0
    }

    # CPU Temperature (Raspberry Pi thermal zone)
    thermal_path = "/sys/class/thermal/thermal_zone0/temp"
    if os.path.exists(thermal_path):
        try:
            with open(thermal_path, "r", encoding="utf-8") as f:
                stats["cpu_temp"] = round(int(f.read().strip()) / 1000.0, 1)
        except Exception:
            pass

    # RAM
    if HAS_PSUTIL:
        try:
            vm = psutil.virtual_memory()
            stats["ram_total_mb"] = int(vm.total / (1024 * 1024))
            stats["ram_used_mb"] = int(vm.used / (1024 * 1024))
            stats["ram_percent"] = vm.percent
        except Exception:
            pass

    # Storage Disk Space
    songs_dir = get_songs_storage_dir()
    try:
        usage = shutil.disk_usage(songs_dir)
        stats["disk_total_gb"] = round(usage.total / (1024 ** 3), 1)
        stats["disk_free_gb"] = round(usage.free / (1024 ** 3), 1)
        stats["disk_percent"] = round((usage.used / usage.total) * 100.0, 1)
    except Exception:
        pass

    # Uptime
    uptime_path = "/proc/uptime"
    if os.path.exists(uptime_path):
        try:
            with open(uptime_path, "r", encoding="utf-8") as f:
                uptime_sec = float(f.read().split()[0])
                hours = int(uptime_sec // 3600)
                minutes = int((uptime_sec % 3600) // 60)
                stats["uptime_str"] = f"{hours}h {minutes}m"
        except Exception:
            pass

    # Local songs count
    if os.path.isdir(songs_dir):
        try:
            count = sum(len(files) for _, _, files in os.walk(songs_dir))
            stats["songs_count"] = count
        except Exception:
            pass

    return stats


def restart_pikaraoke_service() -> bool:
    """Restarts pikaraoke.service to force song library reindex."""
    try:
        logger.info("Restarting pikaraoke.service to rescan library...")
        res = subprocess.run(["systemctl", "restart", "pikaraoke.service"], capture_output=True, text=True, timeout=15)
        return res.returncode == 0
    except Exception as e:
        logger.error("Error restarting pikaraoke.service: %s", e)
        return False


def delayed_power_action(action: str):
    """Executes reboot or shutdown after a 1.5s delay allowing HTTP response to return."""
    time.sleep(1.5)
    if action == "reboot":
        logger.info("Executing system reboot...")
        subprocess.Popen(["systemctl", "reboot"])
    elif action == "shutdown":
        logger.info("Executing system poweroff...")
        subprocess.Popen(["systemctl", "poweroff"])


# ==============================================================================
# 4. Wi-Fi Manager Subsystem (Preserved)
# ==============================================================================

connection_lock = threading.Lock()
connection_state: Dict[str, Any] = {
    "status": "idle",       # idle, connecting, success, error
    "target_ssid": None,
    "message": "",
    "timestamp": 0
}


def parse_terse_line(line: str) -> List[str]:
    """Parses a single line of nmcli -t output handling escaped colons."""
    parts: List[str] = []
    current: List[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == '\\':
            escaped = True
        elif char == ':':
            parts.append(''.join(current))
            current = []
        else:
            current.append(char)
    parts.append(''.join(current))
    return parts


def run_nmcli_command(args: List[str], timeout: int = 15) -> subprocess.CompletedProcess:
    cmd = ["nmcli"] + args
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=False
    )


def get_current_wifi_status() -> Dict[str, Any]:
    status: Dict[str, Any] = {
        "connected": False,
        "ssid": None,
        "device": "wlan0",
        "ip_address": None,
        "signal": None
    }

    try:
        res = run_nmcli_command(["-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status"], timeout=5)
        if res.returncode == 0:
            for line in res.stdout.strip().splitlines():
                if not line:
                    continue
                fields = parse_terse_line(line)
                if len(fields) >= 4:
                    dev, dev_type, state, conn = fields[0], fields[1], fields[2], fields[3]
                    if dev_type == "wifi" and state == "connected":
                        status["connected"] = True
                        status["ssid"] = conn
                        status["device"] = dev
                        break

        dev_name = status["device"] or "wlan0"
        ip_res = run_nmcli_command(["-g", "IP4.ADDRESS", "dev", "show", dev_name], timeout=5)
        if ip_res.returncode == 0 and ip_res.stdout.strip():
            ip_raw = ip_res.stdout.strip().splitlines()[0]
            status["ip_address"] = ip_raw.split('/')[0]

        if status["connected"] and status["ssid"]:
            wifi_res = run_nmcli_command(["-t", "-f", "IN-USE,SSID,SIGNAL", "dev", "wifi", "list"], timeout=8)
            if wifi_res.returncode == 0:
                for line in wifi_res.stdout.strip().splitlines():
                    fields = parse_terse_line(line)
                    if len(fields) >= 3 and fields[0] == "*":
                        try:
                            status["signal"] = int(fields[2])
                        except ValueError:
                            pass
                        break

    except Exception as e:
        logger.warning("Error fetching Wi-Fi status: %s", e)

    return status


def scan_wifi_networks(rescan: bool = False) -> List[Dict[str, Any]]:
    args = ["-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"]
    if rescan:
        args.extend(["--rescan", "yes"])

    try:
        res = run_nmcli_command(args, timeout=20)
    except subprocess.TimeoutExpired:
        logger.error("Wi-Fi scan timed out.")
        return []
    except FileNotFoundError:
        logger.error("nmcli command not found on host system.")
        return []

    if res.returncode != 0:
        logger.error("nmcli scan failed: %s", res.stderr.strip())
        return []

    networks_map: Dict[str, Dict[str, Any]] = {}

    for line in res.stdout.strip().splitlines():
        if not line:
            continue
        fields = parse_terse_line(line)
        if len(fields) < 4:
            continue

        in_use, ssid, signal_str, security = fields[0], fields[1], fields[2], fields[3]
        ssid = ssid.strip()
        if not ssid or ssid == "--":
            continue

        try:
            signal = int(signal_str)
        except ValueError:
            signal = 0

        is_active = (in_use.strip() == "*")
        is_secured = bool(security.strip() and security.strip().upper() != "--")

        entry = {
            "ssid": ssid,
            "signal": signal,
            "security": security.strip() if is_secured else "Open",
            "is_secured": is_secured,
            "is_active": is_active
        }

        if ssid not in networks_map:
            networks_map[ssid] = entry
        else:
            if is_active or (not networks_map[ssid]["is_active"] and signal > networks_map[ssid]["signal"]):
                networks_map[ssid] = entry

    sorted_networks = sorted(
        networks_map.values(),
        key=lambda net: (1 if net["is_active"] else 0, net["signal"]),
        reverse=True
    )

    return sorted_networks


def _async_connect_worker(ssid: str, password: Optional[str]):
    global connection_state
    time.sleep(1.0)
    logger.info("Starting connection attempt to SSID: %s", ssid)

    try:
        connect_args = ["dev", "wifi", "connect", ssid]
        if password:
            connect_args.extend(["password", password])

        res = run_nmcli_command(connect_args, timeout=45)

        with connection_lock:
            if res.returncode == 0:
                logger.info("Connected to '%s'. Setting autoconnect priority to 50...", ssid)
                run_nmcli_command([
                    "connection", "modify", ssid,
                    "connection.autoconnect-priority", "50",
                    "connection.autoconnect", "yes"
                ], timeout=10)

                connection_state["status"] = "success"
                connection_state["message"] = f"Successfully connected to '{ssid}'!"
            else:
                err_msg = res.stderr.strip() or res.stdout.strip() or "Connection failed."
                logger.error("Failed to connect to '%s': %s", ssid, err_msg)
                connection_state["status"] = "error"
                connection_state["message"] = f"Connection error: {err_msg}"
            connection_state["timestamp"] = time.time()

    except Exception as e:
        logger.exception("Unexpected error during Wi-Fi connection: %s", e)
        with connection_lock:
            connection_state["status"] = "error"
            connection_state["message"] = f"Internal error: {str(e)}"
            connection_state["timestamp"] = time.time()


# ==============================================================================
# 5. HTTP Routes & API Endpoints
# ==============================================================================

@app.route("/")
def index():
    """Renders the main mobile-first general configuration portal."""
    status = get_current_wifi_status()
    current_settings = settings_mgr.settings
    diagnostics = get_system_diagnostics()
    return render_template(
        "index.html",
        current_status=status,
        settings=current_settings,
        diagnostics=diagnostics
    )


# --- System Status & Settings Endpoints ---

@app.route("/api/status", methods=["GET"])
def api_status():
    """Returns general system status, Wi-Fi status, diagnostics, and settings."""
    wifi_status = get_current_wifi_status()
    diagnostics = get_system_diagnostics()
    return jsonify({
        "success": True,
        "status": wifi_status,
        "wifi": wifi_status,
        "diagnostics": diagnostics,
        "settings": settings_mgr.settings
    })


@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    """Returns current persistent settings."""
    return jsonify({
        "success": True,
        "settings": settings_mgr.settings
    })


@app.route("/api/settings", methods=["POST"])
def api_update_settings():
    """Updates persistent settings (video quality, offline mode)."""
    data = request.get_json(silent=True) or request.form
    if not data:
        return jsonify({"success": False, "error": "No configuration payload provided."}), 400

    updated = settings_mgr.save(data)
    return jsonify({
        "success": True,
        "message": "Settings updated successfully.",
        "settings": updated
    })


# --- Songs Search & Download Endpoints ---

@app.route("/api/songs/search", methods=["GET"])
def api_songs_search():
    """Searches YouTube videos via yt-dlp flat-playlist metadata."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"success": True, "results": []})

    results = search_youtube_videos(query=query, max_results=10)
    return jsonify({
        "success": True,
        "count": len(results),
        "results": results
    })


@app.route("/api/songs/download", methods=["POST"])
def api_songs_download():
    """Initiates an asynchronous background download of a YouTube video."""
    data = request.get_json(silent=True) or request.form
    url = (data.get("url") or data.get("video_id") or "").strip()
    title = (data.get("title") or "").strip()
    quality = (data.get("quality") or "").strip() or None

    if not url:
        return jsonify({"success": False, "error": "Song URL or video_id is required."}), 400

    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://www.youtube.com/watch?v={url}"

    task = download_mgr.add_download(url=url, title=title, quality=quality)
    return jsonify({
        "success": True,
        "message": f"Download enqueued for '{task['title']}'",
        "task": task
    })


@app.route("/api/songs/downloads", methods=["GET"])
def api_songs_downloads():
    """Returns all active, queued, and recently completed downloads."""
    tasks = download_mgr.get_tasks()
    return jsonify({
        "success": True,
        "tasks": tasks
    })


@app.route("/api/pikaraoke/rescan", methods=["POST"])
def api_pikaraoke_rescan():
    """Refreshes the PiKaraoke song catalog by restarting the core service."""
    success = restart_pikaraoke_service()
    if success:
        return jsonify({"success": True, "message": "PiKaraoke library updated successfully."})
    return jsonify({"success": False, "error": "Failed to restart PiKaraoke service."}), 500


# --- System Power Endpoints ---

@app.route("/api/system/reboot", methods=["POST"])
def api_system_reboot():
    """Initiates a graceful reboot of the Raspberry Pi."""
    t = threading.Thread(target=delayed_power_action, args=("reboot",), daemon=True)
    t.start()
    return jsonify({
        "success": True,
        "message": "System reboot initiated. The device will be back online shortly."
    })


@app.route("/api/system/shutdown", methods=["POST"])
def api_system_shutdown():
    """Initiates a graceful poweroff of the Raspberry Pi."""
    t = threading.Thread(target=delayed_power_action, args=("shutdown",), daemon=True)
    t.start()
    return jsonify({
        "success": True,
        "message": "System shutdown initiated. Power can be safely disconnected after activity LED turns off."
    })


# --- Wi-Fi Network Endpoints (Preserved) ---

@app.route("/api/scan", methods=["GET"])
def api_scan():
    """Scans and returns visible Wi-Fi access points."""
    rescan = request.args.get("rescan", "true").lower() == "true"
    networks = scan_wifi_networks(rescan=rescan)
    return jsonify({
        "success": True,
        "count": len(networks),
        "networks": networks
    })


@app.route("/api/connect", methods=["POST"])
def api_connect():
    """Initiates connection to the selected Wi-Fi network."""
    global connection_state

    data = request.get_json(silent=True) or request.form
    ssid = (data.get("ssid") or "").strip()
    password = (data.get("password") or "").strip()

    if not ssid:
        return jsonify({
            "success": False,
            "error": "Network SSID is required."
        }), 400

    with connection_lock:
        if connection_state["status"] == "connecting":
            return jsonify({
                "success": False,
                "error": "A connection attempt is already in progress. Please wait."
            }), 409

        connection_state["status"] = "connecting"
        connection_state["target_ssid"] = ssid
        connection_state["message"] = f"Attempting connection to '{ssid}'..."
        connection_state["timestamp"] = time.time()

    worker_thread = threading.Thread(
        target=_async_connect_worker,
        args=(ssid, password if password else None),
        daemon=True
    )
    worker_thread.start()

    return jsonify({
        "success": True,
        "message": f"Connection to '{ssid}' initiated.",
        "note": "Device is migrating networks. Reconnect to venue Wi-Fi if needed."
    })


@app.route("/api/connect/status", methods=["GET"])
def api_connect_status():
    """Returns active Wi-Fi connection attempt status."""
    with connection_lock:
        return jsonify({
            "success": True,
            "state": connection_state
        })


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8888"))
    logger.info("Starting KaraokeZero Admin Panel on %s:%d", host, port)
    app.run(host=host, port=port, debug=False, threaded=True)
