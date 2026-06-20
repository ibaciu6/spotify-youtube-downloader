#!/usr/bin/env python3
"""Background daemon with progress display for downloading tracks."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

IS_TTY = sys.stdout.isatty()
DENO_DIR = os.path.expanduser("~/.deno/bin")
if os.path.isdir(DENO_DIR) and DENO_DIR not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{DENO_DIR}:{os.environ.get('PATH', '')}"

import storage
from storage import DOWNLOADS_DIR, reset_stuck_downloads

MAX_WORKERS = 10
AUDIO_QUALITY = "0"
YT_DLP_PATH = shutil.which("yt-dlp") or os.path.expanduser("~/bin/yt-dlp")
SILENCE_THRESHOLD_DB = -40
SILENCE_MIN_DURATION = 0.3
POLL_INTERVAL = 5
MAX_RETRIES = 3
DOWNLOAD_TIMEOUT = 600

class ProgressDisplay:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = True
        self.current_queue = None
        self.current_track = None
        self.stats = {"pending": 0, "downloading": 0, "completed": 0, "failed": 0}
    
    def update_stats(self):
        self.stats = storage.get_stats()
    
    def set_current(self, queue_name, track_query, done, total):
        with self.lock:
            self.current_queue = queue_name
            self.current_track = track_query
            self.done = done
            self.total = total
    
    def clear_current(self):
        with self.lock:
            self.current_queue = None
            self.current_track = None
    
    _last_log = ""

    def render(self):
        with self.lock:
            if IS_TTY:
                lines = []
                lines.append("\033[2J\033[H")
                lines.append("=" * 60)
                lines.append("  SPOTIFY/YOUTUBE DOWNLOADER DAEMON")
                lines.append("=" * 60)
                lines.append(f"  Pending: {self.stats['pending']}  Downloading: {self.stats['downloading']}  Completed: {self.stats['completed']}  Failed: {self.stats['failed']}")
                lines.append("-" * 60)
                if self.current_queue:
                    lines.append(f"  Queue: {self.current_queue}")
                    lines.append(f"  Progress: {self.done}/{self.total}")
                    if self.current_track:
                        lines.append(f"  Current: {self.current_track[:50]}")
                else:
                    lines.append("  Idle - waiting for new queues...")
                lines.append("-" * 60)
                lines.append("  Press Ctrl+C to stop")
                print("\n".join(lines))
            else:
                msg = f"Pending:{self.stats['pending']} DL:{self.stats['downloading']} Done:{self.stats['completed']} Fail:{self.stats['failed']}"
                if self.current_queue:
                    msg += f" | {self.current_queue} {self.done}/{self.total}"
                if msg != self._last_log:
                    print(msg, flush=True)
                    self._last_log = msg
    
    def run(self):
        while self.running:
            self.update_stats()
            self.render()
            time.sleep(1)

def trim_silence(input_file):
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

def build_search_queries(query):
    queries = [query]
    parts = [p.strip() for p in query.split("-", 1)]
    if len(parts) == 2 and parts[0] and parts[1]:
        queries.append(f"{parts[1]} {parts[0]} audio")
        queries.append(parts[1])
        queries.append(f"{parts[0]} {parts[1]}")
    stripped = re.sub(r'\s*-\s*\w+\s+\d{1,2},?\s*\d{4}', '', query)
    if stripped != query:
        queries.append(stripped)
    return queries

def download_track(query, output_dir):
    safe = re.sub(r'[\\/*?:"<>|]', "", query).strip()
    output_path = os.path.join(output_dir, f"{safe}.%(ext)s")
    search_queries = build_search_queries(query)
    
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

def process_queue(display, queue):
    queue_id = queue["id"]
    folder = queue["folder"]
    pending_tracks = storage.get_pending_tracks(queue_id, limit=MAX_WORKERS * 2)
    
    if not pending_tracks:
        storage.update_queue_status(queue_id)
        return
    
    download_folder = os.path.join(DOWNLOADS_DIR, folder)
    os.makedirs(download_folder, exist_ok=True)
    
    total = len(pending_tracks)
    done = 0
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        track_attempts = {}
        for track in pending_tracks:
            track_id = track["id"]
            query = track["query"]
            attempts = track.get("attempts", 0)
            track_attempts[track_id] = attempts
            storage.mark_downloading(track_id)
            fut = executor.submit(download_track, query, download_folder)
            futures[fut] = (track_id, query)
        
        for fut in as_completed(futures):
            track_id, query = futures[fut]
            ok, filename = fut.result()
            done += 1
            attempts = track_attempts.get(track_id, 0) + 1
            
            display.set_current(folder, query, done, total)
            
            if ok:
                file_path = os.path.join(download_folder, filename)
                storage.mark_completed(track_id, file_path)
            elif attempts >= MAX_RETRIES:
                storage.mark_failed(track_id, "Max retries exceeded", attempts)
            else:
                storage.mark_pending(track_id, attempts)
            
            display.clear_current()
    
    storage.update_queue_status(queue_id)

def main():
    storage.init_db()
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    
    display = ProgressDisplay()
    display_thread = threading.Thread(target=display.run, daemon=True)
    display_thread.start()
    
    print("Starting downloader daemon...")
    print(f"Database: {storage.DB_PATH}")
    print(f"Downloads: {DOWNLOADS_DIR}")
    print(f"Workers: {MAX_WORKERS}")
    print("Press Ctrl+C to stop")
    
    try:
        while True:
            reset_stuck_downloads()
            queues = storage.get_pending_queues()
            if queues:
                for q in queues:
                    process_queue(display, q)
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print("\nShutting down...")
        display.running = False
        display_thread.join(timeout=2)

if __name__ == "__main__":
    main()