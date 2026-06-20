#!/usr/bin/env python3
"""
Download YouTube videos at 1080p quality.
Usage: python3 download_youtube.py '<VIDEO_URL>'
"""
import sys
import subprocess
import os
from config import DOWNLOAD_DIR, YT_DLP_PATH

def download_video(url, output_name="youtube_video"):
    """Download YouTube video at 1080p"""
    output_path = os.path.join(DOWNLOAD_DIR, f"{output_name}.%(ext)s")
    
    cmd = [
        YT_DLP_PATH,
        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
        "--merge-output-format", "mp4",
        "--embed-subs",
        "--sub-langs", "en",
        "-o", output_path,
        url
    ]
    
    print(f"Downloading: {url}")
    print(f"Output: {DOWNLOAD_DIR}/{output_name}.mp4")
    print()
    
    subprocess.run(cmd)
    print("\nDownload complete!")

def fix_partial_video(part_file):
    """Fix a partially downloaded video file"""
    if not os.path.exists(part_file):
        print(f"File not found: {part_file}")
        return
    
    output_file = part_file.replace(".part", "_fixed.mp4")
    
    cmd = [
        "ffmpeg",
        "-err_detect", "ignore_err",
        "-i", part_file,
        "-c", "copy",
        output_file
    ]
    
    print(f"Fixing partial video: {part_file}")
    subprocess.run(cmd)
    print(f"Fixed video saved to: {output_file}")
    
    # Remove the .part file
    os.remove(part_file)
    print("Cleaned up partial file")

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  Download video: python3 download_youtube.py '<VIDEO_URL>'")
        print("  Fix partial file: python3 download_youtube.py --fix <part_file>")
        sys.exit(1)
    
    if sys.argv[1] == "--fix":
        if len(sys.argv) < 3:
            print("Usage: python3 download_youtube.py --fix <path_to_part_file>")
            sys.exit(1)
        fix_partial_video(sys.argv[2])
    else:
        url = sys.argv[1]
        download_video(url)

if __name__ == "__main__":
    main()
