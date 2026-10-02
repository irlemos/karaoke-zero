#!/usr/bin/env python3
"""
KaraokeZero Desktop Downloader - YouTube Search & Playlist Engine
Uses YouTube Innertube API via pure standard library (urllib.request)
to search videos and extract thumbnails, titles, durations, and channels
without any Google API keys or external pip dependencies.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

try:
    from download_manager import sanitize_filename
except ImportError:
    try:
        from desktop_downloader.download_manager import sanitize_filename
    except ImportError:
        def sanitize_filename(name: str, max_len: int = 180) -> str:
            return name

logger = logging.getLogger("DesktopDownloader.Search")


def parse_duration_seconds(duration_str: str) -> int:
    """Parses a time string formatted as HH:MM:SS or MM:SS into total seconds."""
    if not duration_str or not isinstance(duration_str, str):
        return 0
    parts = duration_str.strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 1 and parts[0].isdigit():
            return int(parts[0])
    except (ValueError, TypeError):
        pass
    return 0


def search_youtube(query: str, max_results: int = 15, ytdlp_cmd: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Searches YouTube for karaoke videos and returns rich metadata including
    high-resolution thumbnails, duration, channel name, and video ID.
    Zero external pip dependencies (pure Python standard library).
    """
    clean_query = query.strip()
    if not clean_query:
        return []

    # 1. Direct YouTube video URL or 11-char video ID detection
    url_match = re.search(r"(?:v=|youtu\.be\/|embed\/|^)([A-Za-z0-9_-]{11})(?:[&?]|$)", clean_query)
    if url_match and ("youtube.com" in clean_query or "youtu.be" in clean_query or len(clean_query) == 11):
        vid = url_match.group(1)
        try:
            oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json"
            req = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return [{
                    "id": vid,
                    "title": data.get("title") or f"YouTube Video ({vid})",
                    "uploader": data.get("author_name") or "YouTube",
                    "duration": "",
                    "thumbnail": data.get("thumbnail_url") or f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                    "url": f"https://www.youtube.com/watch?v={vid}"
                }]
        except Exception as e:
            logger.debug("Direct oEmbed lookup error for %s: %s", vid, e)
            return [{
                "id": vid,
                "title": f"YouTube Video ({vid})",
                "uploader": "YouTube",
                "duration": "",
                "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                "url": f"https://www.youtube.com/watch?v={vid}"
            }]

    # 2. Primary Engine: YouTube Innertube API (Runs in ~250ms, zero CPU overhead)
    search_term = clean_query
    if "karaoke" not in search_term.lower():
        search_term = f"{clean_query} karaoke"

    try:
        url = "https://www.youtube.com/youtubei/v1/search"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        payload = {
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": "2.20240101.01.00"
                }
            },
            "query": search_term
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        sections = data.get("contents", {}).get("twoColumnSearchResultsRenderer", {}).get("primaryContents", {}).get("sectionListRenderer", {}).get("contents", [])
        results: List[Dict[str, Any]] = []

        for sec in sections:
            items = sec.get("itemSectionRenderer", {}).get("contents", [])
            for it in items:
                v = it.get("videoRenderer")
                if v and "videoId" in v:
                    vid = v["videoId"]
                    title = "".join(r.get("text", "") for r in v.get("title", {}).get("runs", []))
                    uploader = "".join(r.get("text", "") for r in v.get("ownerText", {}).get("runs", []))
                    duration = v.get("lengthText", {}).get("simpleText", "")
                    thumbs = v.get("thumbnail", {}).get("thumbnails", [])
                    thumb = thumbs[-1].get("url") if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

                    results.append({
                        "id": vid,
                        "title": sanitize_filename(title) if title else "Unknown Title",
                        "uploader": uploader or "Unknown Artist",
                        "channel": uploader or "Unknown Artist",
                        "duration": duration,
                        "duration_sec": parse_duration_seconds(duration),
                        "thumbnail": thumb,
                        "url": f"https://www.youtube.com/watch?v={vid}"
                    })
                    if len(results) >= max_results:
                        break
            if len(results) >= max_results:
                break

        if results:
            logger.info("YouTube Innertube search found %d results for '%s'", len(results), search_term)
            return results
    except Exception as e:
        logger.warning("YouTube Innertube search failed: %s. Attempting yt-dlp fallback...", e)

    # 3. Fallback Engine: yt-dlp Subprocess (if available)
    cmd_base = ytdlp_cmd or ["yt-dlp"]
    if shutil.which(cmd_base[0]):
        cmd = cmd_base + [
            f"ytsearch{max_results}:{search_term}",
            "-j",
            "--no-playlist",
            "--flat-playlist",
            "--skip-download",
            "--no-warnings"
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=40)
            if res.returncode == 0:
                results = []
                for line in res.stdout.strip().splitlines():
                    if not line:
                        continue
                    try:
                        v = json.loads(line)
                        vid = v.get("id")
                        if not vid:
                            continue
                        duration_sec = v.get("duration") or 0
                        duration_str = ""
                        if duration_sec:
                            m, s = divmod(int(duration_sec), 60)
                            duration_str = f"{m}:{s:02d}"
                        thumbs = v.get("thumbnails", [])
                        thumb = thumbs[-1].get("url") if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
                        upl = v.get("uploader") or "Unknown Artist"
                        results.append({
                            "id": vid,
                            "title": sanitize_filename(v.get("title") or "Unknown Title"),
                            "uploader": upl,
                            "channel": upl,
                            "duration": duration_str,
                            "duration_sec": int(duration_sec),
                            "thumbnail": thumb,
                            "url": f"https://www.youtube.com/watch?v={vid}"
                        })
                    except Exception:
                        pass
                if results:
                    return results
        except Exception as e:
            logger.error("yt-dlp fallback search error: %s", e)

    return []


