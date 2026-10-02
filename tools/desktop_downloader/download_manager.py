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
import unicodedata
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("DesktopDownloader.Manager")


def sanitize_filename(name: str, max_len: int = 180) -> str:
    """
    Sanitizes a string for use as a clean, legible filesystem filename.
    Removes emojis, icons, symbols, control chars, unreadable glyphs, and filesystem-reserved characters.
    Preserves legible letters (including accents), numbers, spaces, and safe punctuation.
    """
    if not name:
        return "Song"

    # Step 1: Normalize compatibility characters (e.g. ᴴᴰ -> HD, fullwidth symbols -> standard)
    s = unicodedata.normalize("NFKC", str(name))

    # Step 2: Replace dividers, quotes, and brackets with clean equivalents
    s = s.replace("/", " - ").replace("\\", " - ")
    s = s.replace("|", " - ").replace(":", " - ").replace(";", " ")
    s = s.replace("【", "[").replace("】", "]").replace("（", "(").replace("）", ")")
    s = s.replace("“", "").replace("”", "").replace("‘", "").replace("’", "").replace("`", "")
    s = s.replace('"', "").replace("'", "")
    s = s.replace("—", "-").replace("–", "-").replace("−", "-")

    # Step 3: Filter characters
    # Keep Letters (L*), Numbers (N*), Spaces (Zs), Combining marks (M*), and safe punctuation (-_.(),[]&)
    # Drops emojis/icons (So, Sm, Sc, Sk), controls (Cc, Cf, Cn, Cs), and special characters (*?<>~!@#$%^=+)
    allowed = []
    for ch in s:
        cat = unicodedata.category(ch)
        if cat.startswith("L") or cat.startswith("N") or cat.startswith("M"):
            allowed.append(ch)
        elif ch in " -_.(),[]&":
            allowed.append(ch)

    cleaned = "".join(allowed)

    # Step 4: Clean up spacing, multiple hyphens, and brackets
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s*-\s*", " - ", cleaned)
    cleaned = re.sub(r"( - )+", " - ", cleaned)
    cleaned = re.sub(r"\[\s+", "[", cleaned)
    cleaned = re.sub(r"\s+\]", "]", cleaned)
    cleaned = re.sub(r"\](?=[A-Za-z0-9])", "] ", cleaned)
    cleaned = re.sub(r"(?<=[A-Za-z0-9])\[", " [", cleaned)
    cleaned = re.sub(r"\(\s+", "(", cleaned)
    cleaned = re.sub(r"\s+\)", ")", cleaned)
    cleaned = cleaned.strip(" .-_")

    if not cleaned:
        cleaned = "Song"

    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].strip(" .-_")

    return cleaned


