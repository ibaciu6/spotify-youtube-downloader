# Spotify & YouTube Downloader

Download Spotify playlists as MP3s and YouTube/TikTok videos — with a web UI and background daemon.

## How it works

1. Spotify URLs are fetched via the official Spotify Web API (with optional OAuth app credentials) or a Playwright browser session as fallback
2. Each track is searched on YouTube and downloaded as MP3 via `yt-dlp`
3. A background daemon processes the queue, and a local web UI lets you manage everything from the browser

## Requirements

- Python 3.9+
- `ffmpeg` (for audio conversion and video merging)
- Node.js 20+ (optional — for some Spotify tools)

## Install

```bash
# Ubuntu/Debian — installs all system and Python deps
bash install.sh

# Or manually
pip install -r requirements.txt
python -m playwright install chromium
```

## Setup credentials

```bash
cp scripts/credentials.example.py scripts/credentials.py
```

Edit `scripts/credentials.py`:

```python
SPOTIFY_EMAIL = "your-email@example.com"
SPOTIFY_PASSWORD = "your-password"

PLAYLISTS = [
    ("https://open.spotify.com/playlist/PLAYLIST_ID", "folder_name"),
]
```

> `credentials.py` is gitignored — it will never be committed.

### Optional: Spotify Web API (faster, full pagination)

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and create an app
2. Set Redirect URI to `http://127.0.0.1:8888/callback`
3. Save your Client ID and Secret:

```bash
echo "YOUR_CLIENT_ID"     > scripts/.spotify_client_id
echo "YOUR_CLIENT_SECRET" > scripts/.spotify_client_secret
```

Without these, the tool uses Playwright browser automation to scrape playlists.

## Usage

### Web UI + interactive menu

```bash
./start.sh
```

Opens the menu and launches the web UI at **http://localhost:8899**.

From the web UI you can:
- Paste any YouTube, TikTok, or direct video URL to download as MP3 or MP4
- Add Spotify playlists to the queue
- Start/stop/monitor the download daemon

### CLI shortcuts

```bash
./start.sh "https://open.spotify.com/playlist/PLAYLIST_ID"   # add playlist to queue
./start.sh daemon start      # start background downloader
./start.sh daemon status     # check progress
./start.sh daemon stop
```

### Download a single YouTube video

```bash
python3 scripts/download_youtube.py 'https://www.youtube.com/watch?v=VIDEO_ID'
```

### Fix a partial download

```bash
python3 scripts/download_youtube.py --fix ~/local/mp3/video.mp4.part
```

## Configuration

Edit `scripts/config.py` to change defaults:

| Setting | Default | Description |
|---------|---------|-------------|
| `BASE_DIR` | `~/local/mp3` | Root folder for MP3 output |
| `MAX_WORKERS` | `10` | Parallel download threads |
| `AUDIO_QUALITY` | `0` | yt-dlp quality (0 = best) |
| `POLL_INTERVAL` | `5` | Daemon queue poll interval (seconds) |

## Output structure

```
~/local/mp3/
  downloads/
    playlist-folder/
      Artist - Track.mp3
      ...
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Playlist shows only ~25 tracks | Run with `SPOTIFY_HEADLESS=0 ./start.sh` to use a visible browser |
| Debug network capture | `SPOTIFY_DEBUG_NETWORK=1 python3 scripts/fetch_playlist.py 'URL'` |
| yt-dlp not found | Check `~/bin/yt-dlp` or run `which yt-dlp` |
| FFmpeg errors | Run `ffmpeg -version` to verify install |
| Daemon stuck | Choose option 6 (Reset stuck downloads) from the menu |
