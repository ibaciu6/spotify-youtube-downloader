#!/usr/bin/env python3
"""Import local *_tracks.json files into download queue."""
import sys
import os
import json
import glob
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from storage import init_db, add_queue, WORK_DIR

TRACKS_DIR = os.path.join(WORK_DIR)

def extract_playlist_name(filename):
    base = os.path.basename(filename)
    if base.endswith("_tracks.json"):
        name = base[: -len("_tracks.json")]
    elif base.endswith("_tracks.JSON"):
        name = base[: -len("_tracks.JSON")]
    else:
        name = os.path.splitext(base)[0]
    return name.strip()

def main():
    init_db()
    pattern = os.path.join(TRACKS_DIR, "*_tracks.json")
    files = sorted(glob.glob(pattern))

    if not files:
        print(f"No *_tracks.json files found in {TRACKS_DIR}")
        sys.exit(1)

    imported = 0
    for fp in files:
        playlist = extract_playlist_name(fp)
        with open(fp) as f:
            tracks = json.load(f)

        if not isinstance(tracks, list):
            print(f"  SKIP (not a list): {playlist}")
            continue

        qid = add_queue(folder=playlist, source_url="local", tracks=tracks)
        print(f"  {playlist}: {len(tracks)} tracks -> queue {qid}")
        imported += 1

    print(f"\nImported {imported} playlists into download queue.")
    print("Run daemon to start downloading: ./start.sh daemon start")

if __name__ == "__main__":
    main()
