#!/usr/bin/env python3
"""
Configuration for Spotify & YouTube Downloader.
"""

import os
import shutil

# Import credentials and playlists from separate file (keep that file private)
try:
    from credentials import SPOTIFY_EMAIL, SPOTIFY_PASSWORD, PLAYLISTS
except ImportError:
    SPOTIFY_EMAIL = ""
    SPOTIFY_PASSWORD = ""
    PLAYLISTS = []
    print("Warning: credentials.py not found. Copy credentials.example.py to credentials.py and fill it in.")

# ============== WORK DIR (non-music files live here, not in BASE_DIR) ==============
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.join(os.path.dirname(SCRIPT_DIR), "work")

# ============== STORAGE PATHS ==============
BASE_DIR = os.path.expanduser("~/local/mp3")
QUEUE_DIR = os.path.join(WORK_DIR, "queue")        # Module 1 writes here (new playlists/tracks to process)
STATUS_DIR = os.path.join(WORK_DIR, "status")      # Module 2 writes here (download status tracking)
COMPLETED_DIR = os.path.join(WORK_DIR, "completed") # Completed downloads (archive)
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads") # Actual MP3 files
DOWNLOAD_DIR = DOWNLOADS_DIR  # Alias for backward compatibility

# ============== DOWNLOAD SETTINGS ==============
MAX_WORKERS = 10
AUDIO_QUALITY = "0"
YT_DLP_PATH = shutil.which("yt-dlp") or os.path.expanduser("~/bin/yt-dlp")

# ============== SPOTIFY ==============
SPOTIFY_STORAGE_STATE = os.path.join(WORK_DIR, "spotify_storage_state.json")
COOKIES_FILE = os.path.join(WORK_DIR, "cookies.txt")
SPOTIFY_PROFILE_DIR = os.path.join(WORK_DIR, ".spotify_profile")
SPOTIFY_TOKEN_FILE = os.path.join(WORK_DIR, "spotify_token.json")
SPOTIFY_OAUTH_REDIRECT_URI = "http://127.0.0.1:8888/callback"
SPOTIFY_OAUTH_SCOPES = "playlist-read-private playlist-read-collaborative"

# ============== SILENCE TRIMMING ==============
SILENCE_THRESHOLD_DB = -40
SILENCE_MIN_DURATION = 0.3

# ============== DAEMON SETTINGS ==============
POLL_INTERVAL = 5
MAX_RETRIES = 3
DOWNLOAD_TIMEOUT = 600


def ensure_dirs():
    """Create necessary directories"""
    os.makedirs(WORK_DIR, exist_ok=True)
    for d in [QUEUE_DIR, STATUS_DIR, COMPLETED_DIR, DOWNLOADS_DIR]:
        os.makedirs(d, exist_ok=True)


if __name__ == "__main__":
    ensure_dirs()
    print(f"Base directory: {BASE_DIR}")
    print(f"Queue: {QUEUE_DIR}")
    print(f"Status: {STATUS_DIR}")
    print(f"Completed: {COMPLETED_DIR}")
    print(f"Downloads: {DOWNLOADS_DIR}")