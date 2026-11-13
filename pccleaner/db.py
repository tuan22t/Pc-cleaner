"""SQLite cache for scan results, file hashes and the action log."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from . import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY,
    root TEXT NOT NULL,
    started REAL NOT NULL,
    finished REAL,
    status TEXT NOT NULL DEFAULT 'running',
    total_size INTEGER DEFAULT 0,
    file_count INTEGER DEFAULT 0,
    dir_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS dirs (
    scan_id INTEGER NOT NULL,
    id INTEGER NOT NULL,
    parent_id INTEGER,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    size INTEGER DEFAULT 0,
    file_count INTEGER DEFAULT 0,
    PRIMARY KEY (scan_id, id)
);
CREATE INDEX IF NOT EXISTS dirs_parent ON dirs(scan_id, parent_id);
CREATE INDEX IF NOT EXISTS dirs_path ON dirs(scan_id, path);
CREATE TABLE IF NOT EXISTS files (
    scan_id INTEGER NOT NULL,
    dir_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    ext TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS files_dir ON files(scan_id, dir_id);
CREATE INDEX IF NOT EXISTS files_size ON files(scan_id, size);
CREATE TABLE IF NOT EXISTS hashes (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    partial TEXT,
    full TEXT
);
CREATE TABLE IF NOT EXISTS dup_groups (
    scan_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    hash TEXT NOT NULL,
    size INTEGER NOT NULL,
    path TEXT NOT NULL,
    mtime REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS dup_scan ON dup_groups(scan_id, group_id);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY,
    batch_id TEXT NOT NULL,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,          -- quarantine | restore | purge | error
    path TEXT NOT NULL,          -- original location
    stored_at TEXT,              -- location inside quarantine
    size INTEGER DEFAULT 0,
    reason TEXT,
    restored INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS actions_batch ON actions(batch_id);
CREATE TABLE IF NOT EXISTS similar_groups (
    scan_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    width INTEGER,
    height INTEGER,
    distance INTEGER
);
CREATE INDEX IF NOT EXISTS similar_scan ON similar_groups(scan_id, group_id);
CREATE TABLE IF NOT EXISTS image_hashes (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    dhash TEXT,
    width INTEGER,
    height INTEGER
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS startup_changes (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    item_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    original TEXT,              -- JSON describing how to restore it
    active INTEGER DEFAULT 1    -- 1 = currently disabled by us
);
"""

_local = threading.local()
_db_path: Path | None = None


def db_path() -> Path:
    global _db_path
    if _db_path is None:
        _db_path = paths.data_dir() / "cache.sqlite3"
    return _db_path


def connect() -> sqlite3.Connection:
    """One connection per thread; WAL lets the UI read while a scan writes."""
    conn = getattr(_local, "conn", None)
    if conn is None or getattr(_local, "path", None) != db_path():
        conn = sqlite3.connect(db_path(), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(SCHEMA)
        _local.conn = conn
        _local.path = db_path()
    return conn


def reset_for_tests(path: Path) -> None:
    global _db_path
    _db_path = path
    _local.conn = None


def get_setting(key: str, default=None):
    r = connect().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(key: str, value) -> None:
    conn = connect()
    conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
    conn.commit()
