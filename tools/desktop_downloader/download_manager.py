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
import random
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

    # Avoid Windows reserved device names (CON, PRN, AUX, NUL, COM1-9, LPT1-9)
    windows_reserved = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
    }
    if cleaned.upper() in windows_reserved:
        cleaned = f"{cleaned}_song"

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


def get_free_disk_space_gb(path: str) -> float:
    """Returns free disk space in gigabytes for a path using cross-platform shutil.disk_usage."""
    try:
        usage = shutil.disk_usage(path)
        return round(usage.free / (1024 ** 3), 1)
    except Exception:
        return 0.0


def resolve_ytdlp_command() -> List[str]:
    """
    Finds available yt-dlp executable on the system.
    Searches PATH, ~/.local/bin, /usr/local/bin, /usr/bin, local tool bin, and repo root bin.
    """
    # 1. Search system PATH (including yt-dlp.exe on Windows)
    bin_names = ["yt-dlp.exe", "yt-dlp"] if sys.platform == "win32" else ["yt-dlp"]
    for bin_name in bin_names:
        which_bin = shutil.which(bin_name)
        if which_bin and os.path.isfile(which_bin):
            if sys.platform == "win32" or os.access(which_bin, os.X_OK):
                return [which_bin]

    user_home = os.path.expanduser("~")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, "..", ".."))

    candidates = [
        os.path.join(repo_root, "bin", "yt-dlp.exe"),
        os.path.join(repo_root, "bin", "yt-dlp"),
        os.path.join(script_dir, "bin", "yt-dlp.exe"),
        os.path.join(script_dir, "bin", "yt-dlp"),
        os.path.join(user_home, ".local", "bin", "yt-dlp"),
        "/usr/local/bin/yt-dlp",
        "/usr/bin/yt-dlp",
        "/opt/pikaraoke/venv/bin/yt-dlp"
    ]

    # Windows-specific candidate paths
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        prog_data = os.environ.get("PROGRAMDATA", "")
        candidates.extend([
            os.path.join(local_app_data, "Microsoft", "WinGet", "Links", "yt-dlp.exe"),
            os.path.join(prog_data, "chocolatey", "bin", "yt-dlp.exe"),
            os.path.join(user_home, "scoop", "shims", "yt-dlp.exe")
        ])

    for c in candidates:
        if c and os.path.isfile(c):
            if sys.platform == "win32" or os.access(c, os.X_OK):
                return [c]

    try:
        import yt_dlp
        return [sys.executable, "-m", "yt_dlp"]
    except ImportError:
        pass

    return ["yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"]


