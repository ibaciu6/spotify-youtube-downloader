#!/usr/bin/env python3
"""
Deduplicate and move music files from source to destination.
Handles exact filename matches and fuzzy matches (removes common suffixes).
"""

import os
import re
import shutil
from pathlib import Path
from collections import defaultdict

SOURCE_DIR = Path("/home/ursu/local/mp3")
DEST_DIR = Path("/mnt/e/Music")

# Common suffixes to strip for fuzzy matching
SUFFIXES_TO_REMOVE = [
    r'\s*\(official lyric video\)',
    r'\s*\(official video\)',
    r'\s*\(lyric video\)',
    r'\s*\(lyrics\)',
    r'\s*\(official audio\)',
    r'\s*\(audio\)',
    r'\s*\(video\)',
    r'\s*\[official lyric video\]',
    r'\s*\[official video\]',
    r'\s*\[lyric video\]',
    r'\s*\[lyrics\]',
    r'\s*\[official audio\]',
    r'\s*\[audio\]',
    r'\s*\[video\]',
    r'\s*\(official\)',
    r'\s*\[official\]',
    r'\s*\(hd\)',
    r'\s*\[hd\]',
    r'\s*\(hq\)',
    r'\s*\[hq\]',
    r'\s*\(remastered\)',
    r'\s*\[remastered\]',
    r'\s*\(remix\)',
    r'\s*\[remix\]',
    r'\s*\(live\)',
    r'\s*\[live\]',
    r'\s*\(acoustic\)',
    r'\s*\[acoustic\]',
    r'\s*\(instrumental\)',
    r'\s*\[instrumental\]',
    r'\s*\(extended\)',
    r'\s*\[extended\]',
    r'\s*\(radio edit\)',
    r'\s*\[radio edit\]',
    r'\s*\(edit\)',
    r'\s*\[edit\]',
    r'\s*\(single\)',
    r'\s*\[single\]',
    r'\s*\(album\)',
    r'\s*\[album\]',
    r'\s*\(feat\..*?\)',
    r'\s*\[feat\..*?\]',
    r'\s*\(ft\..*?\)',
    r'\s*\[ft\..*?\]',
    r'\s*featuring.*',
]

SUFFIX_PATTERNS = [re.compile(s, re.IGNORECASE) for s in SUFFIXES_TO_REMOVE]


def normalize_filename(filename: str) -> str:
    """Normalize filename for fuzzy matching."""
    name = filename.lower()
    name = name.replace('.mp3', '').replace('.mp4', '')
    for pattern in SUFFIX_PATTERNS:
        name = pattern.sub('', name)
    name = re.sub(r'[^\w\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def collect_files(root: Path) -> list[dict]:
    """Collect all music files with metadata."""
    files = []
    for ext in ('*.mp3', '*.mp4'):
        for f in root.rglob(ext):
            try:
                stat = f.stat()
                files.append({
                    'path': f,
                    'name': f.name,
                    'norm_name': normalize_filename(f.name),
                    'size': stat.st_size,
                    'mtime': stat.st_mtime,
                    'rel_dir': f.parent.relative_to(root) if f.parent != root else Path('.'),
                })
            except OSError:
                pass
    return files


def find_best_version(dupes: list[dict]) -> dict:
    """Select best version from duplicates. Prefer: smaller name, larger size."""
    return min(dupes, key=lambda f: (len(f['name']), -f['size']))


def main():
    print("Collecting files...")
    src_files = collect_files(SOURCE_DIR)
    dst_files = collect_files(DEST_DIR)
    print(f"Source: {len(src_files)} files")
    print(f"Dest:   {len(dst_files)} files")

    all_files = src_files + dst_files

    # Group by normalized name
    groups = defaultdict(list)
    for f in all_files:
        groups[f['norm_name']].append(f)

    # Find duplicates
    exact_dupes = {k: v for k, v in groups.items() if len(v) > 1}

    # For each group, pick best version
    keep = {}
    remove = []

    for norm_name, files in exact_dupes.items():
        best = find_best_version(files)
        keep[norm_name] = best
        for f in files:
            if f != best:
                remove.append(f['path'])
        print(f"  Duplicate group: {norm_name}")
        for f in files:
            marker = " <-- KEEP" if f == best else " <-- REMOVE"
            print(f"    {f['path']}{marker}")

    # Files with no duplicates
    for norm_name, files in groups.items():
        if len(files) == 1:
            keep[norm_name] = files[0]

    print(f"\nTotal unique tracks: {len(keep)}")
    print(f"Files to remove: {len(remove)}")

    # Confirm
    response = input("\nProceed with copy to destination? [y/N] ").strip().lower()
    if response != 'y':
        print("Aborted")
        return

    # Copy unique files to destination (organized by artist/album or flat)
    copied = 0
    for norm_name, f in keep.items():
        src_path = f['path']
        # Try to determine a good destination folder
        # Use the first part before " - " as artist folder
        parts = f['name'].replace('.mp3', '').replace('.mp4', '').split(' - ', 1)
        if len(parts) == 2:
            artist = parts[0].strip()
            # Sanitize folder name
            artist = re.sub(r'[\\/*?:"<>|]', '_', artist).strip()
            dest_folder = DEST_DIR / artist
        else:
            dest_folder = DEST_DIR

        dest_folder.mkdir(parents=True, exist_ok=True)
        dest_path = dest_folder / f['name']

        # Handle filename collision in destination folder
        counter = 1
        original_dest = dest_path
        while dest_path.exists():
            stem = original_dest.stem
            suffix = original_dest.suffix
            dest_path = dest_folder / f"{stem} ({counter}){suffix}"
            counter += 1

        try:
            if src_path != dest_path:
                shutil.copy2(src_path, dest_path)
                copied += 1
                if copied % 50 == 0:
                    print(f"  Copied {copied}...")
        except Exception as e:
            print(f"  Error copying {src_path}: {e}")

    print(f"\nDone! Copied {copied} new files to {DEST_DIR}")

    # Optionally remove source files
    response = input("\nRemove source files from ~/local/mp3? [y/N] ").strip().lower()
    if response == 'y':
        for f in src_files:
            try:
                f['path'].unlink()
            except Exception:
                pass
        # Remove empty directories
        for d in SOURCE_DIR.iterdir():
            if d.is_dir() and not any(d.iterdir()):
                d.rmdir()
        print("Source cleaned up.")


if __name__ == "__main__":
    main()