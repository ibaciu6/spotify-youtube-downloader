#!/usr/bin/env python3
"""
Fetch one playlist by URL from an existing Spotify browser session.
Gets playlist name from the page and uses it as the folder name.
Usage: python3 fetch_playlist.py <playlist_url> [--download]
  --download: run download_tracks for this playlist after fetching.
"""
import json
import os
import re
import sys
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright

from config import COOKIES_FILE, DOWNLOAD_DIR, WORK_DIR, SPOTIFY_EMAIL, SPOTIFY_PASSWORD, SPOTIFY_STORAGE_STATE
from spotify_api import api_error_suggests_premium_or_blocked, get_playlist_metadata_and_tracks, has_web_api_app_credentials
from spotify_network import PlaylistNetworkCollector
from spotify_scrape import collect_playlist_tracks_with_network


def sanitize_folder_name(name):
    """Make a string safe for use as a folder name."""
    name = re.subn(r'[/\\:*?"<>|]', "_", name)[0]
    name = name.strip(". ") or "Playlist"
    return name[:200]


def normalize_playlist_url(raw_text):
    """
    Extract and normalize a Spotify playlist URL from arbitrary pasted text.
    Keeps only the playlist path and optional `si` query param.
    """
    text = raw_text.strip()
    match = re.search(r"https?://open\.spotify\.com/playlist/[A-Za-z0-9]+(?:\?[^\s]+)?", text)
    if not match:
        return ""
    candidate = match.group(0).rstrip(").,;!?]}>\"'")
    parsed = urlparse(candidate)
    if not parsed.path.startswith("/playlist/"):
        return ""
    playlist_id = parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else ""
    if not playlist_id:
        return ""
    params = parse_qs(parsed.query)
    si = params.get("si", [""])[0].strip()
    if si:
        return f"https://open.spotify.com/playlist/{playlist_id}?si={si}"
    return f"https://open.spotify.com/playlist/{playlist_id}"


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


def is_logged_in(page):
    try:
        page.goto(
            "https://open.spotify.com/",
            wait_until="domcontentloaded",
            timeout=90_000,
        )
        page.wait_for_timeout(1200)
        return "accounts.spotify.com" not in page.url
    except Exception:
        return False


def _fill_first_visible(page, selector, value, timeout=12000):
    field = page.locator(selector).first
    field.wait_for(state="visible", timeout=timeout)
    field.fill(value)


def try_auto_login(page, email, password):
    page.goto(
        "https://accounts.spotify.com/en/login",
        wait_until="domcontentloaded",
        timeout=90_000,
    )
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


