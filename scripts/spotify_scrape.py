#!/usr/bin/env python3
"""
DOM scraping helpers for open.spotify.com playlist pages (virtualized lists).
"""
import re
import sys
from urllib.parse import urlparse


def scroll_playlist_viewport(page, step_px: int = 0):
    """Scroll the main playlist/tracklist container so virtualized rows mount.
    If step_px > 0, scroll incrementally instead of jumping to bottom -
    this triggers IntersectionObserver repeatedly for lazy-loaded items."""
    page.evaluate(
        f"""
        () => {{
          const pick = () =>
            document.querySelector('[data-testid="playlist-tracklist"]') ||
            document.querySelector('[data-testid="track-list"]') ||
            document.querySelector('main[role="main"]') ||
            document.querySelector('main') ||
            document.scrollingElement ||
            document.documentElement;
          const el = pick();
          if (el) {{
            if ({step_px} > 0) {{
              el.scrollBy({{top: {step_px}, behavior: 'auto'}});
            }} else {{
              el.scrollTop = el.scrollHeight;
            }}
          }}
          if ({step_px} <= 0) {{
            window.scrollTo(0, document.body.scrollHeight);
          }}
        }}
        """
    )


def get_expected_track_count(page):
    """Parse '155 songs' style hint from visible page text (Spotify header)."""
    try:
        text = page.inner_text("body", timeout=5000)
    except Exception:
        return None
    if not text:
        return None
    # Match largest plausible count (avoid tiny numbers from unrelated UI)
    best = None
    for m in re.finditer(r"(\d{1,4})\s+songs?", text, re.I):
        n = int(m.group(1))
        if best is None or n > best:
            best = n
    return best


def harvest_playlist_rows(page, seen_keys: set[str] | None = None, tracks_out: list[str] | None = None) -> list[str]:
    """Read currently mounted track rows (no scrolling)."""
    if seen_keys is None:
        seen_keys = set()
    if tracks_out is None:
        tracks_out = []
    primary = '[data-testid="tracklist-row"]'
    fallback = '[role="row"]'
    rows = page.query_selector_all(primary)
    if not rows:
        rows = page.query_selector_all(fallback)
    for row in rows:
        try:
            name_el = row.query_selector('a[href*="/track/"]')
            href = ""
            if name_el:
                href = (name_el.get_attribute("href") or "").strip()
                name = name_el.inner_text().strip()
            else:
                name = ""
            artist_els = row.query_selector_all('a[href*="/artist/"]')
            artist = ", ".join(
                a.inner_text().strip()
                for a in artist_els
                if a.inner_text().strip()
            )
            if not name:
                text = row.inner_text()
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                if len(lines) >= 2:
                    name = lines[0]
                    artist = artist or lines[1]
            if not (name and artist):
                continue
            key = href if href else f"{artist}::{name}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            tracks_out.append(f"{artist} - {name}")
        except Exception:
            continue
    return tracks_out


def focus_tracklist(page) -> None:
    """Click / focus playlist body so keyboard scroll targets the virtualized list."""
    try:
        loc = page.locator('[data-testid="playlist-tracklist"], [data-testid="top-sentinel"]').first
        if loc.count() > 0:
            loc.click(timeout=3000)
    except Exception:
        pass


def harvest_all_text_content(page) -> str:
    """
    Extract ALL text content from the page using JavaScript.
    This is more reliable than element queries which can cause greenlet errors.
    """
    try:
        return page.evaluate("""
            () => {
                const main = document.querySelector('main') || document.body;
                if (!main) return '';
                let text = '';
                const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT, null, false);
                let node;
                while (node = walker.nextNode()) {
                    const t = node.textContent.trim();
                    if (t && t.length > 1 && !t.startsWith('http')) {
                        text += t + '\\n';
                    }
                }
                return text;
            }
        """)
    except Exception as e:
        print(f"[harvest-text] Error: {e}", file=sys.stderr)
        return ""


