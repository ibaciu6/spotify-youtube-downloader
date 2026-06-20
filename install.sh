#!/bin/bash
# Spotify & YouTube Downloader Installation Script for Ubuntu
# This script installs all required dependencies

set -e

echo "=== Spotify & YouTube Downloader Installer ==="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running on Ubuntu/Debian
if ! command -v apt-get &> /dev/null; then
    echo -e "${RED}Error: This script is designed for Ubuntu/Debian systems${NC}"
    exit 1
fi

echo -e "${YELLOW}Step 1/5: Updating package list...${NC}"
sudo apt-get update

echo -e "${YELLOW}Step 2/5: Installing Python3, pip, and ffmpeg...${NC}"
sudo apt-get install -y python3 python3-pip python3-venv ffmpeg curl

echo -e "${YELLOW}Step 3/5: Installing Node.js (required for some tools)...${NC}"
if ! command -v node &> /dev/null; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi

echo -e "${YELLOW}Step 4/5: Installing Playwright (for browser automation)...${NC}"
pip3 install playwright --break-system-packages || pip3 install playwright --user
python3 -m playwright install chromium

echo -e "${YELLOW}Step 5/5: Installing yt-dlp...${NC}"
# Download latest yt-dlp
mkdir -p ~/bin
curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o ~/bin/yt-dlp
chmod +x ~/bin/yt-dlp

# Add ~/bin to PATH if not already there
if [[ ":$PATH:" != *":$HOME/bin:"* ]]; then
    echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
    echo -e "${GREEN}Added ~/bin to PATH in ~/.bashrc${NC}"
fi

echo ""
echo -e "${GREEN}=== Installation Complete! ===${NC}"
echo ""
echo "Tools installed:"
echo "  - ffmpeg: $(which ffmpeg)"
echo "  - python3: $(which python3)"
echo "  - yt-dlp: ~/bin/yt-dlp"
echo "  - playwright: $(which playwright)"
echo ""
echo "To use the downloader:"
echo "  1. Edit scripts/config.py with your settings"
echo "  2. Run: python3 scripts/open_spotify.py (to login to Spotify)"
echo "  3. Run: python3 scripts/extract_playlists.py (to get playlist tracks)"
echo "  4. Run: python3 scripts/download_tracks.py (to download MP3s)"
echo ""
echo "For YouTube videos:"
echo "  python3 scripts/download_youtube.py '<VIDEO_URL>'"
