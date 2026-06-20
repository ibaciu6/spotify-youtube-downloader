#!/usr/bin/env python3
"""
Alternative approach: Make manual GraphQL requests to fetch ALL playlist tracks.
Uses pathfinder API with pagination to get beyond the web player's 75-track viewport limit.
"""

import json
import sys
import time
import urllib.request
import urllib.parse
from typing import Any


def extract_tokens_from_browser(page) -> dict[str, str] | None:
    """Extract access_token and client_token from the browser's sessionStorage/localStorage."""
    try:
        # Try to get tokens from browser storage
        result = page.evaluate("""
            () => {
                const tokens = {};
                // Try sessionStorage
                for (let i = 0; i < sessionStorage.length; i++) {
                    const key = sessionStorage.key(i);
                    const val = sessionStorage.getItem(key);
                    if (key && val) {
                        if (key.includes('access') || key.includes('token') || key.includes('client')) {
                            tokens[key] = val;
                        }
                    }
                }
                // Try localStorage
                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    const val = localStorage.getItem(key);
                    if (key && val) {
                        if (key.includes('access') || key.includes('token') || key.includes('client')) {
                            tokens[key] = val;
                        }
                    }
                }
                return tokens;
            }
        """)
        print(f"[graphql] Found tokens: {list(result.keys())}", file=sys.stderr)
        return result
    except Exception as e:
        print(f"[graphql] Failed to extract tokens: {e}", file=sys.stderr)
        return None


def get_tokens_from_network_response(collector_data: dict) -> dict[str, str] | None:
    """Try to extract bearer token from captured network responses."""
    # This would need to be populated from network interception
    return None


def fetch_playlist_tracks_graphql(
    playlist_id: str,
    access_token: str,
    client_token: str | None = None,
    limit: int = 100
) -> list[str]:
    """
    Fetch ALL tracks from a playlist using GraphQL pathfinder API with pagination.
    Uses cursor-based pagination to get all tracks beyond initial batch.
    """
    url = "https://api-partner.spotify.com/pathfinder/v1/query"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.0",
        "Authorization": f"Bearer {access_token}",
        "Origin": "https://open.spotify.com",
        "Referer": "https://open.spotify.com/",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    
    if client_token:
        headers["client-token"] = client_token
    
    tracks = []
    cursor = None
    page_count = 0
    max_pages = 20  # Safety limit
    
    # Hash for fetchPlaylist query - this may need updating
    # From spotDL issue: different hashes for different queries
    FETCH_PLAYLIST_HASH = "7a4c5c5e3f8e3f3e3c5d5e6f7a8b9c0d"  # Placeholder - need actual hash
    
    while page_count < max_pages:
        page_count += 1
        
        variables = {
            "uri": f"spotify:playlist:{playlist_id}",
            "limit": limit,
        }
        if cursor:
            variables["offset"] = cursor
        
        payload = {
            "variables": variables,
            "operationName": "fetchPlaylist",
            "extensions": {
                "persistedQuery": {
                    "version": 1,
                    "sha256Hash": FETCH_PLAYLIST_HASH
                }
            }
        }
        
        try:
            data = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                url,
                data=data,
                headers=headers,
                method='POST'
            )
            
            print(f"[graphql] Fetching page {page_count} (cursor={cursor})...", file=sys.stderr)
            
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                
                # Extract tracks from response
                playlist_data = result.get("data", {}).get("playlistV2") or result.get("data", {}).get("playlist")
                if not playlist_data:
                    print(f"[graphql] No playlist data in response", file=sys.stderr)
                    break
                
                content = playlist_data.get("content", {})
                items = content.get("items", [])
                
                page_tracks = 0
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    
                    # Extract track data (handle itemV2/itemV3 wrapper)
                    track_data = item.get("itemV2", {}).get("data") or item.get("itemV3", {}).get("data")
                    if not track_data:
                        continue
                    
                    name = track_data.get("name", "").strip()
                    
                    # Extract artists
                    artists_obj = track_data.get("artists", {})
                    artist_items = artists_obj.get("items", []) if isinstance(artists_obj, dict) else []
                    artist_names = []
                    for a in artist_items:
                        if isinstance(a, dict):
                            profile = a.get("profile", {})
                            artist_name = profile.get("name") if isinstance(profile, dict) else None
                            if not artist_name:
                                artist_name = a.get("name", "")
                            if artist_name:
                                artist_names.append(artist_name)
                    
                    artists = ", ".join(artist_names)
                    if name and artists:
                        tracks.append(f"{artists} - {name}")
                        page_tracks += 1
                
                print(f"[graphql] Page {page_count}: {page_tracks} tracks (total: {len(tracks)})", file=sys.stderr)
                
                # Check for more pages
                paging_info = content.get("pagingInfo", {})
                has_next = paging_info.get("hasNextPage", False)
                next_offset = paging_info.get("offset", 0) + len(items)
                
                if not has_next or len(items) == 0:
                    print(f"[graphql] Reached end of playlist", file=sys.stderr)
                    break
                
                cursor = next_offset
                time.sleep(0.5)  # Rate limiting
                
        except Exception as e:
            print(f"[graphql] Error on page {page_count}: {e}", file=sys.stderr)
            break
    
    return tracks


def fetch_playlist_tracks_rest_api(
    playlist_id: str,
    access_token: str
) -> list[str]:
    """
    Fallback: Use official REST API to fetch all tracks.
    This requires a valid OAuth token with playlist-read scope.
    """
    tracks = []
    offset = 0
    limit = 100
    max_pages = 20
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    
    for page in range(max_pages):
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks?limit={limit}&offset={offset}"
        
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode('utf-8'))
                
                items = data.get("items", [])
                for item in items:
                    track = item.get("track", {})
                    if track.get("is_local"):
                        continue
                    name = track.get("name", "").strip()
                    artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
                    if name and artists:
                        tracks.append(f"{artists} - {name}")
                
                print(f"[rest-api] Page {page+1}: {len(items)} tracks (total: {len(tracks)})", file=sys.stderr)
                
                if not data.get("next") or len(items) == 0:
                    break
                
                offset += limit
                time.sleep(0.3)
                
        except Exception as e:
            print(f"[rest-api] Error: {e}", file=sys.stderr)
            break
    
    return tracks


if __name__ == "__main__":
    print("GraphQL fetcher module - import and use with browser page object")
