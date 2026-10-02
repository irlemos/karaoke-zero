#!/usr/bin/env python3
"""
KaraokeZero Video Deduplication Tool - Command Line Interface
Interactive text-mode utility for identifying and removing duplicate video/audio files,
even if they have different filenames.
"""

import argparse
import os
import shutil
import sys
import time
from typing import List, Optional

# Ensure local imports work
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from dedup_engine import (
    DuplicateGroup,
    MatchStrategy,
    MediaFile,
    VideoDeduplicator
)

# ANSI Color Codes for terminal
CLR_CYAN = "\033[96m"
CLR_GREEN = "\033[92m"
CLR_YELLOW = "\033[93m"
CLR_RED = "\033[91m"
CLR_MAGENTA = "\033[95m"
CLR_BOLD = "\033[1m"
CLR_DIM = "\033[2m"
CLR_RESET = "\033[0m"


def auto_detect_karaoke_directory() -> str:
    """Detects available KaraokeZero songs directory or external drive."""
    # 1. Primary target on Raspberry Pi
    if os.path.isdir("/mnt/external_hd/karaoke/songs"):
        return "/mnt/external_hd/karaoke/songs"

    user_home = os.path.expanduser("~")
    username = os.environ.get("USER", os.path.basename(user_home))

    # 2. Check mounted USB media drives
    search_roots = [
        f"/media/{username}",
        f"/run/media/{username}",
        "/media",
        "/mnt"
    ]
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        try:
            for entry in os.listdir(root):
                full_path = os.path.join(root, entry)
                if not os.path.isdir(full_path):
                    continue
                # Check songs subfolder
                for candidate in [
                    os.path.join(full_path, "songs"),
                    os.path.join(full_path, "karaoke", "songs"),
                    full_path
                ]:
                    if os.path.isdir(candidate):
                        # Verify it has any video files
                        for f in os.listdir(candidate):
                            if f.lower().endswith((".mp4", ".mkv", ".webm")):
                                return candidate
        except Exception:
            pass

    # 3. Check standard local Music folders
    music_kz = os.path.join(user_home, "Music", "KaraokeZero")
    if os.path.isdir(music_kz):
        return music_kz

    downloads_kz = os.path.join(user_home, "Downloads", "KaraokeZero")
    if os.path.isdir(downloads_kz):
        return downloads_kz

    # 4. Fallback to current working directory
    return os.getcwd()


def render_progress(current: int, total: int, filename: str):
    """Draws a clean terminal progress bar."""
    bar_width = 30
    pct = (current / total) if total > 0 else 0
    filled = int(round(bar_width * pct))
    bar = "=" * filled + "-" * (bar_width - filled)
    short_fn = filename[:28] + "..." if len(filename) > 31 else filename.ljust(31)
    sys.stdout.write(f"\r  {CLR_CYAN}[{bar}] {int(pct*100):3d}%{CLR_RESET} ({current}/{total}) {CLR_DIM}{short_fn}{CLR_RESET}")
    sys.stdout.flush()


def print_banner():
    print(f"{CLR_BOLD}{CLR_MAGENTA}========================================================================={CLR_RESET}")
    print(f"{CLR_BOLD}{CLR_CYAN}         🎤 KaraokeZero Video Deduplication & Cleaner Utility 🎤         {CLR_RESET}")
    print(f"{CLR_BOLD}{CLR_MAGENTA}========================================================================={CLR_RESET}")
    print(f"{CLR_DIM}Identifies duplicates by content hash, YouTube ID, audio fingerprint & duration{CLR_RESET}")
    print("")


def print_group_details(group: DuplicateGroup, group_idx: int, total_groups: int):
    all_files = group.all_files()
    wasted_mb = round(group.wasted_bytes / (1024 * 1024), 2)

    print(f"\n{CLR_BOLD}{CLR_YELLOW}-------------------------------------------------------------------------{CLR_RESET}")
    print(f"{CLR_BOLD}Duplicate Group [{group_idx}/{total_groups}] {CLR_RESET}| {CLR_CYAN}Matched by: {group.matched_by}{CLR_RESET}")
    print(f"{CLR_DIM}Wasted Space: {wasted_mb} MB across {len(group.duplicates)} redundant file(s){CLR_RESET}")
    print(f"{CLR_BOLD}{CLR_YELLOW}-------------------------------------------------------------------------{CLR_RESET}")

    for idx, f in enumerate(all_files, start=1):
        is_keeper = (f.path == group.keeper.path)
        tag = f"{CLR_GREEN}★ [RECOMMENDED KEEPER]{CLR_RESET}" if is_keeper else f"{CLR_RED}✖ [DUPLICATE]{CLR_RESET}"
        res_info = f"{CLR_BOLD}{f.resolution_str}{CLR_RESET}" if f.resolution_str != "Unknown Res" else "Unknown Res"
        codec_info = f"{f.vcodec or '?'}/{f.acodec or '?'}"
        
        print(f"  {CLR_BOLD}[{idx}]{CLR_RESET} {tag}")
        print(f"      {CLR_BOLD}File:{CLR_RESET}     {f.filename}")
        print(f"      {CLR_DIM}Details:{CLR_RESET}  {f.size_mb} MB | {f.duration_str} | {res_info} ({codec_info})")
        print(f"      {CLR_DIM}Path:{CLR_RESET}     {f.path}")


