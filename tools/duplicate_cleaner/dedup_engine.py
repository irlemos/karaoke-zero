#!/usr/bin/env python3
"""
KaraokeZero Video Deduplication Engine
Detects duplicate video and audio files across directories using multiple strategies:
1. Exact binary content hash (SHA-256 with fast multi-tier filtering)
2. YouTube Video ID extraction from filename
3. Audio stream fingerprinting (MD5 of decoded PCM audio stream via ffmpeg)
4. Exact duration and normalized title fuzzy matching

Selects the optimal file to keep based on video resolution, Raspberry Pi Zero H.264
hardware acceleration compatibility, and filename cleanliness.
"""

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import time
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("DuplicateCleaner.Engine")

MEDIA_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".avi", ".mov",
    ".flv", ".m4v", ".mpg", ".mpeg", ".wmv", ".ts"
}


class MatchStrategy(Enum):
    EXACT_HASH = "exact_hash"
    YOUTUBE_ID = "youtube_id"
    AUDIO_STREAM = "audio_stream"
    DURATION_TITLE = "duration_title"
    ALL = "all"


@dataclass
class MediaFile:
    path: str
    filename: str
    size: int
    mtime: float
    video_id: Optional[str] = None
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    vcodec: Optional[str] = None
    acodec: Optional[str] = None
    file_hash: Optional[str] = None
    audio_hash: Optional[str] = None
    clean_title: str = ""
    quality_score: float = 0.0

    @property
    def resolution_str(self) -> str:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        if self.height:
            return f"{self.height}p"
        return "Unknown Res"

    @property
    def duration_str(self) -> str:
        if not self.duration:
            return "--:--"
        m, s = divmod(int(round(self.duration)), 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    @property
    def size_mb(self) -> float:
        return round(self.size / (1024 * 1024), 2)


@dataclass
class DuplicateGroup:
    group_id: str
    matched_by: str
    keeper: MediaFile
    duplicates: List[MediaFile]
    wasted_bytes: int = 0

    def all_files(self) -> List[MediaFile]:
        return [self.keeper] + self.duplicates


def normalize_title(name: str) -> str:
    """Normalizes song title for fuzzy duplicate matching."""
    s = unicodedata.normalize("NFKC", name)
    s = re.sub(r"\[[A-Za-z0-9_-]{6,}\]", "", s)
    s = re.sub(r"\.[a-zA-Z0-9]+$", "", s)
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def extract_youtube_id(filename: str) -> Optional[str]:
    """Extracts 11-character YouTube video ID from bracketed filename."""
    m = re.search(r"\[([A-Za-z0-9_-]{11})\]", filename)
    if m:
        return m.group(1)
    m = re.search(r"(?:^|[\s_-])([A-Za-z0-9_-]{11})(?:\.[a-zA-Z0-9]+)?$", filename)
    return None


def calculate_file_hash(filepath: str, block_size: int = 65536) -> str:
    """Calculates full SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(block_size):
            h.update(chunk)
    return h.hexdigest()


def calculate_partial_hash(filepath: str, sample_size: int = 65536) -> str:
    """Calculates fast header + footer hash for quick duplicate elimination."""
    size = os.path.getsize(filepath)
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        if size <= sample_size * 2:
            h.update(f.read())
        else:
            h.update(f.read(sample_size))
            f.seek(size - sample_size)
            h.update(f.read(sample_size))
    return h.hexdigest()


def probe_media_info(filepath: str, ffprobe_bin: str = "ffprobe") -> Dict[str, Any]:
    """Extracts duration, resolution, and codecs via ffprobe."""
    if not shutil.which(ffprobe_bin) and not os.path.isfile(ffprobe_bin):
        return {}

    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-show_entries", "format=duration,size,bit_rate:stream=width,height,codec_name,codec_type",
        "-of", "json",
        filepath
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            return {}
        return json.loads(proc.stdout)
    except Exception as e:
        logger.debug("ffprobe error on %s: %s", filepath, e)
        return {}


def calculate_audio_stream_hash(filepath: str, ffmpeg_bin: str = "ffmpeg") -> Optional[str]:
    """
    Computes an MD5 checksum of the raw decoded audio stream.
    Identical audio will produce the exact same hash regardless of video resolution or container metadata.
    """
    if not shutil.which(ffmpeg_bin) and not os.path.isfile(ffmpeg_bin):
        return None

    cmd = [
        ffmpeg_bin,
        "-v", "error",
        "-i", filepath,
        "-map", "0:a:0",
        "-vn",
        "-f", "md5",
        "-"
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        if proc.returncode == 0:
            out = proc.stdout.strip()
            return out.replace("MD5=", "").strip()
    except Exception as e:
        logger.debug("ffmpeg audio hash error on %s: %s", filepath, e)
    return None


def score_media_file(mf: MediaFile) -> float:
    """
    Computes a quality and preference score for a media file to determine
    which duplicate should be kept.
    Prioritizes:
    - Pi Zero W hardware compatibility (H.264 video + AAC audio)
    - Optimal resolution (720p or 480p preferred for Pi Zero performance)
    - Clean, standardized naming (e.g. 'Artist - Song [id].mp4')
    """
    score = 100.0

    # Resolution scoring (720p is sweet spot for Pi Zero W; 1080p is sharp; 480p is smooth)
    if mf.height:
        if mf.height == 720:
            score += 40.0
        elif mf.height == 480:
            score += 35.0
        elif mf.height == 1080:
            score += 30.0
        elif mf.height < 480:
            score += 15.0

    # Video codec scoring: H.264 (avc1) is hardware-accelerated on Pi Zero W
    if mf.vcodec:
        if "h264" in mf.vcodec.lower() or "avc" in mf.vcodec.lower():
            score += 25.0
        elif "vp9" in mf.vcodec.lower() or "av1" in mf.vcodec.lower():
            # CPU intensive on Pi Zero
            score -= 20.0

    # Audio codec scoring: AAC is natively accelerated
    if mf.acodec:
        if "aac" in mf.acodec.lower() or "mp4a" in mf.acodec.lower():
            score += 15.0

    # Filename quality scoring
    fn = mf.filename
    # Clean separator ' - '
    if " - " in fn:
        score += 20.0
    # Has YouTube ID bracket
    if mf.video_id:
        score += 15.0
    # Penalize random numbers or camera filenames
    if re.search(r"^(VID|IMG|FILE|track|output|download|song)[\d_-]+", fn, re.IGNORECASE):
        score -= 40.0
    if len(fn) < 8:
        score -= 30.0

    return score


class VideoDeduplicator:
    """
    Scans directory of video files and groups duplicates using multiple tiers.
    """

    def __init__(self, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe"):
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin

    def scan_directory(
        self,
        directory: str,
        strategy: MatchStrategy = MatchStrategy.ALL,
        deep_audio: bool = True,
        progress_cb: Optional[Callable[[int, int, str], None]] = None
    ) -> List[DuplicateGroup]:
        """
        Scans directory and returns list of DuplicateGroup objects.
        """
        if not os.path.isdir(directory):
            logger.error("Directory not found: %s", directory)
            return []

        # 1. Discover media files
        raw_files = []
        for root, _, filenames in os.walk(directory):
            # Skip hidden trash directories
            if "/.trash" in root or "/.duplicates_trash" in root:
                continue
            for fn in filenames:
                ext = os.path.splitext(fn)[1].lower()
                if ext in MEDIA_EXTENSIONS:
                    fp = os.path.join(root, fn)
                    try:
                        sz = os.path.getsize(fp)
                        if sz > 0:
                            raw_files.append(fp)
                    except OSError:
                        pass

        total_files = len(raw_files)
        logger.info("Found %d media files to analyze in '%s'", total_files, directory)
        if total_files < 2:
            return []

        # 2. Extract media metadata
        media_files: List[MediaFile] = []
        for idx, fp in enumerate(raw_files):
            if progress_cb:
                progress_cb(idx + 1, total_files, os.path.basename(fp))

            fn = os.path.basename(fp)
            sz = os.path.getsize(fp)
            mt = os.path.getmtime(fp)
            yid = extract_youtube_id(fn)
            clean_t = normalize_title(fn)

            mf = MediaFile(
                path=fp,
                filename=fn,
                size=sz,
                mtime=mt,
                video_id=yid,
                clean_title=clean_t
            )

            # Probe media metadata
            info = probe_media_info(fp, ffprobe_bin=self.ffprobe_bin)
            fmt = info.get("format", {})
            if "duration" in fmt:
                try:
                    mf.duration = float(fmt["duration"])
                except ValueError:
                    pass

            for s in info.get("streams", []):
                if s.get("codec_type") == "video" and not mf.width:
                    mf.width = s.get("width")
                    mf.height = s.get("height")
                    mf.vcodec = s.get("codec_name")
                elif s.get("codec_type") == "audio" and not mf.acodec:
                    mf.acodec = s.get("codec_name")

            mf.quality_score = score_media_file(mf)
            media_files.append(mf)

        # 3. Detect duplicates via requested strategies
        handled_paths: Set[str] = set()
        duplicate_groups: List[DuplicateGroup] = []

        # Tier 1: Exact Binary Hash (Fast partial sample -> full hash)
        if strategy in (MatchStrategy.ALL, MatchStrategy.EXACT_HASH):
            hash_groups = self._find_exact_hash_duplicates(media_files, handled_paths)
            for g in hash_groups:
                duplicate_groups.append(g)
                for f in g.all_files():
                    handled_paths.add(f.path)

        # Tier 2: YouTube Video ID Match
        if strategy in (MatchStrategy.ALL, MatchStrategy.YOUTUBE_ID):
            yt_groups = self._find_youtube_id_duplicates(media_files, handled_paths)
            for g in yt_groups:
                duplicate_groups.append(g)
                for f in g.all_files():
                    handled_paths.add(f.path)

        # Tier 3: Audio Stream Fingerprint Match (deep audio md5)
        if deep_audio and strategy in (MatchStrategy.ALL, MatchStrategy.AUDIO_STREAM):
            audio_groups = self._find_audio_stream_duplicates(media_files, handled_paths)
            for g in audio_groups:
                duplicate_groups.append(g)
                for f in g.all_files():
                    handled_paths.add(f.path)

        # Tier 4: Exact Duration + Clean Title Fuzzy Match
        if strategy in (MatchStrategy.ALL, MatchStrategy.DURATION_TITLE):
            fuzzy_groups = self._find_fuzzy_duplicates(media_files, handled_paths)
            for g in fuzzy_groups:
                duplicate_groups.append(g)
                for f in g.all_files():
                    handled_paths.add(f.path)

        return duplicate_groups

    def _create_group(self, matched_by: str, files: List[MediaFile], group_num: int) -> DuplicateGroup:
        # Sort files by quality score descending
        sorted_files = sorted(files, key=lambda f: (f.quality_score, f.size), reverse=True)
        keeper = sorted_files[0]
        duplicates = sorted_files[1:]
        wasted = sum(d.size for d in duplicates)
        return DuplicateGroup(
            group_id=f"group_{group_num}",
            matched_by=matched_by,
            keeper=keeper,
            duplicates=duplicates,
            wasted_bytes=wasted
        )

    def _find_exact_hash_duplicates(self, files: List[MediaFile], handled: Set[str]) -> List[DuplicateGroup]:
        available = [f for f in files if f.path not in handled]
        size_buckets: Dict[int, List[MediaFile]] = {}
        for f in available:
            size_buckets.setdefault(f.size, []).append(f)

        candidates = [lst for sz, lst in size_buckets.items() if len(lst) > 1 and sz > 0]
        groups = []

        # Partial hash check
        for bucket in candidates:
            sample_buckets: Dict[str, List[MediaFile]] = {}
            for f in bucket:
                phash = calculate_partial_hash(f.path)
                sample_buckets.setdefault(phash, []).append(f)

            for shash, s_lst in sample_buckets.items():
                if len(s_lst) > 1:
                    # Full hash confirmation
                    full_buckets: Dict[str, List[MediaFile]] = {}
                    for f in s_lst:
                        if not f.file_hash:
                            f.file_hash = calculate_file_hash(f.path)
                        full_buckets.setdefault(f.file_hash, []).append(f)

                    for fhash, f_lst in full_buckets.items():
                        if len(f_lst) > 1:
                            groups.append(self._create_group("Exact Binary Content (100% Identical)", f_lst, len(groups) + 1))

        return groups

    def _find_youtube_id_duplicates(self, files: List[MediaFile], handled: Set[str]) -> List[DuplicateGroup]:
        available = [f for f in files if f.path not in handled and f.video_id]
        yt_buckets: Dict[str, List[MediaFile]] = {}
        for f in available:
            yt_buckets.setdefault(f.video_id, []).append(f)

        groups = []
        for yid, lst in yt_buckets.items():
            if len(lst) > 1:
                groups.append(self._create_group(f"YouTube Video ID [{yid}]", lst, len(groups) + 1))
        return groups

    def _find_audio_stream_duplicates(self, files: List[MediaFile], handled: Set[str]) -> List[DuplicateGroup]:
        available = [f for f in files if f.path not in handled and f.duration]
        # Group by rounded duration (within 1 second) to minimize ffmpeg calls
        dur_buckets: Dict[int, List[MediaFile]] = {}
        for f in available:
            dur_buckets.setdefault(int(round(f.duration or 0)), []).append(f)

        groups = []
        for dur, lst in dur_buckets.items():
            if len(lst) > 1 and dur > 10:  # Minimum 10 seconds song
                audio_buckets: Dict[str, List[MediaFile]] = {}
                for f in lst:
                    if not f.audio_hash:
                        f.audio_hash = calculate_audio_stream_hash(f.path, self.ffmpeg_bin)
                    if f.audio_hash:
                        audio_buckets.setdefault(f.audio_hash, []).append(f)

                for ahash, a_lst in audio_buckets.items():
                    if len(a_lst) > 1:
                        groups.append(self._create_group("Audio Stream Fingerprint (Identical Soundtrack)", a_lst, len(groups) + 1))
        return groups

    def _find_fuzzy_duplicates(self, files: List[MediaFile], handled: Set[str]) -> List[DuplicateGroup]:
        available = [f for f in files if f.path not in handled and f.duration and f.clean_title]
        groups = []
        visited = set()

        for i in range(len(available)):
            f1 = available[i]
            if f1.path in visited:
                continue

            matches = [f1]
            for j in range(i + 1, len(available)):
                f2 = available[j]
                if f2.path in visited:
                    continue

                # Match if duration is within 0.5s AND clean titles are identical
                dur_diff = abs((f1.duration or 0) - (f2.duration or 0))
                if dur_diff <= 0.5 and f1.clean_title == f2.clean_title:
                    matches.append(f2)
                    visited.add(f2.path)

            if len(matches) > 1:
                visited.add(f1.path)
                groups.append(self._create_group("Exact Duration & Normalized Title Match", matches, len(groups) + 1))

        return groups

    def delete_file(self, filepath: str, move_to_trash: bool = False, trash_dir: Optional[str] = None) -> bool:
        """
        Safely removes a duplicate file.
        If move_to_trash is True, moves to a backup trash folder instead of permanent unlinking.
        """
        if not os.path.isfile(filepath):
            return False

        try:
            if move_to_trash:
                target_dir = trash_dir or os.path.join(os.path.dirname(filepath), ".trash")
                os.makedirs(target_dir, exist_ok=True)
                dest = os.path.join(target_dir, os.path.basename(filepath))
                # Handle filename collisions in trash
                base, ext = os.path.splitext(dest)
                counter = 1
                while os.path.exists(dest):
                    dest = f"{base}_{counter}{ext}"
                    counter += 1
                shutil.move(filepath, dest)
                logger.info("Moved duplicate to trash: '%s' -> '%s'", filepath, dest)
            else:
                os.unlink(filepath)
                logger.info("Permanently deleted duplicate: '%s'", filepath)
            return True
        except Exception as e:
            logger.error("Failed to remove duplicate '%s': %s", filepath, e)
            return False
