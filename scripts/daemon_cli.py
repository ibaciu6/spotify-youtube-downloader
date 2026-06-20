#!/usr/bin/env python3
"""CLI to manage the downloader daemon."""
import os
import sys
import subprocess
import signal
import time
import sqlite3

from storage import DB_PATH, WORK_DIR, get_stats, get_pending_queues

PID_FILE = os.path.join(WORK_DIR, "daemon.pid")
LOG_FILE = os.path.join(WORK_DIR, "daemon.log")

def is_running():
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, OSError):
        return False

def get_pid():
    if os.path.exists(PID_FILE):
        with open(PID_FILE) as f:
            return int(f.read().strip())
    return None

def start_daemon():
    if is_running():
        print("Daemon already running")
        return 1
    
    python = sys.executable
    script = os.path.join(os.path.dirname(__file__), "daemon_downloader.py")
    
    with open(LOG_FILE, "a") as log:
        proc = subprocess.Popen(
            [python, script],
            stdout=log,
            stderr=log,
            start_new_session=True
        )
    
    with open(PID_FILE, "w") as f:
        f.write(str(proc.pid))
    
    time.sleep(1)
    if is_running():
        print(f"Daemon started (PID: {proc.pid})")
        print(f"Log: {LOG_FILE}")
        return 0
    else:
        print("Failed to start daemon")
        return 1

def stop_daemon():
    if not is_running():
        print("Daemon not running")
        return 1
    
    pid = get_pid()
    os.kill(pid, signal.SIGTERM)
    
    for _ in range(10):
        time.sleep(0.5)
        if not is_running():
            break
    else:
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.5)
    
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    
    print("Daemon stopped")
    return 0

def status_daemon():
    stats = get_stats()
    queues = get_pending_queues()
    
    print("=" * 50)
    print("  DOWNLOADER DAEMON STATUS")
    print("=" * 50)
    print(f"  Running: {'Yes' if is_running() else 'No'}")
    if is_running():
        print(f"  PID: {get_pid()}")
    print(f"  Database: {DB_PATH}")
    print(f"  Log: {LOG_FILE}")
    print("-" * 50)
    print(f"  Pending: {stats['pending']}")
    print(f"  Downloading: {stats['downloading']}")
    print(f"  Completed: {stats['completed']}")
    print(f"  Failed: {stats['failed']}")
    print("-" * 50)
    
    if queues:
        print("  Active Queues:")
        for q in queues:
            print(f"    {q['id']} | {q['folder']} | {q['pending_tracks']} pending, {q['downloading_tracks']} downloading, {q['done_tracks']} done")
    else:
        print("  No active queues")
    
    return 0

def logs_daemon(lines=50):
    if os.path.exists(LOG_FILE):
        subprocess.run(["tail", "-n", str(lines), LOG_FILE])
    else:
        print("No log file found")

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 daemon_cli.py <start|stop|restart|status|logs>")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "start":
        sys.exit(start_daemon())
    elif cmd == "stop":
        sys.exit(stop_daemon())
    elif cmd == "restart":
        stop_daemon()
        time.sleep(1)
        sys.exit(start_daemon())
    elif cmd == "status":
        sys.exit(status_daemon())
    elif cmd == "logs":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 50
        logs_daemon(n)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

if __name__ == "__main__":
    main()