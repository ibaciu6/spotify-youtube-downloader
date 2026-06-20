#!/usr/bin/env python3
"""
Module 1: Fetch Spotify playlists/tracks and add to SQLite queue.
Can be run anytime to add new URLs to the download queue.
"""
import os
import re
import sys

from playwright.sync_api import sync_playwright

import storage
from config import (
    SPOTIFY_STORAGE_STATE,
    SPOTIFY_EMAIL, SPOTIFY_PASSWORD
)
from fetch_playlist import (
    normalize_playlist_url,
    ensure_session_on_playlist, get_playlist_name_from_page,
    collect_playlist_tracks_with_network, PlaylistNetworkCollector,
    save_cookies, resolve_credentials
)
from download_single_track import normalize_track_url, get_track_info_from_title


def sanitize_folder_name(name):
    name = re.subn(r'[/\\:*?"<>|]', "_", name)[0]
    return name.strip(". ")[:200] or "Playlist"


def fetch_playlist_tracks(page, url):
    """Fetch all tracks from a playlist URL."""
    collector = PlaylistNetworkCollector()
    collector.attach(page)
    if not ensure_session_on_playlist(page, None, url):
        return None, "Session expired"
    tracks, _, _ = collect_playlist_tracks_with_network(
        page, url, collector=collector, skip_initial_goto=True
    )
    return tracks, None


def fetch_single_track(page, url):
    """Fetch single track info."""
    if not ensure_session_on_playlist(page, None, url):
        return None, "Session expired"
    page.wait_for_timeout(2000)
    title = page.title()
    track_name, artist = get_track_info_from_title(title)
    if not track_name:
        return None, "Could not parse track"
    query = f"{track_name} - {artist}" if artist else track_name
    return [query], None


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 module1_fetch.py <spotify_url> [--name FOLDER_NAME]")
        sys.exit(1)

    url = sys.argv[1]
    custom_name = None
    if "--name" in sys.argv:
        idx = sys.argv.index("--name")
        if idx + 1 < len(sys.argv):
            custom_name = sys.argv[idx + 1]

    is_playlist = "/playlist/" in url
    is_track = "/track/" in url

    if not (is_playlist or is_track):
        print("Must be a Spotify playlist or track URL")
        sys.exit(1)

    # Normalize URL
    if is_playlist:
        url = normalize_playlist_url(url)
    else:
        url = normalize_track_url(url)

    if not url:
        print("Invalid Spotify URL")
        sys.exit(1)

    storage.init_db()

    with sync_playwright() as p:
        browser = None
        context = None
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222", timeout=5000)
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
        except Exception:
            if not os.path.exists(SPOTIFY_STORAGE_STATE):
                print("No browser session. Run open_spotify.py first.")
                sys.exit(1)
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=SPOTIFY_STORAGE_STATE)
            page = context.new_page()

        try:
            if is_playlist:
                tracks, err = fetch_playlist_tracks(page, url)
                if err:
                    print(f"Error: {err}")
                    sys.exit(1)
                name = custom_name or get_playlist_name_from_page(page)
                folder = sanitize_folder_name(name)
            else:
                tracks, err = fetch_single_track(page, url)
                if err:
                    print(f"Error: {err}")
                    sys.exit(1)
                folder = custom_name or "singles"

            if not tracks:
                print("No tracks found")
                sys.exit(1)

            queue_id = storage.add_queue(folder, url, tracks)
            print(f"Added to queue: {queue_id} ({len(tracks)} tracks) -> {folder}")

        finally:
            if context:
                try:
                    context.storage_state(path=SPOTIFY_STORAGE_STATE)
                    save_cookies(context)
                except Exception:
                    pass
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass


if __name__ == "__main__":
    main()