def sanitize_file_path(filepath: str) -> str:
    """
    Sanitizes a full file path by cleaning the basename while preserving directory and extension.
    If the file ends with a YouTube video ID in brackets '[id]', the ID is preserved.
    """
    dirname, filename = os.path.split(filepath)
    name, ext = os.path.splitext(filename)

    m = re.search(r"^(.*?)\s*(\[[A-Za-z0-9_-]{6,}\])$", name)
    if m:
        raw_title = m.group(1)
        id_part = m.group(2)
        clean_title = sanitize_filename(raw_title)
        new_filename = f"{clean_title} {id_part}{ext}"
    else:
        new_filename = f"{sanitize_filename(name)}{ext}"

    return os.path.join(dirname, new_filename)


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
        self.completed_count: int = 0

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

        clean_title = sanitize_filename(title) if title else "Unknown Song"

        task: Dict[str, Any] = {
            "id": task_id,
            "url": target_url,
            "title": clean_title,
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
        now = time.time()
        with self.lock:
            # Completed tasks leave the download list (purged after 1.5s grace period)
            # Cancelled tasks are purged immediately
            to_purge = [
                tid for tid, t in self.tasks.items()
                if t.get("status") == "cancelled" or (
                    t.get("status") == "completed" and (now - (t.get("completed_at") or 0)) > 1.5
                )
            ]
            for tid in to_purge:
                del self.tasks[tid]

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
                "completed_count": self.completed_count,
                "total_count": len(all_tasks),
                "tasks": all_tasks
            }

    def cancel_task(self, task_id: str) -> bool:
        """Cancels a queued or active download and immediately removes it from the task list."""
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return False

            if self.active_task_id == task_id or task.get("status") == "downloading":
                task["status"] = "cancelled"
                if self.current_process:
                    try:
                        self.current_process.terminate()
                        try:
                            self.current_process.wait(timeout=0.3)
                        except subprocess.TimeoutExpired:
                            self.current_process.kill()
                    except Exception as e:
                        logger.debug("Error terminating process for task %s: %s", task_id, e)
                self.active_task_id = None
                self.current_process = None

            task["status"] = "cancelled"
            if task_id in self.tasks:
                del self.tasks[task_id]

            logger.info("Cancelled and removed task %s", task_id)
            return True

    def clear_completed(self) -> int:
        """Removes completed, cancelled, and error items from the queue."""
        with self.lock:
            to_delete = [
                tid for tid, t in self.tasks.items()
                if t["status"] in ("completed", "cancelled", "error")
            ]
            for tid in to_delete:
                del self.tasks[tid]
            return len(to_delete)

    def retry_task(self, task_id: str) -> bool:
        """Resets a failed task to queued status and puts it back in the queue."""
        with self.lock:
            task = self.tasks.get(task_id)
            if not task:
                return False
            task["status"] = "queued"
            task["progress"] = 0.0
            task["speed"] = ""
            task["eta"] = ""
            task["error"] = None
            task["error_details"] = None
            task["completed_at"] = None
            task["created_at"] = time.time()
        self.queue.put(task_id)
        logger.info("Retrying task %s: '%s'", task_id, task.get("title", ""))
        return True

    def retry_all_failed(self) -> int:
        """Retries all tasks currently in error status."""
        to_retry = []
        with self.lock:
            for tid, t in self.tasks.items():
                if t.get("status") == "error":
                    t["status"] = "queued"
                    t["progress"] = 0.0
                    t["speed"] = ""
                    t["eta"] = ""
                    t["error"] = None
                    t["error_details"] = None
                    t["completed_at"] = None
                    t["created_at"] = time.time()
                    to_retry.append(tid)

        for tid in to_retry:
            self.queue.put(tid)

        logger.info("Retrying %d failed tasks", len(to_retry))
        return len(to_retry)

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
                time.sleep(1.0)

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
                task["error_details"] = f"Failed to create directory {output_dir}: {e}"
            logger.error("Cannot create output dir %s: %s", output_dir, e)
            return

        ytdlp_cmd = resolve_ytdlp_command()
        bin_target = ytdlp_cmd[0]
        if not shutil.which(bin_target) and not os.path.isfile(bin_target):
            with self.lock:
                task["status"] = "error"
                task["error"] = f"yt-dlp binary not found: '{bin_target}'"
                task["error_details"] = f"yt-dlp executable was not found on system PATH or fallback locations: {bin_target}"
            logger.error("yt-dlp not found: %s", bin_target)
            return

        # Target H.264 video + AAC/M4A audio in MP4 container for smooth Pi Zero hardware playback
        # Resilient format fallback handles YouTube changes without failing downloads
        format_spec = f"bestvideo[vcodec^=avc1][height<={quality}]+bestaudio[ext!=webm]/bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best"
        output_template = os.path.join(output_dir, "%(title)s [%(id)s].%(ext)s")
        archive_path = os.path.join(output_dir, "download_archive.txt")

        # Essential flags:
        # --extractor-args youtube:player_client=android,web bypasses YouTube "Sign in to confirm you're not a bot" challenge
        cmd = ytdlp_cmd + [
            "--no-playlist",
            "-f", format_spec,
            "-S", "vcodec:h264,res,acodec:m4a",
            "--merge-output-format", "mp4",
            "--extractor-args", "youtube:player_client=android,web",
            "--socket-timeout", "30",
            "--retries", "3",
            "--fragment-retries", "3",
            "--compat-options", "filename-sanitization",
            "--download-archive", archive_path,
            "--no-mtime",
            "--newline",
            "-o", output_template,
            url
        ]

        logger.info("Starting yt-dlp download for '%s'...", task["title"])

        output_lines = []
        error_lines = []

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
            downloaded_filepath = None

            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue

                output_lines.append(line)
                if "ERROR:" in line or "error:" in line.lower() or "Sign in to confirm" in line or "HTTP Error" in line:
                    error_lines.append(line)

                # Capture destination or merged filepath from yt-dlp output
                dest_m = re.search(r"\[(?:download|Merger)\]\s+(?:Destination:\s+|Merging formats into\s+)\"?([^\"\n\r]+)\"?", line)
                if dest_m:
                    downloaded_filepath = dest_m.group(1).strip()

                # Check if archive matched an already-downloaded file
                if already_downloaded_regex.search(line):
                    with self.lock:
                        task["progress"] = 100.0
                        task["speed"] = "Archived"
                        task["eta"] = "00:00"
                        task["already_downloaded"] = True
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
                    task["error"] = None
                    task["error_details"] = None
                    self.completed_count += 1
                    if task.get("already_downloaded"):
                        task["completed_at"] = time.time() - 10.0
                    else:
                        task["completed_at"] = time.time()

                    # Sanitize filename on disk: eliminate emojis, icons, and unreadable characters
                    clean_target = self._sanitize_downloaded_file(output_dir, task, downloaded_filepath)
                    if clean_target:
                        clean_name = os.path.splitext(os.path.basename(clean_target))[0]
                        clean_title = re.sub(r"\s*\[[A-Za-z0-9_-]+\]$", "", clean_name)
                        task["title"] = clean_title or clean_name
                        task["filepath"] = clean_target

                    logger.info("Download completed successfully: %s", task["title"])
                else:
                    task["status"] = "error"

                    # Synthesize clear, meaningful human-readable error summary
                    error_summary = None
                    if error_lines:
                        for el in reversed(error_lines):
                            if "Sign in to confirm you" in el:
                                error_summary = "YouTube bot check: Sign in to confirm you're not a bot"
                                break
                            elif "HTTP Error 429" in el:
                                error_summary = "YouTube rate limited (HTTP 429: Too Many Requests)"
                                break
                            elif "Private video" in el or "Video unavailable" in el:
                                error_summary = "Video unavailable or private"
                                break
                            else:
                                clean_el = re.sub(r"^ERROR:\s*(\[[^\]]+\]\s*)?([A-Za-z0-9_-]+:\s*)?", "", el).strip()
                                if clean_el and len(clean_el) > 5:
                                    error_summary = clean_el
                                    break

                    if not error_summary:
                        for line in reversed(output_lines):
                            if not line.startswith("[download]") and len(line) > 5:
                                error_summary = line
                                break

                    task["error"] = error_summary or f"yt-dlp exited with error code {proc.returncode}"
                    task["error_details"] = "\n".join(output_lines[-25:]) if output_lines else f"Process exited with code {proc.returncode}"
                    logger.error("Download failed (code %d): %s -> %s", proc.returncode, task["title"], task["error"])

        except Exception as e:
            with self.lock:
                task["status"] = "error"
                task["error"] = str(e)
                task["error_details"] = str(e)
            logger.exception("Exception during download execution: %s", e)
        finally:
            if proc and proc.stdout:
                try:
                    proc.stdout.close()
                except Exception:
                    pass

    def _sanitize_downloaded_file(
        self,
        output_dir: str,
        task: Dict[str, Any],
        candidate_path: Optional[str] = None
    ) -> Optional[str]:
        """
        Locates the downloaded file on disk and renames it to remove emojis,
        icons, special characters, and unreadable glyphs.
        """
        target_file = None
        if candidate_path and os.path.isfile(candidate_path):
            target_file = candidate_path

        # If not directly identified, find by YouTube video ID in output_dir
        if not target_file:
            vid_m = re.search(r"(?:v=|youtu\.be/|vi/)([A-Za-z0-9_-]{11})", task.get("url", ""))
            if vid_m:
                vid = vid_m.group(1)
                try:
                    for entry in os.listdir(output_dir):
                        if f"[{vid}]" in entry and os.path.isfile(os.path.join(output_dir, entry)):
                            target_file = os.path.join(output_dir, entry)
                            break
                except Exception as e:
                    logger.debug("Error scanning output dir for video %s: %s", vid, e)

        if not target_file or not os.path.isfile(target_file):
            return None

        clean_path = sanitize_file_path(target_file)
        if clean_path != target_file:
            try:
                os.replace(target_file, clean_path)
                logger.info("Sanitized filename on disk: '%s' -> '%s'", os.path.basename(target_file), os.path.basename(clean_path))
                return clean_path
            except Exception as e:
                logger.warning("Failed to rename file '%s' to '%s': %s", target_file, clean_path, e)
                return target_file

        return target_file
