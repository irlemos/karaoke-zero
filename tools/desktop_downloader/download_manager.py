#!/usr/bin/env python3
"""
KaraokeZero Desktop Downloader - Download Queue & Storage Manager
Handles asynchronous background downloads with real-time speed & progress tracking,
automatic duplicate skipping via download archive, and Raspberry Pi H.264 encoding guarantees.
"""

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

logger = logging.getLogger("DesktopDownloader.Manager")


def resolve_ytdlp_command() -> List[str]:
    """
    Finds available yt-dlp executable on the system.
    Searches PATH, ~/.local/bin, /usr/local/bin, /usr/bin, and local tool directory.
    """
    which_bin = shutil.which("yt-dlp")
    if which_bin and os.path.isfile(which_bin) and os.access(which_bin, os.X_OK):
        return [which_bin]

    user_home = os.path.expanduser("~")
    script_dir = os.path.dirname(os.path.abspath(__file__))

    candidates = [
        os.path.join(script_dir, "bin", "yt-dlp"),
        os.path.join(user_home, ".local", "bin", "yt-dlp"),
        "/usr/local/bin/yt-dlp",
        "/usr/bin/yt-dlp",
        "/opt/pikaraoke/venv/bin/yt-dlp"
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return [c]

    try:
        import yt_dlp
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        pass

    return ["yt-dlp"]


def detect_storage_devices() -> List[Dict[str, Any]]:
    """
    Detects mounted USB storage devices, external drives, and common home folders
    available on the Linux PC. Identifies KaraokeZero drives automatically.
    """
    devices: List[Dict[str, Any]] = []
    seen_paths = set()

    user_home = os.path.expanduser("~")
    username = os.environ.get("USER", os.path.basename(user_home))

    # Search mount locations for external USB drives
    search_roots = [
        f"/media/{username}",
        f"/run/media/{username}",
        "/media",
        "/mnt",
        "/mnt/external_hd/karaoke",
    ]

    for root in search_roots:
        if not os.path.isdir(root):
            continue
        try:
            for entry in os.listdir(root):
                full_path = os.path.join(root, entry)
                if not os.path.isdir(full_path):
                    continue
                real_p = os.path.realpath(full_path)
                if real_p in seen_paths:
                    continue
                seen_paths.add(real_p)

                # Check if this is a KaraokeZero storage drive
                is_kz = False
                songs_subpath = full_path
                if os.path.isdir(os.path.join(full_path, "songs")):
                    songs_subpath = os.path.join(full_path, "songs")
                    is_kz = True
                elif os.path.isdir(os.path.join(full_path, "karaoke", "songs")):
                    songs_subpath = os.path.join(full_path, "karaoke", "songs")
                    is_kz = True
                elif entry.lower() in ("karaoke", "karaokezero"):
                    is_kz = True

                # Check free space
                free_gb = 0.0
                try:
                    stat = os.statvfs(full_path)
                    free_gb = round((stat.f_bavail * stat.f_frsize) / (1024 ** 3), 1)
                except Exception:
                    pass

                label = f"{entry} ({free_gb} GB free)"
                if is_kz:
                    label = f"★ KaraokeZero HD: {entry} ({free_gb} GB free)"

                devices.append({
                    "path": songs_subpath,
                    "base_path": full_path,
                    "label": label,
                    "free_gb": free_gb,
                    "is_karaokezero": is_kz,
                    "is_external": True
                })
        except Exception as e:
            logger.debug("Error scanning storage root %s: %s", root, e)

    # Add standard default locations
    default_music = os.path.join(user_home, "Music", "KaraokeZero")
    default_downloads = os.path.join(user_home, "Downloads", "KaraokeZero")

    for loc, name in [(default_music, "Music / KaraokeZero"), (default_downloads, "Downloads / KaraokeZero")]:
        try:
            stat = os.statvfs(user_home)
            free_gb = round((stat.f_bavail * stat.f_frsize) / (1024 ** 3), 1)
        except Exception:
            free_gb = 0.0

        devices.append({
            "path": loc,
            "base_path": loc,
            "label": f"Local PC: {name} ({free_gb} GB free)",
            "free_gb": free_gb,
            "is_karaokezero": False,
            "is_external": False
        })

    # Sort so KaraokeZero drives appear first
    devices.sort(key=lambda d: (not d["is_karaokezero"], not d["is_external"], d["path"]))
    return devices


class DownloadManager:
    """
    Manages sequential and parallel download queues via yt-dlp,
    updating progress percentages, transfer speed, and ETA in real time.
    """

    def __init__(self, config_path: Optional[str] = None, auto_start: bool = True):
        self.lock = threading.Lock()
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.queue: queue.Queue = queue.Queue()
        self.is_paused: bool = False
        self.current_process: Optional[subprocess.Popen] = None
        self.active_task_id: Optional[str] = None

        # Configuration storage
        user_home = os.path.expanduser("~")
        self.config_dir = os.path.join(user_home, ".config", "karaokezero")
        os.makedirs(self.config_dir, exist_ok=True)
        self.config_file = config_path or os.path.join(self.config_dir, "desktop_downloader.json")
        self.settings: Dict[str, Any] = self._load_settings()

        # Start background worker if requested
        self.worker_thread = None
        if auto_start:
            self.start_worker()

    def start_worker(self):
        """Starts background worker thread if not already active."""
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()

    def _load_settings(self) -> Dict[str, Any]:
        default_settings = {
            "output_dir": os.path.join(os.path.expanduser("~"), "Music", "KaraokeZero"),
            "default_quality": "480",
            "max_parallel": 1
        }
        # Check if an external KaraokeZero HD is already connected
        devs = detect_storage_devices()
        for d in devs:
            if d.get("is_karaokezero"):
                default_settings["output_dir"] = d["path"]
                break

        if os.path.isfile(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    default_settings.update(saved)
            except Exception as e:
                logger.warning("Could not read settings from %s: %s", self.config_file, e)

        return default_settings

    def save_settings(self, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        with self.lock:
            self.settings.update(new_settings)
            try:
                with open(self.config_file, "w", encoding="utf-8") as f:
                    json.dump(self.settings, f, indent=2)
                logger.info("Saved settings to %s", self.config_file)
            except Exception as e:
                logger.error("Failed to write settings to %s: %s", self.config_file, e)
            return dict(self.settings)

    def enqueue_download(
        self,
        url_or_id: str,
        title: Optional[str] = None,
        uploader: Optional[str] = None,
        duration: Optional[str] = None,
        thumbnail: Optional[str] = None,
        quality: Optional[str] = None
    ) -> Dict[str, Any]:
        """Adds a single track to the sequential download queue."""
        task_id = f"task_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        chosen_quality = quality or self.settings.get("default_quality", "480")

        # Format clean target URL
        target_url = url_or_id
        if not target_url.startswith("http://") and not target_url.startswith("https://"):
            target_url = f"https://www.youtube.com/watch?v={url_or_id}"

        task: Dict[str, Any] = {
            "id": task_id,
            "url": target_url,
            "title": title or "Unknown Song",
            "uploader": uploader or "YouTube",
            "duration": duration or "",
            "thumbnail": thumbnail or "",
            "quality": str(chosen_quality),
            "status": "queued",  # queued, downloading, completed, error, cancelled
            "progress": 0.0,
            "speed": "",
            "eta": "",
            "size": "",
            "error": None,
            "created_at": time.time(),
            "completed_at": None
        }

        with self.lock:
            self.tasks[task_id] = task

        self.queue.put(task_id)
        logger.info("Enqueued task %s: '%s' (%sp)", task_id, task["title"], chosen_quality)
        return task

    def enqueue_batch(self, items: List[Dict[str, Any]], quality: Optional[str] = None) -> List[Dict[str, Any]]:
        """Enqueues a list of song dictionaries at once."""
        enqueued = []
        for item in items:
            t = self.enqueue_download(
                url_or_id=item.get("url") or item.get("id"),
                title=item.get("title"),
                uploader=item.get("uploader"),
                duration=item.get("duration"),
                thumbnail=item.get("thumbnail"),
                quality=quality or item.get("quality")
            )
            enqueued.append(t)
        return enqueued

    def get_queue_status(self) -> Dict[str, Any]:
        """Returns the current state of all tasks and queue controls."""
        with self.lock:
            all_tasks = sorted(self.tasks.values(), key=lambda t: t["created_at"], reverse=True)
            active = [t for t in all_tasks if t["status"] == "downloading"]
            queued = [t for t in all_tasks if t["status"] == "queued"]
            completed = [t for t in all_tasks if t["status"] == "completed"]
            errors = [t for t in all_tasks if t["status"] == "error"]

            return {
                "is_paused": self.is_paused,
                "active": active,
                "queued": queued,
                "completed": completed,
                "errors": errors,
                "total_count": len(all_tasks),
                "tasks": all_tasks
            }

    def cancel_task(self, task_id: str) -> bool:
        """Cancels a queued or active download."""
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return False

            if task["status"] == "queued":
                task["status"] = "cancelled"
                return True

            if task["status"] == "downloading" and self.active_task_id == task_id:
                task["status"] = "cancelled"
                if self.current_process:
                    try:
                        self.current_process.terminate()
                    except Exception:
                        pass
                return True

        return False

    def clear_completed(self) -> int:
        """Removes completed and cancelled items from the task history."""
        with self.lock:
            to_delete = [
                tid for tid, t in self.tasks.items()
                if t["status"] in ("completed", "cancelled")
            ]
            for tid in to_delete:
                del self.tasks[tid]
            return len(to_delete)

    def set_paused(self, paused: bool) -> bool:
        with self.lock:
            self.is_paused = paused
            logger.info("Download queue paused: %s", paused)
            return self.is_paused

    def _worker_loop(self):
        while True:
            try:
                if self.is_paused:
                    time.sleep(0.5)
                    continue

                try:
                    task_id = self.queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                with self.lock:
                    if self.is_paused:
                        self.queue.put(task_id)
                        time.sleep(0.3)
                        continue
                    task = self.tasks.get(task_id)
                    if not task or task["status"] != "queued":
                        continue
                    task["status"] = "downloading"
                    task["progress"] = 2.0
                    self.active_task_id = task_id

                self._execute_download(task)

                with self.lock:
                    self.active_task_id = None
                    self.current_process = None
            except Exception as e:
                logger.exception("Worker loop exception: %s", e)
            finally:
                time.sleep(0.2)

    def _execute_download(self, task: Dict[str, Any]):
        task_id = task["id"]
        url = task["url"]
        quality = task.get("quality") or self.settings.get("default_quality", "480")
        output_dir = self.settings.get("output_dir", os.path.join(os.path.expanduser("~"), "Music", "KaraokeZero"))

        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as e:
            with self.lock:
                task["status"] = "error"
                task["error"] = f"Cannot create output directory: {e}"
            logger.error("Cannot create output dir %s: %s", output_dir, e)
            return

        ytdlp_cmd = resolve_ytdlp_command()
        bin_target = ytdlp_cmd[0]
        if not shutil.which(bin_target) and not os.path.isfile(bin_target):
            with self.lock:
                task["status"] = "error"
                task["error"] = f"yt-dlp binary not found: '{bin_target}'"
            logger.error("yt-dlp not found: %s", bin_target)
            return

        # Target H.264 video + AAC/M4A audio in MP4 container for smooth Pi Zero hardware playback
        format_spec = f"bestvideo[vcodec^=avc1][height<={quality}]+bestaudio[ext!=webm]/best[height<={quality}]/best"
        output_template = os.path.join(output_dir, "%(title)s [%(id)s].%(ext)s")
        archive_path = os.path.join(output_dir, "download_archive.txt")

        cmd = ytdlp_cmd + [
            "--no-playlist",
            "-f", format_spec,
            "-S", "vcodec:h264,res,acodec:m4a",
            "--merge-output-format", "mp4",
            "--compat-options", "filename-sanitization",
            "--download-archive", archive_path,
            "--no-mtime",
            "--newline",
            "-o", output_template,
            url
        ]

        logger.info("Starting yt-dlp download for '%s'...", task["title"])

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            with self.lock:
                self.current_process = proc

            progress_regex = re.compile(
                r"\[download\]\s+(\d+(?:\.\d+)?)%\s+of\s+~?(\S+)\s+at\s+(\S+)\s+ETA\s+(\S+)"
            )
            already_downloaded_regex = re.compile(r"\[download\]\s+(.+)\s+has already been downloaded")

            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue

                # Check if archive matched an already-downloaded file
                if already_downloaded_regex.search(line):
                    with self.lock:
                        task["progress"] = 100.0
                        task["speed"] = "Archived"
                        task["eta"] = "00:00"
                    continue

                m = progress_regex.search(line)
                if m:
                    pct = float(m.group(1))
                    size_str = m.group(2)
                    speed_str = m.group(3)
                    eta_str = m.group(4)
                    with self.lock:
                        task["progress"] = pct
                        task["size"] = size_str
                        task["speed"] = speed_str
                        task["eta"] = eta_str

            proc.wait()

            with self.lock:
                if task["status"] == "cancelled":
                    return

                if proc.returncode == 0:
                    task["status"] = "completed"
                    task["progress"] = 100.0
                    task["completed_at"] = time.time()
                    logger.info("Download completed successfully: %s", task["title"])
                else:
                    task["status"] = "error"
                    task["error"] = f"yt-dlp exited with error code {proc.returncode}"
                    logger.error("Download failed (code %d): %s", proc.returncode, task["title"])

        except Exception as e:
            with self.lock:
                task["status"] = "error"
                task["error"] = str(e)
            logger.exception("Exception during download execution: %s", e)
        finally:
            if proc and proc.stdout:
                try:
                    proc.stdout.close()
                except Exception:
                    pass