# Bogus track patterns to filter out
BOGUS_PATTERNS = [
    r'saves?\s*-\s*\d+\s*songs?',      # "7,857,814 saves - 80 songs"
    r'\d+\s+saves?',                    # "12345 saves"
    r'\d+\s*days?\s+ago',               # "4 days ago", "3 days ago"
    r'\d+\s*hours?\s+ago',              # "2 hours ago"
    r'\d+\s*weeks?\s+ago',              # "1 week ago"
    r'date\s+added',                    # "Date added"
    r'date\s+created',                  # "Date created"
    r'added\s+\d+',                     # "Added 3 days ago"
    r'title\s*-\s*album',               # "Title - Album" header
    r'artist\s*-\s*artist',             # "Artist - Artist" header
    r'album\s*-\s*album',               # "Album - Album" header
    r'duration',                        # "Duration"
    r'total\s+time',                    # "Total time"
    r'length',                          # "Length"
    r'^\d+:\d{2}$',                     # "3:45" duration only
    r'^\d{1,3}:\d{2}$',                # duration patterns
    r'^\s*E\s*$',                       # "E" explicit marker
    r'^\s*•\s*$',                       # "•" bullet
    r'^\s*Play\s*$',                    # "Play" button
    r'^\s*Pause\s*$',                   # "Pause" button
    r'^\s*Add\s*$',                     # "Add" button
    r'^\s*More\s*$',                    # "More" button
    r'^\s*Save\s*$',                    # "Save" button
    r'^\s*Share\s*$',                   # "Share" button
    r'^\s*Explicit\s*$',                # "Explicit"
    r'about\s+\d+\s+hr',               # "about 3 hr 30 min"
    r'^\d+\s+hr\s+\d+\s+min',           # "3 hr 30 min"
    r'list$',                           # "List" header
    r'^List\s*$',                       # "List"
    r'^Playlist\s*$',                   # "Playlist"
    # Playlist description patterns
    r'pumping\s+tracks?\s+for\s+pumping',
    r'workout\s+mix',
    r'gym\s+hits?',
    r'best\s+of\s+\d{4}',
    r'top\s+\d+',
    r'hits?\s+\d{4}',
    # Artist - Artist patterns (not real tracks)
    r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*-\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s*$',
]

BOGUS_COMPILED = [re.compile(p, re.I) for p in BOGUS_PATTERNS]

# Known bogus artist names that appear as separators
BOGUS_ARTISTS = {
    'dimitri vegas', 'like mike', 'marlon hoffstadt', 'dj konik',
    'david guetta', 'marten hørger', 'men machine', 'breathe carolina',
    'giacobbi', 'alok', 'khalid', 'southstar', 'braaheim', 'robbe',
    'max styler', 'vintage culture', 'ali love', 'chrystal', 'notion',
    'bebe rexha', 'faithless', 'gordo', 'reinier zonneveld', 'danny l harle',
    'dua lipa', 'lost frequencies', 'nathan nicholson', 'calvin harris',
    'kasabian', 'alesso', 'joa', 'tyree cooper', 'illeniu', 'dustin lynch',
    'lightleak', 'anyma', 'lisa', 'felix jaehn', 'roro', 'hvrr', 'technoir',
    'ely oaks', 'dimitri vegas', 'like mike', 'marlon hoffstadt', 'dj konik',
    'kygo', 'gryffin', 'fisher', 'tones and i', 'matt sassari', 'talvo', 'repulse',
    'ian asher', 'galantis', 'nimino', 'steve angello', 'kream', 'clementine douglas',
    'mondello', 'ceres', 'tribbs', 'hugel', 'solto', 'effy', 'tiësto', 'gabry ponte',
    'namasenda', 'hypaton', 'la bouche', 'jennifer lopez', 'ella henderson', 'rudimental',
    'aaron smith', 'luvli', 'indila', 'bennett', 'r2', 'dom dolla', 'tiga',
    'cloonee', 'young m.a', 'inntraw', 'hntr', 'joji', 'badger', 'natasha bedingfield',
    'niklas dee', 'old jim', 'enny-mae', 'jain', 'mau p', 'john summit', 'the chainsmokers',
    'ilsey', 'sean paul', 'odd mob',
}

# Known bogus titles that are actually artist names or album names
BOGUS_TITLES = {
    'marten hørger', 'men machine', 'men machine ep', 'breathe carolina', 'giacobbi',
    'dive into me', 'i like', 'turn the lights off', 'freaky 1', 'vintage culture',
    'ali love', 'the days', 'notion remix', 'new religion', 'loco loco',
    'two hearts', 'cerulean', 'so much beauty', 'around us', 'release the pressure',
    'turn up the bass', 'die living', 'dustin lynch', 'mambos', 'bad angel',
    'believe in', 'right here', 'makina time', 'dj konik', 'dimitri vegas', 'like mike',
    'save my love', 'favour', 'give it to me', 'full vocal mix', 'react',
    'runaway', 'u & i', 'tivoli', 'kream remix', 'let\'s get fkd up', 'sad girls',
    'jamaican', 'bam bam', 'talk nice', 'mockingbird', 'miami crest', 'be my lover',
    'save me tonight', 'alibi', 'dancin', 'southstar remix', 'dernière danse',
    'techno mix', 'blah blah blah', 'don\'t worry baby', 'lay low', 'it\'s that time',
    'fisher remix', 'stephanie', 'hntr remix', 'beautiful', 'these words', 'makeba',
    'ian asher remix', 'the less i know the better', 'not fair', 'all the time',
    'get busy', 'odd mob club mix', 'pumping tracks for pumping iron',
}