def interactive_mode(
    groups: List[DuplicateGroup],
    deduplicator: VideoDeduplicator,
    move_to_trash: bool
) -> int:
    """Interactively prompts user for each duplicate group."""
    total_reclaimed = 0
    auto_keep_all = False

    for idx, group in enumerate(groups, start=1):
        all_files = group.all_files()
        print_group_details(group, idx, len(groups))

        if auto_keep_all:
            print(f"  {CLR_GREEN}Auto-keeping recommended file [{1}] and removing duplicates...{CLR_RESET}")
            for d in group.duplicates:
                if deduplicator.delete_file(d.path, move_to_trash=move_to_trash):
                    total_reclaimed += d.size
            continue

        while True:
            try:
                prompt = (
                    f"\n  Choose which file to {CLR_BOLD}KEEP{CLR_RESET} "
                    f"[{CLR_GREEN}1{CLR_RESET}-{len(all_files)}] (default 1), "
                    f"[{CLR_CYAN}A{CLR_RESET}]uto-keep best for all, "
                    f"[{CLR_YELLOW}S{CLR_RESET}]kip, "
                    f"[{CLR_RED}Q{CLR_RESET}]uit: "
                )
                choice = input(prompt).strip().lower()

                if choice in ("", "1"):
                    # Keep default recommended keeper [1]
                    keeper = all_files[0]
                    to_delete = all_files[1:]
                    for d in to_delete:
                        if deduplicator.delete_file(d.path, move_to_trash=move_to_trash):
                            total_reclaimed += d.size
                    print(f"  {CLR_GREEN}✓ Kept '{keeper.filename}' and removed {len(to_delete)} duplicate(s).{CLR_RESET}")
                    break

                elif choice.isdigit() and 1 <= int(choice) <= len(all_files):
                    chosen_idx = int(choice) - 1
                    keeper = all_files[chosen_idx]
                    to_delete = [f for i, f in enumerate(all_files) if i != chosen_idx]
                    for d in to_delete:
                        if deduplicator.delete_file(d.path, move_to_trash=move_to_trash):
                            total_reclaimed += d.size
                    print(f"  {CLR_GREEN}✓ Kept '{keeper.filename}' and removed {len(to_delete)} duplicate(s).{CLR_RESET}")
                    break

                elif choice == "a":
                    auto_keep_all = True
                    for d in group.duplicates:
                        if deduplicator.delete_file(d.path, move_to_trash=move_to_trash):
                            total_reclaimed += d.size
                    print(f"  {CLR_GREEN}✓ Kept recommended file. Auto-cleaning remaining groups...{CLR_RESET}")
                    break

                elif choice == "s":
                    print(f"  {CLR_YELLOW}Skipped group. No files modified.{CLR_RESET}")
                    break

                elif choice == "q":
                    print(f"\n{CLR_YELLOW}Deduplication cancelled by user.{CLR_RESET}")
                    return total_reclaimed

                else:
                    print(f"  {CLR_RED}Invalid choice. Please select 1-{len(all_files)}, A, S, or Q.{CLR_RESET}")

            except (KeyboardInterrupt, EOFError):
                print(f"\n\n{CLR_YELLOW}Deduplication interrupted.{CLR_RESET}")
                return total_reclaimed

    return total_reclaimed


def auto_clean_mode(
    groups: List[DuplicateGroup],
    deduplicator: VideoDeduplicator,
    move_to_trash: bool
) -> int:
    """Automatically keeps best files and deletes duplicates without prompts."""
    total_reclaimed = 0
    print(f"{CLR_BOLD}Auto-cleaning {len(groups)} duplicate group(s)...{CLR_RESET}")

    for idx, group in enumerate(groups, start=1):
        print(f"  [{idx}/{len(groups)}] Keeping: {CLR_GREEN}{group.keeper.filename}{CLR_RESET}")
        for d in group.duplicates:
            print(f"      Removing duplicate: {CLR_RED}{d.filename}{CLR_RESET} ({d.size_mb} MB)")
            if deduplicator.delete_file(d.path, move_to_trash=move_to_trash):
                total_reclaimed += d.size

    return total_reclaimed


