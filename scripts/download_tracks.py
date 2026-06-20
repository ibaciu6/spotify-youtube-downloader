#!/usr/bin/env python3
"""
Download tracks from YouTube using yt-dlp.
Run with no args to download all playlists that have *_tracks.json,
or pass folder names: python3 download_tracks.py "Folder1" "Folder2"
"""
import json
import re
import subprocess
import os
import sys
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import DOWNLOAD_DIR, WORK_DIR, YT_DLP_PATH, AUDIO_QUALITY, MAX_WORKERS

MAX_RETRIES = 3
TIMEOUT_SEC = 600

SILENCE_THRESHOLD_DB = -40
SILENCE_MIN_DURATION = 0.3


def download_track(args):
    """Download a track from YouTube. Returns (bool, query)."""
    query, output_dir, i, total = args
    safe = re.sub(r'[\\/*?:"<>|]', "", query).strip()
    output_path = os.path.join(output_dir, f"{safe}.%(ext)s")
    search_queries = [query, reformat_query(query)]
    for attempt in range(1, MAX_RETRIES + 2):
        for search_query in search_queries:
            cmd = [
                YT_DLP_PATH,
                "-x", "--audio-format", "mp3",
                "--audio-quality", AUDIO_QUALITY,
                "--no-playlist",
                "--no-overwrites",
                "--no-keep-video",
                "--rm-cache-dir",
                "--default-search", "ytsearch",
                "-o", output_path,
                f"ytsearch1:{search_query}"
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_SEC)
                # Clean any leftover intermediate files yt-dlp didn't remove
                for fname in os.listdir(output_dir):
                    if not fname.endswith(".mp3"):
                        try:
                            os.remove(os.path.join(output_dir, fname))
                        except Exception:
                            pass
                if result.returncode == 0:
                    mp3_files = [f for f in os.listdir(output_dir) if f.endswith(".mp3") and f.startswith(safe)]
                    if mp3_files:
                        mp3_path = os.path.join(output_dir, mp3_files[0])
                        trim_silence(mp3_path)
                    print(f"[{i}/{total}] ✓ {query}")
                    return True, query
            except Exception:
                pass
        if attempt <= MAX_RETRIES:
            print(f"[{i}/{total}] … retry {attempt}/{MAX_RETRIES} {query}")
    print(f"[{i}/{total}] ✗ {query}")
    return False, query


def reformat_query(query):
    """Fallback query style: 'artist - title' -> 'title artist audio'."""
    parts = [p.strip() for p in query.split("-", 1)]
    if len(parts) == 2 and parts[0] and parts[1]:
        return f"{parts[1]} {parts[0]} audio"
    return f"{query} audio"


def trim_silence(input_file, output_file=None):
    """Remove silence from start/end of MP3 using ffmpeg silenceremove."""
    if output_file is None:
        output_file = input_file
    tmp_file = output_file + ".tmp.mp3"
    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-af", f"silenceremove=start_periods=1:start_threshold={SILENCE_THRESHOLD_DB}dB:start_duration={SILENCE_MIN_DURATION}:stop_periods=-1:stop_threshold={SILENCE_THRESHOLD_DB}dB:stop_duration={SILENCE_MIN_DURATION}",
        "-c:a", "libmp3lame", "-q:a", "2",
        tmp_file
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120)
        if os.path.exists(tmp_file):
            shutil.move(tmp_file, output_file)
            return True
    except Exception:
        pass
    if os.path.exists(tmp_file):
        try:
            os.remove(tmp_file)
        except Exception:
            pass
    return False


def _clean_folder(folder_path):
    """Remove non-MP3 / temp files from folder."""
    if not os.path.isdir(folder_path):
        return
    for name in os.listdir(folder_path):
        fpath = os.path.join(folder_path, name)
        if not os.path.isfile(fpath):
            continue
        if name.endswith(".mp3"):
            continue
        try:
            os.remove(fpath)
        except Exception:
            pass


def _run_playlist(folder, interactive=True):
    """Download one playlist by folder name. Returns True if any tracks were processed."""
    track_file = os.path.join(WORK_DIR, f"{folder}_tracks.json")
    folder_path = os.path.join(DOWNLOAD_DIR, folder)
    try:
        with open(track_file, "r") as f:
            tracks = json.load(f)
    except Exception:
        print(f"Could not load {track_file}")
        return False

    os.makedirs(folder_path, exist_ok=True)
    # Clean leftover temp files from previous runs
    _clean_folder(folder_path)
    print(f"\n=== {folder}: {len(tracks)} tracks (parallel: {MAX_WORKERS} workers) ===")
    tasks = [(track, folder_path, i + 1, len(tracks)) for i, track in enumerate(tracks)]
    success_count = 0
    failed = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(download_track, task) for task in tasks]
        for future in as_completed(futures):
            ok, query = future.result()
            if ok:
                success_count += 1
            else:
                failed.append(query)
    print(f"\n{folder} complete: {success_count}/{len(tracks)} downloaded")
    _clean_folder(folder_path)

    if failed and interactive and sys.stdin.isatty():
        print(f"\n{folder}: {len(failed)} track(s) failed")
        try:
            resp = input("Retry failed tracks sequentially? [y/N] ").strip().lower()
            if resp == "y":
                n2 = 0
                print(f"\n=== Retrying {len(failed)} failed track(s) ===")
                for idx, q in enumerate(failed, 1):
                    ok, _ = download_track((q, folder_path, idx, len(failed)))
                    if ok:
                        n2 += 1
                print(f"Retry saved: {n2}/{len(failed)}")
                success_count += n2
                _clean_folder(folder_path)
        except (EOFError, OSError):
            pass

    print(f"\n{folder} final: {success_count}/{len(tracks)} downloaded")
    return True


def download_one_playlist(folder):
    """Download a single playlist by folder name (used by fetch_playlist.py)."""
    _run_playlist(folder, interactive=False)


def main():
    if len(sys.argv) > 1:
        folders = sys.argv[1:]
    else:
        os.makedirs(WORK_DIR, exist_ok=True)
        folders = []
        for name in os.listdir(WORK_DIR):
            if name.endswith("_tracks.json"):
                folders.append(name[:-len("_tracks.json")])
        if not folders:
            print("No *_tracks.json found in", WORK_DIR)
            print("Use menu option 2 to enter a playlist URL first.")
            return

    for folder in folders:
        _run_playlist(folder)


if __name__ == "__main__":
    main()