def search_playlists(query: str, max_results: int = 15) -> List[Dict[str, Any]]:
    """
    Searches YouTube specifically for complete playlists matching the query.
    Uses YouTube search with playlist filter (sp=EgIQAw%3D%3D) via pure Python standard library.
    Returns playlist title, ID, video count, channel, thumbnail, and URL.
    """
    clean_query = query.strip()
    if not clean_query:
        return []

    if "playlist" not in clean_query.lower() and "karaoke" not in clean_query.lower():
        search_query = f"{clean_query} karaoke"
    else:
        search_query = clean_query

    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(search_query)}&sp=EgIQAw%3D%3D"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8")

        m = re.search(r"var ytInitialData = ({.+?});<\/script>", html)
        if not m:
            return []

        data = json.loads(m.group(1))

        def walk_tree(obj):
            found = []
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k == "lockupViewModel" and v.get("contentType") == "LOCKUP_CONTENT_TYPE_PLAYLIST":
                        found.append(("lockup", v))
                    elif k == "playlistRenderer":
                        found.append(("renderer", v))
                    else:
                        found.extend(walk_tree(v))
            elif isinstance(obj, list):
                for item in obj:
                    found.extend(walk_tree(item))
            return found

        results: List[Dict[str, Any]] = []
        seen = set()

        for kind, node in walk_tree(data):
            if kind == "lockup":
                pid = node.get("contentId")
                if not pid or pid in seen:
                    continue

                title = (
                    node.get("metadata", {}).get("lockupMetadataViewModel", {}).get("title", {}).get("content")
                    or f"Playlist {pid}"
                )

                channel = ""
                rows = node.get("metadata", {}).get("lockupMetadataViewModel", {}).get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
                if rows:
                    parts = rows[0].get("metadataParts", [])
                    if parts:
                        channel = parts[0].get("text", {}).get("content", "")

                count_str = ""
                overlays = node.get("contentImage", {}).get("collectionThumbnailViewModel", {}).get("primaryThumbnail", {}).get("thumbnailViewModel", {}).get("overlays", [])
                for ov in overlays:
                    badges = ov.get("thumbnailOverlayBadgeViewModel", {}).get("thumbnailBadges", [])
                    for b in badges:
                        badge_text = b.get("thumbnailBadgeViewModel", {}).get("text")
                        if badge_text:
                            count_str = badge_text
                            break

                thumbs = node.get("contentImage", {}).get("collectionThumbnailViewModel", {}).get("primaryThumbnail", {}).get("thumbnailViewModel", {}).get("image", {}).get("sources", [])
                thumb = thumbs[-1].get("url") if thumbs else f"https://i.ytimg.com/vi/default/hqdefault.jpg"

                seen.add(pid)
                results.append({
                    "id": pid,
                    "title": sanitize_filename(title),
                    "channel": channel or "YouTube",
                    "uploader": channel or "YouTube",
                    "video_count": count_str or "Full Playlist",
                    "thumbnail": thumb,
                    "url": f"https://www.youtube.com/playlist?list={pid}"
                })

            elif kind == "renderer":
                pid = node.get("playlistId")
                if not pid or pid in seen:
                    continue

                title = (
                    "".join(r.get("text", "") for r in node.get("title", {}).get("runs", []))
                    or node.get("title", {}).get("simpleText")
                    or f"Playlist {pid}"
                )
                channel = "".join(r.get("text", "") for r in node.get("ownerText", {}).get("runs", []))
                count_str = node.get("videoCount") or node.get("videoCountText", {}).get("simpleText") or ""
                thumbs = node.get("thumbnails", [{}])[0].get("thumbnails", [{}])
                thumb = thumbs[-1].get("url") if thumbs else f"https://i.ytimg.com/vi/default/hqdefault.jpg"

                seen.add(pid)
                results.append({
                    "id": pid,
                    "title": sanitize_filename(title),
                    "channel": channel or "YouTube",
                    "uploader": channel or "YouTube",
                    "video_count": count_str or "Full Playlist",
                    "thumbnail": thumb,
                    "url": f"https://www.youtube.com/playlist?list={pid}"
                })

            if len(results) >= max_results:
                break

        logger.info("Found %d playlists for '%s'", len(results), search_query)
        return results

    except Exception as e:
        logger.warning("Search playlists error: %s", e)
        return []


