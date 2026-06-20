#!/usr/bin/env python3
"""
Module 2: Background daemon that monitors queue and downloads tracks.
Moves tracks from queue -> status (downloading) -> completed, removing from queue on success.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from config import (
    QUEUE_DIR, STATUS_DIR, COMPLETED_DIR, DOWNLOADS_DIR,
    YT_DLP_PATH, AUDIO_QUALITY, MAX_WORKERS,
    SILENCE_THRESHOLD_DB, SILENCE_MIN_DURATION,
    POLL_INTERVAL, MAX_RETRIES, DOWNLOAD_TIMEOUT
)


def trim_silence(input_file):
    """Remove silence from start/end of MP3 using ffmpeg silenceremove."""
    tmp_file = input_file + ".tmp.mp3"
    cmd = [
        "ffmpeg", "-y", "-i", input_file,
        "-af", f"silenceremove=start_periods=1:start_threshold={SILENCE_THRESHOLD_DB}dB:start_duration={SILENCE_MIN_DURATION}:stop_periods=-1:stop_threshold={SILENCE_THRESHOLD_DB}dB:stop_duration={SILENCE_MIN_DURATION}",
        "-c:a", "libmp3lame", "-q:a", "2",
        tmp_file
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120)
        if os.path.exists(tmp_file):
            shutil.move(tmp_file, input_file)
            return True
    except Exception:
        pass
    if os.path.exists(tmp_file):
        try:
            os.remove(tmp_file)
        except Exception:
            pass
    return False


def download_track(query, output_dir):
    """Download a single track from YouTube as MP3."""
    safe = re.sub(r'[\\/*?:"<>|]', "", query).strip()
    output_path = os.path.join(output_dir, f"{safe}.%(ext)s")

    search_queries = [query, reformat_query(query)]
    for attempt in range(1, MAX_RETRIES + 1):
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
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT)
                if result.returncode == 0:
                    mp3_files = [f for f in os.listdir(output_dir)
                                 if f.endswith(".mp3") and f.startswith(safe)]
                    if mp3_files:
                        mp3_path = os.path.join(output_dir, mp3_files[0])
                        trim_silence(mp3_path)
                        return True, mp3_files[0]
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass
    return False, None


def reformat_query(query):
    parts = [p.strip() for p in query.split("-", 1)]
    if len(parts) == 2 and parts[0] and parts[1]:
        return f"{parts[1]} {parts[0]} audio"
    return f"{query} audio"


def load_json(path):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return None


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    shutil.move(tmp, path)


def process_queue_file(queue_file):
    """Process a single queue file: download all pending tracks."""
    data = load_json(queue_file)
    if not data:
        return

    folder = data["folder"]
    tracks = data["tracks"]

    # Load or create status file
    status_file = os.path.join(STATUS_DIR, f"{folder}.json")
    status = load_json(status_file) or {
        "folder": folder,
        "tracks": {}
    }

    # Ensure download folder exists
    download_folder = os.path.join(DOWNLOADS_DIR, folder)
    os.makedirs(download_folder, exist_ok=True)

    # Find pending tracks
    pending = []
    for i, t in enumerate(tracks):
        query = t["query"]
        key = f"{i}:{query}"
        if key not in status["tracks"] or status["tracks"][key].get("status") != "completed":
            pending.append((i, query, key))

    if not pending:
        # All done - move queue to completed
        completed_file = os.path.join(COMPLETED_DIR, os.path.basename(queue_file))
        shutil.move(queue_file, completed_file)
        print(f"[{folder}] All tracks completed. Moved to completed.")
        return

    print(f"[{folder}] Processing {len(pending)}/{len(tracks)} pending tracks...")

    # Download pending tracks in parallel
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for i, query, key in pending:
            status["tracks"][key] = {"status": "downloading", "query": query, "attempt": 0}
            save_json(status_file, status)
            fut = executor.submit(download_track, query, download_folder)
            futures[fut] = (i, query, key)

        for fut in as_completed(futures):
            i, query, key = futures[fut]
            ok, filename = fut.result()
            if ok:
                status["tracks"][key] = {
                    "status": "completed",
                    "query": query,
                    "file": filename,
                    "completed_at": time.time()
                }
                print(f"[{folder}] ✓ {query}")
            else:
                # Increment attempt, will retry next poll
                current = status["tracks"].get(key, {})
                attempts = current.get("attempt", 0) + 1
                if attempts >= MAX_RETRIES:
                    status["tracks"][key] = {
                        "status": "failed",
                        "query": query,
                        "attempts": attempts,
                        "error": "Max retries exceeded"
                    }
                    print(f"[{folder}] ✗ {query} (failed after {attempts} attempts)")
                else:
                    status["tracks"][key] = {
                        "status": "pending",
                        "query": query,
                        "attempt": attempts
                    }
                    print(f"[{folder}] … {query} (retry {attempts}/{MAX_RETRIES})")
            save_json(status_file, status)

    # Check if all tracks are completed
    all_done = all(
        t.get("status") == "completed"
        for t in status["tracks"].values()
    )

    if all_done:
        # Move queue file to completed
        completed_file = os.path.join(COMPLETED_DIR, os.path.basename(queue_file))
        shutil.move(queue_file, completed_file)
        print(f"[{folder}] All done. Queue moved to completed.")


def main():
    print("Starting downloader daemon...")
    print(f"Queue: {QUEUE_DIR}")
    print(f"Status: {STATUS_DIR}")
    print(f"Completed: {COMPLETED_DIR}")
    print(f"Downloads: {DOWNLOADS_DIR}")
    print(f"Poll interval: {POLL_INTERVAL}s")
    print(f"Max workers: {MAX_WORKERS}")

    while True:
        try:
            # Find all queue files
            queue_files = sorted(Path(QUEUE_DIR).glob("*.json"))
            if queue_files:
                for qf in queue_files:
                    process_queue_file(str(qf))
            else:
                print(".", end="", flush=True)

        except KeyboardInterrupt:
            print("\nShutting down...")
            break
        except Exception as e:
            print(f"\nError: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()