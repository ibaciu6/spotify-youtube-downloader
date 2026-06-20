#!/usr/bin/env bash
# Main menu for Spotify → YouTube Downloader
# Run: ./start.sh                          (interactive menu, auto-starts Web UI)
# Run: ./start.sh <spotify_url>             (add to download queue)
# Run: ./start.sh daemon <start|stop|status|logs>  (manage background daemon)

set -e
cd "$(dirname "$0")"

# Clear stale Python bytecache
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null

VENV="venv/bin/activate"
if [ -f "$VENV" ]; then
    source "$VENV"
fi

# Track background processes for cleanup
WEBUI_PID=""
DAEMON_STARTED=false

cleanup() {
    if [ -n "$WEBUI_PID" ] && kill -0 "$WEBUI_PID" 2>/dev/null; then
        echo "Stopping Web UI (PID: $WEBUI_PID)..."
        kill "$WEBUI_PID" 2>/dev/null
        wait "$WEBUI_PID" 2>/dev/null
    fi
}
trap cleanup EXIT INT TERM

# Start Web UI in background
echo "Starting Web UI on http://localhost:8899 ..."
source venv/bin/activate
python3 webui.py > /tmp/webui.log 2>&1 &
WEBUI_PID=$!
sleep 2

# Verify it started
if kill -0 "$WEBUI_PID" 2>/dev/null; then
    echo "Web UI running (PID: $WEBUI_PID)"
    echo "Open http://localhost:8899 in your browser"
else
    echo "WARNING: Web UI failed to start. Check /tmp/webui.log"
fi

# Direct URL mode - add to queue
if [ $# -ge 1 ] && [[ "$1" == *"open.spotify.com/"* ]]; then
    echo "Adding to download queue: $1"
    python3 scripts/module1_fetch.py "$1"
    echo ""
    echo "To start downloading, run: ./start.sh daemon start"
    exit 0
fi

# Daemon management
if [ $# -ge 1 ] && [ "$1" == "daemon" ]; then
    shift
    python3 scripts/daemon_cli.py "$@"
    exit $?
fi

prompt_spotify_url() {
    local url=""
    while true; do
        echo >&2
        echo >&2 "Paste Spotify URL (playlist or track), or 'q' to cancel:"
        read -r -p "> " url
        url="${url#"${url%%[![:space:]]*}"}"
        url="${url%"${url##*[![:space:]]}"}"
        if [ -z "$url" ]; then
            echo >&2 "URL cannot be empty."
            continue
        fi
        case "$url" in
            q|Q)
                echo >&2 ""
                return 1
                ;;
        esac
        if [[ "$url" == *"open.spotify.com/playlist/"* ]]; then
            printf 'playlist|%s\n' "$url"
            return 0
        fi
        if [[ "$url" == *"open.spotify.com/track/"* ]]; then
            printf 'track|%s\n' "$url"
            return 0
        fi
        echo >&2 "No Spotify URL detected. Paste the full link."
    done
}

while true; do
    echo
    echo "=================================================="
    echo "  Spotify → YouTube Downloader (Modular)"
    echo "=================================================="
    echo
    echo "  Web UI: http://localhost:8899"
    echo
    echo "  1. Add Spotify URL to queue (playlist or track)"
    echo "  2. Start download daemon (background)"
    echo "  3. Show daemon status (live)"
    echo "  4. Stop download daemon"
    echo "  5. Open Spotify (browser – log in if needed)"
    echo "  6. Reset stuck downloads"
    echo "  7. Import local track lists to queue"
    echo "  8. View Web UI logs"
    echo "  9. Exit"
    echo
    read -r -p "Choice [1-9]: " choice
    choice=${choice:-0}

    case "$choice" in
        1)
            if result=$(prompt_spotify_url); then
                python3 scripts/module1_fetch.py "$result"
                echo ""
                echo "Added to queue. Start daemon with option 2 to download."
            else
                echo "Canceled."
            fi
            ;;
        2)
            python3 scripts/daemon_cli.py start
            ;;
        3)
            # Live status loop - updates every 3 seconds until key press
            echo "Showing live daemon status (press any key to return)..."
            while true; do
                clear
                python3 scripts/daemon_cli.py status
                echo ""
                echo "Press any key to return to menu (refreshes every 3s)..."
                if read -t 3 -n 1 -s key 2>/dev/null; then
                    break
                fi
            done
            ;;
        4)
            python3 scripts/daemon_cli.py stop
            ;;
        5)
            python3 scripts/open_spotify.py
            ;;
        6)
            python3 -c "import sys; sys.path.insert(0, 'scripts'); from storage import reset_stuck_downloads; n = reset_stuck_downloads(); print(f'Reset {n} stuck tracks')"
            ;;
        7)
            python3 scripts/import_local_tracks.py
            ;;
        8)
            echo "=== Web UI Logs ==="
            tail -30 /tmp/webui.log 2>/dev/null || echo "(no logs)"
            echo ""
            echo "=== Downloader Daemon Logs ==="
            tail -30 work/daemon.log 2>/dev/null || echo "(no logs)"
            echo ""
            read -r -p "Press Enter to return to menu..." key
            ;;
        9)
            echo "Bye."
            exit 0
            ;;
        *)
            echo "Invalid option. Enter 1-9."
            ;;
    esac
done