#!/usr/bin/env python3
"""
Restore playlist folder structure on USB from source folders.
Maps each file to its original playlist folder.
"""

import os
import shutil
from pathlib import Path

SOURCE_ROOT = Path("/home/ursu/local/mp3")
DEST_ROOT = Path("/mnt/e/Music")

# Source playlist folders
PLAYLIST_FOLDERS = [
    "Best_90s_Techno_Trance",
    "Brain_Damage",
    "Gym_Hits",
    "KISS_FM_Romania_Top40",
    "Magic_FM",
    "Muzica_Romaneasca_2010-2015",
    "Muzica_Romaneasca_Top100",
    "singles",
]

def main():
    # Build mapping: filename -> playlist folder
    file_to_playlist = {}
    
    for playlist in PLAYLIST_FOLDERS:
        src_dir = SOURCE_ROOT / playlist
        if not src_dir.exists():
            print(f"Warning: {src_dir} not found")
            continue
        
        for f in src_dir.rglob("*"):
            if f.is_file() and f.suffix.lower() in ('.mp3', '.mp4'):
                file_to_playlist[f.name] = playlist
    
    print(f"Mapped {len(file_to_playlist)} files to playlists")
    
    # Create destination folders
    for playlist in PLAYLIST_FOLDERS:
        (DEST_ROOT / playlist).mkdir(parents=True, exist_ok=True)
    
    # Move files to their playlist folders
    moved = 0
    not_found = []
    
    for f in DEST_ROOT.iterdir():
        if f.is_file() and f.suffix.lower() in ('.mp3', '.mp4'):
            playlist = file_to_playlist.get(f.name)
            if playlist:
                dest = DEST_ROOT / playlist / f.name
                # Handle collision
                counter = 1
                while dest.exists():
                    stem = f.stem
                    suffix = f.suffix
                    dest = DEST_ROOT / playlist / f"{stem} ({counter}){suffix}"
                    counter += 1
                shutil.move(str(f), str(dest))
                moved += 1
            else:
                not_found.append(f.name)
    
    print(f"Moved {moved} files to playlist folders")
    
    if not_found:
        print(f"\n{len(not_found)} files not found in source (putting in 'Other'):")
        other_dir = DEST_ROOT / "Other"
        other_dir.mkdir(exist_ok=True)
        for name in not_found:
            src = DEST_ROOT / name
            dest = other_dir / name
            counter = 1
            while dest.exists():
                stem = src.stem
                suffix = src.suffix
                dest = other_dir / f"{stem} ({counter}){suffix}"
                counter += 1
            shutil.move(str(src), str(dest))
        print(f"Moved {len(not_found)} to Other/")

if __name__ == "__main__":
    main()