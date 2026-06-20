#!/usr/bin/env python3
"""
Download a single Spotify track as MP3 via YouTube.
Usage: python3 download_single_track.py <track_url>
"""
import os
import re
import subprocess
import sys
import shutil
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright

from config import DOWNLOAD_DIR, YT_DLP_PATH, AUDIO_QUALITY, SPOTIFY_STORAGE_STATE
from fetch_playlist import ensure_session_on_playlist, save_cookies

SILENCE_THRESHOLD_DB = -40
SILENCE_MIN_DURATION = 0.3


def normalize_track_url(raw_text):
    text = raw_text.strip()
    match = re.search(r"https?://open\.spotify\.com/track/[A-Za-z0-9]+(?:\?[^\s]+)?", text)
    if not match:
        return ""
    candidate = match.group(0).rstrip(").,;!?]}>\"'")
    parsed = urlparse(candidate)
    if not parsed.path.startswith("/track/"):
        return ""
    track_id = parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else ""
    if not track_id:
        return ""
    params = parse_qs(parsed.query)
    si = params.get("si", [""])[0].strip()
    if si:
        return f"https://open.spotify.com/track/{track_id}?si={si}"
    return f"https://open.spotify.com/track/{track_id}"


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


def get_track_info_from_title(title):
    """Extract track name and artist from Spotify page title.

    Formats seen:
      Track Name - song and lyrics by Artist | Spotify
      Track Name - Single - Artist | Spotify  
      Track Name - Album - Artist | Spotify
      Track Name | Spotify
    """
    t = title
    for suffix in (" | Spotify", " – Spotify", " - Spotify"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
            break
    # Pattern: "Track - song and lyrics by Artist1, Artist2"
    m = re.match(r"^(.+?)\s*[-–]\s*song and lyrics by\s+(.+)$", t, re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # Pattern: "Track - Single - Artist" or "Track - Album - Artist"
    m = re.match(r"^(.+?)\s*[-–]\s+(?:Single|Album|EP)\s*[-–]\s+(.+)$", t, re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # Split everything on last " - "
    parts = t.split(" - ")
    if len(parts) == 1:
        return parts[0].strip(), ""
    return " - ".join(parts[:-1]).strip(), parts[-1].strip()


def download_track_as_mp3(query, output_dir):
    safe = re.sub(r'[\\/*?:"<>|]', "", query).strip()
    output_path = os.path.join(output_dir, f"{safe}.%(ext)s")
    os.makedirs(output_dir, exist_ok=True)

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
        f"ytsearch1:{query}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            mp3_files = [f for f in os.listdir(output_dir) if f.endswith(".mp3") and f.startswith(safe)]
            if mp3_files:
                mp3_path = os.path.join(output_dir, mp3_files[0])
                trim_silence(mp3_path)
            print(f"✓ Downloaded: {query}")
            return True
        print(f"✗ Failed: {query}")
        if result.stderr:
            print(result.stderr[-500:])
        return False
    except subprocess.TimeoutExpired:
        print(f"✗ Timeout: {query}")
        return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 download_single_track.py <track_url>", file=sys.stderr)
        sys.exit(1)

    url = normalize_track_url(sys.argv[1])
    if not url:
        print("Not a valid Spotify track URL.", file=sys.stderr)
        sys.exit(1)

    print("Connecting to browser...")
    with sync_playwright() as p:
        browser = None
        context = None
        connected_via_cdp = False
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222", timeout=5000)
            context = browser.contexts[0]
            context.set_default_navigation_timeout(120_000)
            page = context.pages[0] if context.pages else context.new_page()
            connected_via_cdp = True
            print("Connected to running browser session.")
        except Exception:
            if not os.path.exists(SPOTIFY_STORAGE_STATE):
                print("ERROR: No running browser and no saved Spotify session.", file=sys.stderr)
                print("Run menu option 1 once to log in and save session.", file=sys.stderr)
                sys.exit(1)
            headless = os.environ.get("SPOTIFY_HEADLESS", "1").lower() not in ("0", "false", "no")
            browser = p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled", "--window-size=1280,720"],
            )
            context = browser.new_context(
                storage_state=SPOTIFY_STORAGE_STATE,
                viewport={"width": 1280, "height": 720},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            context.set_default_navigation_timeout(120_000)
            page = context.new_page()
            print("Using saved Spotify session from storage state.")

        print(f"Loading track: {url}", flush=True)
        if not ensure_session_on_playlist(page, context, url):
            print("Session expired and auto-login failed.", file=sys.stderr)
            sys.exit(1)

        page.wait_for_timeout(2000)
        title = page.title()
        track_name, artist = get_track_info_from_title(title)

        if not track_name:
            print(f"Could not parse track info from page title: {title!r}", file=sys.stderr)
            sys.exit(1)

        query = f"{track_name} - {artist}" if artist else track_name
        print(f"Track: {track_name}")
        print(f"Artist: {artist}")

        singles_dir = os.path.join(DOWNLOAD_DIR, "singles")
        os.makedirs(singles_dir, exist_ok=True)

        # Save state before download (browser may disconnect during long yt-dlp)
        try:
            context.storage_state(path=SPOTIFY_STORAGE_STATE)
            save_cookies(context)
        except Exception:
            pass

        if download_track_as_mp3(query, singles_dir):
            print(f"\nSaved: {singles_dir}/")
        else:
            sys.exit(1)

        if browser and not connected_via_cdp:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