def detect_storage_devices() -> List[Dict[str, Any]]:
    """
    Detects mounted USB storage devices, external drives, and common folders
    available on Windows or Linux PC. Identifies KaraokeZero drives automatically.
    """
    devices: List[Dict[str, Any]] = []
    seen_paths = set()

    user_home = os.path.expanduser("~")
    username = os.environ.get("USERNAME") or os.environ.get("USER", os.path.basename(user_home))

    # --- Windows Drive Letter Detection ---
    if sys.platform == "win32":
        import string
        drive_letters = []
        try:
            import ctypes
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drive_letters.append(f"{letter}:\\")
                bitmask >>= 1
        except Exception:
            for letter in string.ascii_uppercase:
                d_root = f"{letter}:\\"
                if os.path.exists(d_root):
                    drive_letters.append(d_root)

        for drive_root in drive_letters:
            if not os.path.exists(drive_root):
                continue
            real_p = os.path.realpath(drive_root)
            if real_p in seen_paths:
                continue
            seen_paths.add(real_p)

            drive_type = 3  # default fixed
            volume_label = ""
            try:
                import ctypes
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_root)
                vol_buf = ctypes.create_unicode_buffer(261)
                fs_buf = ctypes.create_unicode_buffer(261)
                if ctypes.windll.kernel32.GetVolumeInformationW(
                    ctypes.c_wchar_p(drive_root),
                    vol_buf, ctypes.sizeof(vol_buf),
                    None, None, None,
                    fs_buf, ctypes.sizeof(fs_buf)
                ):
                    volume_label = vol_buf.value
            except Exception:
                pass

            is_removable = (drive_type == 2)
            system_drive = os.environ.get("SystemDrive", "C:").upper()
            drive_letter_only = drive_root[:2].upper()
            is_secondary = (drive_letter_only != system_drive)
            is_external = is_removable or is_secondary

            # Check if this is a KaraokeZero storage drive
            is_kz = False
            songs_subpath = os.path.join(drive_root, "songs")
            if os.path.isdir(os.path.join(drive_root, "songs")):
                songs_subpath = os.path.join(drive_root, "songs")
                is_kz = True
            elif os.path.isdir(os.path.join(drive_root, "karaoke", "songs")):
                songs_subpath = os.path.join(drive_root, "karaoke", "songs")
                is_kz = True
            elif "karaoke" in volume_label.lower():
                is_kz = True

            free_gb = get_free_disk_space_gb(drive_root)

            display_name = f"{volume_label} ({drive_root})" if volume_label else drive_root
            if is_kz:
                label = f"★ KaraokeZero HD: {display_name} ({free_gb} GB free)"
            elif is_removable:
                label = f"USB Drive: {display_name} ({free_gb} GB free)"
            else:
                label = f"Local Drive: {display_name} ({free_gb} GB free)"

            devices.append({
                "path": songs_subpath if is_kz else drive_root,
                "base_path": drive_root,
                "label": label,
                "free_gb": free_gb,
                "is_karaokezero": is_kz,
                "is_external": is_external
            })

    # --- Linux / Unix Mount Detection ---
    else:
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

                    free_gb = get_free_disk_space_gb(full_path)

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

    # Add standard default locations (Music & Downloads)
    default_music = os.path.join(user_home, "Music", "KaraokeZero")
    default_downloads = os.path.join(user_home, "Downloads", "KaraokeZero")

    for loc, name in [(default_music, "Music / KaraokeZero"), (default_downloads, "Downloads / KaraokeZero")]:
        free_gb = get_free_disk_space_gb(user_home)
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

        # Anti-ban and rate limit protection state
        self.rate_limit_active: bool = False
        self.rate_limit_cooldown_until: float = 0.0
        self.rate_limit_reason: str = ""
        self.pacing_status: Dict[str, Any] = {"active": False, "seconds": 0.0, "until": 0.0}

        # Configuration storage
        user_home = os.path.expanduser("~")
        self.config_dir = os.path.join(user_home, ".config", "karaokezero")
        os.makedirs(self.config_dir, exist_ok=True)
        self.config_file = config_path or os.path.join(self.config_dir, "desktop_downloader.json")
        self.settings: Dict[str, Any] = self._load_settings()

        # Start background worker and daily autonomous yt-dlp update check
        self.worker_thread = None
        if auto_start:
            self.start_worker()
            threading.Thread(target=self.check_and_update_ytdlp, kwargs={"force": False}, daemon=True).start()

    def start_worker(self):
        """Starts background worker thread if not already active."""
        if self.worker_thread is None or not self.worker_thread.is_alive():
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()

    def _load_settings(self) -> Dict[str, Any]:
        default_settings = {
            "output_dir": os.path.join(os.path.expanduser("~"), "Music", "KaraokeZero"),
            "default_quality": "480",
            "max_parallel": 1,
            "rate_limit_streaming": "5M",
            "pacing_min_seconds": 5,
            "pacing_max_seconds": 15,
            "browser_cookies": "none",
            "last_ytdlp_update_check": 0.0
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

            rate_limit_info = {
                "active": self.rate_limit_active,
                "cooldown_until": self.rate_limit_cooldown_until,
                "remaining_seconds": max(0, int(self.rate_limit_cooldown_until - now)) if self.rate_limit_active else 0,
                "reason": self.rate_limit_reason
            }
            pacing_active = bool(self.pacing_status.get("active") and self.pacing_status.get("until", 0) > now)
            pacing_info = {
                "active": pacing_active,
                "seconds": self.pacing_status.get("seconds", 0.0),
                "remaining_seconds": max(0, round(self.pacing_status.get("until", 0) - now, 1)) if pacing_active else 0.0
            }

            return {
                "is_paused": self.is_paused,
                "active": active,
                "queued": queued,
                "completed": completed,
                "errors": errors,
                "completed_count": self.completed_count,
                "total_count": len(all_tasks),
                "tasks": all_tasks,
                "rate_limit": rate_limit_info,
                "pacing": pacing_info
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
                        if sys.platform == "win32":
                            try:
                                subprocess.run(
                                    ["taskkill", "/F", "/T", "/PID", str(self.current_process.pid)],
                                    capture_output=True,
                                    timeout=2
                                )
                            except Exception:
                                self.current_process.terminate()
                        else:
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

    def dismiss_rate_limit(self) -> bool:
        """Manually dismisses rate limit cooldown and resumes queue."""
        with self.lock:
            self.rate_limit_active = False
            self.rate_limit_cooldown_until = 0.0
            self.rate_limit_reason = ""
            self.is_paused = False
        logger.info("YouTube rate limit cooldown dismissed manually by user.")
        return True

    def check_and_update_ytdlp(self, force: bool = False) -> Dict[str, Any]:
        """
        Checks for yt-dlp updates and updates the binary if last check was > 24 hours ago
        or if forced. Updates cipher decoders against YouTube's evolving base.js.
        """
        now = time.time()
        last_check = float(self.settings.get("last_ytdlp_update_check", 0) or 0)
        # 24 hours = 86400 seconds
        if not force and (now - last_check) < 86400:
            return {
                "success": True,
                "status": "cached",
                "message": "yt-dlp is already up to date for today.",
                "last_check": last_check
            }

        ytdlp_cmd = resolve_ytdlp_command()
        bin_target = ytdlp_cmd[0]
        logger.info("Checking for yt-dlp updates (target: %s)...", bin_target)

        update_success = False
        output = ""
        try:
            cmd = [bin_target, "-U"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            output = (res.stdout + "\n" + res.stderr).strip()
            if res.returncode == 0:
                update_success = True
                logger.info("yt-dlp update check completed: %s", output.splitlines()[-1] if output else "OK")
            else:
                logger.info("yt-dlp -U output (code %d): %s", res.returncode, output)
                if "up to date" in output.lower():
                    update_success = True
                elif "not supported" in output.lower() or "pip" in output.lower():
                    pip_res = subprocess.run(
                        [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                        capture_output=True, text=True, timeout=60
                    )
                    if pip_res.returncode == 0:
                        update_success = True
                        output = "Updated via pip"
        except Exception as e:
            logger.warning("Error running yt-dlp update: %s", e)
            output = str(e)

        self.save_settings({"last_ytdlp_update_check": now})
        return {
            "success": update_success,
            "status": "updated" if update_success else ("ok" if "up to date" in output.lower() else "notice"),
            "output": output,
            "last_check": now
        }

    def _worker_loop(self):
        while True:
            try:
                # 1. Check rate limit cooldown status (HTTP 429 mitigation)
                if self.rate_limit_active:
                    now = time.time()
                    if now < self.rate_limit_cooldown_until:
                        time.sleep(1.0)
                        continue
                    else:
                        with self.lock:
                            self.rate_limit_active = False
                            self.rate_limit_cooldown_until = 0.0
                            self.rate_limit_reason = ""
                            self.is_paused = False
                        logger.info("YouTube rate limit cooldown expired! Resuming download queue.")

                if self.is_paused:
                    time.sleep(0.5)
                    continue

                try:
                    task_id = self.queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                with self.lock:
                    if self.is_paused or self.rate_limit_active:
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

                # 2. Behavioral Mitigation: Randomized pacing delay between consecutive downloads
                has_pending = False
                with self.lock:
                    has_pending = any(t.get("status") == "queued" for t in self.tasks.values())
                    is_active = not self.is_paused and not self.rate_limit_active

                if has_pending and is_active:
                    min_sec = float(self.settings.get("pacing_min_seconds", 5))
                    max_sec = float(self.settings.get("pacing_max_seconds", 15))
                    pacing_delay = random.uniform(min_sec, max_sec)
                    with self.lock:
                        self.pacing_status = {
                            "active": True,
                            "seconds": round(pacing_delay, 1),
                            "until": time.time() + pacing_delay
                        }
                    logger.info("Anti-ban human pacing: sleeping %.1fs before next download...", pacing_delay)

                    slept = 0.0
                    while slept < pacing_delay:
                        if self.is_paused or self.rate_limit_active:
                            break
                        time.sleep(0.5)
                        slept += 0.5

                    with self.lock:
                        self.pacing_status = {"active": False, "seconds": 0.0, "until": 0.0}

            except Exception as e:
                logger.exception("Worker loop exception: %s", e)
            finally:
                time.sleep(0.5)

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
        format_spec = f"bestvideo[height<={quality}][vcodec^=avc1]+bestaudio[acodec^=mp4a]/bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best"
        sort_spec = f"res:{quality},vcodec:h264,acodec:m4a"
        output_template = os.path.join(output_dir, "%(title)s [%(id)s].%(ext)s")
        archive_path = os.path.join(output_dir, "download_archive.txt")

        # Essential flags:
        # --limit-rate 5M restricts burst bandwidth to mimic real-time video streaming
        # --sleep-requests throttles rapid API calls during extraction
        rate_limit = self.settings.get("rate_limit_streaming", "5M")
        cmd = ytdlp_cmd + [
            "--no-playlist",
            "-f", format_spec,
            "-S", sort_spec,
            "--merge-output-format", "mp4",
            "--limit-rate", rate_limit,
            "--sleep-requests", "1.5",
            "--socket-timeout", "30",
            "--retries", "3",
            "--fragment-retries", "3",
            "--compat-options", "filename-sanitization",
            "--download-archive", archive_path,
            "--no-mtime",
            "--newline",
            "-o", output_template,
        ]

        # Ensure a JavaScript runtime is configured so yt-dlp can solve YouTube cipher and n-challenges
        deno_bin = (
            shutil.which("deno")
            or (os.path.isfile(os.path.expanduser("~/.deno/bin/deno")) and os.path.expanduser("~/.deno/bin/deno"))
            or (sys.platform == "win32" and os.path.isfile(os.path.expandvars(r"%USERPROFILE%\.deno\bin\deno.exe")) and os.path.expandvars(r"%USERPROFILE%\.deno\bin\deno.exe"))
        )
        if deno_bin:
            cmd.extend(["--js-runtimes", f"deno:{deno_bin}"])
        else:
            qjs_bin = shutil.which("qjs") or shutil.which("quickjs")
            if qjs_bin:
                cmd.extend(["--js-runtimes", f"quickjs:{qjs_bin}"])

        # Optional browser cookies or cookies.txt to bypass YouTube bot verification challenges
        cookies_file = os.path.join(self.config_dir, "cookies.txt")
        if os.path.isfile(cookies_file) and os.path.getsize(cookies_file) > 0:
            cmd.extend(["--cookies", cookies_file])
        else:
            browser_cookies = self.settings.get("browser_cookies", "none")
            if browser_cookies and browser_cookies != "none":
                cmd.extend(["--cookies-from-browser", browser_cookies])

        cmd.append(url)

        logger.info("Starting yt-dlp download for '%s'...", task["title"])

        output_lines = []
        error_lines = []

        try:
            env = dict(os.environ)
            deno_dir = os.path.expanduser("~/.deno/bin")
            if os.path.isdir(deno_dir) and deno_dir not in env.get("PATH", ""):
                env["PATH"] = f"{deno_dir}:{env.get('PATH', '')}"

            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                env=env
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
                is_warning = line.startswith("WARNING:") or "[youtube] WARNING" in line
                if not is_warning:
                    if "ERROR:" in line or "Sign in to confirm" in line or line.lower().startswith("error:"):
                        error_lines.append(line)
                    elif "HTTP Error" in line and "Unable to download webpage" not in line:
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

                    # Check if error was caused by genuine fatal rate limiting (HTTP 429)
                    # Non-fatal warnings like "Unable to download webpage: HTTP Error 429" are ignored
                    is_rate_limited = any(
                        ("HTTP Error 429" in l or "429: Too Many Requests" in l)
                        and not l.startswith("WARNING:")
                        and "Unable to download webpage" not in l
                        for l in error_lines
                    )
                    if is_rate_limited:
                        cooldown_secs = 30 * 60  # 30-minute safety cooldown
                        self.rate_limit_active = True
                        self.rate_limit_cooldown_until = time.time() + cooldown_secs
                        self.rate_limit_reason = "YouTube rate limit (HTTP 429: Too Many Requests) detected."
                        self.is_paused = True
                        logger.warning(
                            "YouTube rate limit (HTTP 429) detected! Automatically suspending download queue for 30 minutes to safeguard IP address."
                        )

                    # Synthesize clear, meaningful human-readable error summary
                    error_summary = None
                    if error_lines:
                        for el in reversed(error_lines):
                            if "Sign in to confirm you" in el:
                                error_summary = "YouTube bot check: Sign in required (configure browser cookies in Settings)"
                                break
                            elif "HTTP Error 429" in el or "429: Too Many Requests" in el:
                                error_summary = "YouTube rate limited (HTTP 429: Too Many Requests)"
                                break
                            elif "Private video" in el or "Video unavailable" in el:
                                error_summary = "Video unavailable or private"
                                break
                            elif "The page needs to be reloaded" in el:
                                error_summary = "YouTube challenge failed: The page needs to be reloaded (A JavaScript runtime like Deno is required)"
                                break
                            elif "Requested format is not available" in el:
                                error_summary = "Requested format not available for this video"
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
            for attempt in range(3):
                try:
                    os.replace(target_file, clean_path)
                    logger.info("Sanitized filename on disk: '%s' -> '%s'", os.path.basename(target_file), os.path.basename(clean_path))
                    return clean_path
                except PermissionError:
                    time.sleep(0.15)
                except Exception as e:
                    logger.warning("Failed to rename file '%s' to '%s': %s", target_file, clean_path, e)
                    return target_file
            return target_file

        return target_file
