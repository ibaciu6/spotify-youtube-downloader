#!/usr/bin/env python3
"""
Spotify Web API helper.
Supports OAuth authorization, token refresh, and full playlist track extraction.
"""
import base64
import json
import os
import re
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from config import (
    WORK_DIR,
    SPOTIFY_OAUTH_REDIRECT_URI,
    SPOTIFY_OAUTH_SCOPES,
    SPOTIFY_TOKEN_FILE,
)


AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"


def _read_secret_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def load_spotify_app_credentials():
    """Read Spotify app credentials from local files or env vars."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    client_id = _read_secret_file(os.path.join(base_dir, ".spotify_client_id")) or os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = _read_secret_file(os.path.join(base_dir, ".spotify_client_secret")) or os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
    return client_id, client_secret


def has_web_api_app_credentials():
    """True if developer app id/secret are present (OAuth possible)."""
    cid, sec = load_spotify_app_credentials()
    return bool(cid and sec)


def api_error_suggests_premium_or_blocked(message: str) -> bool:
    """Spotify may block Web API for Free-tier developer accounts."""
    if not message:
        return False
    lower = message.lower()
    return (
        "premium" in lower
        or "blocked" in lower
        or "does not have access" in lower
        or "upgrade to spotify premium" in lower
        or "spotify api error (403)" in lower
    )


def _token_path():
    os.makedirs(WORK_DIR, exist_ok=True)
    return SPOTIFY_TOKEN_FILE


def load_token():
    path = _token_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_token(token_data):
    path = _token_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2)


def _post_form(url, data, headers=None):
    body = urlencode(data).encode("utf-8")
    req_headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if headers:
        req_headers.update(headers)
    req = Request(url, data=body, headers=req_headers, method="POST")
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _auth_header(client_id, client_secret):
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return f"Basic {base64.b64encode(raw).decode('ascii')}"


def refresh_access_token(client_id, client_secret, refresh_token):
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    headers = {"Authorization": _auth_header(client_id, client_secret)}
    token_data = _post_form(TOKEN_URL, payload, headers=headers)
    token_data["refresh_token"] = token_data.get("refresh_token") or refresh_token
    token_data["expires_at"] = int(time.time()) + int(token_data.get("expires_in", 3600)) - 30
    save_token(token_data)
    return token_data


def _wait_for_oauth_code(redirect_uri, timeout_s=180):
    parsed = urlparse(redirect_uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8888
    path = parsed.path or "/callback"
    result = {"code": None, "error": None}
    done = threading.Event()

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            current = urlparse(self.path)
            params = parse_qs(current.query)
            if current.path != path:
                self.send_response(404)
                self.end_headers()
                return
            result["code"] = (params.get("code") or [None])[0]
            result["error"] = (params.get("error") or [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h3>Spotify auth complete.</h3>"
                b"<p>You can close this tab and return to terminal.</p></body></html>"
            )
            done.set()

        def log_message(self, _fmt, *_args):
            return

    server = HTTPServer((host, port), CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        if not done.wait(timeout=timeout_s):
            return None, "Timeout waiting for Spotify authorization callback."
        if result["error"]:
            return None, f"Spotify authorization error: {result['error']}"
        if not result["code"]:
            return None, "No authorization code received."
        return result["code"], None
    finally:
        server.shutdown()
        server.server_close()


def authorize_interactive():
    """Run OAuth Authorization Code flow and save token locally."""
    client_id, client_secret = load_spotify_app_credentials()
    if not client_id or not client_secret:
        raise RuntimeError(
            "Missing Spotify app credentials. Add .spotify_client_id and "
            ".spotify_client_secret files (or env vars)."
        )

    params = {
        "response_type": "code",
        "client_id": client_id,
        "scope": SPOTIFY_OAUTH_SCOPES,
        "redirect_uri": SPOTIFY_OAUTH_REDIRECT_URI,
    }
    auth_link = f"{AUTH_URL}?{urlencode(params)}"
    print("Opening browser for Spotify OAuth...")
    webbrowser.open(auth_link)
    code, err = _wait_for_oauth_code(SPOTIFY_OAUTH_REDIRECT_URI)
    if err:
        raise RuntimeError(err)

    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": SPOTIFY_OAUTH_REDIRECT_URI,
    }
    token_data = _post_form(TOKEN_URL, payload, headers={"Authorization": _auth_header(client_id, client_secret)})
    token_data["expires_at"] = int(time.time()) + int(token_data.get("expires_in", 3600)) - 30
    save_token(token_data)
    return token_data


def get_valid_access_token(auto_authorize=False):
    """Return a valid access token, refreshing/authorizing when possible."""
    client_id, client_secret = load_spotify_app_credentials()
    if not client_id or not client_secret:
        raise RuntimeError("Spotify app credentials not configured.")

    token = load_token()
    access_token = token.get("access_token")
    expires_at = int(token.get("expires_at", 0) or 0)
    if access_token and expires_at > int(time.time()) + 10:
        return access_token

    refresh_token = token.get("refresh_token")
    if refresh_token:
        refreshed = refresh_access_token(client_id, client_secret, refresh_token)
        return refreshed.get("access_token", "")

    if auto_authorize:
        created = authorize_interactive()
        return created.get("access_token", "")

    raise RuntimeError("No Spotify token available. Run OAuth authorization first.")


def api_get(path, access_token, query=None):
    query = query or {}
    url = f"{API_BASE}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    req = Request(url, headers={"Authorization": f"Bearer {access_token}"}, method="GET")
    try:
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = str(e)
        raise RuntimeError(f"Spotify API error ({e.code}): {body}") from e
    except URLError as e:
        raise RuntimeError(f"Spotify API network error: {e}") from e


def extract_playlist_id(raw):
    text = raw.strip()
    match = re.search(r"(?:https?://open\.spotify\.com/playlist/)?([A-Za-z0-9]+)", text)
    if not match:
        return ""
    return match.group(1)


def get_playlist_metadata_and_tracks(playlist_url_or_id, auto_authorize=False):
    """Fetch full playlist name + all tracks using official paginated API."""
    playlist_id = extract_playlist_id(playlist_url_or_id)
    if not playlist_id:
        raise RuntimeError("Invalid Spotify playlist URL or ID.")

    token = get_valid_access_token(auto_authorize=auto_authorize)
    playlist = api_get(f"/playlists/{playlist_id}", token, {"fields": "name,owner(display_name),tracks(total)"})
    display_name = playlist.get("name") or "Playlist"
    owner = (playlist.get("owner") or {}).get("display_name")
    if owner:
        display_name = f"{display_name} - playlist by {owner}"

    tracks = []
    offset = 0
    limit = 100
    while True:
        data = api_get(
            f"/playlists/{playlist_id}/tracks",
            token,
            {
                "limit": limit,
                "offset": offset,
                "fields": "items(track(name,artists(name),is_local)),next,total",
            },
        )
        items = data.get("items") or []
        for item in items:
            track = (item or {}).get("track") or {}
            if not track or track.get("is_local"):
                continue
            name = (track.get("name") or "").strip()
            artists = ", ".join((a.get("name") or "").strip() for a in (track.get("artists") or []) if (a.get("name") or "").strip())
            if name and artists:
                tracks.append(f"{artists} - {name}")
        if not data.get("next"):
            break
        offset += limit

    # Keep order, remove duplicates.
    deduped = list(dict.fromkeys(tracks))
    return display_name, deduped


if __name__ == "__main__":
    try:
        authorize_interactive()
        print(f"OAuth token saved: {SPOTIFY_TOKEN_FILE}")
    except Exception as e:
        print(f"Spotify OAuth failed: {e}")