def is_bogus_track(artist: str, title: str) -> bool:
    """Check if a track looks like bogus metadata rather than a real song."""
    combined = f"{artist} - {title}".strip()
    artist_lower = artist.lower().strip()
    title_lower = title.lower().strip()
    
    # Check against bogus patterns
    for pattern in BOGUS_COMPILED:
        if pattern.search(combined):
            return True
        if pattern.search(artist) or pattern.search(title):
            return True
    
    # Check if artist or title is a known bogus separator
    if artist_lower in BOGUS_ARTISTS:
        # If artist is a known bogus artist, check if title is also bogus
        if title_lower in BOGUS_TITLES or title_lower in BOGUS_ARTISTS:
            return True
    
    if title_lower in BOGUS_TITLES:
        return True
    
    # Additional heuristics
    # Too many numbers relative to letters (likely a stats line)
    for text in [artist, title, combined]:
        letters = sum(1 for c in text if c.isalpha())
        digits = sum(1 for c in text if c.isdigit())
        if letters > 0 and digits > letters * 2:
            return True
    
    # Common bogus combinations
    bogus_combos = [
        ('saves', 'songs'),
        ('date', 'added'),
        ('title', 'album'),
        ('artist', 'artist'),
    ]
    combined_lower = combined.lower()
    for a, b in bogus_combos:
        if a in combined_lower and b in combined_lower:
            return True
    
    # Check for "Artist - Artist" pattern (both parts are known artists)
    if artist_lower in BOGUS_ARTISTS and title_lower in BOGUS_ARTISTS:
        return True
    
    # Check for "Title - Album" or "Artist - Album" patterns
    album_keywords = ['ep', 'album', 'single', 'remix', 'mix', 'version', 'edit']
    if any(kw in title_lower for kw in album_keywords) and artist_lower in BOGUS_ARTISTS:
        # Could be "Artist - Album" which is bogus
        pass
    
    return False


def parse_tracks_from_text(text: str) -> list[tuple[str, str]]:
    """
    Parse track names and artists from raw text.
    Returns list of (artist, title) tuples.
    """
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    tracks = []
    
    # UI elements to skip
    ui_patterns = [
        'Spotify', 'Premium', 'Support', 'Download', 'Sign up', 'Log in',
        'Home', 'Search', 'Your Library', 'Create Playlist', 'Liked Songs',
        'Cookie', 'Privacy', 'Terms', 'Legal', 'Privacy Policy', 'Terms of Service',
        'About', 'Ads', 'Careers', 'For the Record', 'Communities', 'Developers',
        'Advertising', 'Investors', 'Vendors', 'Free Mobile App', 'Spotify Free',
        'Premium Individual', 'Premium Duo', 'Premium Family', 'Premium Student',
        'Company', 'Useful links', 'Popular', 'By Country', 'Import', 'Plans',
        'Popular by Country', 'Import your music', 'Spotify Plans',
        'Recommended', 'Based on', 'Playlist', 'Recommended for you', 'Preview',
        'HOW MUSIC WORKS', 'Viral Pop Hits', 'Stef', '🫧✨'
    ]
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # Skip UI elements, timestamps, numbers
        if re.match(r'^\d{1,3}:\d{2}$', line):  # Duration like 3:45
            i += 1
            continue
        if re.match(r'^\d+$', line):  # Just a number
            i += 1
            continue
        if line in ['Play', 'Pause', 'Add', 'More', 'Save', 'Share', 'Explicit', 'E', '•']:
            i += 1
            continue
            
        # Skip lines that look like UI elements
        if any(ui in line for ui in ui_patterns):
            i += 1
            continue
        
        # Skip if line is too long or too short
        if len(line) < 2 or len(line) > 150:
            i += 1
            continue
        
        # Look for potential artist-title pairs
        # Pattern: Artist on one line, Title on next
        if i + 1 < len(lines):
            next_line = lines[i + 1]
            
            # Skip if next line looks like a timestamp or UI element
            if not re.match(r'^\d{1,3}:\d{2}$', next_line) and \
               next_line not in ['Explicit', 'E', 'Play', '•'] and \
               len(next_line) > 1 and len(next_line) < 150 and \
               not any(ui in next_line for ui in ui_patterns):
                
                artist = line
                title = next_line
                
                # Validate: both should have some alphabetic characters
                if re.search(r'[a-zA-Z]', artist) and re.search(r'[a-zA-Z]', title):
                    tracks.append((artist, title))
                    i += 2
                    continue
        
        i += 1
    
    return tracks