def main():
    parser = argparse.ArgumentParser(
        description="KaraokeZero Video Deduplication & Duplicate Cleaner Tool"
    )
    parser.add_argument(
        "--dir", "-d",
        type=str,
        default=None,
        help="Target folder containing video files (defaults to detected KaraokeZero storage)"
    )
    parser.add_argument(
        "--scan", "--dry-run", "-s",
        action="store_true",
        help="Scan and report duplicate files without deleting anything"
    )
    parser.add_argument(
        "--auto", "-a",
        action="store_true",
        help="Automatically keep the best copy and remove duplicates without interactive prompt"
    )
    parser.add_argument(
        "--trash", "-t",
        action="store_true",
        help="Move duplicates to a .trash folder instead of permanently deleting them"
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        help="Skip deep audio stream fingerprinting (faster scan)"
    )
    parser.add_argument(
        "--strategy",
        choices=["all", "exact_hash", "youtube_id", "audio_stream", "duration_title"],
        default="all",
        help="Matching strategy (default: all)"
    )
    args = parser.parse_args()

    print_banner()

    target_dir = args.dir or auto_detect_karaoke_directory()
    target_dir = os.path.abspath(os.path.expanduser(target_dir))

    if not os.path.isdir(target_dir):
        print(f"{CLR_RED}Error: Directory '{target_dir}' does not exist.{CLR_RESET}")
        sys.exit(1)

    print(f"  • Target Directory:  {CLR_BOLD}{target_dir}{CLR_RESET}")
    print(f"  • Strategy:          {CLR_CYAN}{args.strategy.upper()}{CLR_RESET}")
    print(f"  • Audio Fingerprint: {CLR_GREEN if not args.no_audio else CLR_YELLOW}{'Enabled' if not args.no_audio else 'Disabled'}{CLR_RESET}")
    print(f"  • Mode:              {CLR_MAGENTA}{'Dry-Run Scan Only' if args.scan else ('Auto Clean' if args.auto else 'Interactive')}{CLR_RESET}")
    print(f"  • Deletion Method:   {CLR_YELLOW if args.trash else CLR_RED}{'Move to .trash' if args.trash else 'Permanent Delete'}{CLR_RESET}")
    print("")

    deduplicator = VideoDeduplicator()
    strat_enum = MatchStrategy(args.strategy)

    print(f"{CLR_BOLD}Analyzing media files...{CLR_RESET}")
    start_time = time.time()

    groups = deduplicator.scan_directory(
        directory=target_dir,
        strategy=strat_enum,
        deep_audio=not args.no_audio,
        progress_cb=render_progress
    )
    print("\n")

    elapsed = round(time.time() - start_time, 1)

    if not groups:
        print(f"{CLR_GREEN}✓ No duplicate video files found in '{target_dir}'! (Scanned in {elapsed}s){CLR_RESET}\n")
        return

    total_wasted = sum(g.wasted_bytes for g in groups)
    total_wasted_mb = round(total_wasted / (1024 * 1024), 2)
    total_dups = sum(len(g.duplicates) for g in groups)

    print(f"{CLR_BOLD}{CLR_YELLOW}Found {len(groups)} duplicate group(s) ({total_dups} redundant files, {total_wasted_mb} MB wasted){CLR_RESET}")

    if args.scan:
        # Dry-run report only
        for idx, group in enumerate(groups, start=1):
            print_group_details(group, idx, len(groups))
        print(f"\n{CLR_CYAN}Dry-run complete. Run without --scan or with --auto to clean duplicates.{CLR_RESET}\n")
        return

    # Deletion execution
    if args.auto:
        reclaimed = auto_clean_mode(groups, deduplicator, move_to_trash=args.trash)
    else:
        reclaimed = interactive_mode(groups, deduplicator, move_to_trash=args.trash)

    reclaimed_mb = round(reclaimed / (1024 * 1024), 2)
    action_word = "Moved to .trash" if args.trash else "Cleaned"
    print(f"\n{CLR_BOLD}{CLR_GREEN}✓ Done! {action_word} {reclaimed_mb} MB of duplicate video files.{CLR_RESET}\n")


if __name__ == "__main__":
    main()
