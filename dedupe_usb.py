#!/usr/bin/env python3
"""
Remove duplicate files from USB drive only.
Keeps the best version (no (1)/(2) suffixes, no "official lyric video" etc.).
"""

import os
import re
from pathlib import Path
from collections import defaultdict

DEST_DIR = Path("/mnt/e/Music")

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
    name = filename.lower()
    name = name.replace('.mp3', '').replace('.mp4', '')
    for pattern in SUFFIX_PATTERNS:
        name = pattern.sub('', name)
    # Remove (1), (2), etc. suffixes
    name = re.sub(r'\s*\(\d+\)', '', name)
    name = re.sub(r'[^\w\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def collect_files(root: Path) -> list[dict]:
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
                    'has_number_suffix': bool(re.search(r'\(\d+\)', f.name)),
                })
            except OSError:
                pass
    return files


def find_best_version(dupes: list[dict]) -> dict:
    """Select best version: prefer no number suffix, larger size."""
    return min(dupes, key=lambda f: (1 if f['has_number_suffix'] else 0, -f['size'], len(f['name'])))


def main():
    print("Collecting files from USB...")
    dst_files = collect_files(DEST_DIR)
    print(f"USB: {len(dst_files)} files")

    groups = defaultdict(list)
    for f in dst_files:
        groups[f['norm_name']].append(f)

    exact_dupes = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"Duplicate groups: {len(exact_dupes)}")

    remove = []
    for norm_name, files in exact_dupes.items():
        best = find_best_version(files)
        for f in files:
            if f != best:
                remove.append(f['path'])
        print(f"  {norm_name}: KEEP {best['path'].name} ({best['size']} bytes)")
        for f in files:
            if f != best:
                print(f"    REMOVE {f['path'].name} ({f['size']} bytes)")

    print(f"\nTotal to remove: {len(remove)}")
    
    # Actually remove
    removed = 0
    for p in remove:
        try:
            p.unlink()
            removed += 1
        except Exception as e:
            print(f"  Error removing {p}: {e}")

    print(f"\nRemoved {removed} duplicate files")

    # Remove empty directories
    for d in DEST_DIR.iterdir():
        if d.is_dir() and not any(d.iterdir()):
            try:
                d.rmdir()
                print(f"Removed empty dir: {d.name}")
            except Exception:
                pass


if __name__ == "__main__":
    main()