def harvest_tracks_text_based(page, seen_keys: set[str] | None = None) -> list[str]:
    """
    Harvest tracks using text-based extraction.
    More robust than element queries which can cause threading issues.
    """
    if seen_keys is None:
        seen_keys = set()
    
    tracks_out = []
    text = harvest_all_text_content(page)
    
    if text:
        parsed = parse_tracks_from_text(text)
        for artist, title in parsed:
            if is_bogus_track(artist, title):
                continue
            key = f"{artist}::{title}"
            if key not in seen_keys:
                seen_keys.add(key)
                tracks_out.append(f"{artist} - {title}")
    
    return tracks_out


def filter_bogus_tracks(tracks: list[str]) -> list[str]:
    """Filter out bogus tracks from a list of 'Artist - Title' strings."""
    filtered = []
    seen = set()
    for track in tracks:
        if ' - ' not in track:
            continue
        artist, title = track.split(' - ', 1)
        if is_bogus_track(artist, title):
            continue
        key = f"{artist}::{title}"
        if key not in seen:
            seen.add(key)
            filtered.append(track)
    return filtered


def scrape_playlist_tracks(page, do_scroll: bool = True):
    """
    Collect track rows from a playlist page.
    Prefers data-testid tracklist rows; uses track href as stable key when present.
    Scrolls until count stabilizes or matches expected 'N songs' from the page.
    """
    seen_keys: set[str] = set()
    tracks: list[str] = []

    def harvest():
        harvest_playlist_rows(page, seen_keys, tracks)

    if not do_scroll:
        harvest()
        return tracks

    expected = None
    try:
        expected = get_expected_track_count(page)
    except Exception:
        pass

    stable_rounds = 0
    max_rounds = 200 if expected else 120
    target_stable = 18 if expected else 14

    focus_tracklist(page)
    for round_idx in range(max_rounds):
        before = len(tracks)
        harvest()

        if expected and len(tracks) >= expected:
            break

        if len(tracks) == before:
            stable_rounds += 1
        else:
            stable_rounds = 0

        if tracks and stable_rounds >= target_stable:
            # If UI promised more songs, keep forcing scroll a bit longer
            if expected and len(tracks) < expected and round_idx < max_rounds - 30:
                stable_rounds = max(0, stable_rounds - 8)
            else:
                break

        scroll_playlist_viewport(page)
        try:
            page.keyboard.press("PageDown")
            page.keyboard.press("End")
        except Exception:
            pass
        page.wait_for_timeout(650 + min(round_idx, 25) * 15)

    return tracks


def _get_playlist_id(url: str) -> str:
    """Extract playlist ID from a Spotify playlist URL."""
    parsed = urlparse(url)
    path = parsed.path
    parts = path.split("/")
    if len(parts) >= 3 and parts[1] == "playlist":
        return parts[2]
    return ""


