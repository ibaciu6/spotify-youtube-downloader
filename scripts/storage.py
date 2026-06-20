#!/usr/bin/env python3
"""SQLite storage for download queue and status."""
import sqlite3
import os
import time
import uuid
from pathlib import Path

BASE_DIR = os.path.expanduser("~/local/mp3")
WORK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "work")
DOWNLOADS_DIR = os.path.join(BASE_DIR, "downloads")
DB_PATH = os.path.join(WORK_DIR, "downloader.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS queues (
    id TEXT PRIMARY KEY,
    folder TEXT NOT NULL,
    source_url TEXT,
    created_at REAL,
    status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id TEXT NOT NULL,
    query TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    file_path TEXT,
    attempts INTEGER DEFAULT 0,
    error TEXT,
    created_at REAL,
    completed_at REAL,
    FOREIGN KEY (queue_id) REFERENCES queues(id)
);

CREATE INDEX IF NOT EXISTS idx_tracks_queue ON tracks(queue_id);
CREATE INDEX IF NOT EXISTS idx_tracks_status ON tracks(status);
"""

def init_db():
    Path(WORK_DIR).mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        conn.commit()

def add_queue(folder, source_url, tracks):
    queue_id = str(uuid.uuid4())[:8]
    now = time.time()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO queues (id, folder, source_url, created_at) VALUES (?, ?, ?, ?)",
            (queue_id, folder, source_url, now)
        )
        for t in tracks:
            conn.execute(
                "INSERT INTO tracks (queue_id, query, created_at) VALUES (?, ?, ?)",
                (queue_id, t, now)
            )
        conn.commit()
    return queue_id

def get_pending_queues():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("""
            SELECT q.*, COUNT(t.id) as total_tracks,
                   SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END) as done_tracks,
                   SUM(CASE WHEN t.status = 'downloading' THEN 1 ELSE 0 END) as downloading_tracks,
                   SUM(CASE WHEN t.status = 'pending' THEN 1 ELSE 0 END) as pending_tracks,
                   SUM(CASE WHEN t.status = 'failed' THEN 1 ELSE 0 END) as failed_tracks
            FROM queues q
            LEFT JOIN tracks t ON q.id = t.queue_id
            WHERE q.status != 'completed'
            GROUP BY q.id
            HAVING pending_tracks > 0 OR downloading_tracks > 0
            ORDER BY q.created_at
        """)
        return [dict(r) for r in cur.fetchall()]

def get_pending_tracks(queue_id, limit=50):
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("""
            SELECT * FROM tracks
            WHERE queue_id = ? AND status = 'pending'
            ORDER BY created_at
            LIMIT ?
        """, (queue_id, limit))
        return [dict(r) for r in cur.fetchall()]

def mark_downloading(track_id):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE tracks SET status = 'downloading' WHERE id = ?", (track_id,))
        conn.commit()

def mark_completed(track_id, file_path):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE tracks SET status = 'completed', file_path = ?, completed_at = ? WHERE id = ?",
            (file_path, time.time(), track_id)
        )
        conn.commit()

def mark_failed(track_id, error, attempts):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE tracks SET status = 'failed', error = ?, attempts = ? WHERE id = ?",
            (error, attempts, track_id)
        )
        conn.commit()

def mark_pending(track_id, attempts):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE tracks SET status = 'pending', attempts = ? WHERE id = ?",
            (attempts, track_id)
        )
        conn.commit()

def update_queue_status(queue_id):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as done,
                   SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
            FROM tracks WHERE queue_id = ?
        """, (queue_id,))
        row = cur.fetchone()
        total, done, failed = row
        if total == done:
            status = 'completed'
        elif failed == total:
            status = 'failed'
        else:
            status = 'processing'
        conn.execute("UPDATE queues SET status = ? WHERE id = ?", (status, queue_id))
        conn.commit()
    return status

def reset_stuck_downloads(timeout_secs=600):
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "UPDATE tracks SET status = 'pending' WHERE status = 'downloading'"
        )
        conn.commit()
        return cur.rowcount

def get_stats():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute("""
            SELECT 
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'downloading' THEN 1 ELSE 0 END) as downloading,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed
            FROM tracks
        """)
        row = cur.fetchone()
        if row:
            return dict(row)
        return {"pending": 0, "downloading": 0, "completed": 0, "failed": 0}

if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")