def ensure_session_on_playlist(page, context, playlist_url: str) -> bool:
    """
    Open the playlist directly (fast path). If redirected to login, run auto-login
    and return to the playlist. Avoids an extra full open.spotify.com round-trip.
    """
    page.goto(playlist_url, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(2000)
    if "accounts.spotify.com" not in page.url:
        return True
    email, password = resolve_credentials()
    if not (email and password):
        return False
    try:
        try_auto_login(page, email, password)
    except Exception:
        return False
    page.goto(playlist_url, wait_until="domcontentloaded", timeout=120_000)
    page.wait_for_timeout(2000)
    if "accounts.spotify.com" in page.url:
        return False
    context.storage_state(path=SPOTIFY_STORAGE_STATE)
    return True


def get_playlist_name_from_page(page):
    """Extract playlist name from current page (title or heading)."""
    try:
        title = page.title()
        if title:
            for suffix in (" - Spotify", " | Spotify", " – Spotify"):
                if title.endswith(suffix):
                    return title[:-len(suffix)].strip()
            return title.strip()
    except Exception:
        pass
    try:
        el = page.query_selector('[data-testid="entity-title"], h1, .playlist-name')
        if el:
            return el.inner_text().strip()
    except Exception:
        pass
    return "Playlist"


def save_cookies(context):
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


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 fetch_playlist.py <playlist_url> [--download]", file=sys.stderr)
        sys.exit(1)

    url = normalize_playlist_url(sys.argv[1])
    do_download = "--download" in sys.argv

    if not url:
        print("Not a valid Spotify playlist URL.", file=sys.stderr)
        sys.exit(1)

    # API-first only when developer app credentials exist (requires OAuth token).
    # Spotify may block Web API for Free-tier developer accounts — then we scrape.
    if has_web_api_app_credentials():
        try:
            api_name, api_tracks = get_playlist_metadata_and_tracks(url, auto_authorize=False)
            if api_tracks:
                folder = sanitize_folder_name(api_name)
                os.makedirs(DOWNLOAD_DIR, exist_ok=True)
                folder_path = os.path.join(DOWNLOAD_DIR, folder)
                os.makedirs(folder_path, exist_ok=True)
                track_file = os.path.join(WORK_DIR, f"{folder}_tracks.json")
                with open(track_file, "w", encoding="utf-8") as f:
                    json.dump(api_tracks, f, indent=2)
                print(f"Saved (API): {folder} ({len(api_tracks)} tracks)")
                print(f"Folder: {folder_path}")
                if do_download:
                    import download_tracks
                    download_tracks.download_one_playlist(folder)
                return
        except Exception as e:
            msg = str(e)
            if api_error_suggests_premium_or_blocked(msg):
                print(
                    "Spotify Web API blocked or requires Premium-linked developer access. "
                    "Using browser playlist scrape.",
                    file=sys.stderr,
                )
            elif "not configured" in msg.lower():
                pass
            elif "No Spotify token" in msg or "token available" in msg.lower():
                print(
                    "Spotify API: no token yet. Run menu option 4 (OAuth) or rely on browser scrape.",
                    file=sys.stderr,
                )
            else:
                print(f"API fetch failed, using browser scrape: {msg}", file=sys.stderr)

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
                print(
                    "ERROR: No running browser and no saved Spotify session.",
                    file=sys.stderr,
                )
                print(
                    "Run menu option 1 once to log in and save session.",
                    file=sys.stderr,
                )
                sys.exit(1)
            headless = os.environ.get("SPOTIFY_HEADLESS", "1").lower() not in ("0", "false", "no")
            browser = p.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--window-size=1920,1080",
                ],
            )
            context = browser.new_context(
                storage_state=SPOTIFY_STORAGE_STATE,
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            context.set_default_navigation_timeout(120_000)
            page = context.new_page()
            print("Using saved Spotify session from storage state.")

        print(f"Loading playlist: {url}", flush=True)
        collector = PlaylistNetworkCollector()
        collector.attach(page)
        if not ensure_session_on_playlist(page, context, url):
            print(
                "Session expired and auto-login failed. Run menu option 1 to complete login/captcha.",
                file=sys.stderr,
            )
            sys.exit(1)

        tracks, n_net, n_dom = collect_playlist_tracks_with_network(
            page, url, collector=collector, skip_initial_goto=True
        )
        if n_net or n_dom:
            print(f"Track sources: network={n_net} DOM={n_dom} merged={len(tracks)}")

        name = get_playlist_name_from_page(page)
        folder = sanitize_folder_name(name)

        if not tracks:
            print("No tracks found. Make sure you're logged in and the playlist is visible.", file=sys.stderr)
            sys.exit(1)

        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        folder_path = os.path.join(DOWNLOAD_DIR, folder)
        os.makedirs(folder_path, exist_ok=True)
        track_file = os.path.join(WORK_DIR, f"{folder}_tracks.json")
        with open(track_file, "w") as f:
            json.dump(tracks, f, indent=2)

        print(f"Saved: {folder} ({len(tracks)} tracks)")
        print(f"Folder: {folder_path}")
        try:
            context.storage_state(path=SPOTIFY_STORAGE_STATE)
            save_cookies(context)
            print(f"Cookies refreshed: {COOKIES_FILE}")
        except Exception:
            pass

        if do_download:
            import download_tracks
            download_tracks.download_one_playlist(folder)

        # Close only if this script started the browser.
        if browser and not connected_via_cdp:
            try:
                browser.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