def collect_playlist_tracks_with_network(
    page,
    playlist_url: str,
    collector=None,
    skip_initial_goto: bool = False,
) -> tuple[list[str], int, int]:
    """
    Load playlist URL, scroll to trigger XHR pagination, merge network JSON + DOM.
    Falls back to direct REST API calls using browser Bearer token when virtual
    scroller doesn't load all tracks.
    Returns (tracks, n_network, n_dom).
    """
    from spotify_network import PlaylistNetworkCollector

    if collector is None:
        collector = PlaylistNetworkCollector()
        collector.attach(page)
    if not skip_initial_goto:
        page.goto(playlist_url, wait_until="domcontentloaded", timeout=120_000)
        page.wait_for_timeout(2500)
    focus_tracklist(page)

    expected = None
    try:
        expected = get_expected_track_count(page)
        print(f"[DEBUG] Expected track count: {expected}", flush=True, file=sys.stderr)
    except Exception:
        pass

    max_scrolls = 400 if expected else 350
    print(f"[DEBUG] Starting scroll loop (max={max_scrolls}, expected={expected})...", flush=True, file=sys.stderr)
    last_logged_tracks = -1
    stagnant_count = 0
    
    # Also collect from text-based extraction
    seen_text_keys: set[str] = set()
    text_tracks: list[str] = []
    
    for i in range(max_scrolls):
        if i % 10 == 0:
            current_tracks = len(collector.tracks_ordered())
            if current_tracks != last_logged_tracks:
                print(f"[DEBUG] Scroll {i}/{max_scrolls}, network: {current_tracks}, text: {len(text_tracks)}", flush=True, file=sys.stderr)
                last_logged_tracks = current_tracks
                stagnant_count = 0
            else:
                stagnant_count += 1
                # If stuck for a while, try text extraction
                if stagnant_count >= 3:
                    new_text = harvest_tracks_text_based(page, seen_text_keys)
                    if new_text:
                        text_tracks.extend(new_text)
                        print(f"[DEBUG] Text extraction added {len(new_text)} tracks (total: {len(text_tracks)})", flush=True, file=sys.stderr)
        
        # Scroll incrementally to trigger IntersectionObserver for lazy-loaded items
        scroll_step = 800 if i < 200 else 1200
        scroll_playlist_viewport(page, step_px=scroll_step)
        try:
            # Try different scroll methods
            if i % 3 == 0:
                page.keyboard.press("End")
            elif i % 3 == 1:
                page.keyboard.press("PageDown")
            else:
                page.evaluate(f"window.scrollBy(0, {scroll_step})")
        except Exception:
            pass
        
        # Progressive wait time
        wait_time = 150 if i < 50 else (250 if i < 150 else 350)
        page.wait_for_timeout(wait_time)
        
        if expected and len(collector.tracks_ordered()) >= expected:
            print(f"[DEBUG] Reached expected track count: {expected}", flush=True, file=sys.stderr)
            break
            
        # Break if no progress for too long
        if stagnant_count >= 15 and i > 100:
            print(f"[DEBUG] No progress for 150 scrolls, breaking", flush=True, file=sys.stderr)
            break
    
    print(f"[DEBUG] Scroll loop complete, total scrolls: {i+1}", flush=True, file=sys.stderr)

    # Response bodies are parsed on worker threads; give them time to finish.
    page.wait_for_timeout(4000)
    tracks_net = collector.tracks_ordered()
    print(f"[DEBUG] Network tracks: {len(tracks_net)}", flush=True, file=sys.stderr)

    # Try multiple DOM extraction methods
    tracks_dom = harvest_playlist_rows(page)
    print(f"[DEBUG] DOM tracks (element harvest): {len(tracks_dom)}", flush=True, file=sys.stderr)
    
    # Add text-based tracks
    if text_tracks:
        print(f"[DEBUG] Text-based tracks: {len(text_tracks)}", flush=True, file=sys.stderr)
    
    # Merge all sources
    all_tracks = list(dict.fromkeys(tracks_net + tracks_dom + text_tracks))
    print(f"[DEBUG] Total unique tracks after merge: {len(all_tracks)}", flush=True, file=sys.stderr)
    
    # Filter bogus tracks
    all_tracks = filter_bogus_tracks(all_tracks)
    print(f"[DEBUG] After bogus filter: {len(all_tracks)}", flush=True, file=sys.stderr)
    
    # Use collector's totalCount as fallback if page text didn't provide expected
    if not expected:
        expected = collector.get_total_count()
        if expected:
            print(f"[DEBUG] Using pathfinder totalCount as expected: {expected}", flush=True, file=sys.stderr)

    # If expected count not reached, try direct pathfinder pagination
    api_tracks = []
    if expected and len(all_tracks) < expected:
        print(f"[DEBUG] Missing {expected - len(all_tracks)} tracks, trying pathfinder pagination...", flush=True, file=sys.stderr)
        existing = set(tracks_net)
        api_tracks = collector.fetch_pathfinder_paginated(existing)
        if api_tracks:
            print(f"[DEBUG] Pathfinder pagination added {len(api_tracks)} tracks", flush=True, file=sys.stderr)

    # Pathfinder results are authoritative — discard DOM/text noise when we have them
    if api_tracks:
        all_tracks = list(dict.fromkeys(tracks_net + api_tracks))
    else:
        all_tracks = list(dict.fromkeys(tracks_net + tracks_dom + text_tracks))
    
    # Final bogus filter
    all_tracks = filter_bogus_tracks(all_tracks)

    print(f"[DEBUG] Final track count: {len(all_tracks)}", flush=True, file=sys.stderr)
    
    return all_tracks, len(tracks_net), len(tracks_dom)
