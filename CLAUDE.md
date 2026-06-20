# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the tool

```bash
./start.sh                                               # interactive menu + web UI on :8899
./start.sh "https://open.spotify.com/playlist/ID"       # add playlist directly
./start.sh daemon start|stop|status                     # manage daemon

python3 scripts/download_youtube.py 'URL'               # single YouTube/TikTok download
python3 scripts/download_youtube.py --fix file.mp4.part # recover partial download
```

## Install

```bash
bash install.sh         # Ubuntu/Debian full install
pip install -r requirements.txt && python -m playwright install chromium
```

## Architecture

**Two independent subsystems:**

### 1. Spotify → MP3 daemon pipeline
```
module1_fetch.py  →  SQLite queue  →  daemon_downloader.py  →  ~/local/mp3/downloads/
```
- `module1_fetch.py` — accepts Spotify URL (playlist/track), resolves tracks via API or Playwright scrape, writes to `work/queue/`
- `storage.py` — SQLite DB (`work/downloads.db`); queue, status, stats
- `daemon_downloader.py` — polls queue, calls `download_single_track.py` per track via `ThreadPoolExecutor` (10 workers)
- `download_single_track.py` — searches YouTube for `"Artist - Title"`, downloads MP3 via `yt-dlp`, embeds metadata
- `daemon_cli.py` — start/stop/status wrapper for the daemon process

### 2. Web UI
- `webui.py` — Flask app on `:8899`; two panels: quick yt-dlp download (any URL → MP3/MP4) and Spotify daemon management
- `templates/index.html` — single-page UI; polling `/api/jobs/<id>` and `/api/daemon/status`
- `start.sh` launches webui.py as a background process before showing the menu

## Spotify track resolution (layered fallback)
1. Spotify Web API (if `.spotify_client_id` / `.spotify_client_secret` present)
2. `spotify_graphql_fetcher.py` — XHR network interception during Playwright scroll
3. `spotify_scrape.py` — DOM scraping fallback

## Credentials
- `scripts/credentials.py` — Spotify email/password (gitignored, copy from `credentials.example.py`)
- `scripts/.spotify_client_id` / `.spotify_client_secret` — Spotify Web API app creds (gitignored)
- `work/spotify_storage_state.json` — Playwright saved browser session (gitignored)

## Key paths (from `config.py`)
- `BASE_DIR` = `~/local/mp3` — MP3 output root
- `WORK_DIR` = `./work/` — queue JSON, DB, logs, Playwright session
- `YT_DLP_PATH` — auto-detected via `which yt-dlp` or `~/bin/yt-dlp`
