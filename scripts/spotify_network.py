#!/usr/bin/env python3
"""
Capture playlist track metadata from Spotify Web Player network responses.
Falls back when the virtualized DOM only mounts ~25 rows (common in headless / lazy load).
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse


def _artist_join(track: dict[str, Any]) -> str:
    artists_raw = track.get("artists")
    if not isinstance(artists_raw, list):
        return ""
    names = []
    for a in artists_raw:
        if isinstance(a, dict):
            n = (a.get("name") or "").strip()
            if n:
                names.append(n)
    return ", ".join(names)


def _track_uri_key(track: dict[str, Any]) -> str | None:
    uri = track.get("uri")
    if isinstance(uri, str) and uri.startswith("spotify:track:"):
        return uri
    tid = track.get("id")
    if isinstance(tid, str) and tid:
        return f"spotify:track:{tid}"
    return None


def _label_from_track_obj(obj: dict[str, Any]) -> tuple[str, str] | None:
    """Return (uri_key, 'Artist - Title') or None."""
    name = (obj.get("name") or "").strip()
    artists = _artist_join(obj)
    if not name or not artists:
        return None
    key = _track_uri_key(obj)
    if not key:
        key = f"{artists}|{name}"
    return key, f"{artists} - {name}"


def _walk_collect_tracks(node: Any, acc: dict[str, str]) -> None:
    """Find nested track objects anywhere in JSON."""
    if isinstance(node, dict):
        if node.get("type") == "track" or (
            node.get("name") and isinstance(node.get("artists"), list) and _artist_join(node)
        ):
            pair = _label_from_track_obj(node)
            if pair:
                k, label = pair
                acc.setdefault(k, label)
        for v in node.values():
            _walk_collect_tracks(v, acc)
    elif isinstance(node, list):
        for item in node:
            _walk_collect_tracks(item, acc)


def _ingest_v1_playlist_tracks_url(url: str, data: dict[str, Any], chunks: list[tuple[int, list[tuple[str, str]]]]) -> None:
    """Parse GET /v1/playlists/{id}/tracks?offset=&limit= responses."""
    if "/v1/playlists/" not in url or "/tracks" not in url:
        return
    try:
        path = urlparse(url).path
        if not re.search(r"/v1/playlists/[^/]+/tracks", path):
            return
    except Exception:
        return
    qs = parse_qs(urlparse(url).query)
    try:
        offset = int((qs.get("offset") or ["0"])[0])
    except ValueError:
        offset = 0
    items = data.get("items")
    if not isinstance(items, list):
        return
    pairs: list[tuple[str, str]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        tr = it.get("track")
        if not isinstance(tr, dict):
            continue
        if tr.get("is_local"):
            continue
        pair = _label_from_track_obj(tr)
        if pair:
            pairs.append(pair)
    if pairs:
        chunks.append((offset, pairs))


def _extract_pathfinder_artists(track: dict[str, Any]) -> str:
    """Extract artist names from pathfinder track format (artists.items[].profile.name)."""
    artists_obj = track.get("artists")
    if not isinstance(artists_obj, dict):
        return ""
    items = artists_obj.get("items")
    if not isinstance(items, list):
        return ""
    names = []
    for a in items:
        if isinstance(a, dict):
            # Try profile.name first (pathfinder format)
            if isinstance(a.get("profile"), dict):
                name = a["profile"].get("name", "").strip()
                if name:
                    names.append(name)
            # Fallback to direct name field
            elif a.get("name"):
                names.append(a["name"].strip())
    return ", ".join(names)


def _ingest_pathfinder_query(data: dict[str, Any], generic: dict[str, str]) -> None:
    """Parse api-partner.spotify.com/pathfinder/v2/query GraphQL responses.
    
    Uses generic dict for deduplication (not chunks) since pathfinder uses cursors not offsets.
    """
    # Pathfinder returns data in data.playlistV2.content.items structure
    playlist = None
    if isinstance(data.get("data"), dict):
        playlist = data["data"].get("playlistV2") or data["data"].get("playlist")
    if not isinstance(playlist, dict):
        return

    # Extract tracks from content.items (the modern structure)
    items = None
    if isinstance(playlist.get("content"), dict):
        items = playlist["content"].get("items")
    elif isinstance(playlist.get("trV2"), dict):
        items = playlist["trV2"].get("items")
    elif isinstance(playlist.get("tracks"), dict):
        items = playlist["tracks"].get("items")
    elif isinstance(playlist.get("items"), list):
        items = playlist["items"]

    if not isinstance(items, list):
        return

    count = 0
    for it in items:
        if not isinstance(it, dict):
            continue

        # Track data is in itemV2.data or itemV3.data (nested structure)
        track = None
        item_wrapper = None
        if isinstance(it.get("itemV2"), dict):
            item_wrapper = it["itemV2"]
        elif isinstance(it.get("itemV3"), dict):
            item_wrapper = it["itemV3"]

        # The actual track is in the 'data' field of itemV2/itemV3
        if isinstance(item_wrapper, dict):
            if isinstance(item_wrapper.get("data"), dict):
                track = item_wrapper["data"]
            else:
                track = item_wrapper  # Fallback to wrapper itself
        elif it.get("__typename") == "Track":
            track = it
        elif isinstance(it.get("track"), dict):
            track = it["track"]
        elif isinstance(it.get("data"), dict):
            track = it["data"]

        if not isinstance(track, dict):
            continue

        # Skip local tracks and non-track items (like episodes)
        if track.get("isLocal") or track.get("is_local"):
            continue
        if track.get("__typename") not in (None, "Track"):
            continue

        # Extract track info with pathfinder artist format support
        name = (track.get("name") or "").strip()
        artists = _extract_pathfinder_artists(track)
        if not name or not artists:
            continue

        # Build key from uri or id
        uri = track.get("uri", "")
        tid = track.get("id", "")
        if uri and uri.startswith("spotify:track:"):
            key = uri
        elif tid:
            key = f"spotify:track:{tid}"
        else:
            key = f"{artists}|{name}"

        # Add to generic dict for automatic deduplication
        generic.setdefault(key, f"{artists} - {name}")
        count += 1


@dataclass
class PlaylistNetworkCollector:
    """Attach to a Playwright page; collect tracks from JSON responses."""

    _chunks: list[tuple[int, list[tuple[str, str]]]] = field(default_factory=list)
    _generic: dict[str, str] = field(default_factory=dict)
    _handler: Callable[..., None] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _auth_token: str = ""
    _pathfinder_body: bytes | None = None
    _pathfinder_headers: dict[str, str] | None = None
    _total_count: int = 0

    def attach(self, page) -> None:
        import sys
        prev = getattr(page, "_spotify_playlist_collector_handler", None)
        if prev is not None:
            try:
                page.remove_listener("response", prev)
            except Exception:
                pass

        # Counters for debugging
        self._total_responses = 0
        self._json_responses = 0
        self._spotify_responses = 0
        self._captured_responses = 0
        self._auth_token = ""
        self._pathfinder_body = None
        self._pathfinder_headers = None
        self._total_count = 0

        # Capture auth token and pathfinder request body from request headers
        def on_request(request) -> None:
            try:
                auth = request.headers.get("authorization", "")
                if auth.startswith("Bearer ") and not self._auth_token:
                    self._auth_token = auth[7:]
                # Capture pathfinder POST body for later replay
                url = request.url
                if "pathfinder" in url and request.method == "POST":
                    body = request.post_data
                    if body and not self._pathfinder_body:
                        self._pathfinder_body = body.encode("utf-8") if isinstance(body, str) else body
                        self._pathfinder_headers = dict(request.headers)
            except Exception:
                pass

        page.on("request", on_request)

        def on_response(response) -> None:
            # Capture all Playwright response data in the main thread (greenlet-safe).
            # Playwright sync API objects are not thread-safe; extract primitives here.
            try:
                self._total_responses += 1
                status = response.status
                url = response.url

                # Log every 50th response for visibility
                if self._total_responses % 50 == 0:
                    print(f"[spotify-network] Processed {self._total_responses} responses, captured: {self._captured_responses}", file=sys.stderr)

                if status != 200:
                    return
                try:
                    rtype = response.request.resource_type
                except Exception:
                    rtype = ""
                if rtype and rtype not in ("xhr", "fetch"):
                    return
                ctype = (response.headers.get("content-type") or "").lower()
                if "json" not in ctype:
                    return
                self._json_responses += 1
                if "spotify" not in url.lower():
                    return
                self._spotify_responses += 1
                # Accept all Spotify JSON API endpoints (widen for new domains)
                spotify_api_indicators = (
                    "api.spotify.com",
                    "spclient.wg.spotify.com",
                    "gew-spclient.spotify.com",
                    "graphql",
                    "edge-api.spotify.com",
                    "open.spotify.com",
                    "spotify.com",
                )
                if not any(x in url for x in spotify_api_indicators):
                    return
                print(f"[spotify-network] Capturing: {url[:100]}", file=sys.stderr)
                self._captured_responses += 1
                # response.text() can deadlock navigation; read body bytes and decode in thread
                try:
                    body_bytes = response.body()
                except Exception as e:
                    print(f"[spotify-network] Failed to read body: {e}", file=sys.stderr)
                    return
            except Exception as e:
                print(f"[spotify-network] Exception in handler: {e}", file=sys.stderr)
                return

            # Offload JSON parsing and data ingestion to a worker thread
            def work(url: str, body_bytes: bytes) -> None:
                try:
                    if not body_bytes:
                        return
                    try:
                        text = body_bytes.decode("utf-8", errors="replace")
                    except Exception:
                        return
                    stripped = text.lstrip()
                    if not stripped.startswith(("{", "[")):
                        return
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        return


                    # Debug: log pathfinder totalCount
                    if "pathfinder" in url and isinstance(data, dict):
                        try:
                            playlist = data.get("data", {}).get("playlistV2") or data.get("data", {}).get("playlist")
                            if isinstance(playlist, dict) and isinstance(playlist.get("content"), dict):
                                total = playlist["content"].get("totalCount")
                                paging = playlist["content"].get("pagingInfo", {})
                                if total:
                                    if total > self._total_count:
                                        self._total_count = total
                                    print(f"[spotify-network] Pathfinder totalCount: {total}, offset: {paging.get('offset', 'N/A')}", file=sys.stderr)
                        except Exception:
                            pass

                    with self._lock:
                        if isinstance(data, dict):
                            _ingest_v1_playlist_tracks_url(url, data, self._chunks)
                            # Also try pathfinder GraphQL endpoint (uses generic dict for dedup)
                            if "pathfinder" in url or "/query" in url:
                                _ingest_pathfinder_query(data, self._generic)
                        extra: dict[str, str] = {}
                        _walk_collect_tracks(data, extra)
                        for k, v in extra.items():
                            self._generic.setdefault(k, v)
                except Exception:
                    return

            threading.Thread(target=work, args=(url, body_bytes), daemon=True).start()

        self._handler = on_response
        page._spotify_playlist_collector_handler = on_response
        page.on("response", on_response)

    def get_auth_token(self) -> str:
        return self._auth_token

    def get_total_count(self) -> int:
        return self._total_count

    def fetch_pathfinder_paginated(self, existing: set[str]) -> list[str]:
        """Replay pathfinder GraphQL query with incremented offset to get all tracks.
        Uses captured request body + auth token — same endpoint as the page, no rate limit."""
        token = self._auth_token
        body_bytes = self._pathfinder_body
        if not token or not body_bytes:
            print("[spotify-network] Cannot paginate: no auth token or pathfinder body captured", file=sys.stderr)
            return []

        import urllib.request
        from urllib.error import HTTPError

        # Parse variables from captured body
        try:
            body_text = body_bytes.decode("utf-8", errors="replace")
            body_json = json.loads(body_text)
            variables = body_json.get("variables", {})
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[spotify-network] Failed to parse pathfinder body: {e}", file=sys.stderr)
            return []

        # Determine pagination params from variables
        limit = variables.get("limit", 50)
        offset = variables.get("offset", 0)
        total = self._total_count

        if not total:
            print("[spotify-network] No totalCount known, cannot paginate", file=sys.stderr)
            return []

        print(f"[spotify-network] Pathfinder pagination: total={total}, limit={limit}, start_offset={offset}", file=sys.stderr)

        # Build headers from captured ones + auth token
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json;charset=UTF-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "app-platform": "WebPlayer",
            "spotify-app-version": "1.2.0",
        }

        out = []
        seen_keys: set[str] = set()
        for t in existing:
            seen_keys.add(t)

        # Start from where we left off
        next_offset = offset + limit
        page_size = limit

        while next_offset < total:
            # Clone variables with new offset
            new_vars = dict(variables)
            new_vars["offset"] = next_offset
            new_body = json.dumps({"operationName": body_json.get("operationName"), "variables": new_vars, "extensions": body_json.get("extensions"), "query": body_json.get("query")}).encode("utf-8")

            req = urllib.request.Request(
                "https://api-partner.spotify.com/pathfinder/v2/query",
                data=new_body,
                headers=headers,
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                print(f"[spotify-network] Pathfinder pagination error ({e.code}): {body[:200]}", file=sys.stderr)
                break
            except Exception as e:
                print(f"[spotify-network] Pathfinder pagination failed: {e}", file=sys.stderr)
                break

            # Parse tracks from response
            generic: dict[str, str] = {}
            _ingest_pathfinder_query(data, generic)
            count_before = len(out)
            for key, label in generic.items():
                if key not in seen_keys and label not in seen_keys:
                    seen_keys.add(key)
                    seen_keys.add(label)
                    out.append(label)
            print(f"[spotify-network] Pathfinder page offset={next_offset}: got {len(out) - count_before} new tracks", file=sys.stderr)

            next_offset += page_size

        return out

    def tracks_ordered(self) -> list[str]:
        """Merge offset-ordered API chunks, then append generic walk keys not seen."""
        with self._lock:
            chunks = list(self._chunks)
            generic = dict(self._generic)
        out: list[str] = []
        seen: set[str] = set()

        if chunks:
            chunks.sort(key=lambda x: x[0])
            # Debug: log chunk info
            total_in_chunks = sum(len(pairs) for _, pairs in chunks)
            offsets = [off for off, _ in chunks]
            print(f"[spotify-network] Merging {len(chunks)} chunks, offsets: {offsets}, total pairs: {total_in_chunks}", file=sys.stderr)
            for _offset, pairs in chunks:
                for uri_key, label in pairs:
                    if uri_key in seen:
                        continue
                    seen.add(uri_key)
                    out.append(label)
            print(f"[spotify-network] After merge: {len(out)} unique tracks", file=sys.stderr)

        for uri_key, label in generic.items():
            if uri_key in seen:
                continue
            seen.add(uri_key)
            out.append(label)

        return out