def extract_playlist_info(playlist_url: str, ytdlp_cmd: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Extracts all video entries from a YouTube playlist URL using yt-dlp --flat-playlist.
    Returns playlist title, count, and list of video items with thumbnails and IDs.
    """
    cmd_base = ytdlp_cmd or ["yt-dlp"]
    bin_target = cmd_base[0]

    if not shutil.which(bin_target) and not os.path.isfile(bin_target):
        return {
            "success": False,
            "error": "yt-dlp executable not found. Please install yt-dlp to inspect playlists.",
            "title": "",
            "items": []
        }

    # Normalize watch URL with list parameter to clean playlist URL
    target_url = playlist_url.strip()
    list_match = re.search(r"list=([A-Za-z0-9_-]+)", target_url)
    if list_match and not target_url.startswith("https://www.youtube.com/playlist?list="):
        target_url = f"https://www.youtube.com/playlist?list={list_match.group(1)}"

    cmd = cmd_base + [
        target_url,
        "--flat-playlist",
        "-J",
        "--skip-download",
        "--no-warnings"
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            err = proc.stderr.strip() or "Failed to read playlist."
            return {
                "success": False,
                "error": err,
                "title": "",
                "items": []
            }

        data = json.loads(proc.stdout)
        playlist_title = data.get("title") or "YouTube Playlist"
        playlist_id = data.get("id") or (list_match.group(1) if list_match else "")
        entries = data.get("entries") or []

        items: List[Dict[str, Any]] = []
        for e in entries:
            if not e:
                continue
            vid = e.get("id")
            if not vid:
                continue
            title = sanitize_filename(e.get("title") or f"Track {vid}")
            uploader = e.get("uploader") or e.get("channel") or ""
            duration_sec = e.get("duration")
            duration_str = ""
            if duration_sec:
                m, s = divmod(int(duration_sec), 60)
                duration_str = f"{m}:{s:02d}"

            thumbs = e.get("thumbnails") or []
            thumb = thumbs[-1].get("url") if thumbs else f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

            items.append({
                "id": vid,
                "title": title,
                "uploader": uploader,
                "channel": uploader,
                "duration": duration_str,
                "duration_sec": int(duration_sec) if duration_sec else 0,
                "thumbnail": thumb,
                "url": f"https://www.youtube.com/watch?v={vid}"
            })

        return {
            "success": True,
            "id": playlist_id,
            "title": sanitize_filename(playlist_title),
            "count": len(items),
            "items": items
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Playlist extraction timed out (60s).", "title": "", "items": []}
    except Exception as e:
        return {"success": False, "error": str(e), "title": "", "items": []}
