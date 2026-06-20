#!/usr/bin/env python3
"""
Extract configured playlists from Spotify with resilient auth/session handling.
Uses running browser session if available, otherwise storage state fallback.
"""
import json
import os
import re
from playwright.sync_api import sync_playwright
from spotify_api import (
    api_error_suggests_premium_or_blocked,
    get_playlist_metadata_and_tracks,
    has_web_api_app_credentials,
)
from spotify_scrape import collect_playlist_tracks_with_network
from config import (
    COOKIES_FILE,
    DOWNLOAD_DIR,
    WORK_DIR,
    PLAYLISTS,
    SPOTIFY_EMAIL,
    SPOTIFY_PASSWORD,
    SPOTIFY_STORAGE_STATE,
)


def _read_secret_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def resolve_credentials():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_user = _read_secret_file(os.path.join(base_dir, ".user"))
    file_password = _read_secret_file(os.path.join(base_dir, ".password"))
    email = file_user or SPOTIFY_EMAIL
    password = file_password or SPOTIFY_PASSWORD
    return email, password

def save_cookies(context):
    """Save cookies to file for later use"""
    cookies = context.cookies()
    os.makedirs(os.path.dirname(COOKIES_FILE), exist_ok=True)
    with open(COOKIES_FILE, "w", encoding="utf-8") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for cookie in cookies:
            domain = cookie.get("domain", "")
            include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
            secure = "TRUE" if cookie.get("secure") else "FALSE"
            expires = cookie.get("expires")
            expiry = str(int(expires)) if expires and expires > 0 else "0"
            f.write(
                f"{domain}\t{include_subdomains}\t{cookie.get('path', '/')}\t"
                f"{secure}\t{expiry}\t{cookie.get('name', '')}\t{cookie.get('value', '')}\n"
            )
    print(f"Cookies saved to {COOKIES_FILE}")


def is_logged_in(page):
    try:
        page.goto("https://open.spotify.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        return "accounts.spotify.com" not in page.url
    except Exception:
        return False


def _fill_first_visible(page, selector, value, timeout=12000):
    field = page.locator(selector).first
    field.wait_for(state="visible", timeout=timeout)
    field.fill(value)


def try_auto_login(page, email, password):
    page.goto("https://accounts.spotify.com/en/login", wait_until="domcontentloaded")
    username_selector = (
        'input[type="email"], input[name="username"], input[id="login-username"], '
        'input[autocomplete="username"], input[placeholder*="mail" i], input[placeholder*="user" i]'
    )
    _fill_first_visible(page, username_selector, email)
    continue_button = page.get_by_role("button", name=re.compile(r"continue|next", re.I)).first
    try:
        if continue_button.is_visible(timeout=2000):
            continue_button.click(timeout=2000)
    except Exception:
        pass
    password_selector = 'input[type="password"], input[name="password"], input[id="login-password"]'
    _fill_first_visible(page, password_selector, password, timeout=20000)
    login_button = page.get_by_role("button", name=re.compile(r"log\s*in|sign\s*in", re.I)).first
    try:
        login_button.click(timeout=4000)
    except Exception:
        page.keyboard.press("Enter")
    page.wait_for_timeout(3000)


def ensure_authenticated(page, context):
    if is_logged_in(page):
        return True
    email, password = resolve_credentials()
    if not (email and password):
        return False
    try:
        try_auto_login(page, email, password)
    except Exception:
        return False
    ok = is_logged_in(page)
    if ok:
        context.storage_state(path=SPOTIFY_STORAGE_STATE)
    return ok


def get_playlist_tracks(page, url):
    """Extract tracks via captured XHR + DOM (virtualized lists)."""
    print(f"\nLoading playlist: {url}")
    tracks, n_net, n_dom = collect_playlist_tracks_with_network(page, url)
    print(f"  → {len(tracks)} tracks (network={n_net} DOM={n_dom})")
    return tracks

def main():
    print("Connecting to Spotify session...")

    with sync_playwright() as p:
        browser = None
        connected_via_cdp = False
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
            connected_via_cdp = True
            print("Connected to running browser session.")
        except Exception:
            if not os.path.exists(SPOTIFY_STORAGE_STATE):
                print("ERROR: No running browser and no saved session.")
                print("Run: python3 open_spotify.py")
                return
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(storage_state=SPOTIFY_STORAGE_STATE)
            page = context.new_page()
            print("Using saved Spotify session from storage state.")

        if not ensure_authenticated(page, context):
            print("ERROR: Session expired and auto-login failed.")
            print("Run: python3 open_spotify.py and complete login/captcha.")
            return

        save_cookies(context)

        for url, folder in PLAYLISTS:
            tracks = []
            used_api = False
            if has_web_api_app_credentials():
                try:
                    _api_name, tracks = get_playlist_metadata_and_tracks(url, auto_authorize=False)
                    used_api = bool(tracks)
                    if used_api:
                        print(f"{folder}: {len(tracks)} tracks found (API)")
                except Exception as e:
                    msg = str(e)
                    if api_error_suggests_premium_or_blocked(msg):
                        print(f"{folder}: Web API blocked (Premium/developer policy); using browser scrape.")
                    else:
                        print(f"{folder}: API error ({msg}); using browser scrape.")
            if not tracks:
                tracks = get_playlist_tracks(page, url)
                print(f"{folder}: {len(tracks)} tracks found (browser)")

            # Save track list
            track_file = os.path.join(WORK_DIR, f"{folder}_tracks.json")
            with open(track_file, "w", encoding="utf-8") as f:
                json.dump(tracks, f, indent=2)

        context.storage_state(path=SPOTIFY_STORAGE_STATE)
        save_cookies(context)

        if browser and not connected_via_cdp:
            try:
                browser.close()
            except Exception:
                pass
        print("\nDone! Track lists saved.")
        print("Next step: python3 download_tracks.py")

if __name__ == "__main__":
    main()
